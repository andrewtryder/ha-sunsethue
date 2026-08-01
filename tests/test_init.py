"""Version-gate tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import sunsethue
from custom_components.sunsethue import _async_update_listener, async_migrate_entry, is_supported_home_assistant_version
from custom_components.sunsethue.const import API_BASE_URL, CONF_LOCATION_ID


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
    assert entry.minor_version == 1
    assert entry.unique_id == entry.data[CONF_LOCATION_ID]


@pytest.mark.asyncio
async def test_migration_rejects_future_minor_version(hass, mock_config_entry) -> None:
    """A future schema is never migrated backward."""
    entry = MockConfigEntry(domain="sunsethue", data=mock_config_entry.data, version=1, minor_version=2)
    assert not await async_migrate_entry(hass, entry)


@pytest.mark.asyncio
async def test_update_listener_reloads_entry(hass, mock_config_entry, monkeypatch) -> None:
    """Options and reconfigure changes reload the integration exactly once."""
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    await _async_update_listener(hass, mock_config_entry)
    reload.assert_awaited_once_with(mock_config_entry.entry_id)
