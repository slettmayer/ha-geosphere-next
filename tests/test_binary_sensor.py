"""Tests for the binary sensor platform."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.const import CONF_FORECAST_INTERVAL

from .conftest import (
    AROME_URL,
    ENSEMBLE_URL,
    INCA_URL,
    NOWCAST_URL,
    load_fixture,
    stormy_arome,
)

FROZEN_NOW = "2026-07-15T16:00:00+00:00"
ENTITY_ID = "binary_sensor.geosphere_next_thunderstorm_expected_next_hour"


def _mock_api_with(aioclient_mock: AiohttpClientMocker, arome: dict) -> None:
    """Serve a patched AROME payload alongside the recorded companions."""
    aioclient_mock.get(AROME_URL, json=arome)
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))


async def test_thunderstorm_expected_is_off_for_a_calm_forecast(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """The recorded fixture never reaches the thunder threshold."""
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "off"


async def test_thunderstorm_expected_is_on_for_a_stormy_forecast(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The `on` path: CAPE above the threshold with weak inhibition and rain.

    `stormy_arome` wets hour 1 of the fixture (16:00Z, the in-progress hour),
    so raising its CAPE makes it `lightning-rainy`.
    """
    freezer.move_to(FROZEN_NOW)
    _mock_api_with(aioclient_mock, stormy_arome(indexes=(1,)))
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == "on"


async def test_thunderstorm_expected_re_evaluates_on_the_hour(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The window must follow the clock, not only coordinator refreshes.

    The storm sits at 18:00Z, outside the 16:00Z window (16:00-17:00) but
    inside the 17:00Z one (17:00-18:00).
    """
    freezer.move_to(FROZEN_NOW)
    # Dry hour, so the condition needs full cloud to read as `lightning`.
    _mock_api_with(
        aioclient_mock, stormy_arome(indexes=(3,), cloud=1.0, precipitation=0.0)
    )
    mock_config_entry.add_to_hass(hass)
    # The longest allowed forecast interval: no data refresh within the hour.
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_FORECAST_INTERVAL: 180}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == "off"

    freezer.move_to("2026-07-15T17:00:05+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == "on"
