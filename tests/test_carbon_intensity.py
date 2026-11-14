"""Unit tests for the carbon intensity fetcher and loader (no network, no database)."""

from datetime import UTC, datetime, timedelta

import pytest
import requests

from ingest.batch import carbon_intensity as ci
from ingest.batch.load_carbon_intensity import chunk_windows

UTC = UTC


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def slot(start: str, end: str, forecast=100, actual=None):
    return {"from": start, "to": end,
            "intensity": {"forecast": forecast, "actual": actual, "index": "low"}}


def test_parse_utc_is_timezone_aware():
    dt = ci._parse_utc("2026-07-01T12:00Z")
    assert dt.tzinfo is not None and dt.utcoffset() == timedelta(0)
    assert dt.hour == 12  # must NOT be shifted to local time


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        ci.fetch_intensity(datetime(2026, 7, 1), datetime(2026, 7, 2))


def test_window_over_14_days_is_rejected():
    s = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="exceeds API limit"):
        ci.fetch_intensity(s, s + timedelta(days=15))


def test_half_open_filter_drops_extra_leading_slot(monkeypatch):
    payload = {"data": [
        slot("2026-11-12T23:30Z", "2026-11-13T00:00Z"),  # API's extra slot before start
        slot("2026-11-13T00:00Z", "2026-11-13T00:30Z"),
        slot("2026-11-13T00:30Z", "2026-11-13T01:00Z"),
    ]}
    monkeypatch.setattr(ci, "_get_with_retries", lambda url: FakeResponse(payload))
    s = datetime(2026, 11, 13, tzinfo=UTC)
    rows = ci.fetch_intensity(s, s + timedelta(hours=1))
    assert [r["period_start"].strftime("%H:%M") for r in rows] == ["00:00", "00:30"]


def test_missing_actual_becomes_none(monkeypatch):
    payload = {"data": [{"from": "2026-11-13T00:00Z", "to": "2026-11-13T00:30Z",
                         "intensity": {"forecast": 120, "index": "moderate"}}]}
    monkeypatch.setattr(ci, "_get_with_retries", lambda url: FakeResponse(payload))
    s = datetime(2026, 11, 13, tzinfo=UTC)
    rows = ci.fetch_intensity(s, s + timedelta(minutes=30))
    assert rows[0]["actual"] is None


def test_dst_night_keeps_all_utc_slots(monkeypatch):
    """Regression: 2026-10-25 (UK clocks go back) must yield distinct 01:00 and 01:30 UTC slots."""
    times = ["00:00", "00:30", "01:00", "01:30", "02:00"]
    payload = {"data": [slot(f"2026-10-25T{a}Z", f"2026-10-25T{b}Z")
                        for a, b in zip(times, times[1:] + ["02:30"], strict=True)]}
    monkeypatch.setattr(ci, "_get_with_retries", lambda url: FakeResponse(payload))
    s = datetime(2026, 10, 25, tzinfo=UTC)
    rows = ci.fetch_intensity(s, s + timedelta(hours=2, minutes=30))
    starts = [r["period_start"] for r in rows]
    assert len(starts) == len(set(starts)) == 5


def test_chunk_windows_cover_range_without_gaps_or_overlap():
    s = datetime(2025, 11, 1, tzinfo=UTC)
    e = datetime(2026, 11, 14, tzinfo=UTC)
    windows = list(chunk_windows(s, e))
    assert windows[0][0] == s and windows[-1][1] == e
    assert all(b == next_a for (_, b), (next_a, _) in zip(windows, windows[1:], strict=False))
    assert all(b - a <= timedelta(days=14) for a, b in windows)


def test_4xx_fails_fast_without_retry(monkeypatch):
    calls = []
    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse({}, status=400)
    monkeypatch.setattr(ci.requests, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        ci._get_with_retries("http://x")
    assert len(calls) == 1


def test_503_retries_then_raises(monkeypatch):
    calls = []
    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse({}, status=503)
    monkeypatch.setattr(ci.requests, "get", fake_get)
    monkeypatch.setattr(ci.time, "sleep", lambda s: None)  # don't actually wait
    with pytest.raises(requests.HTTPError):
        ci._get_with_retries("http://x")
    assert len(calls) == ci.MAX_ATTEMPTS
