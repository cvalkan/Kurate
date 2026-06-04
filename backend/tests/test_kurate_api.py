"""Backend tests for Kurate API endpoints."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://scholarly-intel.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /api/categories ----------
def test_categories(client):
    r = client.get(f"{BASE_URL}/api/categories", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 12
    for c in data:
        for k in ("code", "name", "paper_count", "latest_update", "field", "description"):
            assert k in c, f"missing {k}"
        assert isinstance(c["paper_count"], int)


# ---------- /api/years ----------
def test_years(client):
    r = client.get(f"{BASE_URL}/api/years", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    vals = [int(y["value"]) for y in data]
    assert vals == sorted(vals, reverse=True)


# ---------- /api/metrics ----------
def test_metrics(client):
    r = client.get(f"{BASE_URL}/api/metrics", timeout=30)
    assert r.status_code == 200
    m = r.json()
    assert m["papers_ranked"] == 120
    assert m["active_categories"] == 12
    assert m["ai_judges"] == 4
    assert "total_comparisons" in m
    assert "latest_update" in m
    assert "avg_model_agreement" in m


# ---------- /api/papers ----------
def test_papers_default(client):
    r = client.get(f"{BASE_URL}/api/papers", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 120
    assert len(data["results"]) == 10
    # Verify ranks and top sort by score desc
    scores = [p["score"] for p in data["results"]]
    assert scores == sorted(scores, reverse=True)
    for i, p in enumerate(data["results"]):
        assert p["rank"] == i + 1


def test_papers_category_filter(client):
    r = client.get(f"{BASE_URL}/api/papers", params={"category": "cs.AI", "limit": 50}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 10
    assert all(p["category_code"] == "cs.AI" for p in data["results"])


def test_papers_search_quantum(client):
    r = client.get(f"{BASE_URL}/api/papers", params={"q": "quantum", "limit": 50}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    for p in data["results"]:
        hay = (p["title"] + p["category_code"] + p["category_name"] + " ".join(p["authors"])).lower()
        assert "quantum" in hay


def test_papers_rank_agreement(client):
    r = client.get(f"{BASE_URL}/api/papers", params={"rank_type": "agreement", "limit": 20}, timeout=30)
    assert r.status_code == 200
    vals = [p["model_agreement"] for p in r.json()["results"]]
    assert vals == sorted(vals, reverse=True)


def test_papers_rank_validation(client):
    r = client.get(f"{BASE_URL}/api/papers", params={"rank_type": "validation", "limit": 20}, timeout=30)
    assert r.status_code == 200
    vals = [p["validation_signal"] for p in r.json()["results"]]
    assert vals == sorted(vals, reverse=True)


def test_papers_period_7d(client):
    r = client.get(f"{BASE_URL}/api/papers", params={"period": "7d", "limit": 100}, timeout=30)
    assert r.status_code == 200
    # might be smaller than 120
    assert r.json()["total"] <= 120


def test_papers_year_filter(client):
    yr = client.get(f"{BASE_URL}/api/years", timeout=30).json()[0]["value"]
    r = client.get(f"{BASE_URL}/api/papers", params={"year": yr, "limit": 100}, timeout=30)
    assert r.status_code == 200
    for p in r.json()["results"]:
        assert str(p["year"]) == yr


# ---------- /api/recent ----------
def test_recent(client):
    r = client.get(f"{BASE_URL}/api/recent", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert "cards" in data and "recent_papers" in data
    assert len(data["cards"]) == 8
    assert data["cards"][0]["kind"] == "feed"
    assert len(data["recent_papers"]) == 8


# ---------- /api/activity ----------
def test_activity(client):
    r = client.get(f"{BASE_URL}/api/activity", timeout=30)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and len(items) >= 6
    for it in items:
        for k in ("kind", "title", "category_code", "timestamp"):
            assert k in it
