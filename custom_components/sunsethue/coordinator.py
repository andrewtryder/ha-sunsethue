"""Coordinator for SunriseHue forecasts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import event as event_helper
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueError,
    SunsetHueInvalidResponseError,
    SunsetHueQuotaExceededError,
    SunsetHueRateLimitError,
)
from .const import (
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
    DEFAULT_INCLUDE_SUNRISE,
    DEFAULT_INCLUDE_SUNSET,
    DOMAIN,
    MIDNIGHT_REFRESH_DELAY_SECONDS,
    SunsetHueEventType,
    forecast_days_from_options,
    forecast_start_offset_from_options,
    update_interval_from_options,
)
from .models import Coordinates, EventForecast, ForecastKey, SunsetHueCoordinatorData
from .types import SunsetHueConfigEntry

_LOGGER = logging.getLogger(__name__)


class SunsetHueDataUpdateCoordinator(DataUpdateCoordinator[SunsetHueCoordinatorData]):
    """Fetch a complete, consistent forecast grid for a config entry."""

    def __init__(self, hass: HomeAssistant, entry: SunsetHueConfigEntry, client: SunsetHueClient) -> None:
        """Initialize the coordinator for one location."""
        self.client = client
        self._entry = entry
        self._time_zone = ZoneInfo(entry.data[CONF_TIME_ZONE])
        self._cancel_midnight: Callable[[], None] | None = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"SunsetHue {entry.title}",
            update_interval=update_interval_from_options(entry.options),
        )

    def async_schedule_midnight_refresh(self) -> None:
        """Schedule a refresh shortly after the location's next local midnight."""
        self.async_cancel_midnight_refresh()
        now = dt_util.now(self._time_zone)
        next_midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=self._time_zone)
        self._cancel_midnight = event_helper.async_track_point_in_time(
            self.hass,
            self._async_midnight_refresh,
            next_midnight + timedelta(seconds=MIDNIGHT_REFRESH_DELAY_SECONDS),
        )

    def async_cancel_midnight_refresh(self) -> None:
        """Cancel any pending midnight refresh callback."""
        if self._cancel_midnight is not None:
            self._cancel_midnight()
            self._cancel_midnight = None

    async def _async_midnight_refresh(self, _now: datetime) -> None:
        """Refresh after local midnight and schedule the next occurrence."""
        self.async_schedule_midnight_refresh()
        await self.async_request_refresh()

    async def _async_update_data(self) -> SunsetHueCoordinatorData:
        """Fetch every requested forecast or fail atomically."""
        entry = self._entry
        coordinates = Coordinates(float(entry.data[CONF_LATITUDE]), float(entry.data[CONF_LONGITUDE]))
        start_offset = forecast_start_offset_from_options(entry.options)
        days = forecast_days_from_options(entry.options)
        events = self._enabled_events()
        today = dt_util.now(self._time_zone).date()
        semaphore = asyncio.Semaphore(3)

        forecasts: dict[ForecastKey, EventForecast] = {}

        async def fetch(key: ForecastKey) -> None:
            async with semaphore:
                forecast_date = today + timedelta(days=key.day_offset)
                forecast = await self.client.async_get_event(coordinates, forecast_date, key.event_type)
            if forecast.event_type is not key.event_type:
                raise SunsetHueInvalidResponseError("Response event type does not match request")
            forecasts[key] = replace(forecast, forecast_date=forecast_date)

        keys = [
            ForecastKey(day_offset, event_type)
            for day_offset in range(start_offset, start_offset + days)
            for event_type in events
        ]
        try:
            async with asyncio.TaskGroup() as task_group:
                for key in keys:
                    task_group.create_task(fetch(key))
        except BaseExceptionGroup as err:
            error = next(iter(_iter_sunsethue_errors(err)), None)
            if isinstance(error, SunsetHueAuthError):
                raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="reauth_required") from err
            if isinstance(error, SunsetHueRateLimitError):
                raise UpdateFailed("SunsetHue API rate limit reached", retry_after=error.retry_after) from err
            if isinstance(error, SunsetHueQuotaExceededError):
                raise UpdateFailed(
                    "SunsetHue daily API quota exceeded",
                    retry_after=getattr(error, "retry_after", None),
                ) from err
            if isinstance(error, SunsetHueInvalidResponseError):
                raise UpdateFailed("SunsetHue API returned an invalid response") from err
            raise UpdateFailed("Unable to update SunsetHue forecast") from err
        return SunsetHueCoordinatorData.from_forecasts(forecasts)

    def _enabled_events(self) -> tuple[SunsetHueEventType, ...]:
        events: list[SunsetHueEventType] = []
        entry = self._entry
        if entry.options.get(CONF_INCLUDE_SUNRISE, DEFAULT_INCLUDE_SUNRISE):
            events.append(SunsetHueEventType.SUNRISE)
        if entry.options.get(CONF_INCLUDE_SUNSET, DEFAULT_INCLUDE_SUNSET):
            events.append(SunsetHueEventType.SUNSET)
        return tuple(events)

    @property
    def device_info(self) -> dr.DeviceInfo:
        """Expose a single service device for this config entry."""
        return dr.DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="SunsetHue",
            entry_type=dr.DeviceEntryType.SERVICE,
        )


def _iter_sunsethue_errors(error_group: BaseExceptionGroup) -> tuple[SunsetHueError, ...]:
    """Flatten nested exception groups into SunsetHue client errors."""
    errors: list[SunsetHueError] = []
    for error in error_group.exceptions:
        if isinstance(error, BaseExceptionGroup):
            errors.extend(_iter_sunsethue_errors(error))
        elif isinstance(error, SunsetHueError):
            errors.append(error)
    return tuple(errors)
