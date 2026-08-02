"""Config flow for SunsetHue."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
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
    SunsetHueRateLimitError,
)
from .const import (
    CONF_API_KEY,
    CONF_CREATE_DETAILED_ENTITIES,
    CONF_FORECAST_DAYS,
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
    DEFAULT_INCLUDE_SUNRISE,
    DEFAULT_INCLUDE_SUNSET,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MAX_FORECAST_DAYS,
    MIN_HA_VERSION,
    VALID_UPDATE_INTERVAL_HOURS,
    SunsetHueEventType,
)
from .models import Coordinates

_LOGGER = logging.getLogger(__name__)


def _normalize_coordinate(value: float) -> str:
    """Normalize coordinates for duplicate detection without using a secret."""
    return f"{value:.5f}"


def _valid_time_zone(value: str) -> str:
    """Validate an IANA time zone name."""
    try:
        ZoneInfo(value)
    except (TypeError, ZoneInfoNotFoundError) as err:
        raise vol.Invalid("invalid_time_zone") from err
    return value


USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOCATION_NAME): selector.TextSelector(),
        vol.Required(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_LATITUDE): vol.Coerce(float),
        vol.Required(CONF_LONGITUDE): vol.Coerce(float),
        vol.Required(CONF_TIME_ZONE): vol.All(vol.Coerce(str), _valid_time_zone),
    }
)


class SunsetHueConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration and credential maintenance."""

    VERSION = 1
    MINOR_VERSION = 1

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
                if self._location_is_configured(normalized[CONF_LATITUDE], normalized[CONF_LONGITUDE]):
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(normalized[CONF_LOCATION_ID])
                self._abort_if_unique_id_configured()
                error = await _async_validate_connection(self.hass, normalized)
                if error is None:
                    return self.async_create_entry(title=normalized[CONF_LOCATION_NAME], data=normalized)
                errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, self._user_defaults(user_input)),
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
            error = await _async_validate_connection(self.hass, candidate)
            if error is None:
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=candidate)
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
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
                    error = await _async_validate_connection(self.hass, normalized)
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
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(_reconfigure_schema(), user_input or defaults),
            errors=errors,
        )

    def _normalize_user_input(self, user_input: Mapping[str, Any], errors: dict[str, str]) -> dict[str, Any] | None:
        """Normalize form data and return only persisted connection values."""
        try:
            latitude = float(user_input[CONF_LATITUDE])
            longitude = float(user_input[CONF_LONGITUDE])
        except (KeyError, TypeError, ValueError):
            errors["base"] = "invalid_coordinates"
            return None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            errors["base"] = "invalid_coordinates"
            return None
        try:
            time_zone = _valid_time_zone(str(user_input[CONF_TIME_ZONE]))
        except (KeyError, vol.Invalid):
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
            return dict(user_input)
        return {
            CONF_LOCATION_NAME: self.hass.config.location_name,
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
            CONF_TIME_ZONE: self.hass.config.time_zone,
        }

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SunsetHueOptionsFlow:
        """Return the options flow handler."""
        return SunsetHueOptionsFlow()


class SunsetHueOptionsFlow(config_entries.OptionsFlow):
    """Options for request scope and entity inventory."""

    async def async_step_init(self, user_input: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        """Handle forecast options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            days = int(user_input[CONF_FORECAST_DAYS])
            interval = int(user_input[CONF_UPDATE_INTERVAL])
            if days < 1 or days > MAX_FORECAST_DAYS:
                errors["base"] = "invalid_forecast_days"
            elif interval not in VALID_UPDATE_INTERVAL_HOURS:
                errors["base"] = "invalid_update_interval"
            elif not user_input[CONF_INCLUDE_SUNRISE] and not user_input[CONF_INCLUDE_SUNSET]:
                errors["base"] = "no_events_selected"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **user_input,
                        CONF_FORECAST_DAYS: days,
                        CONF_UPDATE_INTERVAL: interval,
                    },
                )
        defaults = {
            CONF_FORECAST_DAYS: self.config_entry.options.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
            CONF_INCLUDE_SUNRISE: self.config_entry.options.get(CONF_INCLUDE_SUNRISE, DEFAULT_INCLUDE_SUNRISE),
            CONF_INCLUDE_SUNSET: self.config_entry.options.get(CONF_INCLUDE_SUNSET, DEFAULT_INCLUDE_SUNSET),
            CONF_UPDATE_INTERVAL: self.config_entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS),
            CONF_CREATE_DETAILED_ENTITIES: self.config_entry.options.get(
                CONF_CREATE_DETAILED_ENTITIES, DEFAULT_CREATE_DETAILED_ENTITIES
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(_options_schema(), defaults),
            errors=errors,
        )


def _reconfigure_schema() -> vol.Schema:
    """Return the schema that intentionally excludes the persisted API key."""
    return vol.Schema(
        {
            vol.Required(CONF_LOCATION_NAME): selector.TextSelector(),
            vol.Required(CONF_LATITUDE): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE): vol.Coerce(float),
            vol.Required(CONF_TIME_ZONE): selector.TextSelector(),
        }
    )


def _options_schema() -> vol.Schema:
    """Return the configurable non-connection preferences."""
    return vol.Schema(
        {
            vol.Required(CONF_FORECAST_DAYS): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=MAX_FORECAST_DAYS,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
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


async def _async_validate_connection(hass: HomeAssistant, data: Mapping[str, Any]) -> str | None:
    """Validate credentials and connectivity with a documented lightweight request."""
    try:
        time_zone = ZoneInfo(data[CONF_TIME_ZONE])
        client = SunsetHueClient(async_get_clientsession(hass), data[CONF_API_KEY])
        await client.async_get_event(
            Coordinates(float(data[CONF_LATITUDE]), float(data[CONF_LONGITUDE])),
            dt_util.now(time_zone).date(),
            SunsetHueEventType.SUNSET,
        )
    except SunsetHueAuthError:
        return "invalid_auth"
    except SunsetHueConnectionError:
        return "cannot_connect"
    except SunsetHueRateLimitError:
        return "rate_limited"
    except SunsetHueInvalidRequestError:
        return "invalid_coordinates"
    except SunsetHueInvalidResponseError:
        return "invalid_response"
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return "invalid_time_zone"
    except Exception:  # Intentional UI boundary; never expose unexpected details.
        _LOGGER.exception("Unexpected SunsetHue validation failure")
        return "unknown"
    return None
