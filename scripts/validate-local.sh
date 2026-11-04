#!/usr/bin/env bash
set -euo pipefail

# Portfolio Universal Local Validation Contract
# Repository: ha-sunsethue
# Gate: 96% component branch coverage

echo "==> [1/8] Verifying toolchain and interpreter"
command -v uv >/dev/null 2>&1 || { echo "Error: uv is required but not installed"; exit 1; }
python_version=$(uv run --locked python --version)
echo "Using $python_version"

echo "==> [2/8] Verifying dependency lockfile freshness"
uv lock --check

echo "==> [3/8] Running pre-commit hooks on all files"
uv run --locked pre-commit run --all-files

echo "==> [4/8] Running Ruff lint and formatting checks"
uv run --locked ruff check .
uv run --locked ruff format --check .

echo "==> [5/8] Running Mypy strict type checks"
uv run --locked mypy custom_components/sunsethue

echo "==> [6/8] Verifying release metadata consistency"
uv run --locked python scripts/verify_release_metadata.py --expected-version 0.4.5
uv run --locked python scripts/verify_hacs_distribution.py

echo "==> [7/8] Running Python test suite with branch coverage (>=96% gate)"
uv run --locked python -m pytest

echo "==> [8/8] Verifying clean git working tree"
git diff --exit-code

echo "==> Local validation passed successfully!"
