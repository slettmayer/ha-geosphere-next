"""Current-condition sensors for GeoSphere Austria Next."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

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
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    OUTLOOK_LONG_HORIZON_HOURS,
    OUTLOOK_SHORT_HORIZON_HOURS,
)
from .coordinator import (
    GeoSphereAirQualityCoordinator,
    GeoSphereCurrentCoordinator,
    GeoSphereForecastCoordinator,
    GeoSphereNextConfigEntry,
)
from .entity import HourBoundaryRefreshMixin, device_info
from .models import AirQualityData, CurrentConditions, ForecastData
from .outlook import max_cape, max_gust, next_thunderstorm


@dataclass(frozen=True, kw_only=True)
class GeoSphereSensorEntityDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[CurrentConditions], float | int | str | None]


def _kmh(value: float | None) -> float | None:
    """Convert m/s (internal model units) to km/h at the entity boundary."""
    return None if value is None else value * 3.6


@dataclass(frozen=True, kw_only=True)
class GeoSphereOutlookSensorEntityDescription(SensorEntityDescription):
    """Forecast-outlook sensor description; value_fn also receives `now`."""

    value_fn: Callable[[ForecastData, datetime], float | datetime | None]
    attributes_fn: Callable[[ForecastData, datetime], dict[str, object]] | None = None


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
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=lambda data: _kmh(data.wind_speed),
    ),
    GeoSphereSensorEntityDescription(
        key="wind_gust_speed",
        translation_key="wind_gust_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=lambda data: _kmh(data.wind_gust_speed),
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
        key="cin",
        translation_key="cin",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="J/kg",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.cin,
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

# These are forecast *predictions*, not measurements, so they deliberately
# carry no `state_class`: long-term statistics over a prediction would mix
# future values into the recorder's history of what actually happened.
#
# The "1h" / "12h" horizons round up to whole hourly steps (see
# `outlook._window` and the README): a 1-hour window covers the in-progress
# hour plus the next one, so these sensors can report an event ~2 h ahead.
OUTLOOK_SENSORS: tuple[GeoSphereOutlookSensorEntityDescription, ...] = (
    GeoSphereOutlookSensorEntityDescription(
        key="wind_gust_max_1h",
        translation_key="wind_gust_max_1h",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=0,
        value_fn=lambda data, now: _kmh(
            max_gust(data.hourly, OUTLOOK_SHORT_HORIZON_HOURS, now)[0]
        ),
    ),
    GeoSphereOutlookSensorEntityDescription(
        key="wind_gust_max_12h",
        translation_key="wind_gust_max_12h",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=0,
        value_fn=lambda data, now: _kmh(
            max_gust(data.hourly, OUTLOOK_LONG_HORIZON_HOURS, now)[0]
        ),
        attributes_fn=lambda data, now: {
            "peak_time": (
                peak.isoformat()
                if (peak := max_gust(data.hourly, OUTLOOK_LONG_HORIZON_HOURS, now)[1])
                else None
            )
        },
    ),
    GeoSphereOutlookSensorEntityDescription(
        key="cape_max_12h",
        translation_key="cape_max_12h",
        native_unit_of_measurement="J/kg",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data, now: max_cape(
            data.hourly, OUTLOOK_LONG_HORIZON_HOURS, now
        ),
    ),
    GeoSphereOutlookSensorEntityDescription(
        key="next_thunderstorm",
        translation_key="next_thunderstorm",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, now: next_thunderstorm(data.hourly, now)[0],
        attributes_fn=lambda data, now: {
            "cape": next_thunderstorm(data.hourly, now)[1]
        },
    ),
)


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
    entities.extend(
        GeoSphereOutlookSensor(entry.runtime_data.forecast, entry, description)
        for description in OUTLOOK_SENSORS
    )
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


class GeoSphereOutlookSensor(
    HourBoundaryRefreshMixin,
    CoordinatorEntity[GeoSphereForecastCoordinator],
    SensorEntity,
):
    """A forecast-outlook sensor backed by the forecast coordinator.

    The window is re-evaluated on every hour boundary as well as on
    coordinator updates — see `HourBoundaryRefreshMixin`.
    """

    entity_description: GeoSphereOutlookSensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: GeoSphereForecastCoordinator,
        entry: GeoSphereNextConfigEntry,
        description: GeoSphereOutlookSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | datetime | None:
        """`None` (unknown) when there is no forecast to scan.

        Guarded like `GeoSphereBinarySensor.is_on`: unreachable while
        `async_config_entry_first_refresh` guarantees data, but the two classes
        are otherwise identical and must not disagree about it.
        """
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        if (
            self.coordinator.data is None
            or self.entity_description.attributes_fn is None
        ):
            return {}
        return self.entity_description.attributes_fn(
            self.coordinator.data, dt_util.utcnow()
        )
