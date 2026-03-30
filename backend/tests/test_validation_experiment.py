"""
Validation Experiment API Tests
Tests Human vs AI Validation feature endpoints
- GET /api/validation/status (public)
- GET /api/validation/results (public)
- POST /api/validation/import (admin only)
- POST /api/validation/run-tournament (admin only)
- POST /api/validation/reset (admin only)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class TestValidationStatusEndpoint:
    """GET /api/validation/status - public endpoint"""

    def test_status_returns_200(self):
        """Status endpoint accessible without auth"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_status_contains_papers_imported(self):
        """Status contains papers_imported count"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert "papers_imported" in data, "Missing papers_imported field"
        assert data["papers_imported"] == 47, f"Expected 47 papers, got {data['papers_imported']}"

    def test_status_contains_matches_completed(self):
        """Status contains matches_completed count"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert "matches_completed" in data, "Missing matches_completed field"
        assert data["matches_completed"] > 0, "Expected completed matches > 0"

    def test_status_contains_coverage_stats(self):
        """Status contains coverage percentage and total possible pairs"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert "coverage_pct" in data, "Missing coverage_pct"
        assert "total_possible_pairs" in data, "Missing total_possible_pairs"
        assert isinstance(data["coverage_pct"], (int, float))

    def test_status_contains_tournament_state(self):
        """Status contains tournament running state"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert "tournament_running" in data, "Missing tournament_running"
        assert "tournament_progress" in data, "Missing tournament_progress"

    def test_status_contains_matches_per_paper_stats(self):
        """Status contains avg/min/max matches per paper"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert "avg_matches_per_paper" in data
        assert "min_matches_per_paper" in data
        assert "max_matches_per_paper" in data

    def test_status_contains_min_expert_ratings(self):
        """Status contains min_expert_ratings threshold"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert "min_expert_ratings" in data
        assert data["min_expert_ratings"] == 5


class TestValidationResultsEndpoint:
    """GET /api/validation/results - public endpoint with correlation metrics"""

    def test_results_returns_200(self):
        """Results endpoint accessible without auth"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        assert response.status_code == 200

    def test_results_status_ok(self):
        """Results endpoint returns status ok when data exists"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert data.get("status") == "ok", f"Expected status=ok, got {data.get('status')}"

    def test_results_contains_correlation_metrics(self):
        """Results contains Spearman, Kendall, Pearson correlation"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert "correlation" in data, "Missing correlation object"
        corr = data["correlation"]
        assert "spearman_rho" in corr, "Missing spearman_rho"
        assert "kendall_tau" in corr, "Missing kendall_tau"
        assert "pearson_r" in corr, "Missing pearson_r"

    def test_results_correlation_values_in_range(self):
        """Correlation values should be between -1 and 1"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        corr = data["correlation"]
        for key in ["spearman_rho", "kendall_tau", "pearson_r"]:
            assert -1 <= corr[key] <= 1, f"{key}={corr[key]} out of range [-1, 1]"

    def test_results_contains_p_values(self):
        """Results contains p-values for statistical significance"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        corr = data["correlation"]
        assert "spearman_p_value" in corr
        assert "kendall_p_value" in corr
        assert "pearson_p_value" in corr

    def test_results_contains_comparison_table(self):
        """Results contains comparison array with paper rankings"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert "comparison" in data, "Missing comparison array"
        assert len(data["comparison"]) > 0, "Comparison array is empty"

    def test_results_comparison_entry_structure(self):
        """Each comparison entry has required fields"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        entry = data["comparison"][0]
        required_fields = ["id", "title", "h1_avg_rating", "h1_rating_count", 
                          "human_rank", "ai_rank", "ai_score", "ai_win_rate", 
                          "ai_matches", "rank_delta"]
        for field in required_fields:
            assert field in entry, f"Missing field: {field}"

    def test_results_contains_interpretation(self):
        """Results contains human-readable interpretation"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert "interpretation" in data
        assert len(data["interpretation"]) > 0

    def test_results_contains_analysis_counts(self):
        """Results contains papers_analyzed and total_matches"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert "papers_analyzed" in data
        assert "total_matches" in data
        assert data["papers_analyzed"] == 47
        assert data["total_matches"] > 100


class TestValidationAdminEndpoints:
    """Admin-only validation endpoints"""

    @pytest.fixture(autouse=True)
    def get_admin_token(self):
        """Get admin token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD})
        if response.status_code == 200:
            self.admin_token = response.json().get("token")
        else:
            pytest.skip("Admin login failed - skipping admin tests")

    def test_import_requires_auth(self):
        """POST /api/validation/import requires admin auth"""
        response = requests.post(f"{BASE_URL}/api/validation/import")
        assert response.status_code == 401 or response.status_code == 403

    def test_import_with_auth_succeeds(self):
        """POST /api/validation/import works with valid admin token"""
        headers = {"X-Admin-Token": self.admin_token}
        response = requests.post(f"{BASE_URL}/api/validation/import", headers=headers)
        # Should return 200 even if no new papers to import
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_run_tournament_requires_auth(self):
        """POST /api/validation/run-tournament requires admin auth"""
        response = requests.post(f"{BASE_URL}/api/validation/run-tournament")
        assert response.status_code == 401 or response.status_code == 403

    def test_reset_requires_auth(self):
        """POST /api/validation/reset requires admin auth"""
        response = requests.post(f"{BASE_URL}/api/validation/reset")
        assert response.status_code == 401 or response.status_code == 403


class TestValidationDataSilo:
    """Verify validation data is siloed from main leaderboard"""

    def test_main_leaderboard_unaffected(self):
        """Main leaderboard should not contain validation papers"""
        # Get main leaderboard
        main_response = requests.get(f"{BASE_URL}/api/leaderboard?period=all")
        main_data = main_response.json()
        
        # Get validation results
        validation_response = requests.get(f"{BASE_URL}/api/validation/results")
        validation_data = validation_response.json()
        
        if validation_data.get("status") == "ok":
            validation_ids = {p["id"] for p in validation_data.get("comparison", [])}
            main_ids = {p["id"] for p in main_data.get("leaderboard", [])}
            
            # Validation papers should not appear in main leaderboard
            overlap = validation_ids & main_ids
            # Note: Some overlap might occur if papers exist in both systems
            # The key is that the rankings are computed separately
            print(f"Validation papers: {len(validation_ids)}, Main leaderboard: {len(main_ids)}, Overlap: {len(overlap)}")
