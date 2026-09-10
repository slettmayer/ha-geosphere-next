"""Tests for the binary sensor platform."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.const import (
    CONF_FORECAST_INTERVAL,
    CONF_HAS_NOWCAST,
    DOMAIN,
)

from .conftest import (
    AROME_URL,
    ENSEMBLE_URL,
    INCA_URL,
    NOWCAST_URL,
    load_fixture,
    stormy_arome,
    wet_nowcast,
)

FROZEN_NOW = "2026-07-15T16:00:00+00:00"
ENTITY_ID = "binary_sensor.geosphere_next_thunderstorm_expected_next_hour"
PRECIPITATING_ENTITY_ID = "binary_sensor.geosphere_next_precipitating"


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


async def test_precipitating_is_off_for_a_dry_analysis(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """The recorded fixtures are dry: `pt` 255 and no measurable rate."""
    freezer.move_to(FROZEN_NOW)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(PRECIPITATING_ENTITY_ID)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["device_class"] == "moisture"


async def test_precipitating_is_on_from_the_nowcast_code(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A `pt` code other than 255 turns it on with no measurable rate."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=wet_nowcast(rate_mm=0.0))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(PRECIPITATING_ENTITY_ID)
    assert state is not None
    assert state.state == "on"


async def test_precipitating_is_on_from_the_rate_alone(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The rate alone carries it: a dry `pt` 255 must not veto observed rain.

    Note this is *not* the no-coverage path — that one has no rate either
    (see `test_precipitating_is_unknown_without_nowcast_coverage`). It is a
    dry `pt` code alongside real rain, proving neither source vetoes the other.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(
        NOWCAST_URL, json=wet_nowcast(precipitation_type=255.0, rate_mm=0.5)
    )
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(PRECIPITATING_ENTITY_ID)
    assert state is not None
    assert state.state == "on"


async def test_precipitating_is_unknown_without_nowcast_coverage(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No observation of precipitation at all must not render as a dry "off".

    `CONF_HAS_NOWCAST` false skips the nowcast *and* INCA — they share the
    Austrian grid (`GeoSphereCurrentCoordinator._async_get_inca`) — so there
    is neither a `pt` code nor an observed rate, and any answer here would be
    invented. AROME still supplies the rest of the current conditions, so the
    entity exists; it just has nothing to say. Matches the sibling
    `precipitation_1h`, which reports `unknown` under exactly this setup.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GeoSphere Next",
        unique_id="47.0000_9.0000",
        data={
            CONF_LATITUDE: 47.0,
            CONF_LONGITUDE: 9.0,
            CONF_HAS_NOWCAST: False,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(PRECIPITATING_ENTITY_ID)
    assert state is not None
    assert state.state == "unknown"
    # The sibling it has to stay consistent with.
    assert hass.states.get("sensor.geosphere_next_precipitation_last_hour").state == (
        "unknown"
    )


async def test_precipitating_is_on_from_inca_when_the_nowcast_fetch_fails(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The real rate-only path: nowcast down, `pt` absent, INCA `RR` wet.

    This is what the observed-rate half of `condition.is_precipitating`
    actually buys — a transient nowcast outage inside the grid, not a point
    outside it (that case has no rate either, see the test above).
    """
    freezer.move_to(FROZEN_NOW)
    inca = load_fixture("inca.json")
    inca["features"][0]["properties"]["parameters"]["RR"]["data"][-1] = 2.4
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, exc=TimeoutError)
    aioclient_mock.get(INCA_URL, json=inca)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(PRECIPITATING_ENTITY_ID)
    assert state is not None
    assert state.state == "on"
