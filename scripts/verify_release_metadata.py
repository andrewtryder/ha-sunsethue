"""Verify that all user-facing SunsetHue version declarations agree."""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path

VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class VersionConsistencyError(ValueError):
    """Raised when a release version declaration is missing or inconsistent."""


def verify_versions(root: Path, expected_version: str | None = None) -> str:
    """Return the shared version or raise when tracked declarations disagree."""
    versions = {
        "pyproject.toml": _pyproject_version(root / "pyproject.toml"),
        "manifest.json": _manifest_version(root / "custom_components/sunsethue/manifest.json"),
        "const.py": _const_version(root / "custom_components/sunsethue/const.py"),
    }
    declared_versions = set(versions.values())
    if len(declared_versions) != 1:
        raise VersionConsistencyError(f"Version declarations differ: {versions}")

    version = declared_versions.pop()
    if not VERSION_PATTERN.fullmatch(version):
        raise VersionConsistencyError(f"Version must be semantic X.Y.Z, got {version!r}")
    if expected_version is not None and version != expected_version:
        raise VersionConsistencyError(f"Expected {expected_version!r}, found {version!r}")
    return version


def _pyproject_version(path: Path) -> str:
    """Read the project version from pyproject.toml."""
    project = tomllib.loads(path.read_text())["project"]
    return _string_value(project.get("version"), path)


def _manifest_version(path: Path) -> str:
    """Read the integration version from manifest.json."""
    return _string_value(json.loads(path.read_text()).get("version"), path)


def _const_version(path: Path) -> str:
    """Read the VERSION assignment from the integration constants module."""
    module = ast.parse(path.read_text(), filename=path)
    for statement in module.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "VERSION"
            and isinstance(statement.value, ast.Constant)
        ):
            return _string_value(statement.value.value, path)
    raise VersionConsistencyError(f"VERSION assignment missing from {path}")


def _string_value(value: object, path: Path) -> str:
    """Require a non-empty string version value."""
    if not isinstance(value, str) or not value:
        raise VersionConsistencyError(f"Version missing or invalid in {path}")
    return value


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the metadata verifier as a command-line program."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-version")
    args = parser.parse_args(arguments)
    try:
        version = verify_versions(args.root, args.expected_version)
    except VersionConsistencyError as err:
        parser.error(str(err))
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
