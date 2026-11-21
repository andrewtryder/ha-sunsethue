"""Run-aware API and coordinator regression tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.sunsethue.api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueInvalidResponseError,
    SunsetHueQuotaExceededError,
    SunsetHueRateLimitError,
    _parse_event_forecast,
    _parse_optional_model_run,
)
from custom_components.sunsethue.const import API_BASE_URL
from custom_components.sunsethue.coordinator import _reusable_run_id
from custom_components.sunsethue.models import ForecastKey, ModelRunInfo, SunsetHueCoordinatorData
from custom_components.sunsethue.run_info import ModelRunMonitor
from tests.helpers import FakeSunsetHueClient, make_coordinator, make_forecast

OLD_RUN = "2026-11-20-06z"
NEW_RUN = "2026-11-20-12z"


def test_event_run_metadata_is_optional(event_full) -> None:
    """Old event responses remain valid; new run metadata survives parsing."""
    assert _parse_event_forecast(event_full).run_id is None
    event_full["run_id"] = OLD_RUN
    event_full["next_expected_update"] = "2026-11-20T17:00:00Z"
    forecast = _parse_event_forecast(event_full)
    assert forecast.run_id == OLD_RUN
    assert forecast.next_expected_update == datetime(2026, 11, 20, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    ("payload", "expected_id"),
    [
        ({"run_id": OLD_RUN}, OLD_RUN),
        ({"data": {"run_id": OLD_RUN}}, OLD_RUN),
        ({"data": {"current_run": {"id": OLD_RUN}}}, OLD_RUN),
        ({"current_run": OLD_RUN}, OLD_RUN),
        ({"run_info": {"run_id": OLD_RUN}}, OLD_RUN),
        ({"runs": {"current": {"id": OLD_RUN}}}, OLD_RUN),
        ({"data": {"other": "unknown"}}, None),
        ({"run_id": True}, None),
        ({"run_id": "  "}, None),
        ([], None),
    ],
)
def test_run_metadata_shapes(payload, expected_id) -> None:
    """Missing or unfamiliar metadata never accidentally identifies a model run."""
    result = _parse_optional_model_run(payload)
    assert (result.identifier if result else None) == expected_id


def test_next_publication_parses_and_invalid_hints_are_ignored() -> None:
    """Only timezone-aware ISO timestamps affect the next check."""
    payload = {"current_run": {"id": OLD_RUN}, "next_run": {"expected_at": "2026-11-20T23:00:00Z"}}
    assert _parse_optional_model_run(payload).next_expected_update == datetime(2026, 11, 20, 23, tzinfo=UTC)
    payload["next_run"]["expected_at"] = "bad"
    assert _parse_optional_model_run(payload).next_expected_update is None
    payload["next_expected_update"] = "2026-11-20T17:00:00Z"
    assert _parse_optional_model_run(payload).next_expected_update == datetime(2026, 11, 20, 17, tzinfo=UTC)


@pytest.mark.asyncio
async def test_run_info_client_uses_safe_authentication(hass, aioclient_mock) -> None:
    """Credential stays in x-api-key, never URL or response parsing."""
    client = SunsetHueClient(async_get_clientsession(hass), "secret-do-not-print")
    aioclient_mock.get(
        f"{API_BASE_URL}/run-info",
        status=200,
        json={"data": {"current_run": {"id": OLD_RUN}, "next_run": {"expected_at": "2026-11-20T23:00:00Z"}}},
    )
    run = await client.async_get_run_info()
    assert run.identifier == OLD_RUN
    assert run.next_expected_update == datetime(2026, 11, 20, 23, tzinfo=UTC)
    assert "secret-do-not-print" not in client.run_info_cache_key


@pytest.mark.asyncio
async def test_unknown_run_info_returns_invalid_response(hass, aioclient_mock) -> None:
    """Unsupported API schemas trigger safe fallback at the monitor level."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/run-info", status=200, json={"unrecognized": True})
    with pytest.raises(SunsetHueInvalidResponseError):
        await client.async_get_run_info()


@pytest.mark.asyncio
async def test_run_info_rate_limit_is_not_ignored(hass, aioclient_mock) -> None:
    """Rate limits must stop the forecast batch instead of spending more credits."""
    client = SunsetHueClient(async_get_clientsession(hass), "test-key")
    aioclient_mock.get(f"{API_BASE_URL}/run-info", status=429, headers={"Retry-After": "90"})
    with pytest.raises(SunsetHueRateLimitError) as raised:
        await client.async_get_run_info()
    assert raised.value.retry_after == 90


class FakeRunClient:
    """Run-info client with shared credential identity and controllable responses."""

    def __init__(self, response: ModelRunInfo | Exception) -> None:
        self.run_info_cache_key = "shared-credential"
        self.response = response
        self.calls = 0

    async def async_get_run_info(self) -> ModelRunInfo:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_monitor_coalesces_run_checks_by_api_key() -> None:
    """Different locations sharing a key use one cached run result."""
    monitor = ModelRunMonitor()
    first = FakeRunClient(ModelRunInfo(OLD_RUN, None))
    second = FakeRunClient(ModelRunInfo(NEW_RUN, None))
    assert (await monitor.async_current(first)).identifier == OLD_RUN  # type: ignore[arg-type]
    assert (await monitor.async_current(second)).identifier == OLD_RUN  # type: ignore[arg-type]
    assert first.calls == 1
    assert second.calls == 0


@pytest.mark.asyncio
async def test_monitor_falls_back_on_invalid_metadata() -> None:
    """An invalid or unsupported metadata endpoint never breaks existing forecasts."""
    monitor = ModelRunMonitor()
    client = FakeRunClient(SunsetHueInvalidResponseError("unknown run contract"))
    assert await monitor.async_current(client) is None  # type: ignore[arg-type]
    assert await monitor.async_current(client) is None  # type: ignore[arg-type]
    assert client.calls == 1


@pytest.mark.asyncio
async def test_monitor_propagates_quota_auth_and_rate_limits() -> None:
    """Security and quota failures are not swallowed as harmless metadata errors."""
    for error in (SunsetHueQuotaExceededError(), SunsetHueAuthError(), SunsetHueRateLimitError(60)):
        monitor = ModelRunMonitor()
        with pytest.raises(type(error)):
            await monitor.async_current(FakeRunClient(error))  # type: ignore[arg-type]


def test_incomplete_or_mixed_run_cannot_be_reused() -> None:
    """Every selected key, date and run ID must match for reuse."""
    now = datetime.now(UTC).date()
    one = ForecastKey(0, make_forecast().event_type)
    today_forecast = replace(make_forecast(), forecast_date=now, run_id=OLD_RUN)
    data = SunsetHueCoordinatorData.from_forecasts({one: today_forecast})
    assert _reusable_run_id(data, [one], now) == OLD_RUN
    assert _reusable_run_id(None, [one], now) is None
    assert _reusable_run_id(data, [], now) is None
    assert _reusable_run_id(data, [one], now + timedelta(days=1)) is None
    other = replace(today_forecast, run_id=NEW_RUN)
    later = ForecastKey(1, one.event_type)
    mixed = SunsetHueCoordinatorData.from_forecasts(
        {one: today_forecast, later: replace(other, forecast_date=now + timedelta(days=1))}
    )
    assert _reusable_run_id(mixed, [one, later], now) is None
    missing_id = SunsetHueCoordinatorData.from_forecasts({one: replace(today_forecast, run_id=None)})
    assert _reusable_run_id(missing_id, [one], now) is None


@pytest.mark.asyncio
async def test_unchanged_run_skips_event_requests(hass, mock_config_entry) -> None:
    """Scheduled refresh with full date coverage uses cached events."""
    client = FakeSunsetHueClient(replace(make_forecast(), run_id=OLD_RUN))
    coordinator = make_coordinator(hass, mock_config_entry, client)
    check = Mock()
    check.async_current = AsyncMock(return_value=ModelRunInfo(OLD_RUN, None))
    coordinator._run_info_monitor = check
    initial = await coordinator._async_update_data()
    coordinator.async_set_updated_data(initial)
    original_calls = len(client.calls)
    same = await coordinator._async_update_data()
    assert same is initial
    assert len(client.calls) == original_calls
    check.async_current.assert_awaited_once_with(client)


@pytest.mark.asyncio
async def test_new_run_fetches_all_events(hass, mock_config_entry) -> None:
    """A new published model version refreshes every enabled event."""
    client = FakeSunsetHueClient(replace(make_forecast(), run_id=OLD_RUN))
    coordinator = make_coordinator(hass, mock_config_entry, client)
    initial = await coordinator._async_update_data()
    coordinator.async_set_updated_data(initial)
    check = Mock()
    check.async_current = AsyncMock(return_value=ModelRunInfo(NEW_RUN, None))
    coordinator._run_info_monitor = check
    await coordinator._async_update_data()
    assert len(client.calls) == len(initial.forecasts) * 2


@pytest.mark.asyncio
async def test_metadata_unavailable_reverts_to_regular_refresh(hass, mock_config_entry) -> None:
    """An unknown schema leaves the established event refresh path intact."""
    client = FakeSunsetHueClient(replace(make_forecast(), run_id=OLD_RUN))
    coordinator = make_coordinator(hass, mock_config_entry, client)
    initial = await coordinator._async_update_data()
    coordinator.async_set_updated_data(initial)
    check = Mock()
    check.async_current = AsyncMock(return_value=None)
    coordinator._run_info_monitor = check
    await coordinator._async_update_data()
    assert len(client.calls) == len(initial.forecasts) * 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SunsetHueAuthError(), ConfigEntryAuthFailed),
        (SunsetHueRateLimitError(120), UpdateFailed),
        (SunsetHueQuotaExceededError(), UpdateFailed),
    ],
)
async def test_run_info_blocks_forecast_batch_on_credential_quota_errors(
    hass, mock_config_entry, error, expected
) -> None:
    """Run-info auth, quota, or rate-limit errors use existing coordinator paths."""
    client = FakeSunsetHueClient(replace(make_forecast(), run_id=OLD_RUN))
    coordinator = make_coordinator(hass, mock_config_entry, client)
    initial = await coordinator._async_update_data()
    coordinator.async_set_updated_data(initial)
    check = Mock()
    check.async_current = AsyncMock(side_effect=error)
    coordinator._run_info_monitor = check
    with pytest.raises(expected):
        await coordinator._async_update_data()
    assert len(client.calls) == len(initial.forecasts)
