"""Fetch half-hourly GB carbon intensity from the National Grid Carbon Intensity API."""

import logging
import random
import time
from datetime import datetime, timedelta

import requests

log = logging.getLogger(__name__)

API = "https://api.carbonintensity.org.uk"
MAX_WINDOW = timedelta(days=14)
TS_FORMAT = "%Y-%m-%dT%H:%MZ"

MAX_ATTEMPTS = 4
BASE_DELAY_S = 1.0
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _get_with_retries(url: str) -> requests.Response:
    """GET with bounded exponential backoff on transient failures.

    Retries: timeouts, connection errors, 429 and 5xx.
    Fails immediately: other 4xx (our request is wrong; retrying won't help).
    Raises after MAX_ATTEMPTS so the caller (and Airflow) sees a real failure.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=30)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            reason = type(exc).__name__
        else:
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()  # 4xx -> raise now; 2xx -> no-op
                return response
            if attempt == MAX_ATTEMPTS:
                response.raise_for_status()
            reason = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
                log.warning("attempt %d/%d failed (%s); server asked to wait %ss",
                            attempt, MAX_ATTEMPTS, reason, delay)
                time.sleep(delay)
                continue

        # exponential backoff with jitter: ~1s, 2s, 4s (+ up to 0.5s random)
        delay = BASE_DELAY_S * 2 ** (attempt - 1) + random.uniform(0, 0.5)
        log.warning("attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt, MAX_ATTEMPTS, reason, delay)
        time.sleep(delay)

    raise RuntimeError("unreachable")  # loop always returns or raises


def fetch_intensity(start: datetime, end: datetime) -> list[dict]:
    """Return half-hourly intensity for slots with start <= period_start < end (UTC)."""
    if end <= start:
        raise ValueError("end must be after start")
    if end - start > MAX_WINDOW:
        raise ValueError(f"window {end - start} exceeds API limit of {MAX_WINDOW}")

    url = f"{API}/intensity/{start.strftime(TS_FORMAT)}/{end.strftime(TS_FORMAT)}"
    response = _get_with_retries(url)

    rows = []
    for item in response.json().get("data", []):
        period_start = datetime.strptime(item["from"], TS_FORMAT)
        # API returns slots whose END falls in [from, to], so it includes one extra
        # slot before our start. Half-open filter on period_start removes it.
        if not (start <= period_start < end):
            continue
        intensity = item.get("intensity") or {}
        rows.append(
            {
                "period_start": period_start,
                "period_end": datetime.strptime(item["to"], TS_FORMAT),
                "forecast": intensity.get("forecast"),
                "actual": intensity.get("actual"),
                "index": intensity.get("index"),
            }
        )
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = datetime(2026, 11, 13, 0, 0)
    rows = fetch_intensity(s, s + timedelta(hours=2))
    print(len(rows))
    for r in rows:
        print(r)
