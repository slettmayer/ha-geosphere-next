"""Tests for the GeoSphere API client."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.geosphere_next.api import (
    GeoSphereApiClient,
    GeoSphereApiError,
    GeoSphereOutOfDomainError,
    GeoSphereRateLimitError,
)

from .conftest import AROME_URL, load_fixture


async def test_parse_arome_response() -> None:
    async with aiohttp.ClientSession() as session:
        client = GeoSphereApiClient(session)
        with aioresponses() as mocked:
            mocked.get(AROME_URL, payload=load_fixture("arome.json"))
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


async def test_out_of_domain_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = GeoSphereApiClient(session)
        with aioresponses() as mocked:
            mocked.get(
                AROME_URL,
                status=400,
                payload=load_fixture("arome_out_of_domain.json"),
            )
            with pytest.raises(GeoSphereOutOfDomainError):
                await client.get_timeseries(
                    "forecast",
                    "nwp-v1-1h-2500m",
                    parameters=("t2m",),
                    latitude=52.52,
                    longitude=13.405,
                )


async def test_rate_limit_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = GeoSphereApiClient(session)
        with aioresponses() as mocked:
            mocked.get(AROME_URL, status=429, headers={"Retry-After": "120"})
            with pytest.raises(GeoSphereRateLimitError) as err:
                await client.get_timeseries(
                    "forecast",
                    "nwp-v1-1h-2500m",
                    parameters=("t2m",),
                    latitude=48.0,
                    longitude=16.0,
                )
    assert err.value.retry_after == 120.0


async def test_unexpected_shape_raises_api_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = GeoSphereApiClient(session)
        with aioresponses() as mocked:
            mocked.get(AROME_URL, payload={"features": []})
            with pytest.raises(GeoSphereApiError):
                await client.get_timeseries(
                    "forecast",
                    "nwp-v1-1h-2500m",
                    parameters=("t2m",),
                    latitude=48.0,
                    longitude=16.0,
                )
