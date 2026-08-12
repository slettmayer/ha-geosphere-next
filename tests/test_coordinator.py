"""Tests for coordinator processing via a full config-entry setup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .conftest import (
    AROME_URL,
    ENSEMBLE_URL,
    INCA_URL,
    NOWCAST_URL,
    load_fixture,
    stormy_arome,
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
    behaviour, `outlook.hour_at`, and the current condition's cloud/CAPE/CIN
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
        if "nwp-v1-1h-2500m" in str(call[1]) or "ensemble-v1-1h-2500m" in str(call[1])
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

    # Fixture: reference 12:00Z, timestamps 15:00Z..+60h. At frozen 16:00Z the
    # forecast starts at the in-progress hour 16:00Z (index 1); index 0 (15:00Z)
    # precedes the cutoff. The final stamp (2026-07-18T00:00Z) cannot be
    # emitted -- its interval fields would live on a successor that is not in
    # the series -- so 56 rows survive, ending 2026-07-17T23:00Z.
    assert len(data.hourly) == 56
    assert data.hourly[-1].datetime.isoformat() == "2026-07-17T23:00:00+00:00"

    first = data.hourly[0]
    assert first.datetime.isoformat() == "2026-07-15T16:00:00+00:00"
    # Instantaneous at the stamp.
    assert first.temperature == 28.6
    # Interval fields come from the *following* stamp, because they describe
    # the interval ending at it: rr_acc[2] - rr_acc[1] = 0.479 - 0.479. The
    # fixture's only early rain (0.479 mm) accumulated between 15:00Z and
    # 16:00Z, so it belongs to the hour that has already elapsed -- reading it
    # at index 1 would report rain at 16:00Z that has stopped falling.
    assert first.precipitation == 0.0
    assert first.condition == "sunny"
    # tcc 0.0 -> 0 %
    assert first.cloud_coverage == 0
    # Magnus from t2m 28.6 / rh2m 50.1.
    assert first.dew_point == pytest.approx(17.2)
    # Snow limit and weather symbol are instantaneous, and are read off the same
    # row that becomes `current` -- 16:00Z here, not the series' first stamp.
    assert data.snow_limit == pytest.approx(3371.9)
    assert data.weather_symbol == 26
    assert data.current is first

    # Stepped probability from the ensemble rr percentiles, read one stamp on
    # -- the percentiles cover the hour ending at their stamp, like AROME's
    # accumulations. The fixture's 16:00 entry is all wet (95) and belongs to
    # the 15:00 hour, which the cutoff has already dropped; the 16:00 row gets
    # the 17:00 entry instead. Then: only p90 wet / all dry / p90 below
    # threshold.
    assert first.precipitation_probability == 70
    assert data.hourly[1].precipitation_probability == 30
    assert data.hourly[2].precipitation_probability == 0
    assert data.hourly[3].precipitation_probability == 0
    assert data.hourly[4].precipitation_probability == 0


async def test_forecast_interval_fields_describe_the_hour_they_start(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """Accumulations, gusts and min/max belong to the hour beginning at the stamp.

    AROME stamps `rr_acc`/`snow_acc` as run-accumulations and `ugust`/`vgust`,
    `mnt2m`/`mxt2m` as "the last forecast intervall", so all of them describe
    the interval *ending* at their stamp. A row stamped T covers T..T+1h, so
    its interval fields have to be read one step later. Getting this wrong
    reports rain that already stopped and the previous hour's gust peak.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    hourly = mock_config_entry.runtime_data.forecast.data.hourly

    by_ts = {hour.datetime.isoformat(): hour for hour in hourly}
    # Fixture rr_acc climbs 0.99 -> 1.91 -> 3.552 across 06:00Z/07:00Z/08:00Z,
    # so the hour *starting* 06:00Z catches 0.92 mm and the one starting
    # 07:00Z catches 1.64 mm.
    assert by_ts["2026-07-16T06:00:00+00:00"].precipitation == 0.92
    assert by_ts["2026-07-16T07:00:00+00:00"].precipitation == 1.64
    # Same rule for the min/max pair: mnt2m/mxt2m at the 07:00Z stamp describe
    # 06:00Z-07:00Z, so the row starting 06:00Z takes the 07:00Z values.
    assert by_ts["2026-07-16T06:00:00+00:00"].temphigh == pytest.approx(22.8)
    assert by_ts["2026-07-16T06:00:00+00:00"].templow == pytest.approx(22.62)


async def test_precipitation_probability_matches_the_row_it_is_reported_with(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """PoP is shifted with the amount, not left a stamp behind.

    The C-LAEF percentiles are interval values too ("in the last forecast
    period"), so they need the same one-step shift as `rr_acc`. Left unshifted
    they pair each row's amount with the previous hour's probability -- the
    forecast then shows a dry hour at 95 %, or rain at 0 %.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    hourly = mock_config_entry.runtime_data.forecast.data.hourly

    by_ts = {hour.datetime.isoformat(): hour for hour in hourly}
    # The fixture's wet ensemble hours are its first two: 16:00Z is all wet and
    # 17:00Z has a wet median. Both describe the hour ending at their stamp, so
    # they belong to the rows starting 15:00Z (dropped, already elapsed) and
    # 16:00Z. The 17:00Z row falls to the 18:00Z entry, only p90 wet.
    assert by_ts["2026-07-15T16:00:00+00:00"].precipitation_probability == 70
    assert by_ts["2026-07-15T17:00:00+00:00"].precipitation_probability == 30


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
    for name in ("rr_p10", "rr_p50", "rr_p90"):
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
    # Cloud cover comes from the AROME fallback (nowcast has none): 0 %.
    assert data.cloud_coverage == 0
    assert data.condition == "sunny"
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
    """The lull between cells of an active storm still reads as a storm.

    The matched bucket reads 0.0 while the one 15 min earlier caught 2 mm
    (8 mm/h). Taking the matched bucket alone reports 0 mm/h, which starves
    the downpour override that lets observed rain overrule a modelled CIN lid.
    """
    freezer.move_to(FROZEN_NOW)
    # Capped, so only the observed rate can carry it to `lightning-rainy`.
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(1,), cin=-80.0))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=_storm_nowcast([2.0, 0.0]))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.current.data.condition == "lightning-rainy"


async def test_a_shower_that_already_ended_does_not_derive_a_storm(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Rain that stopped must not keep driving the condition.

    INCA's `RR` is a total over the whole past hour, so 6 mm that fell early
    in it and stopped is still on the books while only drizzle continues --
    enough to keep `pt` non-zero. Reading that total as an instantaneous rate
    would clear POURING_MM_PER_H and derive a thunderstorm from a capped,
    drizzling sky. Every bucket inside RATE_LOOKBACK is dry, so it must not.
    """
    inca = load_fixture("inca.json")
    inca["features"][0]["properties"]["parameters"]["RR"]["data"] = [6.0] * len(
        inca["timestamps"]
    )

    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(1,), cin=-80.0))
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


async def test_cin_is_populated_from_the_response(
    hass: HomeAssistant, mock_config_entry, mock_api, freezer: FrozenDateTimeFactory
) -> None:
    """`cin` must actually arrive, not silently degrade to all-None.

    `GeoSphereResponse.series()` returns `[None] * len(timestamps)` for an
    absent parameter and the thunder gate treats None as uncapped, so a
    renamed or typo'd `cin` key would turn the gate into a no-op with a green
    suite. The recorded fixture's `cin` ranges -49.5..0.0 J/kg.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    values = [hour.cin for hour in mock_config_entry.runtime_data.forecast.data.hourly]

    assert any(value is not None for value in values)
    assert min(value for value in values if value is not None) == pytest.approx(-49.5)
    assert max(value for value in values if value is not None) == pytest.approx(0.0)
    # And it reaches the current conditions, whose `cin` comes from AROME.
    assert mock_config_entry.runtime_data.current.data.cin is not None
    # The mocker ignores the query string, so also pin that `cin` is requested
    # — dropping it from AROME_PARAMETERS would otherwise stay invisible here.
    arome_urls = [
        str(call[1])
        for call in mock_api.mock_calls
        if "nwp-v1-1h-2500m" in str(call[1])
    ]
    assert arome_urls
    assert all("cin" in url for url in arome_urls)


@pytest.mark.parametrize(
    ("cin", "expected"),
    [
        # Uncapped: ample CAPE plus rain derives a thunderstorm...
        (0.0, "lightning-rainy"),
        # ...while a strong lid (below -CAP_CIN_JKG) keeps it plain rain.
        (-80.0, "rainy"),
    ],
)
async def test_cin_gate_changes_the_derived_condition(
    hass: HomeAssistant,
    mock_config_entry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    cin: float,
    expected: str,
) -> None:
    """End-to-end proof that the gate is wired, not just unit-tested.

    `stormy_arome` wets hour 1 of the fixture (16:00Z) so the derivation can
    reach `lightning-rainy`; only its CAPE and CIN vary across the cases.
    """
    freezer.move_to(FROZEN_NOW)
    aioclient_mock.get(AROME_URL, json=stormy_arome(indexes=(1,), cin=cin))
    aioclient_mock.get(ENSEMBLE_URL, json=load_fixture("ensemble.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    aioclient_mock.get(INCA_URL, json=load_fixture("inca.json"))
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.forecast.data.hourly[0].condition == expected


async def test_current_arome_fields_follow_the_clock(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """AROME-sourced current fields track the hour, not the forecast fetch.

    The current coordinator runs every 15 min while the forecast one can be
    180 min apart, so reading the "step 0" snapshot captured at fetch time
    would leave cloud cover, CAPE and CIN — and with them the derived
    condition — up to 3 h stale.
    """
    freezer.move_to(FROZEN_NOW)
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.current

    def arome_calls() -> int:
        return sum("nwp-v1-1h-2500m" in str(call[1]) for call in mock_api.mock_calls)

    baseline = arome_calls()
    # Fixture hour 16:00Z: tcc 0.0 -> 0 %, cape 61.7, cin 0.0.
    assert coordinator.data.cloud_coverage == 0
    assert coordinator.data.cape == pytest.approx(61.7)
    assert coordinator.data.cin == pytest.approx(0.0)

    # Three hours on, without refetching the forecast: hour 19:00Z carries
    # tcc 0.8 -> 80 %, cape 106.2, cin -49.5.
    freezer.move_to("2026-07-15T19:30:00+00:00")
    await coordinator.async_refresh()
    assert arome_calls() == baseline
    assert coordinator.data.cloud_coverage == 80
    assert coordinator.data.cape == pytest.approx(106.2)
    assert coordinator.data.cin == pytest.approx(-49.5)


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
    assert coordinator.data.cin == step_zero.cin
