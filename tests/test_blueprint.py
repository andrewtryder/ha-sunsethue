"""Tests for bundled SunsetHue automation blueprints."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.util import yaml as yaml_util

BLUEPRINT_PATH = Path(__file__).parents[1] / "blueprints/automation/sunsethue/notify_sunset_quality_threshold.yaml"


def test_sunset_quality_notification_blueprint_is_a_valid_automation_blueprint() -> None:
    """The bundled blueprint is accepted by Home Assistant's automation schema."""
    source = BLUEPRINT_PATH.read_text()
    blueprint = Blueprint(
        yaml_util.load_yaml_dict(BLUEPRINT_PATH),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )

    assert blueprint.domain == "automation"
    assert set(blueprint.inputs) == {"sunset_quality_sensor", "quality_threshold", "notification_action"}
    assert "action" in blueprint.inputs["notification_action"]["selector"]
    assert blueprint.data["mode"] == "queued"
    assert blueprint.data["max"] == 10
    assert "trigger: state" in source
    assert "is_number(trigger.to_state.state)" in source
    assert "(trigger.to_state.state | float) > (quality_threshold | float)" in source
    assert "actions: !input notification_action" in source
