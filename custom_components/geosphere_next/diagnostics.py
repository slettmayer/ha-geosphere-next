"""Diagnostics for GeoSphere Austria Next."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .coordinator import GeoSphereNextConfigEntry

TO_REDACT = {CONF_LATITUDE, CONF_LONGITUDE, "grid_latitude", "grid_longitude"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GeoSphereNextConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    forecast = entry.runtime_data.forecast
    current = entry.runtime_data.current
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "forecast": {
            "last_update_success": forecast.last_update_success,
            "data": (
                async_redact_data(asdict(forecast.data), TO_REDACT)
                if forecast.data
                else None
            ),
        },
        "current": {
            "last_update_success": current.last_update_success,
            "has_nowcast": current.has_nowcast,
            "data": asdict(current.data) if current.data else None,
        },
    }
