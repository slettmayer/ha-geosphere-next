"""Tests for the optional air-quality sensors."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONF_LATITUDE,
    CONF_LONGITUDE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.const import (
    CONF_AIR_QUALITY,
    CONF_HAS_NOWCAST,
    DOMAIN,
)

from .conftest import (
    AROME_URL,
    CHEM_AQI_URL,
    CHEM_URL,
    ENSEMBLE_URL,
    INCA_URL,
    LATITUDE,
    LONGITUDE,
    NOWCAST_URL,
    load_fixture,
)

FROZEN_NOW = "2026-07-15T16:00:00+00:00"

POLLUTANT_ENTITY_IDS = (
    "sensor.geosphere_next_nitrogen_dioxide",
    "sensor.geosphere_next_ozone",
    "sensor.geosphere_next_pm10",
    "sensor.geosphere_next_pm2_5",
)
AQI_ENTITY_ID = "sensor.geosphere_next_air_quality_index"


@pytest.fixture
def aq_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GeoSphere Next",
        unique_id=f"{LATITUDE:.4f}_{LONGITUDE:.4f}",
        data={
            CONF_LATITUDE: LATITUDE,
            CONF_LONGITUDE: LONGITUDE,
            CONF_HAS_NOWCAST: True,
        },
        options={CONF_AIR_QUALITY: True},
    )


async def _setup(hass: HomeAssistant, entry) -> None:
    await hass.config.async_set_time_zone("Europe/Vienna")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_disabled_by_default(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """Without the option, no air-quality sensors exist and no chem calls run."""
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    for entity_id in (*POLLUTANT_ENTITY_IDS, AQI_ENTITY_ID):
        assert hass.states.get(entity_id) is None
    assert not any("chem" in str(call[1]) for call in mock_api.mock_calls)


async def test_air_quality_sensors(
    hass: HomeAssistant, aq_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """With the option on, pollutant + AQI sensors publish the fixture values."""
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, aq_config_entry)
    assert aq_config_entry.state is ConfigEntryState.LOADED

    # Values at the timestamp closest to frozen now (16:00Z, index 1).
    expectations = {
        "sensor.geosphere_next_nitrogen_dioxide": "4.7",
        "sensor.geosphere_next_ozone": "122.5",
        "sensor.geosphere_next_pm10": "7.5",
        "sensor.geosphere_next_pm2_5": "4.9",
    }
    for entity_id, value in expectations.items():
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} missing"
        assert state.state == value, f"{entity_id}: {state.state} != {value}"
        assert (
            state.attributes["unit_of_measurement"]
            == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
        )
        forecast = state.attributes["forecast"]
        assert len(forecast) == 8
        assert forecast[0]["datetime"] == "2026-07-15T15:00:00+00:00"
        assert forecast[0]["value"] is not None

    aqi = hass.states.get(AQI_ENTITY_ID)
    assert aqi is not None
    # 2026-07-15T00:00Z is local (Vienna) July 15 -> today.
    assert aqi.state == "4"
    assert aqi.attributes["today"] == 4
    assert aqi.attributes["tomorrow"] == 3
    assert aqi.attributes["in_2_days"] == 2


async def test_chem_failure_retries_setup(
    hass: HomeAssistant,
    aq_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failing chem endpoint puts the entry into setup retry."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    aioclient_mock.get(CHEM_URL, status=500)
    aioclient_mock.get(CHEM_AQI_URL, json=load_fixture("chem_aqi.json"))

    await hass.config.async_set_time_zone("Europe/Vienna")
    aq_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(aq_config_entry.entry_id)
    assert aq_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_aqi_failure_keeps_pollutants(
    hass: HomeAssistant,
    aq_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failing AQI endpoint must not take the pollutant sensors down."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    aioclient_mock.get(CHEM_URL, json=load_fixture("chem.json"))
    aioclient_mock.get(CHEM_AQI_URL, status=500)
    await _setup(hass, aq_config_entry)
    assert aq_config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.geosphere_next_ozone").state == "122.5"
    assert hass.states.get(AQI_ENTITY_ID).state == "unknown"


async def test_disabling_option_removes_entities(
    hass: HomeAssistant, aq_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """Switching the option off cleans the air-quality entities from the registry."""
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, aq_config_entry)
    registry = er.async_get(hass)
    assert registry.async_get(AQI_ENTITY_ID) is not None

    hass.config_entries.async_update_entry(aq_config_entry, options={})
    await hass.config_entries.async_reload(aq_config_entry.entry_id)
    await hass.async_block_till_done()

    assert aq_config_entry.state is ConfigEntryState.LOADED
    for entity_id in (*POLLUTANT_ENTITY_IDS, AQI_ENTITY_ID):
        assert registry.async_get(entity_id) is None
