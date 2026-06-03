"""Tests for the arXiv rate-limit hardening: global throttle (P1), exponential
back-off + Retry-After (P2)."""
import asyncio
import time
import pytest
import httpx

import services.arxiv as ax


def test_parse_retry_after_numeric():
    r = httpx.Response(429, headers={"Retry-After": "42"})
    assert ax._parse_retry_after(r) == 42.0


def test_parse_retry_after_missing():
    r = httpx.Response(429)
    assert ax._parse_retry_after(r) is None


def test_throttle_enforces_spacing(monkeypatch):
    """Concurrent callers are paced >= _MIN_INTERVAL apart and served FIFO."""
    monkeypatch.setattr(ax, "_MIN_INTERVAL", 0.25)
    ax._last_request_ts = 0.0
    stamps = []

    async def worker():
        await ax._throttle()
        stamps.append(time.monotonic())

    async def run():
        await asyncio.gather(*[worker() for _ in range(4)])

    asyncio.get_event_loop().run_until_complete(run())
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    assert all(g >= 0.24 for g in gaps), f"throttle gaps too small: {gaps}"


def test_fetch_honors_retry_after_then_succeeds(monkeypatch):
    """A 429 with Retry-After backs off for ~that long (not the linear default),
    then the retry succeeds — and the back-off sleep is the requested value."""
    monkeypatch.setattr(ax, "_MIN_INTERVAL", 0.0)
    ax._last_request_ts = 0.0
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ax.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}
    empty_feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    class _Resp:
        def __init__(self, code, text="", headers=None):
            self.status_code = code
            self.text = text
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=httpx.Request("GET", "http://x"), response=self)

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(429, headers={"Retry-After": "7"})
            return _Resp(200, text=empty_feed)

    monkeypatch.setattr(ax.httpx, "AsyncClient", lambda *a, **k: _Client())

    async def run():
        return await ax.fetch_arxiv_papers(category="math.PR", max_results=10)

    out = asyncio.get_event_loop().run_until_complete(run())
    assert calls["n"] == 2, "should retry once after the 429"
    assert any(6.9 <= s <= 8.1 for s in sleeps), f"expected ~7s Retry-After back-off, got {sleeps}"
    assert out == []  # empty feed -> no papers


def test_backoff_minutes_schedule():
    """P0 schedule: 15, 30, 60, 120, capped at 240."""
    sched = [min(240, 15 * (2 ** (n - 1))) for n in range(1, 7)]
    assert sched == [15, 30, 60, 120, 240, 240]
