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
from .coordinator import GeoSphereCurrentCoordinator, GeoSphereNextConfigEntry
from .entity import device_info
from .models import CurrentConditions


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoSphereNextConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.current
    async_add_entities(
        GeoSphereSensor(coordinator, entry, description) for description in SENSORS
    )


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
