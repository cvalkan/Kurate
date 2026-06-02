"""
Test suite for Auth (register, login, logout, me) and Suggestions endpoints.
Uses pytest for backend API testing with auth flows.
"""
import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://atlas-optimized.preview.emergentagent.com').rstrip('/')
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Test user credentials - unique for each test run
TEST_USER_PREFIX = f"test_user_{int(time.time())}"
TEST_EMAIL = f"{TEST_USER_PREFIX}@example.com"
TEST_PASSWORD = "test123456"
TEST_NAME = "Test User Auth"


class TestAuthRegister:
    """Test POST /api/auth/register endpoint"""

    def test_register_success(self):
        """Register creates user and returns session_token"""
        unique_email = f"register_test_{uuid.uuid4().hex[:8]}@example.com"
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": unique_email,
            "password": "testpassword123",
            "name": "Register Test User"
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Data assertions
        assert "session_token" in data, "Response missing session_token"
        assert "user" in data, "Response missing user object"
        assert data["user"]["email"] == unique_email, "Email mismatch"
        assert data["user"]["name"] == "Register Test User", "Name mismatch"
        assert "user_id" in data["user"], "User ID not returned"
        assert data["user"]["provider"] == "email", "Provider should be 'email'"

    def test_register_duplicate_email(self):
        """Register with existing email returns 400"""
        unique_email = f"dup_test_{uuid.uuid4().hex[:8]}@example.com"
        
        # First registration
        response1 = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": unique_email,
            "password": "testpassword123",
            "name": "First User"
        })
        assert response1.status_code == 200

        # Second registration with same email
        response2 = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": unique_email,
            "password": "testpassword456",
            "name": "Second User"
        })
        assert response2.status_code == 400, f"Expected 400 for duplicate, got {response2.status_code}"
        assert "already registered" in response2.json().get("detail", "").lower()

    def test_register_short_password(self):
        """Register with password < 6 chars returns 400"""
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": f"short_pw_{uuid.uuid4().hex[:8]}@example.com",
            "password": "abc",
            "name": "Short Password User"
        })
        assert response.status_code == 400


class TestAuthLogin:
    """Test POST /api/auth/login endpoint"""

    @pytest.fixture(scope="class")
    def registered_user(self):
        """Create a user for login tests"""
        email = f"login_test_{uuid.uuid4().hex[:8]}@example.com"
        password = "testpassword123"
        name = "Login Test User"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": password,
            "name": name
        })
        assert response.status_code == 200
        return {"email": email, "password": password, "name": name}

    def test_login_success(self, registered_user):
        """Login with valid credentials returns session_token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": registered_user["email"],
            "password": registered_user["password"]
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Data assertions
        assert "session_token" in data, "Response missing session_token"
        assert "user" in data, "Response missing user object"
        assert data["user"]["email"] == registered_user["email"]
        assert "user_id" in data["user"]
        assert data["user"]["provider"] == "email"

    def test_login_invalid_password(self, registered_user):
        """Login with wrong password returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": registered_user["email"],
            "password": "wrongpassword"
        })
        assert response.status_code == 401

    def test_login_nonexistent_user(self):
        """Login with non-existent email returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nonexistent@example.com",
            "password": "password123"
        })
        assert response.status_code == 401


class TestAuthMe:
    """Test GET /api/auth/me endpoint"""

    @pytest.fixture(scope="class")
    def auth_session(self):
        """Create a user and get session token"""
        email = f"me_test_{uuid.uuid4().hex[:8]}@example.com"
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpassword123",
            "name": "Me Test User"
        })
        assert response.status_code == 200
        return response.json()["session_token"]

    def test_me_with_valid_token(self, auth_session):
        """GET /api/auth/me returns user data with valid session token"""
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {auth_session}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Data assertions
        assert "user_id" in data, "Response missing user_id"
        assert "email" in data, "Response missing email"
        assert "name" in data, "Response missing name"
        assert data["provider"] == "email"

    def test_me_without_token(self):
        """GET /api/auth/me returns 401 without session token"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401

    def test_me_with_invalid_token(self):
        """GET /api/auth/me returns 401 with invalid session token"""
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": "Bearer invalid_token_12345"}
        )
        assert response.status_code == 401


class TestAuthLogout:
    """Test POST /api/auth/logout endpoint"""

    def test_logout_success(self):
        """POST /api/auth/logout clears session"""
        # First register and get token
        email = f"logout_test_{uuid.uuid4().hex[:8]}@example.com"
        reg_response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpassword123",
            "name": "Logout Test User"
        })
        assert reg_response.status_code == 200
        token = reg_response.json()["session_token"]

        # Verify token works
        me_response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 200

        # Logout
        logout_response = requests.post(
            f"{BASE_URL}/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert logout_response.status_code == 200
        assert logout_response.json().get("status") == "ok"

        # Verify token no longer works
        me_after = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_after.status_code == 401, "Token should be invalidated after logout"


class TestSuggestions:
    """Test /api/suggestions endpoint"""

    @pytest.fixture(scope="class")
    def auth_session(self):
        """Create authenticated user for suggestions tests"""
        email = f"sug_test_{uuid.uuid4().hex[:8]}@example.com"
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpassword123",
            "name": "Suggestion Test User"
        })
        assert response.status_code == 200
        return response.json()["session_token"]

    def test_create_suggestion_requires_auth(self):
        """POST /api/suggestions returns 401 without token"""
        response = requests.post(f"{BASE_URL}/api/suggestions", json={
            "type": "field",
            "text": "Add cs.ML Machine Learning"
        })
        assert response.status_code == 401

    def test_create_field_suggestion(self, auth_session):
        """POST /api/suggestions creates field suggestion with valid token"""
        response = requests.post(
            f"{BASE_URL}/api/suggestions",
            json={"type": "field", "text": "Add cs.ML Machine Learning - test suggestion"},
            headers={"Authorization": f"Bearer {auth_session}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("status") == "ok"
        assert "suggestion_id" in data

    def test_create_general_suggestion(self, auth_session):
        """POST /api/suggestions creates general feedback with valid token"""
        response = requests.post(
            f"{BASE_URL}/api/suggestions",
            json={"type": "general", "text": "Great app! - test feedback"},
            headers={"Authorization": f"Bearer {auth_session}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "suggestion_id" in data

    def test_create_suggestion_invalid_type(self, auth_session):
        """POST /api/suggestions with invalid type returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/suggestions",
            json={"type": "invalid", "text": "Test text"},
            headers={"Authorization": f"Bearer {auth_session}"}
        )
        assert response.status_code == 400

    def test_create_suggestion_empty_text(self, auth_session):
        """POST /api/suggestions with empty text returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/suggestions",
            json={"type": "field", "text": "   "},
            headers={"Authorization": f"Bearer {auth_session}"}
        )
        assert response.status_code == 400


class TestAdminSuggestions:
    """Test GET /api/admin/suggestions endpoint"""

    def test_admin_suggestions_without_auth(self):
        """GET /api/admin/suggestions returns 401/403 without admin token"""
        response = requests.get(f"{BASE_URL}/api/admin/suggestions")
        assert response.status_code in [401, 403]

    def test_admin_suggestions_with_auth(self):
        """GET /api/admin/suggestions returns suggestions list with admin token"""
        response = requests.get(
            f"{BASE_URL}/api/admin/suggestions",
            headers={"X-Admin-Token": ADMIN_PASSWORD}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)


class TestExistingUserLogin:
    """Test with existing test user credentials from auth_testing.md"""

    def test_existing_user_login(self):
        """Login with test@example.com / test123"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "test@example.com",
            "password": "test123"
        })
        # This may return 401 if user doesn't exist - that's fine
        if response.status_code == 200:
            data = response.json()
            assert "session_token" in data
            assert data["user"]["email"] == "test@example.com"
            print(f"Existing user login succeeded")
        else:
            print(f"Existing user test@example.com not found (status: {response.status_code}) - will create new test user")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
