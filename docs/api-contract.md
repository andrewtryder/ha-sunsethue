# Sunsethue API contract

Verified 2026-08-02 against the [developer page](https://sunsethue.com/dev-api)
and its linked [Postman documentation](https://documenter.getpostman.com/view/39964523/2sAYBUDY4W),
plus observed production error responses.

## Documented request

- Base URL: `https://api.sunsethue.com`
- Endpoint: `GET /event`
- Authentication: API key in the `x-api-key` request header. The docs also
  describe a query-key form, but this integration intentionally never uses it.
- Required parameters: WGS84 `latitude`, `longitude`, local `date` formatted
  `YYYY-MM-DD`, and `type` of `sunrise` or `sunset`.
- Optional `forecast` is boolean-like and defaults to `true`. `false` forces
  `model_data` false while still returning event timing, direction, and magic
  hours.
- Forecast horizon is three days from today (offsets 0, 1, and 2). The service
  says forecasts are updated four times per day and may be cached per grid cell
  for six hours.

Config-flow and reauth validation send `forecast=false` for the user-selected
forecast date so setup can confirm the API key, connectivity, and parameters
without spending model-data credits. Coordinator refresh sends `forecast=true`
because quality sensors need model fields. New installations default to one
local date (today) with sunrise and sunset enabled, so each refresh uses two
`forecast=true` requests unless the user expands the window in options. The
integration never calls `/usage` or any other endpoint. A response costs 1
credit when `model_data` is false and 5 credits when it is true, per the
Postman documentation.

## Response

The top-level object has request `time` (UTC), requested `location`,
`grid_location` (upper-left model grid-cell coordinates), and `data`. `data`
has `type`, `model_data`, event `time`, `direction`, and optional model fields:
normalized `quality`, normalized `cloud_cover`, `quality_text`, and `magics`
with two-item `blue_hour` and `golden_hour` timestamp arrays. Timestamps are
ISO 8601 with an offset. Unknown fields are ignored. `model_data: false` is a
valid success response and quality/cloud cover may be absent.

Verified nested `magics` shape:

```json
"magics": {
  "blue_hour": ["2026-08-03T00:32:00.000Z", "2026-08-03T00:47:00.000Z"],
  "golden_hour": ["2026-08-02T23:50:00.000Z", "2026-08-03T00:25:00.000Z"]
}
```

Each window is a two-item array of timezone-aware timestamps (or `null`
endpoints). The integration maps index `0` to `start` and index `1` to `end`,
and rejects reversed non-null windows.

## Errors and implementation policy

Published documentation describes JSON error objects with `status`, `code`, and
`message`, and lists 400 user errors and 500 server errors. It does not document
authentication HTTP codes, 422, 429, `Retry-After`, rate-limit headers, or an
attribution requirement.

Empirically observed quota exhaustion response (not listed as a named code in
the public Postman docs reviewed for this release):

```json
{"status": 400, "code": 204, "message": "Exceeded daily quota"}
```

The client reads a bounded response body before mapping failures so documented
JSON error fields are available. When `code` is `204` (or the sanitized message
indicates daily quota exhaustion), the client raises a dedicated quota error
(config flow: `quota_exceeded`; coordinator: `UpdateFailed` without reauth).
Coordinate-specific 400/422 messages map to `invalid_coordinates`. Other
400/422 rejections map to `invalid_request`. Standard 401/403 map to
reauthentication, 5xx/network failures to transient failures, and 429 to a
bounded `Retry-After` delay. Unknown error codes are treated as generic invalid
requests or connection failures by HTTP class only—those mappings are
implementation inferences, not claimed API guarantees. No branding or
attribution requirement was found in the reviewed sources.
