# API usage and refreshes

Return to the [README](../README.md) for setup.

Each coordinator refresh requests one SunsetHue `/event` call per selected
forecast date and enabled event type:

`selected dates × enabled event types = API calls per refresh`

Examples:

- Today, sunrise and sunset: **2** calls
- Today through day after tomorrow, sunrise and sunset: **6** calls
- One day, sunset only: **1** call

Setup validation uses one lightweight `forecast=false` request. Ongoing refresh
uses `forecast=true` so quality sensors receive model data. The integration also
refreshes shortly after each location's local midnight.

Current quota and pricing details are in the
[SunsetHue developer portal](https://sunsethue.com/dev-api/portal). See
[docs/api-contract.md](api-contract.md) for the request and response
contract used by this integration.
