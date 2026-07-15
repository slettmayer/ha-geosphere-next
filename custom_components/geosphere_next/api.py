"""Async client for the GeoSphere Austria Dataset API.

This module (together with models.py) is deliberately free of any
homeassistant imports so it can be extracted into a standalone PyPI
package later.
"""

from __future__ import annotations

import contextlib
from datetime import datetime

import aiohttp

from .models import GeoSphereResponse, ParameterSeries

API_BASE_URL = "https://dataset.api.hub.geosphere.at/v1"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class GeoSphereApiError(Exception):
    """Base error talking to the GeoSphere API."""


class GeoSphereConnectionError(GeoSphereApiError):
    """Network-level failure."""


class GeoSphereRateLimitError(GeoSphereApiError):
    """HTTP 429 — request budget exceeded (5 req/s, 240 req/h)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GeoSphereOutOfDomainError(GeoSphereApiError):
    """Requested point lies outside the dataset's grid bounds."""


class GeoSphereApiClient:
    """Minimal typed client for GeoSphere timeseries endpoints."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str = API_BASE_URL
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    async def get_timeseries(
        self,
        mode: str,
        resource_id: str,
        parameters: tuple[str, ...],
        latitude: float,
        longitude: float,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GeoSphereResponse:
        """Fetch a point timeseries and parse the GeoJSON response."""
        url = f"{self._base_url}/timeseries/{mode}/{resource_id}"
        query: dict[str, str] = {
            "parameters": ",".join(parameters),
            "lat_lon": f"{latitude},{longitude}",
            "output_format": "geojson",
        }
        if start is not None:
            query["start"] = start.strftime("%Y-%m-%dT%H:%M")
        if end is not None:
            query["end"] = end.strftime("%Y-%m-%dT%H:%M")

        try:
            async with self._session.get(
                url, params=query, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 429:
                    retry_after = resp.headers.get("Retry-After")
                    raise GeoSphereRateLimitError(
                        "GeoSphere API rate limit exceeded",
                        retry_after=float(retry_after) if retry_after else None,
                    )
                if resp.status == 400:
                    detail = ""
                    with contextlib.suppress(aiohttp.ClientError, ValueError):
                        detail = str((await resp.json()).get("detail", ""))
                    if "outside of dataset bounds" in detail:
                        raise GeoSphereOutOfDomainError(detail)
                    raise GeoSphereApiError(
                        f"GeoSphere API rejected the request: {detail or resp.status}"
                    )
                if resp.status >= 400:
                    raise GeoSphereApiError(
                        f"GeoSphere API returned HTTP {resp.status} for {resource_id}"
                    )
                body = await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise GeoSphereConnectionError(
                f"Error connecting to the GeoSphere API: {err}"
            ) from err

        return _parse_geojson(resource_id, body)


def _parse_geojson(resource_id: str, body: dict) -> GeoSphereResponse:
    """Parse the verified GeoJSON timeseries shape into a typed response."""
    try:
        feature = body["features"][0]
        raw_parameters = feature["properties"]["parameters"]
        parameters = {
            name: ParameterSeries(
                name=name,
                unit=str(param.get("unit", "")),
                data=list(param["data"]),
            )
            for name, param in raw_parameters.items()
        }
        reference_time = (
            datetime.fromisoformat(body["reference_time"])
            if body.get("reference_time")
            else None
        )
        return GeoSphereResponse(
            resource_id=resource_id,
            reference_time=reference_time,
            timestamps=[datetime.fromisoformat(ts) for ts in body["timestamps"]],
            parameters=parameters,
            grid_longitude=float(feature["geometry"]["coordinates"][0]),
            grid_latitude=float(feature["geometry"]["coordinates"][1]),
        )
    except (KeyError, IndexError, TypeError, ValueError) as err:
        raise GeoSphereApiError(
            f"Unexpected GeoSphere API response shape for {resource_id}: {err}"
        ) from err
