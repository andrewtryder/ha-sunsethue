"""Config flow for SunsetHue."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import is_supported_home_assistant_version
from .api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueConnectionError,
    SunsetHueInvalidRequestError,
    SunsetHueInvalidResponseError,
    SunsetHueQuotaExceededError,
    SunsetHueRateLimitError,
)
from .const import (
    CONF_API_KEY,
    CONF_CREATE_DETAILED_ENTITIES,
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    CONF_LATITUDE,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CREATE_DETAILED_ENTITIES,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_FORECAST_START_OFFSET,
    DEFAULT_INCLUDE_SUNRISE,
    DEFAULT_INCLUDE_SUNSET,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MAX_FORECAST_DAYS,
    MIN_HA_VERSION,
    VALID_FORECAST_START_OFFSETS,
    VALID_UPDATE_INTERVAL_HOURS,
    SunsetHueEventType,
    is_valid_forecast_window,
)
from .models import Coordinates

_LOGGER = logging.getLogger(__name__)


def _normalize_coordinate(value: float) -> str:
    """Normalize coordinates for duplicate detection without using a secret."""
    return f"{value:.5f}"


async def _async_resolve_time_zone(key: str) -> ZoneInfo | None:
    """Resolve an IANA zone without blocking the event loop."""
    try:
        return await dt_util.async_get_time_zone(key)
    except TypeError, ValueError:
        return None


def _format_utc_offset(offset: timedelta | None) -> str:
    """Return an offset such as UTC-04:00."""
    if offset is None:
        return "UTC"

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)

    return f"UTC{sign}{hours:02d}:{minutes:02d}"


@lru_cache(maxsize=1)
def _time_zone_names() -> tuple[str, ...]:
    """Return supported IANA zones once per process."""
    return tuple(sorted(available_timezones()))


@lru_cache(maxsize=2)
def _build_time_zone_options(utc_hour: datetime) -> tuple[selector.SelectOptionDict, ...]:
    """Build time-zone options outside the event loop."""
    return tuple(
        selector.SelectOptionDict(
            value=zone_name,
            label=(
                f"({_format_utc_offset(utc_hour.astimezone(ZoneInfo(zone_name)).utcoffset())}) "
                f"{zone_name.replace('_', ' ')}"
            ),
        )
        for zone_name in _time_zone_names()
    )


def _option_for_zone(utc_hour: datetime, zone_name: str) -> selector.SelectOptionDict | None:
    """Return a labeled option for a valid zone, or None when invalid."""
    try:
        offset = utc_hour.astimezone(ZoneInfo(zone_name)).utcoffset()
    except TypeError, ValueError, ZoneInfoNotFoundError:
        return None
    return selector.SelectOptionDict(
        value=zone_name,
        label=f"({_format_utc_offset(offset)}) {zone_name.replace('_', ' ')}",
    )


def _with_included_zone(
    options: Sequence[selector.SelectOptionDict],
    utc_hour: datetime,
    include_zone: str | None,
) -> tuple[selector.SelectOptionDict, ...]:
    """Ensure a valid suggested zone remains selectable even if absent from the cache."""
    if not include_zone or any(option["value"] == include_zone for option in options):
        return tuple(options)
    extra = _option_for_zone(utc_hour, include_zone)
    if extra is None:
        return tuple(options)
    return tuple(sorted((*options, extra), key=lambda option: option["value"]))


async def _async_time_zone_options(
    hass: HomeAssistant,
    *,
    include_zone: str | None = None,
) -> tuple[selector.SelectOptionDict, ...]:
    """Build or retrieve the current time-zone option set off the event loop."""
    utc_hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    options = await hass.async_add_executor_job(_build_time_zone_options, utc_hour)
    if include_zone is None:
        return options
    return await hass.async_add_executor_job(_with_included_zone, options, utc_hour, include_zone)


def _time_zone_selector(options: Sequence[selector.SelectOptionDict]) -> selector.SelectSelector:
    """Return a dropdown selector of IANA time zones."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


async def _async_user_schema(
    hass: HomeAssistant,
    *,
    include_zone: str | None = None,
) -> vol.Schema:
    """Build the initial setup schema with supported time zones."""
    options = await _async_time_zone_options(hass, include_zone=include_zone)
    return vol.Schema(
        {
            vol.Required(CONF_LOCATION_NAME): selector.TextSelector(),
            vol.Required(CONF_API_KEY): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_LATITUDE): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE): vol.Coerce(float),
            vol.Required(CONF_TIME_ZONE): _time_zone_selector(options),
            vol.Required(
                CONF_FORECAST_START_OFFSET, default=str(DEFAULT_FORECAST_START_OFFSET)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(item) for item in VALID_FORECAST_START_OFFSETS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="forecast_start_offset",
                )
            ),
        }
    )


async def _async_reconfigure_schema(
    hass: HomeAssistant,
    *,
    include_zone: str | None = None,
) -> vol.Schema:
    """Return the schema that intentionally excludes the persisted API key."""
    options = await _async_time_zone_options(hass, include_zone=include_zone)
    return vol.Schema(
        {
            vol.Required(CONF_LOCATION_NAME): selector.TextSelector(),
            vol.Required(CONF_LATITUDE): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE): vol.Coerce(float),
            vol.Required(CONF_TIME_ZONE): _time_zone_selector(options),
        }
    )


def _update_interval_selector_value(value: object) -> str:
    """Return a valid string value for the update-interval SelectSelector."""
    if isinstance(value, bool):
        interval = DEFAULT_UPDATE_INTERVAL_HOURS
    elif isinstance(value, int):
        interval = value
    elif isinstance(value, str):
        try:
            interval = int(value)
        except ValueError:
            interval = DEFAULT_UPDATE_INTERVAL_HOURS
    else:
        interval = DEFAULT_UPDATE_INTERVAL_HOURS
    if interval not in VALID_UPDATE_INTERVAL_HOURS:
        interval = DEFAULT_UPDATE_INTERVAL_HOURS
    return str(interval)


def _forecast_start_offset_selector_value(value: object) -> str:
    """Return a valid string value for the forecast-day SelectSelector."""
    if isinstance(value, bool):
        offset = DEFAULT_FORECAST_START_OFFSET
    elif isinstance(value, int):
        offset = value
    elif isinstance(value, str):
        try:
            offset = int(value)
        except ValueError:
            offset = DEFAULT_FORECAST_START_OFFSET
    else:
        offset = DEFAULT_FORECAST_START_OFFSET
    if offset not in VALID_FORECAST_START_OFFSETS:
        offset = DEFAULT_FORECAST_START_OFFSET
    return str(offset)


def _forecast_days_selector_value(value: object) -> str:
    """Return a valid string value for the forecast-days SelectSelector."""
    if isinstance(value, bool):
        days = DEFAULT_FORECAST_DAYS
    elif isinstance(value, int):
        days = value
    elif isinstance(value, str):
        try:
            days = int(value)
        except ValueError:
            days = DEFAULT_FORECAST_DAYS
    else:
        days = DEFAULT_FORECAST_DAYS
    if not 1 <= days <= MAX_FORECAST_DAYS:
        days = DEFAULT_FORECAST_DAYS
    return str(days)


def _default_options(*, start_offset: int = DEFAULT_FORECAST_START_OFFSET) -> dict[str, Any]:
    """Return options stored for a newly created config entry."""
    return {
        CONF_FORECAST_START_OFFSET: start_offset,
        CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
        CONF_INCLUDE_SUNRISE: DEFAULT_INCLUDE_SUNRISE,
        CONF_INCLUDE_SUNSET: DEFAULT_INCLUDE_SUNSET,
        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL_HOURS,
        CONF_CREATE_DETAILED_ENTITIES: DEFAULT_CREATE_DETAILED_ENTITIES,
    }


class SunsetHueConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration and credential maintenance."""

    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(self, user_input: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        """Handle initial UI setup."""
        if not is_supported_home_assistant_version():
            return self.async_abort(
                reason="min_ha_version",
                description_placeholders={"version": MIN_HA_VERSION},
            )
        errors: dict[str, str] = {}
        if user_input is not None:
            normalized = self._normalize_user_input(user_input, errors)
            if normalized is not None:
                start_offset = int(_forecast_start_offset_selector_value(user_input.get(CONF_FORECAST_START_OFFSET)))
                if self._location_is_configured(normalized[CONF_LATITUDE], normalized[CONF_LONGITUDE]):
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(normalized[CONF_LOCATION_ID])
                self._abort_if_unique_id_configured()
                error = await _async_validate_connection(
                    self.hass,
                    normalized,
                    forecast_start_offset=start_offset,
                )
                if error is None:
                    return self.async_create_entry(
                        title=normalized[CONF_LOCATION_NAME],
                        data=normalized,
                        options=_default_options(start_offset=start_offset),
                    )
                errors["base"] = error
        defaults = self._user_defaults(user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                await _async_user_schema(self.hass, include_zone=str(defaults.get(CONF_TIME_ZONE) or "")),
                defaults,
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start an entry-linked API-key replacement flow."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        """Validate and persist replacement credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            candidate = {**self._reauth_entry.data, CONF_API_KEY: api_key}
            start_offset = int(
                _forecast_start_offset_selector_value(
                    self._reauth_entry.options.get(CONF_FORECAST_START_OFFSET, DEFAULT_FORECAST_START_OFFSET)
                )
            )
            error = await _async_validate_connection(
                self.hass,
                candidate,
                forecast_start_offset=start_offset,
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: api_key},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        """Change location metadata without revealing the API key."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {**entry.data, **user_input}
            normalized = self._normalize_user_input(candidate, errors)
            if normalized is not None:
                unique_id = normalized[CONF_LOCATION_ID]
                await self.async_set_unique_id(unique_id)
                if self._location_is_configured(
                    normalized[CONF_LATITUDE], normalized[CONF_LONGITUDE], except_entry_id=entry.entry_id
                ):
                    errors["base"] = "already_configured"
                else:
                    start_offset = int(
                        _forecast_start_offset_selector_value(
                            entry.options.get(CONF_FORECAST_START_OFFSET, DEFAULT_FORECAST_START_OFFSET)
                        )
                    )
                    error = await _async_validate_connection(
                        self.hass,
                        normalized,
                        forecast_start_offset=start_offset,
                    )
                    if error is None:
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates=normalized,
                            title=normalized[CONF_LOCATION_NAME],
                            unique_id=unique_id,
                            reason="reconfigure_successful",
                        )
                    errors["base"] = error
        defaults = {
            CONF_LOCATION_NAME: entry.data[CONF_LOCATION_NAME],
            CONF_LATITUDE: entry.data[CONF_LATITUDE],
            CONF_LONGITUDE: entry.data[CONF_LONGITUDE],
            CONF_TIME_ZONE: entry.data[CONF_TIME_ZONE],
        }
        suggested = user_input or defaults
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                await _async_reconfigure_schema(
                    self.hass,
                    include_zone=str(suggested.get(CONF_TIME_ZONE) or entry.data[CONF_TIME_ZONE]),
                ),
                suggested,
            ),
            errors=errors,
        )

    def _normalize_user_input(self, user_input: Mapping[str, Any], errors: dict[str, str]) -> dict[str, Any] | None:
        """Normalize form data and return only persisted connection values."""
        try:
            latitude = float(user_input[CONF_LATITUDE])
            longitude = float(user_input[CONF_LONGITUDE])
        except KeyError, TypeError, ValueError:
            errors["base"] = "invalid_coordinates"
            return None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            errors["base"] = "invalid_coordinates"
            return None
        try:
            time_zone = str(user_input[CONF_TIME_ZONE]).strip()
        except KeyError:
            errors["base"] = "invalid_time_zone"
            return None
        if not time_zone:
            errors["base"] = "invalid_time_zone"
            return None
        location_name = str(user_input.get(CONF_LOCATION_NAME, "")).strip()
        api_key = str(user_input.get(CONF_API_KEY, "")).strip()
        if not location_name or not api_key:
            errors["base"] = "unknown"
            return None
        return {
            CONF_LOCATION_NAME: location_name,
            CONF_API_KEY: api_key,
            CONF_LATITUDE: float(_normalize_coordinate(latitude)),
            CONF_LONGITUDE: float(_normalize_coordinate(longitude)),
            CONF_TIME_ZONE: time_zone,
            CONF_LOCATION_ID: str(user_input.get(CONF_LOCATION_ID) or uuid4()),
        }

    def _location_is_configured(self, latitude: float, longitude: float, *, except_entry_id: str | None = None) -> bool:
        """Return whether normalized coordinates already belong to another entry."""
        normalized_latitude = _normalize_coordinate(latitude)
        normalized_longitude = _normalize_coordinate(longitude)
        return any(
            configured_entry.entry_id != except_entry_id
            and _normalize_coordinate(float(configured_entry.data[CONF_LATITUDE])) == normalized_latitude
            and _normalize_coordinate(float(configured_entry.data[CONF_LONGITUDE])) == normalized_longitude
            for configured_entry in self._async_current_entries()
        )

    def _user_defaults(self, user_input: Mapping[str, Any] | None) -> dict[str, Any]:
        """Use Home Assistant's configured location as initial form defaults."""
        if user_input is not None:
            defaults = dict(user_input)
            defaults[CONF_FORECAST_START_OFFSET] = _forecast_start_offset_selector_value(
                defaults.get(CONF_FORECAST_START_OFFSET, DEFAULT_FORECAST_START_OFFSET)
            )
            return defaults
        return {
            CONF_LOCATION_NAME: self.hass.config.location_name,
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
            CONF_TIME_ZONE: self.hass.config.time_zone,
            CONF_FORECAST_START_OFFSET: str(DEFAULT_FORECAST_START_OFFSET),
        }

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SunsetHueOptionsFlow:
        """Return the options flow handler."""
        return SunsetHueOptionsFlow()


class SunsetHueOptionsFlow(OptionsFlowWithReload):
    """Options for request scope and entity inventory."""

    async def async_step_init(self, user_input: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        """Handle forecast options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                days = int(user_input[CONF_FORECAST_DAYS])
                start_offset = int(user_input[CONF_FORECAST_START_OFFSET])
                interval = int(user_input[CONF_UPDATE_INTERVAL])
                include_sunrise = user_input[CONF_INCLUDE_SUNRISE]
                include_sunset = user_input[CONF_INCLUDE_SUNSET]
                create_detailed_entities = user_input[CONF_CREATE_DETAILED_ENTITIES]
            except KeyError, TypeError, ValueError:
                errors["base"] = "unknown"
            else:
                if not is_valid_forecast_window(start_offset, days):
                    errors["base"] = "forecast_window_exceeds_horizon"
                elif interval not in VALID_UPDATE_INTERVAL_HOURS:
                    errors["base"] = "invalid_update_interval"
                elif not include_sunrise and not include_sunset:
                    errors["base"] = "no_events_selected"
                elif (
                    not isinstance(include_sunrise, bool)
                    or not isinstance(include_sunset, bool)
                    or not isinstance(create_detailed_entities, bool)
                ):
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        data={
                            CONF_FORECAST_START_OFFSET: start_offset,
                            CONF_FORECAST_DAYS: days,
                            CONF_INCLUDE_SUNRISE: include_sunrise,
                            CONF_INCLUDE_SUNSET: include_sunset,
                            CONF_UPDATE_INTERVAL: interval,
                            CONF_CREATE_DETAILED_ENTITIES: create_detailed_entities,
                        },
                    )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(),
                _options_suggested_values(self.config_entry, user_input),
            ),
            errors=errors,
        )


def _options_suggested_values(
    config_entry: config_entries.ConfigEntry,
    user_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build options-form suggested values with selector-compatible types."""
    suggested = {
        CONF_FORECAST_START_OFFSET: config_entry.options.get(CONF_FORECAST_START_OFFSET, DEFAULT_FORECAST_START_OFFSET),
        CONF_FORECAST_DAYS: config_entry.options.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
        CONF_INCLUDE_SUNRISE: config_entry.options.get(CONF_INCLUDE_SUNRISE, DEFAULT_INCLUDE_SUNRISE),
        CONF_INCLUDE_SUNSET: config_entry.options.get(CONF_INCLUDE_SUNSET, DEFAULT_INCLUDE_SUNSET),
        CONF_UPDATE_INTERVAL: config_entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS),
        CONF_CREATE_DETAILED_ENTITIES: config_entry.options.get(
            CONF_CREATE_DETAILED_ENTITIES, DEFAULT_CREATE_DETAILED_ENTITIES
        ),
    }
    if user_input is not None:
        suggested.update(dict(user_input))
    suggested[CONF_FORECAST_START_OFFSET] = _forecast_start_offset_selector_value(suggested[CONF_FORECAST_START_OFFSET])
    suggested[CONF_FORECAST_DAYS] = _forecast_days_selector_value(suggested[CONF_FORECAST_DAYS])
    suggested[CONF_UPDATE_INTERVAL] = _update_interval_selector_value(suggested[CONF_UPDATE_INTERVAL])
    return suggested


def _options_schema() -> vol.Schema:
    """Return the configurable non-connection preferences."""
    return vol.Schema(
        {
            vol.Required(CONF_FORECAST_START_OFFSET): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(item) for item in VALID_FORECAST_START_OFFSETS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="forecast_start_offset",
                )
            ),
            vol.Required(CONF_FORECAST_DAYS): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(item) for item in range(1, MAX_FORECAST_DAYS + 1)],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="forecast_days",
                )
            ),
            vol.Required(CONF_INCLUDE_SUNRISE): selector.BooleanSelector(),
            vol.Required(CONF_INCLUDE_SUNSET): selector.BooleanSelector(),
            vol.Required(CONF_UPDATE_INTERVAL): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(item) for item in VALID_UPDATE_INTERVAL_HOURS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_CREATE_DETAILED_ENTITIES): selector.BooleanSelector(),
        }
    )


async def _async_validate_connection(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    *,
    forecast_start_offset: int = DEFAULT_FORECAST_START_OFFSET,
) -> str | None:
    """Validate credentials with a lightweight no-model request for the target day."""
    try:
        time_zone = await _async_resolve_time_zone(str(data[CONF_TIME_ZONE]))
        if time_zone is None:
            return "invalid_time_zone"
        client = SunsetHueClient(async_get_clientsession(hass), data[CONF_API_KEY])
        event_date = dt_util.now(time_zone).date() + timedelta(days=forecast_start_offset)
        await client.async_get_event(
            Coordinates(float(data[CONF_LATITUDE]), float(data[CONF_LONGITUDE])),
            event_date,
            SunsetHueEventType.SUNSET,
            forecast=False,
        )
    except SunsetHueAuthError:
        return "invalid_auth"
    except SunsetHueConnectionError:
        return "cannot_connect"
    except SunsetHueRateLimitError:
        return "rate_limited"
    except SunsetHueQuotaExceededError:
        return "quota_exceeded"
    except SunsetHueInvalidRequestError as err:
        return "invalid_coordinates" if err.is_coordinate_error else "invalid_request"
    except SunsetHueInvalidResponseError:
        return "invalid_response"
    except KeyError, TypeError, ValueError:
        return "invalid_time_zone"
    except Exception:  # Intentional UI boundary; never expose unexpected details.
        _LOGGER.exception("Unexpected SunsetHue validation failure")
        return "unknown"
    return None
