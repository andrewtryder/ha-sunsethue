# Troubleshooting

**Integration not in Add integration:** HACS only downloads the files. Restart
Home Assistant after install, then open *Settings → Devices & services → Add
integration* and search for **SunsetHue**. Do not use *Devices → Add device*;
that list is for discovered hardware, and SunsetHue is a service integration.
Confirm Home Assistant is **2026.3.0 or newer** (Python **3.14+**) under
*Settings → About*. If it still does not appear, check *Settings → System →
Logs* for `sunsethue`, `SyntaxError`, or `Error loading custom integration`.

**Authentication failed:** regenerate or copy the API key from the Sunsethue API
portal, then use Home Assistant's reconfigure/reauthenticate prompt. Never put
the key in an issue or log.

**Unavailable quality:** this is expected when Sunsethue returns
`model_data: false`. Event-time attributes and optional detailed fields may
still be present. It is not an integration outage.

**Rate limited:** wait for the service's requested delay. The integration never
polls more frequently than six hours and respects a safe `Retry-After` value.
Review current API quota and terms in the Sunsethue portal.

**Location or time wrong:** reconfigure the entry with WGS84 decimal coordinates
and an IANA time zone such as `Europe/Amsterdam`. Dates are requested in that
location's local time.

**Need support:** download the integration diagnostics and review them before
sharing. Diagnostics deliberately round coordinates and redact credentials.
