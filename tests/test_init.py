"""Version-gate tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.exceptions import ConfigEntryError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import sunsethue
from custom_components.sunsethue import async_migrate_entry, is_supported_home_assistant_version
from custom_components.sunsethue.const import (
    API_BASE_URL,
    CONF_FORECAST_DAYS,
    CONF_FORECAST_START_OFFSET,
    CONF_LOCATION_ID,
    DOMAIN,
    LEGACY_FORECAST_DAYS,
    LEGACY_FORECAST_START_OFFSET,
)


def test_minimum_version_gate() -> None:
    """Only Home Assistant 2026.3 and later is supported."""
    assert not is_supported_home_assistant_version("2026.2.99")
    assert is_supported_home_assistant_version("2026.3.0")


@pytest.mark.asyncio
async def test_setup_and_unload(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """First refresh creates typed runtime data and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"include_sunrise": False})
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.coordinator.data is not None
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)


@pytest.mark.asyncio
async def test_setup_rejects_unsupported_home_assistant(hass, mock_config_entry, monkeypatch) -> None:
    """The runtime gate protects unsupported Home Assistant installations."""
    monkeypatch.setattr(sunsethue, "is_supported_home_assistant_version", lambda: False)
    with pytest.raises(ConfigEntryError):
        await sunsethue.async_setup_entry(hass, mock_config_entry)


@pytest.mark.asyncio
async def test_migration_rejects_unknown_major_version(hass, mock_config_entry) -> None:
    """Future incompatible config-entry schemas are not silently accepted."""
    entry = MockConfigEntry(domain="sunsethue", data=mock_config_entry.data, version=2)
    assert not await async_migrate_entry(hass, entry)


@pytest.mark.asyncio
async def test_migration_replaces_coordinate_unique_id_with_location_id(hass, mock_config_entry) -> None:
    """The privacy migration is upward-only and retains stable entry identity."""
    data = {key: value for key, value in mock_config_entry.data.items() if key != CONF_LOCATION_ID}
    entry = MockConfigEntry(domain="sunsethue", data=data, unique_id="40.71280:-74.00600", version=1, minor_version=0)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.minor_version == 2
    assert entry.unique_id == entry.data[CONF_LOCATION_ID]
    assert entry.options[CONF_FORECAST_START_OFFSET] == LEGACY_FORECAST_START_OFFSET
    assert entry.options[CONF_FORECAST_DAYS] == LEGACY_FORECAST_DAYS


@pytest.mark.asyncio
async def test_migration_preserves_explicit_forecast_days(hass, mock_config_entry) -> None:
    """Legacy forecast_days values are retained while the start offset defaults to today."""
    entry = MockConfigEntry(
        domain="sunsethue",
        data=mock_config_entry.data,
        options={CONF_FORECAST_DAYS: 2},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.minor_version == 2
    assert entry.options[CONF_FORECAST_DAYS] == 2
    assert entry.options[CONF_FORECAST_START_OFFSET] == LEGACY_FORECAST_START_OFFSET


@pytest.mark.asyncio
async def test_migration_preserves_current_schema(hass, mock_config_entry) -> None:
    """Already-migrated entries keep their options unchanged."""
    entry = MockConfigEntry(
        domain="sunsethue",
        data=mock_config_entry.data,
        options={CONF_FORECAST_START_OFFSET: 1, CONF_FORECAST_DAYS: 1},
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.options == {CONF_FORECAST_START_OFFSET: 1, CONF_FORECAST_DAYS: 1}


@pytest.mark.asyncio
async def test_migration_rejects_future_minor_version(hass, mock_config_entry) -> None:
    """A future schema is never migrated backward."""
    entry = MockConfigEntry(domain="sunsethue", data=mock_config_entry.data, version=1, minor_version=3)
    assert not await async_migrate_entry(hass, entry)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "user_input", "abort_reason"),
    [
        (
            "options",
            {
                "forecast_start_offset": "0",
                "forecast_days": "1",
                "include_sunrise": True,
                "include_sunset": True,
                "update_interval": "6",
                "create_detailed_entities": False,
            },
            None,
        ),
        (
            "reconfigure",
            {"location_name": "Office", "latitude": 41, "longitude": -74, "time_zone": "UTC"},
            "reconfigure_successful",
        ),
        (
            "reauth",
            {"api_key": "new-key"},
            "reauth_successful",
        ),
    ],
)
async def test_flow_helpers_schedule_exactly_one_reload(
    hass,
    mock_config_entry,
    aioclient_mock,
    event_full,
    monkeypatch,
    action,
    user_input,
    abort_reason,
) -> None:
    """OptionsFlowWithReload and update_reload_and_abort own reload without listeners."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"include_sunrise": False})
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.update_listeners == []

    schedule_reload = MagicMock()
    reload = MagicMock()
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", schedule_reload)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)

    if action == "options":
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
        assert result["type"] == "create_entry"
    elif action == "reconfigure":
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
        assert result["type"] == "abort"
        assert result["reason"] == abort_reason
    else:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
        assert result["type"] == "abort"
        assert result["reason"] == abort_reason

    await hass.async_block_till_done()
    schedule_reload.assert_called_once_with(mock_config_entry.entry_id)
    reload.assert_not_called()


@pytest.mark.asyncio
async def test_reauth_before_setup_schedules_reload(
    hass, mock_config_entry, aioclient_mock, event_full, monkeypatch
) -> None:
    """Setup-failure reauth reloads even when no update listener was registered."""
    mock_config_entry.add_to_hass(hass)
    assert mock_config_entry.update_listeners == []
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)

    schedule_reload = MagicMock()
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", schedule_reload)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "replacement-key"})
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["api_key"] == "replacement-key"
    schedule_reload.assert_called_once_with(mock_config_entry.entry_id)


@pytest.mark.asyncio
async def test_reauth_with_unchanged_api_key_schedules_reload(
    hass, mock_config_entry, aioclient_mock, event_full, monkeypatch
) -> None:
    """Successful same-key reauth still reloads so a previously failed entry can load."""
    mock_config_entry.add_to_hass(hass)
    existing_key = mock_config_entry.data["api_key"]
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)

    schedule_reload = MagicMock()
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", schedule_reload)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": existing_key})
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["api_key"] == existing_key
    schedule_reload.assert_called_once_with(mock_config_entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "zone_result",
    [None, ValueError("malformed"), TypeError("bad type")],
)
async def test_setup_rejects_invalid_time_zone(hass, mock_config_entry, monkeypatch, zone_result) -> None:
    """Entry setup fails closed for unresolved or malformed stored zones."""

    async def _async_zone(_key: str):
        if isinstance(zone_result, Exception):
            raise zone_result
        return zone_result

    client = MagicMock()
    coordinator = MagicMock()
    monkeypatch.setattr(sunsethue.dt_util, "async_get_time_zone", _async_zone)
    monkeypatch.setattr(sunsethue, "SunsetHueClient", client)
    monkeypatch.setattr(sunsethue, "SunsetHueDataUpdateCoordinator", coordinator)

    with pytest.raises(ConfigEntryError, match="time zone"):
        await sunsethue.async_setup_entry(hass, mock_config_entry)

    client.assert_not_called()
    coordinator.assert_not_called()
