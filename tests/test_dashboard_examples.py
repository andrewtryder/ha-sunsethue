"""Dashboard documentation safety checks."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "lovelace"
DOCS = ROOT / "docs" / "dashboard-examples.md"


def test_dashboard_examples_use_placeholders_without_secrets() -> None:
    """Documented dashboards must not embed credentials or exact coordinates."""
    assert DOCS.is_file()
    docs = DOCS.read_text()
    assert "Mushroom Cards" in docs
    assert "does not depend on Mushroom" in docs.casefold() or "never requires" in docs
    assert "REPLACE_WITH_" in docs
    assert "api_key" not in docs.casefold()
    assert "42.90754" not in docs
    assert "-71.15062" not in docs

    for path in EXAMPLES.glob("*.yaml"):
        payload = yaml.safe_load(path.read_text())
        dumped = yaml.safe_dump(payload)
        assert "REPLACE_WITH_" in dumped
        assert "api_key" not in dumped.casefold()
        assert "42.90754" not in dumped
        assert "x-api-key" not in dumped.casefold()
