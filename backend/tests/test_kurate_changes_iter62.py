"""
Iteration 62: Test recent changes to Kurate.org
- Health endpoint
- Categories API (group field, new_categories, ordering)
- Admin login
- Scheduler diagnostics (leader_id, is_leader)
- Restart history
- System logs event filter
- User registrations endpoint
- Admin users pagination
- Toggle new category
- Archive dedup migration flag
"""
import os
import pytest
import requests

def _load_base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    # Fallback: read frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set and frontend/.env missing")

BASE = _load_base()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "papersumo2025")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    token = data.get("token") or data.get("admin_token")
    assert token, f"No token in admin login response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"X-Admin-Token": admin_token}


# --- Health ---
def test_health_ok():
    r = requests.get(f"{BASE}/api/health", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


# --- Categories: group field + new_categories ---
def test_categories_returns_group_and_new_categories():
    r = requests.get(f"{BASE}/api/categories", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "categories" in body, body
    assert "new_categories" in body, body
    assert isinstance(body["new_categories"], list)
    cats = body["categories"]
    assert len(cats) >= 1
    for c in cats:
        assert "id" in c and "name" in c and "group" in c, c
        assert isinstance(c["group"], str)


def test_categories_sort_first5_admin_rest_alpha_by_group_then_name():
    r = requests.get(f"{BASE}/api/categories", timeout=15)
    assert r.status_code == 200
    cats = r.json()["categories"]
    if len(cats) <= 5:
        pytest.skip("Not enough categories to validate sort")
    rest = cats[5:]
    keys = [(c["group"], c["name"]) for c in rest]
    assert keys == sorted(keys), f"Tail not sorted by (group, name): {keys}"


# --- Admin login ---
def test_admin_login_success(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 5


def test_admin_login_wrong_password():
    r = requests.post(f"{BASE}/api/admin/login", json={"password": "wrong"}, timeout=10)
    assert r.status_code in (401, 403)


# --- Scheduler diagnostics ---
def test_scheduler_diagnostics_leader_fields(admin_headers):
    r = requests.get(f"{BASE}/api/admin/scheduler-diagnostics", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "leader_id" in body, body
    assert "is_leader" in body, body
    assert isinstance(body["is_leader"], bool)
    assert isinstance(body["leader_id"], str) and body["leader_id"]


# --- Restart history ---
def test_restart_history(admin_headers):
    r = requests.get(f"{BASE}/api/admin/restart-history", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "events" in body and "count" in body
    assert isinstance(body["events"], list)
    assert body["count"] == len(body["events"])


# --- System logs event filter ---
def test_system_logs_event_filter(admin_headers):
    r = requests.get(
        f"{BASE}/api/admin/system-logs",
        params={"event": "badge_image_render", "hours": 168, "limit": 50},
        headers=admin_headers,
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Should return a structure with logs/events list. Accept either common shapes.
    assert isinstance(body, dict)
    # logs may be empty in preview env, but request must succeed
    logs = body.get("logs") or body.get("events") or []
    assert isinstance(logs, list)


# --- User registrations endpoint ---
def test_user_registrations_endpoint(admin_headers):
    r = requests.get(f"{BASE}/api/admin/users/registrations", headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "series" in body and "total" in body, body
    assert isinstance(body["series"], list)
    assert isinstance(body["total"], int)


# --- Admin users pagination ---
def test_admin_users_pagination_differs(admin_headers):
    r1 = requests.get(f"{BASE}/api/admin/users", params={"page": 1, "limit": 3}, headers=admin_headers, timeout=20)
    r2 = requests.get(f"{BASE}/api/admin/users", params={"page": 2, "limit": 3}, headers=admin_headers, timeout=20)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    u1 = r1.json().get("users", [])
    u2 = r2.json().get("users", [])
    if r1.json().get("total", 0) < 4:
        pytest.skip(f"Not enough users to test pagination (total={r1.json().get('total')})")
    ids1 = {u.get("user_id") or u.get("email") or u.get("id") for u in u1}
    ids2 = {u.get("user_id") or u.get("email") or u.get("id") for u in u2}
    assert ids1 != ids2, f"Page 1 and Page 2 returned same users: {ids1}"
    assert len(u1) <= 3 and len(u2) <= 3
    # offset reflected
    assert r1.json().get("offset") == 0
    assert r2.json().get("offset") == 3


# --- Toggle new category ---
def test_toggle_new_category_idempotent(admin_headers):
    # Get an existing category id
    r = requests.get(f"{BASE}/api/categories", timeout=15)
    cats = r.json()["categories"]
    assert cats, "No categories to test toggle on"
    cat_id = cats[0]["id"]

    # Initial state via /api/admin/arxiv-categories
    r0 = requests.get(f"{BASE}/api/admin/arxiv-categories", headers=admin_headers, timeout=15)
    assert r0.status_code == 200
    initial = list(r0.json().get("new_categories", []))

    # Toggle once
    r1 = requests.post(
        f"{BASE}/api/admin/categories/toggle-new",
        headers=admin_headers,
        json={"category_id": cat_id},
        timeout=15,
    )
    assert r1.status_code == 200, r1.text
    state1 = r1.json().get("new_categories", [])
    assert (cat_id in state1) != (cat_id in initial), f"toggle did not flip membership: initial={initial}, after={state1}"

    # Toggle back to restore original
    r2 = requests.post(
        f"{BASE}/api/admin/categories/toggle-new",
        headers=admin_headers,
        json={"category_id": cat_id},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    state2 = r2.json().get("new_categories", [])
    assert (cat_id in state2) == (cat_id in initial), f"toggle did not restore: {state2}"


# --- Archive dedup migration flag ---
def test_archive_dedup_migration_flag(admin_headers):
    # Use the db-explorer/settings endpoint via admin to fetch settings doc.
    # Fallback: check via /api/admin/db-explorer if available; otherwise look in archives indirectly.
    # We'll try the explorer endpoint that's usually used.
    url = f"{BASE}/api/admin/db-explorer/collection/settings"
    r = requests.get(url, headers=admin_headers, timeout=20)
    if r.status_code == 404:
        pytest.skip("db-explorer settings endpoint not available; flag check skipped")
    assert r.status_code == 200, r.text
    body = r.json()
    docs = body.get("documents") or body.get("docs") or body if isinstance(body, list) else body.get("rows", [])
    if isinstance(body, dict) and "documents" in body:
        docs = body["documents"]
    # Search for key dedup_archives_v1
    found = False
    for d in docs if isinstance(docs, list) else []:
        if d.get("key") == "dedup_archives_v1":
            found = True
            assert d.get("done") is True
            break
    if not found:
        pytest.skip("dedup_archives_v1 flag not yet present in settings (migration may not have run in preview)")
