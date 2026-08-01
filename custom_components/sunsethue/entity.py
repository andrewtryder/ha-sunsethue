"""Common entity support for SunsetHue."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SunsetHueDataUpdateCoordinator


class SunsetHueEntity(CoordinatorEntity[SunsetHueDataUpdateCoordinator]):
    """Base entity tied to the one coordinator and service device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SunsetHueDataUpdateCoordinator) -> None:
        """Initialize an entity."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
