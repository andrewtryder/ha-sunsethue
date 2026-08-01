"""Typed data models for SunsetHue API responses and coordinator data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

from .const import SunsetHueEventType


@dataclass(frozen=True, slots=True)
class Coordinates:
    """Geographical coordinates returned by the service."""

    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class MagicHourWindow:
    """A start and end timestamp for a magic-hour window."""

    start: datetime | None
    end: datetime | None


@dataclass(frozen=True, slots=True)
class EventForecast:
    """A single sunrise or sunset forecast."""

    response_time: datetime
    location: Coordinates
    grid_location: Coordinates
    event_type: SunsetHueEventType
    model_data: bool
    quality: float | None
    quality_text: str | None
    cloud_cover: float | None
    event_time: datetime | None
    direction: float | None
    blue_hour: MagicHourWindow | None
    golden_hour: MagicHourWindow | None
    forecast_date: date | None = None


@dataclass(frozen=True, slots=True)
class ForecastKey:
    """Stable coordinator key for one forecast day and event type."""

    day_offset: int
    event_type: SunsetHueEventType


@dataclass(frozen=True, slots=True)
class SunsetHueCoordinatorData:
    """Complete, internally consistent coordinator data set."""

    forecasts: Mapping[ForecastKey, EventForecast]

    @classmethod
    def from_forecasts(cls, forecasts: Mapping[ForecastKey, EventForecast]) -> SunsetHueCoordinatorData:
        """Create immutable coordinator data."""
        return cls(MappingProxyType(dict(forecasts)))
