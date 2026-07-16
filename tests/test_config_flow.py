"""Tests for the config and options flows."""

from __future__ import annotations

import re
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.geosphere_next.const import (
    CONF_AIR_QUALITY,
    CONF_CURRENT_INTERVAL,
    CONF_FORECAST_INTERVAL,
    CONF_HAS_NOWCAST,
    DOMAIN,
)

from .conftest import AROME_URL, NOWCAST_URL, load_fixture

USER_INPUT = {
    CONF_NAME: "Home Weather",
    CONF_LOCATION: {CONF_LATITUDE: 48.2208, CONF_LONGITUDE: 16.3738},
}


async def test_user_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(NOWCAST_URL, json=load_fixture("nowcast.json"))
    with patch("custom_components.geosphere_next.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Weather"
    assert result["data"] == {
        CONF_LATITUDE: 48.2208,
        CONF_LONGITUDE: 16.3738,
        CONF_HAS_NOWCAST: True,
    }
    assert result["result"].unique_id == "48.2208_16.3738"


async def test_user_flow_out_of_domain(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    aioclient_mock.get(
        AROME_URL, status=400, json=load_fixture("arome_out_of_domain.json")
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Berlin",
            CONF_LOCATION: {CONF_LATITUDE: 52.52, CONF_LONGITUDE: 13.405},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "out_of_domain"}


async def test_user_flow_arome_only_location(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Inside AROME domain but outside Austria -> nowcast disabled."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    aioclient_mock.get(AROME_URL, json=load_fixture("arome.json"))
    aioclient_mock.get(
        NOWCAST_URL, status=400, json=load_fixture("nowcast_out_of_domain.json")
    )
    with patch("custom_components.geosphere_next.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Munich",
                CONF_LOCATION: {CONF_LATITUDE: 48.137, CONF_LONGITUDE: 11.575},
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HAS_NOWCAST] is False


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    aioclient_mock.get(re.compile(r".*"), status=500)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant, mock_config_entry, mock_api) -> None:
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.geosphere_next.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CURRENT_INTERVAL: 10,
                CONF_FORECAST_INTERVAL: 60,
                CONF_AIR_QUALITY: True,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_CURRENT_INTERVAL: 10,
        CONF_FORECAST_INTERVAL: 60,
        CONF_AIR_QUALITY: True,
    }
