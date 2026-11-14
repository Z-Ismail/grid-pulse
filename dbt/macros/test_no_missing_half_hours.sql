{#
  Generic test: fails with one row per half-hour slot missing between the
  first and last slot of the model. Catches source gaps and timezone bugs.
#}
{% test no_missing_half_hours(model, column_name) %}

with bounds as (
    select min({{ column_name }}) as first_slot,
           max({{ column_name }}) as last_slot
    from {{ model }}
),
expected as (
    select first_slot + toIntervalMinute(number * 30) as slot
    from bounds
    array join range(toUInt64(dateDiff('minute', first_slot, last_slot) / 30) + 1) as number
)
select e.slot as missing_slot
from expected as e
left anti join (select {{ column_name }} as slot from {{ model }}) as m using slot

{% endtest %}
