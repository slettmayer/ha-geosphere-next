"""Tests for the binary sensor platform."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

FROZEN_NOW = "2026-07-15T16:00:00+00:00"


async def test_thunderstorm_expected_is_off_for_a_calm_forecast(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """The recorded fixture never reaches the thunder threshold."""
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(
        "binary_sensor.geosphere_next_thunderstorm_expected_next_hour"
    )
    assert state is not None
    assert state.state == "off"
