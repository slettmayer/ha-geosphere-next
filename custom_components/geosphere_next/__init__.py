"""The GeoSphere Austria Next integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GeoSphereApiClient
from .const import CONF_AIR_QUALITY
from .coordinator import (
    GeoSphereAirQualityCoordinator,
    GeoSphereCurrentCoordinator,
    GeoSphereForecastCoordinator,
    GeoSphereNextConfigEntry,
    GeoSphereNextData,
)
from .sensor import AIR_QUALITY_SENSOR_KEYS

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

    air_quality: GeoSphereAirQualityCoordinator | None = None
    if entry.options.get(CONF_AIR_QUALITY, False):
        air_quality = GeoSphereAirQualityCoordinator(hass, entry, client)
        await air_quality.async_config_entry_first_refresh()
    else:
        _remove_air_quality_entities(hass, entry)

    entry.runtime_data = GeoSphereNextData(
        client=client, forecast=forecast, current=current, air_quality=air_quality
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_air_quality_entities(
    hass: HomeAssistant, entry: GeoSphereNextConfigEntry
) -> None:
    """Drop leftover air-quality entities after the option was switched off."""
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id in {
            f"{entry.entry_id}-{key}" for key in AIR_QUALITY_SENSOR_KEYS
        }:
            registry.async_remove(reg_entry.entity_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: GeoSphereNextConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
