"""
Test Security Headers and eLife Features
- Tests HTTP security headers on all API responses  
- Tests that eLife datasets exist in the validation system
- Tests validation_imports router endpoints exist
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ai-paper-judge-1.preview.emergentagent.com').rstrip('/')

class TestSecurityHeaders:
    """Test that security headers are present on API responses"""
    
    def test_health_returns_ok(self):
        """Health endpoint returns ok status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "papersumo-leaderboard"

    def test_strict_transport_security_header(self):
        """HSTS header is present"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert "strict-transport-security" in response.headers
        hsts = response.headers["strict-transport-security"]
        assert "max-age=" in hsts
        assert "includeSubDomains" in hsts

    def test_x_content_type_options_header(self):
        """X-Content-Type-Options header is set to nosniff"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert "x-content-type-options" in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_x_frame_options_header(self):
        """X-Frame-Options header is set to DENY"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert "x-frame-options" in response.headers
        assert response.headers["x-frame-options"] == "DENY"

    def test_referrer_policy_header(self):
        """Referrer-Policy header is present"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert "referrer-policy" in response.headers
        assert "strict-origin-when-cross-origin" in response.headers["referrer-policy"]

    def test_security_headers_on_validation_endpoint(self):
        """Security headers also present on other API endpoints"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        assert "strict-transport-security" in response.headers
        assert "x-content-type-options" in response.headers
        assert "x-frame-options" in response.headers


class TestValidationDatasets:
    """Test validation datasets endpoint and eLife datasets"""
    
    def test_validation_datasets_endpoint(self):
        """Validation datasets endpoint returns list of datasets"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        data = response.json()
        assert "datasets" in data
        assert isinstance(data["datasets"], list)
        assert len(data["datasets"]) >= 20  # Should have at least 20 datasets

    def test_elife_datasets_exist(self):
        """eLife datasets should be present in validation datasets"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        data = response.json()
        
        dataset_names = [ds.get("name", "").lower() for ds in data["datasets"]]
        
        # Check for eLife datasets
        elife_count = sum(1 for name in dataset_names if "elife" in name)
        assert elife_count >= 4, f"Expected at least 4 eLife datasets, found {elife_count}"
        
        # Verify specific eLife datasets exist
        expected_elife = ["elife cancer", "elife comp", "elife micro", "elife neuro"]
        for expected in expected_elife:
            found = any(expected in name for name in dataset_names)
            assert found, f"Expected to find dataset containing '{expected}'"

    def test_dataset_has_required_fields(self):
        """Each dataset should have required fields"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        data = response.json()
        
        for ds in data["datasets"][:5]:  # Check first 5
            assert "dataset_id" in ds
            assert "name" in ds
            assert "papers" in ds
            assert ds["papers"] > 0

    def test_24_datasets_exist(self):
        """Should have 24 validation datasets"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        data = response.json()
        
        num_datasets = len(data["datasets"])
        assert num_datasets == 24, f"Expected 24 datasets, found {num_datasets}"


class TestValidationImportsRouter:
    """Test that validation_imports router is properly included"""
    
    def test_import_iclr_endpoint_exists(self):
        """Import ICLR endpoint should exist (requires admin)"""
        # We can't actually call it without admin, but we can verify it exists
        # by checking for 401/403 (auth required) rather than 404 (not found)
        response = requests.post(
            f"{BASE_URL}/api/validation/import-iclr",
            json={"dataset_id": "test", "name": "test", "years": [2024]}
        )
        # Should be 401 or 403 (auth), not 404 (not found)
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"

    def test_import_elife_endpoint_exists(self):
        """Import eLife endpoint should exist (requires admin)"""
        response = requests.post(
            f"{BASE_URL}/api/validation/import-elife",
            json={"dataset_id": "test", "name": "test", "subject": "Test"}
        )
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"

    def test_import_midl_endpoint_exists(self):
        """Import MIDL endpoint should exist (requires admin)"""
        response = requests.post(
            f"{BASE_URL}/api/validation/import-midl",
            json={"dataset_id": "test", "name": "test", "years": [2024]}
        )
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"


class TestLeaderboardAndAnalysis:
    """Test leaderboard and analysis pages load data"""
    
    def test_leaderboard_endpoint(self):
        """Leaderboard endpoint returns data"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": "cs.RO", "time_range": "all_time"})
        assert response.status_code == 200
        data = response.json()
        assert "leaderboard" in data

    def test_model_correlation_endpoint(self):
        """Model correlation endpoint exists and returns data"""
        response = requests.get(f"{BASE_URL}/api/model-correlation")
        assert response.status_code == 200
        data = response.json()
        # Should have some correlation data
        assert data is not None
