"""Async client for the GeoSphere Austria Dataset API.

This module (together with models.py) is deliberately free of any
homeassistant imports so it can be extracted into a standalone PyPI
package later.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from datetime import UTC, datetime

import aiohttp

from .models import GeoSphereResponse, ParameterSeries

API_BASE_URL = "https://dataset.api.hub.geosphere.at/v1"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Retry budget for transient faults. The nowcast endpoint in particular
# answers with a bare 502 or drops the connection often enough to matter --
# 11 502s and ~35 connection failures across five days of one installation's
# log -- and every one of them used to cost a whole poll interval (15 min by
# default) of `unknown` on the entities that have no second source. The
# observed faults clear on the next request, so three attempts is ample;
# anything longer-lived is a real outage that a retry cannot paper over.
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0
# Fraction of the delay to spread it by, in both directions. The three
# coordinators poll on schedules that coincide, so an unjittered backoff
# would retry them in lockstep against a 5 req/s budget, turning one 502
# into a burst.
RETRY_JITTER = 0.5


def _backoff_delay(attempt: int) -> float:
    """Seconds to wait after a failed `attempt`, doubling each time."""
    delay = RETRY_BASE_DELAY * 2 ** (attempt - 1)
    return delay * (1 + random.uniform(-RETRY_JITTER, RETRY_JITTER))


def _stamp(when: datetime) -> str:
    """Serialize a bound for the API, which reads naive stamps as UTC.

    An aware datetime is converted to UTC first: formatting it directly would
    drop the offset and turn, say, `14:00+02:00` into a request for `14:00Z` --
    a window two hours off what the caller asked for. Naive values are assumed
    to already be UTC, matching the API's own reading.
    """
    if when.tzinfo is not None:
        when = when.astimezone(UTC)
    return when.strftime("%Y-%m-%dT%H:%M")


class GeoSphereApiError(Exception):
    """Base error talking to the GeoSphere API."""


class GeoSphereTransientError(GeoSphereApiError):
    """A fault worth retrying: the request was fine, the answer never came.

    The retry policy lives in the hierarchy rather than in a tuple at the
    call site, so adding a failure mode means deciding where it belongs
    instead of remembering to extend a list. Everything outside this branch
    -- a 429, a 4xx, a body in an unexpected shape -- is reported as-is.
    """


class GeoSphereConnectionError(GeoSphereTransientError):
    """Network-level failure."""


class GeoSphereRateLimitError(GeoSphereApiError):
    """HTTP 429 — request budget exceeded (5 req/s, 240 req/h)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GeoSphereServerError(GeoSphereTransientError):
    """HTTP 5xx — the API failed to answer a well-formed request.

    Carries `status` for callers that need the code. Callers that only report
    a failure keep catching `GeoSphereApiError` and need no change.
    """

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


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
        """Fetch a point timeseries and parse the GeoJSON response.

        Transient faults -- 5xx and connection errors, including timeouts --
        are retried up to `MAX_ATTEMPTS` times with an exponential, jittered
        backoff. The retry lives here rather than in the coordinators so that
        a fault which clears on a later attempt is never *observed* upstream:
        nothing logs it, nothing falls back, and no entity is blanked for a
        request that was about to succeed. Only the last attempt's failure
        propagates.

        A 429 and every 4xx are returned as-is. The first means the request
        budget is already gone and retrying spends what is left of it; the
        rest are rejections of the request itself, which would be rejected
        identically three times. A 200 whose body is unusable -- the wrong
        shape, the wrong content type, or not JSON at all -- is likewise not
        retried: that is a contract change or an interception, not a blip.
        """
        url = f"{self._base_url}/timeseries/{mode}/{resource_id}"
        query: dict[str, str] = {
            "parameters": ",".join(parameters),
            "lat_lon": f"{latitude},{longitude}",
            "output_format": "geojson",
        }
        if start is not None:
            query["start"] = _stamp(start)
        if end is not None:
            query["end"] = _stamp(end)

        for attempt in range(1, MAX_ATTEMPTS):
            try:
                return await self._attempt(url, query, resource_id)
            except GeoSphereTransientError:
                await asyncio.sleep(_backoff_delay(attempt))
        # The final attempt is deliberately outside the loop: its failure is
        # the caller's, and there is no unreachable branch to explain.
        return await self._attempt(url, query, resource_id)

    async def _attempt(
        self, url: str, query: dict[str, str], resource_id: str
    ) -> GeoSphereResponse:
        """One request, parsed. Every failure mode raises."""
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
                if resp.status >= 500:
                    raise GeoSphereServerError(
                        f"GeoSphere API returned HTTP {resp.status} for {resource_id}",
                        status=resp.status,
                    )
                if resp.status >= 400:
                    raise GeoSphereApiError(
                        f"GeoSphere API returned HTTP {resp.status} for {resource_id}"
                    )
                try:
                    body = await resp.json()
                except ValueError as err:
                    # A 200 whose body is not JSON: a captive portal, a proxy
                    # error page, a maintenance page. The decode raises a
                    # `ValueError`, which is not an `aiohttp.ClientError` and
                    # so was caught by nothing here -- it escaped the
                    # `GeoSphereApiError` hierarchy entirely, past every
                    # `except` in the coordinators into HA's generic
                    # "Unexpected error fetching ... data" traceback, and past
                    # the config flow's handler as an unknown exception rather
                    # than `cannot_connect`.
                    raise GeoSphereApiError(
                        f"GeoSphere API returned a body that is not JSON for "
                        f"{resource_id}: {type(err).__name__}"
                    ) from err
        except aiohttp.ClientResponseError as err:
            # The server answered and the answer is unusable -- a
            # `ContentTypeError` from the decode above is the common case.
            # These are `aiohttp.ClientError` subclasses, so the transport
            # handler below used to sweep them up: reported as "Error
            # connecting to the GeoSphere API", which sends the reader after a
            # network fault that never happened, and classified transient, so
            # retried three times for an answer that will not change. A fault
            # mid-body (`ClientPayloadError`, `ServerDisconnectedError`) is
            # not a `ClientResponseError` and stays retryable below.
            raise GeoSphereApiError(
                f"GeoSphere API answered {resource_id} unusably: {err}"
            ) from err
        except (TimeoutError, aiohttp.ClientError) as err:
            # Name the class. Several of these stringify to `""` --
            # `ClientConnectionError` and `ClientOSError` carry the diagnosis
            # in the type alone -- which made "Error connecting to the
            # GeoSphere API: " both the most frequent line in the log and the
            # least diagnosable one.
            reason = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
            raise GeoSphereConnectionError(
                f"Error connecting to the GeoSphere API: {reason}"
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
