"""Fetch half-hourly GB carbon intensity from the National Grid Carbon Intensity API."""

from datetime import datetime, timedelta

import requests

API = "https://api.carbonintensity.org.uk"
MAX_WINDOW = timedelta(days=14)
TS_FORMAT = "%Y-%m-%dT%H:%MZ"


def fetch_intensity(start: datetime, end: datetime) -> list[dict]:
    """Return half-hourly intensity for slots with start <= period_start < end (UTC)."""
    if end <= start:
        raise ValueError("end must be after start")
    if end - start > MAX_WINDOW:
        raise ValueError(f"window {end - start} exceeds API limit of {MAX_WINDOW}")

    url = f"{API}/intensity/{start.strftime(TS_FORMAT)}/{end.strftime(TS_FORMAT)}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

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
    s = datetime(2026, 11, 13, 0, 0)
    rows = fetch_intensity(s, s + timedelta(hours=2))
    print(len(rows))
    for r in rows:
        print(r)
