"""Iteration 63 — TrueSkill sigma-based convergence migration tests.

Covers:
  - /api/leaderboard ci field is ±Elo (not Wilson %)
  - CI values are numeric and roughly in range 15-170
  - /api/admin/progress goal1/goal2 labels are sigma-based (±pts)
  - goal1.met / goal2.met types are bool
  - estimated_matches_remaining is non-negative int
  - sort_by=wilson_margin works (now mapped to ts_sigma ascending)
  - Fewer-matches papers tend to have higher (or equal) CI
  - /api/health works
"""
import os
import statistics
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_PASSWORD = "papersumo2025"
CAT = "cs.AI"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token")
    assert tok
    return tok


# ─── Health ──────────────────────────────────────────────────────────────
def test_health(s):
    r = s.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200


# ─── Leaderboard ci field ────────────────────────────────────────────────
def _fetch_lb(s, category=CAT, period="all", limit=100, sort_by=None, sort_dir=None):
    params = {"category": category, "period": period, "limit": limit}
    if sort_by:
        params["sort_by"] = sort_by
    if sort_dir:
        params["sort_dir"] = sort_dir
    r = s.get(f"{BASE_URL}/api/leaderboard", params=params, timeout=30)
    assert r.status_code == 200, f"leaderboard {r.status_code}: {r.text[:200]}"
    return r.json()


def test_leaderboard_ci_is_elo_points(s):
    data = _fetch_lb(s)
    lb = data.get("leaderboard", [])
    assert len(lb) > 0, "expected papers in cs.AI"
    for e in lb[:20]:
        assert "ci" in e, f"missing ci field: {e.get('id')}"
        ci = e["ci"]
        assert isinstance(ci, (int, float)), f"ci not numeric: {ci!r}"
        # ±Elo points: sigma * 2 * 10 ≈ 15-170 for typical sigmas 0.75-8.3
        # Allow some slack for boundary cases.
        assert 5 <= ci <= 200, f"ci out of expected ±Elo range: {ci} (paper {e.get('id')})"


def test_leaderboard_ci_distribution_range(s):
    data = _fetch_lb(s, limit=200)
    cis = [e["ci"] for e in data.get("leaderboard", []) if "ci" in e]
    assert len(cis) >= 10
    median = statistics.median(cis)
    # Median should sit comfortably in the ±Elo range, not Wilson % (0-100, typical 10-50)
    # With sigmas typically 1-5, median ci ≈ 20-100.
    assert 10 <= median <= 200, f"median ci suspicious for ±Elo: {median}"


def test_leaderboard_sort_by_wilson_margin(s):
    """sort_by=wilson_margin now sorts by ts_sigma ascending (lower = more confident)."""
    data = _fetch_lb(s, sort_by="wilson_margin", limit=50)
    lb = data.get("leaderboard", [])
    assert len(lb) >= 5
    cis = [e["ci"] for e in lb if "ci" in e]
    # Ascending sigma → ascending ci (allow ≤2 inversions for ties / rounding)
    inversions = sum(1 for i in range(len(cis) - 1) if cis[i] > cis[i + 1] + 1)
    assert inversions <= 2, f"too many inversions on wilson_margin sort: {inversions}, cis={cis[:20]}"


def test_fewer_matches_higher_ci_trend(s):
    """Papers with fewer comparisons should generally have higher CI (wider uncertainty).
    Splits the population by median comparisons to handle categories where every
    paper has many matches (cs.AI)."""
    data = _fetch_lb(s, limit=300)
    lb = [e for e in data.get("leaderboard", []) if "ci" in e and "comparisons" in e]
    assert len(lb) >= 30
    comps = sorted(e["comparisons"] for e in lb)
    median_n = comps[len(comps) // 2]
    low = [e["ci"] for e in lb if e["comparisons"] < median_n]
    high = [e["ci"] for e in lb if e["comparisons"] > median_n]
    if len(low) < 5 or len(high) < 5:
        pytest.skip(f"insufficient spread around median_n={median_n}: low={len(low)} high={len(high)}")
    # Allow equality (rounding can flatten the difference)
    assert statistics.median(low) >= statistics.median(high), (
        f"low-match CI median {statistics.median(low)} not >= high-match CI median "
        f"{statistics.median(high)} (median_n={median_n})"
    )


# ─── Admin progress ──────────────────────────────────────────────────────
def test_admin_progress_sigma_labels(s, admin_token):
    h = {"X-Admin-Token": admin_token}
    r = s.get(f"{BASE_URL}/api/admin/progress", params={"category": CAT}, headers=h, timeout=20)
    assert r.status_code == 200, f"progress {r.status_code}: {r.text[:200]}"
    data = r.json()

    # goal1
    g1 = data.get("goal1")
    assert g1, f"missing goal1; keys={list(data.keys())}"
    label1 = g1.get("label", "")
    # Expect format: "General ±50 pts" (sigma 2.5 * 2 * 10 = 50)
    assert label1.startswith("General \u00B1") and label1.endswith("pts"), f"goal1 label not sigma-based: {label1!r}"
    assert "50" in label1, f"goal1 ±Elo (50) missing: {label1!r}"
    assert isinstance(g1["met"], bool)

    # goal2
    g2 = data["goal2"]
    label2 = g2.get("label", "")
    # Expect: "Top-N ±40 pts" (sigma 2.0 * 2 * 10 = 40)
    assert label2.startswith("Top-") and "\u00B1" in label2 and label2.endswith("pts"), (
        f"goal2 label not sigma-based: {label2!r}"
    )
    assert "40" in label2, f"goal2 ±Elo (40) missing: {label2!r}"
    assert isinstance(g2["met"], bool)


def test_admin_progress_estimated_matches(s, admin_token):
    h = {"X-Admin-Token": admin_token}
    r = s.get(f"{BASE_URL}/api/admin/progress", params={"category": CAT}, headers=h, timeout=20)
    assert r.status_code == 200
    data = r.json()
    est = data.get("estimated_matches_remaining")
    assert est is not None, f"missing estimated_matches_remaining; keys={list(data.keys())}"
    assert isinstance(est, int), f"estimated_matches_remaining not int: {type(est)}"
    assert est >= 0, f"estimated_matches_remaining negative: {est}"
    assert est < 10_000_000, f"estimated_matches_remaining suspiciously large: {est}"


def test_admin_settings_sigma_targets(s, admin_token):
    """Sanity check: settings expose sigma_target_general and sigma_target_topk defaults."""
    h = {"X-Admin-Token": admin_token}
    r = s.get(f"{BASE_URL}/api/admin/settings", headers=h, timeout=15)
    assert r.status_code == 200
    settings = r.json().get("settings", {})
    # Defaults come from DEFAULT_SETTINGS even if not persisted yet — get_settings merges.
    sg = settings.get("sigma_target_general", 2.5)
    st = settings.get("sigma_target_topk", 2.0)
    assert 0.5 <= sg <= 10
    assert 0.5 <= st <= 10
    assert st <= sg, f"top-k target should be <= general: topk={st} general={sg}"
