"""Tests for the GeoSphere API client."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.api import (
    GeoSphereApiClient,
    GeoSphereApiError,
    GeoSphereOutOfDomainError,
    GeoSphereRateLimitError,
)

from .conftest import AROME_URL, load_fixture


@pytest.fixture
async def api_session(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[aiohttp.ClientSession]:
    """A client session routed through the aiohttp mocker."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield session
    await session.close()


async def test_parse_arome_response(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    client = GeoSphereApiClient(api_session)
    response = await client.get_timeseries(
        "forecast",
        "nwp-v1-1h-2500m",
        parameters=("t2m", "tcc"),
        latitude=48.2208,
        longitude=16.3738,
    )

    assert response.reference_time is not None
    assert response.reference_time.isoformat() == "2026-07-15T12:00:00+00:00"
    assert len(response.timestamps) == 58
    assert response.grid_latitude == pytest.approx(48.219, abs=0.001)
    assert response.value_at("t2m", 0) is not None
    assert response.parameters["tcc"].unit == "1"
    # Unknown parameter degrades to a None series, not a KeyError.
    assert response.value_at("nonexistent", 0) is None


async def test_out_of_domain_error(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(
        AROME_URL,
        status=400,
        json=load_fixture("arome_out_of_domain.json"),
    )
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereOutOfDomainError):
        await client.get_timeseries(
            "forecast",
            "nwp-v1-1h-2500m",
            parameters=("t2m",),
            latitude=52.52,
            longitude=13.405,
        )


async def test_rate_limit_error(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(AROME_URL, status=429, headers={"Retry-After": "120"})
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereRateLimitError) as err:
        await client.get_timeseries(
            "forecast",
            "nwp-v1-1h-2500m",
            parameters=("t2m",),
            latitude=48.0,
            longitude=16.0,
        )
    assert err.value.retry_after == 120.0


async def test_unexpected_shape_raises_api_error(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(AROME_URL, json={"features": []})
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereApiError):
        await client.get_timeseries(
            "forecast",
            "nwp-v1-1h-2500m",
            parameters=("t2m",),
            latitude=48.0,
            longitude=16.0,
        )
