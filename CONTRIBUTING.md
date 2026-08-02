# Contributing

This repository ships a HACS custom integration for Home Assistant. Use
[uv](https://docs.astral.sh/uv/) so local tools and CI share the locked
dependency set.

## Local setup

```bash
uv sync --group dev --locked
uv run pre-commit install
```

Useful checks:

```bash
uv run pre-commit run --all-files
uv run python -m pytest
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev mypy custom_components/sunsethue scripts
uv run --group dev mypy --config-file mypy-tests.ini tests/helpers.py
python scripts/verify_release_metadata.py
python scripts/verify_hacs_distribution.py
```

Pre-commit runs formatting hooks first, then the full Home Assistant test suite
with branch coverage. A complete `pre-commit run --all-files` can take longer
than lint-only checks. Commits fail below **96%** branch-aware coverage.

## Continuous integration

GitHub Actions validate HACS, Hassfest, linting, GitHub Actions workflow syntax,
source-layout distribution, and tests against the minimum supported and current
stable Home Assistant releases. CI repeats the same coverage-enforced suite used
locally.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) for every
commit. Valid types include `feat`, `fix`, `docs`, `test`, `refactor`, `ci`,
and `chore`. Use `feat!:` or a breaking-change footer for a major release.

| Commit type | Release effect |
| --- | --- |
| `feat:` | Minor release |
| `fix:` | Patch release |
| `feat!:` / breaking footer | Major release |
| `docs:`, `chore:`, `ci:`, `test:`, `refactor:` | No release |

Before opening a pull request:

```bash
npm ci
npm run commitlint -- --from <base-sha> --to HEAD
```

## Releases

Release Please opens and publishes releases from Conventional Commits and
updates the integration version. Do not create release tags manually.

For a Release Please pull request:

1. Run **Refresh release lock** on that release branch.
2. Manually dispatch the protected validation workflows on the same branch.
3. Merge only after those checks pass.

## Documentation

- User-facing installation and configuration: [README.md](README.md)
- API request/response contract: [docs/api-contract.md](docs/api-contract.md)
- Troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)
- Dashboard examples: [docs/dashboard-examples.md](docs/dashboard-examples.md)
- Automation examples: [docs/automation-examples.md](docs/automation-examples.md)

Consult SunsetHue's current developer page and terms for pricing, quotas, and
permitted use rather than relying on this repository for those details.
