"""Smoke tests for outreach endpoints (admin-gated)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://validation-hub-42.preview.emergentagent.com").rstrip("/")
ADMIN_PASSWORD = "papersumo2025"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    return tok


@pytest.fixture
def admin_headers(admin_token):
    return {"X-Admin-Token": admin_token}


def test_design_preview_route_returns_spa_fallback():
    """The /admin/outreach/design-preview UI route should not exist anymore.
    Since SPA routing handles non-API routes, FastAPI returns 404 (no /admin/* server route),
    which is the expected 'fallback' behaviour at the API layer."""
    r = requests.get(f"{BASE_URL}/admin/outreach/design-preview", timeout=10, allow_redirects=False)
    # Either 404 (not a backend route) or returns the SPA index html (200)
    assert r.status_code in (200, 404)


def test_medalists_endpoint_admin_gated(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/outreach/medalists?period=monthly:2026-3&top_n=3",
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "categories" in body
    assert "period" in body
    assert body["period"] == "monthly:2026-3"


def test_medalists_unauthorized_without_token():
    r = requests.get(f"{BASE_URL}/api/admin/outreach/medalists?period=monthly:2026-3", timeout=10)
    assert r.status_code in (401, 403)


def test_activity_endpoint(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/outreach/activity?limit=10",
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "quotes" in body and "likes" in body and "follows" in body
    assert "counts" in body


def test_discoveries_endpoint(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/outreach/discoveries?period=all&top_n=5",
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "papers" in body
    assert "total" in body


def test_follow_handle_admin_gated_no_token():
    """Verify follow-handle is admin-gated WITHOUT actually following anyone."""
    r = requests.post(f"{BASE_URL}/api/admin/outreach/follow-handle",
                      json={"handle": "fake_unauth_handle_test"}, timeout=10)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_like_tweet_admin_gated_no_token():
    """Verify like-tweet is admin-gated WITHOUT actually liking anything."""
    r = requests.post(f"{BASE_URL}/api/admin/outreach/like-tweet",
                      json={"paper_id": "fake", "tweet_url": "https://x.com/x/status/1", "handle": "x"},
                      timeout=10)
    assert r.status_code in (401, 403)


def test_follow_handle_validates_payload(admin_headers):
    """Empty handle should 400, not actually call X."""
    r = requests.post(f"{BASE_URL}/api/admin/outreach/follow-handle",
                      headers=admin_headers, json={"handle": ""}, timeout=15)
    assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code} {r.text}"


def test_like_tweet_validates_payload(admin_headers):
    """Bad URL should 400, not actually call X."""
    r = requests.post(f"{BASE_URL}/api/admin/outreach/like-tweet",
                      headers=admin_headers,
                      json={"paper_id": "fake", "tweet_url": "https://x.com/notanumber", "handle": "x"},
                      timeout=15)
    assert r.status_code in (400, 422)
