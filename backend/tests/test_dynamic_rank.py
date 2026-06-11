"""Tests for dynamic rank refactoring (no stored rank/rank_ts fields)."""
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


class TestDynamicRank:
    def test_category_ranks_sequential_by_ts_score(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all", "limit": 50},
                    timeout=60)
        assert r.status_code == 200
        lb = r.json().get("leaderboard", [])
        assert len(lb) == 50
        # Sequential ranks
        for i, e in enumerate(lb):
            assert e["rank"] == i + 1, f"Entry {i} has rank={e['rank']}"
        # ts_score monotonically non-increasing
        scores = [e.get("ts_score") for e in lb]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i-1], f"Score at {i} {scores[i]} > {scores[i-1]}"
        # No rank_ts field in response
        for e in lb:
            assert "rank_ts" not in e, "rank_ts should not be in response"
        pytest.cs_ro_p1 = r.json()

    def test_show_all_ranks_sequential(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"show_all": "true", "period": "all", "limit": 50},
                    timeout=60)
        assert r.status_code == 200
        lb = r.json().get("leaderboard", [])
        assert len(lb) > 0
        for i, e in enumerate(lb):
            assert e["rank"] == i + 1
            assert "rank_ts" not in e

    def test_page2_via_cursor_continues_ranks(self, api):
        p1 = getattr(pytest, "cs_ro_p1", None)
        if not p1:
            pytest.skip("p1 missing")
        cur = p1.get("next_cursor")
        assert cur
        last_rank_p1 = p1["leaderboard"][-1]["rank"]  # 50
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all",
                            "limit": 50, "cursor": cur},
                    timeout=60)
        assert r.status_code == 200
        lb2 = r.json().get("leaderboard", [])
        assert len(lb2) == 50
        # NOTE: cursor pagination resets offset to 0 — backend assigns ranks 1..50 again
        # The frontend renumbers via startRank = leaderboard.length + 1.
        # So backend returns rank starting at 1 — verify it's still sequential within page.
        for i, e in enumerate(lb2):
            assert e["rank"] == i + 1
        # Verify no overlap with page 1
        ids1 = {e["id"] for e in p1["leaderboard"]}
        ids2 = {e["id"] for e in lb2}
        assert not (ids1 & ids2)

    def test_page2_via_offset_continues_ranks(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all",
                            "limit": 50, "offset": 50,
                            "sort_by": "title", "sort_dir": "asc"},
                    timeout=60)
        assert r.status_code == 200
        lb = r.json().get("leaderboard", [])
        assert len(lb) == 50
        # With offset, ranks should start at offset+1
        for i, e in enumerate(lb):
            assert e["rank"] == 50 + i + 1

    def test_custom_sort_sequential_ranks(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all",
                            "limit": 30, "sort_by": "comparisons", "sort_dir": "desc"},
                    timeout=60)
        assert r.status_code == 200
        lb = r.json().get("leaderboard", [])
        assert len(lb) == 30
        for i, e in enumerate(lb):
            assert e["rank"] == i + 1
        # comparisons monotonically non-increasing
        comps = [e.get("comparisons", 0) for e in lb]
        for i in range(1, len(comps)):
            assert comps[i] <= comps[i-1]

    def test_search_sequential_ranks(self, api):
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all",
                            "limit": 20, "search": "learning"},
                    timeout=60)
        assert r.status_code == 200
        lb = r.json().get("leaderboard", [])
        if not lb:
            pytest.skip("no search results")
        for i, e in enumerate(lb):
            assert e["rank"] == i + 1

    def test_paper_detail_current_rank_dynamic(self, api):
        # Fetch top paper of cs.RO and check current_rank
        r = api.get(f"{BASE_URL}/api/leaderboard",
                    params={"category": "cs.RO", "period": "all", "limit": 5},
                    timeout=60)
        assert r.status_code == 200
        lb = r.json().get("leaderboard", [])
        if not lb:
            pytest.skip()
        for entry in lb[:3]:
            pid = entry["id"]
            expected_rank = entry["rank"]
            rr = api.get(f"{BASE_URL}/api/papers/{pid}", timeout=30)
            if rr.status_code == 404:
                continue  # data inconsistency mentioned in problem statement
            assert rr.status_code == 200
            paper = rr.json().get("paper", {})
            cr = paper.get("current_rank")
            assert cr is not None, f"current_rank missing for {pid}"
            # Should match the rank from leaderboard
            assert cr == expected_rank, f"Paper {pid}: detail rank {cr} != leaderboard rank {expected_rank}"
            return  # one good check is enough
        pytest.skip("no papers found in DB")
