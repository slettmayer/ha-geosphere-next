"""Condition derivation — pure functions, fully testable.

GeoSphere's `sy` weather symbol uses an undocumented proprietary code table,
so (like open-meteo) the HA condition is derived from physical parameters
instead. Condition strings equal Home Assistant's ATTR_CONDITION_* values;
literals are used to keep this module free of homeassistant imports.
"""

from __future__ import annotations

import math
from datetime import datetime

from astral import Observer
from astral.sun import elevation as solar_elevation

from .const import (
    CAP_CIN_JKG,
    CLEAR_TCC_PCT,
    CLOUDY_TCC_PCT,
    FOG_HEURISTIC_ENABLED,
    FOG_MAX_WIND_MS,
    FOG_MIN_RH_PCT,
    FOG_MIN_TCC_PCT,
    POURING_MM_PER_H,
    PRECIP_MIN_MM,
    PRECIPITATION_TYPES,
    PT_FREEZING_RAIN,
    PT_NO_PRECIPITATION,
    PT_RAIN_AND_SNOW,
    PT_SNOW,
    SNOW_MAX_T2M_C,
    THUNDER_CAPE_JKG,
    WINDY_CLOUD_TCC_PCT,
    WINDY_GUST_MS,
)


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


def is_thunder(cape: float | None, cin: float | None) -> bool:
    """True when CAPE is sufficient AND convective inhibition is weak enough.

    AROME publishes `cin` as negative J/kg (0.0 = uncapped). A missing value is
    treated as uncapped so behaviour degrades to the pre-CIN logic.
    """
    if cape is None or cape < THUNDER_CAPE_JKG:
        return False
    return cin is None or cin > -CAP_CIN_JKG


def derive_condition(
    precipitation: float | None,
    snow: float | None,
    cloud_coverage: float | None,
    cape: float | None,
    cin: float | None,
    gust_speed: float | None,
    night: bool,
) -> str | None:
    """Derive an HA condition from physical parameters (per forecast hour).

    precipitation/snow in mm per hour, cloud_coverage in %, cape and cin in
    J/kg (cin negative), gust_speed in m/s.
    """
    precip = precipitation or 0.0
    snowfall = snow or 0.0
    rain = max(precip - snowfall, 0.0)
    tcc = cloud_coverage
    thunder = is_thunder(cape, cin)

    if snowfall >= PRECIP_MIN_MM and rain >= PRECIP_MIN_MM:
        return "snowy-rainy"
    if snowfall >= PRECIP_MIN_MM:
        return "snowy"
    if precip >= PRECIP_MIN_MM:
        if thunder:
            return "lightning-rainy"
        if precip >= POURING_MM_PER_H:
            return "pouring"
        return "rainy"
    if tcc is None:
        return None
    if thunder and tcc >= WINDY_CLOUD_TCC_PCT:
        return "lightning"
    if gust_speed is not None and gust_speed >= WINDY_GUST_MS:
        return "windy-variant" if tcc >= WINDY_CLOUD_TCC_PCT else "windy"
    if tcc <= CLEAR_TCC_PCT:
        return "clear-night" if night else "sunny"
    if tcc <= CLOUDY_TCC_PCT:
        return "partlycloudy"
    return "cloudy"


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
    rather than restating the comparison. A caller that must decide either way
    (the condition derivation) passes a rate defaulted to 0.0 and so never
    sees `None`.
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
    humidity: float | None,
    wind_speed: float | None,
    cloud_coverage: float | None,
    cape: float | None,
    cin: float | None,
    gust_speed: float | None,
    night: bool,
) -> str | None:
    """Current condition: nowcast precipitation type overrides cloud logic.

    The nowcast `pt` code decides the kind: snow, rain and snow, or freezing
    rain (HA has no condition for it; `snowy-rainy` is the closest) win over
    temperature, which cannot tell wet snow above freezing from rain. Only
    when the code names no kind — absent, 255 beside an observed rate, or a
    code outside GeoSphere's table — does temperature split rain from snow.
    At or below SNOW_MAX_T2M_C snow (pt 5, or no kind) outranks thunder;
    above it, or with no temperature at all, thunder outranks every kind.
    Thunder also outranks the mixed kinds (pt 7, pt 3) when cold, where the
    pre-code temperature rule called any cold precipitation snow.

    Note which evidence is which. Precipitation here is *observed* — INCA and
    the nowcast are anchored to measurements — while CAPE and CIN come from
    AROME's forecast for the hour. Inhibition answers "can convection get
    started?", and a downpour already answers it, so observed rain of
    *convective intensity* (>= POURING_MM_PER_H) overrides the modelled lid:
    letting it veto would render a thunderstorm in progress as plain `rainy`.

    Intensity is the whole qualifier. Observed precipitation alone is far too
    weak a signal to spend the gate on — `is_precipitating` is true of drizzle,
    and high CAPE under a strong lid with light stratiform rain off a frontal
    deck is a real pattern, not a storm. Below that rate the full CAPE/CIN
    gate applies, as it does on the non-precipitating branch and throughout
    `derive_condition`, both of which are forecast-driven end to end.
    """
    rate = precipitation_rate_mm_h or 0.0
    if is_precipitating(precipitation_type, rate):
        # `None` when the code names no kind; never "no_precipitation" here,
        # since 255 only reaches this branch beside a wet rate.
        kind = derive_precipitation_type(precipitation_type, rate)
        cold = temperature is not None and temperature <= SNOW_MAX_T2M_C
        # Snow outranks thunder only at or below SNOW_MAX_T2M_C, as it did
        # under the temperature rule: thundersnow is rare and still snow.
        # Unknown temperature is not cold, again as under that rule.
        if cold and kind in (None, PRECIPITATION_TYPES[PT_SNOW]):
            return "snowy"
        thunder = is_thunder(cape, cin) or (
            rate >= POURING_MM_PER_H and cape is not None and cape >= THUNDER_CAPE_JKG
        )
        # Above it, thunder outranks every kind: it is the hazard people act
        # on, and a graupel or rain-and-snow shower can still be a storm.
        if thunder:
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

    if (
        FOG_HEURISTIC_ENABLED
        and humidity is not None
        and humidity >= FOG_MIN_RH_PCT
        and wind_speed is not None
        and wind_speed < FOG_MAX_WIND_MS
        and cloud_coverage is not None
        and cloud_coverage >= FOG_MIN_TCC_PCT
    ):
        return "fog"

    return derive_condition(0.0, 0.0, cloud_coverage, cape, cin, gust_speed, night)
