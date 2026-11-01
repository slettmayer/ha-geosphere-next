"""Forecast-outlook derivation — pure functions, fully testable.

Scans the processed AROME hourly series for the facts a storm-warning
automation needs: peak gusts within a horizon, and when thunder is next
expected. Gusts are deliberately threshold-free — what counts as "too windy"
is the consumer's policy, not this integration's.

A thunderstorm hour is one whose weather symbol is a thunderstorm code, or
whose current C-LAEF ensemble run allows a storm. Either suffices: storm
blinds act on it, and a false alarm costs less than a miss.

Gust values are returned in m/s, matching `HourlyForecast`; entities convert
to km/h at their own boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .condition import is_thunder_symbol
from .const import (
    ENSEMBLE_MAX_FALLBACK_AGE,
    PRECIP_MIN_MM,
    THUNDER_CAPE_JKG,
    THUNDER_SOURCE_BOTH,
    THUNDER_SOURCE_ENSEMBLE,
    THUNDER_SOURCE_SYMBOL,
)
from .models import HourlyForecast


def _window(
    hourly: list[HourlyForecast], hours: int, now: datetime
) -> list[HourlyForecast]:
    """Hours from the top of the current hour through `now + hours`.

    The series' first entry is the in-progress hour, stamped at the top of the
    hour and therefore earlier than `now` — it must still count.

    The horizon therefore rounds *up* to whole hourly steps: the start floors
    to the top of the current hour while the end stays at `now + hours`, so an
    `hours`-hour window always spans `hours + 1` hourly stamps — the
    in-progress hour plus the next `hours`. A 1-hour window consequently
    covers the current hour and the next one, and can report an event up to
    ~2 h ahead. Consumers that need a strict "within the next 60 minutes"
    answer must compare timestamps themselves.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=hours)
    return [hour for hour in hourly if start <= hour.datetime <= end]


def hour_at(hourly: list[HourlyForecast], now: datetime) -> HourlyForecast | None:
    """The forecast hour covering `now` — the in-progress hour.

    Matches on the top-of-hour floor of `now`, because the series is stamped at
    the top of each hour and its first entry is the hour already under way (so
    it is earlier than `now` by up to 59 minutes).

    Returns `None` when the series does not cover `now` at all — e.g. a
    forecast that has aged out entirely, or one that has not reached `now` yet.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    for hour in hourly:
        if hour.datetime == start:
            return hour
    return None


def ensemble_is_current(reference_time: datetime | None, now: datetime) -> bool:
    """Whether an ensemble run may feed the storm signal at `now`.

    Current while its `reference_time` is less than ENSEMBLE_MAX_FALLBACK_AGE
    old, the same bound the coordinator holds a cached run to. No run, or a run without a stamp, is not current.
    """
    return (
        reference_time is not None and now - reference_time < ENSEMBLE_MAX_FALLBACK_AGE
    )


def _storm_signals(hour: HourlyForecast, ensemble: bool) -> tuple[bool, bool]:
    """Which signals call the hour a thunderstorm: (symbol, ensemble).

    The symbol fires on GeoSphere's thunderstorm codes. The ensemble fires,
    if `ensemble` says its run is current, when its 90th percentiles reach
    THUNDER_CAPE_JKG of CAPE and PRECIP_MIN_MM of precipitation in the hour;
    CAPE alone is a routine dry summer afternoon.
    """
    cape = hour.ensemble_cape_p90
    precipitation = hour.ensemble_precipitation_p90
    return is_thunder_symbol(hour.weather_symbol), (
        ensemble
        and cape is not None
        and cape >= THUNDER_CAPE_JKG
        and precipitation is not None
        and precipitation >= PRECIP_MIN_MM
    )


def _source(symbol: bool, ensemble: bool) -> str | None:
    """The `source` value naming which signals fired, `None` for neither."""
    if symbol and ensemble:
        return THUNDER_SOURCE_BOTH
    if symbol:
        return THUNDER_SOURCE_SYMBOL
    if ensemble:
        return THUNDER_SOURCE_ENSEMBLE
    return None


def max_gust(
    hourly: list[HourlyForecast], hours: int, now: datetime
) -> tuple[float | None, datetime | None]:
    """Peak gust (m/s) within the horizon and the hour it falls in.

    The horizon rounds up to whole hourly steps — see `_window`.
    """
    best_value: float | None = None
    best_time: datetime | None = None
    for hour in _window(hourly, hours, now):
        gust = hour.wind_gust_speed
        if gust is None:
            continue
        if best_value is None or gust > best_value:
            best_value = gust
            best_time = hour.datetime
    return best_value, best_time


def max_cape(hourly: list[HourlyForecast], hours: int, now: datetime) -> float | None:
    """Peak CAPE (J/kg) within the horizon (rounds up to whole hourly steps)."""
    values = [
        hour.cape for hour in _window(hourly, hours, now) if hour.cape is not None
    ]
    return max(values) if values else None


def next_thunderstorm(
    hourly: list[HourlyForecast],
    now: datetime,
    ensemble_reference_time: datetime | None,
) -> tuple[datetime | None, str | None]:
    """Start of the first thunderstorm hour, and which signal fired in it.

    Scans the full horizon from the top of the current hour, so a storm in
    the hour under way returns a timestamp up to 59 minutes in the past: it
    means "storm in progress", and lead-time math must clamp at zero.
    """
    ensemble = ensemble_is_current(ensemble_reference_time, now)
    start = now.replace(minute=0, second=0, microsecond=0)
    for hour in hourly:
        if hour.datetime < start:
            continue
        source = _source(*_storm_signals(hour, ensemble))
        if source is not None:
            return hour.datetime, source
    return None, None


def thunderstorm_outlook(
    hourly: list[HourlyForecast],
    hours: int,
    now: datetime,
    ensemble_reference_time: datetime | None,
) -> tuple[bool | None, str | None]:
    """Whether any hour in the window is a thunderstorm hour, and which signal.

    The source is judged across the whole window. `None` (unknown) only when
    the forecast has no hour in the window; an hour whose symbol is missing
    or outside GeoSphere's table counts as no storm unless the ensemble says
    otherwise.
    """
    window = _window(hourly, hours, now)
    if not window:
        return None, None
    ensemble = ensemble_is_current(ensemble_reference_time, now)
    signals = [_storm_signals(hour, ensemble) for hour in window]
    source = _source(
        any(symbol for symbol, _ in signals), any(ens for _, ens in signals)
    )
    return source is not None, source
