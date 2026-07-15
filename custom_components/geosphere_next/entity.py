"""Shared entity base for GeoSphere Austria Next."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

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


__all__ = ["ATTRIBUTION", "device_info"]
