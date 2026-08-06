"""Forecast-outlook derivation — pure functions, fully testable.

Scans the processed AROME hourly series for the facts a storm-warning
automation needs: peak gusts within a horizon, and when thunder is next
expected. Deliberately threshold-free — what counts as "too windy" is the
consumer's policy, not this integration's.

Gust values are returned in m/s, matching `HourlyForecast`; entities convert
to km/h at their own boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .condition import is_thunder
from .const import PRECIP_MIN_MM
from .models import HourlyForecast

# A condition string starting with this prefix means the derivation decided
# thunder is likely ("lightning" and "lightning-rainy").
_LIGHTNING_PREFIX = "lightning"


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


def _is_lightning(hour: HourlyForecast) -> bool:
    """True when the hour reads as a thunderstorm hour.

    Two branches, because the derived condition alone misses real storms:

    a) the derived condition starts with "lightning" — the model's own
       judgement that convection is occurring, and the primary signal; or
    b) the raw CAPE/CIN thunder predicate holds *and* the hour is forecast to
       produce precipitation. `derive_condition` returns `snowy` /
       `snowy-rainy` before it ever looks at thunder (thundersnow) and returns
       `None` when cloud cover is missing, so those hours would otherwise read
       as "no storm".

    Branch (b) deliberately requires precipitation: dry convective CAPE under
    low cloud is a routine Vienna summer afternoon and must not raise a storm
    signal.
    """
    if hour.condition is not None and hour.condition.startswith(_LIGHTNING_PREFIX):
        return True
    precipitation = hour.precipitation or 0.0
    return is_thunder(hour.cape, hour.cin) and precipitation >= PRECIP_MIN_MM


def _is_decidable(hour: HourlyForecast) -> bool:
    """True when the hour carries enough data to judge thunder either way.

    An hour with neither a derived condition nor CAPE says nothing about
    thunder — "no storm" would be a guess, not an answer.
    """
    return hour.condition is not None or hour.cape is not None


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
) -> tuple[datetime | None, float | None]:
    """First hour with thunder expected, and that hour's CAPE.

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
        if _is_lightning(hour):
            return hour.datetime, hour.cape
    return None, None


def thunderstorm_outlook(
    hourly: list[HourlyForecast], hours: int, now: datetime
) -> bool | None:
    """Tri-state thunderstorm outlook for the horizon.

    `True` / `False` when the window holds hours that can be judged, and
    `None` when it holds none at all or none that are decidable — so an entity
    can report "unknown" instead of a confident "off" on a data gap.
    """
    window = _window(hourly, hours, now)
    if any(_is_lightning(hour) for hour in window):
        return True
    if not any(_is_decidable(hour) for hour in window):
        return None
    return False
