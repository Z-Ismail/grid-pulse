"""Backfill / incremental load of carbon intensity into ClickHouse.

Usage:
    python -m ingest.batch.load_carbon_intensity --start 2026-11-01 --end 2026-11-14

Writes only to raw_carbon_intensity (append-only history). The materialised view
copies each insert into carbon_intensity_latest.

Idempotency:
  - windows are fixed and half-open [start, end), split into <=14-day chunks
  - each slot is assigned to exactly one chunk (filter in fetch_intensity)
  - re-running appends a new version; 'latest' keeps the newest per slot
"""

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone

import clickhouse_connect
from dotenv import load_dotenv

from ingest.batch.carbon_intensity import MAX_WINDOW, fetch_intensity

log = logging.getLogger(__name__)

COLUMNS = ["period_start", "period_end", "forecast", "actual", "intensity_idx", "ingested_at"]


def chunk_windows(start: datetime, end: datetime, size: timedelta = MAX_WINDOW):
    """Yield back-to-back half-open windows [a, b) covering [start, end)."""
    cursor = start
    while cursor < end:
        nxt = min(cursor + size, end)
        yield cursor, nxt
        cursor = nxt


def get_client():
    load_dotenv()
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "grid"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "grid"),
        database=os.getenv("CLICKHOUSE_DB", "grid_pulse"),
    )


def load(start: datetime, end: datetime) -> int:
    client = get_client()
    total = 0
    for a, b in chunk_windows(start, end):
        rows = fetch_intensity(a, b)
        ingested_at = datetime.now(timezone.utc)  # one version stamp per chunk
        data = [
            [r["period_start"], r["period_end"], r["forecast"], r["actual"], r["index"], ingested_at]
            for r in rows
        ]
        if data:
            client.insert("raw_carbon_intensity", data, column_names=COLUMNS)
        log.info("chunk %s -> %s: %d rows", a, b, len(data))
        total += len(data)
    return total


def _parse_day(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", required=True, type=_parse_day, help="YYYY-MM-DD (inclusive, UTC)")
    p.add_argument("--end", required=True, type=_parse_day, help="YYYY-MM-DD (exclusive, UTC)")
    args = p.parse_args()
    n = load(args.start, args.end)
    log.info("done: %d rows loaded", n)
