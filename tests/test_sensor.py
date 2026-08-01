"""Tests for entity-level forecast conversion."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.sunsethue.const import SunsetHueEventType
from custom_components.sunsethue.models import (
    Coordinates,
    EventForecast,
    ForecastKey,
    SunsetHueCoordinatorData,
)
from custom_components.sunsethue.sensor import (
    QUALITY_DESCRIPTION,
    SunsetHueDetailedSensor,
    SunsetHueQualitySensor,
    _configured_keys,
)


def test_configured_keys_default_three_days(mock_config_entry) -> None:
    """Default behavior exposes six forecast quality sensors."""
    keys = _configured_keys(mock_config_entry)
    assert keys == [
        ForecastKey(0, SunsetHueEventType.SUNRISE),
        ForecastKey(0, SunsetHueEventType.SUNSET),
        ForecastKey(1, SunsetHueEventType.SUNRISE),
        ForecastKey(1, SunsetHueEventType.SUNSET),
        ForecastKey(2, SunsetHueEventType.SUNRISE),
        ForecastKey(2, SunsetHueEventType.SUNSET),
    ]


def test_quality_sensor_converts_percentage_and_attributes(mock_config_entry) -> None:
    """Quality values and forecast context have HA-friendly presentation."""
    key = ForecastKey(0, SunsetHueEventType.SUNSET)
    now = datetime(2026, 8, 1, tzinfo=UTC)
    forecast = EventForecast(
        response_time=now,
        location=Coordinates(40, -74),
        grid_location=Coordinates(41, -74),
        event_type=SunsetHueEventType.SUNSET,
        model_data=True,
        quality=0.456,
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
        async_add_listener=lambda *args: lambda: None,
        device_info=None,
    )
    sensor = SunsetHueQualitySensor(coordinator, mock_config_entry, key)
    assert sensor.native_value == 45.6
    assert sensor.available
    assert sensor.extra_state_attributes["cloud_cover_percent"] == 20.0


def test_detailed_sensor_is_unavailable_for_missing_field(mock_config_entry) -> None:
    """An absent detail does not affect the rest of the forecast entities."""
    key = ForecastKey(0, SunsetHueEventType.SUNRISE)
    now = datetime(2026, 8, 1, tzinfo=UTC)
    forecast = EventForecast(
        response_time=now,
        location=Coordinates(40, -74),
        grid_location=Coordinates(40, -74),
        event_type=SunsetHueEventType.SUNRISE,
        model_data=False,
        quality=None,
        quality_text=None,
        cloud_cover=None,
        event_time=None,
        direction=None,
        blue_hour=None,
        golden_hour=None,
    )
    coordinator = SimpleNamespace(
        data=SunsetHueCoordinatorData.from_forecasts({key: forecast}),
        last_update_success=True,
        async_add_listener=lambda *args: lambda: None,
        device_info=None,
    )
    sensor = SunsetHueDetailedSensor(
        coordinator, mock_config_entry, key, QUALITY_DESCRIPTION, lambda item: item.quality
    )
    assert sensor.native_value is None
    assert not sensor.available
