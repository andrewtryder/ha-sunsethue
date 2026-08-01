"""Set up the SunsetHue integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SunsetHueClient
from .const import CONF_API_KEY, CONF_LOCATION_ID, MIN_HA_VERSION, PLATFORMS
from .coordinator import SunsetHueDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SunsetHueRuntimeData:
    """Objects retained for one loaded config entry."""

    client: SunsetHueClient
    coordinator: SunsetHueDataUpdateCoordinator
    cancel_midnight_refresh: Callable[[], None]


type SunsetHueConfigEntry = ConfigEntry[SunsetHueRuntimeData]


def is_supported_home_assistant_version(version: str = HA_VERSION) -> bool:
    """Return whether Home Assistant is new enough for this integration."""
    return AwesomeVersion(version) >= AwesomeVersion(MIN_HA_VERSION)


async def async_setup_entry(hass: HomeAssistant, entry: SunsetHueConfigEntry) -> bool:
    """Set up SunsetHue from a config entry."""
    if not is_supported_home_assistant_version():
        raise ConfigEntryError(f"SunsetHue requires Home Assistant {MIN_HA_VERSION} or newer")
    client = SunsetHueClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = SunsetHueDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_schedule_midnight_refresh()
    entry.runtime_data = SunsetHueRuntimeData(
        client=client,
        coordinator=coordinator,
        cancel_midnight_refresh=coordinator.async_cancel_midnight_refresh,
    )
    entry.async_on_unload(coordinator.async_cancel_midnight_refresh)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SunsetHueConfigEntry) -> bool:
    """Unload a SunsetHue config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: SunsetHueConfigEntry) -> None:
    """Reload after changing options or reconfigured data."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: SunsetHueConfigEntry) -> bool:
    """Migrate known config-entry schemas upward only."""
    _LOGGER.debug("Migrating SunsetHue entry from %s.%s", entry.version, entry.minor_version)
    if entry.version != 1 or entry.minor_version > 1:
        return False
    if entry.minor_version == 0:
        data = dict(entry.data)
        location_id = str(data.get(CONF_LOCATION_ID) or uuid4())
        data[CONF_LOCATION_ID] = location_id
        hass.config_entries.async_update_entry(entry, data=data, unique_id=location_id, minor_version=1)
    return True
