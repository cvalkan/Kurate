"""Tests for new Follow endpoints + activity follows enrichment.

DO NOT call follow-handle with real handles — that performs a LIVE follow.
We only verify:
  - endpoint exists and is admin-gated (401/403 without token)
  - /activity returns follows[] + counts.follows
  - /medalists candidates have `followed` boolean
  - /discoveries candidates have `followed` boolean
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://kurate-ai-judge.preview.emergentagent.com").rstrip("/")
ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "papersumo2025")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PW})
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"X-Admin-Token": admin_token, "Content-Type": "application/json"}


# ── Auth gating ─────────────────────────────────────────────────────────
class TestAuthGating:
    def test_follow_handle_requires_admin(self):
        r = requests.post(f"{BASE_URL}/api/admin/outreach/follow-handle",
                          json={"handle": "kurateorg", "paper_id": "test_x"})
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"

    def test_unfollow_handle_requires_admin(self):
        r = requests.post(f"{BASE_URL}/api/admin/outreach/unfollow-handle",
                          json={"handle": "kurateorg"})
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_activity_requires_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/outreach/activity")
        assert r.status_code in (401, 403)

    def test_medalists_requires_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/outreach/medalists?period=monthly:2026-3&top_n=3")
        assert r.status_code in (401, 403)


# ── Activity now includes follows[] ─────────────────────────────────────
class TestActivityFollows:
    def test_activity_has_follows_key(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/outreach/activity", headers=admin_headers)
        assert r.status_code == 200, f"activity failed: {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert "quotes" in data, "missing quotes key"
        assert "likes" in data, "missing likes key"
        assert "follows" in data, "missing follows key — feature not deployed"
        assert isinstance(data["follows"], list), "follows must be a list"
        assert "counts" in data
        counts = data["counts"]
        assert "quotes" in counts and "likes" in counts and "follows" in counts, f"counts keys missing: {list(counts.keys())}"
        assert isinstance(counts["follows"], int)


# ── Candidates now have `followed` boolean field ────────────────────────
class TestCandidateFollowedField:
    def test_medalists_candidates_have_followed(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/outreach/medalists?period=monthly:2026-3&top_n=3",
            headers=admin_headers,
        )
        assert r.status_code == 200, f"medalists call failed: {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert "categories" in data
        # Find any candidate across all medalists and verify followed key
        any_candidate_found = False
        for cat in data["categories"]:
            for paper in cat.get("papers", []):
                for c in paper.get("candidates", []):
                    any_candidate_found = True
                    assert "followed" in c, f"candidate missing 'followed' field: {c}"
                    assert isinstance(c["followed"], bool), f"followed must be bool got {type(c['followed'])}"
                    assert "liked" in c, "liked field also expected (regression check)"
                    assert "quote_tweeted" in c, "quote_tweeted field also expected"
        if not any_candidate_found:
            pytest.skip("no candidates in medalists for monthly:2026-3 — cannot verify field")

    def test_discoveries_candidates_have_followed(self, admin_headers):
        # Try a generic recent query that's likely to return data
        r = requests.get(
            f"{BASE_URL}/api/admin/outreach/discoveries?period=all&top_n=10",
            headers=admin_headers,
        )
        assert r.status_code == 200, f"discoveries call failed: {r.status_code}"
        data = r.json()
        if not data.get("papers"):
            pytest.skip("no papers from /discoveries to verify enrichment")
        any_candidate = False
        for paper in data["papers"]:
            for c in paper.get("candidates", []):
                any_candidate = True
                assert "followed" in c, f"candidate missing 'followed' on /discoveries: {c}"
                assert isinstance(c["followed"], bool)
        if not any_candidate:
            pytest.skip("no candidates returned — cannot verify enrichment")


# ── Follow endpoint shape (do NOT actually call live follow) ─────────────
class TestFollowEndpointShape:
    def test_follow_handle_with_empty_handle_returns_400(self, admin_headers):
        """Validate shape/validation without triggering a live follow."""
        r = requests.post(f"{BASE_URL}/api/admin/outreach/follow-handle",
                          headers=admin_headers,
                          json={"handle": "", "paper_id": "test_validation"})
        # Empty handle should fail validation
        assert r.status_code in (400, 422), f"expected 400/422 for empty handle, got {r.status_code}: {r.text[:200]}"
