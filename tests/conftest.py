"""Shared fixtures for GeoSphere Austria Next tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.geosphere_next import api
from custom_components.geosphere_next.const import CONF_HAS_NOWCAST, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"

LATITUDE = 48.2208
LONGITUDE = 16.3738

AROME_URL = re.compile(r".*/timeseries/forecast/nwp-v1-1h-2500m\?.*")
ENSEMBLE_URL = re.compile(r".*/timeseries/forecast/ensemble-v1-1h-2500m\?.*")
NOWCAST_URL = re.compile(r".*/timeseries/forecast/nowcast-v1-15min-1km\?.*")
INCA_URL = re.compile(r".*/timeseries/historical/inca-v1-1h-1km\?.*")
CHEM_URL = re.compile(r".*/timeseries/forecast/chem-v2-1h-3km\?.*")
CHEM_AQI_URL = re.compile(r".*/timeseries/forecast/chem_aqi-v1-1d-3km\?.*")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture(autouse=True)
def instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the API client's retry backoff for the whole suite.

    `GeoSphereApiClient` waits ~1-3 s between attempts, and every test that
    serves a 5xx or a connection error now exhausts `MAX_ATTEMPTS` before
    failing. Zeroing the base keeps the delay arithmetic intact (and still
    `await`s, so the loop is exercised) at no wall-clock cost. The one test
    that asserts on the delays restores a real base itself.
    """
    monkeypatch.setattr(api, "RETRY_BASE_DELAY", 0.0)


def mock_response(
    *, status: int = 200, json: dict | None = None, exc: Exception | None = None
) -> AiohttpClientMockResponse:
    """One canned response, for a single attempt of a retry sequence."""
    return AiohttpClientMockResponse(
        "get", AROME_URL, status=status, json=json, exc=exc
    )


def response_sequence(*responses: AiohttpClientMockResponse):
    """Serve a different response per request, repeating the last one.

    `AiohttpClientMocker` answers every request with the first registered
    match, so "fail, then succeed" cannot be expressed by registering two
    mocks. Its `side_effect` hook can: the coroutine's return value replaces
    the matched response on each call.
    """
    queue = list(responses)

    async def side_effect(method, url, data):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return side_effect


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def stormy_arome(
    *,
    indexes: tuple[int, ...] = (1,),
    cape: float = 1500.0,
    cin: float = 0.0,
    cloud: float | None = None,
    precipitation: float = 0.5,
) -> dict:
    """The recorded AROME fixture with a synthetic storm patched into it.

    SYNTHETIC, derived from `arome.json` — the recording peaks at 528 J/kg
    CAPE and so never crosses `THUNDER_CAPE_JKG`, which leaves every thunder
    "on" path untestable. `indexes` are into the fixture's 58 hourly stamps
    (1 = 2026-07-15T16:00Z, the in-progress hour at the tests' frozen clock).
    `cloud` optionally overrides `tcc` (0-1 scale) for those hours, which the
    dry-thunder branch of `derive_condition` requires.

    `precipitation` (mm) wets the storm hours, since `derive_condition` needs
    rain to reach `lightning-rainy`; pass 0.0 for a dry storm. `rr_acc` is
    accumulated since the run start and the delta at `index + 1` is the rain
    of the hour *starting* at `index`, so the series is raised from
    `index + 1` onward — which leaves every later hourly difference untouched.
    """
    payload = load_fixture("arome.json")
    parameters = payload["features"][0]["properties"]["parameters"]
    accumulated = parameters["rr_acc"]["data"]
    for index in indexes:
        parameters["cape"]["data"][index] = cape
        parameters["cin"]["data"][index] = cin
        if cloud is not None:
            parameters["tcc"]["data"][index] = cloud
        if precipitation:
            for later in range(index + 1, len(accumulated)):
                accumulated[later] += precipitation
    return payload


def wet_nowcast(
    *,
    precipitation_type: float = 1.0,
    rate_mm: float = 0.0,
) -> dict:
    """The recorded nowcast fixture with precipitation patched into it.

    SYNTHETIC, derived from `nowcast.json` — the recording is dry throughout
    (`pt` 255, `rr` 0.0), which leaves every "precipitating" path untestable.
    Both series are set for every bucket so the value matched at the frozen
    clock is wet regardless of which bucket that is. `rate_mm` is per 15-min
    bucket, so 0.1 mm is 0.4 mm/h.
    """
    payload = load_fixture("nowcast.json")
    parameters = payload["features"][0]["properties"]["parameters"]
    parameters["pt"]["data"] = [precipitation_type for _ in parameters["pt"]["data"]]
    parameters["rr"]["data"] = [rate_mm for _ in parameters["rr"]["data"]]
    return payload


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GeoSphere Next",
        unique_id=f"{LATITUDE:.4f}_{LONGITUDE:.4f}",
        data={
            CONF_LATITUDE: LATITUDE,
            CONF_LONGITUDE: LONGITUDE,
            CONF_HAS_NOWCAST: True,
        },
    )


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock the GeoSphere API with recorded fixture responses."""
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    aioclient_mock.get(CHEM_URL, json=load_fixture("chem.json"))
    aioclient_mock.get(CHEM_AQI_URL, json=load_fixture("chem_aqi.json"))
    return aioclient_mock
