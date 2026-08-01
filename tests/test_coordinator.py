"""Coordinator request-plan and error mapping tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunsethue.api import SunsetHueAuthError, SunsetHueRateLimitError
from custom_components.sunsethue.const import (
    CONF_FORECAST_DAYS,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    SunsetHueEventType,
)
from custom_components.sunsethue.coordinator import SunsetHueDataUpdateCoordinator
from custom_components.sunsethue.models import Coordinates, EventForecast


class _Client:
    """Deterministic client replacement for coordinator tests."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[date, SunsetHueEventType]] = []

    async def async_get_event(
        self, coordinates: Coordinates, event_date: date, event_type: SunsetHueEventType
    ) -> EventForecast:
        self.calls.append((event_date, event_type))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _forecast(event_type: SunsetHueEventType = SunsetHueEventType.SUNSET) -> EventForecast:
    """Return a complete forecast independent of the selected query type."""
    now = datetime(2026, 8, 1, tzinfo=UTC)
    return EventForecast(
        response_time=now,
        location=Coordinates(40, -74),
        grid_location=Coordinates(40, -74),
        event_type=event_type,
        model_data=True,
        quality=0.5,
        quality_text="Good",
        cloud_cover=0.2,
        event_time=now,
        direction=180,
        blue_hour=None,
        golden_hour=None,
    )


@pytest.mark.asyncio
async def test_default_plan_requests_six_forecasts(hass, mock_config_entry) -> None:
    """Three days by two enabled event types produces six requests."""
    client = _Client(_forecast())
    coordinator = SunsetHueDataUpdateCoordinator(hass, mock_config_entry, client)  # type: ignore[arg-type]
    data = await coordinator._async_update_data()
    assert len(client.calls) == 6
    assert len(data.forecasts) == 6


@pytest.mark.asyncio
async def test_sunrise_only_plan(hass, mock_config_entry) -> None:
    """Disabled event types are never requested."""
    sunrise_entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        data=mock_config_entry.data,
        options={
            CONF_FORECAST_DAYS: 1,
            CONF_INCLUDE_SUNRISE: True,
            CONF_INCLUDE_SUNSET: False,
        },
    )
    client = _Client(_forecast(SunsetHueEventType.SUNRISE))
    coordinator = SunsetHueDataUpdateCoordinator(hass, sunrise_entry, client)  # type: ignore[arg-type]  # MockConfigEntry is runtime-compatible.
    await coordinator._async_update_data()
    assert [event_type for _, event_type in client.calls] == [SunsetHueEventType.SUNRISE]


@pytest.mark.asyncio
async def test_auth_failure_starts_reauth(hass, mock_config_entry) -> None:
    """Authentication errors use the Home Assistant reauth path."""
    coordinator = SunsetHueDataUpdateCoordinator(
        hass,
        mock_config_entry,
        _Client(SunsetHueAuthError()),  # type: ignore[arg-type]
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_rate_limit_becomes_update_failure(hass, mock_config_entry) -> None:
    """Retry information reaches DataUpdateCoordinator."""
    coordinator = SunsetHueDataUpdateCoordinator(
        hass,
        mock_config_entry,
        _Client(SunsetHueRateLimitError(30)),  # type: ignore[arg-type]
    )
    with pytest.raises(UpdateFailed) as caught:
        await coordinator._async_update_data()
    assert caught.value.retry_after == 30
