"""Tests for the pure condition-derivation functions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.geosphere_next.condition import (
    apparent_temperature,
    derive_condition_from_symbol,
    derive_current_condition,
    derive_precipitation_type,
    dew_point_from_t_rh,
    is_night,
    is_precipitating,
    is_thunder_symbol,
    wind_from_components,
)

# GeoSphere's published table, code by code: every code 1-32 has a condition.
SYMBOL_TABLE = {
    1: "sunny",  # Wolkenlos
    2: "sunny",  # Heiter
    3: "partlycloudy",  # Wolkig
    4: "cloudy",  # Stark bewölkt
    5: "cloudy",  # Bedeckt
    6: "fog",  # Bodennebel
    7: "fog",  # Hochnebel
    8: "rainy",  # Leichter Regen
    9: "rainy",  # Mäßiger Regen
    10: "pouring",  # Starker Regen
    11: "snowy-rainy",  # Schneeregen
    12: "snowy-rainy",
    13: "snowy-rainy",
    14: "snowy",  # Leichter Schneefall
    15: "snowy",  # Mäßiger Schneefall
    16: "snowy",  # Starker Schneefall
    17: "rainy",  # Regenschauer
    18: "rainy",
    19: "pouring",  # Starker Regenschauer
    20: "snowy-rainy",  # Schneeregenschauer
    21: "snowy-rainy",
    22: "snowy-rainy",
    23: "snowy",  # Schneeschauer
    24: "snowy",
    25: "snowy",  # Starker Schneeschauer
    26: "lightning-rainy",  # Gewitter
    27: "lightning-rainy",
    28: "lightning-rainy",  # Starkes Gewitter
    29: "lightning-rainy",  # Gewitter mit Schneeregen
    30: "lightning-rainy",  # Starkes Gewitter mit Schneeregen
    31: "lightning-rainy",  # Gewitter mit Schneefall
    32: "lightning-rainy",  # Starkes Gewitter mit Schneefall
}


@pytest.mark.parametrize(("symbol", "expected"), sorted(SYMBOL_TABLE.items()))
def test_derive_condition_from_symbol_by_day(symbol: int, expected: str) -> None:
    assert derive_condition_from_symbol(symbol, night=False) == expected


@pytest.mark.parametrize(("symbol", "expected"), sorted(SYMBOL_TABLE.items()))
def test_derive_condition_from_symbol_by_night(symbol: int, expected: str) -> None:
    """Only the clear codes have a night variant; every other code keeps its."""
    night_expected = "clear-night" if expected == "sunny" else expected
    assert derive_condition_from_symbol(symbol, night=True) == night_expected


@pytest.mark.parametrize("symbol", [None, 0, 33, 99, 255, -1])
def test_derive_condition_from_symbol_is_unknown_outside_the_table(
    symbol: int | None,
) -> None:
    """A missing or unpublished code is unknown, never a guess."""
    assert derive_condition_from_symbol(symbol, night=False) is None
    assert derive_condition_from_symbol(symbol, night=True) is None


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [(26, True), (29, True), (32, True), (25, False), (33, False), (None, False)],
)
def test_is_thunder_symbol(symbol: int | None, expected: bool) -> None:
    assert is_thunder_symbol(symbol) is expected


def _current(
    precipitation_type: int | None,
    temperature: float | None,
    rate: float | None = 1.0,
    *,
    symbol: int | None = 5,
    night: bool = False,
) -> str | None:
    """`derive_current_condition` under an overcast, storm-free symbol."""
    return derive_current_condition(
        precipitation_type=precipitation_type,
        precipitation_rate_mm_h=rate,
        temperature=temperature,
        symbol=symbol,
        night=night,
    )


def test_current_condition_pt_override_rain() -> None:
    """Observed precipitation wins over a symbol that says clear sky."""
    assert _current(1, 12.0, 0.4, symbol=1) == "rainy"


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


@pytest.mark.parametrize("symbol", [14, 8, 11, 10])
def test_current_condition_kind_comes_from_observation_not_the_symbol(
    symbol: int,
) -> None:
    """The symbol's own kind never overrides what is observed falling."""
    assert _current(1, 12.0, symbol=symbol) == "rainy"
    assert _current(5, 0.0, symbol=symbol) == "snowy"


@pytest.mark.parametrize(
    ("precipitation_type", "symbol", "expected"),
    [
        # Above SNOW_MAX_T2M_C a thunderstorm, the hazard people act on,
        # outranks every kind: a spring shower coded rain-and-snow, or a
        # convective graupel shower coded snow, can still be a storm.
        (7, 26, "lightning-rainy"),
        (3, 28, "lightning-rainy"),
        (5, 31, "lightning-rainy"),
        (1, 32, "lightning-rainy"),
        # Without a thunder symbol a downpour keeps its kind, not `pouring`.
        (7, 5, "snowy-rainy"),
        (3, 5, "snowy-rainy"),
        (5, 5, "snowy"),
        (1, 5, "pouring"),
    ],
)
def test_current_condition_thunder_outranks_every_kind_above_snow_max(
    precipitation_type: int, symbol: int, expected: str
) -> None:
    """Observed downpour (8 mm/h) at 4 °C."""
    assert _current(precipitation_type, 4.0, 8.0, symbol=symbol) == expected


@pytest.mark.parametrize(
    ("precipitation_type", "expected"),
    [
        # At or below SNOW_MAX_T2M_C observed snow outranks a thunder symbol:
        # thundersnow is rare and still snow.
        (5, "snowy"),
        (None, "snowy"),
        # Codes that name no kind fall back to temperature, which says snow.
        (2, "snowy"),
        (255, "snowy"),
        # The mixed kinds are not snow, so thunder wins over them even here,
        # and so it does over rain.
        (7, "lightning-rainy"),
        (3, "lightning-rainy"),
        (1, "lightning-rainy"),
    ],
)
def test_current_condition_cold_snow_outranks_thunder(
    precipitation_type: int | None, expected: str
) -> None:
    assert _current(precipitation_type, -2.0, 8.0, symbol=31) == expected


@pytest.mark.parametrize(
    ("precipitation_type", "temperature", "expected"),
    [
        # SNOW_MAX_T2M_C itself is cold: the comparison is inclusive.
        (5, 1.0, "snowy"),
        (None, 1.0, "snowy"),
        # No temperature from any source is not cold, so thunder wins even
        # over a snow code.
        (5, None, "lightning-rainy"),
        (None, None, "lightning-rainy"),
    ],
)
def test_current_condition_snow_thunder_split_edges(
    precipitation_type: int | None, temperature: float | None, expected: str
) -> None:
    assert _current(precipitation_type, temperature, 8.0, symbol=26) == expected


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


@pytest.mark.parametrize(
    ("rate", "expected"), [(4.9, "rainy"), (5.0, "pouring"), (12.0, "pouring")]
)
def test_current_condition_pours_where_the_heavy_rain_symbols_start(
    rate: float, expected: str
) -> None:
    """Observed rain turns `pouring` at 5 mm/h, the floor of codes 10 and 19."""
    assert _current(1, 12.0, rate, symbol=8) == expected


def test_current_condition_light_rain_under_a_thunder_symbol_is_a_storm() -> None:
    """Observed rain plus a thunder symbol is a storm, whatever the rate."""
    assert _current(1, 18.0, 0.4, symbol=26) == "lightning-rainy"


@pytest.mark.parametrize("symbol", [8, 10, 11, 14, 17, 19, 20, 23, 26, 29, 32])
def test_current_condition_dry_under_a_precipitation_symbol_is_cloudy(
    symbol: int,
) -> None:
    """The model expects precipitation that observations do not show.

    The run behind the symbol is routinely 3-6 h old; with nothing falling,
    the sky it describes is an overcast one, not a wet or stormy one.
    """
    assert _current(255, 12.0, 0.0, symbol=symbol) == "cloudy"
    assert _current(255, 12.0, 0.0, symbol=symbol, night=True) == "cloudy"


@pytest.mark.parametrize(
    ("symbol", "night", "expected"),
    [
        (1, False, "sunny"),
        (2, True, "clear-night"),
        (3, False, "partlycloudy"),
        (5, True, "cloudy"),
        # Fog comes only from the symbol.
        (6, False, "fog"),
        (7, True, "fog"),
    ],
)
def test_current_condition_dry_follows_the_symbol(
    symbol: int, night: bool, expected: str
) -> None:
    assert _current(255, 2.0, 0.0, symbol=symbol, night=night) == expected


@pytest.mark.parametrize("symbol", [None, 0, 99])
def test_current_condition_dry_without_a_known_symbol_is_unknown(
    symbol: int | None,
) -> None:
    """No symbol to read and nothing falling: unknown, not a guess."""
    assert _current(255, 2.0, 0.0, symbol=symbol) is None
    # Observed precipitation still decides without any symbol at all.
    assert _current(1, 12.0, 0.5, symbol=symbol) == "rainy"


@pytest.mark.parametrize(
    ("symbol", "night", "expected"),
    [
        (8, False, "rainy"),
        (10, False, "pouring"),
        (26, False, "lightning-rainy"),
        (14, True, "snowy"),
        (2, True, "clear-night"),
        (6, False, "fog"),
        (None, False, None),
    ],
)
def test_current_condition_without_any_observation_is_the_symbol(
    symbol: int | None, night: bool, expected: str | None
) -> None:
    """Nothing observed is not "dry": the symbol is the only evidence left.

    Outside the nowcast grid, or with every observing source down or stale,
    neither a `pt` code nor a rate reaches the derivation; a precipitation
    symbol then keeps its own condition instead of being demoted to `cloudy`.
    """
    assert _current(None, 12.0, None, symbol=symbol, night=night) == expected


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
