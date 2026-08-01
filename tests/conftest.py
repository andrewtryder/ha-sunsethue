"""Shared SunsetHue test fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunsethue.const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant's loader to discover the local component."""


@pytest.fixture
def event_full() -> dict[str, Any]:
    """Return the representative full API response."""
    return json.loads((FIXTURES / "event_full.json").read_text())


@pytest.fixture
def event_without_model_data() -> dict[str, Any]:
    """Return a valid API response without model fields."""
    return json.loads((FIXTURES / "event_without_model_data.json").read_text())


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a default SunsetHue config entry without a real credential."""
    return MockConfigEntry(
        domain="sunsethue",
        title="Home",
        unique_id="test-location-id",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_LOCATION_NAME: "Home",
            CONF_LATITUDE: 40.7128,
            CONF_LONGITUDE: -74.006,
            CONF_TIME_ZONE: "America/New_York",
            CONF_LOCATION_ID: "test-location-id",
        },
    )
