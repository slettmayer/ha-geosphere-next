"""Tests for the pure condition-derivation functions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.geosphere_next.condition import (
    apparent_temperature,
    derive_condition,
    derive_current_condition,
    dew_point_from_t_rh,
    is_night,
    wind_from_components,
)


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


def test_dew_point_from_t_rh() -> None:
    assert dew_point_from_t_rh(20.0, 50.0) == pytest.approx(9.3)
    # Saturated air: dew point equals the temperature.
    assert dew_point_from_t_rh(20.0, 100.0) == pytest.approx(20.0)
    # RH above 100 (model artifact) clamps instead of exceeding T.
    assert dew_point_from_t_rh(20.0, 104.0) == pytest.approx(20.0)
    assert dew_point_from_t_rh(-5.0, 80.0) == pytest.approx(-7.9, abs=0.1)
    assert dew_point_from_t_rh(None, 50.0) is None
    assert dew_point_from_t_rh(20.0, None) is None
    assert dew_point_from_t_rh(20.0, 0.0) is None
