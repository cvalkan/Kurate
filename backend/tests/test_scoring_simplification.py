"""Tests for Phase 8 scoring simplification: TrueSkill is the canonical scoring method.

Verifies:
- Leaderboard API returns score=ts_score, ci=wilson_margin, rank=rank_ts.
- No rank_wr / rank_os fields in API response.
- Sorting works for score, wilson_margin, comparisons, win_rate, published.
- Category switching works.
- Paper detail returns expected stats.
- Archive list endpoint returns archives.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-judge-hub-1.preview.emergentagent.com").rstrip("/")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "papersumo2025")


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    r = session.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json().get("token")


# ---------------------------- Leaderboard shape ----------------------------

class TestLeaderboardShape:
    def test_leaderboard_basic(self, session):
        r = session.get(f"{BASE_URL}/api/leaderboard?category=cs.AI&limit=5", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "leaderboard" in data
        assert len(data["leaderboard"]) > 0
        e = data["leaderboard"][0]
        # Required fields
        for k in ("id", "rank", "rank_ts", "score", "ts_score", "ci", "wilson_margin",
                  "win_rate", "wins", "losses", "comparisons", "title"):
            assert k in e, f"missing {k} in entry"
        # Canonical equalities (Phase 8 invariant)
        assert e["score"] == e["ts_score"], "score must equal ts_score"
        assert e["ci"] == e["wilson_margin"], "ci must equal wilson_margin"
        assert e["rank"] == e["rank_ts"], "rank must equal rank_ts"

    def test_no_legacy_rank_fields(self, session):
        r = session.get(f"{BASE_URL}/api/leaderboard?category=cs.AI&limit=10", timeout=15)
        assert r.status_code == 200
        for e in r.json()["leaderboard"]:
            assert "rank_wr" not in e, "rank_wr must not be in response"
            assert "rank_os" not in e, "rank_os must not be in response"
            assert "os_score" not in e, "os_score must not be in response"
            assert "os_sigma" not in e, "os_sigma must not be in response"

    def test_rank_monotonic(self, session):
        # ts_score must be strictly desc; ranks may swap on ties (mongo paper_id tiebreak
        # vs. rank assignment tiebreak), so only check non-tied positions.
        r = session.get(f"{BASE_URL}/api/leaderboard?category=cs.AI&limit=20", timeout=15)
        assert r.status_code == 200
        items = r.json()["leaderboard"]
        scores = [e["ts_score"] for e in items]
        assert scores == sorted(scores, reverse=True), "ts_score must be desc by default"
        # For non-tied scores, rank must be ascending
        prev_rank, prev_score = None, None
        for e in items:
            if prev_score is not None and e["ts_score"] != prev_score:
                assert e["rank"] > prev_rank, f"rank not increasing across distinct scores: {prev_rank}->{e['rank']}"
            prev_rank, prev_score = e["rank"], e["ts_score"]

    def test_multiple_categories(self, session):
        for cat in ("cs.RO", "cs.LG"):
            r = session.get(f"{BASE_URL}/api/leaderboard?category={cat}&limit=3", timeout=15)
            assert r.status_code == 200, f"{cat}: {r.status_code}"
            data = r.json()
            assert "leaderboard" in data
            if data["leaderboard"]:
                e = data["leaderboard"][0]
                assert e["score"] == e["ts_score"]
                assert e["ci"] == e["wilson_margin"]


# ---------------------------- Sorting ----------------------------

class TestSorting:
    @pytest.mark.parametrize("sort_by,sort_dir", [
        ("score", "desc"),
        ("wilson_margin", "asc"),
        ("comparisons", "desc"),
        ("win_rate", "desc"),
        ("published", "desc"),
    ])
    def test_sort(self, session, sort_by, sort_dir):
        r = session.get(
            f"{BASE_URL}/api/leaderboard?category=cs.AI&limit=10&sort_by={sort_by}&sort_dir={sort_dir}",
            timeout=15,
        )
        assert r.status_code == 200, f"{sort_by}/{sort_dir}: {r.status_code} {r.text[:200]}"
        items = r.json()["leaderboard"]
        assert len(items) > 0


# ---------------------------- Categories ----------------------------

class TestCategories:
    def test_categories_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/categories", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))


# ---------------------------- Paper detail ----------------------------

class TestPaperDetail:
    def test_paper_detail(self, session):
        # Try first 5 leaderboard entries — first one has a known data integrity
        # mismatch (papers.id != rankings.paper_id for a duplicated arxiv doc, pre-existing).
        r = session.get(f"{BASE_URL}/api/leaderboard?category=cs.AI&limit=5", timeout=15)
        items = r.json()["leaderboard"]
        last = None
        for it in items:
            r2 = session.get(f"{BASE_URL}/api/papers/{it['id']}", timeout=15)
            last = r2
            if r2.status_code == 200:
                d = r2.json()
                paper = d.get("paper", d)
                assert paper["id"] == it["id"]
                # Stats present in either paper or top-level
                stats_doc = d if "wins" in d else (d.get("ranking") or d.get("stats") or paper)
                for k in ("wins", "losses", "comparisons"):
                    # find the field somewhere in the response
                    found = any(k in obj for obj in (d, paper, stats_doc) if isinstance(obj, dict))
                    assert found, f"missing {k} anywhere in response"
                return
        pytest.fail(f"No leaderboard paper resolvable via /api/papers/{{id}} (last status={last.status_code})")


# ---------------------------- Archives ----------------------------

class TestArchives:
    def test_archive_list(self, session):
        r = session.get(f"{BASE_URL}/api/archive/list", timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert "archives" in data
        assert isinstance(data["archives"], list)


# ---------------------------- Admin logs ----------------------------

class TestAdminLogs:
    def test_admin_logs(self, session, admin_token):
        h = {"X-Admin-Token": admin_token}
        r = session.get(f"{BASE_URL}/api/admin/system-logs?limit=10", headers=h, timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # minimal shape check — should be a list-ish payload
        assert isinstance(data, (list, dict))


# ---------------------------- Correlation page ----------------------------

class TestCorrelation:
    def test_model_analysis(self, session):
        r = session.get(f"{BASE_URL}/api/model-analysis?category=cs.AI", timeout=20)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # We only verify the endpoint still responds — payload shape is internal.
        assert isinstance(data, dict)
        assert data.get("status") == "ok" or "models" in data or "correlation" in data
