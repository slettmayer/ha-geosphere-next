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
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=hours)
    return [hour for hour in hourly if start <= hour.datetime <= end]


def _is_lightning(hour: HourlyForecast) -> bool:
    return hour.condition is not None and hour.condition.startswith(_LIGHTNING_PREFIX)


def max_gust(
    hourly: list[HourlyForecast], hours: int, now: datetime
) -> tuple[float | None, datetime | None]:
    """Peak gust (m/s) within the horizon and the hour it falls in."""
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
    """Peak CAPE (J/kg) within the horizon."""
    values = [
        hour.cape for hour in _window(hourly, hours, now) if hour.cape is not None
    ]
    return max(values) if values else None


def next_thunderstorm(
    hourly: list[HourlyForecast], now: datetime
) -> tuple[datetime | None, float | None]:
    """First hour with a lightning condition, and that hour's CAPE.

    Scans the full horizon rather than a window — "no storm for two days" and
    "storm in 40 hours" are both useful answers.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    for hour in hourly:
        if hour.datetime < start:
            continue
        if _is_lightning(hour):
            return hour.datetime, hour.cape
    return None, None


def thunderstorm_within(
    hourly: list[HourlyForecast], hours: int, now: datetime
) -> bool:
    """True when any hour in the horizon carries a lightning condition."""
    return any(_is_lightning(hour) for hour in _window(hourly, hours, now))
