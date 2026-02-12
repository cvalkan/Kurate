"""
Pairwise-Derived Human Ranking Validation API Tests
Tests the new pairwise-derived human ranking approach added in iteration 27
- GET /api/validation/pairwise-results (public)
- Verifies pairwise_agreement, human_matches_derived, experts_contributing fields
- Verifies comparison table has human_rank, human_score, human_win_rate, human_matches, ai_rank, ai_score, rank_delta
- Verifies existing /api/validation/results still works (avg-rating experiment)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


class TestPairwiseResultsEndpoint:
    """GET /api/validation/pairwise-results - pairwise-derived human ranking"""

    def test_pairwise_results_returns_200(self):
        """Pairwise results endpoint accessible without auth"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_pairwise_results_status_ok(self):
        """Pairwise results endpoint returns status ok"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert data.get("status") == "ok", f"Expected status=ok, got {data.get('status')}"

    def test_pairwise_results_method_pairwise_derived(self):
        """Pairwise results has method=pairwise_derived"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert data.get("method") == "pairwise_derived", f"Expected method=pairwise_derived"

    def test_pairwise_results_contains_human_matches_derived(self):
        """Pairwise results contains human_matches_derived count"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "human_matches_derived" in data, "Missing human_matches_derived field"
        assert data["human_matches_derived"] > 0, "Expected human_matches_derived > 0"

    def test_pairwise_results_contains_human_matches_ties_excluded(self):
        """Pairwise results contains human_matches_ties_excluded count"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "human_matches_ties_excluded" in data, "Missing human_matches_ties_excluded field"

    def test_pairwise_results_contains_experts_contributing(self):
        """Pairwise results contains experts_contributing count"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "experts_contributing" in data, "Missing experts_contributing field"
        assert data["experts_contributing"] > 0, "Expected experts_contributing > 0"

    def test_pairwise_results_contains_pairwise_agreement(self):
        """Pairwise results contains pairwise_agreement object"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "pairwise_agreement" in data, "Missing pairwise_agreement field"
        agreement = data["pairwise_agreement"]
        assert "overlapping_pairs" in agreement, "Missing overlapping_pairs"
        assert "agreements" in agreement, "Missing agreements"
        assert "agreement_rate" in agreement, "Missing agreement_rate"

    def test_pairwise_agreement_values(self):
        """Pairwise agreement has reasonable values"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        agreement = data["pairwise_agreement"]
        # Agreement rate should be between 0 and 100
        assert 0 <= agreement["agreement_rate"] <= 100
        # Based on expected data: 56.1% agreement, 221 overlapping pairs
        assert agreement["overlapping_pairs"] > 100, f"Expected >100 overlapping pairs, got {agreement['overlapping_pairs']}"
        assert agreement["agreement_rate"] > 50, f"Agreement rate ({agreement['agreement_rate']}%) should be > 50% (better than random)"

    def test_pairwise_results_contains_correlation(self):
        """Pairwise results contains correlation metrics"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "correlation" in data, "Missing correlation object"
        corr = data["correlation"]
        assert "spearman_rho" in corr, "Missing spearman_rho"
        assert "kendall_tau" in corr, "Missing kendall_tau"
        assert "pearson_r" in corr, "Missing pearson_r"
        assert "spearman_p_value" in corr, "Missing spearman_p_value"
        assert "kendall_p_value" in corr, "Missing kendall_p_value"
        assert "pearson_p_value" in corr, "Missing pearson_p_value"

    def test_pairwise_correlation_values_in_range(self):
        """Pairwise correlation values should be between -1 and 1"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        corr = data["correlation"]
        for key in ["spearman_rho", "kendall_tau", "pearson_r"]:
            assert -1 <= corr[key] <= 1, f"{key}={corr[key]} out of range [-1, 1]"

    def test_pairwise_results_contains_comparison_table(self):
        """Pairwise results contains comparison array"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "comparison" in data, "Missing comparison array"
        assert len(data["comparison"]) > 0, "Comparison array is empty"

    def test_pairwise_comparison_entry_has_required_fields(self):
        """Each pairwise comparison entry has required fields"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        entry = data["comparison"][0]
        required_fields = [
            "id", "title", "journal", "h1_avg_rating", "h1_rating_count",
            "human_rank", "human_score", "human_win_rate", "human_matches",
            "ai_rank", "ai_score", "rank_delta"
        ]
        for field in required_fields:
            assert field in entry, f"Missing field: {field}"

    def test_pairwise_comparison_entry_human_values(self):
        """Pairwise comparison entries have valid human values"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        entry = data["comparison"][0]
        # Human rank should be positive integer
        assert entry["human_rank"] >= 1
        # Human score is Bradley-Terry score
        assert isinstance(entry["human_score"], (int, float))
        # Human win rate should be 0-100
        assert 0 <= entry["human_win_rate"] <= 100
        # Human matches should be positive
        assert entry["human_matches"] > 0

    def test_pairwise_results_contains_interpretation(self):
        """Pairwise results contains interpretation text"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "interpretation" in data
        assert len(data["interpretation"]) > 0
        # Should mention pairwise-derived
        assert "pairwise" in data["interpretation"].lower() or "pair" in data["interpretation"].lower()

    def test_pairwise_results_contains_expert_stats(self):
        """Pairwise results contains expert_stats"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        data = response.json()
        assert "expert_stats" in data
        stats = data["expert_stats"]
        assert len(stats) > 0, "Expected at least one expert in stats"
        # Check first expert has required fields
        expert_data = list(stats.values())[0]
        assert "papers_rated" in expert_data
        assert "pairs_derived" in expert_data
        assert "ties" in expert_data


class TestAvgRatingResultsStillWorks:
    """Verify GET /api/validation/results (avg-rating experiment) still works"""

    def test_avg_results_returns_200(self):
        """Avg rating results endpoint still accessible"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        assert response.status_code == 200

    def test_avg_results_status_ok(self):
        """Avg rating results endpoint returns status ok"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert data.get("status") == "ok"

    def test_avg_results_contains_correlation(self):
        """Avg rating results still contains correlation metrics"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert "correlation" in data
        corr = data["correlation"]
        assert "spearman_rho" in corr
        assert "kendall_tau" in corr
        assert "pearson_r" in corr

    def test_avg_results_contains_comparison(self):
        """Avg rating results still contains comparison table"""
        response = requests.get(f"{BASE_URL}/api/validation/results")
        data = response.json()
        assert "comparison" in data
        # Should have 47 papers
        assert data.get("papers_analyzed") == 47


class TestBothExperimentsCoexist:
    """Verify both experiments can run independently"""

    def test_both_endpoints_return_ok(self):
        """Both pairwise and avg endpoints return ok"""
        pairwise_resp = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        avg_resp = requests.get(f"{BASE_URL}/api/validation/results")
        
        assert pairwise_resp.json().get("status") == "ok"
        assert avg_resp.json().get("status") == "ok"

    def test_endpoints_have_different_methods(self):
        """Endpoints use different methods"""
        pairwise_resp = requests.get(f"{BASE_URL}/api/validation/pairwise-results")
        avg_resp = requests.get(f"{BASE_URL}/api/validation/results")
        
        # Pairwise should have method field
        assert pairwise_resp.json().get("method") == "pairwise_derived"
        # Avg results should not have method field or have different one
        assert avg_resp.json().get("method") != "pairwise_derived"

    def test_status_endpoint_still_works(self):
        """Status endpoint still returns expected data"""
        response = requests.get(f"{BASE_URL}/api/validation/status")
        data = response.json()
        assert data.get("papers_imported") == 47
        assert data.get("matches_completed") > 0
