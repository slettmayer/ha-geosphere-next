"""Config flow for GeoSphere Austria Next."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    LocationSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    GeoSphereApiClient,
    GeoSphereApiError,
    GeoSphereOutOfDomainError,
)
from .const import (
    CONF_AIR_QUALITY,
    CONF_CURRENT_INTERVAL,
    CONF_FORECAST_INTERVAL,
    CONF_HAS_NOWCAST,
    DATASET_AROME,
    DATASET_NOWCAST,
    DEFAULT_CURRENT_INTERVAL_MINUTES,
    DEFAULT_FORECAST_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class GeoSphereNextConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            latitude = user_input[CONF_LOCATION][CONF_LATITUDE]
            longitude = user_input[CONF_LOCATION][CONF_LONGITUDE]
            await self.async_set_unique_id(f"{latitude:.4f}_{longitude:.4f}")
            self._abort_if_unique_id_configured()

            client = GeoSphereApiClient(async_get_clientsession(self.hass))
            has_nowcast = True
            try:
                await client.get_timeseries(
                    *DATASET_AROME,
                    parameters=("t2m",),
                    latitude=latitude,
                    longitude=longitude,
                )
            except GeoSphereOutOfDomainError:
                errors["base"] = "out_of_domain"
            except GeoSphereApiError:
                errors["base"] = "cannot_connect"
            else:
                try:
                    await client.get_timeseries(
                        *DATASET_NOWCAST,
                        parameters=("t2m",),
                        latitude=latitude,
                        longitude=longitude,
                    )
                except GeoSphereOutOfDomainError:
                    # Inside the AROME domain but outside Austria: forecast
                    # works, current conditions degrade to AROME step 0.
                    has_nowcast = False
                except GeoSphereApiError:
                    errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_LATITUDE: latitude,
                        CONF_LONGITUDE: longitude,
                        CONF_HAS_NOWCAST: has_nowcast,
                    },
                )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(
                        CONF_LOCATION,
                        default={
                            CONF_LATITUDE: self.hass.config.latitude,
                            CONF_LONGITUDE: self.hass.config.longitude,
                        },
                    ): LocationSelector(),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GeoSphereNextOptionsFlow:
        """Get the options flow."""
        return GeoSphereNextOptionsFlow()


class GeoSphereNextOptionsFlow(OptionsFlowWithReload):
    """Handle options (update intervals)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CURRENT_INTERVAL,
                        default=options.get(
                            CONF_CURRENT_INTERVAL, DEFAULT_CURRENT_INTERVAL_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=5,
                            max=60,
                            step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="min",
                        )
                    ),
                    vol.Required(
                        CONF_FORECAST_INTERVAL,
                        default=options.get(
                            CONF_FORECAST_INTERVAL, DEFAULT_FORECAST_INTERVAL_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=15,
                            max=180,
                            step=15,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="min",
                        )
                    ),
                    vol.Required(
                        CONF_AIR_QUALITY,
                        default=options.get(CONF_AIR_QUALITY, False),
                    ): BooleanSelector(),
                }
            ),
        )
