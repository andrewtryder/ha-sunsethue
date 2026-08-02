"""Translation strings for forecast selectors and option labels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.helpers.translation import async_get_translations

from custom_components.sunsethue.const import DOMAIN

TRANSLATIONS_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "sunsethue" / "translations" / "en.json"


def test_bundled_en_json_contains_forecast_selector_labels() -> None:
    """The shipped en.json exposes field and selector labels for the forecast UI."""
    payload = json.loads(TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    assert payload["options"]["step"]["init"]["data"]["forecast_start_offset"] == "First forecast day"
    assert payload["options"]["step"]["init"]["data"]["forecast_days"] == "Number of consecutive forecast days"
    assert "Today is the default" in payload["options"]["step"]["init"]["data_description"]["forecast_start_offset"]
    assert "consecutive dates" in payload["options"]["step"]["init"]["data_description"]["forecast_days"]
    assert payload["selector"]["forecast_start_offset"]["options"] == {
        "0": "Today",
        "1": "Tomorrow",
        "2": "Day after tomorrow",
    }
    assert payload["selector"]["forecast_days"]["options"] == {
        "1": "1 day",
        "2": "2 consecutive days",
        "3": "3 consecutive days",
    }
    assert "today's forecast" in payload["config"]["step"]["user"]["description"]


@pytest.mark.asyncio
async def test_loaded_translations_resolve_forecast_labels(hass) -> None:
    """Home Assistant loads integration translations with user-facing forecast strings."""
    translations = await async_get_translations(hass, "en", "selector", {DOMAIN})
    assert translations.get(f"component.{DOMAIN}.selector.forecast_start_offset.options.0") == "Today"
    assert translations.get(f"component.{DOMAIN}.selector.forecast_start_offset.options.1") == "Tomorrow"
    assert translations.get(f"component.{DOMAIN}.selector.forecast_days.options.1") == "1 day"
    assert translations.get(f"component.{DOMAIN}.selector.forecast_days.options.3") == "3 consecutive days"

    options = await async_get_translations(hass, "en", "options", {DOMAIN})
    assert options.get(f"component.{DOMAIN}.options.step.init.data.forecast_start_offset") == "First forecast day"
    assert (
        options.get(f"component.{DOMAIN}.options.step.init.data.forecast_days") == "Number of consecutive forecast days"
    )
    assert "Today is the default" in (
        options.get(f"component.{DOMAIN}.options.step.init.data_description.forecast_start_offset") or ""
    )
