"""Tests for HACS source-distribution layout validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_hacs_distribution import HacsDistributionError, verify_hacs_distribution


def _write_valid_tree(root: Path) -> None:
    """Create a minimal repository tree that passes distribution checks."""
    integration = root / "custom_components" / "sunsethue"
    integration.mkdir(parents=True)
    (root / "hacs.json").write_text(
        json.dumps(
            {
                "name": "SunsetHue",
                "homeassistant": "2026.3.0",
                "hide_default_branch": True,
            }
        ),
        encoding="utf-8",
    )
    (integration / "manifest.json").write_text(
        json.dumps({"domain": "sunsethue", "version": "0.2.1"}),
        encoding="utf-8",
    )
    (integration / "__init__.py").write_text("", encoding="utf-8")
    (integration / "config_flow.py").write_text("", encoding="utf-8")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "release.yml").write_text("name: Release Please\n", encoding="utf-8")


def test_verify_hacs_distribution_accepts_standard_layout(tmp_path: Path) -> None:
    """The standard custom_components/sunsethue layout must pass."""
    _write_valid_tree(tmp_path)
    verify_hacs_distribution(tmp_path)


@pytest.mark.parametrize("key", ["zip_release", "filename"])
def test_verify_hacs_distribution_rejects_forbidden_hacs_keys(tmp_path: Path, key: str) -> None:
    """Custom ZIP HACS keys must fail validation."""
    _write_valid_tree(tmp_path)
    hacs = json.loads((tmp_path / "hacs.json").read_text(encoding="utf-8"))
    hacs[key] = True if key == "zip_release" else "sunsethue.zip"
    (tmp_path / "hacs.json").write_text(json.dumps(hacs), encoding="utf-8")

    with pytest.raises(HacsDistributionError, match=key):
        verify_hacs_distribution(tmp_path)


def test_verify_hacs_distribution_rejects_missing_manifest(tmp_path: Path) -> None:
    """A missing manifest must fail validation."""
    _write_valid_tree(tmp_path)
    (tmp_path / "custom_components" / "sunsethue" / "manifest.json").unlink()

    with pytest.raises(HacsDistributionError, match="Missing integration files"):
        verify_hacs_distribution(tmp_path)


def test_verify_hacs_distribution_rejects_incorrect_domain(tmp_path: Path) -> None:
    """The manifest domain must remain sunsethue."""
    _write_valid_tree(tmp_path)
    (tmp_path / "custom_components" / "sunsethue" / "manifest.json").write_text(
        json.dumps({"domain": "other", "version": "0.2.1"}),
        encoding="utf-8",
    )

    with pytest.raises(HacsDistributionError, match="domain must be sunsethue"):
        verify_hacs_distribution(tmp_path)


def test_verify_hacs_distribution_rejects_nested_directory(tmp_path: Path) -> None:
    """A nested sunsethue/sunsethue install layout must fail CI."""
    _write_valid_tree(tmp_path)
    nested = tmp_path / "custom_components" / "sunsethue" / "sunsethue"
    nested.mkdir()
    (nested / "manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(HacsDistributionError, match="Nested"):
        verify_hacs_distribution(tmp_path)


def test_verify_hacs_distribution_rejects_workflow_zip_packaging(tmp_path: Path) -> None:
    """Workflows must not recreate custom ZIP packaging or uploads."""
    _write_valid_tree(tmp_path)
    (tmp_path / ".github" / "workflows" / "release.yml").write_text(
        "run: zip -r dist/sunsethue.zip sunsethue\nrun: gh release upload tag dist/sunsethue.zip\n",
        encoding="utf-8",
    )

    with pytest.raises(HacsDistributionError, match="custom ZIP"):
        verify_hacs_distribution(tmp_path)
