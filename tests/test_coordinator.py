"""Coordinator request-plan and error mapping tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunsethue.api import (
    SunsetHueAuthError,
    SunsetHueConnectionError,
    SunsetHueError,
    SunsetHueInvalidResponseError,
    SunsetHueRateLimitError,
)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [SunsetHueConnectionError(), SunsetHueInvalidResponseError()])
async def test_transient_failures_become_update_failures(hass, mock_config_entry, error) -> None:
    """A failed grid refresh does not publish a partial result."""
    coordinator = SunsetHueDataUpdateCoordinator(hass, mock_config_entry, _Client(error))  # type: ignore[arg-type]
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_generic_sunsethue_failure_becomes_update_failure(hass, mock_config_entry) -> None:
    """Unexpected client subclasses retain the atomic refresh guarantee."""
    coordinator = SunsetHueDataUpdateCoordinator(hass, mock_config_entry, _Client(SunsetHueError()))  # type: ignore[arg-type]
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


def test_device_info_and_midnight_callback_cleanup(hass, mock_config_entry, monkeypatch) -> None:
    """Each entry exposes one service device and releases its scheduled callback."""
    coordinator = SunsetHueDataUpdateCoordinator(hass, mock_config_entry, _Client(_forecast()))  # type: ignore[arg-type]
    cancelled = False

    def track(*args):
        def cancel() -> None:
            nonlocal cancelled
            cancelled = True

        return cancel

    monkeypatch.setattr("custom_components.sunsethue.coordinator.event_helper.async_track_point_in_time", track)
    coordinator.async_schedule_midnight_refresh()
    coordinator.async_cancel_midnight_refresh()
    assert cancelled
    assert coordinator.device_info["identifiers"] == {("sunsethue", mock_config_entry.entry_id)}


@pytest.mark.asyncio
async def test_midnight_callback_reschedules_and_refreshes(hass, mock_config_entry) -> None:
    """The local-midnight callback always replaces itself after execution."""
    coordinator = SunsetHueDataUpdateCoordinator(hass, mock_config_entry, _Client(_forecast()))  # type: ignore[arg-type]
    coordinator.async_schedule_midnight_refresh = Mock()  # type: ignore[method-assign]
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    await coordinator._async_midnight_refresh(datetime.now(UTC))
    coordinator.async_schedule_midnight_refresh.assert_called_once()
    coordinator.async_request_refresh.assert_awaited_once()
