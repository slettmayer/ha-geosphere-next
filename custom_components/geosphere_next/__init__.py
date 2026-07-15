"""The GeoSphere Austria Next integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GeoSphereApiClient
from .coordinator import (
    GeoSphereCurrentCoordinator,
    GeoSphereForecastCoordinator,
    GeoSphereNextConfigEntry,
    GeoSphereNextData,
)

PLATFORMS = [Platform.SENSOR, Platform.WEATHER]


async def async_setup_entry(
    hass: HomeAssistant, entry: GeoSphereNextConfigEntry
) -> bool:
    """Set up GeoSphere Austria Next from a config entry."""
    client = GeoSphereApiClient(async_get_clientsession(hass))
    forecast = GeoSphereForecastCoordinator(hass, entry, client)
    await forecast.async_config_entry_first_refresh()
    current = GeoSphereCurrentCoordinator(hass, entry, client, forecast)
    await current.async_config_entry_first_refresh()

    entry.runtime_data = GeoSphereNextData(
        client=client, forecast=forecast, current=current
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: GeoSphereNextConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
