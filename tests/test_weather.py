"""Tests for the weather entity."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import weather
from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
    SERVICE_GET_FORECASTS,
    WeatherEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.const import CONF_FORECAST_INTERVAL

ENTITY_ID = "weather.geosphere_next"
FROZEN_NOW = "2026-07-15T16:00:00+00:00"


async def _setup(hass: HomeAssistant, entry) -> None:
    # Daily aggregation groups by HA's local calendar day.
    await hass.config.async_set_time_zone("Europe/Vienna")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_weather_state(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "sunny"
    # INCA analysis value, rounded display precision.
    assert state.attributes["temperature"] == 30.4
    assert state.attributes["humidity"] is not None
    assert state.attributes["pressure"] == 1015.9
    assert "GeoSphere Austria" in state.attributes["attribution"]
    # Hourly only: AROME's ~60 h horizon yields at most 2-3 aggregable days,
    # and the HA frontend needs >2 forecast entries to render — a daily tab
    # would intermittently spin forever.
    assert (
        state.attributes["supported_features"] == WeatherEntityFeature.FORECAST_HOURLY
    )


async def test_get_forecasts_hourly(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)

    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {"entity_id": ENTITY_ID, "type": "hourly"},
        blocking=True,
        return_response=True,
    )
    forecast = response[ENTITY_ID]["forecast"]
    assert len(forecast) == 56
    assert forecast[0]["temperature"] is not None
    assert forecast[0]["condition"] is not None

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            WEATHER_DOMAIN,
            SERVICE_GET_FORECASTS,
            {"entity_id": ENTITY_ID, "type": "daily"},
            blocking=True,
            return_response=True,
        )

    hourly = (
        await hass.services.async_call(
            WEATHER_DOMAIN,
            SERVICE_GET_FORECASTS,
            {"entity_id": ENTITY_ID, "type": "hourly"},
            blocking=True,
            return_response=True,
        )
    )[ENTITY_ID]["forecast"]
    assert hourly[0]["datetime"] == "2026-07-15T16:00:00+00:00"
    # Dry: the fixture's 0.479 mm accumulated between 15:00Z and 16:00Z, so it
    # belongs to the hour that has already elapsed, not the one starting here.
    assert hourly[0]["precipitation"] == 0.0
    # Ensemble fixture: all percentiles wet at 16:00Z -> stepped PoP 95 %.
    assert hourly[0]["precipitation_probability"] == 95
    # Magnus dew point from t2m 28.6 / rh2m 50.1 (service output is converted,
    # so the key is dew_point, not native_dew_point).
    assert hourly[0]["dew_point"] == 17.2


async def _get_hourly_forecast(hass: HomeAssistant) -> list[dict]:
    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {"entity_id": ENTITY_ID, "type": "hourly"},
        blocking=True,
        return_response=True,
    )
    return response[ENTITY_ID]["forecast"]


async def test_get_forecasts_hourly_filters_stale_leading_hours(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Between refreshes, elapsed hours must not leak into the returned list."""
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    # The longest allowed forecast interval: guarantees no refetch below.
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_FORECAST_INTERVAL: 180}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    def arome_calls() -> int:
        return sum("nwp-v1-1h-2500m" in str(call[1]) for call in mock_api.mock_calls)

    baseline_calls = arome_calls()
    baseline_forecast = await _get_hourly_forecast(hass)

    # 2h05 later, well inside the 180-min interval, so the coordinator's raw
    # list is unchanged and still starts at the now-elapsed 16:00Z hour.
    freezer.move_to("2026-07-15T18:05:00+00:00")
    forecast = await _get_hourly_forecast(hass)

    assert forecast[0]["datetime"] == "2026-07-15T18:00:00+00:00"
    assert all(hour["datetime"] >= "2026-07-15T18:00:00+00:00" for hour in forecast)
    assert len(forecast) == len(baseline_forecast) - 2
    # ...and no forecast fetch happened in between.
    assert arome_calls() == baseline_calls


async def test_get_forecasts_hourly_keeps_the_in_progress_hour(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The in-progress hour is stamped earlier than `now` and must survive.

    A naive `>= now` filter would drop it; the correct floor is the top of
    the current hour (`start`), matching `outlook._window`.
    """
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_FORECAST_INTERVAL: 180}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Still within the 16:00Z hour, but `now` (16:45) is later than the
    # in-progress hour's own 16:00 stamp.
    freezer.move_to("2026-07-15T16:45:00+00:00")
    forecast = await _get_hourly_forecast(hass)

    assert forecast[0]["datetime"] == "2026-07-15T16:00:00+00:00"


async def test_hourly_forecast_subscribers_are_updated_on_hour_boundary(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The hour-boundary tick must push a re-filtered list to subscribers.

    `async_write_ha_state()` alone would not reach a `subscribe_forecast`
    listener; the entity must call `async_update_listeners()` instead.
    Subscribes directly against the entity object (bypassing the websocket
    auth layer, which does not mix well with a freezer that moves the clock
    backwards relative to the token's real-time `iat`).
    """
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_FORECAST_INTERVAL: 180}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity = hass.data[weather.DATA_COMPONENT].get_entity(ENTITY_ID)
    assert entity is not None

    pushes: list[list[dict] | None] = []
    entity.async_subscribe_forecast("hourly", pushes.append)

    # Cross the hour boundary; the mixin's tracker fires at hh:00:05.
    freezer.move_to("2026-07-15T17:00:05+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert pushes
    latest = pushes[-1]
    assert latest is not None
    assert latest[0]["datetime"] == "2026-07-15T17:00:00+00:00"
