"""Tests for the pure forecast-outlook functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.geosphere_next.models import HourlyForecast
from custom_components.geosphere_next.outlook import (
    max_cape,
    max_gust,
    next_thunderstorm,
    thunderstorm_outlook,
    thunderstorm_within,
)

NOW = datetime(2026, 7, 15, 16, 30, tzinfo=UTC)


def _hour(
    offset_hours: int,
    *,
    gust: float | None = None,
    cape: float | None = None,
    cin: float | None = None,
    precipitation: float | None = None,
    condition: str | None = None,
) -> HourlyForecast:
    """One forecast hour at the top of the hour, `offset_hours` from 16:00Z."""
    return HourlyForecast(
        datetime=datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
        + timedelta(hours=offset_hours),
        temperature=None,
        templow=None,
        temphigh=None,
        humidity=None,
        precipitation=precipitation,
        snow=None,
        wind_speed=None,
        wind_bearing=None,
        wind_gust_speed=gust,
        cloud_coverage=None,
        cape=cape,
        cin=cin,
        condition=condition,
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


def test_next_thunderstorm_returns_first_lightning_hour_and_its_cape() -> None:
    hourly = [
        _hour(0, condition="cloudy", cape=100.0),
        _hour(4, condition="lightning-rainy", cape=1800.0),
        _hour(6, condition="lightning", cape=2500.0),
    ]
    when, cape = next_thunderstorm(hourly, NOW)
    assert when == datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
    assert cape == 1800.0


def test_next_thunderstorm_scans_the_whole_horizon() -> None:
    """Not window-limited — a storm 40 h out is still reported."""
    hourly = [_hour(0, condition="sunny"), _hour(40, condition="lightning")]
    assert next_thunderstorm(hourly, NOW)[0] == datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


def test_next_thunderstorm_ignores_past_hours() -> None:
    hourly = [_hour(-5, condition="lightning"), _hour(3, condition="cloudy")]
    assert next_thunderstorm(hourly, NOW) == (None, None)


def test_next_thunderstorm_none_when_calm() -> None:
    assert next_thunderstorm([_hour(0, condition="sunny")], NOW) == (None, None)


def test_next_thunderstorm_includes_the_in_progress_hour() -> None:
    """A storm in the hour already under way must not be skipped.

    NOW is 16:30 and the in-progress hour is stamped 16:00, so a naive
    `hour.datetime < now` floor would drop it.
    """
    hourly = [
        _hour(0, condition="lightning", cape=1600.0),
        _hour(3, condition="cloudy"),
    ]
    when, cape = next_thunderstorm(hourly, NOW)
    assert when == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
    assert cape == 1600.0


def test_thunderstorm_within() -> None:
    hourly = [_hour(0, condition="cloudy"), _hour(5, condition="lightning")]
    assert thunderstorm_within(hourly, 1, NOW) is False
    assert thunderstorm_within(hourly, 12, NOW) is True


def test_thundersnow_is_detected_despite_the_snowy_condition() -> None:
    """`derive_condition` returns `snowy` before it ever checks thunder.

    A snow hour with ample CAPE, weak inhibition and precipitation is a
    thundersnow hour — the condition string alone would miss it.
    """
    hourly = [_hour(0, condition="snowy", cape=1500.0, cin=0.0, precipitation=0.8)]
    assert thunderstorm_within(hourly, 1, NOW) is True
    assert next_thunderstorm(hourly, NOW)[0] == datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


def test_thunder_is_detected_when_cloud_cover_is_missing() -> None:
    """`derive_condition` returns None without `tcc`, hiding a real storm."""
    hourly = [_hour(0, condition=None, cape=1500.0, cin=0.0, precipitation=0.5)]
    assert thunderstorm_within(hourly, 1, NOW) is True


def test_dry_high_cape_without_precipitation_is_not_a_storm() -> None:
    """The false-positive guard: CAPE alone is a routine summer afternoon.

    Vienna reaches CAPE >= 1000 J/kg with weak inhibition on many days that
    produce no storm; without forecast precipitation the model is not saying
    convection is happening.
    """
    hourly = [
        _hour(0, condition="partlycloudy", cape=2500.0, cin=0.0, precipitation=0.0),
        _hour(1, condition="sunny", cape=3000.0, cin=0.0, precipitation=None),
    ]
    assert thunderstorm_within(hourly, 1, NOW) is False
    assert next_thunderstorm(hourly, NOW) == (None, None)


def test_capped_cape_with_precipitation_is_not_a_storm() -> None:
    """A strong lid (cin <= -50) blocks convection even with rain falling."""
    hourly = [_hour(0, condition="snowy", cape=2500.0, cin=-80.0, precipitation=1.0)]
    assert thunderstorm_within(hourly, 1, NOW) is False


def test_thunderstorm_outlook_is_unknown_without_usable_hours() -> None:
    """An empty or undecidable window must not read as a confident "no storm"."""
    assert thunderstorm_outlook([], 1, NOW) is None
    # Hours exist but carry neither a condition nor CAPE.
    assert thunderstorm_outlook([_hour(0), _hour(1)], 1, NOW) is None
    # Only hours outside the window -> nothing to judge.
    assert thunderstorm_outlook([_hour(6, condition="sunny")], 1, NOW) is None


def test_thunderstorm_outlook_distinguishes_no_storm_from_no_data() -> None:
    hourly = [_hour(0, condition="cloudy"), _hour(5, condition="lightning")]
    assert thunderstorm_outlook(hourly, 1, NOW) is False
    assert thunderstorm_outlook(hourly, 12, NOW) is True
    # CAPE alone (no derived condition) is still a decidable hour.
    assert thunderstorm_outlook([_hour(0, cape=10.0)], 1, NOW) is False
