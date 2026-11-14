-- Daily GB carbon intensity summary and National Grid forecast error.
--
-- Incremental with a lookback: each run deletes and recomputes the last
-- `lookback_days` days, so late revisions (forecast -> actual) are picked up
-- instead of leaving stale numbers. Older days are left untouched.
{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='day',
        order_by='day',
        engine='MergeTree()'
    )
}}

{% set lookback_days = var('lookback_days', 3) %}

select
    toDate(period_start)                                          as day,
    count()                                                       as slots,
    count() = 48                                                  as is_complete,
    round(avg(forecast_gco2_kwh), 1)                              as avg_forecast_gco2_kwh,
    round(avg(actual_gco2_kwh), 1)                                as avg_actual_gco2_kwh,
    min(actual_gco2_kwh)                                          as min_actual_gco2_kwh,
    max(actual_gco2_kwh)                                          as max_actual_gco2_kwh,
    argMax(period_start, actual_gco2_kwh)                         as dirtiest_slot,
    argMin(period_start, actual_gco2_kwh)                         as cleanest_slot,
    round(avg(abs(forecast_gco2_kwh - actual_gco2_kwh)), 1)       as forecast_mae_gco2_kwh,
    round(avg(forecast_gco2_kwh - actual_gco2_kwh), 1)            as forecast_bias_gco2_kwh,
    max(last_ingested_at)                                         as last_ingested_at
from {{ ref('stg_carbon_intensity') }}
{% if is_incremental() %}
where toDate(period_start) >= (select max(day) from {{ this }}) - {{ lookback_days }}
{% endif %}
group by day
