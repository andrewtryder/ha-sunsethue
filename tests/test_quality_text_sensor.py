"""Quality and quality-text sensor coverage for the verified API response."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunsethue.api import _parse_event_forecast
from custom_components.sunsethue.const import (
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    SunsetHueEventType,
)
from custom_components.sunsethue.models import ForecastKey, SunsetHueCoordinatorData
from custom_components.sunsethue.sensor import (
    SunsetHueQualitySensor,
    SunsetHueQualityTextSensor,
    _configured_keys,
)


def _coordinator(forecasts):
    return SimpleNamespace(
        data=SunsetHueCoordinatorData.from_forecasts(forecasts),
        last_update_success=True,
        async_add_listener=lambda *args: lambda: None,
        device_info={"identifiers": {("sunsethue", "entry")}},
    )


def test_sandown_quality_and_quality_text_sensors(mock_config_entry, event_sandown_poor) -> None:
    """The verified response drives both summary sensors and shared attributes."""
    forecast = replace(_parse_event_forecast(event_sandown_poor), forecast_date=date(2026, 8, 2))
    key = ForecastKey(1, SunsetHueEventType.SUNSET)
    coordinator = _coordinator({key: forecast})
    quality = SunsetHueQualitySensor(coordinator, mock_config_entry, key)
    text = SunsetHueQualityTextSensor(coordinator, mock_config_entry, key)
    assert quality.unique_id.endswith("_sunset_1_quality")
    assert text.unique_id.endswith("_sunset_1_quality_text")
    assert quality.native_value == 0
    assert text.native_value == "Poor"
    assert quality.extra_state_attributes["quality_text"] == "Poor"
    assert quality.extra_state_attributes["cloud_cover_percent"] == 100
    assert quality.extra_state_attributes["direction_degrees"] == 295.8
    assert quality.extra_state_attributes["blue_hour_start"] is not None
    assert quality.extra_state_attributes["blue_hour_end"] is not None
    assert quality.extra_state_attributes["golden_hour_start"] is not None
    assert quality.extra_state_attributes["golden_hour_end"] is not None
    assert text.extra_state_attributes["quality_percent"] == 0
    assert text.extra_state_attributes["cloud_cover_percent"] == 100


def test_quality_text_unavailable_when_missing(mock_config_entry, event_sandown_poor) -> None:
    """Missing quality text only disables the quality-text sensor."""
    forecast = replace(_parse_event_forecast(event_sandown_poor), quality_text=None, forecast_date=None)
    key = ForecastKey(1, SunsetHueEventType.SUNSET)
    coordinator = _coordinator({key: forecast})
    assert SunsetHueQualitySensor(coordinator, mock_config_entry, key).available
    assert not SunsetHueQualityTextSensor(coordinator, mock_config_entry, key).available


def test_configured_keys_use_absolute_offsets(mock_config_entry) -> None:
    """Entity inventory follows the configured absolute forecast window."""
    entry = MockConfigEntry(
        domain="sunsethue",
        data=mock_config_entry.data,
        options={
            CONF_FORECAST_START_OFFSET: 1,
            CONF_FORECAST_DAYS: 2,
            CONF_INCLUDE_SUNRISE: False,
            CONF_INCLUDE_SUNSET: True,
        },
    )
    assert _configured_keys(entry) == [
        ForecastKey(1, SunsetHueEventType.SUNSET),
        ForecastKey(2, SunsetHueEventType.SUNSET),
    ]
