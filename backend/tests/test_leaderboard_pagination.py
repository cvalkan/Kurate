"""Tests for keyset cursor pagination + active-category total_papers fix."""
import os
import pytest
import requests
from pathlib import Path


def _load_backend_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if url:
        return url.rstrip('/')
    env_file = Path('/app/frontend/.env')
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith('REACT_APP_BACKEND_URL='):
                return line.split('=', 1)[1].strip().rstrip('/')
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_backend_url()


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- Category leaderboard cursor pagination ---

class TestCategoryCursorPagination:
    def test_initial_load_returns_cursor(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all", "limit": 200},
                    timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        lb = d.get("leaderboard", [])
        # cs.RO has ~2500 papers, expect full 200 page
        assert len(lb) == 200, f"Expected 200 entries, got {len(lb)}"
        assert d.get("next_cursor"), "Initial cs.RO load should provide next_cursor"
        # Save cursor for chain test via class attribute trick
        pytest.cs_ro_page1 = d

    def test_cursor_pagination_chain(self, api):
        page1 = getattr(pytest, "cs_ro_page1", None)
        if not page1:
            pytest.skip("page1 not available")
        cursor = page1["next_cursor"]
        ids_p1 = {e["id"] for e in page1["leaderboard"]}
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all",
                            "limit": 200, "cursor": cursor},
                    timeout=60)
        assert r.status_code == 200
        d = r.json()
        lb = d.get("leaderboard", [])
        assert len(lb) == 200, f"Page 2: expected 200, got {len(lb)}"
        ids_p2 = {e["id"] for e in lb}
        overlap = ids_p1 & ids_p2
        assert not overlap, f"Page 2 overlaps page 1 by {len(overlap)} entries"
        # Should still have a next_cursor (cs.RO ~2500 papers)
        assert d.get("next_cursor"), "Page 2 should have next_cursor for cs.RO"
        # Verify ts_scores monotonically non-increasing across boundary
        last_p1_score = page1["leaderboard"][-1].get("ts_score")
        first_p2_score = lb[0].get("ts_score")
        if last_p1_score is not None and first_p2_score is not None:
            assert first_p2_score <= last_p1_score, \
                f"Page 2 first score {first_p2_score} > page 1 last {last_p1_score}"

    def test_offset_fallback_when_custom_sort(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all",
                            "limit": 200, "sort_by": "title", "sort_dir": "asc"},
                    timeout=60)
        assert r.status_code == 200
        d = r.json()
        # Title-sorted should NOT offer keyset cursor
        assert d.get("next_cursor") in (None, ""), \
            f"Custom sort should not provide next_cursor, got {d.get('next_cursor')}"
        # But offset pagination should still work
        r2 = api.get(f"{BASE_URL}/api/leaderboard",
                     params={"category": "cs.RO", "period": "all",
                             "limit": 200, "offset": 200,
                             "sort_by": "title", "sort_dir": "asc"},
                     timeout=60)
        assert r2.status_code == 200
        d2 = r2.json()
        assert len(d2.get("leaderboard", [])) > 0, "Offset fallback returned no entries"
        # Verify no overlap between offset=0 and offset=200
        ids1 = {e["id"] for e in d["leaderboard"]}
        ids2 = {e["id"] for e in d2["leaderboard"]}
        assert not (ids1 & ids2), "Offset pagination should produce non-overlapping pages"


# --- Show All Papers active-category filter ---

class TestShowAllActiveCategories:
    def test_show_all_excludes_inactive_categories(self, api):
        # Get active categories from /api/categories
        cr = api.get(f"{BASE_URL}/api/categories", timeout=30)
        assert cr.status_code == 200
        cats_data = cr.json()
        active_ids = {c["id"] for c in cats_data.get("categories", [])}
        assert active_ids, "No active categories returned"
        # q-fin.CP should NOT be in active list per request
        assert "q-fin.CP" not in active_ids, \
            "Test premise broken: q-fin.CP appears active in /api/categories"

        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"show_all": "true", "period": "all", "limit": 200},
                    timeout=60)
        assert r.status_code == 200
        d = r.json()
        lb = d.get("leaderboard", [])
        assert len(lb) > 0, "show_all returned empty"
        # No entry should be from inactive q-fin.CP
        offenders = [e for e in lb if e.get("primary_category") == "q-fin.CP"]
        assert not offenders, f"Found {len(offenders)} q-fin.CP entries in show_all"
        # All categories should be active
        seen_cats = {e.get("primary_category") for e in lb if e.get("primary_category")}
        inactive_seen = seen_cats - active_ids
        assert not inactive_seen, f"show_all included inactive categories: {inactive_seen}"
        pytest.show_all_page1 = d

    def test_show_all_total_papers_matches_active_only(self, api):
        d = getattr(pytest, "show_all_page1", None)
        if not d:
            pytest.skip("show_all page 1 not available")
        total_papers = d.get("total_papers", 0)
        # Compute expected total from active categories
        cr = api.get(f"{BASE_URL}/api/categories", timeout=30)
        active_ids = [c["id"] for c in cr.json().get("categories", [])]
        expected = 0
        for cat in active_ids:
            rr = api.get(f"{BASE_URL}/api/leaderboard",
                         params={"category": cat, "period": "all", "limit": 1},
                         timeout=60)
            if rr.status_code == 200:
                expected += rr.json().get("total_papers", 0)
        # Allow some tolerance for race conditions
        assert abs(total_papers - expected) < max(50, expected * 0.02), \
            f"show_all total_papers={total_papers} but active-cat sum={expected}"

    def test_show_all_cursor_pagination(self, api):
        d = getattr(pytest, "show_all_page1", None)
        if not d:
            pytest.skip("show_all page 1 not available")
        cursor = d.get("next_cursor")
        if not cursor:
            pytest.skip("show_all did not provide next_cursor (data set may be small)")
        ids1 = {e["id"] for e in d["leaderboard"]}
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"show_all": "true", "period": "all",
                            "limit": 200, "cursor": cursor},
                    timeout=60)
        assert r.status_code == 200
        d2 = r.json()
        lb2 = d2.get("leaderboard", [])
        assert len(lb2) > 0, "show_all page 2 empty"
        ids2 = {e["id"] for e in lb2}
        assert not (ids1 & ids2), \
            f"show_all page 2 overlaps page 1 by {len(ids1 & ids2)} entries"
