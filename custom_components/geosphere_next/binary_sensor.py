"""Forecast-outlook binary sensors for GeoSphere Austria Next."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, OUTLOOK_SHORT_HORIZON_HOURS
from .coordinator import GeoSphereForecastCoordinator, GeoSphereNextConfigEntry
from .entity import device_info
from .models import ForecastData
from .outlook import thunderstorm_within


@dataclass(frozen=True, kw_only=True)
class GeoSphereBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[ForecastData, datetime], bool]


BINARY_SENSORS: tuple[GeoSphereBinarySensorEntityDescription, ...] = (
    GeoSphereBinarySensorEntityDescription(
        key="thunderstorm_expected_1h",
        translation_key="thunderstorm_expected_1h",
        value_fn=lambda data, now: thunderstorm_within(
            data.hourly, OUTLOOK_SHORT_HORIZON_HOURS, now
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoSphereNextConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    async_add_entities(
        GeoSphereBinarySensor(entry.runtime_data.forecast, entry, description)
        for description in BINARY_SENSORS
    )


class GeoSphereBinarySensor(
    CoordinatorEntity[GeoSphereForecastCoordinator], BinarySensorEntity
):
    """A forecast-outlook binary sensor backed by the forecast coordinator."""

    entity_description: GeoSphereBinarySensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: GeoSphereForecastCoordinator,
        entry: GeoSphereNextConfigEntry,
        description: GeoSphereBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data, dt_util.utcnow())
