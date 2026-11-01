"""Tests for the pure forecast-outlook functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.geosphere_next.models import HourlyForecast
from custom_components.geosphere_next.outlook import (
    ensemble_is_current,
    hour_at,
    max_cape,
    max_gust,
    next_thunderstorm,
    thunderstorm_outlook,
)

NOW = datetime(2026, 7, 15, 16, 30, tzinfo=UTC)
CURRENT_RUN = NOW - timedelta(hours=4)
STALE_RUN = NOW - timedelta(hours=13)


def _hour(
    offset_hours: int,
    *,
    gust: float | None = None,
    cape: float | None = None,
    precipitation: float | None = None,
    symbol: int | None = None,
    cape_p90: float | None = None,
    precipitation_p90: float | None = None,
) -> HourlyForecast:
    """One forecast hour at the top of the hour, `offset_hours` from 16:00Z."""
    return HourlyForecast(
        datetime=datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
        + timedelta(hours=offset_hours),
        temperature=None,
        humidity=None,
        precipitation=precipitation,
        snow=None,
        wind_speed=None,
        wind_bearing=None,
        wind_gust_speed=gust,
        cloud_coverage=None,
        cape=cape,
        weather_symbol=symbol,
        ensemble_cape_p90=cape_p90,
        ensemble_precipitation_p90=precipitation_p90,
    )


def test_max_gust_includes_the_in_progress_hour() -> None:
    """NOW is 16:30 but the 16:00 hour is still in progress and must count."""
    hourly = [_hour(0, gust=20.0), _hour(1, gust=5.0)]
    value, when = max_gust(hourly, 1, NOW)
    assert value == 20.0
    assert when == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


def test_max_gust_respects_the_window() -> None:
    """A bigger gust beyond the horizon must not leak into a short window."""
    hourly = [_hour(0, gust=5.0), _hour(1, gust=9.0), _hour(6, gust=30.0)]
    assert max_gust(hourly, 1, NOW)[0] == 9.0
    assert max_gust(hourly, 12, NOW)[0] == 30.0


def test_max_gust_skips_past_hours_and_none_values() -> None:
    hourly = [_hour(-3, gust=40.0), _hour(0, gust=None), _hour(1, gust=7.0)]
    assert max_gust(hourly, 12, NOW) == (7.0, datetime(2026, 7, 15, 17, 0, tzinfo=UTC))


def test_max_gust_empty_window_returns_none() -> None:
    assert max_gust([], 12, NOW) == (None, None)
    assert max_gust([_hour(0, gust=None)], 12, NOW) == (None, None)


def test_max_cape() -> None:
    hourly = [_hour(0, cape=100.0), _hour(2, cape=1200.0), _hour(20, cape=3000.0)]
    assert max_cape(hourly, 12, NOW) == 1200.0
    assert max_cape([], 12, NOW) is None


def _at(offset_hours: int) -> datetime:
    return datetime(2026, 7, 15, 16, 0, tzinfo=UTC) + timedelta(hours=offset_hours)


STORM_PAIR = {"cape_p90": 1500.0, "precipitation_p90": 0.5}


def test_ensemble_is_current_within_its_age_bound() -> None:
    assert ensemble_is_current(CURRENT_RUN, NOW)
    assert ensemble_is_current(NOW - timedelta(hours=12), NOW)
    assert not ensemble_is_current(STALE_RUN, NOW)
    assert not ensemble_is_current(None, NOW)


def test_symbol_only() -> None:
    hourly = [_hour(0, symbol=5), _hour(1, symbol=26)]
    assert thunderstorm_outlook(hourly, 1, NOW, CURRENT_RUN) == (True, "symbol")
    assert next_thunderstorm(hourly, NOW, CURRENT_RUN) == (_at(1), "symbol")


def test_ensemble_only() -> None:
    """Some members develop a storm the deterministic run does not."""
    hourly = [_hour(0, symbol=5), _hour(1, symbol=8, **STORM_PAIR)]
    assert thunderstorm_outlook(hourly, 1, NOW, CURRENT_RUN) == (True, "ensemble")
    assert next_thunderstorm(hourly, NOW, CURRENT_RUN) == (_at(1), "ensemble")


def test_both() -> None:
    """In the same hour, or in different hours of the window."""
    same_hour = [_hour(0, symbol=26, **STORM_PAIR)]
    assert thunderstorm_outlook(same_hour, 1, NOW, CURRENT_RUN) == (True, "both")
    assert next_thunderstorm(same_hour, NOW, CURRENT_RUN) == (_at(0), "both")
    different_hours = [_hour(0, symbol=27), _hour(1, symbol=5, **STORM_PAIR)]
    assert thunderstorm_outlook(different_hours, 1, NOW, CURRENT_RUN) == (
        True,
        "both",
    )
    # `next_thunderstorm` names the signals of its own hour.
    assert next_thunderstorm(different_hours, NOW, CURRENT_RUN) == (
        _at(0),
        "symbol",
    )


def test_none() -> None:
    hourly = [_hour(0, symbol=1, cape_p90=20.0, precipitation_p90=0.0)]
    assert thunderstorm_outlook(hourly, 1, NOW, CURRENT_RUN) == (False, None)
    assert next_thunderstorm(hourly, NOW, CURRENT_RUN) == (None, None)


def test_an_ensemble_13_hours_old_is_ignored() -> None:
    hourly = [_hour(0, symbol=26), _hour(1, symbol=5, **STORM_PAIR)]
    assert thunderstorm_outlook(hourly, 1, NOW, STALE_RUN) == (True, "symbol")
    ensemble_only = [_hour(0, symbol=5, **STORM_PAIR)]
    assert thunderstorm_outlook(ensemble_only, 1, NOW, STALE_RUN) == (False, None)
    assert next_thunderstorm(ensemble_only, NOW, STALE_RUN) == (None, None)


def test_no_ensemble_leaves_the_symbol() -> None:
    hourly = [_hour(0, symbol=5, **STORM_PAIR), _hour(3, symbol=28)]
    assert thunderstorm_outlook(hourly, 1, NOW, None) == (False, None)
    assert next_thunderstorm(hourly, NOW, None) == (_at(3), "symbol")


def test_no_data_is_unknown() -> None:
    """Unknown only when no forecast hour falls in the window."""
    assert thunderstorm_outlook([], 1, NOW, CURRENT_RUN) == (None, None)
    assert thunderstorm_outlook([_hour(6, symbol=26)], 1, NOW, CURRENT_RUN) == (
        None,
        None,
    )
    assert next_thunderstorm([], NOW, CURRENT_RUN) == (None, None)


def test_a_missing_or_unknown_symbol_is_no_storm() -> None:
    hourly = [_hour(0), _hour(1, symbol=99)]
    assert thunderstorm_outlook(hourly, 1, NOW, CURRENT_RUN) == (False, None)


def test_every_thunder_code_counts_including_thundersnow() -> None:
    """26-32 all count, the sleet and snow thunderstorms (29-32) included."""
    for symbol in range(26, 33):
        hourly = [_hour(0, symbol=symbol)]
        assert thunderstorm_outlook(hourly, 1, NOW, None) == (True, "symbol"), symbol


def test_heavy_rain_and_snow_symbols_are_not_storms() -> None:
    """The heaviest non-thunder codes stay "no storm", whatever the CAPE."""
    hourly = [
        _hour(0, symbol=10, cape=2500.0, precipitation=8.0),
        _hour(1, symbol=25, cape=2500.0, precipitation=3.0),
    ]
    assert thunderstorm_outlook(hourly, 1, NOW, None) == (False, None)
    assert next_thunderstorm(hourly, NOW, None) == (None, None)


def test_the_ensemble_needs_both_cape_and_precipitation() -> None:
    """CAPE alone is a routine dry summer afternoon, not a storm."""
    hourly = [
        _hour(0, symbol=1, cape_p90=3000.0, precipitation_p90=0.0),
        _hour(1, symbol=3, cape_p90=999.9, precipitation_p90=5.0),
        _hour(2, symbol=3, cape_p90=3000.0, precipitation_p90=None),
    ]
    assert thunderstorm_outlook(hourly, 2, NOW, CURRENT_RUN) == (False, None)


def test_the_ensemble_thresholds_are_inclusive() -> None:
    hourly = [_hour(0, symbol=5, cape_p90=1000.0, precipitation_p90=0.1)]
    assert thunderstorm_outlook(hourly, 1, NOW, CURRENT_RUN) == (True, "ensemble")


def test_a_storm_beyond_the_window_does_not_count() -> None:
    hourly = [_hour(0, symbol=5), _hour(5, symbol=26)]
    assert thunderstorm_outlook(hourly, 1, NOW, None) == (False, None)
    assert thunderstorm_outlook(hourly, 12, NOW, None) == (True, "symbol")


def test_next_thunderstorm_scans_the_whole_horizon() -> None:
    """Not window-limited — a storm 40 h out is still reported."""
    hourly = [_hour(0, symbol=1), _hour(40, symbol=27)]
    assert next_thunderstorm(hourly, NOW, None)[0] == datetime(
        2026, 7, 17, 8, 0, tzinfo=UTC
    )


def test_next_thunderstorm_ignores_past_hours() -> None:
    hourly = [_hour(-5, symbol=26), _hour(3, symbol=5)]
    assert next_thunderstorm(hourly, NOW, None) == (None, None)


def test_next_thunderstorm_includes_the_in_progress_hour() -> None:
    """NOW is 16:30; a storm in the hour stamped 16:00 is still reported."""
    hourly = [_hour(0, symbol=26), _hour(3, symbol=5)]
    assert next_thunderstorm(hourly, NOW, None) == (_at(0), "symbol")


def test_hour_at_selects_the_in_progress_hour() -> None:
    """NOW is 16:30; the hour stamped 16:00 is the one covering it."""
    hourly = [_hour(0, cape=100.0), _hour(1, cape=200.0)]
    selected = hour_at(hourly, NOW)
    assert selected is not None
    assert selected.datetime == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
    assert selected.cape == 100.0


def test_hour_at_follows_the_clock() -> None:
    """Later in the day the same series yields the hour then in progress."""
    hourly = [_hour(offset, cape=float(offset)) for offset in range(6)]
    selected = hour_at(hourly, NOW + timedelta(hours=3))
    assert selected is not None
    assert selected.datetime == datetime(2026, 7, 15, 19, 0, tzinfo=UTC)
    assert selected.cape == 3.0


def test_hour_at_returns_none_without_a_match() -> None:
    """An empty series, one that aged out, and one not yet reached."""
    assert hour_at([], NOW) is None
    assert hour_at([_hour(-3), _hour(-2)], NOW) is None
    assert hour_at([_hour(2), _hour(3)], NOW) is None
