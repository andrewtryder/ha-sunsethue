# Sunsethue API contract

Verified 2026-08-01 against the [developer page](https://sunsethue.com/dev-api)
and its linked [Postman documentation](https://documenter.getpostman.com/view/39964523/2sAYBUDY4W).

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
- Forecast horizon is three days. The service says forecasts are updated four
  times per day and may be cached per grid cell for six hours.

The integration sends `forecast=true`; it never calls `/usage` or any other
endpoint. A response costs 1 credit when `model_data` is false and 5 credits
when it is true, per the Postman documentation.

## Response

The top-level object has request `time` (UTC), requested `location`,
`grid_location` (upper-left model grid-cell coordinates), and `data`. `data`
has `type`, `model_data`, event `time`, `direction`, and optional model fields:
normalized `quality`, normalized `cloud_cover`, `quality_text`, and `magics`
with two-item `blue_hour` and `golden_hour` timestamp arrays. Timestamps are
ISO 8601 with an offset. Unknown fields are ignored. `model_data: false` is a
valid success response and quality/cloud cover may be absent.

## Errors and implementation policy

Published documentation describes JSON error objects with `status`, `code`, and
`message`, and lists 400 user errors and 500 server errors. It does not document
authentication HTTP codes, 422, 429, `Retry-After`, rate-limit headers, or an
attribution requirement. The integration defensively maps standard 401/403 to
reauthentication, 400/422 to invalid request, 5xx/network failures to transient
failures, and 429 to a bounded `Retry-After` delay. Those mappings are
implementation inferences, not claimed API guarantees. No branding or
attribution requirement was found in the reviewed sources.
