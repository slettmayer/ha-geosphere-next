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
    CLEAR_TCC_PCT,
    CLOUDY_TCC_PCT,
    FOG_HEURISTIC_ENABLED,
    FOG_MAX_WIND_MS,
    FOG_MIN_RH_PCT,
    FOG_MIN_TCC_PCT,
    POURING_MM_PER_H,
    PRECIP_MIN_MM,
    PT_NO_PRECIPITATION,
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


def derive_condition(
    precipitation: float | None,
    snow: float | None,
    cloud_coverage: float | None,
    cape: float | None,
    gust_speed: float | None,
    night: bool,
) -> str | None:
    """Derive an HA condition from physical parameters (per forecast hour).

    precipitation/snow in mm per hour, cloud_coverage in %, cape in J/kg,
    gust_speed in m/s.
    """
    precip = precipitation or 0.0
    snowfall = snow or 0.0
    rain = max(precip - snowfall, 0.0)
    tcc = cloud_coverage
    thunder = cape is not None and cape >= THUNDER_CAPE_JKG

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


def derive_current_condition(
    *,
    precipitation_type: int | None,
    precipitation_rate_mm_h: float | None,
    temperature: float | None,
    humidity: float | None,
    wind_speed: float | None,
    cloud_coverage: float | None,
    cape: float | None,
    gust_speed: float | None,
    night: bool,
) -> str | None:
    """Current condition: nowcast precipitation type overrides cloud logic.

    The nowcast `pt` code table is undocumented (255 = none), so any other
    code only signals *that* it precipitates; rain vs snow is decided by
    temperature.
    """
    rate = precipitation_rate_mm_h or 0.0
    precipitating = (
        precipitation_type is not None and precipitation_type != PT_NO_PRECIPITATION
    ) or rate >= PRECIP_MIN_MM
    if precipitating:
        thunder = cape is not None and cape >= THUNDER_CAPE_JKG
        snow_likely = temperature is not None and temperature <= SNOW_MAX_T2M_C
        if snow_likely:
            return "snowy"
        if thunder:
            return "lightning-rainy"
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

    return derive_condition(0.0, 0.0, cloud_coverage, cape, gust_speed, night)
