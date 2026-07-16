"""Tests for the weather entity."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
    SERVICE_GET_FORECASTS,
    WeatherEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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
    assert state.attributes["temperature"] == 29.7  # rounded display precision
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
    assert len(forecast) == 57
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
    assert hourly[0]["precipitation"] == 0.48
    # Magnus dew point from t2m 28.6 / rh2m 50.1 (service output is converted,
    # so the key is dew_point, not native_dew_point).
    assert hourly[0]["dew_point"] == 17.2
