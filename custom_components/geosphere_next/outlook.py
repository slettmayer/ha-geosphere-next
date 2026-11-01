"""Forecast-outlook derivation — pure functions, fully testable.

Scans the processed AROME hourly series for the facts a storm-warning
automation needs: peak gusts within a horizon, and when thunder is next
expected. Gusts are deliberately threshold-free — what counts as "too windy"
is the consumer's policy, not this integration's.

Thunder has two signals. GeoSphere's weather symbol (codes 26-32) is the
deterministic run's own verdict. The C-LAEF ensemble adds a second one, so a
storm that only some members develop still raises the short-range outlook:
false alarms there cost a closed blind, a miss costs the blind.

Gust values are returned in m/s, matching `HourlyForecast`; entities convert
to km/h at their own boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .condition import is_thunder_symbol
from .const import (
    PRECIP_MIN_MM,
    SY_CODES,
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


def _is_lightning(hour: HourlyForecast) -> bool:
    """True when GeoSphere's weather symbol calls the hour a thunderstorm."""
    return is_thunder_symbol(hour.weather_symbol)


def _is_ensemble_storm(hour: HourlyForecast) -> bool:
    """True when the ensemble's 90th percentiles allow a thunderstorm.

    Both have to: CAPE reaching THUNDER_CAPE_JKG at the hour's start, and at
    least PRECIP_MIN_MM falling within it. CAPE alone is a routine dry summer
    afternoon. The 90th percentile means at least a tenth of the members
    reach each value, though not necessarily the same members.
    """
    cape = hour.ensemble_cape_p90
    precipitation = hour.ensemble_precipitation_p90
    return (
        cape is not None
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


def _is_decidable(hour: HourlyForecast) -> bool:
    """True when the hour carries enough data to judge thunder either way.

    Either signal suffices: a weather symbol from GeoSphere's table, or both
    ensemble percentiles. A code outside the table is unreadable, not calm.
    An hour with neither says nothing about thunder — "no storm" would be a
    guess, not an answer.
    """
    return hour.weather_symbol in SY_CODES or (
        hour.ensemble_cape_p90 is not None
        and hour.ensemble_precipitation_p90 is not None
    )


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
    hourly: list[HourlyForecast], now: datetime
) -> tuple[datetime | None, float | None, str | None]:
    """First thunderstorm hour, its CAPE, and which signal fired in it.

    A thunderstorm hour is one with a thunderstorm symbol or the ensemble
    storm signal — the same per-hour test `thunderstorm_outlook` applies, so
    whenever that outlook is on, this names an hour inside its window. The
    source is judged for that hour alone.

    Scans the full horizon rather than a window — "no storm for two days" and
    "storm in 40 hours" are both useful answers.

    The scan starts at the top of the *current* hour, so when the storm hour is
    the one already under way the returned timestamp is in the past — by up to
    59 minutes. That is intentional: it means "storm in progress". Downstream
    lead-time math must treat a non-positive lead time as "now", e.g.
    `max(0, (next_thunderstorm - now) minutes)`, rather than assuming the
    timestamp is always in the future.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    for hour in hourly:
        if hour.datetime < start:
            continue
        source = _source(_is_lightning(hour), _is_ensemble_storm(hour))
        if source is not None:
            return hour.datetime, hour.cape, source
    return None, None, None


def thunderstorm_outlook(
    hourly: list[HourlyForecast], hours: int, now: datetime
) -> tuple[bool | None, str | None]:
    """Tri-state thunderstorm outlook for the horizon, and which signal fired.

    On when any hour in the window carries a thunderstorm symbol or the
    ensemble storm signal; the source is THUNDER_SOURCE_SYMBOL,
    THUNDER_SOURCE_ENSEMBLE or THUNDER_SOURCE_BOTH, each judged across the
    whole window rather than per hour.

    `False` when the window holds hours that can be judged and none fires,
    and `None` when it holds none at all or none that are decidable — so an
    entity can report "unknown" instead of a confident "off" on a data gap.
    The source is `None` unless the outlook is on.
    """
    window = _window(hourly, hours, now)
    source = _source(
        any(_is_lightning(hour) for hour in window),
        any(_is_ensemble_storm(hour) for hour in window),
    )
    if source is not None:
        return True, source
    if not any(_is_decidable(hour) for hour in window):
        return None, None
    return False, None
