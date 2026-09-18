"""Tests for the GeoSphere API client."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import Mock

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next import api
from custom_components.geosphere_next.api import (
    GeoSphereApiClient,
    GeoSphereApiError,
    GeoSphereConnectionError,
    GeoSphereOutOfDomainError,
    GeoSphereRateLimitError,
    GeoSphereServerError,
    GeoSphereTransientError,
)

from .conftest import AROME_URL, load_fixture, mock_response, response_sequence


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


async def _fetch(client: GeoSphereApiClient):
    """Request the AROME dataset, the URL the retry tests are wired to."""
    return await client.get_timeseries(
        "forecast",
        "nwp-v1-1h-2500m",
        parameters=("t2m",),
        latitude=48.0,
        longitude=16.0,
    )


def test_backoff_is_exponential_and_jittered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each attempt waits twice as long, spread by a jitter band.

    Jitter matters because the three coordinators poll on schedules that
    coincide: an unjittered backoff would retry them in lockstep against an
    API with a 5 req/s budget, turning one 502 into a burst.
    """
    # The suite-wide fixture zeroes this; the arithmetic under test is only
    # observable at a non-zero base.
    monkeypatch.setattr(api, "RETRY_BASE_DELAY", 1.0)
    for attempt, centre in ((1, 1.0), (2, 2.0)):
        samples = [api._backoff_delay(attempt) for _ in range(200)]
        assert all(
            centre * (1 - api.RETRY_JITTER) <= s <= centre * (1 + api.RETRY_JITTER)
            for s in samples
        )
        # Jittered, not a constant.
        assert len(set(samples)) > 1


async def test_server_error_is_retried_until_it_succeeds(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """Two 502s then a body: the caller sees only the parsed result.

    The whole point of retrying inside the client — the coordinator never
    observes the failures, so nothing downstream goes `unknown` for a fault
    that resolved on the second attempt.
    """
    aioclient_mock.get(
        AROME_URL,
        side_effect=response_sequence(
            mock_response(status=502),
            mock_response(status=502),
            mock_response(json=load_fixture("arome.json")),
        ),
    )
    response = await _fetch(GeoSphereApiClient(api_session))

    assert response.reference_time is not None
    assert aioclient_mock.call_count == 3


async def test_server_error_gives_up_after_three_attempts(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """A persistent 502 raises, and stops at MAX_ATTEMPTS requests."""
    aioclient_mock.get(AROME_URL, status=502)
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereServerError) as err:
        await _fetch(client)

    assert err.value.status == 502
    # The message the coordinator logs — unchanged by the retry.
    assert "HTTP 502 for nwp-v1-1h-2500m" in str(err.value)
    assert aioclient_mock.call_count == api.MAX_ATTEMPTS


async def test_connection_error_is_retried_until_it_succeeds(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """A dropped connection is transient too — the dominant failure in the logs."""
    aioclient_mock.get(
        AROME_URL,
        side_effect=response_sequence(
            mock_response(exc=aiohttp.ClientConnectionError()),
            mock_response(exc=TimeoutError()),
            mock_response(json=load_fixture("arome.json")),
        ),
    )
    response = await _fetch(GeoSphereApiClient(api_session))

    assert response.reference_time is not None
    assert aioclient_mock.call_count == 3


async def test_payload_error_stays_retryable(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    """The boundary case of the response-level/transport-level split.

    `ClientPayloadError` is the transfer dying part-way through a body the
    server had already begun sending. It is an `aiohttp.ClientError` but
    *not* a `ClientResponseError`, so it has to stay on the retryable side of
    the line that keeps `ContentTypeError` off it — otherwise narrowing the
    transport handler would have quietly stopped retrying a genuine
    transport fault.
    """
    aioclient_mock.get(
        AROME_URL,
        side_effect=response_sequence(
            mock_response(exc=aiohttp.ClientPayloadError()),
            mock_response(json=load_fixture("arome.json")),
        ),
    )
    response = await _fetch(GeoSphereApiClient(api_session))

    assert response.reference_time is not None
    assert aioclient_mock.call_count == 2


async def test_rate_limit_is_not_retried(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """429 means the budget is gone; retrying spends what is left of it."""
    aioclient_mock.get(AROME_URL, status=429, headers={"Retry-After": "120"})
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereRateLimitError):
        await _fetch(client)

    assert aioclient_mock.call_count == 1


async def test_bad_request_is_not_retried(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """A rejected request is rejected identically three times."""
    aioclient_mock.get(
        AROME_URL, status=400, json=load_fixture("arome_out_of_domain.json")
    )
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereOutOfDomainError):
        await _fetch(client)

    assert aioclient_mock.call_count == 1


async def test_malformed_body_is_not_retried(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """A 200 in an unexpected shape is a contract change, not a blip."""
    aioclient_mock.get(AROME_URL, json={"features": []})
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereApiError):
        await _fetch(client)

    assert aioclient_mock.call_count == 1


async def test_connection_error_names_the_exception_type(
    aioclient_mock: AiohttpClientMocker,
    api_session: aiohttp.ClientSession,
) -> None:
    """The class carries the diagnosis when `str(err)` is empty.

    Most of the connection failures in the HA log read `Error connecting to
    the GeoSphere API: ` with nothing after the colon — the aiohttp errors
    raised here stringify to `''`, so the most frequent failure mode was the
    one that could not be diagnosed.
    """
    aioclient_mock.get(AROME_URL, exc=aiohttp.ClientConnectionError())
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereConnectionError) as err:
        await _fetch(client)

    assert "ClientConnectionError" in str(err.value)


async def test_undecodable_body_is_not_retried(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    """A 200 carrying something that is not JSON at all.

    What a captive portal, a proxy error page or a maintenance page looks
    like from here: the request succeeded and the body is HTML. The decode
    failure is a `ValueError`, which is neither an `aiohttp.ClientError` nor
    anything else the client used to catch, so it escaped the
    `GeoSphereApiError` hierarchy entirely -- past every `except` in
    `coordinator.py`, surfacing as HA's generic "Unexpected error fetching
    ... data" traceback, and past `config_flow.py`'s handler as an unknown
    exception instead of `cannot_connect`.
    """
    aioclient_mock.get(AROME_URL, text="<html>under maintenance</html>")
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereApiError) as err:
        await _fetch(client)

    # Reported, not retried: three identical HTML pages are still not JSON.
    assert not isinstance(err.value, GeoSphereTransientError)
    assert aioclient_mock.call_count == 1


async def test_response_level_error_is_not_treated_as_a_connection_fault(
    aioclient_mock: AiohttpClientMocker, api_session: aiohttp.ClientSession
) -> None:
    """`ContentTypeError` means the server answered, not that the link broke.

    It is an `aiohttp.ClientResponseError`, and therefore an
    `aiohttp.ClientError`, so the blanket connection handler swept it up:
    reported as "Error connecting to the GeoSphere API" -- sending the reader
    after a network fault that never happened -- and, once retries existed,
    classified transient and retried three times. A transport fault mid-body
    (`ClientPayloadError`, `ServerDisconnectedError`) is *not* a
    `ClientResponseError` and must stay retryable; this is the line between
    the two.
    """
    aioclient_mock.get(
        AROME_URL,
        exc=aiohttp.ContentTypeError(
            Mock(real_url="http://example.com"),
            (),
            message="unexpected mimetype: text/html",
        ),
    )
    client = GeoSphereApiClient(api_session)
    with pytest.raises(GeoSphereApiError) as err:
        await _fetch(client)

    assert not isinstance(err.value, GeoSphereTransientError)
    assert aioclient_mock.call_count == 1
