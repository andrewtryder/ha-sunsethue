"""Constants for the SunsetHue integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "sunsethue"
NAME = "SunsetHue"
VERSION = "0.4.3"  # x-release-please-version
MIN_HA_VERSION = "2026.3.0"

API_BASE_URL = "https://api.sunsethue.com"
API_EVENT_PATH = "/event"
API_KEY_HEADER = "x-api-key"
API_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 128 * 1024
MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60
MIDNIGHT_REFRESH_DELAY_SECONDS = 5
MAX_API_ERROR_MESSAGE_LENGTH = 200
QUOTA_API_CODE = 204

CONF_API_KEY = "api_key"
CONF_LOCATION_NAME = "location_name"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_TIME_ZONE = "time_zone"
CONF_LOCATION_ID = "location_id"

CONF_FORECAST_START_OFFSET = "forecast_start_offset"
CONF_FORECAST_DAYS = "forecast_days"
CONF_INCLUDE_SUNRISE = "include_sunrise"
CONF_INCLUDE_SUNSET = "include_sunset"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_CREATE_DETAILED_ENTITIES = "create_detailed_entities"

# New installations default to today only (1 date x enabled events).
DEFAULT_FORECAST_START_OFFSET = 0
DEFAULT_FORECAST_DAYS = 1
# Pre-v0.3 installations without explicit options keep the prior three-day window via migration.
LEGACY_FORECAST_START_OFFSET = 0
LEGACY_FORECAST_DAYS = 3
DEFAULT_INCLUDE_SUNRISE = True
DEFAULT_INCLUDE_SUNSET = True
DEFAULT_UPDATE_INTERVAL_HOURS = 6
DEFAULT_CREATE_DETAILED_ENTITIES = False
VALID_UPDATE_INTERVAL_HOURS = (6, 12, 24)
VALID_FORECAST_START_OFFSETS = (0, 1, 2)
MAX_FORECAST_START_OFFSET = 2
MAX_FORECAST_DAYS = 3
MAX_FORECAST_HORIZON_DAYS = 3

DAY_TRANSLATION_KEYS = ("today", "tomorrow", "day_after_tomorrow")

PLATFORMS = [Platform.SENSOR]


class SunsetHueEventType(StrEnum):
    """Events supported by the public SunsetHue endpoint."""

    SUNRISE = "sunrise"
    SUNSET = "sunset"


def update_interval_from_options(options: Mapping[str, object]) -> timedelta:
    """Return the selected coordinator interval."""
    value = options.get(CONF_UPDATE_INTERVAL)
    hours = value if isinstance(value, int) and value in VALID_UPDATE_INTERVAL_HOURS else DEFAULT_UPDATE_INTERVAL_HOURS
    return timedelta(hours=hours)


def forecast_start_offset_from_options(options: Mapping[str, object]) -> int:
    """Return the absolute first day offset for the configured forecast window."""
    value = options.get(CONF_FORECAST_START_OFFSET, DEFAULT_FORECAST_START_OFFSET)
    offset: int
    if isinstance(value, bool):
        return DEFAULT_FORECAST_START_OFFSET
    if isinstance(value, int):
        offset = value
    elif isinstance(value, str):
        try:
            offset = int(value)
        except ValueError:
            return DEFAULT_FORECAST_START_OFFSET
    else:
        return DEFAULT_FORECAST_START_OFFSET
    if offset not in VALID_FORECAST_START_OFFSETS:
        return DEFAULT_FORECAST_START_OFFSET
    return offset


def forecast_days_from_options(options: Mapping[str, object]) -> int:
    """Return the consecutive day count for the configured forecast window."""
    value = options.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS)
    days: int
    if isinstance(value, bool):
        return DEFAULT_FORECAST_DAYS
    if isinstance(value, int):
        days = value
    elif isinstance(value, str):
        try:
            days = int(value)
        except ValueError:
            return DEFAULT_FORECAST_DAYS
    else:
        return DEFAULT_FORECAST_DAYS
    if days < 1 or days > MAX_FORECAST_DAYS:
        return DEFAULT_FORECAST_DAYS
    return days


def is_valid_forecast_window(start_offset: int, days: int) -> bool:
    """Return whether the window stays inside the documented three-day horizon."""
    return (
        start_offset in VALID_FORECAST_START_OFFSETS
        and 1 <= days <= MAX_FORECAST_DAYS
        and start_offset + days <= MAX_FORECAST_HORIZON_DAYS
    )


def day_translation_key(day_offset: int) -> str:
    """Return the translation placeholder for an absolute forecast day offset."""
    if 0 <= day_offset < len(DAY_TRANSLATION_KEYS):
        return DAY_TRANSLATION_KEYS[day_offset]
    return DAY_TRANSLATION_KEYS[0]
