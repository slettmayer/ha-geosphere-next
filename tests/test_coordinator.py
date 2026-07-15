"""Tests for coordinator processing via a full config-entry setup."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

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
    # first future hour is 17:00Z (index 2); indices 0-1 are skipped/past.
    assert len(data.hourly) == 56
    first = data.hourly[0]
    assert first.datetime.isoformat() == "2026-07-15T17:00:00+00:00"
    assert first.temperature == 28.1
    # rr_acc[2] - rr_acc[1] = 0.479 - 0.479
    assert first.precipitation == 0.0
    # tcc 0.0 -> 0 %, 19:00 local in July is daytime
    assert first.cloud_coverage == 0
    assert first.condition == "sunny"
    # Only the two full local days (Jul 16, Jul 17) survive aggregation.
    assert len(data.daily) == 2
    assert data.snow_limit == pytest.approx(3401.2)
    assert data.current is first


async def test_current_merge(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.current.data

    # Nowcast timestamp closest to 16:00Z is 16:00Z (index 1).
    assert data.temperature == 29.74
    # INCA latest values (15:00Z): P0 101585.83 Pa -> hPa, GL W/m2.
    assert data.pressure_hpa == pytest.approx(1015.9)
    assert data.global_radiation == pytest.approx(248.94)
    assert data.precipitation_1h == 0.0
    assert data.is_precipitating is False
    # Cloud cover comes from the AROME fallback (nowcast has none): 0 %.
    assert data.cloud_coverage == 0
    assert data.condition == "sunny"
    assert data.apparent_temperature is not None
    assert data.wind_bearing == pytest.approx(345.2)


async def test_nowcast_failure_falls_back_to_inca(
    hass: HomeAssistant, mock_config_entry, freezer: FrozenDateTimeFactory
) -> None:
    """When the nowcast errors, INCA values fill the current conditions."""
    import re

    from aioresponses import aioresponses

    from .conftest import AROME_URL, INCA_URL, load_fixture

    freezer.move_to(FROZEN_NOW)
    with aioresponses() as mocked:
        mocked.get(AROME_URL, payload=load_fixture("arome.json"), repeat=True)
        mocked.get(
            re.compile(r".*/timeseries/forecast/nowcast-v1-15min-1km\?.*"),
            status=500,
            repeat=True,
        )
        mocked.get(INCA_URL, payload=load_fixture("inca.json"), repeat=True)
        await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # INCA T2M latest (15:00Z)
    assert data.temperature == 30.43
    assert data.pressure_hpa == pytest.approx(1015.9)
    # Gusts fall back to AROME.
    assert data.wind_gust_speed is not None
