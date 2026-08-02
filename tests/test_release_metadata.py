"""Tests for release metadata consistency validation."""

from __future__ import annotations

import json

import pytest

from scripts.verify_release_metadata import VersionConsistencyError, verify_versions


def _write_metadata(root, *, pyproject: str = "0.1.1", manifest: str = "0.1.1", const: str = "0.1.1") -> None:
    """Write a minimal release metadata tree."""
    integration = root / "custom_components/sunsethue"
    integration.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f"[project]\nversion = {pyproject!r}\n")
    (integration / "manifest.json").write_text(json.dumps({"version": manifest}))
    (integration / "const.py").write_text(f"VERSION = {const!r}\n")


def test_verify_versions_accepts_matching_metadata(tmp_path) -> None:
    """All tracked release version declarations must agree."""
    _write_metadata(tmp_path)

    assert verify_versions(tmp_path, "0.1.1") == "0.1.1"


@pytest.mark.parametrize(
    ("field", "version"),
    [("pyproject", "0.2.0"), ("manifest", "0.2.0"), ("const", "0.2.0")],
)
def test_verify_versions_rejects_mismatched_metadata(tmp_path, field: str, version: str) -> None:
    """Every declaration participates in consistency validation."""
    _write_metadata(tmp_path, **{field: version})

    with pytest.raises(VersionConsistencyError, match="differ"):
        verify_versions(tmp_path)


def test_verify_versions_rejects_invalid_or_unexpected_version(tmp_path) -> None:
    """Published versions must be semantic and match their release tag."""
    _write_metadata(tmp_path, pyproject="version-one", manifest="version-one", const="version-one")
    with pytest.raises(VersionConsistencyError, match="semantic"):
        verify_versions(tmp_path)

    _write_metadata(tmp_path)
    with pytest.raises(VersionConsistencyError, match="Expected"):
        verify_versions(tmp_path, "0.2.0")
