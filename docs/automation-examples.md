# Automation examples

Replace every example entity ID with your own and keep the availability checks:
Sunsethue may validly omit forecast quality when model data is unavailable.

## Notify for an excellent sunset

```yaml
alias: Notify when sunset quality is high
triggers:
  - trigger: numeric_state
    entity_id: sensor.home_today_sunset_quality
    above: 80
conditions:
  - condition: template
    value_template: "{{ states('sensor.home_today_sunset_quality') not in ['unknown', 'unavailable'] }}"
actions:
  - action: notify.notify
    data:
      message: "Today's sunset forecast is {{ states('sensor.home_today_sunset_quality') }}%."
```

## Notify before the event time

Use the optional event-time sensor, which exposes a real timestamp state. This
template transitions to true 15 minutes before the event:

```yaml
alias: Sunset reminder
triggers:
  - trigger: template
    value_template: >-
      {% set event = as_datetime(states('sensor.home_today_sunset_event_time'), none) %}
      {{ event is not none and now() >= event - timedelta(minutes=15) }}
conditions:
  - condition: template
    value_template: "{{ states('sensor.home_today_sunset_quality') not in ['unknown', 'unavailable'] }}"
actions:
  - action: notify.notify
    data:
      message: "Sunset is in about 15 minutes."
```

## Blue-hour lighting and golden-hour reminder

```yaml
alias: Blue hour scene
triggers:
  - trigger: time
    at: sensor.home_today_sunset_blue_hour_start
actions:
  - action: scene.turn_on
    target: {entity_id: scene.blue_hour}
```

```yaml
alias: Golden hour photographer reminder
triggers:
  - trigger: time
    at: sensor.home_today_sunset_golden_hour_start
actions:
  - action: notify.notify
    data:
      message: "Golden hour has begun."
```
