"""Tests for the redesigned homepage backend endpoints (iter 66)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://research-discovery-2.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestHomepageStats:
    def test_stats_200_and_schema(self, client):
        r = client.get(f"{BASE_URL}/api/homepage/stats", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in [
            "total_papers", "total_categories", "total_matches",
            "recent_papers", "top_categories", "latest_update",
            "categories", "top_papers", "ai_judges",
        ]:
            assert k in d, f"missing key: {k}"

    def test_stats_values_reasonable(self, client):
        d = client.get(f"{BASE_URL}/api/homepage/stats", timeout=30).json()
        assert isinstance(d["total_papers"], int) and d["total_papers"] > 0
        assert isinstance(d["total_categories"], int) and d["total_categories"] > 0
        assert isinstance(d["total_matches"], int) and d["total_matches"] >= 0
        assert d["ai_judges"] == 3

    def test_top_papers_have_required_fields(self, client):
        d = client.get(f"{BASE_URL}/api/homepage/stats", timeout=30).json()
        tp = d.get("top_papers", [])
        assert isinstance(tp, list) and len(tp) > 0
        for p in tp:
            assert "title" in p and isinstance(p["title"], str)
            assert "primary_category" in p
            assert "ts_score" in p
            # ID needed for /paper/{id} link
            assert "id" in p

    def test_top_categories_have_required_fields(self, client):
        d = client.get(f"{BASE_URL}/api/homepage/stats", timeout=30).json()
        tc = d.get("top_categories", [])
        assert isinstance(tc, list) and len(tc) > 0
        for c in tc:
            assert "id" in c and "name" in c and "count" in c
            assert isinstance(c["count"], int)

    def test_categories_list_non_empty(self, client):
        d = client.get(f"{BASE_URL}/api/homepage/stats", timeout=30).json()
        cats = d.get("categories", [])
        assert isinstance(cats, list) and len(cats) > 0
        for c in cats:
            assert "id" in c and "name" in c

    def test_no_mongo_id_leakage(self, client):
        text = client.get(f"{BASE_URL}/api/homepage/stats", timeout=30).text
        # MongoDB ObjectId-style "_id" should never appear
        assert '"_id"' not in text


class TestHomepagePersonas:
    def test_personas_200(self, client):
        r = client.get(f"{BASE_URL}/api/homepage/personas", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "personas" in d and "count" in d
        assert d["count"] == len(d["personas"]) == 5
        for p in d["personas"]:
            assert {"id", "label", "description"}.issubset(p.keys())
