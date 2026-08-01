"""Pure validation behavior in the SunsetHue config flow."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER

from custom_components.sunsethue.config_flow import _location_unique_id, _valid_time_zone
from custom_components.sunsethue.const import API_BASE_URL, DOMAIN


def test_location_unique_id_is_normalized() -> None:
    """Equivalent coordinate precision cannot create duplicate entries."""
    assert _location_unique_id(1, 2) == _location_unique_id(1.0000001, 2.0000001)


def test_invalid_time_zone_is_rejected() -> None:
    """Only IANA time zone identifiers are persisted."""
    try:
        _valid_time_zone("not/a-time-zone")
    except vol.Invalid:
        pass
    else:
        raise AssertionError("invalid time zone was accepted")


@pytest.mark.asyncio
async def test_user_flow_creates_entry(hass, aioclient_mock, event_full) -> None:
    """The UI flow validates a real documented endpoint response."""
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 40.7128,
            "longitude": -74.006,
            "time_zone": "America/New_York",
        },
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Home"
    assert result["data"]["api_key"] == "test-key"


@pytest.mark.asyncio
async def test_user_flow_rejects_invalid_coordinates(hass) -> None:
    """Coordinate bounds are enforced before any API request."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 91,
            "longitude": 0,
            "time_zone": "UTC",
        },
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_coordinates"}
