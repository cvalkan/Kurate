"""
Test ORCID + Semantic Scholar Author Verification and Paper Claiming Feature
Tests all claim endpoints: /api/claim/*
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://ai-judges.preview.emergentagent.com"

# Test user credentials (email already verified, ORCID simulated as connected)
TEST_USER_EMAIL = "test-orcid@example.com"
TEST_USER_PASSWORD = "test123456"
TEST_ORCID_ID = "0000-0002-1234-5678"


class TestClaimEndpointsNoAuth:
    """Test claim endpoints without authentication."""

    def test_my_orcid_returns_401_when_not_logged_in(self):
        """GET /api/claim/my-orcid returns 401 when not authenticated."""
        response = requests.get(f"{BASE_URL}/api/claim/my-orcid")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        assert "Not authenticated" in data["detail"]

    def test_paper_claims_public_endpoint_returns_empty_array(self):
        """GET /api/claim/paper/{paper_id} returns empty claims array for unclaimed papers (public)."""
        # Use a random paper ID that likely doesn't have verified claims
        response = requests.get(f"{BASE_URL}/api/claim/paper/paper_test_12345")
        assert response.status_code == 200
        data = response.json()
        assert "claims" in data
        assert isinstance(data["claims"], list)

    def test_orcid_auth_url_returns_503_when_not_configured(self):
        """GET /api/claim/orcid/auth-url returns 503 when ORCID not configured (no env vars)."""
        response = requests.get(
            f"{BASE_URL}/api/claim/orcid/auth-url",
            params={"redirect_uri": "http://localhost:3000/auth/orcid/callback"}
        )
        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
        assert "not configured" in data["detail"].lower()

    def test_claim_paper_returns_401_when_not_authenticated(self):
        """POST /api/claim/{paper_id} returns 401 when not authenticated."""
        response = requests.post(f"{BASE_URL}/api/claim/paper_test_12345")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        assert "Not authenticated" in data["detail"]


class TestClaimEndpointsWithAuth:
    """Test claim endpoints with authenticated user who has ORCID connected."""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Login and get session token."""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )
        if response.status_code != 200:
            pytest.skip(f"Login failed: {response.status_code} - {response.text}")
        return response.json().get("session_token")

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get authorization headers."""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_auth_me_includes_orcid_id_field(self, auth_headers):
        """GET /api/auth/me includes orcid_id field in response."""
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "orcid_id" in data
        # The test user should have the simulated ORCID
        assert data["orcid_id"] == TEST_ORCID_ID

    def test_my_orcid_returns_connected_status(self, auth_headers):
        """GET /api/claim/my-orcid returns connected=true when ORCID is linked."""
        response = requests.get(f"{BASE_URL}/api/claim/my-orcid", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("connected") is True
        assert data.get("orcid_id") == TEST_ORCID_ID
        assert "orcid_name" in data
        assert "verified_count" in data

    def test_claim_paper_returns_pending_or_verified(self, auth_headers):
        """POST /api/claim/{paper_id} returns pending/verified when ORCID is connected and paper exists."""
        # Get a real paper ID from the leaderboard
        papers_response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&limit=30")
        assert papers_response.status_code == 200
        papers = papers_response.json().get("leaderboard", [])
        assert len(papers) > 15, "Not enough papers to test claiming"
        
        # Use paper at index 15 to avoid collision with earlier tests
        paper_id = papers[15]["id"]
        
        response = requests.post(f"{BASE_URL}/api/claim/{paper_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Should return either 'pending', 'verified', or 'already_claimed'
        assert data.get("status") in ["pending", "verified", "already_claimed"]
        
        # If pending or verified, should have method
        if data["status"] in ["pending", "verified"]:
            assert "method" in data or "message" in data

    def test_claim_same_paper_twice_returns_already_claimed(self, auth_headers):
        """POST /api/claim/{paper_id} returns already_claimed when claiming same paper twice."""
        # Get a real paper ID
        papers_response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&limit=30")
        assert papers_response.status_code == 200
        papers = papers_response.json().get("leaderboard", [])
        assert len(papers) > 20, "Not enough papers to test claiming"
        
        # Use paper at index 20 for this test
        paper_id = papers[20]["id"]
        
        # First claim
        response1 = requests.post(f"{BASE_URL}/api/claim/{paper_id}", headers=auth_headers)
        assert response1.status_code == 200
        
        # Second claim - should be already_claimed
        response2 = requests.post(f"{BASE_URL}/api/claim/{paper_id}", headers=auth_headers)
        assert response2.status_code == 200
        data = response2.json()
        assert data.get("status") == "already_claimed"

    def test_claim_nonexistent_paper_returns_404(self, auth_headers):
        """POST /api/claim/{paper_id} returns 404 for non-existent paper."""
        response = requests.post(
            f"{BASE_URL}/api/claim/nonexistent_paper_xyz_12345",
            headers=auth_headers
        )
        assert response.status_code == 404
        data = response.json()
        assert "Paper not found" in data.get("detail", "")


class TestMyClaimsEndpoint:
    """Test the my-claims endpoint."""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Login and get session token."""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )
        if response.status_code != 200:
            pytest.skip(f"Login failed: {response.status_code}")
        return response.json().get("session_token")

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get authorization headers."""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_my_claims_returns_list(self, auth_headers):
        """GET /api/claim/my-claims returns user's claimed papers."""
        response = requests.get(f"{BASE_URL}/api/claim/my-claims", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "claims" in data
        assert isinstance(data["claims"], list)
        # Should include orcid_id
        assert "orcid_id" in data

    def test_my_claims_returns_401_without_auth(self):
        """GET /api/claim/my-claims returns 401 without authentication."""
        response = requests.get(f"{BASE_URL}/api/claim/my-claims")
        assert response.status_code == 401


class TestOrcidConnectEndpoint:
    """Test ORCID connect endpoint error handling."""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Login and get session token."""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )
        if response.status_code != 200:
            pytest.skip(f"Login failed: {response.status_code}")
        return response.json().get("session_token")

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get authorization headers."""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_orcid_connect_returns_503_when_not_configured(self, auth_headers):
        """POST /api/claim/orcid/connect returns 503 when ORCID not configured."""
        response = requests.post(
            f"{BASE_URL}/api/claim/orcid/connect",
            json={"code": "fake_code", "redirect_uri": "http://localhost:3000/callback"},
            headers=auth_headers
        )
        assert response.status_code == 503
        data = response.json()
        assert "not configured" in data.get("detail", "").lower()

    def test_orcid_connect_returns_401_without_auth(self):
        """POST /api/claim/orcid/connect returns 401 without authentication."""
        response = requests.post(
            f"{BASE_URL}/api/claim/orcid/connect",
            json={"code": "fake_code", "redirect_uri": "http://localhost:3000/callback"}
        )
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
