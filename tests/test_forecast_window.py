"""Forecast-window coordinator planning and quota refresh behavior."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunsethue.api import SunsetHueQuotaExceededError
from custom_components.sunsethue.const import (
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    CONF_INCLUDE_SUNRISE,
    CONF_INCLUDE_SUNSET,
    SunsetHueEventType,
)
from custom_components.sunsethue.models import ForecastKey, SunsetHueCoordinatorData
from tests.helpers import FakeSunsetHueClient, make_coordinator, make_forecast


def _entry(mock_config_entry, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        data=mock_config_entry.data,
        options=options,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "expected_offsets", "expected_events", "count"),
    [
        (
            {CONF_FORECAST_START_OFFSET: 0, CONF_FORECAST_DAYS: 1},
            {0},
            {SunsetHueEventType.SUNRISE, SunsetHueEventType.SUNSET},
            2,
        ),
        (
            {CONF_FORECAST_START_OFFSET: 1, CONF_FORECAST_DAYS: 1},
            {1},
            {SunsetHueEventType.SUNRISE, SunsetHueEventType.SUNSET},
            2,
        ),
        (
            {
                CONF_FORECAST_START_OFFSET: 0,
                CONF_FORECAST_DAYS: 1,
                CONF_INCLUDE_SUNSET: True,
                CONF_INCLUDE_SUNRISE: False,
            },
            {0},
            {SunsetHueEventType.SUNSET},
            1,
        ),
        (
            {CONF_FORECAST_START_OFFSET: 2, CONF_FORECAST_DAYS: 1},
            {2},
            {SunsetHueEventType.SUNRISE, SunsetHueEventType.SUNSET},
            2,
        ),
        (
            {CONF_FORECAST_START_OFFSET: 0, CONF_FORECAST_DAYS: 2},
            {0, 1},
            {SunsetHueEventType.SUNRISE, SunsetHueEventType.SUNSET},
            4,
        ),
        (
            {CONF_FORECAST_START_OFFSET: 1, CONF_FORECAST_DAYS: 2},
            {1, 2},
            {SunsetHueEventType.SUNRISE, SunsetHueEventType.SUNSET},
            4,
        ),
        (
            {CONF_FORECAST_START_OFFSET: 0, CONF_FORECAST_DAYS: 3},
            {0, 1, 2},
            {SunsetHueEventType.SUNRISE, SunsetHueEventType.SUNSET},
            6,
        ),
        (
            {
                CONF_FORECAST_START_OFFSET: 1,
                CONF_FORECAST_DAYS: 1,
                CONF_INCLUDE_SUNRISE: True,
                CONF_INCLUDE_SUNSET: False,
            },
            {1},
            {SunsetHueEventType.SUNRISE},
            1,
        ),
    ],
)
async def test_forecast_window_request_plan(
    hass, mock_config_entry, monkeypatch, options, expected_offsets, expected_events, count
) -> None:
    """Absolute offsets and event filters determine the exact request grid."""
    entry = _entry(mock_config_entry, **options)
    monkeypatch.setattr(
        "custom_components.sunsethue.coordinator.dt_util.now",
        lambda _time_zone: datetime(2026, 8, 2, 12, tzinfo=_time_zone),
    )
    client = FakeSunsetHueClient(make_forecast())
    data = await make_coordinator(hass, entry, client)._async_update_data()
    assert len(client.calls) == count
    assert {key.day_offset for key in data.forecasts} == expected_offsets
    assert {key.event_type for key in data.forecasts} == expected_events
    assert {item[0] for item in client.calls} == {date(2026, 8, 2 + offset) for offset in expected_offsets}


@pytest.mark.asyncio
async def test_quota_exceeded_preserves_prior_data_without_reauth(hass, mock_config_entry) -> None:
    """Quota exhaustion fails refresh without reauthentication or wiping prior data."""
    entry = _entry(
        mock_config_entry,
        **{CONF_FORECAST_START_OFFSET: 1, CONF_FORECAST_DAYS: 1, CONF_INCLUDE_SUNRISE: False},
    )
    prior = SunsetHueCoordinatorData.from_forecasts({ForecastKey(1, SunsetHueEventType.SUNSET): make_forecast()})
    coordinator = make_coordinator(
        hass,
        entry,
        FakeSunsetHueClient(SunsetHueQuotaExceededError()),
    )
    coordinator.data = prior
    with pytest.raises(UpdateFailed, match="quota") as caught:
        await coordinator._async_update_data()
    assert not isinstance(caught.value, ConfigEntryAuthFailed)
    assert coordinator.data is prior
