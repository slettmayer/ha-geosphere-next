"""Tests for the sensor platform."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.const import CONF_FORECAST_INTERVAL

FROZEN_NOW = "2026-07-15T16:00:00+00:00"


def test_wind_sensors_are_natively_kmh() -> None:
    """Wind sensors carry km/h natively rather than relying on unit conversion."""
    from homeassistant.const import UnitOfSpeed

    from custom_components.geosphere_next.sensor import SENSORS

    by_key = {description.key: description for description in SENSORS}
    for key in ("wind_speed", "wind_gust_speed"):
        assert (
            by_key[key].native_unit_of_measurement == UnitOfSpeed.KILOMETERS_PER_HOUR
        ), key


def test_outlook_sensors_carry_no_state_class() -> None:
    """Forecast predictions must stay out of the recorder's long-term statistics."""
    from custom_components.geosphere_next.sensor import OUTLOOK_SENSORS

    for description in OUTLOOK_SENSORS:
        assert description.state_class is None, description.key


def test_current_condition_sensors_keep_their_state_class() -> None:
    """Genuine measurements are still statistics-worthy."""
    from homeassistant.components.sensor import SensorStateClass

    from custom_components.geosphere_next.sensor import SENSORS

    by_key = {description.key: description for description in SENSORS}
    for key in ("wind_speed", "wind_gust_speed", "cape", "cin"):
        assert by_key[key].state_class == SensorStateClass.MEASUREMENT, key


async def test_sensor_values(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Thermodynamic + wind values come from the INCA analysis (latest 15:00Z).
    expectations = {
        "sensor.geosphere_next_temperature": ("30.43", "°C"),
        "sensor.geosphere_next_dew_point": ("12.59", "°C"),
        "sensor.geosphere_next_pressure": ("1015.9", "hPa"),
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

    # INCA UU/VV-derived wind is not a round number; compare numerically.
    # HA's metric unit system converts wind speed to km/h (2.83 m/s).
    wind_speed = hass.states.get("sensor.geosphere_next_wind_speed")
    assert float(wind_speed.state) == pytest.approx(10.19, abs=0.01)
    assert wind_speed.attributes["unit_of_measurement"] == "km/h"
    wind_direction = hass.states.get("sensor.geosphere_next_wind_direction")
    assert float(wind_direction.state) == pytest.approx(1.8, abs=0.1)
    assert wind_direction.attributes["unit_of_measurement"] == "°"


async def test_diagnostic_sensors_disabled_by_default(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for key in ("cape", "cin", "precipitation_type", "weather_symbol"):
        entry = registry.async_get_entity_id(
            "sensor", "geosphere_next", f"{mock_config_entry.entry_id}-{key}"
        )
        assert entry is not None
        assert registry.async_get(entry).disabled_by is not None, key
    assert hass.states.get("sensor.geosphere_next_cape") is None


async def test_outlook_sensors(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    gust_1h = hass.states.get("sensor.geosphere_next_wind_gust_max_1h")
    assert float(gust_1h.state) == pytest.approx(38.65, abs=0.01)
    assert gust_1h.attributes["unit_of_measurement"] == "km/h"

    gust_12h = hass.states.get("sensor.geosphere_next_wind_gust_max_12h")
    assert float(gust_12h.state) == pytest.approx(38.65, abs=0.01)
    assert gust_12h.attributes["peak_time"] == "2026-07-15T16:00:00+00:00"

    # The recorded forecast never reaches the 1000 J/kg thunder threshold.
    assert hass.states.get("sensor.geosphere_next_next_thunderstorm").state == "unknown"


async def test_cape_max_is_diagnostic_and_disabled(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entry = registry.async_get_entity_id(
        "sensor", "geosphere_next", f"{mock_config_entry.entry_id}-cape_max_12h"
    )
    assert entry is not None
    assert registry.async_get(entry).disabled_by is not None
    assert hass.states.get("sensor.geosphere_next_cape_max_12h") is None


async def test_outlook_entity_ids_match_their_keys(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """Entity ids are derived from the translated name, so a rename can silently
    move them. Plan 2's templates address these by id — pin them."""
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for key in (
        "wind_gust_max_1h",
        "wind_gust_max_12h",
        "cape_max_12h",
        "next_thunderstorm",
    ):
        entry_id = registry.async_get_entity_id(
            "sensor", "geosphere_next", f"{mock_config_entry.entry_id}-{key}"
        )
        assert entry_id is not None, key
        assert entry_id == f"sensor.geosphere_next_{key}", key


async def test_outlook_gust_horizons_differ(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """A second clock where the 1 h and 12 h peaks are genuinely different.

    At the 16:00Z clock the fixture's peak gust sits in the in-progress hour,
    inside both windows — so swapping the two horizons would go unnoticed.
    At 2026-07-16T04:00Z the 1 h window (04:00-05:00) peaks at 3.314 m/s
    (11.93 km/h) while the 12 h window peaks at 6.030 m/s (21.71 km/h) in the
    13:00Z hour.
    """
    freezer.move_to("2026-07-16T04:00:00+00:00")
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    gust_1h = hass.states.get("sensor.geosphere_next_wind_gust_max_1h")
    assert float(gust_1h.state) == pytest.approx(11.93, abs=0.01)

    gust_12h = hass.states.get("sensor.geosphere_next_wind_gust_max_12h")
    assert float(gust_12h.state) == pytest.approx(21.71, abs=0.01)
    assert gust_12h.attributes["peak_time"] == "2026-07-16T13:00:00+00:00"


async def test_outlook_window_re_evaluates_on_the_hour(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The window must follow the clock, not only coordinator refreshes."""
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    # The longest allowed forecast interval: no data refresh within the hour.
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_FORECAST_INTERVAL: 180}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    def arome_calls() -> int:
        return sum("nwp-v1-1h-2500m" in str(call[1]) for call in mock_api.mock_calls)

    baseline = arome_calls()
    gust_1h = hass.states.get("sensor.geosphere_next_wind_gust_max_1h")
    assert float(gust_1h.state) == pytest.approx(38.65, abs=0.01)

    # The 16:00Z hour has elapsed; the window is now 17:00-18:00 (6.203 m/s).
    freezer.move_to("2026-07-15T17:00:05+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    gust_1h = hass.states.get("sensor.geosphere_next_wind_gust_max_1h")
    assert float(gust_1h.state) == pytest.approx(22.33, abs=0.01)
    # ...and no forecast fetch happened in between.
    assert arome_calls() == baseline
