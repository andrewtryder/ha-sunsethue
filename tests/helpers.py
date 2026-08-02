"""Typed reusable helpers for SunsetHue tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from custom_components.sunsethue.api import SunsetHueClient
from custom_components.sunsethue.const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
    SunsetHueEventType,
)
from custom_components.sunsethue.coordinator import SunsetHueDataUpdateCoordinator
from custom_components.sunsethue.models import Coordinates, EventForecast
from custom_components.sunsethue.types import SunsetHueConfigEntry

type ConfigEntryData = dict[str, str | float]


def make_coordinator(
    hass: HomeAssistant,
    entry: SunsetHueConfigEntry | Any,
    client: SunsetHueClient | Any,
) -> SunsetHueDataUpdateCoordinator:
    """Build a coordinator with a synchronously resolved test time zone."""
    return SunsetHueDataUpdateCoordinator(
        hass,
        entry,
        client,
        ZoneInfo(str(entry.data[CONF_TIME_ZONE])),
    )


def make_config_entry_data() -> ConfigEntryData:
    """Return valid non-secret configuration data for a test entry."""
    return {
        CONF_API_KEY: "test-api-key",
        CONF_LOCATION_NAME: "Home",
        CONF_LATITUDE: 40.7128,
        CONF_LONGITUDE: -74.006,
        CONF_TIME_ZONE: "America/New_York",
        CONF_LOCATION_ID: "test-location-id",
    }


def make_forecast(event_type: SunsetHueEventType = SunsetHueEventType.SUNSET) -> EventForecast:
    """Return a complete deterministic forecast."""
    now = datetime(2026, 8, 1, tzinfo=UTC)
    return EventForecast(
        response_time=now,
        location=Coordinates(40, -74),
        grid_location=Coordinates(40, -74),
        event_type=event_type,
        model_data=True,
        quality=0.5,
        quality_text="Good",
        cloud_cover=0.2,
        event_time=now,
        direction=180,
        blue_hour=None,
        golden_hour=None,
    )


class FakeSunsetHueClient:
    """Deterministic client replacement for coordinator tests."""

    def __init__(self, result: EventForecast | Exception) -> None:
        self.result = result
        self.calls: list[tuple[date, SunsetHueEventType]] = []

    async def async_get_event(
        self,
        coordinates: Coordinates,
        event_date: date,
        event_type: SunsetHueEventType,
        *,
        forecast: bool = True,
    ) -> EventForecast:
        """Record the request and return the configured outcome."""
        del coordinates, forecast
        self.calls.append((event_date, event_type))
        if isinstance(self.result, Exception):
            raise self.result
        return replace(self.result, event_type=event_type)
