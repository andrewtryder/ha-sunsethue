"""API client tests for quota, forecast flags, and verified response bodies."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, ClassVar

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.sunsethue.api import (
    SunsetHueClient,
    SunsetHueConnectionError,
    SunsetHueInvalidRequestError,
    SunsetHueInvalidResponseError,
    SunsetHueQuotaExceededError,
    _parse_event_forecast,
)
from custom_components.sunsethue.const import API_BASE_URL, VERSION, SunsetHueEventType
from custom_components.sunsethue.models import Coordinates
from tests.conftest import FIXTURES


def test_parse_sandown_poor_response(event_sandown_poor: dict[str, Any]) -> None:
    """The verified Sandown response retains quality text, cloud cover, and magics."""
    forecast = _parse_event_forecast(event_sandown_poor)
    assert forecast.quality == 0
    assert forecast.cloud_cover == 1
    assert forecast.quality_text == "Poor"
    assert forecast.event_time == datetime(2026, 8, 3, 0, 6, tzinfo=UTC)
    assert forecast.direction == 295.8
    assert forecast.blue_hour is not None
    assert forecast.blue_hour.start == datetime(2026, 8, 3, 0, 32, tzinfo=UTC)
    assert forecast.blue_hour.end == datetime(2026, 8, 3, 0, 47, tzinfo=UTC)
    assert forecast.golden_hour is not None
    assert forecast.golden_hour.start == datetime(2026, 8, 2, 23, 50, tzinfo=UTC)
    assert forecast.golden_hour.end == datetime(2026, 8, 3, 0, 25, tzinfo=UTC)


def test_unknown_quality_text_is_retained(event_sandown_poor: dict[str, Any]) -> None:
    """Future quality-text strings remain valid sensor states."""
    event_sandown_poor["data"]["quality_text"] = "Spectacular"
    assert _parse_event_forecast(event_sandown_poor).quality_text == "Spectacular"


def test_reversed_magic_window_is_rejected(event_sandown_poor: dict[str, Any]) -> None:
    """Non-null magic windows must keep chronological order."""
    event_sandown_poor["data"]["magics"]["blue_hour"] = [
        "2026-08-03T00:47:00.000Z",
        "2026-08-03T00:32:00.000Z",
    ]
    with pytest.raises(SunsetHueInvalidResponseError):
        _parse_event_forecast(event_sandown_poor)


@pytest.mark.asyncio
async def test_client_maps_quota_error_from_body(hass, aioclient_mock) -> None:
    """Documented quota JSON becomes a dedicated exception before HTTP mapping."""
    payload = json.loads((FIXTURES / "error_response.json").read_text())
    client = SunsetHueClient(async_get_clientsession(hass), "super-secret")
    aioclient_mock.get(f"{API_BASE_URL}/event", status=400, json=payload)
    with pytest.raises(SunsetHueQuotaExceededError) as caught:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert caught.value.code == 204
    assert "super-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_client_maps_coordinate_and_generic_invalid_request(hass, aioclient_mock) -> None:
    """Only coordinate-specific messages are marked as coordinate errors."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": 400, "code": 100, "message": "Invalid latitude"},
    )
    with pytest.raises(SunsetHueInvalidRequestError) as coordinate:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert coordinate.value.is_coordinate_error

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{API_BASE_URL}/event",
        status=400,
        json={"status": 400, "code": 101, "message": "Unsupported parameter"},
    )
    with pytest.raises(SunsetHueInvalidRequestError) as generic:
        await client.async_get_event(Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET)
    assert not generic.value.is_coordinate_error
    assert str(generic.value) == "SunsetHue rejected the request"


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
    assert session.params["type"] == "sunset"


@pytest.mark.asyncio
async def test_client_timeout_and_oversized_body() -> None:
    """Timeouts and oversized bodies stay non-secret connection/response errors."""

    class TimeoutSession:
        def get(self, *args, **kwargs):
            raise TimeoutError()

    with pytest.raises(SunsetHueConnectionError, match="Timed out"):
        await SunsetHueClient(TimeoutSession(), "test-key").async_get_event(  # type: ignore[arg-type]
            Coordinates(1, 2), date(2026, 8, 1), SunsetHueEventType.SUNSET
        )

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


def test_user_agent_includes_version() -> None:
    """The client advertises the integration version without secrets."""
    assert VERSION in f"HomeAssistant/SunsetHue/{VERSION}"
