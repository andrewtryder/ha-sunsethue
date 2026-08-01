"""Sensor entities for SunsetHue forecasts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import DEGREE, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SunsetHueConfigEntry
from .const import (
    CONF_CREATE_DETAILED_ENTITIES,
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    DEFAULT_CREATE_DETAILED_ENTITIES,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_INCLUDE_SUNRISE,
    DEFAULT_INCLUDE_SUNSET,
    SunsetHueEventType,
)
from .entity import SunsetHueEntity
from .models import EventForecast, ForecastKey, MagicHourWindow

QUALITY_DESCRIPTION = SensorEntityDescription(
    key="quality", translation_key="quality", native_unit_of_measurement=PERCENTAGE
)

_DETAILED_DESCRIPTIONS: tuple[tuple[SensorEntityDescription, Callable[[EventForecast], Any]], ...] = (
    (
        SensorEntityDescription(
            key="event_time",
            translation_key="event_time",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        lambda forecast: forecast.event_time,
    ),
    (
        SensorEntityDescription(
            key="cloud_cover",
            translation_key="cloud_cover",
            native_unit_of_measurement=PERCENTAGE,
        ),
        lambda forecast: None if forecast.cloud_cover is None else forecast.cloud_cover * 100,
    ),
    (
        SensorEntityDescription(
            key="direction",
            translation_key="direction",
            native_unit_of_measurement=DEGREE,
        ),
        lambda forecast: forecast.direction,
    ),
    (
        SensorEntityDescription(
            key="golden_hour_start",
            translation_key="golden_hour_start",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        lambda forecast: _window_value(forecast.golden_hour, "start"),
    ),
    (
        SensorEntityDescription(
            key="golden_hour_end",
            translation_key="golden_hour_end",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        lambda forecast: _window_value(forecast.golden_hour, "end"),
    ),
    (
        SensorEntityDescription(
            key="blue_hour_start",
            translation_key="blue_hour_start",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        lambda forecast: _window_value(forecast.blue_hour, "start"),
    ),
    (
        SensorEntityDescription(
            key="blue_hour_end",
            translation_key="blue_hour_end",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        lambda forecast: _window_value(forecast.blue_hour, "end"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SunsetHueConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up quality and optional detailed forecast sensors."""
    coordinator = entry.runtime_data.coordinator
    keys = _configured_keys(entry)
    entities: list[SensorEntity] = [SunsetHueQualitySensor(coordinator, entry, key) for key in keys]
    if entry.options.get(CONF_CREATE_DETAILED_ENTITIES, DEFAULT_CREATE_DETAILED_ENTITIES):
        entities.extend(
            SunsetHueDetailedSensor(coordinator, entry, key, description, value_getter)
            for key in keys
            for description, value_getter in _DETAILED_DESCRIPTIONS
        )
    async_add_entities(entities)


def _configured_keys(entry: SunsetHueConfigEntry) -> list[ForecastKey]:
    """Build every key represented by this entry's entity inventory."""
    days = int(entry.options.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS))
    events: list[SunsetHueEventType] = []
    if entry.options.get(CONF_INCLUDE_SUNRISE, DEFAULT_INCLUDE_SUNRISE):
        events.append(SunsetHueEventType.SUNRISE)
    if entry.options.get(CONF_INCLUDE_SUNSET, DEFAULT_INCLUDE_SUNSET):
        events.append(SunsetHueEventType.SUNSET)
    return [ForecastKey(day_offset, event_type) for day_offset in range(days) for event_type in events]


def _window_value(window: MagicHourWindow | None, name: str) -> datetime | None:
    """Get an optional magic-hour boundary."""
    return None if window is None else getattr(window, name)


class _SunsetHueForecastSensor(SunsetHueEntity, SensorEntity):
    """Base sensor for a stable forecast key."""

    def __init__(self, coordinator: Any, entry: SunsetHueConfigEntry, key: ForecastKey) -> None:
        """Initialize a keyed forecast sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_placeholders = {
            "day": ("today", "tomorrow", "day_after_tomorrow")[key.day_offset],
            "event": key.event_type.value,
        }
        self._entry_id = entry.entry_id

    @property
    def _forecast(self) -> EventForecast | None:
        """Return this sensor's current record, if the full update succeeded."""
        return self.coordinator.data.forecasts.get(self._key)


class SunsetHueQualitySensor(_SunsetHueForecastSensor):
    """Forecast quality percentage sensor."""

    entity_description = QUALITY_DESCRIPTION

    def __init__(self, coordinator: Any, entry: SunsetHueConfigEntry, key: ForecastKey) -> None:
        """Initialize the quality sensor."""
        super().__init__(coordinator, entry, key)
        self._attr_unique_id = f"{entry.entry_id}_{key.event_type.value}_{key.day_offset}_quality"

    @property
    def available(self) -> bool:
        """Quality is unavailable when the valid API record has no quality."""
        return super().available and self._forecast is not None and self._forecast.quality is not None

    @property
    def native_value(self) -> float | None:
        """Convert the API's normalized quality to percent."""
        forecast = self._forecast
        return None if forecast is None or forecast.quality is None else round(forecast.quality * 100, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return concise, non-secret forecast context."""
        forecast = self._forecast
        if forecast is None:
            return {}
        attributes: dict[str, Any] = {
            "forecast_date": self._forecast_date,
            "event_type": forecast.event_type.value,
            "model_data": forecast.model_data,
            "grid_latitude": forecast.grid_location.latitude,
            "grid_longitude": forecast.grid_location.longitude,
            "response_time": forecast.response_time,
        }
        optional = {
            "quality_raw": forecast.quality,
            "quality_text": forecast.quality_text,
            "event_time": forecast.event_time,
            "cloud_cover_percent": None if forecast.cloud_cover is None else round(forecast.cloud_cover * 100, 1),
            "direction_degrees": forecast.direction,
            "golden_hour_start": _window_value(forecast.golden_hour, "start"),
            "golden_hour_end": _window_value(forecast.golden_hour, "end"),
            "blue_hour_start": _window_value(forecast.blue_hour, "start"),
            "blue_hour_end": _window_value(forecast.blue_hour, "end"),
        }
        attributes.update({key: value for key, value in optional.items() if value is not None})
        return attributes

    @property
    def _forecast_date(self) -> str | None:
        forecast = self._forecast
        return None if forecast is None or forecast.event_time is None else forecast.event_time.date().isoformat()


class SunsetHueDetailedSensor(_SunsetHueForecastSensor):
    """An opt-in sensor for one detailed forecast field."""

    def __init__(
        self,
        coordinator: Any,
        entry: SunsetHueConfigEntry,
        key: ForecastKey,
        description: SensorEntityDescription,
        value_getter: Callable[[EventForecast], Any],
    ) -> None:
        """Initialize the detailed forecast sensor."""
        super().__init__(coordinator, entry, key)
        self.entity_description = description
        self._value_getter = value_getter
        self._attr_unique_id = f"{entry.entry_id}_{key.event_type.value}_{key.day_offset}_{description.key}"

    @property
    def available(self) -> bool:
        """Only the entity with a missing field is unavailable."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> Any:
        """Return the field supplied by the description's getter."""
        forecast = self._forecast
        return None if forecast is None else self._value_getter(forecast)
