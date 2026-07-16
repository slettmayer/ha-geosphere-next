"""Tests for coordinator processing via a full config-entry setup."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .conftest import AROME_URL, ENSEMBLE_URL, INCA_URL, NOWCAST_URL, load_fixture

FROZEN_NOW = "2026-07-15T16:00:00+00:00"


async def _setup(hass: HomeAssistant, entry) -> None:
    # Daily aggregation groups by HA's local calendar day.
    await hass.config.async_set_time_zone("Europe/Vienna")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_forecast_processing(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.forecast.data

    # Fixture: reference 12:00Z, timestamps 15:00Z..+60h. At frozen 16:00Z the
    # forecast starts at the in-progress hour 16:00Z (index 1); index 0 (15:00Z)
    # is dropped since accumulated params have no predecessor to difference.
    assert len(data.hourly) == 57
    first = data.hourly[0]
    assert first.datetime.isoformat() == "2026-07-15T16:00:00+00:00"
    assert first.temperature == 28.6
    # rr_acc[1] - rr_acc[0] = 0.479 - 0.0
    assert first.precipitation == 0.48
    assert first.condition == "rainy"
    # tcc 0.0 -> 0 %
    assert first.cloud_coverage == 0
    # Magnus from t2m 28.6 / rh2m 50.1.
    assert first.dew_point == pytest.approx(17.2)
    assert data.snow_limit == pytest.approx(3371.9)
    assert data.current is first

    # Stepped probability from the ensemble rr percentiles (fixture hours):
    # all wet / median wet / only p90 wet / all dry / p90 below threshold.
    assert first.precipitation_probability == 95
    assert data.hourly[1].precipitation_probability == 70
    assert data.hourly[2].precipitation_probability == 30
    assert data.hourly[3].precipitation_probability == 0
    assert data.hourly[4].precipitation_probability == 0
    # Last fixture hour has null percentiles -> no probability.
    assert data.hourly[-1].precipitation_probability is None


async def test_ensemble_failure_omits_probability(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failing ensemble endpoint must not take the forecast down."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, status=500)
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.forecast.data
    assert len(data.hourly) == 57
    assert all(hour.precipitation_probability is None for hour in data.hourly)


async def test_current_merge(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.current.data

    # Thermodynamic fields and wind prefer the INCA analysis (latest 15:00Z)
    # over the nowcast, which lags diurnal ramps by ~2 h.
    assert data.temperature == 30.43
    assert data.humidity == pytest.approx(33.53)
    assert data.dew_point == pytest.approx(12.59)
    # INCA UU -0.09 / VV -2.83 -> wind from just east of north.
    assert data.wind_speed == pytest.approx(2.83, abs=0.01)
    assert data.wind_bearing == pytest.approx(1.8, abs=0.1)
    # INCA latest values (15:00Z): P0 101585.83 Pa -> hPa, GL W/m2.
    assert data.pressure_hpa == pytest.approx(1015.9)
    assert data.global_radiation == pytest.approx(248.94)
    assert data.precipitation_1h == 0.0
    assert data.is_precipitating is False
    # Cloud cover comes from the AROME fallback (nowcast has none): 0 %.
    assert data.cloud_coverage == 0
    assert data.condition == "sunny"
    assert data.apparent_temperature is not None


async def test_nowcast_failure_falls_back_to_inca(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the nowcast errors, INCA values fill the current conditions."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, status=500)
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # INCA T2M latest (15:00Z)
    assert data.temperature == 30.43
    assert data.pressure_hpa == pytest.approx(1015.9)
    # Gusts fall back to AROME.
    assert data.wind_gust_speed is not None


async def test_inca_failure_falls_back_to_nowcast(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When INCA errors, the nowcast fills the thermodynamic fields."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, status=500)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # Nowcast timestamp closest to 16:00Z.
    assert data.temperature == 29.74
    assert data.wind_bearing == pytest.approx(345.2)
    # INCA-only fields stay empty.
    assert data.pressure_hpa is None
    assert data.global_radiation is None


async def test_inca_refresh_keyed_on_data_age(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """INCA refetches when its newest analysis ages out, not on a fetch timer."""
    # Fixture's latest INCA analysis is 15:00Z: fresh at 15:30Z (30 min old).
    freezer.move_to("2026-07-15T15:30:00+00:00")
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.current

    def inca_calls() -> int:
        return sum("inca-v1-1h-1km" in str(call[1]) for call in mock_api.mock_calls)

    baseline = inca_calls()
    assert baseline == 1

    # Still fresh: the next update reuses the cached slice.
    await coordinator.async_refresh()
    assert inca_calls() == baseline

    # 16:10Z: the 15:00Z analysis is 70 min old -> stale, refetch.
    freezer.tick(timedelta(minutes=40))
    await coordinator.async_refresh()
    assert inca_calls() == baseline + 1
