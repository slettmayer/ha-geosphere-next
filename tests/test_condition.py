"""Tests for the pure condition-derivation functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.geosphere_next.condition import (
    aggregate_daily,
    apparent_temperature,
    derive_condition,
    derive_current_condition,
    is_night,
    wind_from_components,
)
from custom_components.geosphere_next.models import HourlyForecast

VIENNA = ZoneInfo("Europe/Vienna")


@pytest.mark.parametrize(
    ("precip", "snow", "tcc", "cape", "gust", "night", "expected"),
    [
        # clear / cloud buckets
        (0.0, 0.0, 0.0, 0.0, 0.0, False, "sunny"),
        (0.0, 0.0, 0.0, 0.0, 0.0, True, "clear-night"),
        (0.0, 0.0, 12.5, None, None, False, "sunny"),
        (0.0, 0.0, 40.0, 0.0, 0.0, False, "partlycloudy"),
        (0.0, 0.0, 62.5, 0.0, 0.0, False, "partlycloudy"),
        (0.0, 0.0, 80.0, 0.0, 0.0, True, "cloudy"),
        # precipitation
        (0.5, 0.0, 90.0, 0.0, 0.0, False, "rainy"),
        (4.0, 0.0, 90.0, 0.0, 0.0, False, "pouring"),
        (0.5, 0.0, 90.0, 1500.0, 0.0, False, "lightning-rainy"),
        (0.5, 0.5, 90.0, 0.0, 0.0, False, "snowy"),
        (1.0, 0.3, 90.0, 0.0, 0.0, False, "snowy-rainy"),
        # dry thunder / wind
        (0.0, 0.0, 80.0, 1500.0, 0.0, False, "lightning"),
        (0.0, 0.0, 30.0, 0.0, 16.0, False, "windy"),
        (0.0, 0.0, 80.0, 0.0, 16.0, False, "windy-variant"),
        # missing cloud data
        (0.0, 0.0, None, 0.0, 0.0, False, None),
    ],
)
def test_derive_condition(precip, snow, tcc, cape, gust, night, expected) -> None:
    assert derive_condition(precip, snow, tcc, cape, gust, night) == expected


def test_current_condition_pt_override_rain() -> None:
    """A precipitation-type code other than 255 forces a precipitation state."""
    assert (
        derive_current_condition(
            precipitation_type=1,
            precipitation_rate_mm_h=0.4,
            temperature=12.0,
            humidity=80.0,
            wind_speed=3.0,
            cloud_coverage=10.0,  # cloud says clear, pt wins
            cape=0.0,
            gust_speed=5.0,
            night=False,
        )
        == "rainy"
    )


def test_current_condition_pt_override_snow_by_temperature() -> None:
    assert (
        derive_current_condition(
            precipitation_type=3,
            precipitation_rate_mm_h=1.0,
            temperature=-1.0,
            humidity=90.0,
            wind_speed=3.0,
            cloud_coverage=100.0,
            cape=0.0,
            gust_speed=5.0,
            night=False,
        )
        == "snowy"
    )


def test_current_condition_no_precip_falls_through() -> None:
    assert (
        derive_current_condition(
            precipitation_type=255,
            precipitation_rate_mm_h=0.0,
            temperature=20.0,
            humidity=50.0,
            wind_speed=3.0,
            cloud_coverage=5.0,
            cape=0.0,
            gust_speed=5.0,
            night=False,
        )
        == "sunny"
    )


def test_current_condition_fog() -> None:
    assert (
        derive_current_condition(
            precipitation_type=255,
            precipitation_rate_mm_h=0.0,
            temperature=2.0,
            humidity=99.0,
            wind_speed=0.5,
            cloud_coverage=100.0,
            cape=0.0,
            gust_speed=1.0,
            night=False,
        )
        == "fog"
    )


def test_wind_from_components() -> None:
    speed, bearing = wind_from_components(0.0, -5.0)
    assert speed == 5.0
    assert bearing == 0.0  # wind FROM the north blows toward -v
    speed, bearing = wind_from_components(-5.0, 0.0)
    assert bearing == 90.0  # from the east
    assert wind_from_components(None, 1.0) == (None, None)


def test_is_night_vienna() -> None:
    noon = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    midnight = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    assert not is_night(48.22, 16.37, noon)
    assert is_night(48.22, 16.37, midnight)


def test_apparent_temperature() -> None:
    assert apparent_temperature(30.0, 50.0, 2.0) == pytest.approx(31.6, abs=0.3)
    assert apparent_temperature(None, 50.0, 2.0) is None


def _hour(ts: datetime, **kwargs) -> HourlyForecast:
    defaults = {
        "temperature": 20.0,
        "templow": 18.0,
        "temphigh": 22.0,
        "humidity": 60.0,
        "precipitation": 0.0,
        "snow": 0.0,
        "wind_speed": 3.0,
        "wind_bearing": 180.0,
        "wind_gust_speed": 6.0,
        "cloud_coverage": 20.0,
        "cape": 0.0,
        "condition": "partlycloudy",
    }
    defaults.update(kwargs)
    return HourlyForecast(datetime=ts, **defaults)


def test_aggregate_daily() -> None:
    # Two full days of hourly data starting at local midnight.
    start = datetime(2026, 7, 16, 0, 0, tzinfo=VIENNA).astimezone(UTC)
    hours = []
    for i in range(48):
        ts = start + timedelta(hours=i)
        rainy_afternoon = 12 <= (i % 24) <= 16 and i >= 24
        hours.append(
            _hour(
                ts,
                temphigh=25.0 + (i % 24) / 10,
                templow=14.0 - (i % 24) / 10,
                precipitation=1.2 if rainy_afternoon else 0.0,
                condition="rainy" if rainy_afternoon else "partlycloudy",
            )
        )

    daily = aggregate_daily(hours, VIENNA)
    assert len(daily) == 2
    day1, day2 = daily
    assert day1.temperature == pytest.approx(27.3)
    assert day1.templow == pytest.approx(11.7)
    assert day1.condition == "partlycloudy"
    assert day1.precipitation == 0.0
    # Day 2 has a 5-hour rainy afternoon -> severe condition wins.
    assert day2.condition == "rainy"
    assert day2.precipitation == pytest.approx(6.0)


def test_aggregate_daily_drops_short_days() -> None:
    start = datetime(2026, 7, 16, 21, 0, tzinfo=VIENNA).astimezone(UTC)
    hours = [_hour(start + timedelta(hours=i)) for i in range(3)]
    assert aggregate_daily(hours, VIENNA) == []


def test_aggregate_daily_clear_night_becomes_sunny() -> None:
    start = datetime(2026, 7, 16, 0, 0, tzinfo=VIENNA).astimezone(UTC)
    hours = [
        _hour(start + timedelta(hours=i), condition="clear-night") for i in range(24)
    ]
    daily = aggregate_daily(hours, VIENNA)
    assert daily[0].condition == "sunny"
