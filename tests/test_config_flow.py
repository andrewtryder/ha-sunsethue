"""Pure validation behavior in the SunsetHue config flow."""

from __future__ import annotations

from datetime import UTC, datetime
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
    _async_reconfigure_schema,
    _async_user_schema,
    _async_validate_connection,
    _format_utc_offset,
    _normalize_coordinate,
    _options_schema,
    _time_zone_names,
    _time_zone_options,
    _valid_time_zone,
)
from custom_components.sunsethue.const import API_BASE_URL, CONF_API_KEY, CONF_LOCATION_ID, CONF_TIME_ZONE, DOMAIN


def _suggested_values(schema) -> dict:
    """Return suggested values attached to a form schema."""
    return {
        key.schema: key.description["suggested_value"]
        for key in schema.schema
        if key.description and "suggested_value" in key.description
    }


def _time_zone_selector_options(schema) -> list[dict[str, str]]:
    """Return the labeled options from the time-zone SelectSelector."""
    for key, validator in schema.schema.items():
        if key.schema == CONF_TIME_ZONE:
            return list(validator.config["options"])
    raise AssertionError("time_zone selector missing from schema")


def test_normalized_coordinates_are_stable() -> None:
    """Equivalent coordinate precision identifies the same configured place."""
    assert _normalize_coordinate(1) == _normalize_coordinate(1.0000001)


@pytest.mark.parametrize(
    "time_zone",
    ["", "/etc/passwd", "../UTC", "not/a-time-zone"],
)
def test_invalid_time_zone_is_rejected(time_zone: str) -> None:
    """Malformed and unknown zone keys raise a form-friendly validation error."""
    with pytest.raises(vol.Invalid):
        _valid_time_zone(time_zone)


@pytest.mark.parametrize(
    "time_zone",
    ["", "/etc/passwd", "../UTC", "not/a-time-zone"],
)
def test_normalize_user_input_rejects_malformed_time_zones(time_zone: str) -> None:
    """Direct submissions still map unknown zones to invalid_time_zone."""
    flow = SunsetHueConfigFlow()
    errors: dict[str, str] = {}
    assert (
        flow._normalize_user_input(
            {
                "location_name": "Home",
                "api_key": "key",
                "latitude": 40.7128,
                "longitude": -74.006,
                "time_zone": time_zone,
            },
            errors,
        )
        is None
    )
    assert errors == {"base": "invalid_time_zone"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time_zone",
    ["", "/etc/passwd", "../UTC", "not/a-time-zone"],
)
async def test_user_flow_rejects_unknown_time_zone_options(hass, time_zone: str) -> None:
    """SelectSelector rejects zone keys that are not in the dropdown."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "location_name": "Home",
                "latitude": 40.7128,
                "longitude": -74.006,
                "time_zone": time_zone,
                "api_key": "test-key",
                "forecast_start_offset": "0",
            },
        )


@pytest.mark.asyncio
async def test_user_form_schema_is_frontend_serializable(hass) -> None:
    """The initial form schema can be converted for the frontend."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "form"
    serialized = convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert serialized


@pytest.mark.asyncio
async def test_time_zone_dropdown_includes_iana_zones_with_offset_labels(hass) -> None:
    """The dropdown stores IANA keys and shows the current offset in labels."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    options = _time_zone_selector_options(result["data_schema"])
    by_value = {option["value"]: option["label"] for option in options}
    assert "UTC" in by_value
    assert "America/New_York" in by_value
    assert by_value["America/New_York"].startswith("(UTC")
    assert by_value["America/New_York"].endswith("America/New York")
    assert "UTC-04:00" not in by_value
    assert "UTC-05:00" not in by_value


@pytest.mark.asyncio
async def test_user_flow_stores_iana_time_zone(hass, aioclient_mock, event_full) -> None:
    """Successful setup persists America/New_York, never a fixed offset."""
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 40.7128,
            "longitude": -74.006,
            "time_zone": "America/New_York",
            "forecast_start_offset": "0",
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_TIME_ZONE] == "America/New_York"
    assert result["data"][CONF_TIME_ZONE] != "UTC-04:00"


@pytest.mark.parametrize(
    ("when", "expected_offset"),
    [
        (datetime(2026, 7, 15, 12, tzinfo=UTC), "UTC-04:00"),
        (datetime(2026, 1, 15, 12, tzinfo=UTC), "UTC-05:00"),
    ],
)
def test_time_zone_option_labels_reflect_dst(when: datetime, expected_offset: str) -> None:
    """Offset labels follow IANA daylight-saving transitions."""
    _time_zone_names.cache_clear()
    options = {option["value"]: option["label"] for option in _time_zone_options(when)}
    assert options["America/New_York"] == f"({expected_offset} now) America/New York"


def test_format_utc_offset_handles_zero_and_missing() -> None:
    """Zero offsets stay signed while missing offsets collapse to UTC."""
    assert _format_utc_offset(None) == "UTC"
    assert _format_utc_offset(datetime(2026, 1, 1, tzinfo=UTC).utcoffset()) == "UTC+00:00"


@pytest.mark.asyncio
async def test_time_zone_names_are_warmed_via_executor_and_cached(hass, monkeypatch) -> None:
    """available_timezones work runs in the executor and the name set is cached."""
    _time_zone_names.cache_clear()
    real_add_executor_job = hass.async_add_executor_job
    executor_targets: list[object] = []

    async def tracking_add_executor_job(func, *args):
        executor_targets.append(func)
        return await real_add_executor_job(func, *args)

    monkeypatch.setattr(hass, "async_add_executor_job", tracking_add_executor_job)

    await _async_user_schema(hass)
    assert executor_targets == [_time_zone_names]
    after_first = _time_zone_names.cache_info()
    assert after_first.misses == 1
    assert after_first.hits >= 1

    await _async_reconfigure_schema(hass)
    assert executor_targets == [_time_zone_names, _time_zone_names]
    after_second = _time_zone_names.cache_info()
    assert after_second.misses == 1
    assert after_second.hits > after_first.hits


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
async def test_error_forms_remain_frontend_serializable(hass, mock_config_entry, aioclient_mock) -> None:
    """Forms re-shown after validation failures stay frontend-serializable."""
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
    assert result["errors"] == {"base": "invalid_coordinates"}
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)

    aioclient_mock.get(f"{API_BASE_URL}/event", status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "bad-key",
            "latitude": 1,
            "longitude": 2,
            "time_zone": "UTC",
        },
    )
    assert result["errors"] == {"base": "invalid_auth"}
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/event", status=503)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 1,
            "longitude": 2,
            "time_zone": "UTC",
        },
    )
    assert result["errors"] == {"base": "cannot_connect"}
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/event", status=429, headers={"Retry-After": "30"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 1,
            "longitude": 2,
            "time_zone": "UTC",
        },
    )
    assert result["errors"] == {"base": "rate_limited"}
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)

    mock_config_entry.add_to_hass(hass)
    reauth = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id}
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/event", status=401)
    reauth = await hass.config_entries.flow.async_configure(reauth["flow_id"], {"api_key": "bad-key"})
    assert reauth["errors"] == {"base": "invalid_auth"}
    convert(reauth["data_schema"], custom_serializer=cv.custom_serializer)

    reconfigure = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id}
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/event", status=503)
    reconfigure = await hass.config_entries.flow.async_configure(
        reconfigure["flow_id"],
        {"location_name": "Office", "latitude": 41, "longitude": -74, "time_zone": "UTC"},
    )
    assert reconfigure["errors"] == {"base": "cannot_connect"}
    convert(reconfigure["data_schema"], custom_serializer=cv.custom_serializer)

    options = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    options = await hass.config_entries.options.async_configure(
        options["flow_id"],
        {
            "forecast_start_offset": "1",
            "forecast_days": "1",
            "include_sunrise": False,
            "include_sunset": False,
            "update_interval": "6",
            "create_detailed_entities": False,
        },
    )
    assert options["errors"] == {"base": "no_events_selected"}
    convert(options["data_schema"], custom_serializer=cv.custom_serializer)


@pytest.mark.asyncio
async def test_user_flow_recovers_after_invalid_time_zone(hass, aioclient_mock, event_full) -> None:
    """Unknown dropdown values are rejected, then a valid IANA zone creates the entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "location_name": "Home",
                "api_key": "test-key",
                "latitude": 40.7128,
                "longitude": -74.006,
                "time_zone": "Not/AZone",
            },
        )
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
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
    assert result["data"][CONF_TIME_ZONE] == "America/New_York"


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
            "forecast_start_offset": "0",
        },
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Home"
    assert result["data"]["api_key"] == "test-key"
    assert result["data"][CONF_LOCATION_ID]
    assert CONF_API_KEY not in result.get("options", {})
    assert result["options"]["forecast_start_offset"] == 0
    assert result["options"]["forecast_days"] == 1


@pytest.mark.asyncio
async def test_user_flow_uses_home_assistant_location_defaults(hass) -> None:
    """The initial form starts from Home Assistant's configured location."""
    hass.config.location_name = "Configured home"
    hass.config.latitude = 12.34
    hass.config.longitude = 56.78
    hass.config.time_zone = "America/New_York"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    defaults = _suggested_values(result["data_schema"])
    assert {key: defaults[key] for key in ("location_name", "latitude", "longitude", "time_zone")} == {
        "location_name": "Configured home",
        "latitude": 12.34,
        "longitude": 56.78,
        "time_zone": "America/New_York",
    }
    options = _time_zone_selector_options(result["data_schema"])
    assert any(option["value"] == "America/New_York" for option in options)


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
async def test_reconfigure_keeps_form_for_invalid_time_zone(hass, mock_config_entry) -> None:
    """Unknown reconfigure zone keys are rejected by the dropdown schema."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id}
    )
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_TIME_ZONE] == mock_config_entry.data[CONF_TIME_ZONE]
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"location_name": "Office", "latitude": 41, "longitude": -74, "time_zone": "Not/AZone"},
        )
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)


@pytest.mark.asyncio
async def test_reconfigure_preserves_stored_iana_zone(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """Reconfigure keeps the saved IANA zone unless the user picks another."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id}
    )
    assert _suggested_values(result["data_schema"])[CONF_TIME_ZONE] == "America/New_York"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Office",
            "latitude": 41,
            "longitude": -74,
            "time_zone": "America/New_York",
        },
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TIME_ZONE] == "America/New_York"


@pytest.mark.asyncio
async def test_reconfigure_recovers_after_connection_error(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """Reconfigure keeps the form after a connection error, then succeeds."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id}
    )
    aioclient_mock.get(f"{API_BASE_URL}/event", status=503)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location_name": "Office", "latitude": 41, "longitude": -74, "time_zone": "UTC"},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location_name": "Office", "latitude": 41, "longitude": -74, "time_zone": "UTC"},
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.asyncio
async def test_options_flow_enforces_selection_constraints(hass, mock_config_entry) -> None:
    """The option flow rejects invalid ranges and empty event inventories."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "forecast_start_offset": "1",
            "forecast_days": "1",
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
            "forecast_start_offset": "1",
            "forecast_days": "1",
            "include_sunrise": True,
            "include_sunset": False,
            "update_interval": "6",
            "create_detailed_entities": True,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"]["update_interval"] == 6
    assert result["data"]["forecast_start_offset"] == 1
    assert result["data"]["forecast_days"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_input",
    [
        {"forecast_days": "4", "update_interval": "6"},
        {"forecast_days": "1", "update_interval": "5"},
    ],
)
async def test_options_flow_recovers_from_invalid_range(hass, mock_config_entry, user_input) -> None:
    """Selector bounds reject invalid options without persisting them."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    invalid = {
        "forecast_start_offset": "0",
        "forecast_days": "1",
        "include_sunrise": True,
        "include_sunset": False,
        "update_interval": "6",
        "create_detailed_entities": False,
        **user_input,
    }
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(result["flow_id"], invalid)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    valid = {**invalid, "forecast_days": "1", "update_interval": "12"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], valid)
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_config_schemas_apply_expected_types(hass) -> None:
    """Reconfigure omits credentials while options retain only supported fields."""
    reconfigure = await _async_reconfigure_schema(hass)
    assert CONF_API_KEY not in {key.schema for key in reconfigure.schema}
    options = _options_schema()(
        {
            "forecast_start_offset": "1",
            "forecast_days": "1",
            "include_sunrise": True,
            "include_sunset": False,
            "update_interval": "6",
            "create_detailed_entities": True,
        }
    )
    assert options["forecast_days"] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SunsetHueAuthError(), "invalid_auth"),
        (SunsetHueConnectionError(), "cannot_connect"),
        (SunsetHueRateLimitError(1), "rate_limited"),
        (SunsetHueInvalidRequestError(api_message="Invalid latitude"), "invalid_coordinates"),
        (SunsetHueInvalidRequestError(api_message="Bad request"), "invalid_request"),
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

        async def async_get_event(self, *args, **kwargs) -> None:
            raise error

    monkeypatch.setattr(config_flow, "SunsetHueClient", Client)
    data = {"api_key": "secret", "latitude": 1, "longitude": 2, "time_zone": "UTC"}
    assert await _async_validate_connection(hass, data) == expected
