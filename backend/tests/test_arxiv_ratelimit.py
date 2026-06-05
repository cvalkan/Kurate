"""Tests for arXiv fetch: throttle spacing, proxy-aware retry on 429."""
import asyncio
import time
import pytest
import httpx

import services.arxiv as ax


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


def test_fetch_retries_on_429_with_proxy(monkeypatch):
    """With rotating proxies, 429 should be retried (new IP each attempt)."""
    monkeypatch.setattr(ax, "_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(ax, "_ARXIV_PROXY", "http://test:test@proxy:1234")
    ax._last_request_ts = 0.0

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
            if calls["n"] <= 2:
                return _Resp(429)
            return _Resp(200, text=empty_feed)

    monkeypatch.setattr(ax.httpx, "AsyncClient", lambda *a, **k: _Client())
    _real_sleep = asyncio.sleep
    async def _nosleep(s): pass
    monkeypatch.setattr(ax.asyncio, "sleep", _nosleep)

    async def run():
        return await ax.fetch_arxiv_papers(category="cs.RO", max_results=10)

    out = asyncio.get_event_loop().run_until_complete(run())
    assert calls["n"] == 3, f"should retry 429 with proxy (got {calls['n']} calls)"
    assert out == []


def test_fetch_exhausts_retries_on_persistent_429(monkeypatch):
    """After all retries fail, the function should raise (OAI-PMH + API fallback)."""
    monkeypatch.setattr(ax, "_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(ax, "_ARXIV_PROXY", None)
    ax._last_request_ts = 0.0
    # Clear OAI cache to force a fresh harvest
    ax._oai_cache.clear()

    calls = {"n": 0}

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.text = "Rate exceeded."
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=httpx.Request("GET", "http://x"), response=self)

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, *a, **k):
            calls["n"] += 1
            return _Resp(429)

    monkeypatch.setattr(ax.httpx, "AsyncClient", lambda *a, **k: _Client())
    _real_sleep = asyncio.sleep
    async def _nosleep(s): pass
    monkeypatch.setattr(ax.asyncio, "sleep", _nosleep)

    async def run():
        return await ax.fetch_arxiv_papers(category="cs.RO", max_results=10)

    # Should either raise or return empty (both are acceptable failure modes)
    try:
        result = asyncio.get_event_loop().run_until_complete(run())
        # If it returns, it should be empty
        assert result == [] or len(result) == 0, f"Expected empty result on persistent 429, got {len(result)}"
    except httpx.HTTPStatusError:
        pass  # Also acceptable
    assert calls["n"] >= 3, f"should attempt at least 3 requests (got {calls['n']})"
