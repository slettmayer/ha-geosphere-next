"""Shared entity base for GeoSphere Austria Next."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_change

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import GeoSphereNextConfigEntry


def device_info(entry: GeoSphereNextConfigEntry) -> DeviceInfo:
    """One service device shared by the weather entity and all sensors."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name=entry.title,
        configuration_url="https://dataset.api.hub.geosphere.at/v1/docs/",
    )


class HourBoundaryRefreshMixin(Entity):
    """Re-writes the entity state just after every full hour.

    Forecast-outlook entities answer questions about a window anchored on
    `now` ("the next hour"), but `CoordinatorEntity` sets
    `should_poll = False`, so their value would otherwise only be recomputed
    when the coordinator refreshes. With `CONF_FORECAST_INTERVAL` set as high
    as 180 min, a "next hour" answer could describe an hour that has already
    elapsed, and a gust could pass unreported.

    Only the window re-evaluates here; forecast *data* still refreshes on the
    coordinator's own interval. The listener fires at hh:00:05 — a few seconds
    past the boundary, so the new hour is unambiguously the current one.
    """

    async def async_added_to_hass(self) -> None:
        """Register the hourly re-evaluation next to the coordinator listener."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_hour_boundary, minute=0, second=5
            )
        )

    @callback
    def _handle_hour_boundary(self, now: datetime) -> None:
        """Recompute the window against the new hour without refetching data."""
        self.async_write_ha_state()


__all__ = ["ATTRIBUTION", "HourBoundaryRefreshMixin", "device_info"]
