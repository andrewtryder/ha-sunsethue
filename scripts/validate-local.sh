#!/usr/bin/env bash
set -euo pipefail

# Portfolio Universal Local Validation Contract
# Repository: ha-sunsethue
# Gate: 96% component branch coverage

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n $(git ls-files --others --exclude-standard) ]]; then
    echo "Error: move or commit untracked files before validation" >&2
    exit 1
fi

# Compare both index and working-tree changes, including untracked paths.
snapshot_dir=$(mktemp -d)
snapshot() {
    git status --porcelain=v1 --untracked-files=all > "$1/status"
    git diff --binary > "$1/worktree"
    git diff --cached --binary > "$1/index"
}
mkdir "$snapshot_dir/before" "$snapshot_dir/after"
snapshot "$snapshot_dir/before"
check_changes() {
    snapshot "$snapshot_dir/after"
    if ! diff -qr "$snapshot_dir/before" "$snapshot_dir/after" >/dev/null; then
        echo "Error: validation changed the working tree or index:" >&2
        git status --short >&2
        return 1
    fi
}
finish() {
    local result=$?
    check_changes || result=1
    rm -rf "$snapshot_dir"
    return "$result"
}
trap finish EXIT

echo "==> [1/8] Verifying toolchain and interpreter"
command -v uv >/dev/null 2>&1 || { echo "Error: uv is required but not installed"; exit 1; }
command -v actionlint >/dev/null 2>&1 || { echo "Error: actionlint is required but not installed" >&2; exit 1; }
uv sync --locked
uv run --locked python -c 'import sys; assert sys.version_info >= (3, 14, 2), "Python 3.14.2 or newer is required"; print(sys.version)'

echo "==> [2/8] Verifying dependency lockfile freshness"
uv lock --check

echo "==> [3/8] Running pre-commit hooks on all files"
uv run --locked pre-commit run --all-files

echo "==> [4/8] Running Ruff lint and formatting checks"
uv run --locked ruff check .
uv run --locked ruff format --check .

echo "==> [5/8] Running Mypy strict type checks"
uv run --locked mypy custom_components/sunsethue
uv run --locked mypy --config-file mypy-tests.ini tests/helpers.py
actionlint .github/workflows/*.yml

echo "==> [6/8] Verifying release metadata consistency"
uv run --locked python scripts/verify_release_metadata.py
uv run --locked python scripts/verify_hacs_distribution.py

echo "==> [7/8] Running Python test suite with branch coverage (>=96% gate)"
uv run --locked python -m pytest
uv run --locked python -c 'import json; t = json.load(open("coverage.json"))["totals"]; n = t["num_statements"]; c = t["covered_lines"]; print(f"Statement coverage: {c}/{n}"); assert n and c * 100 >= n * 90, "Statement coverage must be at least 90%"'

echo "==> [8/8] Checking for changes made by validation"
check_changes

echo "==> Local validation passed successfully!"
