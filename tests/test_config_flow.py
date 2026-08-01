"""Pure validation behavior in the SunsetHue config flow."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER

from custom_components.sunsethue import config_flow
from custom_components.sunsethue.api import (
    SunsetHueAuthError,
    SunsetHueConnectionError,
    SunsetHueInvalidRequestError,
    SunsetHueInvalidResponseError,
    SunsetHueRateLimitError,
)
from custom_components.sunsethue.config_flow import (
    SunsetHueConfigFlow,
    _async_validate_connection,
    _location_unique_id,
    _options_schema,
    _reconfigure_schema,
    _valid_time_zone,
)
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


@pytest.mark.asyncio
async def test_user_flow_reports_auth_failure(hass, aioclient_mock) -> None:
    """Credential failures remain in the form instead of creating an entry."""
    aioclient_mock.get(f"{API_BASE_URL}/event", status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location_name": "Home", "api_key": "test-key", "latitude": 1, "longitude": 2, "time_zone": "UTC"},
    )
    assert result["errors"] == {"base": "invalid_auth"}


def test_normalize_user_input_validates_all_persisted_values() -> None:
    """The flow stores normalized coordinates and never accepts blank secrets."""
    flow = SunsetHueConfigFlow()
    errors: dict[str, str] = {}
    normalized = flow._normalize_user_input(
        {
            "location_name": " Home ",
            "api_key": " key ",
            "latitude": "40.7128123",
            "longitude": "-74.0060123",
            "time_zone": "UTC",
        },
        errors,
    )
    assert errors == {}
    assert normalized is not None
    assert normalized["location_name"] == "Home"
    assert normalized["api_key"] == "key"
    assert normalized["latitude"] == 40.71281


@pytest.mark.parametrize(
    "data, error",
    [
        ({"latitude": "bad", "longitude": 0, "time_zone": "UTC"}, "invalid_coordinates"),
        ({"latitude": 0, "longitude": 181, "time_zone": "UTC"}, "invalid_coordinates"),
        ({"latitude": 0, "longitude": 0, "time_zone": "bad/timezone"}, "invalid_time_zone"),
        ({"latitude": 0, "longitude": 0, "time_zone": "UTC", "location_name": "", "api_key": "key"}, "unknown"),
    ],
)
def test_normalize_user_input_rejects_invalid_values(data, error) -> None:
    """Invalid local form values never result in a network request."""
    errors: dict[str, str] = {}
    assert SunsetHueConfigFlow()._normalize_user_input(data, errors) is None
    assert errors == {"base": error}


@pytest.mark.asyncio
async def test_user_flow_respects_minimum_version(hass, monkeypatch) -> None:
    """Unsupported Home Assistant versions abort before showing credentials."""
    monkeypatch.setattr(config_flow, "is_supported_home_assistant_version", lambda: False)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "abort"
    assert result["reason"] == "min_ha_version"


@pytest.mark.asyncio
async def test_reauth_flow_replaces_api_key(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """Reauthentication validates and saves only the replacement credential."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "new-key"})
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["api_key"] == "new-key"


@pytest.mark.asyncio
async def test_reauth_flow_keeps_form_for_invalid_key(hass, mock_config_entry, aioclient_mock) -> None:
    """A rejected replacement key is not persisted."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE_URL}/event", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "bad-key"})
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data["api_key"] == "test-api-key"


@pytest.mark.asyncio
async def test_reconfigure_flow_retains_api_key(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """Location reconfiguration cannot erase or show the stored credential."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location_name": "Office", "latitude": 41, "longitude": -74, "time_zone": "UTC"},
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["api_key"] == "test-api-key"
    assert mock_config_entry.title == "Office"
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_options_flow_enforces_selection_constraints(hass, mock_config_entry) -> None:
    """The option flow rejects invalid ranges and empty event inventories."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "forecast_days": 1,
            "include_sunrise": False,
            "include_sunset": False,
            "update_interval": "6",
            "create_detailed_entities": False,
        },
    )
    assert result["errors"] == {"base": "no_events_selected"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "forecast_days": 1,
            "include_sunrise": True,
            "include_sunset": False,
            "update_interval": "6",
            "create_detailed_entities": True,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"]["update_interval"] == 6


def test_config_schemas_apply_expected_types() -> None:
    """Reconfigure omits credentials while options retain only supported fields."""
    assert "api_key" not in _reconfigure_schema().schema
    options = _options_schema()(
        {
            "forecast_days": 1,
            "include_sunrise": True,
            "include_sunset": False,
            "update_interval": "6",
            "create_detailed_entities": True,
        }
    )
    assert options["forecast_days"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SunsetHueAuthError(), "invalid_auth"),
        (SunsetHueConnectionError(), "cannot_connect"),
        (SunsetHueRateLimitError(1), "rate_limited"),
        (SunsetHueInvalidRequestError(), "invalid_coordinates"),
        (SunsetHueInvalidResponseError(), "invalid_response"),
        (ValueError(), "invalid_time_zone"),
        (RuntimeError(), "unknown"),
    ],
)
async def test_connection_validation_maps_safe_errors(hass, monkeypatch, error, expected) -> None:
    """The UI surfaces only translated, non-secret connection errors."""

    class Client:
        def __init__(self, *args) -> None:
            pass

        async def async_get_event(self, *args) -> None:
            raise error

    monkeypatch.setattr(config_flow, "SunsetHueClient", Client)
    data = {"api_key": "secret", "latitude": 1, "longitude": 2, "time_zone": "UTC"}
    assert await _async_validate_connection(hass, data) == expected
