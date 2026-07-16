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
)

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


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


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
