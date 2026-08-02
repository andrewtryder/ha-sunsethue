"""Tests for entity-level forecast conversion."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunsethue.const import (
    CONF_CREATE_DETAILED_ENTITIES,
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    DOMAIN,
    SunsetHueEventType,
)
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
    _valid_unique_ids,
    async_setup_entry,
)


def _broad_options() -> dict[str, object]:
    """Return a wide inventory used as the starting options state."""
    return {
        CONF_FORECAST_START_OFFSET: 0,
        CONF_FORECAST_DAYS: 3,
        CONF_INCLUDE_SUNRISE: True,
        CONF_INCLUDE_SUNSET: True,
        CONF_CREATE_DETAILED_ENTITIES: True,
    }


def test_configured_keys_default_today_only(mock_config_entry) -> None:
    """Default behavior exposes two forecast quality sensors for today."""
    keys = _configured_keys(mock_config_entry)
    assert keys == [
        ForecastKey(0, SunsetHueEventType.SUNRISE),
        ForecastKey(0, SunsetHueEventType.SUNSET),
    ]


def test_configured_keys_supports_single_event(mock_config_entry) -> None:
    """A disabled event type does not create superfluous entities."""
    entry = MockConfigEntry(
        domain="sunsethue",
        data=mock_config_entry.data,
        options={"forecast_days": 1, "include_sunrise": False, "include_sunset": True},
    )
    assert _configured_keys(entry) == [ForecastKey(0, SunsetHueEventType.SUNSET)]
    sunrise_only = MockConfigEntry(
        domain="sunsethue",
        data=mock_config_entry.data,
        options={"forecast_days": 1, "include_sunrise": True, "include_sunset": False},
    )
    assert _configured_keys(sunrise_only) == [ForecastKey(0, SunsetHueEventType.SUNRISE)]


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
        forecast_date=date(2026, 8, 1),
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
    assert sensor.extra_state_attributes["forecast_date"] == "2026-08-01"
    assert "grid_latitude" not in sensor.extra_state_attributes
    assert "grid_longitude" not in sensor.extra_state_attributes


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


def test_quality_sensor_is_unavailable_without_a_forecast(mock_config_entry) -> None:
    """Only an affected entity becomes unavailable when its record is absent."""
    key = ForecastKey(0, SunsetHueEventType.SUNSET)
    coordinator = SimpleNamespace(
        data=SunsetHueCoordinatorData.from_forecasts({}),
        last_update_success=True,
        async_add_listener=lambda *args: lambda: None,
        device_info=None,
    )
    sensor = SunsetHueQualitySensor(coordinator, mock_config_entry, key)
    assert sensor.extra_state_attributes == {}
    assert not sensor.available


@pytest.mark.asyncio
async def test_entity_setup_includes_opt_in_detail_entities(hass, mock_config_entry) -> None:
    """Detailed entities are created only when the option is explicitly enabled."""
    entry = MockConfigEntry(
        domain="sunsethue",
        title=mock_config_entry.title,
        data=mock_config_entry.data,
        options={"forecast_days": 1, "create_detailed_entities": True},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(coordinator=SimpleNamespace(device_info=None))
    entities = []
    await async_setup_entry(hass, entry, entities.extend)
    assert len(entities) == 18
    assert sum(1 for entity in entities if entity.unique_id.endswith("_quality_text")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("shrunk_options", "expected_suffix_fragment"),
    [
        (
            {
                CONF_FORECAST_START_OFFSET: 0,
                CONF_FORECAST_DAYS: 1,
                CONF_INCLUDE_SUNRISE: True,
                CONF_INCLUDE_SUNSET: True,
                CONF_CREATE_DETAILED_ENTITIES: True,
            },
            "_2_",
        ),
        (
            {
                CONF_FORECAST_START_OFFSET: 0,
                CONF_FORECAST_DAYS: 3,
                CONF_INCLUDE_SUNRISE: False,
                CONF_INCLUDE_SUNSET: True,
                CONF_CREATE_DETAILED_ENTITIES: True,
            },
            "_sunrise_",
        ),
        (
            {
                CONF_FORECAST_START_OFFSET: 0,
                CONF_FORECAST_DAYS: 3,
                CONF_INCLUDE_SUNRISE: True,
                CONF_INCLUDE_SUNSET: True,
                CONF_CREATE_DETAILED_ENTITIES: False,
            },
            "_event_time",
        ),
    ],
)
async def test_shrinking_options_removes_stale_registry_entries(
    hass,
    mock_config_entry,
    shrunk_options,
    expected_suffix_fragment,
) -> None:
    """Sensors disabled by options are removed from the entity registry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=mock_config_entry.title,
        data=mock_config_entry.data,
        options=_broad_options(),
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    broad_ids = _valid_unique_ids(entry, _configured_keys(entry))
    for unique_id in broad_ids:
        registry.async_get_or_create(Platform.SENSOR, DOMAIN, unique_id, config_entry=entry)
    # A non-sensor registry row must never be pruned by sensor setup.
    registry.async_get_or_create("binary_sensor", DOMAIN, f"{entry.entry_id}_keep", config_entry=entry)

    hass.config_entries.async_update_entry(entry, options=shrunk_options)
    entry.runtime_data = SimpleNamespace(coordinator=SimpleNamespace(device_info=None))
    entities: list[object] = []
    await async_setup_entry(hass, entry, entities.extend)

    remaining = {
        item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == Platform.SENSOR
    }
    assert remaining == _valid_unique_ids(entry, _configured_keys(entry))
    assert remaining == {entity.unique_id for entity in entities}
    assert all(expected_suffix_fragment not in unique_id for unique_id in remaining)
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_keep")


@pytest.mark.asyncio
async def test_expanding_options_recreates_previously_removed_entities(hass, mock_config_entry) -> None:
    """Re-enabling a wider window creates the expected unique IDs again."""
    narrow_options = {
        CONF_FORECAST_START_OFFSET: 0,
        CONF_FORECAST_DAYS: 1,
        CONF_INCLUDE_SUNRISE: True,
        CONF_INCLUDE_SUNSET: True,
        CONF_CREATE_DETAILED_ENTITIES: False,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=mock_config_entry.title,
        data=mock_config_entry.data,
        options=narrow_options,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    narrow_ids = _valid_unique_ids(entry, _configured_keys(entry))
    for unique_id in narrow_ids:
        registry.async_get_or_create(Platform.SENSOR, DOMAIN, unique_id, config_entry=entry)

    orphan_id = f"{entry.entry_id}_sunset_2_quality"
    registry.async_get_or_create(Platform.SENSOR, DOMAIN, orphan_id, config_entry=entry)

    entry.runtime_data = SimpleNamespace(coordinator=SimpleNamespace(device_info=None))
    await async_setup_entry(hass, entry, [].extend)
    assert registry.async_get_entity_id(Platform.SENSOR, DOMAIN, orphan_id) is None
    assert {
        item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == Platform.SENSOR
    } == narrow_ids

    hass.config_entries.async_update_entry(entry, options=_broad_options())
    entities: list[object] = []
    await async_setup_entry(hass, entry, entities.extend)

    # Direct async_setup_entry creates entity objects but does not register them.
    # Orphans stay removed until a full platform add re-registers them.
    remaining = {
        item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == Platform.SENSOR
    }
    assert remaining == narrow_ids
    assert orphan_id not in remaining
    assert {entity.unique_id for entity in entities} == _valid_unique_ids(entry, _configured_keys(entry))
    assert any(entity.unique_id.endswith("_sunset_2_quality") for entity in entities)
