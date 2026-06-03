"""Backend tests for the new /admin2 stats endpoints.

Covers:
- /api/admin/login auth bootstrap
- /api/admin2/stats-overview (no-token, token, ?category, ?force, perf, internal consistency)
- /api/admin2/backfill
- /api/admin2/memory (with bounds validation)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://analytics-fix-32.preview.emergentagent.com").rstrip("/")
ADMIN_PASSWORD = "papersumo2025"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    token = data.get("token")
    assert token and isinstance(token, str) and len(token) > 5, f"no token in response: {data}"
    return token


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"X-Admin-Token": admin_token, "Content-Type": "application/json"}


# ─────────── auth ───────────
class TestAdminLogin:
    def test_login_returns_token(self, admin_token):
        assert admin_token

    def test_login_wrong_password(self, api):
        r = api.post(f"{BASE_URL}/api/admin/login", json={"password": "wrong-password-xyz"}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"


# ─────────── stats-overview ───────────
class TestStatsOverview:
    def test_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview", timeout=15)
        assert r.status_code == 401, f"expected 401 without token, got {r.status_code}"

    def test_invalid_token_rejected(self, api):
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview",
                    headers={"X-Admin-Token": "bogus-token-xyz"}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 with bad token, got {r.status_code}"

    def test_returns_full_payload_under_10s(self, api, auth_headers):
        t0 = time.time()
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview", headers=auth_headers, timeout=15)
        dt = time.time() - t0
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        assert dt < 10.0, f"response took {dt:.2f}s — must be <10s"
        data = r.json()
        # required keys
        for k in ("summary", "series", "categories", "match_models", "summary_models",
                  "user_registrations", "backfilling", "data_complete", "refreshed_at"):
            assert k in data, f"missing key {k!r} in payload"
        # series non-empty + key shape
        assert isinstance(data["series"], list) and len(data["series"]) > 0, "series empty"
        first = data["series"][0]
        for sk in ("date", "papers_cumulative", "matches_cumulative", "tokens_cumulative",
                   "cost_cumulative", "match_cost_cumulative", "summary_cost_cumulative"):
            assert sk in first, f"series entry missing {sk!r}: {list(first.keys())[:15]}"
        # at least one per-category cumulative key
        per_cat = [k for k in first if k.startswith("papers_cumulative_") and k != "papers_cumulative"]
        assert per_cat, f"no per-category papers_cumulative_<cat> keys; sample: {list(first.keys())[:25]}"

    def test_internal_cost_consistency(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        s = data["summary"]
        mm_sum = round(sum(m.get("cost", 0) for m in data["match_models"]), 2)
        sm_sum = round(sum(m.get("cost", 0) for m in data["summary_models"]), 2)
        # 1% relative tolerance (or $1 absolute for low totals)
        def close(a, b, tol_rel=0.01, tol_abs=1.0):
            return abs(a - b) <= max(tol_abs, tol_rel * max(abs(a), abs(b), 1.0))
        assert close(s["match_cost"], mm_sum), f"match_cost {s['match_cost']} vs sum(match_models)={mm_sum}"
        assert close(s["summary_cost"], sm_sum), f"summary_cost {s['summary_cost']} vs sum(summary_models)={sm_sum}"
        assert close(s["total_cost"], s["match_cost"] + s["summary_cost"], tol_rel=0.005), \
            f"total_cost {s['total_cost']} != match+summary {s['match_cost'] + s['summary_cost']}"

    def test_category_filter(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview", params={"category": "cs.AI"},
                    headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert isinstance(data.get("series"), list) and len(data["series"]) > 0

    def test_force_param_kicks_backfill_fast(self, api, auth_headers):
        t0 = time.time()
        r = api.get(f"{BASE_URL}/api/admin2/stats-overview", params={"force": "true"},
                    headers=auth_headers, timeout=15)
        dt = time.time() - t0
        assert r.status_code == 200
        assert dt < 10.0, f"force=true should NOT block; took {dt:.2f}s"
        data = r.json()
        assert data.get("backfilling") is True, f"expected backfilling=True; got {data.get('backfilling')}"


# ─────────── backfill ───────────
class TestBackfillEndpoint:
    def test_backfill_started(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/admin2/backfill", headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data.get("started") is True
        assert "already_running" in data

    def test_backfill_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/admin2/backfill", timeout=15)
        assert r.status_code == 401


# ─────────── memory ───────────
class TestMemoryEndpoint:
    @pytest.mark.parametrize("hours", [6, 24, 168])
    def test_valid_hours(self, api, auth_headers, hours):
        r = api.get(f"{BASE_URL}/api/admin2/memory", params={"hours": hours},
                    headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"hours={hours}: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data.get("hours") == hours
        assert isinstance(data.get("points"), list)
        if data["points"]:
            p = data["points"][0]
            for k in ("ts", "rss_mb", "pod_role"):
                assert k in p, f"missing memory point key {k!r}"

    def test_hours_zero_rejected(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin2/memory", params={"hours": 0},
                    headers=auth_headers, timeout=15)
        assert r.status_code == 422, f"hours=0 should 422, got {r.status_code}"

    def test_hours_over_max_rejected(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/admin2/memory", params={"hours": 200},
                    headers=auth_headers, timeout=15)
        assert r.status_code == 422, f"hours=200 should 422, got {r.status_code}"

    def test_memory_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/admin2/memory", timeout=15)
        assert r.status_code == 401
