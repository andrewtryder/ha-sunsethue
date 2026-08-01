"""Tests for the isolated SunsetHue API client."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.sunsethue.api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueConnectionError,
    SunsetHueInvalidRequestError,
    SunsetHueInvalidResponseError,
    SunsetHueRateLimitError,
    _parse_event_forecast,
    _parse_retry_after,
)
from custom_components.sunsethue.const import API_BASE_URL, SunsetHueEventType
from custom_components.sunsethue.models import Coordinates


def test_parse_full_response_ignores_unknown_fields(event_full: dict[str, Any]) -> None:
    """The parser preserves known values and ignores additions."""
    event_full["unknown"] = "ignored"
    forecast = _parse_event_forecast(event_full)
    assert forecast.event_type is SunsetHueEventType.SUNSET
    assert forecast.quality == 0.45
    assert forecast.blue_hour is not None


def test_parse_without_model_data(event_without_model_data: dict[str, Any]) -> None:
    """No model data is a valid response with absent quality."""
    forecast = _parse_event_forecast(event_without_model_data)
    assert not forecast.model_data
    assert forecast.quality is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("30", 30), ("999999", 86400), ("invalid", None)],
)
def test_parse_retry_after_is_bounded(value: str, expected: int | None) -> None:
    """Retry delays are sanitized before the coordinator receives them."""
    assert _parse_retry_after(value) == expected


@pytest.mark.asyncio
async def test_client_maps_http_errors(hass, aioclient_mock) -> None:
    """HTTP classes become safe, explicit exceptions."""
    client = SunsetHueClient(async_get_clientsession(hass), "super-secret")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=401)
    with pytest.raises(SunsetHueAuthError):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_rate_limit_does_not_include_key(hass, aioclient_mock) -> None:
    """Rate-limit errors preserve a bounded delay but never credentials."""
    client = SunsetHueClient(async_get_clientsession(hass), "super-secret")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=429, headers={"Retry-After": "100000"})
    with pytest.raises(SunsetHueRateLimitError) as caught:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert caught.value.retry_after == 86400
    assert "super-secret" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, SunsetHueInvalidRequestError),
        (422, SunsetHueInvalidRequestError),
        (500, SunsetHueConnectionError),
        (503, SunsetHueConnectionError),
    ],
)
async def test_client_maps_request_and_service_errors(hass, aioclient_mock, status, error) -> None:
    """Invalid requests and service faults have distinct safe exceptions."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=status)
    with pytest.raises(error):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_rejects_invalid_json(hass, aioclient_mock) -> None:
    """A successful status is not enough: bodies must be valid JSON."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, text="not-json")
    with pytest.raises(SunsetHueInvalidResponseError):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_parses_response(hass, aioclient_mock, event_full: dict[str, Any]) -> None:
    """The public client sends the documented request and parses the record."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    forecast = await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert forecast.quality_text == "Good"


def test_invalid_timestamp_is_rejected(event_full: dict[str, Any]) -> None:
    """Malformed timestamps cannot reach entities."""
    event_full["data"]["time"] = "not-a-date"
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_full)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"data": []}),
        lambda payload: payload["data"].update({"quality": "bad"}),
        lambda payload: payload["data"].update({"magics": {"blue_hour": ["one"]}}),
    ],
)
def test_invalid_schema_is_rejected(event_full: dict[str, Any], mutate) -> None:
    """Type validation rejects invalid fields rather than leaking them to HA."""
    mutate(event_full)
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_full)
