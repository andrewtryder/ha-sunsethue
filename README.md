# SunsetHue

SunsetHue is an unofficial community Home Assistant integration for the
[Sunsethue developer API](https://sunsethue.com/dev-api). It creates forecast
quality sensors for sunrise and sunset at one or more locations. It is neither
reviewed, endorsed, nor supported by Home Assistant or Sunsethue.

## Requirements

- Home Assistant 2026.3.0 or newer.
- A Sunsethue API key from the [API portal](https://sunsethue.com/dev-api/portal).
- HACS for the easiest installation, or filesystem access for manual installation.

## Install

In HACS, add `https://github.com/andrewtryder/ha-sunsethue` as an Integration
custom repository, install **SunsetHue**, then restart Home Assistant. For a
manual installation, copy `custom_components/sunsethue` from a release into
`<config>/custom_components/sunsethue`, then restart.

Add **SunsetHue** from *Settings → Devices & services → Add integration*.
Supply a display name, API key, latitude, longitude, and an IANA time zone such
as `America/New_York`. Configure another entry for each location. Location
coordinates are validated by Sunsethue and duplicate normalized locations are
rejected.

## Entities and updates

By default each location has six quality sensors: today, tomorrow, and day
after tomorrow for both sunrise and sunset. Quality is shown as a percentage;
the API may report no model data, in which case that forecast is unavailable
without making the integration fail. Quality sensors also include event time,
cloud cover, direction, blue/golden-hour windows, and response metadata as
attributes where supplied by the API.

Optional detailed entities create separate event-time, cloud-cover, direction,
and magic-hour sensors. Choose one to three forecast days, sunrise and/or
sunset, a 6/12/24-hour polling interval, and detail entities from the
integration options. The six-hour default follows Sunsethue's cache guidance;
the integration also refreshes shortly after each location's local midnight.

Example dashboard card:

```yaml
type: entities
title: Sunset forecast
entities:
  - sensor.home_today_sunset_quality
  - sensor.home_today_sunrise_quality
```

See [automation examples](docs/automation-examples.md) for notifications and
lighting examples.

## Privacy and support

The API key is stored in the config entry and sent only as the documented
`x-api-key` HTTPS header. It is never included in entity IDs, states,
attributes, logs, diagnostics, or test fixtures. Diagnostics round coordinate
values and do not include request headers. Use *Settings → Devices & services
→ SunsetHue → Download diagnostics* when opening an issue, reviewing the file
before sharing it.

If an API key is revoked or expires, Home Assistant starts reauthentication.
See [troubleshooting](docs/troubleshooting.md) for rate limits and availability.
Remove an entry from its integration page, then uninstall through HACS or delete
`custom_components/sunsethue`; removing an entry does not alter your Sunsethue
account or API key.

## Development and release

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/sunsethue
uv run pytest
pre-commit run --all-files
```

The GitHub workflows validate HACS, Hassfest, linting, and tests against the
minimum supported and current stable Home Assistant releases. Publish a semantic
version tag only after green CI; the release workflow verifies the manifest,
packages `custom_components/sunsethue`, writes a checksum, and creates a GitHub
Release. Consult Sunsethue's current developer page and terms for pricing,
quotas, and permitted use rather than relying on this repository for those
details.

## Roadmap

Potential future work includes more platforms and configurable presentation;
version 0.1.0 deliberately excludes YAML configuration, services, refresh
buttons, historical storage, geocoding, account management, and frontend cards.
