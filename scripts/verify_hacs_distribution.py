"""Verify SunsetHue uses the standard HACS source-layout distribution."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HACS_PATH = ROOT / "hacs.json"
INTEGRATION_PATH = ROOT / "custom_components" / "sunsethue"
WORKFLOWS_PATH = ROOT / ".github" / "workflows"

FORBIDDEN_HACS_KEYS = frozenset({"zip_release", "filename"})
REQUIRED_INTEGRATION_FILES = ("manifest.json", "__init__.py", "config_flow.py")
FORBIDDEN_WORKFLOW_PATTERNS = (
    re.compile(r"\bzip_release\b"),
    re.compile(r"sunsethue\.zip"),
    re.compile(r"sunsethue\.zip\.sha256"),
    re.compile(r"gh\s+release\s+upload\b"),
    re.compile(r"\bzip\s+-r\b"),
)


class HacsDistributionError(ValueError):
    """Raised when HACS distribution metadata or layout is invalid."""


def verify_hacs_distribution(root: Path | None = None) -> None:
    """Validate HACS config, integration layout, and release workflow hygiene."""
    base = ROOT if root is None else root
    hacs_path = base / "hacs.json"
    integration_path = base / "custom_components" / "sunsethue"
    workflows_path = base / ".github" / "workflows"

    if not hacs_path.is_file():
        raise HacsDistributionError(f"Missing {hacs_path.relative_to(base)}")

    try:
        hacs = json.loads(hacs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise HacsDistributionError(f"hacs.json is not valid JSON: {err}") from err
    if not isinstance(hacs, dict):
        raise HacsDistributionError("hacs.json must contain a JSON object")

    forbidden = FORBIDDEN_HACS_KEYS & hacs.keys()
    if forbidden:
        raise HacsDistributionError(
            "Custom ZIP distribution is disabled; remove HACS keys: " + ", ".join(sorted(forbidden))
        )

    required = [integration_path / name for name in REQUIRED_INTEGRATION_FILES]
    missing = [str(path.relative_to(base)) for path in required if not path.is_file()]
    if missing:
        raise HacsDistributionError(f"Missing integration files: {', '.join(missing)}")

    nested = integration_path / "sunsethue"
    if nested.exists():
        raise HacsDistributionError("Nested custom_components/sunsethue/sunsethue directory detected")

    try:
        manifest = json.loads((integration_path / "manifest.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise HacsDistributionError(f"manifest.json is not valid JSON: {err}") from err
    if not isinstance(manifest, dict):
        raise HacsDistributionError("manifest.json must contain a JSON object")
    if manifest.get("domain") != "sunsethue":
        raise HacsDistributionError("Manifest domain must be sunsethue")

    _verify_workflows_have_no_custom_zip_packaging(workflows_path, base)


def _verify_workflows_have_no_custom_zip_packaging(workflows_path: Path, root: Path) -> None:
    """Fail when release workflows recreate the obsolete custom ZIP pipeline."""
    if not workflows_path.is_dir():
        return
    violations: list[str] = []
    for path in sorted(workflows_path.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_WORKFLOW_PATTERNS:
            if pattern.search(text):
                violations.append(f"{path.relative_to(root)} matches {pattern.pattern}")
    if violations:
        raise HacsDistributionError(
            "Release workflows must not create or upload custom ZIP assets:\n" + "\n".join(violations)
        )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the HACS distribution verifier as a command-line program."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(arguments)
    try:
        verify_hacs_distribution(args.root)
    except HacsDistributionError as err:
        parser.error(str(err))
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
