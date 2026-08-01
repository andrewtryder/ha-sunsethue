"""Constants for the SunsetHue integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "sunsethue"
NAME = "SunsetHue"
VERSION = "0.1.1"  # x-release-please-version
MIN_HA_VERSION = "2026.3.0"

API_BASE_URL = "https://api.sunsethue.com"
API_EVENT_PATH = "/event"
API_KEY_HEADER = "x-api-key"
API_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 128 * 1024
MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60
MIDNIGHT_REFRESH_DELAY_SECONDS = 5

CONF_API_KEY = "api_key"
CONF_LOCATION_NAME = "location_name"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_TIME_ZONE = "time_zone"
CONF_LOCATION_ID = "location_id"

CONF_FORECAST_DAYS = "forecast_days"
CONF_INCLUDE_SUNRISE = "include_sunrise"
CONF_INCLUDE_SUNSET = "include_sunset"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_CREATE_DETAILED_ENTITIES = "create_detailed_entities"

DEFAULT_FORECAST_DAYS = 3
DEFAULT_INCLUDE_SUNRISE = True
DEFAULT_INCLUDE_SUNSET = True
DEFAULT_UPDATE_INTERVAL_HOURS = 6
DEFAULT_CREATE_DETAILED_ENTITIES = False
VALID_UPDATE_INTERVAL_HOURS = (6, 12, 24)
MAX_FORECAST_DAYS = 3

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
