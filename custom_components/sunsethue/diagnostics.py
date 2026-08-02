"""Diagnostics support with privacy-preserving forecast summaries."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_KEY,
    CONF_LOCATION_ID,
    VERSION,
)
from .types import SunsetHueConfigEntry

type DiagnosticValue = str | int | float | bool | dict[str, DiagnosticValue] | list[DiagnosticValue] | None
type DiagnosticData = dict[str, DiagnosticValue]


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SunsetHueConfigEntry) -> DiagnosticData:
    """Return useful diagnostics without credentials or exact location."""
    coordinator = entry.runtime_data.coordinator
    forecasts: dict[str, DiagnosticValue] = {}
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
                "grid_location": "REDACTED",
            }
    options = {key: _diagnostic_value(value) for key, value in entry.options.items()}
    return {
        "integration_version": VERSION,
        "options": options,
        "location": "REDACTED",
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception_type": (
                None if coordinator.last_exception is None else type(coordinator.last_exception).__name__
            ),
            "forecast_keys": [_diagnostic_value(key) for key in sorted(forecasts)],
        },
        "forecasts": forecasts,
        "redacted": {CONF_API_KEY: "REDACTED", CONF_LOCATION_ID: "REDACTED"},
    }


def _serialize_datetime(value: object) -> str | None:
    """Keep diagnostics JSON serializable."""
    return value.isoformat() if hasattr(value, "isoformat") else None


def _diagnostic_value(value: object) -> DiagnosticValue:
    """Return a serializable value from Home Assistant's dynamic options mapping."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_diagnostic_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _diagnostic_value(item) for key, item in value.items()}
    return str(value)
