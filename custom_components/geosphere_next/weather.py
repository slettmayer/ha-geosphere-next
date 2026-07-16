"""Weather entity for GeoSphere Austria Next."""

from __future__ import annotations

from homeassistant.components.weather import (
    ATTR_FORECAST_CLOUD_COVERAGE,
    ATTR_FORECAST_CONDITION,
    ATTR_FORECAST_HUMIDITY,
    ATTR_FORECAST_NATIVE_DEW_POINT,
    ATTR_FORECAST_NATIVE_PRECIPITATION,
    ATTR_FORECAST_NATIVE_TEMP,
    ATTR_FORECAST_NATIVE_WIND_GUST_SPEED,
    ATTR_FORECAST_NATIVE_WIND_SPEED,
    ATTR_FORECAST_TIME,
    ATTR_FORECAST_WIND_BEARING,
    CoordinatorWeatherEntity,
    Forecast,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTRIBUTION
from .coordinator import (
    GeoSphereCurrentCoordinator,
    GeoSphereForecastCoordinator,
    GeoSphereNextConfigEntry,
)
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoSphereNextConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the weather entity."""
    async_add_entities([GeoSphereWeather(entry)])


class GeoSphereWeather(
    CoordinatorWeatherEntity[
        GeoSphereCurrentCoordinator,
        GeoSphereForecastCoordinator,
        GeoSphereForecastCoordinator,
    ]
):
    """Weather entity backed by the current + forecast coordinators.

    Hourly forecast only: AROME's ~60 h horizon yields at most 2-3 aggregable
    local days, and the HA frontend only renders forecast arrays with more
    than 2 entries — a daily tab would intermittently spin forever.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = ATTRIBUTION
    _attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS

    def __init__(self, entry: GeoSphereNextConfigEntry) -> None:
        super().__init__(
            entry.runtime_data.current,
            hourly_coordinator=entry.runtime_data.forecast,
        )
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = device_info(entry)

    @property
    def condition(self) -> str | None:
        return self.coordinator.data.condition

    @property
    def native_temperature(self) -> float | None:
        return self.coordinator.data.temperature

    @property
    def native_apparent_temperature(self) -> float | None:
        return self.coordinator.data.apparent_temperature

    @property
    def native_dew_point(self) -> float | None:
        return self.coordinator.data.dew_point

    @property
    def humidity(self) -> float | None:
        return self.coordinator.data.humidity

    @property
    def native_pressure(self) -> float | None:
        return self.coordinator.data.pressure_hpa

    @property
    def native_wind_speed(self) -> float | None:
        return self.coordinator.data.wind_speed

    @property
    def wind_bearing(self) -> float | None:
        return self.coordinator.data.wind_bearing

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self.coordinator.data.wind_gust_speed

    @property
    def cloud_coverage(self) -> int | None:
        cloud = self.coordinator.data.cloud_coverage
        return int(cloud) if cloud is not None else None

    @callback
    def _async_forecast_hourly(self) -> list[Forecast] | None:
        coordinator = self.forecast_coordinators["hourly"]
        if coordinator is None or coordinator.data is None:
            return None
        return [
            Forecast(
                {
                    ATTR_FORECAST_TIME: hour.datetime.isoformat(),
                    ATTR_FORECAST_CONDITION: hour.condition,
                    ATTR_FORECAST_NATIVE_TEMP: hour.temperature,
                    ATTR_FORECAST_NATIVE_DEW_POINT: hour.dew_point,
                    ATTR_FORECAST_HUMIDITY: hour.humidity,
                    ATTR_FORECAST_NATIVE_PRECIPITATION: hour.precipitation,
                    ATTR_FORECAST_NATIVE_WIND_SPEED: hour.wind_speed,
                    ATTR_FORECAST_WIND_BEARING: hour.wind_bearing,
                    ATTR_FORECAST_NATIVE_WIND_GUST_SPEED: hour.wind_gust_speed,
                    ATTR_FORECAST_CLOUD_COVERAGE: hour.cloud_coverage,
                }
            )
            for hour in coordinator.data.hourly
        ]
