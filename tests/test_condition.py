"""Tests for the pure condition-derivation functions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.geosphere_next.condition import (
    apparent_temperature,
    derive_condition,
    derive_current_condition,
    derive_precipitation_type,
    dew_point_from_t_rh,
    is_night,
    is_precipitating,
    wind_from_components,
)


@pytest.mark.parametrize(
    ("precip", "snow", "tcc", "cape", "cin", "gust", "night", "expected"),
    [
        # clear / cloud buckets
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, "sunny"),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, True, "clear-night"),
        (0.0, 0.0, 12.5, None, None, None, False, "sunny"),
        (0.0, 0.0, 40.0, 0.0, 0.0, 0.0, False, "partlycloudy"),
        (0.0, 0.0, 62.5, 0.0, 0.0, 0.0, False, "partlycloudy"),
        (0.0, 0.0, 80.0, 0.0, 0.0, 0.0, True, "cloudy"),
        # precipitation
        (0.5, 0.0, 90.0, 0.0, 0.0, 0.0, False, "rainy"),
        (4.0, 0.0, 90.0, 0.0, 0.0, 0.0, False, "pouring"),
        (0.5, 0.0, 90.0, 1500.0, 0.0, 0.0, False, "lightning-rainy"),
        (0.5, 0.5, 90.0, 0.0, 0.0, 0.0, False, "snowy"),
        (1.0, 0.3, 90.0, 0.0, 0.0, 0.0, False, "snowy-rainy"),
        # dry thunder / wind
        (0.0, 0.0, 80.0, 1500.0, 0.0, 0.0, False, "lightning"),
        (0.0, 0.0, 30.0, 0.0, 0.0, 16.0, False, "windy"),
        (0.0, 0.0, 80.0, 0.0, 0.0, 16.0, False, "windy-variant"),
        # missing cloud data
        (0.0, 0.0, None, 0.0, 0.0, 0.0, False, None),
        # capped: ample CAPE but strong inhibition -> no thunder
        (0.0, 0.0, 80.0, 1500.0, -80.0, 0.0, False, "cloudy"),
        (0.5, 0.0, 90.0, 1500.0, -80.0, 0.0, False, "rainy"),
        # missing CIN degrades to the pre-CIN behaviour
        (0.0, 0.0, 80.0, 1500.0, None, 0.0, False, "lightning"),
    ],
)
def test_derive_condition(precip, snow, tcc, cape, cin, gust, night, expected) -> None:
    assert derive_condition(precip, snow, tcc, cape, cin, gust, night) == expected


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
            cin=0.0,
            gust_speed=5.0,
            night=False,
        )
        == "rainy"
    )


def _current(
    precipitation_type: int | None, temperature: float, rate: float = 1.0
) -> str | None:
    """`derive_current_condition` in an overcast, convectively quiet setting."""
    return derive_current_condition(
        precipitation_type=precipitation_type,
        precipitation_rate_mm_h=rate,
        temperature=temperature,
        humidity=90.0,
        wind_speed=3.0,
        cloud_coverage=100.0,
        cape=0.0,
        cin=0.0,
        gust_speed=5.0,
        night=False,
    )


@pytest.mark.parametrize(
    ("precipitation_type", "temperature", "expected"),
    [
        # The confirmed `pt` code decides rain vs snow, not temperature: snow
        # can reach the ground well above freezing, and rain fall below it.
        (5, 3.0, "snowy"),
        (1, -1.0, "rainy"),
        (7, 4.0, "snowy-rainy"),
        # HA has no freezing-rain condition; snowy-rainy is the closest.
        (3, -2.0, "snowy-rainy"),
    ],
)
def test_current_condition_pt_decides_the_precipitation_kind(
    precipitation_type: int, temperature: float, expected: str
) -> None:
    assert _current(precipitation_type, temperature) == expected


@pytest.mark.parametrize(
    ("precipitation_type", "cape", "expected"),
    [
        # A thunderstorm is the hazard people act on, so it outranks the mixed
        # kinds: a spring shower coded rain-and-snow can still be a storm.
        (7, 1500.0, "lightning-rainy"),
        (3, 1500.0, "lightning-rainy"),
        # Snow still outranks thunder, as the temperature rule always did.
        (5, 1500.0, "snowy"),
        # Without thunder a downpour of mixed kinds stays mixed, not `pouring`.
        (7, 0.0, "snowy-rainy"),
        (3, 0.0, "snowy-rainy"),
    ],
)
def test_current_condition_thunder_outranks_mixed_precipitation(
    precipitation_type: int, cape: float, expected: str
) -> None:
    """Observed downpour (8 mm/h) at 4 °C: the CAPE-alone override applies."""
    assert (
        derive_current_condition(
            precipitation_type=precipitation_type,
            precipitation_rate_mm_h=8.0,
            temperature=4.0,
            humidity=90.0,
            wind_speed=3.0,
            cloud_coverage=100.0,
            cape=cape,
            cin=-80.0,
            gust_speed=5.0,
            night=False,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("precipitation_type", "temperature", "expected"),
    [
        # No code at all: the rate says it precipitates, temperature splits it.
        (None, -1.0, "snowy"),
        (None, 5.0, "rainy"),
        # 255 alongside an observed rate: the code has no kind to offer.
        (255, -1.0, "snowy"),
        # A code outside GeoSphere's table says *that*, not *what*.
        (2, -1.0, "snowy"),
        (2, 5.0, "rainy"),
    ],
)
def test_current_condition_falls_back_to_temperature_without_a_known_kind(
    precipitation_type: int | None, temperature: float, expected: str
) -> None:
    assert _current(precipitation_type, temperature) == expected


@pytest.mark.parametrize(
    ("code", "rate", "expected"),
    [
        (1, None, "rain"),
        (3, None, "freezing_rain"),
        (5, None, "snow"),
        (7, None, "rain_and_snow"),
        (255, None, "no_precipitation"),
        (255, 0.0, "no_precipitation"),
        # 255 beside a rate that says it precipitates names no kind — and the
        # rate here is the condition's own, INCA fallback included, so "none"
        # would contradict the condition derived from it.
        (255, 0.5, None),
        (2, None, None),
        (None, 0.5, None),
        (None, None, None),
    ],
)
def test_derive_precipitation_type(
    code: int | None, rate: float | None, expected: str | None
) -> None:
    """GeoSphere's table, verbatim; anything outside it is unknown."""
    assert derive_precipitation_type(code, rate) == expected


def test_current_condition_thunder_ignores_the_forecast_cap() -> None:
    """An observed storm is not vetoed by AROME's inhibition for the hour.

    Precipitation here comes from INCA/the nowcast -- measurements -- while
    CAPE and CIN are forecast. Inhibition answers "can convection start?", and
    the observation has already settled that, so a strong modelled cap must
    not turn a thunderstorm in progress into plain `rainy`. The forecast path
    (`derive_condition`) still applies the full gate.
    """
    assert (
        derive_current_condition(
            precipitation_type=1,
            precipitation_rate_mm_h=6.0,
            temperature=18.0,
            humidity=85.0,
            wind_speed=4.0,
            cloud_coverage=95.0,
            cape=1800.0,
            cin=-60.0,  # past CAP_CIN_JKG: capped, per the model
            gust_speed=8.0,
            night=False,
        )
        == "lightning-rainy"
    )


def test_current_condition_light_rain_does_not_override_the_cap() -> None:
    """Only convective-intensity rain overrides the modelled lid.

    Same capped, high-CAPE air as the test above, but the observation is
    drizzle off a frontal deck rather than a downpour. `precipitating` is true
    of any rate at all, so without the intensity qualifier this returned
    `lightning-rainy` -- and contradicted `derive_condition`, which keeps the
    full gate and calls the same hour `rainy`.
    """
    assert (
        derive_current_condition(
            precipitation_type=1,
            precipitation_rate_mm_h=0.4,  # below POURING_MM_PER_H
            temperature=18.0,
            humidity=85.0,
            wind_speed=4.0,
            cloud_coverage=95.0,
            cape=1800.0,
            cin=-150.0,  # strongly capped, per the model
            gust_speed=8.0,
            night=False,
        )
        == "rainy"
    )


def test_current_condition_light_rain_thunders_when_uncapped() -> None:
    """The intensity qualifier gates the *override*, not thunder itself.

    With weak inhibition the ordinary gate passes on CAPE alone, so light rain
    still reads as a thunderstorm -- the rate only matters when the model
    claims a lid.
    """
    assert (
        derive_current_condition(
            precipitation_type=1,
            precipitation_rate_mm_h=0.4,
            temperature=18.0,
            humidity=85.0,
            wind_speed=4.0,
            cloud_coverage=95.0,
            cape=1800.0,
            cin=-10.0,  # within CAP_CIN_JKG: effectively uncapped
            gust_speed=8.0,
            night=False,
        )
        == "lightning-rainy"
    )


def test_current_condition_without_precipitation_still_honours_the_cap() -> None:
    """With nothing observed, the verdict is forecast-only and the cap applies."""
    assert (
        derive_current_condition(
            precipitation_type=255,
            precipitation_rate_mm_h=0.0,
            temperature=25.0,
            humidity=40.0,
            wind_speed=3.0,
            cloud_coverage=95.0,
            cape=1800.0,
            cin=-60.0,
            gust_speed=5.0,
            night=False,
        )
        == "cloudy"
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
            cin=0.0,
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
            cin=0.0,
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


@pytest.mark.parametrize(
    ("precipitation_type", "rate", "expected"),
    [
        # The nowcast `pt` code alone is sufficient: any code but 255 is wet,
        # even with no measurable rate behind it yet.
        (1, 0.0, True),
        (5, 0.0, True),
        (255, 0.0, False),
        # ...and the instantaneous nowcast rate alone is sufficient, covering
        # a bucket that measured rain but carries no usable `pt` code. Both
        # signals come from the nowcast — INCA's hourly `RR` is deliberately
        # not one of them (see `GeoSphereCurrentCoordinator._merge`).
        # PRECIP_MIN_MM (0.1) is the floor.
        (None, 0.5, True),
        (None, 0.1, True),
        (None, 0.09, False),
        (None, 0.0, False),
        # Neither source spoke: unknown, NOT dry. Both are the nowcast, so
        # both fall silent together — outside the Austrian grid, and on a
        # failed nowcast fetch. Defaulting this to False invents a "dry".
        (None, None, None),
        # A dry `pt` does not veto an observed rate, nor the reverse.
        (255, 0.5, True),
        (1, None, True),
    ],
)
def test_is_precipitating(
    precipitation_type: int | None, rate: float | None, expected: bool | None
) -> None:
    """Either source is sufficient; neither vetoes the other; silence is `None`."""
    assert is_precipitating(precipitation_type, rate) is expected
