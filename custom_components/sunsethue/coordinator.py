"""Coordinator for SunriseHue forecasts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import event as event_helper
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueConnectionError,
    SunsetHueError,
    SunsetHueInvalidRequestError,
    SunsetHueInvalidResponseError,
    SunsetHueRateLimitError,
)
from .const import (
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_INCLUDE_SUNRISE,
    DEFAULT_INCLUDE_SUNSET,
    DOMAIN,
    MIDNIGHT_REFRESH_DELAY_SECONDS,
    SunsetHueEventType,
    update_interval_from_options,
)
from .models import Coordinates, EventForecast, ForecastKey, SunsetHueCoordinatorData

_LOGGER = logging.getLogger(__name__)


class SunsetHueDataUpdateCoordinator(DataUpdateCoordinator[SunsetHueCoordinatorData]):
    """Fetch a complete, consistent forecast grid for a config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry[Any], client: SunsetHueClient) -> None:
        self.config_entry = entry
        self.client = client
        self._time_zone = ZoneInfo(entry.data[CONF_TIME_ZONE])
        self._cancel_midnight_refresh: Callable[[], None] | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=update_interval_from_options(entry.options),
            always_update=False,
        )

    def async_schedule_midnight_refresh(self) -> None:
        """Schedule exactly one refresh shortly after this location's midnight."""
        self.async_cancel_midnight_refresh()
        now = dt_util.now(self._time_zone)
        next_midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=self._time_zone) + timedelta(
            seconds=MIDNIGHT_REFRESH_DELAY_SECONDS
        )
        self._cancel_midnight_refresh = event_helper.async_track_point_in_time(
            self.hass, self._async_midnight_refresh, next_midnight
        )

    def async_cancel_midnight_refresh(self) -> None:
        """Cancel the pending midnight callback, if any."""
        if self._cancel_midnight_refresh is not None:
            self._cancel_midnight_refresh()
            self._cancel_midnight_refresh = None

    async def _async_midnight_refresh(self, _: datetime) -> None:
        """Refresh and schedule tomorrow's callback."""
        self.async_schedule_midnight_refresh()
        await self.async_request_refresh()

    async def _async_update_data(self) -> SunsetHueCoordinatorData:
        """Fetch every requested forecast or fail atomically."""
        entry = cast(ConfigEntry[Any], self.config_entry)
        coordinates = Coordinates(float(entry.data[CONF_LATITUDE]), float(entry.data[CONF_LONGITUDE]))
        days = int(entry.options.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS))
        events = self._enabled_events()
        today = dt_util.now(self._time_zone).date()
        semaphore = asyncio.Semaphore(3)

        async def fetch(key: ForecastKey) -> tuple[ForecastKey, EventForecast]:
            async with semaphore:
                forecast = await self.client.async_get_event(
                    coordinates, today + timedelta(days=key.day_offset), key.event_type
                )
            return key, forecast

        keys = [ForecastKey(day_offset, event_type) for day_offset in range(days) for event_type in events]
        try:
            results = await asyncio.gather(*(fetch(key) for key in keys))
        except SunsetHueAuthError as err:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="reauth_required") from err
        except SunsetHueRateLimitError as err:
            raise UpdateFailed("SunsetHue API rate limit reached", retry_after=err.retry_after) from err
        except (SunsetHueConnectionError, SunsetHueInvalidRequestError) as err:
            raise UpdateFailed("Unable to update SunsetHue forecast") from err
        except SunsetHueInvalidResponseError as err:
            raise UpdateFailed("SunsetHue API returned an invalid response") from err
        except SunsetHueError as err:
            raise UpdateFailed("Unable to update SunsetHue forecast") from err
        return SunsetHueCoordinatorData.from_forecasts(dict(results))

    def _enabled_events(self) -> tuple[SunsetHueEventType, ...]:
        events: list[SunsetHueEventType] = []
        entry = cast(ConfigEntry[Any], self.config_entry)
        if entry.options.get(CONF_INCLUDE_SUNRISE, DEFAULT_INCLUDE_SUNRISE):
            events.append(SunsetHueEventType.SUNRISE)
        if entry.options.get(CONF_INCLUDE_SUNSET, DEFAULT_INCLUDE_SUNSET):
            events.append(SunsetHueEventType.SUNSET)
        return tuple(events)

    @property
    def device_info(self) -> dr.DeviceInfo:
        """Return the single service device shared by this entry's entities."""
        entry = cast(ConfigEntry[Any], self.config_entry)
        return dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="SunsetHue",
            model="Sunrise and sunset forecast service",
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url="https://sunsethue.com/dev-api",
        )
