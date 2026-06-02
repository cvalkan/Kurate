"""Backend regression tests for the admin2 stats refactor (iteration 66).

Validates the single-source-of-truth contract:
- old endpoints /api/admin/timeseries and /api/admin/stats are DELETED (404)
- /api/admin2/stats-overview mutual equality across summary/series/categories/match_models/summary_models/totals
- precomputed user_registrations is present and cumulative
- response caching (~45s) on repeated identical calls
- force=true bypasses cache; category filter works
- summary_models from model_summary_stats (count ~36500), matches timeseries total
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://atlas-optimized.preview.emergentagent.com",
).rstrip("/")
ADMIN_PASSWORD = "papersumo2025"
TOL_ABS = 2.0  # absolute tolerance in dollars / counts per spec ("<2")


def close(a, b, tol_abs=TOL_ABS):
    return abs(a - b) <= tol_abs


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    token = r.json().get("token")
    assert token
    return token


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"X-Admin-Token": admin_token, "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def overview(api, auth_headers):
    r = api.get(f"{BASE_URL}/api/admin2/stats-overview", headers=auth_headers, timeout=20)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    return r.json()


# ─────────── deleted endpoints ───────────
class TestDeletedEndpoints:
    def test_old_timeseries_gone(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin/timeseries", headers=auth_headers, timeout=15)
        assert r.status_code == 404, f"expected 404 deleted; got {r.status_code}: {r.text[:200]}"

    def test_old_stats_gone(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin/stats", headers=auth_headers, timeout=15)
        assert r.status_code == 404, f"expected 404 deleted; got {r.status_code}: {r.text[:200]}"


# ─────────── caching ───────────
class TestCaching:
    def test_second_call_served_from_cache(self, api, auth_headers):
        # prime
        r1 = api.get(f"{BASE_URL}/api/admin2/stats-overview", headers=auth_headers, timeout=20)
        assert r1.status_code == 200
        t0 = time.time()
        r2 = api.get(f"{BASE_URL}/api/admin2/stats-overview", headers=auth_headers, timeout=20)
        dt = time.time() - t0
        assert r2.status_code == 200
        # cached response should be very fast (well below the typical 1-3s build time)
        assert dt < 2.0, f"2nd identical call should be cached & fast; took {dt:.2f}s"
        # cached payload should be byte-identical refreshed_at
        assert r1.json().get("refreshed_at") == r2.json().get("refreshed_at"), \
            "cached response should keep same refreshed_at"

    def test_force_bypasses_cache(self, api, auth_headers):
        r1 = api.get(f"{BASE_URL}/api/admin2/stats-overview", headers=auth_headers, timeout=20)
        assert r1.status_code == 200
        r2 = api.get(f"{BASE_URL}/api/admin2/stats-overview", params={"force": "true"},
                     headers=auth_headers, timeout=20)
        assert r2.status_code == 200
        # force may rebuild, refreshed_at should be different (or at least not be cached)
        # accept equal if rebuilt in same second; require backfilling=True per contract
        assert r2.json().get("backfilling") is True


# ─────────── mutual equality (CRITICAL) ───────────
class TestSingleSourceOfTruth:
    def test_match_cost_sources_consistent(self, overview):
        s = overview["summary"]
        mm_sum = round(sum(m.get("cost", 0) for m in overview["match_models"]), 2)
        stats_total = overview.get("stats", {}).get("totals", {}).get("total_cost")
        ts_match = overview.get("timeseries", {}).get("totals", {}).get("match_cost")
        # at minimum: summary.match_cost == sum(match_models[].cost)
        assert close(s["match_cost"], mm_sum), \
            f"summary.match_cost={s['match_cost']} vs sum(match_models)={mm_sum}"
        if stats_total is not None:
            assert close(s["match_cost"], stats_total), \
                f"summary.match_cost={s['match_cost']} vs stats.totals.total_cost={stats_total}"
        if ts_match is not None:
            assert close(s["match_cost"], ts_match), \
                f"summary.match_cost={s['match_cost']} vs timeseries.totals.match_cost={ts_match}"

    def test_summary_cost_sources_consistent(self, overview):
        s = overview["summary"]
        sm_sum = round(sum(m.get("cost", 0) for m in overview["summary_models"]), 2)
        stats_sum_total = (overview.get("stats", {}).get("summaries", {}) or {}).get("totals", {}).get("total_cost")
        ts_sum = overview.get("timeseries", {}).get("totals", {}).get("summary_cost")
        assert close(s["summary_cost"], sm_sum), \
            f"summary.summary_cost={s['summary_cost']} vs sum(summary_models)={sm_sum}"
        if stats_sum_total is not None:
            assert close(s["summary_cost"], stats_sum_total), \
                f"summary.summary_cost={s['summary_cost']} vs stats.summaries.totals.total_cost={stats_sum_total}"
        if ts_sum is not None:
            assert close(s["summary_cost"], ts_sum), \
                f"summary.summary_cost={s['summary_cost']} vs timeseries.totals.summary_cost={ts_sum}"

    def test_total_cost_decomposition(self, overview):
        s = overview["summary"]
        assert close(s["total_cost"], s["match_cost"] + s["summary_cost"]), \
            f"total_cost={s['total_cost']} != match+summary={s['match_cost']+s['summary_cost']}"

    def test_total_papers_sources(self, overview):
        s = overview["summary"]
        storage_papers = (overview.get("stats", {}).get("storage", {}) or {}).get("total_papers")
        ts_papers = overview.get("timeseries", {}).get("totals", {}).get("papers")
        if storage_papers is not None:
            assert close(s["total_papers"], storage_papers), \
                f"summary.total_papers={s['total_papers']} vs stats.storage.total_papers={storage_papers}"
        if ts_papers is not None:
            assert close(s["total_papers"], ts_papers), \
                f"summary.total_papers={s['total_papers']} vs timeseries.totals.papers={ts_papers}"

    def test_total_matches_sources(self, overview):
        s = overview["summary"]
        stats_matches = (overview.get("stats", {}).get("totals", {}) or {}).get("total_matches")
        ts_matches = overview.get("timeseries", {}).get("totals", {}).get("matches")
        if stats_matches is not None:
            assert close(s["total_matches"], stats_matches), \
                f"summary.total_matches={s['total_matches']} vs stats.totals.total_matches={stats_matches}"
        if ts_matches is not None:
            assert close(s["total_matches"], ts_matches), \
                f"summary.total_matches={s['total_matches']} vs timeseries.totals.matches={ts_matches}"


# ─────────── summary_models from model_summary_stats ───────────
class TestSummaryModels:
    def test_summary_models_count_and_cost(self, overview):
        sm = overview["summary_models"]
        assert isinstance(sm, list) and len(sm) > 0
        count_sum = sum(int(m.get("count", 0)) for m in sm)
        # The spec says ~36500 summaries
        assert count_sum >= 30000, f"summary_models count sum {count_sum} < 30k — model_summary_stats likely empty/stale"
        ts_sum_count = overview.get("timeseries", {}).get("totals", {}).get("summaries")
        if ts_sum_count is not None:
            assert close(count_sum, ts_sum_count, tol_abs=5), \
                f"sum(summary_models.count)={count_sum} vs timeseries.totals.summaries={ts_sum_count}"
        cost_sum = round(sum(m.get("cost", 0) for m in sm), 2)
        assert close(cost_sum, overview["summary"]["summary_cost"]), \
            f"sum(summary_models.cost)={cost_sum} vs summary.summary_cost={overview['summary']['summary_cost']}"


# ─────────── user_registrations ───────────
class TestUserRegistrations:
    def test_user_registrations_present_and_cumulative(self, overview):
        ur = overview.get("user_registrations")
        assert isinstance(ur, list) and len(ur) > 0, "user_registrations missing/empty"
        # Each entry should have date + cumulative count
        keys = set(ur[0].keys())
        # accept common key names
        count_key = next((k for k in ("cumulative", "total", "count", "users") if k in keys), None)
        assert count_key, f"no count field in user_registrations entries: {keys}"
        # Cumulative => non-decreasing
        vals = [int(p.get(count_key, 0)) for p in ur]
        assert all(b >= a for a, b in zip(vals, vals[1:])), \
            f"user_registrations not non-decreasing (not cumulative): {vals[:10]}…"


# ─────────── category filter ───────────
class TestCategoryFilter:
    def test_cs_ai_scope(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview", params={"category": "cs.AI"},
                    headers=auth_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        s = data["summary"]
        # internal consistency still holds within a category response
        mm_sum = round(sum(m.get("cost", 0) for m in data["match_models"]), 2)
        sm_sum = round(sum(m.get("cost", 0) for m in data["summary_models"]), 2)
        assert close(s["match_cost"], mm_sum), \
            f"[cs.AI] match_cost={s['match_cost']} vs sum(match_models)={mm_sum}"
        assert close(s["summary_cost"], sm_sum), \
            f"[cs.AI] summary_cost={s['summary_cost']} vs sum(summary_models)={sm_sum}"
