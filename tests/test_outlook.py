"""Tests for the pure forecast-outlook functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.geosphere_next.models import HourlyForecast
from custom_components.geosphere_next.outlook import (
    hour_at,
    max_cape,
    max_gust,
    next_thunderstorm,
    thunderstorm_outlook,
)

NOW = datetime(2026, 7, 15, 16, 30, tzinfo=UTC)


def _hour(
    offset_hours: int,
    *,
    gust: float | None = None,
    cape: float | None = None,
    precipitation: float | None = None,
    symbol: int | None = None,
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


def test_next_thunderstorm_returns_first_thunder_symbol_hour_and_its_cape() -> None:
    hourly = [
        _hour(0, symbol=5, cape=100.0),
        _hour(4, symbol=26, cape=1800.0),
        _hour(6, symbol=28, cape=2500.0),
    ]
    when, cape = next_thunderstorm(hourly, NOW)
    assert when == datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
    assert cape == 1800.0


def test_next_thunderstorm_scans_the_whole_horizon() -> None:
    """Not window-limited — a storm 40 h out is still reported."""
    hourly = [_hour(0, symbol=1), _hour(40, symbol=27)]
    assert next_thunderstorm(hourly, NOW)[0] == datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


def test_next_thunderstorm_ignores_past_hours() -> None:
    hourly = [_hour(-5, symbol=26), _hour(3, symbol=5)]
    assert next_thunderstorm(hourly, NOW) == (None, None)


def test_next_thunderstorm_none_when_calm() -> None:
    assert next_thunderstorm([_hour(0, symbol=1)], NOW) == (None, None)


def test_next_thunderstorm_includes_the_in_progress_hour() -> None:
    """A storm in the hour already under way must not be skipped.

    NOW is 16:30 and the in-progress hour is stamped 16:00, so a naive
    `hour.datetime < now` floor would drop it.
    """
    hourly = [_hour(0, symbol=26, cape=1600.0), _hour(3, symbol=5)]
    when, cape = next_thunderstorm(hourly, NOW)
    assert when == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
    assert cape == 1600.0


def test_every_thunder_code_counts_including_thundersnow() -> None:
    """26-32 all count, the sleet and snow thunderstorms (29-32) included."""
    for symbol in range(26, 33):
        hourly = [_hour(0, symbol=symbol)]
        assert thunderstorm_outlook(hourly, 1, NOW) is True, symbol
        assert next_thunderstorm(hourly, NOW)[0] is not None, symbol


def test_heavy_rain_and_snow_symbols_are_not_storms() -> None:
    """The heaviest non-thunder codes stay "no storm", whatever the CAPE."""
    hourly = [
        _hour(0, symbol=10, cape=2500.0, precipitation=8.0),
        _hour(1, symbol=25, cape=2500.0, precipitation=3.0),
    ]
    assert thunderstorm_outlook(hourly, 1, NOW) is False
    assert next_thunderstorm(hourly, NOW) == (None, None)


def test_thunderstorm_outlook_is_unknown_without_usable_hours() -> None:
    """An empty or undecidable window must not read as a confident "no storm"."""
    assert thunderstorm_outlook([], 1, NOW) is None
    # Hours exist but carry no symbol; CAPE alone does not decide.
    assert thunderstorm_outlook([_hour(0, cape=10.0), _hour(1)], 1, NOW) is None
    # Only hours outside the window -> nothing to judge.
    assert thunderstorm_outlook([_hour(6, symbol=1)], 1, NOW) is None


def test_thunderstorm_outlook_distinguishes_no_storm_from_no_data() -> None:
    hourly = [_hour(0, symbol=5), _hour(5, symbol=26)]
    assert thunderstorm_outlook(hourly, 1, NOW) is False
    assert thunderstorm_outlook(hourly, 12, NOW) is True
    # One decidable hour is enough to answer for the window.
    assert thunderstorm_outlook([_hour(0), _hour(1, symbol=3)], 1, NOW) is False


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
