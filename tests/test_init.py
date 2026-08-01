"""Version-gate tests."""

from __future__ import annotations

import pytest

from custom_components.sunsethue import is_supported_home_assistant_version
from custom_components.sunsethue.const import API_BASE_URL


def test_minimum_version_gate() -> None:
    """Only Home Assistant 2026.3 and later is supported."""
    assert not is_supported_home_assistant_version("2026.2.99")
    assert is_supported_home_assistant_version("2026.3.0")


@pytest.mark.asyncio
async def test_setup_and_unload(hass, mock_config_entry, aioclient_mock, event_full) -> None:
    """First refresh creates typed runtime data and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE_URL}/event", status=200, json=event_full)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.coordinator.data is not None
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
