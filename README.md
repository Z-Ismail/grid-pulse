# Grid Pulse

A GB electricity data platform. It ingests half-hourly carbon intensity from the National Grid (NESO) Carbon Intensity API into ClickHouse, keeps a full version history, and models it with dbt into a daily mart that tracks how accurate the national forecast is.

Planned next, not built yet: streaming generation data from Elexon IRIS, Airflow orchestration and Terraform-managed AWS landing (see [Roadmap](#roadmap)).

## Architecture

```
Carbon Intensity API ──► Python loader ──► ClickHouse
  (half-hourly, UTC)     (chunked,          raw_carbon_intensity      append-only history
                          retries,             │  materialised view (insert trigger)
                          UTC-aware)           ▼
                                            carbon_intensity_latest   ReplacingMergeTree, 1 row/slot
                                               │
                                            dbt: stg_carbon_intensity (argMax dedup)
                                                 fct_carbon_intensity_daily (incremental, 3-day lookback)
                                                 tests: unique, not_null, no_missing_half_hours
```

## Design decisions

| Decision | Why | Trade-off |
| --- | --- | --- |
| **Half-open windows** `[start, end)` on slot start | The API returns every slot whose *end* falls in `[from, to]`, so back-to-back requests overlap by one slot. Filtering on start assigns each slot to exactly one chunk. | Relies on an observed (undocumented) API behaviour; covered by a unit test. |
| **Bounded retries with exponential backoff + jitter** | Retry what is transient (timeouts, 429, 5xx); fail fast on other 4xx; raise after 4 attempts so failures are loud, never an empty "success". | A long outage fails the run rather than waiting it out; the scheduler retries later. |
| **Two storage layers**: append-only history + latest | History keeps every forecast/actual version for audit and forecast-accuracy analysis; latest gives cheap "current truth" reads. | Extra storage. At current volume a plain `argMax` view over history would suffice; the insert-trigger pattern keeps read cost flat as history grows. |
| **ReplacingMergeTree for latest** | Absorbs reruns and forecast→actual revisions without upsert logic. | Deduplication is *eventual* (on merge). Readers use `argMax` in dbt rather than `FINAL`. |
| **Defence in depth on duplicates** | Known duplicates (API boundary overlap) removed at source; unknown ones (retries, reruns) absorbed by the table engine. | — |
| **Incremental mart with lookback** | `delete+insert` keyed on `day`, recomputing the last 3 days each run, so late revisions don't leave stale numbers. | A revision older than the lookback needs `--full-refresh`. |
| **Timezone-aware UTC everywhere** | UTC days always have 48 slots; local time has 46/50 on clock-change days. | Display-time conversion is the consumer's job. |
| **ClickHouse** | Time-series append workload, native revision handling, cheap materialised views. | Overkill for ~18k rows; justified as volume grows (regional data, IRIS datasets, multi-year history). |

## Findings

### 1. A timezone bug, caught by a completeness check
After a one-year backfill (1 Nov 2025 – 14 Nov 2026), the table held **18,142 of 18,144** expected slots. The two missing slots were 01:00 and 01:30 UTC on **25 October 2026**, the night UK clocks went back.

The API was returning them correctly. The cause was in the loader: timestamps were parsed as *naive* datetimes, which the ClickHouse client interpreted in the machine's local timezone (Europe/London). On the ambiguous repeated hour, 01:00 and 01:30 resolved to the first (BST) occurrence and collapsed onto 00:00 and 00:30 UTC. Worse, **every British Summer Time slot had been shifted one hour early**, which a spot check against the API confirmed.

**Fix:** parse API timestamps as timezone-aware UTC, reject naive datetimes at the fetcher boundary, truncate and reload. Guarded by a regression test for the clock-change night and a dbt `no_missing_half_hours` test.

### 2. Forecast error is seasonal and peaks at transitions
From `fct_carbon_intensity_daily`:
- Typical mean absolute forecast error is ~9–10 gCO2/kWh, rising to **12.5 (Aug) and 14.7 (Sep 2026)**.
- **Bias flips with the seasons:** forecasts ran too high in winter (+3.4 in Nov 2025) and too low through spring–autumn (−5.6 in Sep 2026).
- During a sustained high-carbon spell (6–10 Nov 2026, ~240–260 gCO2/kWh) error was *lowest* (~4–5); it rose to 9.5 when the spell broke on 12 Nov.

Hypothesis (to test with generation-mix data): forecast misses are driven by wind under/over-delivery, and they concentrate at weather transitions rather than during steady conditions.

## Running locally

```bash
cp .env.example .env
docker compose up -d
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# create tables
docker exec -i grid-pulse-clickhouse clickhouse-client --user grid --password grid \
  --multiquery < clickhouse/schema/001_carbon_intensity.sql

# load (UTC dates; end is exclusive)
python -m ingest.batch.load_carbon_intensity --start 2025-11-01 --end 2026-11-14

# transform + test
dbt build --project-dir dbt --profiles-dir dbt

# unit tests (no network, no database)
python -m pytest -v
```

## Repository layout

```
ingest/batch/      fetcher (retries, UTC parsing, window filter) and chunked loader
clickhouse/schema/ table + materialised view DDL
dbt/               staging and mart models, generic completeness test
tests/             unit tests incl. DST regression and retry behaviour
```

## Roadmap

- [ ] **Streaming:** Elexon IRIS consumer (generation by fuel, demand) → ClickHouse, as a long-running service with at-least-once delivery and idempotent writes
- [ ] **Orchestration:** Airflow DAG (load → dbt build → freshness check) with a custom operator
- [ ] **Infrastructure:** Terraform for S3 Parquet landing + least-privilege IAM
- [ ] **SLAs:** freshness and completeness targets per data product, with alerting
- [ ] Join intensity with generation mix to test the forecast-error hypothesis
- [x] **CI:** GitHub Actions running ruff, pytest, dbt build and a gitleaks secret scan
