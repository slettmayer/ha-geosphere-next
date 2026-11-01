"""Condition derivation — pure functions, fully testable.

The forecast condition is GeoSphere's own weather symbol (`sy`) mapped onto
Home Assistant's conditions; the current condition lets observations decide
whether and what is falling and takes the rest from that symbol. Condition
strings equal Home Assistant's ATTR_CONDITION_* values; literals are used to
keep this module free of homeassistant imports.
"""

from __future__ import annotations

import math
from datetime import datetime

from astral import Observer
from astral.sun import elevation as solar_elevation

from .const import (
    POURING_MM_PER_H,
    PRECIP_MIN_MM,
    PRECIPITATION_TYPES,
    PT_FREEZING_RAIN,
    PT_NO_PRECIPITATION,
    PT_RAIN_AND_SNOW,
    PT_SNOW,
    SNOW_MAX_T2M_C,
    SY_CLEAR,
    SY_CLOUDY,
    SY_FOG,
    SY_PARTLY_CLOUDY,
    SY_POURING,
    SY_PRECIPITATION,
    SY_RAIN,
    SY_SLEET,
    SY_SNOW,
    SY_THUNDER,
)

# Every `sy` code but the clear ones, which depend on the time of day.
_SYMBOL_CONDITIONS: dict[int, str] = {
    **dict.fromkeys(SY_PARTLY_CLOUDY, "partlycloudy"),
    **dict.fromkeys(SY_CLOUDY, "cloudy"),
    **dict.fromkeys(SY_FOG, "fog"),
    **dict.fromkeys(SY_RAIN, "rainy"),
    **dict.fromkeys(SY_POURING, "pouring"),
    **dict.fromkeys(SY_SLEET, "snowy-rainy"),
    **dict.fromkeys(SY_SNOW, "snowy"),
    **dict.fromkeys(SY_THUNDER, "lightning-rainy"),
}


def wind_from_components(
    u: float | None, v: float | None
) -> tuple[float | None, float | None]:
    """Convert u/v wind components (m/s) to (speed m/s, meteorological bearing °)."""
    if u is None or v is None:
        return None, None
    speed = math.hypot(u, v)
    bearing = (270.0 - math.degrees(math.atan2(v, u))) % 360.0
    return speed, bearing


def is_night(latitude: float, longitude: float, when: datetime) -> bool:
    """True when the sun is below the horizon at the given point and time."""
    return solar_elevation(Observer(latitude, longitude), when) < 0.0


def apparent_temperature(
    temperature: float | None, humidity: float | None, wind_speed: float | None
) -> float | None:
    """Australian BoM apparent temperature (°C) from T (°C), RH (%), wind (m/s)."""
    if temperature is None or humidity is None or wind_speed is None:
        return None
    vapor_pressure = (
        humidity / 100.0 * 6.105 * math.exp(17.27 * temperature / (237.7 + temperature))
    )
    return round(temperature + 0.33 * vapor_pressure - 0.70 * wind_speed - 4.0, 1)


def dew_point_from_t_rh(
    temperature: float | None, humidity: float | None
) -> float | None:
    """Magnus dew point (°C) from T (°C) and RH (%); AROME has no dew-point param."""
    if temperature is None or humidity is None or humidity <= 0.0:
        return None
    humidity = min(humidity, 100.0)
    a, b = 17.62, 243.12
    gamma = math.log(humidity / 100.0) + a * temperature / (b + temperature)
    return round(b * gamma / (a - gamma), 1)


def derive_condition_from_symbol(symbol: int | None, night: bool) -> str | None:
    """The HA condition for a GeoSphere `sy` code (per forecast hour).

    A missing code, or one outside GeoSphere's table, is `None` -- unknown,
    never a guess. The table has no night variants, so the clear codes take
    `night` to tell `sunny` from `clear-night`.
    """
    if symbol is None:
        return None
    if symbol in SY_CLEAR:
        return "clear-night" if night else "sunny"
    return _SYMBOL_CONDITIONS.get(symbol)


def is_thunder_symbol(symbol: int | None) -> bool:
    """True when a `sy` code is one of GeoSphere's thunderstorm codes."""
    return symbol in SY_THUNDER


def is_precipitating(
    precipitation_type: int | None,
    precipitation_rate_mm_h: float | None,
) -> bool | None:
    """Whether precipitation is falling right now, or `None` if nothing says.

    Two independent signals, either of which is sufficient: the nowcast `pt`
    code, and an instantaneous rate. Both come from the 15-min nowcast, the
    only source that observes precipitation *now* — the caller must not
    substitute INCA's hourly `RR`, an accumulation that answers a different
    question (see `GeoSphereCurrentCoordinator._merge`).

    `None` when *neither* spoke, which is not the same as "dry" and must not
    render as one. Two ways to get there: a point outside the Austrian grid,
    where `CONF_HAS_NOWCAST` skips the nowcast and INCA alike (they share the
    grid — see `_async_get_inca`), and a transient nowcast fetch failure.
    Both leave nothing observing precipitation, so a confident "dry" would be
    invented. `precipitation_1h` already reports `unknown` in the first case;
    this keeps the pair consistent.

    Sole definition of "precipitating" for the integration: both
    `derive_current_condition` and `GeoSphereCurrentCoordinator._merge` (which
    stores the result as `CurrentConditions.is_precipitating`) call this
    rather than restating the comparison. The condition derivation reads
    `None` as "nothing observed" and leaves the verdict to the forecast.
    """
    if precipitation_type is not None and precipitation_type != PT_NO_PRECIPITATION:
        return True
    if precipitation_rate_mm_h is not None:
        return precipitation_rate_mm_h >= PRECIP_MIN_MM
    # Reached only by a `pt` of 255 with no rate alongside it, which is rare —
    # the nowcast normally carries `rr` for the same bucket and the branch
    # above decides. 255 is GeoSphere's "no precipitation", not GRIB2's
    # "Missing" (see PRECIPITATION_TYPES), so this is an observed "dry".
    return None if precipitation_type is None else False


def derive_precipitation_type(
    precipitation_type: int | None, precipitation_rate_mm_h: float | None
) -> str | None:
    """GeoSphere's name for a nowcast `pt` code, or `None` if it names no kind.

    `None` outside GeoSphere's table, and for 255 beside a rate that says it
    precipitates. Pass the rate `derive_current_condition` gets, so a sensor
    reading "no precipitation" can never sit beside a rainy condition.
    """
    if precipitation_type is None:
        return None
    if precipitation_type == PT_NO_PRECIPITATION and is_precipitating(
        precipitation_type, precipitation_rate_mm_h
    ):
        return None
    return PRECIPITATION_TYPES.get(precipitation_type)


def derive_current_condition(
    *,
    precipitation_type: int | None,
    precipitation_rate_mm_h: float | None,
    temperature: float | None,
    symbol: int | None,
    night: bool,
) -> str | None:
    """Current condition: observations decide what falls, the symbol the rest.

    `symbol` is the `sy` code of the forecast hour covering now, from a model
    run that is routinely 3-6 h old, so it does not get to say whether it is
    precipitating. The observed path does: the nowcast `pt` code decides the
    kind -- snow, rain and snow, or freezing rain (HA has no condition for
    it; `snowy-rainy` is the closest) win over temperature, which cannot tell
    wet snow above freezing from rain. Only when the code names no kind --
    absent, 255 beside an observed rate, or a code outside GeoSphere's table
    -- does temperature split rain from snow.

    Thunder is the one thing observations here cannot see, so it comes from
    the symbol, and only while precipitation is observed. At or below
    SNOW_MAX_T2M_C observed snow (pt 5, or no kind) outranks a thunder symbol:
    HA's `lightning-rainy` depicts rain, and the run that forecast the storm
    may have expected a warmer airmass than the one now snowing. Above it, or
    with no temperature at all, thunder outranks every kind; it also
    outranks the mixed kinds (pt 7, pt 3) when cold, since they are not snow.

    Dry by observation, the symbol's own mapping applies -- except that a
    precipitation or thunder code becomes `cloudy`: the model expects
    precipitation that is not falling, under what is then an overcast sky.
    With no observation at all — a `None` rate and no `pt` code: outside the
    nowcast grid, or the nowcast down with no current wet INCA `RR` (a dry
    one is never passed as an observation) — the symbol is the only evidence
    and its mapping applies unchanged.
    """
    observed = is_precipitating(precipitation_type, precipitation_rate_mm_h)
    if observed is None:
        return derive_condition_from_symbol(symbol, night)
    rate = precipitation_rate_mm_h or 0.0
    if observed:
        # `None` when the code names no kind; never "no_precipitation" here,
        # since 255 only reaches this branch beside a wet rate.
        kind = derive_precipitation_type(precipitation_type, rate)
        cold = temperature is not None and temperature <= SNOW_MAX_T2M_C
        # Observed snow outranks a thunder symbol only at or below
        # SNOW_MAX_T2M_C: thundersnow is rare and still snow. Unknown
        # temperature is not cold.
        if cold and kind in (None, PRECIPITATION_TYPES[PT_SNOW]):
            return "snowy"
        # Above it, thunder outranks every kind: it is the hazard people act
        # on, and a graupel or rain-and-snow shower can still be a storm.
        if is_thunder_symbol(symbol):
            return "lightning-rainy"
        if kind == PRECIPITATION_TYPES[PT_SNOW]:
            return "snowy"
        if kind in (
            PRECIPITATION_TYPES[PT_RAIN_AND_SNOW],
            PRECIPITATION_TYPES[PT_FREEZING_RAIN],
        ):
            return "snowy-rainy"
        if rate >= POURING_MM_PER_H:
            return "pouring"
        return "rainy"

    if symbol in SY_PRECIPITATION:
        return "cloudy"
    return derive_condition_from_symbol(symbol, night)
