"""Diagnostics support with privacy-preserving forecast summaries."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import SunsetHueConfigEntry
from .const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION_ID,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
    VERSION,
)


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SunsetHueConfigEntry) -> dict[str, Any]:
    """Return useful diagnostics without credentials or exact location."""
    coordinator = entry.runtime_data.coordinator
    forecasts: dict[str, Any] = {}
    if coordinator.data is not None:
        for key, forecast in coordinator.data.forecasts.items():
            forecasts[f"{key.day_offset}_{key.event_type.value}"] = {
                "event_type": forecast.event_type.value,
                "model_data": forecast.model_data,
                "quality": forecast.quality,
                "quality_text": forecast.quality_text,
                "cloud_cover": forecast.cloud_cover,
                "event_time": _serialize_datetime(forecast.event_time),
                "direction": forecast.direction,
                "response_time": _serialize_datetime(forecast.response_time),
                "grid_location": _rounded_location(forecast.grid_location.latitude, forecast.grid_location.longitude),
            }
    return {
        "integration_version": VERSION,
        "options": dict(entry.options),
        "location": _rounded_location(float(entry.data[CONF_LATITUDE]), float(entry.data[CONF_LONGITUDE])),
        "time_zone": entry.data[CONF_TIME_ZONE],
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception_type": (
                None if coordinator.last_exception is None else type(coordinator.last_exception).__name__
            ),
            "forecast_keys": sorted(forecasts),
        },
        "forecasts": forecasts,
        "redacted": {CONF_API_KEY: "REDACTED", CONF_LOCATION_ID: "REDACTED"},
    }


def _rounded_location(latitude: float, longitude: float) -> dict[str, float]:
    """Reduce location precision for diagnostics."""
    return {"latitude": round(latitude, 1), "longitude": round(longitude, 1)}


def _serialize_datetime(value: object) -> str | None:
    """Keep diagnostics JSON serializable."""
    return value.isoformat() if hasattr(value, "isoformat") else None
