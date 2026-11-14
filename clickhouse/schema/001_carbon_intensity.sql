-- Grid Pulse: carbon intensity storage (two layers)
--
-- raw_carbon_intensity     append-only history: every version of every slot, each fetch.
--                          Used for forecast-accuracy analysis, audit and replay.
-- carbon_intensity_latest  one row per half-hour slot, the newest version.
--                          Fed automatically by a materialised view on insert into raw.

CREATE TABLE IF NOT EXISTS grid_pulse.raw_carbon_intensity
(
    period_start  DateTime('UTC'),
    period_end    DateTime('UTC'),
    forecast      Nullable(UInt16),          -- gCO2/kWh
    actual        Nullable(UInt16),          -- gCO2/kWh, null until the slot has happened
    intensity_idx LowCardinality(Nullable(String)),
    ingested_at   DateTime64(3, 'UTC')       -- when we fetched it; acts as the version
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(period_start)
ORDER BY (period_start, ingested_at);

CREATE TABLE IF NOT EXISTS grid_pulse.carbon_intensity_latest
(
    period_start  DateTime('UTC'),
    period_end    DateTime('UTC'),
    forecast      Nullable(UInt16),
    actual        Nullable(UInt16),
    intensity_idx LowCardinality(Nullable(String)),
    ingested_at   DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)     -- keep the row with the highest ingested_at
PARTITION BY toYYYYMM(period_start)
ORDER BY period_start;                       -- the slot identity

CREATE MATERIALIZED VIEW IF NOT EXISTS grid_pulse.mv_carbon_intensity_latest
TO grid_pulse.carbon_intensity_latest
AS SELECT * FROM grid_pulse.raw_carbon_intensity;
