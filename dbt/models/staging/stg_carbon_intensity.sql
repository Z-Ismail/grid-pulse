-- One row per half-hour slot, newest version.
-- argMax(col, ingested_at) picks each column's value from the newest version, so this
-- is correct even before ClickHouse has merged duplicates (no FINAL needed).
select
    period_start,
    argMax(period_end,    ingested_at) as period_end,
    argMax(forecast,      ingested_at) as forecast_gco2_kwh,
    argMax(actual,        ingested_at) as actual_gco2_kwh,
    argMax(intensity_idx, ingested_at) as intensity_index,
    max(ingested_at)                   as last_ingested_at
from {{ source('grid_pulse', 'carbon_intensity_latest') }}
group by period_start
