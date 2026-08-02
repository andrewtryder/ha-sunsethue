"""Constant helper coverage for forecast windows and day labels."""

from __future__ import annotations

from custom_components.sunsethue.const import (
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    day_translation_key,
    forecast_days_from_options,
    forecast_start_offset_from_options,
    is_valid_forecast_window,
)


def test_forecast_option_helpers_and_window_validation() -> None:
    """Legacy fallbacks and horizon checks stay deterministic."""
    assert forecast_start_offset_from_options({}) == 0
    assert forecast_days_from_options({}) == 3
    assert forecast_start_offset_from_options({CONF_FORECAST_START_OFFSET: "1"}) == 1
    assert forecast_days_from_options({CONF_FORECAST_DAYS: "2"}) == 2
    assert forecast_start_offset_from_options({CONF_FORECAST_START_OFFSET: "bad"}) == 0
    assert forecast_days_from_options({CONF_FORECAST_DAYS: True}) == 3
    assert forecast_start_offset_from_options({CONF_FORECAST_START_OFFSET: True}) == 0
    assert forecast_days_from_options({CONF_FORECAST_DAYS: 9}) == 3
    assert forecast_start_offset_from_options({CONF_FORECAST_START_OFFSET: 1.5}) == 0
    assert forecast_days_from_options({CONF_FORECAST_DAYS: "nope"}) == 3
    assert forecast_start_offset_from_options({CONF_FORECAST_START_OFFSET: 9}) == 0
    assert is_valid_forecast_window(0, 3)
    assert is_valid_forecast_window(1, 2)
    assert is_valid_forecast_window(2, 1)
    assert not is_valid_forecast_window(1, 3)
    assert not is_valid_forecast_window(2, 2)
    assert day_translation_key(0) == "today"
    assert day_translation_key(1) == "tomorrow"
    assert day_translation_key(2) == "day_after_tomorrow"
    assert day_translation_key(9) == "today"
