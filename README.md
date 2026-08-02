# SunsetHue

SunsetHue is an unofficial community Home Assistant integration for the
[Sunsethue developer API](https://sunsethue.com/dev-api). It creates forecast
quality sensors for sunrise and sunset at one or more locations. It is neither
reviewed, endorsed, nor supported by Home Assistant or Sunsethue.

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=andrewtryder&repository=ha-sunsethue&category=integration)

![SunsetHue service page in Home Assistant showing quality sensors and activity](docs/images/home-assistant-service.png)

## Requirements

- Home Assistant 2026.3.0 or newer (Python 3.14 or newer).
- A Sunsethue API key from the [API portal](https://sunsethue.com/dev-api/portal).
- HACS for the easiest installation, or filesystem access for manual installation.

## Install

In HACS, add `https://github.com/andrewtryder/ha-sunsethue` as an Integration
custom repository, install a numbered **SunsetHue** release, then restart Home
Assistant. Do not install `main` for normal use. HACS installs from the tagged
repository source using the standard `custom_components/sunsethue` layout; no
custom release ZIP is required. GitHub may still show automatic *Source code*
ZIP and tarball links on a release page; those are unrelated to HACS install.

For a manual installation, copy `custom_components/sunsethue` from a release
into `<config>/custom_components/sunsethue`, then restart. After a correct
install, `manifest.json` is at
`<config>/custom_components/sunsethue/manifest.json`.

After the restart, add **SunsetHue** from *Settings → Devices & services → Add
integration* (not *Devices → Add device*). Supply a display name, API key,
latitude, longitude, an IANA time zone such as `America/New_York`, and the
initial forecast day (today, tomorrow, or day after tomorrow). New installations
default to **tomorrow only**. Configure another entry for each location.
Location coordinates are validated by Sunsethue and duplicate normalized
locations are rejected. See [troubleshooting](docs/troubleshooting.md) if the
integration does not appear.

## Entities and updates

New installations create quality and quality-text sensors for the selected
forecast day (default: tomorrow) for sunrise and sunset — **two API requests per
refresh** when both event types stay enabled. Existing installations keep their
previous forecast window through migration (previously three days starting
today, six requests by default).

Quality is shown as a percentage. A companion quality-text sensor shows the
API's raw description (`Poor`, `Fair`, `Good`, `Great`, `Excellent`, or any
future string). The API may report no model data, in which case those sensors
are unavailable without making the integration fail. Quality sensors also
include event time, cloud cover, direction, blue/golden-hour windows, and
response metadata as attributes where supplied by the API.

Optional detailed entities create separate event-time, cloud-cover, direction,
and magic-hour sensors. From integration options you can change the first
forecast day, consecutive day count (within the three-day horizon), sunrise
and/or sunset, a 6/12/24-hour polling interval, and detail entities. The
six-hour default follows Sunsethue's cache guidance; the integration also
refreshes shortly after each location's local midnight.

API usage: setup validation requests one event with `forecast=false` (1 credit)
for the selected day. Each coordinator refresh uses `forecast=true`. Selecting
more days or both event types increases requests. Increase your allowance in the
[Sunsethue developer portal](https://sunsethue.com/dev-api/portal) if you hit
the daily quota.

| Entity | Unit | Availability |
| --- | --- | --- |
| Quality (default) | % | Unavailable only when that forecast has no model quality or is missing. |
| Quality text (default) | — | Unavailable only when that forecast has no quality text. |
| Event time (optional) | Timestamp | Unavailable when the API does not provide an event time. |
| Cloud cover (optional) | % | Unavailable when the API does not provide cloud cover. |
| Direction (optional) | ° | Unavailable when the API does not provide direction. |
| Blue/golden-hour boundaries (optional) | Timestamp | Unavailable when the relevant boundary is absent. |

See [dashboard examples](docs/dashboard-examples.md) for native and optional
Mushroom pill layouts, and [automation examples](docs/automation-examples.md)
for notifications and lighting.

## Automation blueprints

[![Import the SunsetHue quality notification blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/andrewtryder/ha-sunsethue/blob/main/blueprints/automation/sunsethue/notify_sunset_quality_threshold.yaml)

The official [sunset-quality notification blueprint](blueprints/automation/sunsethue/notify_sunset_quality_threshold.yaml)
runs your chosen notification or action sequence whenever a selected sunset
quality sensor updates above a percentage you set. Use the manual
[automation examples](docs/automation-examples.md) when you need custom logic.

## Privacy and support

The API key is stored in the config entry and sent only as the documented
`x-api-key` HTTPS header. It is never included in entity IDs, states,
attributes, logs, diagnostics, or test fixtures. Diagnostics redact configured
and model-grid coordinates and do not include request headers. Use *Settings →
Devices & services → SunsetHue → Download diagnostics* when opening an issue,
reviewing the file before sharing it.

If an API key is revoked or expires, Home Assistant starts reauthentication.
Daily quota exhaustion shows a quota-specific error and does not blame
coordinates. See [troubleshooting](docs/troubleshooting.md). Remove an entry
from its integration page, then uninstall through HACS or delete
`custom_components/sunsethue`; removing an entry does not alter your Sunsethue
account or API key.

## Support

Report reproducible integration defects through [GitHub Issues](https://github.com/andrewtryder/ha-sunsethue/issues). Never include an API key, exact address, or unreviewed diagnostics.

## Development and release

Requires [uv](https://docs.astral.sh/uv/) so pre-commit and local commands share the
locked dependency set.

```bash
uv sync --group dev --locked
uv run pre-commit install
uv run pre-commit run --all-files
uv run python -m pytest
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev mypy custom_components/sunsethue scripts
uv run --group dev mypy --config-file mypy-tests.ini tests/helpers.py
python scripts/verify_release_metadata.py
python scripts/verify_hacs_distribution.py
```

Pre-commit runs the complete Home Assistant test suite with branch coverage after
the fast formatting hooks, so a full `pre-commit run --all-files` can take longer
than lint-only checks. Commits fail below **96%** branch-aware coverage. CI
repeats the same coverage-enforced suite against the minimum supported and
current stable Home Assistant versions.

The GitHub workflows validate HACS, Hassfest, linting, GitHub Actions syntax,
source-layout distribution, and tests against the minimum supported and current
stable Home Assistant releases. Release Please opens and publishes releases from
Conventional Commits and updates the integration version. Do not create release
tags manually. For a Release Please PR, run **Refresh release lock** on that
release branch, then manually dispatch the protected validation workflows on
the same branch before merging it.

## Contributing

Use Conventional Commits for every commit. Valid types include `feat`, `fix`,
`docs`, `test`, `refactor`, `ci`, and `chore`; use `feat!:` or a breaking-change
footer for a major release. `feat:` produces a minor release and `fix:` a patch
release. `docs:`, `chore:`, `ci:`, `test:`, and `refactor:` do not open a release.
Run `npm ci` followed by `npm run commitlint -- --from <base-sha> --to
HEAD` before opening a pull request.

Consult Sunsethue's current developer page and terms for pricing, quotas, and
permitted use rather than relying on this repository for those details.
