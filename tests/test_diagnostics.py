"""Diagnostics privacy helper tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.sunsethue.const import SunsetHueEventType
from custom_components.sunsethue.diagnostics import (
    _serialize_datetime,
    async_get_config_entry_diagnostics,
)
from custom_components.sunsethue.models import Coordinates, EventForecast, ForecastKey, SunsetHueCoordinatorData


def test_diagnostic_value_normalizes_nested_types() -> None:
    """Options and forecast metadata stay JSON-safe without leaking objects."""
    from custom_components.sunsethue.diagnostics import _diagnostic_value

    assert _diagnostic_value(None) is None
    assert _diagnostic_value("ok") == "ok"
    assert _diagnostic_value([1, {"a": True}]) == [1, {"a": True}]
    assert _diagnostic_value({"x": [2]}) == {"x": [2]}
    assert isinstance(_diagnostic_value(object()), str)


def test_diagnostics_serialize_none() -> None:
    """Diagnostics retain only serializable values."""
    assert _serialize_datetime(None) is None


@pytest.mark.asyncio
async def test_diagnostics_redacts_runtime_data(hass, mock_config_entry) -> None:
    """Useful forecast status survives while credentials and exact ID do not."""
    now = datetime(2026, 8, 1, tzinfo=UTC)
    key = ForecastKey(0, SunsetHueEventType.SUNSET)
    forecast = EventForecast(
        response_time=now,
        location=Coordinates(40.7, -74),
        grid_location=Coordinates(41, -74),
        event_type=SunsetHueEventType.SUNSET,
        model_data=True,
        quality=0.5,
        quality_text="Good",
        cloud_cover=0.2,
        event_time=now,
        direction=180,
        blue_hour=None,
        golden_hour=None,
    )
    coordinator = SimpleNamespace(
        data=SunsetHueCoordinatorData.from_forecasts({key: forecast}),
        last_update_success=True,
        last_update_success_time=now,
        last_exception=None,
    )
    mock_config_entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    data = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert data["redacted"]["api_key"] == "REDACTED"
    assert data["location"] == "REDACTED"
    assert data["forecasts"]["0_sunset"]["grid_location"] == "REDACTED"
    assert "time_zone" not in data
    assert data["coordinator"]["forecast_keys"] == ["0_sunset"]
