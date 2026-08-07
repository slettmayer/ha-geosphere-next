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
from .entity import HourBoundaryRefreshMixin, device_info
from .models import ForecastData
from .outlook import thunderstorm_outlook


@dataclass(frozen=True, kw_only=True)
class GeoSphereBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[ForecastData, datetime], bool | None]


# The 1-hour horizon rounds up to whole hourly steps (see `outlook._window`
# and the README): it covers the in-progress hour plus the next one, so this
# can turn on for a storm ~2 h out.
BINARY_SENSORS: tuple[GeoSphereBinarySensorEntityDescription, ...] = (
    GeoSphereBinarySensorEntityDescription(
        key="thunderstorm_expected_1h",
        translation_key="thunderstorm_expected_1h",
        value_fn=lambda data, now: thunderstorm_outlook(
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
    HourBoundaryRefreshMixin,
    CoordinatorEntity[GeoSphereForecastCoordinator],
    BinarySensorEntity,
):
    """A forecast-outlook binary sensor backed by the forecast coordinator.

    The window is re-evaluated on every hour boundary as well as on
    coordinator updates — see `HourBoundaryRefreshMixin`.
    """

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
    def is_on(self) -> bool | None:
        """Tri-state: None (unknown) when there is no usable forecast window.

        A data gap must not read as a confident "off" — a downstream
        `is_state(..., 'off')` template would treat it as "no storm".
        """
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, dt_util.utcnow())
