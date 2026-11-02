"""Tests for coordinator processing via a full config-entry setup."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next import api
from custom_components.geosphere_next.condition import is_night
from custom_components.geosphere_next.const import CONF_HAS_NOWCAST, DOMAIN
from custom_components.geosphere_next.models import ForecastData

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


async def _setup(hass: HomeAssistant, entry) -> None:
    # Daily aggregation groups by HA's local calendar day.
    await hass.config.async_set_time_zone("Europe/Vienna")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_forecast_requests_an_hour_of_history(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """AROME and the ensemble are asked for one hour before the current hour.

    Together they guarantee the series reaches back to the hour already under
    way. Losing that hour would take the "forecast starts at the current hour"
    behaviour, `outlook.hour_at`, and the current condition's cloud/CAPE
    reading with it.

    The clock is deliberately **off** the hour, because that is the only clock
    at which the anchor is observable: the API honours a `start` that lands on
    a stamp and rounds a mid-hour one *up* to the next. Anchored to `now`,
    16:30 - 1 h = 15:30 would come back at 16:00 — still the hour under way,
    but with the margin spent, and with no lookback at all `start = 16:30`
    would round to 17:00 and lose it outright. At a clock of exactly 16:00:00
    both anchorings produce 15:00 and the distinction goes untested.
    """
    freezer.move_to("2026-07-15T16:30:00+00:00")
    await _setup(hass, mock_config_entry)

    starts = [
        call[1].query.get("start")
        for call in mock_api.mock_calls
        if "nwp-v2-1h-1km" in str(call[1]) or "ensemble-v2-1h-1km" in str(call[1])
    ]
    assert len(starts) == 2
    assert starts == ["2026-07-15T15:00", "2026-07-15T15:00"]
    # And the assembled forecast still opens on the hour under way.
    hourly = mock_config_entry.runtime_data.forecast.data.hourly
    assert hourly[0].datetime.isoformat() == "2026-07-15T16:00:00+00:00"


async def test_forecast_processing(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.forecast.data

    # Fixture: reference 12:00Z, timestamps 12:00Z..+60h, recorded from the
    # run's own t0. At frozen 16:00Z the forecast starts at the in-progress
    # hour 16:00Z (index 4); indexes 0-3 precede the cutoff. The final stamp
    # (2026-07-18T00:00Z) cannot be emitted -- its interval fields would live
    # on a successor that is not in the series -- so 56 rows survive, ending
    # 2026-07-17T23:00Z.
    assert len(data.hourly) == 56
    assert data.hourly[-1].datetime.isoformat() == "2026-07-17T23:00:00+00:00"

    first = data.hourly[0]
    assert first.datetime.isoformat() == "2026-07-15T16:00:00+00:00"
    # Instantaneous at the stamp.
    assert first.temperature == 4.8
    # `tp` is a per-hour amount for the hour ending at its stamp, so the hour
    # beginning 16:00Z is read at 17:00Z (0.0) -- not at 16:00Z, whose 0.002
    # fell in the hour that has already elapsed.
    assert first.precipitation == 0.0
    assert first.wind_gust_speed == 1.7
    # `tcc` is published in percent and passed through unscaled.
    assert first.cloud_coverage == 100.0
    # `sy` covers the interval ending at its stamp, like `tp`, so the hour
    # beginning 16:00Z reads the 17:00Z code: 5 (Bedeckt).
    assert first.weather_symbol == 5
    assert first.condition == "cloudy"
    # Magnus from 2t 4.8 / 2r 80.89.
    assert first.dew_point == pytest.approx(1.8)
    # `snowlmt` is instantaneous, read at the row's own stamp. The snow limit
    # and the weather symbol live on the rows only; the current coordinator
    # picks them from the hour covering now.
    assert first.snow_limit == pytest.approx(854.1)
    assert "weather_symbol" not in {f.name for f in fields(ForecastData)}
    assert "snow_limit" not in {f.name for f in fields(ForecastData)}
    assert data.current is first

    # Stepped probability from the ensemble tp percentiles, read one stamp on
    # -- the percentiles cover the hour ending at their stamp, like `tp`.
    # Rows 16:00Z and 17:00Z take the 17:00Z/18:00Z entries, whose p90 stays
    # under PRECIP_MIN_MM; the next three take entries with only p90 wet.
    assert [hour.precipitation_probability for hour in data.hourly[:5]] == [
        0,
        0,
        30,
        30,
        30,
    ]


async def test_ensemble_storm_percentiles_describe_the_row_they_sit_on(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """`cape_p90` is read at its own stamp, `tp_p90` one stamp on.

    Requested from the run's t0, `cape_p90` has a value at index 0 and is
    instantaneous, like `cape`; `tp_p90` is null there and covers the
    interval ending at its stamp, like `tp`. The 16:00Z row therefore carries
    the 16:00Z `cape_p90` (11.2) and the 17:00Z `tp_p90` (0.001).
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.forecast.data
    first = data.hourly[0]

    # The run's stamp travels along, for the outlook's age bound.
    assert data.ensemble_reference_time == datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert first.ensemble_cape_p90 == pytest.approx(11.2)
    assert first.ensemble_precipitation_p90 == pytest.approx(0.001)
    ensemble_urls = [
        str(call[1])
        for call in mock_api.mock_calls
        if "ensemble-v2-1h-1km" in str(call[1])
    ]
    assert ensemble_urls
    assert all("cape_p90" in url for url in ensemble_urls)


async def test_forecast_interval_fields_describe_the_hour_they_start(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """Precipitation and gusts belong to the hour beginning at the stamp.

    `tp` and `10fg` are published "in the last forecast interval" -- they
    are null at the run's t0 -- so each describes the interval *ending* at its
    stamp. A row stamped T covers T..T+1h, so its interval fields have to be
    read one step later. Getting this wrong reports rain that already stopped
    and the previous hour's gust peak.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    hourly = mock_config_entry.runtime_data.forecast.data.hourly

    by_ts = {hour.datetime.isoformat(): hour for hour in hourly}
    # Fixture `tp` reads 0.0 / 0.213 / 0.424 at 04:00Z / 05:00Z / 06:00Z, so
    # the hour *starting* 04:00Z catches 0.213 mm and the one starting 05:00Z
    # catches 0.424 mm. Each is read directly: `tp` is not run-accumulated.
    assert by_ts["2026-07-16T04:00:00+00:00"].precipitation == 0.213
    assert by_ts["2026-07-16T05:00:00+00:00"].precipitation == 0.424
    # Same rule for the gust: `10fg` at 05:00Z (6.5 m/s) describes
    # 04:00Z-05:00Z, while 04:00Z's own 4.3 belongs to the hour before.
    assert by_ts["2026-07-16T04:00:00+00:00"].wind_gust_speed == 6.5
    assert by_ts["2026-07-16T03:00:00+00:00"].wind_gust_speed == 4.3


async def test_precipitation_probability_matches_the_row_it_is_reported_with(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """PoP is shifted with the amount, not left a stamp behind.

    The C-LAEF percentiles are interval values too ("in the last forecast
    interval"), so they need the same one-step shift as `tp`. Left unshifted
    they pair each row's amount with the previous hour's probability -- the
    forecast then shows a dry hour at 70 %, or rain at 0 %.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    hourly = mock_config_entry.runtime_data.forecast.data.hourly

    by_ts = {hour.datetime.isoformat(): hour for hour in hourly}
    # The fixture's wettest ensemble entries are 06:00Z and 07:00Z (p50 wet,
    # 70 %), with p90-only entries either side: 05:00Z and 08:00Z (30 %) and a
    # dry 04:00Z. Each describes the hour ending at its stamp, so they land on
    # the rows starting 05:00Z/06:00Z (70 %) and 04:00Z/07:00Z (30 %).
    # Unshifted, 04:00Z would read 0 % and 07:00Z 70 %.
    assert by_ts["2026-07-16T04:00:00+00:00"].precipitation_probability == 30
    assert by_ts["2026-07-16T05:00:00+00:00"].precipitation_probability == 70
    assert by_ts["2026-07-16T06:00:00+00:00"].precipitation_probability == 70
    assert by_ts["2026-07-16T07:00:00+00:00"].precipitation_probability == 30


async def test_precipitation_probability_survives_a_coarsening_ensemble(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The percentile's period comes from the series, not a fixed 1 h step.

    Ensembles commonly coarsen along their horizon, and C-LAEF may yet do so.
    Subtracting a hardcoded step from every stamp would then miss every AROME
    row past the break and blank the probability across the whole forecast,
    silently -- no warning, just `None` everywhere. Keying on the preceding
    stamp is right at any cadence.

    Here the series goes 3-hourly after 17:00Z, so the 20:00Z percentile
    describes the period beginning 17:00Z and must land on that row.
    """
    ensemble = load_fixture("ensemble.json")
    ensemble["timestamps"] = [
        "2026-07-15T15:00+00:00",
        "2026-07-15T16:00+00:00",
        "2026-07-15T17:00+00:00",
        "2026-07-15T20:00+00:00",
    ]
    parameters = ensemble["features"][0]["properties"]["parameters"]
    # Only the last (3-hourly) entry is wet, and it is wet at every percentile.
    for name in ("tp_p10", "tp_p50", "tp_p90"):
        parameters[name]["data"] = [0.0, 0.0, 0.0, 5.0]

    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=ensemble)
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    by_ts = {
        hour.datetime.isoformat(): hour
        for hour in mock_config_entry.runtime_data.forecast.data.hourly
    }
    assert by_ts["2026-07-15T17:00:00+00:00"].precipitation_probability == 95
    # And the regular part of the series still lands where it did.
    assert by_ts["2026-07-15T16:00:00+00:00"].precipitation_probability == 0


async def test_ensemble_failure_omits_probability(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failing ensemble endpoint must not take the forecast down."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, status=500)
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.forecast.data
    assert len(data.hourly) == 56
    assert all(hour.precipitation_probability is None for hour in data.hourly)
    assert data.ensemble_reference_time is None


def _forecast_calls(mock_api: AiohttpClientMocker) -> tuple[int, int]:
    """(AROME, ensemble) request counts recorded so far."""
    calls = [str(call[1]) for call in mock_api.mock_calls]
    return (
        sum("nwp-v2-1h-1km" in call for call in calls),
        sum("ensemble-v2-1h-1km" in call for call in calls),
    )


async def test_ensemble_failure_degrades_to_the_cached_run(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failed *re*-fetch keeps the previous run rather than dropping to none.

    The percentiles are matched to AROME by timestamp, so an older run
    still has a value for every hour it covers. Blanking the probability
    across the whole forecast because one request failed would throw away a
    usable, if older, answer. The bound on how old is asserted separately.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.forecast
    baseline = {
        hour.datetime: hour.precipitation_probability
        for hour in coordinator.data.hourly
    }
    assert any(value is not None for value in baseline.values())

    # The next update fetches the ensemble again — and fails.
    aioclient_mock.clear_requests()
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, status=500)
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    freezer.move_to("2026-07-15T17:00:00+00:00")
    await coordinator.async_refresh()

    # A failed fetch costs the client's full retry budget, since a 500 is
    # retryable.
    assert _forecast_calls(aioclient_mock)[1] == api.MAX_ATTEMPTS
    assert coordinator.last_update_success
    probabilities = {
        hour.datetime: hour.precipitation_probability
        for hour in coordinator.data.hourly
    }
    assert any(value is not None for value in probabilities.values())
    # Every hour the cached run still covers reports what it reported before.
    assert all(value == baseline[ts] for ts, value in probabilities.items())


async def test_ensemble_fallback_is_bounded(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An endpoint that never recovers must not keep a stale run in service.

    An older run is not the same answer as the current one — it is an
    older, worse forecast for the same hour — and nothing on display says
    which run a probability came from. Past `ENSEMBLE_MAX_FALLBACK_AGE` the
    probability disappears instead, which is visible rather than quietly
    wrong.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.forecast

    aioclient_mock.clear_requests()
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, status=500)
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))

    # Run 12:00Z, now +10 h: inside the 12 h bound.
    freezer.move_to("2026-07-15T22:00:00+00:00")
    await coordinator.async_refresh()
    assert any(
        hour.precipitation_probability is not None for hour in coordinator.data.hourly
    )

    # +13 h: past the bound. The run is dropped, not quietly kept.
    freezer.move_to("2026-07-16T01:00:00+00:00")
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert all(
        hour.precipitation_probability is None for hour in coordinator.data.hourly
    )


async def test_current_merge(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.current.data

    # Thermodynamic fields and wind prefer the INCA analysis (latest 15:00Z)
    # over the nowcast, which lags diurnal ramps by ~2 h.
    assert data.temperature == 30.43
    assert data.humidity == pytest.approx(33.53)
    assert data.dew_point == pytest.approx(12.59)
    # INCA UU -0.09 / VV -2.83 -> wind from just east of north.
    assert data.wind_speed == pytest.approx(2.83, abs=0.01)
    assert data.wind_bearing == pytest.approx(1.8, abs=0.1)
    # INCA latest values (15:00Z): P0 101585.83 Pa -> hPa, GL W/m2.
    assert data.pressure_hpa == pytest.approx(1015.9)
    assert data.global_radiation == pytest.approx(248.94)
    assert data.precipitation_1h == 0.0
    assert data.is_precipitating is False
    # Cloud cover comes from the AROME fallback (nowcast has none): 100 %.
    assert data.cloud_coverage == 100.0
    assert data.condition == "cloudy"
    assert data.apparent_temperature is not None


async def test_nowcast_failure_falls_back_to_inca(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the nowcast errors, INCA values fill the current conditions."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, status=500)
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # INCA T2M latest (15:00Z)
    assert data.temperature == 30.43
    assert data.pressure_hpa == pytest.approx(1015.9)
    # Gusts fall back to AROME.
    assert data.wind_gust_speed is not None


async def test_inca_failure_falls_back_to_nowcast(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When INCA errors, the nowcast fills the thermodynamic fields."""
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, status=500)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # Nowcast timestamp closest to 16:00Z.
    assert data.temperature == 29.74
    assert data.wind_bearing == pytest.approx(345.2)
    # INCA-only fields stay empty.
    assert data.pressure_hpa is None
    assert data.global_radiation is None


async def test_observed_at_reports_the_nowcast_bucket_not_the_clock(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With the nowcast supplying the temperature, its bucket stamp is the answer.

    `now` is not: no source ever states it, and this sensor exists precisely
    to show how far behind real time a reading is. The clock sits deliberately
    off the 15-min grid, which is the only condition under which the two
    differ at all.
    """
    freezer.move_to("2026-07-15T16:07:00+00:00")
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, status=500)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.temperature == 29.74  # the nowcast bucket nearest 16:07
    assert data.observed_at == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


async def test_observed_at_is_never_in_the_future(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The bucket match is nearest, not nearest-in-the-past.

    At 16:38 the 16:45 bucket is closer than 16:30, so the stamp would be
    reported seven minutes ahead of the clock -- an "observation" time later
    than the present, describing what is really a short forecast.
    """
    freezer.move_to("2026-07-15T16:38:00+00:00")
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, status=500)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.observed_at <= datetime(2026, 7, 15, 16, 38, tzinfo=UTC)


async def test_observed_at_ignores_an_analysis_without_temperature(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An INCA slice carrying RR but no T2M must not date the temperature.

    The temperature then falls to the nowcast and is current, so reporting the
    analysis stamp (15:00Z, over an hour back) would claim a staleness the
    displayed value does not have. Every rung follows the temperature.
    """
    inca = load_fixture("inca.json")
    parameters = inca["features"][0]["properties"]["parameters"]
    parameters["T2M"]["data"] = [None] * len(inca["timestamps"])

    freezer.move_to("2026-07-15T16:07:00+00:00")
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=inca)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # INCA still supplies its own fields, so the analysis did arrive.
    assert data.pressure_hpa is not None
    assert data.observed_at == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


def _storm_nowcast(rr: list[float]) -> dict:
    """The nowcast fixture with `pt` precipitating and `rr` set per bucket.

    Buckets run 15:45, 16:00, 16:15, ... so at the 16:00 frozen clock the
    matched bucket is index 1 and `RATE_LOOKBACK` reaches back to 15:30,
    covering index 0 as well.
    """
    payload = load_fixture("nowcast.json")
    parameters = payload["features"][0]["properties"]["parameters"]
    count = len(payload["timestamps"])
    parameters["rr"]["data"] = (rr + [0.0] * count)[:count]
    parameters["pt"]["data"] = [1.0] * count
    return payload


async def test_a_dry_bucket_does_not_hide_the_cell_that_just_passed(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The lull between cells of an active downpour still reads as one.

    The matched bucket reads 0.0 while the one 15 min earlier caught 2 mm
    (8 mm/h). Taking the matched bucket alone reports 0 mm/h, which starves
    the `pouring` branch and leaves plain `rainy`.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=_storm_nowcast([2.0, 0.0]))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.current.data.condition == "pouring"


async def test_a_shower_that_already_ended_does_not_derive_a_downpour(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Rain that stopped must not keep driving the condition.

    INCA's `RR` is a total over the whole past hour, so 6 mm that fell early
    in it and stopped is still on the books while only drizzle continues --
    enough to keep `pt` non-zero. Reading that total as an instantaneous rate
    would clear POURING_MM_PER_H and derive `pouring` from a drizzling sky.
    Every bucket inside RATE_LOOKBACK is dry, so it must not.
    """
    inca = load_fixture("inca.json")
    inca["features"][0]["properties"]["parameters"]["RR"]["data"] = [6.0] * len(
        inca["timestamps"]
    )

    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=_storm_nowcast([0.0, 0.0]))
    aioclient_mock.get(INCA_URL, json=inca)
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.current.data.condition == "rainy"


async def test_inca_refresh_keyed_on_data_age(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """INCA refetches when its newest analysis ages out, not on a fetch timer."""
    # Fixture's latest INCA analysis is 15:00Z: fresh at 15:30Z (30 min old).
    freezer.move_to("2026-07-15T15:30:00+00:00")
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.current

    def inca_calls() -> int:
        return sum("inca-v1-1h-1km" in str(call[1]) for call in mock_api.mock_calls)

    baseline = inca_calls()
    assert baseline == 1

    # Still fresh: the next update reuses the cached slice.
    await coordinator.async_refresh()
    assert inca_calls() == baseline

    # 16:10Z: the 15:00Z analysis is 70 min old -> stale, refetch.
    freezer.tick(timedelta(minutes=40))
    await coordinator.async_refresh()
    assert inca_calls() == baseline + 1


async def test_forecast_parameters_are_requested_and_populated(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """Every field the forecast is built from must actually arrive.

    `GeoSphereResponse.series()` returns `[None] * len(timestamps)` for an
    absent parameter, so a renamed or typo'd key would blank that field across
    the whole forecast with a green suite.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    hourly = mock_config_entry.runtime_data.forecast.data.hourly

    for field in (
        "temperature",
        "humidity",
        "wind_speed",
        "wind_bearing",
        "wind_gust_speed",
        "cloud_coverage",
        "precipitation",
        "cape",
        "weather_symbol",
        "condition",
        "precipitation_probability",
    ):
        assert all(getattr(hour, field) is not None for hour in hourly), field
    # The mocker ignores the query string, so also pin what is requested.
    arome_urls = [
        str(call[1]) for call in mock_api.mock_calls if "nwp-v2-1h-1km" in str(call[1])
    ]
    assert arome_urls
    for name in ("2t", "2r", "10u", "10v", "10fg", "tcc", "tp", "cape", "sy"):
        assert all(name in url for url in arome_urls), name


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        (26, "lightning-rainy"),
        (19, "pouring"),
        (23, "snowy"),
        (20, "snowy-rainy"),
        (6, "fog"),
        (3, "partlycloudy"),
        (1, "sunny"),
    ],
)
async def test_symbol_decides_the_forecast_condition_end_to_end(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    symbol: int,
    expected: str,
) -> None:
    """End-to-end proof that the symbol mapping is wired, not just unit-tested.

    `stormy_arome` writes `symbol` to the code of the 16:00Z hour (index 5).
    16:00Z is daytime in Vienna in July, so code 1 is `sunny`.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(
        AROME_URL, json=stormy_arome(indexes=(4,), symbol=symbol, cape=0.0)
    )
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    first = mock_config_entry.runtime_data.forecast.data.hourly[0]
    assert first.weather_symbol == symbol
    assert first.condition == expected


async def test_forecast_night_is_judged_at_the_middle_of_the_hour(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A clear hour that is mostly after sunset reads `clear-night`.

    At this longitude the sun is still up at 18:00Z but down by 18:30Z, so
    the 18:00Z row is judged at its middle, not at its start.
    """
    latitude, longitude = 48.22, 25.0
    start = datetime(2026, 7, 15, 18, tzinfo=UTC)
    assert not is_night(latitude, longitude, start)
    assert is_night(latitude, longitude, start + timedelta(minutes=30))

    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(
        AROME_URL, json=stormy_arome(indexes=(6,), symbol=1, precipitation=0.0)
    )
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GeoSphere Next",
        unique_id=f"{latitude:.4f}_{longitude:.4f}",
        data={
            CONF_LATITUDE: latitude,
            CONF_LONGITUDE: longitude,
            CONF_HAS_NOWCAST: True,
        },
    )
    await _setup(hass, entry)

    by_hour = {h.datetime: h for h in entry.runtime_data.forecast.data.hourly}
    assert by_hour[start].weather_symbol == 1
    assert by_hour[start].condition == "clear-night"


async def test_an_unknown_symbol_is_unknown_and_reported_once(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A code outside the table reads `None` and warns once, not every update."""
    payload = load_fixture("arome.json")
    sy = payload["features"][0]["properties"]["parameters"]["sy"]["data"]
    # The 16:00Z and 17:00Z rows, the same unpublished code twice.
    sy[5] = 40.0
    sy[6] = 40.0
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=payload)
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.forecast
    await coordinator.async_refresh()

    assert coordinator.data.hourly[0].weather_symbol == 40
    assert coordinator.data.hourly[0].condition is None
    warnings = [
        record
        for record in caplog.records
        if "weather-symbol code 40" in record.getMessage()
    ]
    assert len(warnings) == 1


async def test_forecast_symbol_describes_the_hour_it_starts(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A row reads the symbol stamped one hour on, as it reads `tp`.

    Measured against the live nwp-v2 grid: every precipitation class is wet
    in `tp` at its own stamp, i.e. it describes the interval *ending* there.
    A thunderstorm code stamped 17:00Z is therefore the storm of the hour
    beginning 16:00Z, and one stamped 16:00Z belongs to the hour that has
    already ended. Reading it at the row's own stamp would show the storm an
    hour late and keep it an hour after it has passed.
    """
    payload = load_fixture("arome.json")
    sy = payload["features"][0]["properties"]["parameters"]["sy"]["data"]
    # 16:00Z: the hour 15:00-16:00, already over at the frozen clock.
    sy[4] = 26.0
    # 18:00Z: the hour 17:00-18:00.
    sy[6] = 28.0
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=payload)
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    hourly = mock_config_entry.runtime_data.forecast.data.hourly
    conditions = {hour.datetime.hour: hour.condition for hour in hourly[:3]}
    assert conditions == {16: "cloudy", 17: "lightning-rainy", 18: "cloudy"}


async def test_current_condition_reads_the_symbol_of_the_hour(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Observations decide what falls; the hour's symbol the rest.

    A thunderstorm symbol for the in-progress hour under a dry nowcast is
    `cloudy` -- the model expects a storm nobody observes -- while the same
    symbol over observed rain is a thunderstorm. The `weather_symbol` sensor
    reports the code that was read.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(4,), symbol=27))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.current

    assert coordinator.data.weather_symbol == 27
    assert coordinator.data.is_precipitating is False
    assert coordinator.data.condition == "cloudy"

    aioclient_mock.clear_requests()
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(4,), symbol=27))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=wet_nowcast(rate_mm=0.5))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await coordinator.async_refresh()

    assert coordinator.data.is_precipitating is True
    assert coordinator.data.condition == "lightning-rainy"


async def test_current_condition_outside_the_nowcast_grid_is_the_symbol(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With no nowcast and no INCA, nothing observes precipitation.

    The hour's rain symbol therefore stands as `rainy` rather than being
    read as a dry sky under a wrong forecast.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(4,), symbol=9))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GeoSphere Next",
        unique_id="47.0000_9.0000",
        data={CONF_LATITUDE: 47.0, CONF_LONGITUDE: 9.0, CONF_HAS_NOWCAST: False},
    )
    await _setup(hass, entry)

    data = entry.runtime_data.current.data
    assert data.is_precipitating is None
    assert data.weather_symbol == 9
    assert data.condition == "rainy"


async def test_current_arome_fields_follow_the_clock(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """AROME-sourced current fields track the hour, not the forecast fetch.

    The current coordinator runs every 15 min while the forecast one can be
    180 min apart, so reading the "step 0" snapshot captured at fetch time
    would leave cloud cover, CAPE and the snow limit — and with them the
    derived condition — up to 3 h stale.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.current

    def arome_calls() -> int:
        return sum("nwp-v2-1h-1km" in str(call[1]) for call in mock_api.mock_calls)

    baseline = arome_calls()
    # Fixture hour 16:00Z: tcc 100 %, cape 2.8, snow limit 854.1 m, symbol 5
    # (read at 17:00Z).
    assert coordinator.data.cloud_coverage == 100.0
    assert coordinator.data.cape == pytest.approx(2.8)
    assert coordinator.data.snow_limit == pytest.approx(854.1)
    assert coordinator.data.weather_symbol == 5

    # Three hours on, without refetching the forecast: hour 19:00Z carries
    # tcc 97 %, cape 7.3, snow limit 903.3 m.
    freezer.move_to("2026-07-15T19:30:00+00:00")
    await coordinator.async_refresh()
    assert arome_calls() == baseline
    assert coordinator.data.cloud_coverage == 97.0
    assert coordinator.data.cape == pytest.approx(7.3)
    assert coordinator.data.snow_limit == pytest.approx(903.3)

    # And the symbol: the hour 20:00Z reads code 8 (light rain, stamped
    # 21:00Z), which the dry nowcast turns into `cloudy`.
    freezer.move_to("2026-07-15T20:30:00+00:00")
    await coordinator.async_refresh()
    assert arome_calls() == baseline
    assert coordinator.data.weather_symbol == 8
    assert coordinator.data.condition == "cloudy"


async def test_current_falls_back_when_the_forecast_aged_out(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Past the end of the series there is no matching hour — keep step 0."""
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.current
    step_zero = mock_config_entry.runtime_data.forecast.data.current

    # The fixture ends at 2026-07-18T00:00Z; nothing covers this hour.
    freezer.move_to("2026-07-19T12:30:00+00:00")
    await coordinator.async_refresh()
    assert coordinator.data.cloud_coverage == step_zero.cloud_coverage
    assert coordinator.data.cape == step_zero.cape


def _wet_inca(millimetres: float = 2.4) -> dict:
    """The recorded INCA fixture with rain in its newest analysis (15:00Z)."""
    inca = load_fixture("inca.json")
    inca["features"][0]["properties"]["parameters"]["RR"]["data"][-1] = millimetres
    return inca


async def test_stale_inca_rr_does_not_derive_rain(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An `RR` whose hour has fully receded must not keep the condition rainy.

    `RR` accumulates over the hour ending at its own stamp, `inca_latest`
    returns the newest non-None value at any age, and the cached slice is
    served on for `INCA_MAX_AGE_SECONDS` — indefinitely while refreshes fail.
    With the nowcast down that fed the condition directly, so 2.4 mm falling
    in the hour to 15:00Z kept deriving `rainy` under whatever sky AROME
    forecast, indefinitely. Past `INCA_RR_MAX_AGE_SECONDS` the derivation now falls
    through to cloud cover. The bound sits well past INCA's own ~90 min
    worst-case lag, so it marks a slice that stopped updating rather than
    ordinary publishing delay — see `test_current_inca_rr_still_derives_rain`.
    """
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, exc=TimeoutError)
    aioclient_mock.get(INCA_URL, json=_wet_inca())
    # 2h35m past the 15:00Z stamp: INCA should have published two newer
    # analyses by now, so the slice has demonstrably stopped updating. Well
    # clear of the ~90 min a healthy publish cycle can legitimately reach.
    freezer.move_to("2026-07-15T17:35:00+00:00")
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.condition == "cloudy"
    assert data.is_precipitating is None
    # The accumulation is still reported — a real measurement of a past hour,
    # dated by `observation_time`. It just is not evidence about now.
    assert data.precipitation_1h == 2.4


async def test_future_dated_inca_rr_does_not_derive_rain(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A negative age is not freshness.

    The bound compared only its upper end, and `age <= INCA_RR_MAX_AGE_SECONDS`
    is satisfied by a negative age too — so an `RR` stamped ahead of `now`
    passed as the freshest reading there is and fed the condition an hour that
    has not happened yet. `_async_get_inca` requests `end=now` so the live API
    does not return one, but nothing in `_merge` enforces that pairing, and
    `observation_time` already clamps every rung to `now` on the same
    principle.
    """
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, exc=TimeoutError)
    aioclient_mock.get(INCA_URL, json=_wet_inca())
    # Two hours BEFORE the 15:00Z stamp the fixture's rain is dated to.
    freezer.move_to("2026-07-15T13:00:00+00:00")
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    # Pinned to the cloud-derived value, not merely "not rainy": with the
    # lower bound removed this derives `rainy` from the future hour, so a
    # loose assertion would pass with the defect present.
    assert data.condition == "cloudy"
    # Still reported as the measurement it is, exactly as in the stale case.
    assert data.precipitation_1h == 2.4


async def test_current_inca_rr_still_derives_rain(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The other side of the bound: a fresh `RR` keeps its fallback.

    Gating staleness must not amount to dropping the fallback — with the
    nowcast down and an analysis whose hour still touches the present, INCA
    remains the best evidence there is and the condition follows it.
    """
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, exc=TimeoutError)
    aioclient_mock.get(INCA_URL, json=_wet_inca())
    # 85 min past the 15:00Z stamp — within the ~90 min a healthy INCA
    # publish cycle reaches, so this is the freshest data the source has and
    # rejecting it would flap the condition once an hour through steady rain.
    freezer.move_to("2026-07-15T16:25:00+00:00")
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.condition == "rainy"
    # Still `None`: the rate gate feeds the condition, never the binary sensor.
    assert data.is_precipitating is None


async def test_a_dry_nowcast_code_outranks_a_wet_inca_rr(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A nowcast reporting `pt` 255 decides, even with no `rr` beside it.

    The INCA `RR` is current and wet, but it only stands in when the nowcast
    observes nothing. Here the nowcast says "no precipitation", so the rain
    symbol is demoted to `cloudy` rather than shown as rain.
    """
    nowcast = load_fixture("nowcast.json")
    parameters = nowcast["features"][0]["properties"]["parameters"]
    parameters["rr"]["data"] = [None for _ in parameters["rr"]["data"]]
    assert set(parameters["pt"]["data"]) == {255.0}
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(4,), symbol=8))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=nowcast)
    aioclient_mock.get(INCA_URL, json=_wet_inca())
    freezer.move_to("2026-07-15T16:25:00+00:00")
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.precipitation_1h == 2.4
    assert data.is_precipitating is False
    assert data.condition == "cloudy"


@pytest.mark.parametrize(
    "clock",
    [
        # 10 and 40 min after the 15:00Z analysis, then 70 and 100 min after
        # it: the condition must not flip as the analysis ages or lands.
        "2026-07-15T15:10:00+00:00",
        "2026-07-15T15:40:00+00:00",
        "2026-07-15T16:10:00+00:00",
        "2026-07-15T16:40:00+00:00",
    ],
)
async def test_a_dry_inca_rr_never_demotes_the_symbol(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    clock: str,
) -> None:
    """With the nowcast down, a dry `RR` is not "observed dry".

    It analyses an hour that ended up to ~90 min ago, so it cannot rule out
    rain that has started since; the rain symbol stands at every clock.
    """
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(3, 4), symbol=8))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, exc=TimeoutError)
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    freezer.move_to(clock)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.weather_symbol == 8
    assert data.precipitation_1h == 0.0
    assert data.condition == "rainy"


async def test_precipitation_1h_is_unknown_without_inca(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No INCA `RR`, no hourly accumulation -- the nowcast cannot stand in.

    Summing the nowcast's own buckets was tried and removed. The endpoint
    serves a single run clamped to its own t0, which sits ~25-35 min back, so
    the sum covered a fraction of an hour and was published as a full one.
    The instantaneous fields are unaffected: they read the matched bucket.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=wet_nowcast(rate_mm=0.5))
    aioclient_mock.get(INCA_URL, status=500)
    await _setup(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.current.data
    assert data.precipitation_1h is None
    assert data.is_precipitating is True


async def test_nowcast_request_reaches_back_past_the_matched_bucket(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The nowcast `start` is anchored to the 15-min grid, one lookback back.

    Unbounded, the endpoint begins at the bucket covering `now` -- exactly one
    stamp at or before it, measured 2026-09-11 at all three of the author's
    locations. That leaves the `RATE_LOOKBACK` peak with nothing to look back
    at, silently reducing it to the matched bucket it exists to widen.

    The anchor is load-bearing, as it is for the AROME request: the API rounds
    a mid-interval `start` *up* to the next stamp, so an unfloored 15:22 would
    come back at 15:30.
    """
    freezer.move_to("2026-07-15T16:07:00+00:00")
    await _setup(hass, mock_config_entry)

    starts = [
        call[1].query["start"]
        for call in mock_api.mock_calls
        if "nowcast-v1-15min-1km" in str(call[1])
    ]
    # 16:07 floors to 16:00; `NOWCAST_LOOKBACK` (RATE_LOOKBACK + one bucket)
    # reaches back to 15:15.
    assert starts == ["2026-07-15T15:15"]
