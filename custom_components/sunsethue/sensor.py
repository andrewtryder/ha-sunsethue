"""Sensor entities for SunsetHue forecasts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import DEGREE, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CREATE_DETAILED_ENTITIES,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    DEFAULT_CREATE_DETAILED_ENTITIES,
    DEFAULT_INCLUDE_SUNRISE,
    DEFAULT_INCLUDE_SUNSET,
    SunsetHueEventType,
    day_translation_key,
    forecast_days_from_options,
    forecast_start_offset_from_options,
)
from .coordinator import SunsetHueDataUpdateCoordinator
from .entity import SunsetHueEntity
from .models import EventForecast, ForecastKey, MagicHourWindow
from .types import SunsetHueConfigEntry

type SensorNativeValue = str | int | float | date | datetime | None
type SensorAttributeValue = SensorNativeValue | bool
type ForecastValueGetter = Callable[[EventForecast], SensorNativeValue]

QUALITY_DESCRIPTION = SensorEntityDescription(
    key="quality", translation_key="quality", native_unit_of_measurement=PERCENTAGE
)
QUALITY_TEXT_DESCRIPTION = SensorEntityDescription(
    key="quality_text",
    translation_key="quality_text",
)

PARALLEL_UPDATES = 0

_DETAILED_DESCRIPTIONS: tuple[tuple[SensorEntityDescription, ForecastValueGetter], ...] = (
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
    """Set up quality, quality-text, and optional detailed forecast sensors."""
    del hass
    coordinator = entry.runtime_data.coordinator
    keys = _configured_keys(entry)
    entities: list[SensorEntity] = []
    for key in keys:
        entities.append(SunsetHueQualitySensor(coordinator, entry, key))
        entities.append(SunsetHueQualityTextSensor(coordinator, entry, key))
    if entry.options.get(CONF_CREATE_DETAILED_ENTITIES, DEFAULT_CREATE_DETAILED_ENTITIES):
        entities.extend(
            SunsetHueDetailedSensor(coordinator, entry, key, description, value_getter)
            for key in keys
            for description, value_getter in _DETAILED_DESCRIPTIONS
        )
    async_add_entities(entities)


def _configured_keys(entry: SunsetHueConfigEntry) -> list[ForecastKey]:
    """Build every key represented by this entry's entity inventory."""
    start_offset = forecast_start_offset_from_options(entry.options)
    days = forecast_days_from_options(entry.options)
    events: list[SunsetHueEventType] = []
    if entry.options.get(CONF_INCLUDE_SUNRISE, DEFAULT_INCLUDE_SUNRISE):
        events.append(SunsetHueEventType.SUNRISE)
    if entry.options.get(CONF_INCLUDE_SUNSET, DEFAULT_INCLUDE_SUNSET):
        events.append(SunsetHueEventType.SUNSET)
    return [
        ForecastKey(day_offset, event_type)
        for day_offset in range(start_offset, start_offset + days)
        for event_type in events
    ]


def _window_value(window: MagicHourWindow | None, name: str) -> datetime | None:
    """Get an optional magic-hour boundary."""
    return None if window is None else getattr(window, name)


def forecast_common_attributes(forecast: EventForecast) -> dict[str, SensorAttributeValue]:
    """Return shared non-secret attributes for forecast sensors."""
    attributes: dict[str, SensorAttributeValue] = {
        "forecast_date": None if forecast.forecast_date is None else forecast.forecast_date.isoformat(),
        "event_type": forecast.event_type.value,
        "model_data": forecast.model_data,
        "response_time": forecast.response_time,
    }
    optional: dict[str, SensorAttributeValue] = {
        "quality_percent": None if forecast.quality is None else round(forecast.quality * 100, 1),
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


class _SunsetHueForecastSensor(SunsetHueEntity, SensorEntity):
    """Base sensor for a stable forecast key."""

    def __init__(
        self, coordinator: SunsetHueDataUpdateCoordinator, entry: SunsetHueConfigEntry, key: ForecastKey
    ) -> None:
        """Initialize a keyed forecast sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_placeholders = {
            "day": day_translation_key(key.day_offset),
            "event": key.event_type.value,
        }
        self._entry_id = entry.entry_id
        self._attr_icon = (
            "mdi:weather-sunset-up" if key.event_type is SunsetHueEventType.SUNRISE else "mdi:weather-sunset"
        )

    @property
    def _forecast(self) -> EventForecast | None:
        """Return this sensor's current record, if the full update succeeded."""
        return self.coordinator.data.forecasts.get(self._key)


class SunsetHueQualitySensor(_SunsetHueForecastSensor):
    """Forecast quality percentage sensor."""

    entity_description = QUALITY_DESCRIPTION

    def __init__(
        self, coordinator: SunsetHueDataUpdateCoordinator, entry: SunsetHueConfigEntry, key: ForecastKey
    ) -> None:
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
    def extra_state_attributes(self) -> dict[str, SensorAttributeValue]:
        """Return concise, non-secret forecast context."""
        forecast = self._forecast
        return {} if forecast is None else forecast_common_attributes(forecast)


class SunsetHueQualityTextSensor(_SunsetHueForecastSensor):
    """Forecast quality description sensor."""

    entity_description = QUALITY_TEXT_DESCRIPTION

    def __init__(
        self, coordinator: SunsetHueDataUpdateCoordinator, entry: SunsetHueConfigEntry, key: ForecastKey
    ) -> None:
        """Initialize the quality-text sensor."""
        super().__init__(coordinator, entry, key)
        self._attr_unique_id = f"{entry.entry_id}_{key.event_type.value}_{key.day_offset}_quality_text"

    @property
    def available(self) -> bool:
        """Unavailable only when the forecast lacks quality_text."""
        return super().available and self._forecast is not None and self._forecast.quality_text is not None

    @property
    def native_value(self) -> str | None:
        """Return the API's raw quality description."""
        forecast = self._forecast
        return None if forecast is None else forecast.quality_text

    @property
    def extra_state_attributes(self) -> dict[str, SensorAttributeValue]:
        """Return concise, non-secret forecast context."""
        forecast = self._forecast
        return {} if forecast is None else forecast_common_attributes(forecast)


class SunsetHueDetailedSensor(_SunsetHueForecastSensor):
    """An opt-in sensor for one detailed forecast field."""

    def __init__(
        self,
        coordinator: SunsetHueDataUpdateCoordinator,
        entry: SunsetHueConfigEntry,
        key: ForecastKey,
        description: SensorEntityDescription,
        value_getter: ForecastValueGetter,
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
    def native_value(self) -> SensorNativeValue:
        """Return the field supplied by the description's getter."""
        forecast = self._forecast
        return None if forecast is None else self._value_getter(forecast)
