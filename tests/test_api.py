"""Tests for the isolated SunsetHue API client."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.sunsethue.api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueConnectionError,
    SunsetHueInvalidRequestError,
    SunsetHueInvalidResponseError,
    SunsetHueQuotaExceededError,
    SunsetHueRateLimitError,
    _parse_event_forecast,
    _parse_retry_after,
)
from custom_components.sunsethue.const import API_BASE_URL, VERSION, SunsetHueEventType
from custom_components.sunsethue.models import Coordinates
from tests.conftest import FIXTURES


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


def test_parse_retry_after_accepts_http_date_and_negative_values() -> None:
    """HTTP-date delays and negative numbers are safely normalized."""
    future = (datetime.now(UTC) + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert 0 <= _parse_retry_after(future) <= 30
    assert _parse_retry_after("-1") == 0


def test_parse_retry_after_rejects_malformed_http_date() -> None:
    """Unparseable headers never escape as server-controlled data."""
    assert _parse_retry_after("not a date") is None


def test_parser_rejects_invalid_response_root(event_full: dict[str, Any]) -> None:
    """Only object responses can satisfy the documented API contract."""
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast([])
    event_full["data"]["quality_text"] = 1
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_full)


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
async def test_client_maps_quota_error_from_body(hass, aioclient_mock) -> None:
    """Documented quota JSON becomes a dedicated exception before HTTP mapping."""
    payload = json.loads((FIXTURES / "error_response.json").read_text())
    client = SunsetHueClient(async_get_clientsession(hass), "super-secret")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=400, json=payload)
    with pytest.raises(SunsetHueQuotaExceededError) as caught:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert "super-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_client_maps_quota_message_without_code(hass, aioclient_mock) -> None:
    """Quota wording is recognized even when the numeric code is absent."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": 400, "message": "Exceeded daily quota"},
    )
    with pytest.raises(SunsetHueQuotaExceededError):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_maps_non_quota_invalid_request(hass, aioclient_mock) -> None:
    """Non-quota 400 bodies remain invalid-request errors with safe attributes."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": 400, "code": 100, "message": "Invalid latitude"},
    )
    with pytest.raises(SunsetHueInvalidRequestError) as caught:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert caught.value.code == 100
    assert caught.value.api_message == "Invalid latitude"
    assert str(caught.value) == "SunsetHue rejected the request"


@pytest.mark.asyncio
async def test_client_reads_body_before_status_mapping() -> None:
    """Error JSON is inspected even when Content-Length is unset."""
    payload = json.loads((FIXTURES / "error_response.json").read_text())

    class Content:
        async def read(self, _size: int) -> bytes:
            return json.dumps(payload).encode()

    class Response:
        status = 400
        headers: ClassVar[dict[str, str]] = {}
        content_length = None
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(SunsetHueQuotaExceededError):
        await SunsetHueClient(Session(), "test-key").async_get_event(  # type: ignore[arg-type]
            Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET
        )


@pytest.mark.asyncio
async def test_client_maps_timeout(hass, aioclient_mock) -> None:
    """Transport timeouts become connection errors."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", exc=TimeoutError())
    with pytest.raises(SunsetHueConnectionError, match="Timed out"):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_rejects_oversized_body(hass) -> None:
    """Bodies larger than the hard limit are rejected after a bounded read."""

    class Content:
        async def read(self, size: int) -> bytes:
            return b"x" * size

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {}
        content_length = None
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(SunsetHueInvalidResponseError, match="size limit"):
        await SunsetHueClient(Session(), "test-key").async_get_event(  # type: ignore[arg-type]
            Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET
        )


@pytest.mark.asyncio
async def test_client_ignores_malformed_error_body(hass, aioclient_mock) -> None:
    """Non-object error bodies still map by HTTP status."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=400, json=["not", "an", "object"])
    with pytest.raises(SunsetHueInvalidRequestError) as caught:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert caught.value.code is None
    assert caught.value.api_message is None


@pytest.mark.asyncio
async def test_client_ignores_invalid_error_field_types(hass, aioclient_mock) -> None:
    """Bool and blank fields are not treated as documented error metadata."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": True, "code": True, "message": "   "},
    )
    with pytest.raises(SunsetHueInvalidRequestError) as caught:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert caught.value.code is None
    assert caught.value.api_message is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 418])
async def test_client_maps_remaining_http_errors(hass, aioclient_mock, status) -> None:
    """Forbidden and undocumented status codes stay non-secret failures."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=status)
    expected = SunsetHueAuthError if status == 403 else SunsetHueConnectionError
    with pytest.raises(expected):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_maps_transport_error(hass, aioclient_mock) -> None:
    """aiohttp failures have the same safe public error surface."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/event", exc=aiohttp.ClientConnectionError())
    with pytest.raises(SunsetHueConnectionError):
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)


@pytest.mark.asyncio
async def test_client_rejects_oversized_content_length(hass) -> None:
    """An oversized declared body is rejected before it is read."""

    class Response:
        status = 200
        headers = None
        content_length = 128 * 1024 + 1

        async def __aenter__(self):
            self.headers = {}
            return self

        async def __aexit__(self, *args):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(SunsetHueInvalidResponseError):
        await SunsetHueClient(Session(), "test-key").async_get_event(  # type: ignore[arg-type]
            Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET
        )


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


@pytest.mark.asyncio
async def test_client_sends_documented_request_contract(event_full: dict[str, Any]) -> None:
    """Credentials stay in the header and the complete query is explicit."""

    class Content:
        async def read(self, _size: int) -> bytes:
            return json.dumps(event_full).encode()

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {}
        content_length = None
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def get(self, url: str, **kwargs: Any) -> Response:
            self.calls.append((url, kwargs))
            return Response()

    session = Session()
    await SunsetHueClient(session, "test-key").async_get_event(  # type: ignore[arg-type]
        Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET
    )
    url, request = session.calls[0]
    assert url == f"{API_BASE_URL}/event"
    assert request["params"] == {
        "latitude": 1,
        "longitude": 2,
        "date": "2026-08-01",
        "type": "sunset",
        "forecast": "true",
    }
    assert request["headers"] == {"x-api-key": "test-key", "User-Agent": f"HomeAssistant/SunsetHue/{VERSION}"}


@pytest.mark.asyncio
async def test_client_sends_forecast_false_when_requested(event_full: dict[str, Any]) -> None:
    """Callers can request the lightweight no-model validation path."""

    class Content:
        async def read(self, _size: int) -> bytes:
            return json.dumps(event_full).encode()

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {}
        content_length = None
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Session:
        def __init__(self) -> None:
            self.params: dict[str, Any] | None = None

        def get(self, url: str, **kwargs: Any) -> Response:
            del url
            self.params = kwargs["params"]
            return Response()

    session = Session()
    await SunsetHueClient(session, "test-key").async_get_event(  # type: ignore[arg-type]
        Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET, forecast=False
    )
    assert session.params is not None
    assert session.params["forecast"] == "false"


@pytest.mark.asyncio
async def test_client_rejects_response_for_wrong_event_type(hass, aioclient_mock, event_full: dict[str, Any]) -> None:
    """A valid response cannot be assigned to a different requested event."""
    event_full["data"]["type"] = "sunrise"
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    with pytest.raises(SunsetHueInvalidResponseError, match="event type"):
        await SunsetHueClient(async_get_clientsession(hass), "test-key").async_get_event(
            Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET
        )


def test_invalid_timestamp_is_rejected(event_full: dict[str, Any]) -> None:
    """Malformed timestamps cannot reach entities."""
    event_full["data"]["time"] = "not-a-date"
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_full)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"data": {"type": "twilight", "model_data": True}}),
        lambda payload: payload["data"].update({"model_data": "yes"}),
        lambda payload: payload["data"].update({"time": "2026-08-01T19:30:00"}),
        lambda payload: payload["data"].update({"magics": {"blue_hour": [None, 1]}}),
        lambda payload: payload["location"].update({"latitude": True}),
    ],
)
def test_parser_rejects_invalid_documented_fields(event_full: dict[str, Any], mutate) -> None:
    """Required fields, timestamps, and magic-window values are type-safe."""
    mutate(event_full)
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_full)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["data"].pop("magics"),
        lambda payload: payload["data"].update({"magics": []}),
        lambda payload: payload["data"].update({"time": 1}),
        lambda payload: payload["grid_location"].pop("longitude"),
    ],
)
def test_parser_handles_optional_and_missing_fields(event_full: dict[str, Any], mutate) -> None:
    """Optional magic windows may be absent, while malformed values cannot leak through."""
    mutate(event_full)
    if "magics" not in event_full["data"]:
        assert _parse_event_forecast(event_full).blue_hour is None
    else:
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["data"].update({"quality": -0.01}),
        lambda payload: payload["data"].update({"quality": 1.01}),
        lambda payload: payload["data"].update({"cloud_cover": -0.01}),
        lambda payload: payload["data"].update({"cloud_cover": 1.01}),
        lambda payload: payload["data"].update({"direction": -0.01}),
        lambda payload: payload["data"].update({"direction": 360.01}),
        lambda payload: payload["location"].update({"latitude": -90.01}),
        lambda payload: payload["location"].update({"longitude": 180.01}),
        lambda payload: payload["grid_location"].update({"latitude": 90.01}),
        lambda payload: payload["grid_location"].update({"longitude": -180.01}),
    ],
)
def test_parser_rejects_out_of_range_values(event_full: dict[str, Any], mutate) -> None:
    """Documented numeric ranges prevent nonsensical Home Assistant states."""
    mutate(event_full)
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_full)


def test_parser_normalizes_full_circle_direction(event_full: dict[str, Any]) -> None:
    """360° is accepted and represented as the equivalent 0° direction."""
    event_full["data"]["direction"] = 360
    assert _parse_event_forecast(event_full).direction == 0
