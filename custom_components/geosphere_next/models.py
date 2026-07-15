"""Data models for the GeoSphere Austria Next integration.

Kept free of homeassistant imports (see api.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ParameterSeries:
    """One parameter's series within a timeseries response."""

    name: str
    unit: str
    data: list[float | None]


@dataclass(slots=True)
class GeoSphereResponse:
    """Parsed GeoJSON timeseries response."""

    resource_id: str
    reference_time: datetime | None
    timestamps: list[datetime]
    parameters: dict[str, ParameterSeries]
    grid_longitude: float
    grid_latitude: float

    def series(self, name: str) -> list[float | None]:
        if name not in self.parameters:
            return [None] * len(self.timestamps)
        return self.parameters[name].data

    def value_at(self, name: str, index: int) -> float | None:
        data = self.series(name)
        if 0 <= index < len(data):
            return data[index]
        return None


@dataclass(slots=True)
class HourlyForecast:
    """One processed AROME forecast hour. Units: °C, %, mm, m/s, °, hPa, J/kg."""

    datetime: datetime
    temperature: float | None
    templow: float | None
    temphigh: float | None
    humidity: float | None
    precipitation: float | None
    snow: float | None
    wind_speed: float | None
    wind_bearing: float | None
    wind_gust_speed: float | None
    cloud_coverage: float | None
    cape: float | None
    condition: str | None = None


@dataclass(slots=True)
class DailyForecast:
    """One derived daily forecast entry."""

    datetime: datetime
    temperature: float | None
    templow: float | None
    precipitation: float | None
    wind_speed: float | None
    wind_bearing: float | None
    humidity: float | None
    condition: str | None = None


@dataclass(slots=True)
class ForecastData:
    """Processed forecast-coordinator data."""

    reference_time: datetime | None
    grid_latitude: float
    grid_longitude: float
    hourly: list[HourlyForecast] = field(default_factory=list)
    daily: list[DailyForecast] = field(default_factory=list)
    # "Step 0" snapshot for current-state fallbacks (first future-most hour).
    current: HourlyForecast | None = None
    snow_limit: float | None = None
    weather_symbol: int | None = None


@dataclass(slots=True)
class CurrentConditions:
    """Merged current conditions (nowcast → INCA → AROME fallback chain)."""

    observed_at: datetime | None = None
    temperature: float | None = None
    apparent_temperature: float | None = None
    dew_point: float | None = None
    humidity: float | None = None
    pressure_hpa: float | None = None
    wind_speed: float | None = None
    wind_bearing: float | None = None
    wind_gust_speed: float | None = None
    precipitation_1h: float | None = None
    precipitation_type: int | None = None
    is_precipitating: bool = False
    cloud_coverage: float | None = None
    global_radiation: float | None = None
    snow_limit: float | None = None
    cape: float | None = None
    weather_symbol: int | None = None
    condition: str | None = None
