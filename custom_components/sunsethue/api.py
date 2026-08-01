"""Async client for the documented SunsetHue public API."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_EVENT_PATH,
    API_KEY_HEADER,
    API_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    SunsetHueEventType,
)
from .models import Coordinates, EventForecast, MagicHourWindow

_LOGGER = logging.getLogger(__name__)
_USER_AGENT = "HomeAssistant/SunsetHue"


class SunsetHueError(Exception):
    """Base error raised by the SunsetHue client."""


class SunsetHueAuthError(SunsetHueError):
    """Authentication failed."""


class SunsetHueConnectionError(SunsetHueError):
    """A transient service or network error occurred."""


class SunsetHueRateLimitError(SunsetHueError):
    """The API asked the client to slow down."""

    def __init__(self, retry_after: int | None) -> None:
        super().__init__("SunsetHue API rate limit reached")
        self.retry_after = retry_after


class SunsetHueInvalidResponseError(SunsetHueError):
    """The API returned malformed or incompatible data."""


class SunsetHueInvalidRequestError(SunsetHueError):
    """The API rejected a request as invalid."""


class SunsetHueClient:
    """Small, dependency-free client for the documented `/event` endpoint."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        timeout: float = API_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def async_get_event(
        self,
        coordinates: Coordinates,
        event_date: date,
        event_type: SunsetHueEventType,
        *,
        forecast: bool = True,
    ) -> EventForecast:
        """Fetch a single event forecast."""
        params: dict[str, str | float] = {
            "latitude": coordinates.latitude,
            "longitude": coordinates.longitude,
            "date": event_date.isoformat(),
            "type": event_type.value,
            "forecast": str(forecast).lower(),
        }
        headers = {API_KEY_HEADER: self._api_key, "User-Agent": _USER_AGENT}
        try:
            async with self._session.get(
                f"{API_BASE_URL}{API_EVENT_PATH}",
                params=params,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                self._raise_for_status(response)
                content_length = getattr(response, "content_length", None)
                if content_length is not None and content_length > MAX_RESPONSE_BYTES:
                    raise SunsetHueInvalidResponseError("Response exceeds size limit")
                body = await response.content.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise SunsetHueInvalidResponseError("Response exceeds size limit")
        except TimeoutError as err:
            raise SunsetHueConnectionError("Timed out contacting SunsetHue API") from err
        except aiohttp.ClientError as err:
            raise SunsetHueConnectionError("Unable to contact SunsetHue API") from err

        try:
            payload = json.loads(body)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as err:
            raise SunsetHueInvalidResponseError("Invalid JSON response") from err
        return _parse_event_forecast(payload)

    @staticmethod
    def _raise_for_status(response: aiohttp.ClientResponse) -> None:
        """Map HTTP classes without parsing a potentially untrusted body."""
        if 200 <= response.status < 300:
            return
        if response.status in (401, 403):
            raise SunsetHueAuthError("SunsetHue authentication failed")
        if response.status == 429:
            raise SunsetHueRateLimitError(_parse_retry_after(response.headers.get("Retry-After")))
        if response.status in (400, 422):
            raise SunsetHueInvalidRequestError("SunsetHue rejected the request")
        if 500 <= response.status < 600:
            raise SunsetHueConnectionError("SunsetHue service is unavailable")
        raise SunsetHueConnectionError("Unexpected response from SunsetHue API")


def _parse_retry_after(value: str | None) -> int | None:
    """Parse and bound a Retry-After header without trusting server input."""
    if not value:
        return None
    try:
        seconds = int(value)
    except ValueError:
        try:
            seconds = int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except TypeError, ValueError, IndexError, OverflowError:
            return None
    return max(0, min(seconds, MAX_RETRY_AFTER_SECONDS))


def _parse_event_forecast(payload: Any) -> EventForecast:
    """Validate documented response fields and ignore unknown additions."""
    if not isinstance(payload, dict):
        raise SunsetHueInvalidResponseError("Response root must be an object")
    data = _required_object(payload, "data")
    try:
        event_type = SunsetHueEventType(_required_string(data, "type"))
    except ValueError as err:
        raise SunsetHueInvalidResponseError("Unsupported event type") from err
    model_data = _required_bool(data, "model_data")
    return EventForecast(
        response_time=_parse_datetime(_required_string(payload, "time")),
        location=_parse_coordinates(_required_object(payload, "location")),
        grid_location=_parse_coordinates(_required_object(payload, "grid_location")),
        event_type=event_type,
        model_data=model_data,
        quality=_optional_number(data, "quality"),
        quality_text=_optional_string(data, "quality_text"),
        cloud_cover=_optional_number(data, "cloud_cover"),
        event_time=_optional_datetime(data, "time"),
        direction=_optional_number(data, "direction"),
        blue_hour=_optional_magic_window(data, "blue_hour"),
        golden_hour=_optional_magic_window(data, "golden_hour"),
    )


def _required_object(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise SunsetHueInvalidResponseError(f"Missing or invalid {key}")
    return item


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise SunsetHueInvalidResponseError(f"Missing or invalid {key}")
    return item


def _required_bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise SunsetHueInvalidResponseError(f"Missing or invalid {key}")
    return item


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise SunsetHueInvalidResponseError(f"Invalid {key}")
    return item


def _optional_number(value: dict[str, Any], key: str) -> float | None:
    item = value.get(key)
    if item is None:
        return None
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise SunsetHueInvalidResponseError(f"Invalid {key}")
    return float(item)


def _parse_coordinates(value: dict[str, Any]) -> Coordinates:
    return Coordinates(_required_number(value, "latitude"), _required_number(value, "longitude"))


def _required_number(value: dict[str, Any], key: str) -> float:
    item = _optional_number(value, key)
    if item is None:
        raise SunsetHueInvalidResponseError(f"Missing or invalid {key}")
    return item


def _optional_datetime(value: dict[str, Any], key: str) -> datetime | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise SunsetHueInvalidResponseError(f"Invalid {key}")
    return _parse_datetime(item)


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise SunsetHueInvalidResponseError("Invalid timestamp") from err
    if parsed.tzinfo is None:
        raise SunsetHueInvalidResponseError("Timestamp must include a time zone")
    return parsed


def _optional_magic_window(data: dict[str, Any], name: str) -> MagicHourWindow | None:
    magics = data.get("magics")
    if magics is None:
        return None
    if not isinstance(magics, dict):
        raise SunsetHueInvalidResponseError("Invalid magics")
    value = magics.get(name)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise SunsetHueInvalidResponseError(f"Invalid {name}")
    start = None if value[0] is None else _parse_magic_datetime(value[0], name)
    end = None if value[1] is None else _parse_magic_datetime(value[1], name)
    return MagicHourWindow(start, end)


def _parse_magic_datetime(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise SunsetHueInvalidResponseError(f"Invalid {name}")
    return _parse_datetime(value)
