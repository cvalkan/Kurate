"""
Tests for Scoring Method Correlation API endpoint
Tests the /api/scoring-method-correlation endpoint that compares Win-Rate, Bradley-Terry, and TrueSkill ranking methods
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestScoringMethodCorrelation:
    """Tests for GET /api/scoring-method-correlation endpoint"""

    def test_endpoint_returns_ok_status(self):
        """Test that endpoint returns status=ok with valid data"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status=ok, got {data.get('status')}"
        print("PASS: Endpoint returns status=ok")

    def test_response_contains_required_fields(self):
        """Test that response contains all required fields"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["status", "n_papers", "n_matches", "compute_time_s", "correlations", "rank_agreement"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        print(f"PASS: Response contains all required fields: {required_fields}")

    def test_correlations_array_has_3_pairs(self):
        """Test that correlations array has exactly 3 method pairs"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        correlations = data.get("correlations", [])
        assert len(correlations) == 3, f"Expected 3 correlation pairs, got {len(correlations)}"
        
        # Verify all 3 pairs are present
        pairs = [(c["method1"], c["method2"]) for c in correlations]
        expected_pairs = [("win_rate", "bt"), ("win_rate", "trueskill"), ("bt", "trueskill")]
        for pair in expected_pairs:
            assert pair in pairs, f"Missing correlation pair: {pair}"
        print(f"PASS: Correlations array has 3 pairs: {pairs}")

    def test_correlation_values_are_valid(self):
        """Test that spearman_rho and kendall_tau values are between 0 and 1"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        for corr in data.get("correlations", []):
            spearman = corr.get("spearman_rho")
            kendall = corr.get("kendall_tau")
            
            assert spearman is not None, f"Missing spearman_rho for {corr.get('label')}"
            assert kendall is not None, f"Missing kendall_tau for {corr.get('label')}"
            
            # Correlation values should be between -1 and 1, but for ranking methods they should be positive
            assert -1 <= spearman <= 1, f"Invalid spearman_rho: {spearman}"
            assert -1 <= kendall <= 1, f"Invalid kendall_tau: {kendall}"
            
            # For ranking methods, we expect positive correlations
            assert spearman > 0, f"Expected positive spearman_rho, got {spearman}"
            assert kendall > 0, f"Expected positive kendall_tau, got {kendall}"
            
            print(f"PASS: {corr.get('label')}: spearman_rho={spearman:.4f}, kendall_tau={kendall:.4f}")

    def test_rank_agreement_structure(self):
        """Test that rank_agreement has correct structure with pct, top_overlap, bottom_overlap"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        rank_agreement = data.get("rank_agreement", [])
        assert len(rank_agreement) > 0, "rank_agreement should not be empty"
        
        # Should have 9 entries: 3 pairs × 3 percentages (5%, 10%, 20%)
        assert len(rank_agreement) == 9, f"Expected 9 rank_agreement entries, got {len(rank_agreement)}"
        
        for entry in rank_agreement:
            assert "pct" in entry, "Missing pct field"
            assert "top_overlap" in entry, "Missing top_overlap field"
            assert "bottom_overlap" in entry, "Missing bottom_overlap field"
            assert "method1" in entry, "Missing method1 field"
            assert "method2" in entry, "Missing method2 field"
            
            # Validate percentage values
            assert entry["pct"] in [5, 10, 20], f"Unexpected pct value: {entry['pct']}"
            assert 0 <= entry["top_overlap"] <= 100, f"Invalid top_overlap: {entry['top_overlap']}"
            assert 0 <= entry["bottom_overlap"] <= 100, f"Invalid bottom_overlap: {entry['bottom_overlap']}"
        
        print(f"PASS: rank_agreement has {len(rank_agreement)} entries with valid structure")

    def test_category_filter_cs_dc(self):
        """Test that category filter returns filtered results for cs.DC"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation?category=cs.DC", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("status") == "ok", f"Expected status=ok, got {data.get('status')}"
        assert data.get("category") == "cs.DC", f"Expected category=cs.DC, got {data.get('category')}"
        
        # cs.DC should have fewer papers than all categories
        n_papers = data.get("n_papers", 0)
        n_matches = data.get("n_matches", 0)
        
        assert n_papers > 0, "n_papers should be > 0 for cs.DC"
        assert n_matches > 0, "n_matches should be > 0 for cs.DC"
        
        # According to context, cs.DC has 282 papers and ~10K matches
        assert n_papers < 500, f"cs.DC should have fewer papers, got {n_papers}"
        
        print(f"PASS: Category filter cs.DC returns {n_papers} papers, {n_matches} matches")

    def test_category_filter_returns_fewer_papers(self):
        """Test that filtered category returns fewer papers than all categories"""
        # Get all categories
        response_all = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response_all.status_code == 200
        data_all = response_all.json()
        
        # Get cs.DC category
        response_dc = requests.get(f"{BASE_URL}/api/scoring-method-correlation?category=cs.DC", timeout=120)
        assert response_dc.status_code == 200
        data_dc = response_dc.json()
        
        n_papers_all = data_all.get("n_papers", 0)
        n_papers_dc = data_dc.get("n_papers", 0)
        
        assert n_papers_dc < n_papers_all, f"cs.DC ({n_papers_dc}) should have fewer papers than all ({n_papers_all})"
        print(f"PASS: cs.DC ({n_papers_dc} papers) < All categories ({n_papers_all} papers)")

    def test_compute_time_is_reasonable(self):
        """Test that compute_time_s is present and reasonable"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation?category=cs.DC", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        compute_time = data.get("compute_time_s")
        assert compute_time is not None, "compute_time_s should be present"
        assert isinstance(compute_time, (int, float)), f"compute_time_s should be numeric, got {type(compute_time)}"
        assert compute_time >= 0, f"compute_time_s should be non-negative, got {compute_time}"
        
        print(f"PASS: compute_time_s = {compute_time}s")

    def test_methods_array_structure(self):
        """Test that methods array contains all 3 scoring methods"""
        response = requests.get(f"{BASE_URL}/api/scoring-method-correlation", timeout=120)
        assert response.status_code == 200
        data = response.json()
        
        methods = data.get("methods", [])
        assert len(methods) == 3, f"Expected 3 methods, got {len(methods)}"
        
        method_keys = [m["key"] for m in methods]
        expected_keys = ["win_rate", "bt", "trueskill"]
        for key in expected_keys:
            assert key in method_keys, f"Missing method key: {key}"
        
        # Verify labels
        for method in methods:
            assert "key" in method, "Method missing 'key' field"
            assert "label" in method, "Method missing 'label' field"
        
        print(f"PASS: methods array contains: {method_keys}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
