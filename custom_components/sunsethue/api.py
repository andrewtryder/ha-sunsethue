"""Async client for the documented SunsetHue public API."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, NoReturn

import aiohttp

from .const import (
    API_BASE_URL,
    API_EVENT_PATH,
    API_KEY_HEADER,
    API_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    VERSION,
    SunsetHueEventType,
)
from .models import Coordinates, EventForecast, MagicHourWindow

_LOGGER = logging.getLogger(__name__)
_USER_AGENT = f"HomeAssistant/SunsetHue/{VERSION}"


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

    def __init__(self, *, code: int | None = None, api_message: str | None = None) -> None:
        super().__init__("SunsetHue rejected the request")
        self.code = code
        self.api_message = api_message


class SunsetHueQuotaExceededError(SunsetHueError):
    """The API account has exhausted its daily quota."""

    def __init__(self) -> None:
        super().__init__("SunsetHue daily API quota exceeded")


_MAX_ERROR_MESSAGE_LENGTH = 200
_QUOTA_API_CODE = 204


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
                status = response.status
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
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

        if 200 <= status < 300:
            try:
                payload = json.loads(body)
            except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as err:
                raise SunsetHueInvalidResponseError("Invalid JSON response") from err
            return _parse_event_forecast(payload, expected_event_type=event_type)

        error_fields = _parse_api_error_fields(body)
        if _is_quota_exceeded(error_fields):
            raise SunsetHueQuotaExceededError()
        _raise_for_http_status(status, retry_after=retry_after, error_fields=error_fields)


def _parse_api_error_fields(body: bytes) -> dict[str, Any]:
    """Extract documented error fields without trusting unexpected shapes."""
    try:
        payload = json.loads(body)
    except TypeError, UnicodeDecodeError, json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    fields: dict[str, Any] = {}
    status = payload.get("status")
    if isinstance(status, int) and not isinstance(status, bool):
        fields["status"] = status
    code = payload.get("code")
    if isinstance(code, int) and not isinstance(code, bool):
        fields["code"] = code
    message = payload.get("message")
    if isinstance(message, str):
        cleaned = message.strip()[:_MAX_ERROR_MESSAGE_LENGTH]
        if cleaned:
            fields["message"] = cleaned
    return fields


def _is_quota_exceeded(error_fields: dict[str, Any]) -> bool:
    """Return whether the API reported a daily quota exhaustion."""
    code = error_fields.get("code")
    if code == _QUOTA_API_CODE:
        return True
    message = error_fields.get("message")
    if not isinstance(message, str):
        return False
    normalized = message.casefold()
    return "quota" in normalized or "exceeded daily" in normalized


def _raise_for_http_status(
    status: int,
    *,
    retry_after: int | None,
    error_fields: dict[str, Any],
) -> NoReturn:
    """Map non-success HTTP statuses after the body has been inspected."""
    if status in (401, 403):
        raise SunsetHueAuthError("SunsetHue authentication failed")
    if status == 429:
        raise SunsetHueRateLimitError(retry_after)
    if status in (400, 422):
        code = error_fields.get("code")
        message = error_fields.get("message")
        raise SunsetHueInvalidRequestError(
            code=code if isinstance(code, int) else None,
            api_message=message if isinstance(message, str) else None,
        )
    if 500 <= status < 600:
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


def _parse_event_forecast(
    payload: Any,
    *,
    expected_event_type: SunsetHueEventType | None = None,
) -> EventForecast:
    """Validate documented response fields and ignore unknown additions."""
    if not isinstance(payload, dict):
        raise SunsetHueInvalidResponseError("Response root must be an object")
    data = _required_object(payload, "data")
    try:
        event_type = SunsetHueEventType(_required_string(data, "type"))
    except ValueError as err:
        raise SunsetHueInvalidResponseError("Unsupported event type") from err
    model_data = _required_bool(data, "model_data")
    if expected_event_type is not None and event_type is not expected_event_type:
        raise SunsetHueInvalidResponseError("Response event type does not match request")
    return EventForecast(
        response_time=_parse_datetime(_required_string(payload, "time")),
        location=_parse_coordinates(_required_object(payload, "location")),
        grid_location=_parse_coordinates(_required_object(payload, "grid_location")),
        event_type=event_type,
        model_data=model_data,
        quality=_optional_bounded_number(data, "quality", minimum=0, maximum=1),
        quality_text=_optional_string(data, "quality_text"),
        cloud_cover=_optional_bounded_number(data, "cloud_cover", minimum=0, maximum=1),
        event_time=_optional_datetime(data, "time"),
        direction=_parse_direction(data),
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
    return Coordinates(
        _required_bounded_number(value, "latitude", minimum=-90, maximum=90),
        _required_bounded_number(value, "longitude", minimum=-180, maximum=180),
    )


def _required_number(value: dict[str, Any], key: str) -> float:
    item = _optional_number(value, key)
    if item is None:
        raise SunsetHueInvalidResponseError(f"Missing or invalid {key}")
    return item


def _optional_bounded_number(value: dict[str, Any], key: str, *, minimum: float, maximum: float) -> float | None:
    """Return an optional finite number within the documented range."""
    item = _optional_number(value, key)
    if item is None:
        return None
    if not minimum <= item <= maximum:
        raise SunsetHueInvalidResponseError(f"Invalid {key}")
    return item


def _required_bounded_number(value: dict[str, Any], key: str, *, minimum: float, maximum: float) -> float:
    """Return a required finite number within the documented range."""
    item = _optional_bounded_number(value, key, minimum=minimum, maximum=maximum)
    if item is None:
        raise SunsetHueInvalidResponseError(f"Missing or invalid {key}")
    return item


def _parse_direction(data: dict[str, Any]) -> float | None:
    """Return degrees in the canonical half-open [0, 360) range."""
    direction = _optional_bounded_number(data, "direction", minimum=0, maximum=360)
    return 0.0 if direction == 360 else direction


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
