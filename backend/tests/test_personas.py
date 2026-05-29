"""Tests for Reviewer Personas feature and Homepage stats."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://research-discovery-2.preview.emergentagent.com").rstrip("/")
ADMIN_PASSWORD = "papersumo2025"

EXPECTED_PERSONA_IDS = {"methodologist", "innovator", "practitioner", "generalist", "skeptic"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


# ── Public personas endpoint ────────────────────────────────────────────
def test_get_homepage_personas():
    r = requests.get(f"{BASE_URL}/api/homepage/personas", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 5
    assert "personas" in data and isinstance(data["personas"], list)
    assert len(data["personas"]) == 5
    ids = {p["id"] for p in data["personas"]}
    assert ids == EXPECTED_PERSONA_IDS
    for p in data["personas"]:
        assert {"id", "label", "description"}.issubset(p.keys())
        assert p["label"] and p["description"]
        # Ensure system_prompt NOT leaked publicly
        assert "system_prompt" not in p


# ── Homepage stats ──────────────────────────────────────────────────────
def test_homepage_stats():
    r = requests.get(f"{BASE_URL}/api/homepage/stats", timeout=20)
    assert r.status_code == 200
    data = r.json()
    for k in ["total_papers", "total_categories", "total_matches", "recent_papers",
              "top_categories", "categories", "top_papers", "ai_judges"]:
        assert k in data, f"Missing key: {k}"
    assert data["ai_judges"] == 3
    assert isinstance(data["total_papers"], int) and data["total_papers"] > 0
    assert isinstance(data["categories"], list) and len(data["categories"]) > 0


# ── Admin persona-stats ─────────────────────────────────────────────────
def test_persona_stats_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/persona-stats", timeout=15)
    assert r.status_code in (401, 403)


def test_persona_stats_with_auth(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/persona-stats",
        headers={"x-admin-token": admin_token},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "personas" in data
    assert "total_persona_matches" in data
    assert "total_all_matches" in data
    assert "coverage_pct" in data
    # All 5 personas must appear even with 0 matches
    assert len(data["personas"]) == 5
    ids = {p["id"] for p in data["personas"]}
    assert ids == EXPECTED_PERSONA_IDS
    for p in data["personas"]:
        assert {"id", "label", "description", "matches", "paper1_win_rate"}.issubset(p.keys())
        assert isinstance(p["matches"], int) and p["matches"] >= 0
    # Coverage values consistent
    assert isinstance(data["total_persona_matches"], int)
    assert isinstance(data["total_all_matches"], int)


def test_persona_stats_with_category_filter(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/persona-stats?category=cs.RO",
        headers={"x-admin-token": admin_token},
        timeout=20,
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("category") == "cs.RO"
    assert len(data["personas"]) == 5
