"""Current-condition sensors for GeoSphere Austria Next."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import (
    GeoSphereAirQualityCoordinator,
    GeoSphereCurrentCoordinator,
    GeoSphereNextConfigEntry,
)
from .entity import device_info
from .models import AirQualityData, CurrentConditions


@dataclass(frozen=True, kw_only=True)
class GeoSphereSensorEntityDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[CurrentConditions], float | int | str | None]


SENSORS: tuple[GeoSphereSensorEntityDescription, ...] = (
    GeoSphereSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: data.temperature,
    ),
    GeoSphereSensorEntityDescription(
        key="apparent_temperature",
        translation_key="apparent_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: data.apparent_temperature,
    ),
    GeoSphereSensorEntityDescription(
        key="dew_point",
        translation_key="dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: data.dew_point,
    ),
    GeoSphereSensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.humidity,
    ),
    GeoSphereSensorEntityDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
        suggested_display_precision=1,
        value_fn=lambda data: data.pressure_hpa,
    ),
    GeoSphereSensorEntityDescription(
        key="wind_speed",
        translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        value_fn=lambda data: data.wind_speed,
    ),
    GeoSphereSensorEntityDescription(
        key="wind_gust_speed",
        translation_key="wind_gust_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        value_fn=lambda data: data.wind_gust_speed,
    ),
    GeoSphereSensorEntityDescription(
        key="wind_bearing",
        translation_key="wind_bearing",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
        value_fn=lambda data: data.wind_bearing,
    ),
    GeoSphereSensorEntityDescription(
        key="cloud_coverage",
        translation_key="cloud_coverage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.cloud_coverage,
    ),
    GeoSphereSensorEntityDescription(
        key="precipitation_1h",
        translation_key="precipitation_1h",
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1,
        value_fn=lambda data: data.precipitation_1h,
    ),
    GeoSphereSensorEntityDescription(
        key="condition",
        translation_key="condition",
        value_fn=lambda data: data.condition,
    ),
    GeoSphereSensorEntityDescription(
        key="global_radiation",
        translation_key="global_radiation",
        device_class=SensorDeviceClass.IRRADIANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        suggested_display_precision=0,
        value_fn=lambda data: data.global_radiation,
    ),
    GeoSphereSensorEntityDescription(
        key="snow_limit",
        translation_key="snow_limit",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0,
        value_fn=lambda data: data.snow_limit,
    ),
    GeoSphereSensorEntityDescription(
        key="cape",
        translation_key="cape",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="J/kg",
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.cape,
    ),
    GeoSphereSensorEntityDescription(
        key="precipitation_type",
        translation_key="precipitation_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.precipitation_type,
    ),
    GeoSphereSensorEntityDescription(
        key="weather_symbol",
        translation_key="weather_symbol",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.weather_symbol,
    ),
)


def _pollutant_forecast(
    data: AirQualityData, key: str
) -> dict[str, list[dict[str, float | str | None]]]:
    return {
        "forecast": [
            {"datetime": ts.isoformat(), "value": value}
            for ts, value in data.forecast.get(key, [])
        ]
    }


@dataclass(frozen=True, kw_only=True)
class GeoSphereAirQualitySensorEntityDescription(SensorEntityDescription):
    """Air-quality sensor description with value and attribute extractors."""

    value_fn: Callable[[AirQualityData], float | int | None]
    attributes_fn: Callable[[AirQualityData], dict[str, object]]


AIR_QUALITY_SENSORS: tuple[GeoSphereAirQualitySensorEntityDescription, ...] = (
    GeoSphereAirQualitySensorEntityDescription(
        key="nitrogen_dioxide",
        translation_key="nitrogen_dioxide",
        device_class=SensorDeviceClass.NITROGEN_DIOXIDE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        suggested_display_precision=1,
        value_fn=lambda data: data.no2,
        attributes_fn=lambda data: _pollutant_forecast(data, "no2"),
    ),
    GeoSphereAirQualitySensorEntityDescription(
        key="ozone",
        translation_key="ozone",
        device_class=SensorDeviceClass.OZONE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        suggested_display_precision=1,
        value_fn=lambda data: data.o3,
        attributes_fn=lambda data: _pollutant_forecast(data, "o3"),
    ),
    GeoSphereAirQualitySensorEntityDescription(
        key="pm10",
        translation_key="pm10",
        device_class=SensorDeviceClass.PM10,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        suggested_display_precision=1,
        value_fn=lambda data: data.pm10,
        attributes_fn=lambda data: _pollutant_forecast(data, "pm10"),
    ),
    GeoSphereAirQualitySensorEntityDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        suggested_display_precision=1,
        value_fn=lambda data: data.pm25,
        attributes_fn=lambda data: _pollutant_forecast(data, "pm25"),
    ),
    GeoSphereAirQualitySensorEntityDescription(
        key="air_quality_index",
        translation_key="air_quality_index",
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.aqi_today,
        attributes_fn=lambda data: {
            "today": data.aqi_today,
            "tomorrow": data.aqi_tomorrow,
            "in_2_days": data.aqi_in_2_days,
        },
    ),
)

# Consumed by __init__ to clean the entity registry when the option is off.
AIR_QUALITY_SENSOR_KEYS = tuple(description.key for description in AIR_QUALITY_SENSORS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoSphereNextConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.current
    entities: list[SensorEntity] = [
        GeoSphereSensor(coordinator, entry, description) for description in SENSORS
    ]
    if (air_quality := entry.runtime_data.air_quality) is not None:
        entities.extend(
            GeoSphereAirQualitySensor(air_quality, entry, description)
            for description in AIR_QUALITY_SENSORS
        )
    async_add_entities(entities)


class GeoSphereSensor(CoordinatorEntity[GeoSphereCurrentCoordinator], SensorEntity):
    """A current-condition sensor backed by the current coordinator."""

    entity_description: GeoSphereSensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: GeoSphereCurrentCoordinator,
        entry: GeoSphereNextConfigEntry,
        description: GeoSphereSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.coordinator.data)


class GeoSphereAirQualitySensor(
    CoordinatorEntity[GeoSphereAirQualityCoordinator], SensorEntity
):
    """An air-quality sensor backed by the air-quality coordinator."""

    entity_description: GeoSphereAirQualitySensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    # The ~61-entry hourly forecast is for dashboards, not for history.
    _unrecorded_attributes = frozenset({"forecast"})

    def __init__(
        self,
        coordinator: GeoSphereAirQualityCoordinator,
        entry: GeoSphereNextConfigEntry,
        description: GeoSphereAirQualitySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return self.entity_description.attributes_fn(self.coordinator.data)
