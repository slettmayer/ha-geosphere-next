"""Tests for the sensor platform."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

FROZEN_NOW = "2026-07-15T16:00:00+00:00"


async def test_sensor_values(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    expectations = {
        "sensor.geosphere_next_temperature": ("29.74", "°C"),
        "sensor.geosphere_next_dew_point": ("13.04", "°C"),
        "sensor.geosphere_next_pressure": ("1015.9", "hPa"),
        # HA's metric unit system converts wind speed to km/h (2.1 m/s).
        "sensor.geosphere_next_wind_speed": ("7.56", "km/h"),
        "sensor.geosphere_next_wind_direction": ("345.2", "°"),
        "sensor.geosphere_next_global_radiation": ("248.94", "W/m²"),
        "sensor.geosphere_next_condition": ("sunny", None),
        "sensor.geosphere_next_precipitation_last_hour": ("0.0", "mm"),
    }
    for entity_id, (value, unit) in expectations.items():
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} missing"
        assert state.state == value, f"{entity_id}: {state.state} != {value}"
        if unit is not None:
            assert state.attributes["unit_of_measurement"] == unit


async def test_diagnostic_sensors_disabled_by_default(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for key in ("cape", "precipitation_type", "weather_symbol"):
        entry = registry.async_get_entity_id(
            "sensor", "geosphere_next", f"{mock_config_entry.entry_id}-{key}"
        )
        assert entry is not None
        assert registry.async_get(entry).disabled_by is not None, key
    assert hass.states.get("sensor.geosphere_next_cape") is None
