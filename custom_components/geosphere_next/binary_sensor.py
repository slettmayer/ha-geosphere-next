"""Binary sensors for GeoSphere Austria Next.

Two groups on two coordinators: forecast-outlook sensors scan the hourly
series ahead, current-condition sensors report the analysis for now.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, OUTLOOK_SHORT_HORIZON_HOURS
from .coordinator import (
    GeoSphereCurrentCoordinator,
    GeoSphereForecastCoordinator,
    GeoSphereNextConfigEntry,
)
from .entity import HourBoundaryRefreshMixin, device_info
from .models import CurrentConditions, ForecastData
from .outlook import thunderstorm_outlook


@dataclass(frozen=True, kw_only=True)
class GeoSphereBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Forecast-outlook binary sensor description.

    `state_fn` returns the state and the attributes together, from one scan
    of the series at one `now`.
    """

    state_fn: Callable[[ForecastData, datetime], tuple[bool | None, dict[str, object]]]


def _thunderstorm_state(
    data: ForecastData, now: datetime
) -> tuple[bool | None, dict[str, object]]:
    expected, source = thunderstorm_outlook(
        data.hourly, OUTLOOK_SHORT_HORIZON_HOURS, now
    )
    return expected, {"source": source}


# The 1-hour horizon rounds up to whole hourly steps (see `outlook._window`
# and the README): it covers the in-progress hour plus the next one, so this
# can turn on for a storm ~2 h out. `source` names the signal that turned it
# on: the weather symbol, the ensemble, or both.
BINARY_SENSORS: tuple[GeoSphereBinarySensorEntityDescription, ...] = (
    GeoSphereBinarySensorEntityDescription(
        key="thunderstorm_expected_1h",
        translation_key="thunderstorm_expected_1h",
        state_fn=_thunderstorm_state,
    ),
)


@dataclass(frozen=True, kw_only=True)
class GeoSphereCurrentBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description reading the current-conditions model."""

    value_fn: Callable[[CurrentConditions], bool | None]


CURRENT_BINARY_SENSORS: tuple[GeoSphereCurrentBinarySensorEntityDescription, ...] = (
    GeoSphereCurrentBinarySensorEntityDescription(
        key="precipitating",
        translation_key="precipitating",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda data: data.is_precipitating,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoSphereNextConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    entities: list[BinarySensorEntity] = [
        GeoSphereBinarySensor(entry.runtime_data.forecast, entry, description)
        for description in BINARY_SENSORS
    ]
    entities.extend(
        GeoSphereCurrentBinarySensor(entry.runtime_data.current, entry, description)
        for description in CURRENT_BINARY_SENSORS
    )
    async_add_entities(entities)


class GeoSphereBinarySensor(
    HourBoundaryRefreshMixin,
    CoordinatorEntity[GeoSphereForecastCoordinator],
    BinarySensorEntity,
):
    """A forecast-outlook binary sensor backed by the forecast coordinator.

    State and attributes are computed together, from one sample of the clock,
    whenever the coordinator updates or an hour boundary passes — see
    `GeoSphereOutlookSensor._refresh_outlook`, which this mirrors, and
    `HourBoundaryRefreshMixin`.
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
        # Populate before the platform performs its first state write.
        self._refresh_outlook()

    @callback
    def _refresh_outlook(self) -> None:
        """Recompute state and attributes from a single sample of the clock.

        Tri-state: None (unknown) when there is no usable forecast window. A
        data gap must not read as a confident "off" — a downstream
        `is_state(..., 'off')` template would treat it as "no storm".
        """
        data = self.coordinator.data
        if data is None:
            self._attr_is_on = None
            self._attr_extra_state_attributes = {}
            return
        self._attr_is_on, self._attr_extra_state_attributes = (
            self.entity_description.state_fn(data, dt_util.utcnow())
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_outlook()
        super()._handle_coordinator_update()

    @callback
    def _handle_hour_boundary(self, now: datetime) -> None:
        self._refresh_outlook()
        super()._handle_hour_boundary(now)


class GeoSphereCurrentBinarySensor(
    CoordinatorEntity[GeoSphereCurrentCoordinator], BinarySensorEntity
):
    """A current-condition binary sensor backed by the current coordinator."""

    entity_description: GeoSphereCurrentBinarySensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: GeoSphereCurrentCoordinator,
        entry: GeoSphereNextConfigEntry,
        description: GeoSphereCurrentBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        """Tri-state: None (unknown) when there are no current conditions."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
