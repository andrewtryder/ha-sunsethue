"""Pure validation behavior in the SunsetHue config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import InvalidData
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry
from voluptuous_serialize import convert

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
    SunsetHueOptionsFlow,
    _async_validate_connection,
    _normalize_coordinate,
    _options_schema,
    _reconfigure_schema,
    _update_interval_selector_value,
    _valid_time_zone,
)
from custom_components.sunsethue.const import (
    API_BASE_URL,
    CONF_CREATE_DETAILED_ENTITIES,
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    CONF_LOCATION_ID,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)


def test_normalized_coordinates_are_stable() -> None:
    """Equivalent coordinate precision identifies the same configured place."""
    assert _normalize_coordinate(1) == _normalize_coordinate(1.0000001)


def test_invalid_time_zone_is_rejected() -> None:
    """Only IANA time zone identifiers are persisted."""
    try:
        _valid_time_zone("not/a-time-zone")
    except vol.Invalid:
        pass
    else:
        raise AssertionError("invalid time zone was accepted")


@pytest.mark.asyncio
async def test_user_form_schema_is_frontend_serializable(hass) -> None:
    """The initial form schema can be converted for the frontend."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "form"
    serialized = convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert serialized


@pytest.mark.asyncio
async def test_all_config_flow_forms_are_frontend_serializable(hass, mock_config_entry) -> None:
    """Every form returned by SunsetHue can be serialized."""
    user_result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    convert(user_result["data_schema"], custom_serializer=cv.custom_serializer)

    mock_config_entry.add_to_hass(hass)

    reauth_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
    )
    convert(reauth_result["data_schema"], custom_serializer=cv.custom_serializer)

    reconfigure_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    convert(reconfigure_result["data_schema"], custom_serializer=cv.custom_serializer)

    options_result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    convert(options_result["data_schema"], custom_serializer=cv.custom_serializer)


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
    assert result["data"][CONF_LOCATION_ID]


@pytest.mark.asyncio
async def test_user_flow_uses_home_assistant_location_defaults(hass) -> None:
    """The initial form starts from Home Assistant's configured location."""
    hass.config.location_name = "Configured home"
    hass.config.latitude = 12.34
    hass.config.longitude = 56.78
    hass.config.time_zone = "UTC"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    defaults = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert {key: defaults[key] for key in ("location_name", "latitude", "longitude", "time_zone")} == {
        "location_name": "Configured home",
        "latitude": 12.34,
        "longitude": 56.78,
        "time_zone": "UTC",
    }


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


@pytest.mark.asyncio
async def test_user_flow_rejects_duplicate_normalized_location(hass, mock_config_entry) -> None:
    """Opaque entry IDs do not weaken location duplicate prevention."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Duplicate",
            "api_key": "test-key",
            "latitude": 40.7128001,
            "longitude": -74.0060001,
            "time_zone": "America/New_York",
        },
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_user_flow_recovers_after_connection_error(hass, monkeypatch) -> None:
    """A user can correct a transient validation failure in the same flow."""
    validate = AsyncMock(side_effect=["cannot_connect", None])
    monkeypatch.setattr(config_flow, "_async_validate_connection", validate)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    user_input = {"location_name": "Home", "api_key": "key", "latitude": 1, "longitude": 2, "time_zone": "UTC"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] == "create_entry"


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
    assert normalized[CONF_LOCATION_ID]


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


@pytest.mark.asyncio
async def test_reconfigure_rejects_another_entry_location(hass, mock_config_entry) -> None:
    """Reconfigure performs the same coordinate duplicate check as setup."""
    mock_config_entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Office",
        unique_id="office-location-id",
        data={**mock_config_entry.data, CONF_LOCATION_ID: "office-location-id", "latitude": 41, "longitude": -74},
    )
    other.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location_name": "Home", "latitude": 41, "longitude": -74, "time_zone": "UTC"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_input",
    [
        {"forecast_days": 4, "update_interval": "6"},
        {"forecast_days": 1, "update_interval": "5"},
    ],
)
async def test_options_flow_recovers_from_invalid_range(hass, mock_config_entry, user_input) -> None:
    """Selector bounds reject invalid options without persisting them."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    invalid = {
        "forecast_days": 1,
        "include_sunrise": True,
        "include_sunset": False,
        "update_interval": "6",
        "create_detailed_entities": False,
        **user_input,
    }
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(result["flow_id"], invalid)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    valid = {**invalid, "forecast_days": 1, "update_interval": "12"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], valid)
    assert result["type"] == "create_entry"


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


def _suggested_values(schema: vol.Schema) -> dict[str, object]:
    """Extract suggested values attached by add_suggested_values_to_schema."""
    return {
        key.schema: key.description["suggested_value"]
        for key in schema.schema
        if key.description and "suggested_value" in key.description
    }


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (6, "6"),
        (12, "12"),
        (24, "24"),
        ("6", "6"),
        ("12", "12"),
        ("24", "24"),
        (None, "6"),
        (5, "6"),
        ("bad", "6"),
        (True, "6"),
    ],
)
def test_update_interval_selector_value_normalizes(stored: object, expected: str) -> None:
    """Stored intervals become valid SelectSelector strings."""
    assert _update_interval_selector_value(stored) == expected


@pytest.mark.asyncio
async def test_options_form_suggests_string_update_interval(hass, mock_config_entry) -> None:
    """Integer stored intervals must not raise expected str against the selector."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id="interval-home",
        data=mock_config_entry.data,
        options={CONF_UPDATE_INTERVAL: 6},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_UPDATE_INTERVAL] == "6"
    assert isinstance(suggested[CONF_UPDATE_INTERVAL], str)
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    validated = result["data_schema"](
        {
            CONF_FORECAST_DAYS: suggested.get(CONF_FORECAST_DAYS, 3),
            CONF_INCLUDE_SUNRISE: suggested.get(CONF_INCLUDE_SUNRISE, True),
            CONF_INCLUDE_SUNSET: suggested.get(CONF_INCLUDE_SUNSET, True),
            CONF_UPDATE_INTERVAL: suggested[CONF_UPDATE_INTERVAL],
            CONF_CREATE_DETAILED_ENTITIES: suggested.get(CONF_CREATE_DETAILED_ENTITIES, False),
        }
    )
    assert validated[CONF_UPDATE_INTERVAL] == "6"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (6, "6"),
        (12, "12"),
        (24, "24"),
        ("6", "6"),
        ("12", "12"),
        ("24", "24"),
        (None, "6"),
        (5, "6"),
        ("bad", "6"),
    ],
)
async def test_options_form_normalizes_stored_intervals(hass, mock_config_entry, stored, expected) -> None:
    """Legacy and malformed stored intervals still render as valid selector strings."""
    options = {} if stored is None else {CONF_UPDATE_INTERVAL: stored}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=f"interval-{expected}-{stored!s}",
        data=mock_config_entry.data,
        options=options,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_UPDATE_INTERVAL] == expected
    result["data_schema"](
        {
            CONF_FORECAST_DAYS: 3,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: suggested[CONF_UPDATE_INTERVAL],
            CONF_CREATE_DETAILED_ENTITIES: False,
        }
    )


@pytest.mark.asyncio
async def test_options_flow_persists_integer_update_interval(hass, mock_config_entry) -> None:
    """Selector strings are stored as integers in config-entry options."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_FORECAST_DAYS: 1,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: "12",
            CONF_CREATE_DETAILED_ENTITIES: True,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_UPDATE_INTERVAL] == 12
    assert isinstance(result["data"][CONF_UPDATE_INTERVAL], int)


@pytest.mark.asyncio
async def test_options_flow_preserves_values_after_validation_error(hass, mock_config_entry) -> None:
    """Recoverable options errors keep the user's submitted selections visible."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    invalid = {
        CONF_FORECAST_DAYS: 2,
        CONF_INCLUDE_SUNRISE: False,
        CONF_INCLUDE_SUNSET: False,
        CONF_UPDATE_INTERVAL: "12",
        CONF_CREATE_DETAILED_ENTITIES: True,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], invalid)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_events_selected"}
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_FORECAST_DAYS] == 2
    assert suggested[CONF_INCLUDE_SUNRISE] is False
    assert suggested[CONF_INCLUDE_SUNSET] is False
    assert suggested[CONF_UPDATE_INTERVAL] == "12"
    assert suggested[CONF_CREATE_DETAILED_ENTITIES] is True
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    result["data_schema"](dict(suggested))
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **invalid,
            CONF_INCLUDE_SUNRISE: True,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_UPDATE_INTERVAL] == 12
    assert result["data"][CONF_FORECAST_DAYS] == 2


@pytest.mark.asyncio
async def test_options_flow_maps_malformed_input_to_form_errors(hass, mock_config_entry) -> None:
    """Direct options submissions never escape as uncaught type errors."""
    mock_config_entry.add_to_hass(hass)
    flow = SunsetHueOptionsFlow()
    flow.hass = hass
    flow.handler = mock_config_entry.entry_id

    malformed = await flow.async_step_init(
        {
            CONF_FORECAST_DAYS: "bad",
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: "6",
            CONF_CREATE_DETAILED_ENTITIES: False,
        }
    )
    assert malformed["type"] == "form"
    assert malformed["errors"] == {"base": "unknown"}

    invalid_days = await flow.async_step_init(
        {
            CONF_FORECAST_DAYS: 4,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: "6",
            CONF_CREATE_DETAILED_ENTITIES: False,
        }
    )
    assert invalid_days["errors"] == {"base": "invalid_forecast_days"}

    invalid_interval = await flow.async_step_init(
        {
            CONF_FORECAST_DAYS: 1,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: "5",
            CONF_CREATE_DETAILED_ENTITIES: False,
        }
    )
    assert invalid_interval["errors"] == {"base": "invalid_update_interval"}
    suggested = _suggested_values(invalid_interval["data_schema"])
    assert suggested[CONF_UPDATE_INTERVAL] == "6"

    non_bool = await flow.async_step_init(
        {
            CONF_FORECAST_DAYS: 1,
            CONF_INCLUDE_SUNRISE: "yes",
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: "6",
            CONF_CREATE_DETAILED_ENTITIES: False,
        }
    )
    assert non_bool["errors"] == {"base": "unknown"}

    non_bool_detail = await flow.async_step_init(
        {
            CONF_FORECAST_DAYS: 1,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_UPDATE_INTERVAL: "6",
            CONF_CREATE_DETAILED_ENTITIES: "yes",
        }
    )
    assert non_bool_detail["errors"] == {"base": "unknown"}

    missing_key = await flow.async_step_init(
        {
            CONF_FORECAST_DAYS: 1,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: True,
            CONF_CREATE_DETAILED_ENTITIES: False,
        }
    )
    assert missing_key["errors"] == {"base": "unknown"}


@pytest.mark.asyncio
async def test_all_forms_suggested_values_round_trip(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """Every SunsetHue form accepts its own suggested values without type mismatch."""
    del aioclient_mock, event_full
    user_result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    user_suggested = _suggested_values(user_result["data_schema"])
    convert(user_result["data_schema"], custom_serializer=cv.custom_serializer)
    user_result["data_schema"](
        {
            **user_suggested,
            "api_key": "test-key",
        }
    )

    mock_config_entry.add_to_hass(hass)

    reauth_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
    )
    convert(reauth_result["data_schema"], custom_serializer=cv.custom_serializer)

    reconfigure_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    convert(reconfigure_result["data_schema"], custom_serializer=cv.custom_serializer)
    reconfigure_result["data_schema"](_suggested_values(reconfigure_result["data_schema"]))

    options_result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    convert(options_result["data_schema"], custom_serializer=cv.custom_serializer)
    options_suggested = _suggested_values(options_result["data_schema"])
    options_result["data_schema"](options_suggested)
    assert isinstance(options_suggested[CONF_UPDATE_INTERVAL], str)


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
