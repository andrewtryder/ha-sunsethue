"""Shared runtime types for SunsetHue."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .api import SunsetHueClient
    from .coordinator import SunsetHueDataUpdateCoordinator


@dataclass(slots=True)
class SunsetHueRuntimeData:
    """Objects retained for one loaded config entry."""

    client: SunsetHueClient
    coordinator: SunsetHueDataUpdateCoordinator
    cancel_midnight_refresh: Callable[[], None]


type SunsetHueConfigEntry = ConfigEntry[SunsetHueRuntimeData]
