# Dashboard examples

These examples use native Home Assistant dashboard cards and an optional
[Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) HACS frontend
integration. SunsetHue does **not** bundle a custom JavaScript card and does
**not** depend on Mushroom Cards.

Replace every `sensor.REPLACE_WITH_*` entity ID with entities from your
installation. Entity IDs follow Home Assistant naming from the location title
and translated sensor names, for example:

```text
sensor.sandown_nh_tomorrow_sunset_quality
sensor.sandown_nh_tomorrow_sunset_quality_text
```

When detailed entities are disabled, event time, cloud cover, direction, and
magic-hour boundaries remain available as attributes on the quality and
quality-text sensors.

## Native Home Assistant cards

Native cards can show quality percentage, quality text, and attributes, but
they cannot dynamically recolor arbitrary text states such as `Poor` or
`Excellent`. Use a static entities/markdown layout, or the optional Mushroom
example below for a colored pill.

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Tomorrow's sunset forecast
    entities:
      - entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        name: Quality
      - entity: sensor.REPLACE_WITH_QUALITY_TEXT_ENTITY
        name: Description
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: event_time
        name: Event time
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: cloud_cover_percent
        name: Cloud cover
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: direction_degrees
        name: Direction
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: golden_hour_start
        name: Golden hour start
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: golden_hour_end
        name: Golden hour end
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: blue_hour_start
        name: Blue hour start
      - type: attribute
        entity: sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
        attribute: blue_hour_end
        name: Blue hour end
```

Copy-ready file: [`examples/lovelace/sunsethue-native.yaml`](../examples/lovelace/sunsethue-native.yaml).

## Optional Mushroom colored pill

Install [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) separately
through HACS if you want a pill-shaped chip whose icon color follows the API's
raw `quality_text` state. SunsetHue itself never requires this frontend package.

Color mapping (case-insensitive):

| Quality text | Color |
| --- | --- |
| Poor | red |
| Fair | orange |
| Good | yellow |
| Great | green |
| Excellent | purple |
| Unknown / unavailable | grey |

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-chips-card
    chips:
      - type: template
        entity: sensor.REPLACE_WITH_QUALITY_TEXT_ENTITY
        content: >-
          {{ states('sensor.REPLACE_WITH_QUALITY_TEXT_ENTITY') }}
          ·
          {{ states('sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY') }}%
        icon: mdi:weather-sunset
        icon_color: >-
          {% set quality = states('sensor.REPLACE_WITH_QUALITY_TEXT_ENTITY') | lower %}
          {% set colors = {
            'poor': 'red',
            'fair': 'orange',
            'good': 'yellow',
            'great': 'green',
            'excellent': 'purple'
          } %}
          {{ colors.get(quality, 'grey') }}

  - type: entities
    title: Tomorrow's sunset forecast
    entities:
      - sensor.REPLACE_WITH_QUALITY_PERCENT_ENTITY
      - sensor.REPLACE_WITH_QUALITY_TEXT_ENTITY
```

When detailed entities are enabled, add those sensors to the entities card.
When they are disabled, keep reading details from quality-sensor attributes as
in the native example.

Copy-ready file: [`examples/lovelace/sunsethue-mushroom.yaml`](../examples/lovelace/sunsethue-mushroom.yaml).

Do not put API keys, exact home coordinates, or unreviewed diagnostics into a
shared dashboard configuration.
