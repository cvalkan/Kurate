"""Tests for /api/admin/email-outreach/* endpoints."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://academic-ranker-1.preview.emergentagent.com").rstrip("/")
ADMIN_PASSWORD = "papersumo2025"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    token = r.json().get("token")
    assert token
    return token


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"X-Admin-Token": admin_token, "Content-Type": "application/json"}


# --- Templates ---
class TestTemplates:
    def test_get_default_template(self, headers):
        r = requests.get(f"{BASE_URL}/api/admin/email-outreach/templates", headers=headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "templates" in data
        assert "default" in data
        assert "subject" in data["default"]
        assert "body_html" in data["default"]
        assert "{{rank}}" in data["default"]["subject"]

    def test_save_custom_template(self, headers):
        payload = {
            "name": "default",
            "subject": "TEST_SUBJECT #{{rank}} {{category}}",
            "body_html": "<p>TEST_BODY {{author_name}} {{paper_title}}</p>",
        }
        r = requests.post(f"{BASE_URL}/api/admin/email-outreach/templates", json=payload, headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "saved"
        # Verify persistence via GET
        r2 = requests.get(f"{BASE_URL}/api/admin/email-outreach/templates", headers=headers, timeout=20)
        templates = r2.json().get("templates", [])
        saved = next((t for t in templates if t["name"] == "default"), None)
        assert saved is not None
        assert saved["subject"] == payload["subject"]
        assert saved["body_html"] == payload["body_html"]


# --- Gmail status ---
class TestGmailStatus:
    def test_gmail_status_authorized_field(self, headers):
        r = requests.get(f"{BASE_URL}/api/admin/email-outreach/gmail-status", headers=headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "authorized" in data
        assert isinstance(data["authorized"], bool)
        # In preview env, expected False, but just sanity check
        assert "user_id" in data


# --- Medalists ---
class TestMedalists:
    def test_medalists_monthly(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/email-outreach/medalists",
            params={"period": "monthly:2026-3", "top_n": 3},
            headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["period"] == "monthly:2026-3"
        assert "categories" in data
        assert isinstance(data["categories"], list)
        assert "total_papers" in data
        assert "total_with_emails" in data
        assert "total_sent" in data
        # Each category should have papers with required structure
        if data["categories"]:
            cat = data["categories"][0]
            assert "category" in cat
            assert "name" in cat
            assert "papers" in cat
            if cat["papers"]:
                p = cat["papers"][0]
                for key in ("id", "rank", "title", "emails", "emails_extracted", "already_sent"):
                    assert key in p, f"missing key {key}"

    def test_medalists_invalid_period(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/email-outreach/medalists",
            params={"period": "garbage", "top_n": 3},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200
        assert "error" in r.json()


# --- Manual emails ---
class TestManualEmails:
    @pytest.fixture(scope="class")
    def sample_paper_id(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/email-outreach/medalists",
            params={"period": "monthly:2026-3", "top_n": 3},
            headers=headers, timeout=30,
        )
        cats = r.json().get("categories", [])
        for c in cats:
            for p in c.get("papers", []):
                return p["id"]
        pytest.skip("No papers available for set-emails test")

    def test_set_emails_manually(self, headers, sample_paper_id):
        payload = {
            "paper_id": sample_paper_id,
            "emails": ["TEST_author1@example.edu", "TEST_author2@example.org", "invalid-no-at-sign"],
        }
        r = requests.post(f"{BASE_URL}/api/admin/email-outreach/set-emails", json=payload, headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "saved"
        assert data["paper_id"] == sample_paper_id
        # Invalid email should be filtered out
        assert "invalid-no-at-sign" not in data["emails"]
        assert "TEST_author1@example.edu" in data["emails"]
        # Verify persistence via medalists endpoint
        r2 = requests.get(
            f"{BASE_URL}/api/admin/email-outreach/medalists",
            params={"period": "monthly:2026-3", "top_n": 3},
            headers=headers, timeout=30,
        )
        cats = r2.json().get("categories", [])
        found = False
        for c in cats:
            for p in c.get("papers", []):
                if p["id"] == sample_paper_id:
                    assert "TEST_author1@example.edu" in p["emails"]
                    found = True
                    break
        assert found, "Saved emails not visible in medalists endpoint"


# --- Extract emails (single paper) ---
class TestExtractEmails:
    def test_extract_emails_unknown_paper(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/admin/email-outreach/extract-emails",
            json={"paper_id": "TEST_NONEXISTENT_PAPER_ID_XYZ"},
            headers=headers, timeout=30,
        )
        assert r.status_code == 404


# --- History ---
class TestHistory:
    def test_get_history(self, headers):
        r = requests.get(f"{BASE_URL}/api/admin/email-outreach/history", headers=headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "sends" in data
        assert "count" in data
        assert isinstance(data["sends"], list)
        assert data["count"] == len(data["sends"])


# --- Auth required ---
class TestAuth:
    def test_no_auth_rejected(self):
        r = requests.get(f"{BASE_URL}/api/admin/email-outreach/templates", timeout=15)
        assert r.status_code in (401, 403, 422)
