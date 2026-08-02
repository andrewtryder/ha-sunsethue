"""Config-flow forecast-day defaults, options windows, and quota mapping."""

from __future__ import annotations

from datetime import date

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers import config_validation as cv
from voluptuous_serialize import convert

from custom_components.sunsethue import config_flow
from custom_components.sunsethue.config_flow import (
    _async_validate_connection,
    _forecast_start_offset_selector_value,
    _update_interval_selector_value,
)
from custom_components.sunsethue.const import (
    API_BASE_URL,
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    SunsetHueEventType,
)
from tests.helpers import make_forecast


def _suggested_values(schema) -> dict:
    return {
        key.schema: key.description["suggested_value"]
        for key in schema.schema
        if key.description and "suggested_value" in key.description
    }


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(0, "0"), (1, "1"), (2, "2"), ("1", "1"), (None, "1"), (5, "1"), ("bad", "1"), (True, "1")],
)
def test_forecast_start_offset_selector_value(stored, expected) -> None:
    """Forecast-day selector values are normalized to valid strings."""
    assert _forecast_start_offset_selector_value(stored) == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(6, "6"), (12, "12"), ("24", "24"), (None, "6"), (5, "6"), ("bad", "6"), (True, "6")],
)
def test_update_interval_selector_value(stored, expected) -> None:
    """Update-interval selector values are normalized to valid strings."""
    assert _update_interval_selector_value(stored) == expected


@pytest.mark.asyncio
async def test_user_form_defaults_to_tomorrow(hass) -> None:
    """The initial form suggests tomorrow as the forecast day."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_FORECAST_START_OFFSET] == "1"
    convert(result["data_schema"], custom_serializer=cv.custom_serializer)


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", ["0", "1", "2"])
async def test_user_flow_stores_selected_forecast_day(hass, aioclient_mock, event_full, offset) -> None:
    """Selected forecast days become options while credentials stay in data."""
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 1,
            "longitude": 2,
            "time_zone": "UTC",
            "forecast_start_offset": offset,
        },
    )
    assert result["type"] == "create_entry"
    assert result["options"][CONF_FORECAST_START_OFFSET] == int(offset)
    assert result["options"][CONF_FORECAST_DAYS] == 1
    assert "api_key" not in result["options"]
    assert result["data"]["api_key"] == "test-key"


@pytest.mark.asyncio
async def test_validation_uses_forecast_false_and_selected_date(hass, monkeypatch) -> None:
    """Setup validation avoids model credits and uses the chosen day offset."""
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, *args) -> None:
            pass

        async def async_get_event(self, coordinates, event_date, event_type, *, forecast=True):
            captured["forecast"] = forecast
            captured["event_date"] = event_date
            captured["event_type"] = event_type
            return make_forecast()

    monkeypatch.setattr(config_flow, "SunsetHueClient", Client)
    monkeypatch.setattr(
        config_flow.dt_util,
        "now",
        lambda time_zone: datetime_at(time_zone, 2026, 8, 2),
    )
    data = {"api_key": "secret", "latitude": 1, "longitude": 2, "time_zone": "UTC"}
    assert await _async_validate_connection(hass, data, forecast_start_offset=2) is None
    assert captured["forecast"] is False
    assert captured["event_type"] is SunsetHueEventType.SUNSET
    assert captured["event_date"] == date(2026, 8, 4)


def datetime_at(time_zone, year, month, day):
    from datetime import datetime

    return datetime(year, month, day, 12, tzinfo=time_zone)


@pytest.mark.asyncio
async def test_user_flow_quota_and_invalid_request(hass, aioclient_mock) -> None:
    """Quota and generic invalid requests have distinct form errors."""
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": 400, "code": 204, "message": "Exceeded daily quota"},
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 1,
            "longitude": 2,
            "time_zone": "UTC",
            "forecast_start_offset": "1",
        },
    )
    assert result["errors"] == {"base": "quota_exceeded"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": 400, "code": 101, "message": "Unsupported parameter"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "location_name": "Home",
            "api_key": "test-key",
            "latitude": 1,
            "longitude": 2,
            "time_zone": "UTC",
            "forecast_start_offset": "1",
        },
    )
    assert result["errors"] == {"base": "invalid_request"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "days", "error"),
    [
        ("1", 3, "forecast_window_exceeds_horizon"),
        ("2", 2, "forecast_window_exceeds_horizon"),
    ],
)
async def test_options_rejects_window_beyond_horizon(hass, mock_config_entry, offset, days, error) -> None:
    """Local forecast-window validation never issues an API request."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "forecast_start_offset": offset,
            "forecast_days": days,
            "include_sunrise": True,
            "include_sunset": True,
            "update_interval": "6",
            "create_detailed_entities": False,
        },
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_FORECAST_START_OFFSET] == offset
    assert suggested[CONF_UPDATE_INTERVAL] == "6"


@pytest.mark.asyncio
async def test_options_integer_interval_suggests_string(hass, mock_config_entry) -> None:
    """Stored integer intervals round-trip through the string SelectSelector."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=mock_config_entry.data,
        options={CONF_UPDATE_INTERVAL: 6, CONF_FORECAST_START_OFFSET: 0, CONF_FORECAST_DAYS: 3},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    suggested = _suggested_values(result["data_schema"])
    assert suggested[CONF_UPDATE_INTERVAL] == "6"
    assert isinstance(suggested[CONF_UPDATE_INTERVAL], str)
    result["data_schema"](dict(suggested))
