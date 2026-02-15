"""
Test Summary Bias Experiment endpoints
- GET /api/summary-bias/status - Returns pipeline status and counts
- GET /api/summary-bias/results - Returns experiment results with grids and bias metrics
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

class TestSummaryBiasStatus:
    """Tests for GET /api/summary-bias/status endpoint"""
    
    def test_status_endpoint_returns_200(self):
        """Status endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/status?category=q-bio.BM")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Status endpoint returns 200")
    
    def test_status_contains_required_fields(self):
        """Status should contain all required fields"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/status?category=q-bio.BM")
        data = response.json()
        
        required_fields = ["category", "summaries_generated", "summaries_per_model", 
                         "matches_completed", "matches_failed", "phase", "progress"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        print(f"✓ Status contains all required fields: {list(data.keys())}")
    
    def test_status_summaries_generated_150(self):
        """Should have 150 summaries (50 papers x 3 models)"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/status?category=q-bio.BM")
        data = response.json()
        
        assert data["summaries_generated"] == 150, f"Expected 150 summaries, got {data['summaries_generated']}"
        print(f"✓ Summaries generated: {data['summaries_generated']}")
    
    def test_status_matches_completed_1800(self):
        """Should have 1800 matches (200 matches x 9 configs)"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/status?category=q-bio.BM")
        data = response.json()
        
        assert data["matches_completed"] == 1800, f"Expected 1800 matches, got {data['matches_completed']}"
        print(f"✓ Matches completed: {data['matches_completed']}")
    
    def test_status_summaries_per_model_3_items(self):
        """Summaries per model should have 3 model entries"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/status?category=q-bio.BM")
        data = response.json()
        
        assert len(data["summaries_per_model"]) == 3, f"Expected 3 models, got {len(data['summaries_per_model'])}"
        # Each model should have 50 summaries
        for model_key, count in data["summaries_per_model"].items():
            assert count == 50, f"Model {model_key} should have 50 summaries, got {count}"
        print(f"✓ Summaries per model: {data['summaries_per_model']}")


class TestSummaryBiasResults:
    """Tests for GET /api/summary-bias/results endpoint"""
    
    def test_results_endpoint_returns_200(self):
        """Results endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Results endpoint returns 200")
    
    def test_results_status_ok(self):
        """Results should have status=ok"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        assert data["status"] == "ok", f"Expected status 'ok', got {data.get('status')}"
        print(f"✓ Results status: {data['status']}")
    
    def test_results_contains_all_required_fields(self):
        """Results should contain all required analysis fields"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        required_fields = ["status", "category", "num_matches", "total_evaluations",
                         "judges", "summarizers", "grid_consensus", "grid_original",
                         "self_bias", "judge_consistency", "summary_influence"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        print(f"✓ Results contains all required fields")
    
    def test_results_judges_3_items(self):
        """Should have 3 judges"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        assert len(data["judges"]) == 3, f"Expected 3 judges, got {len(data['judges'])}"
        expected_judges = ["Claude Opus", "Gemini 3", "GPT 5.2"]
        for judge in expected_judges:
            assert judge in data["judges"], f"Missing judge: {judge}"
        print(f"✓ Judges: {data['judges']}")
    
    def test_results_summarizers_3_items(self):
        """Should have 3 summarizers"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        assert len(data["summarizers"]) == 3, f"Expected 3 summarizers, got {len(data['summarizers'])}"
        expected_summarizers = ["Claude Opus", "Gemini 3", "GPT 5.2"]
        for summarizer in expected_summarizers:
            assert summarizer in data["summarizers"], f"Missing summarizer: {summarizer}"
        print(f"✓ Summarizers: {data['summarizers']}")
    
    def test_results_grid_consensus_3x3(self):
        """grid_consensus should be a 3x3 array"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        grid = data["grid_consensus"]
        assert len(grid) == 3, f"Expected 3 rows, got {len(grid)}"
        for i, row in enumerate(grid):
            assert len(row) == 3, f"Row {i} should have 3 columns, got {len(row)}"
        print(f"✓ grid_consensus is 3x3: {grid}")
    
    def test_results_grid_original_3x3(self):
        """grid_original should be a 3x3 array"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        grid = data["grid_original"]
        assert len(grid) == 3, f"Expected 3 rows, got {len(grid)}"
        for i, row in enumerate(grid):
            assert len(row) == 3, f"Row {i} should have 3 columns, got {len(row)}"
        print(f"✓ grid_original is 3x3: {grid}")
    
    def test_results_self_bias_structure(self):
        """self_bias should have entries for each model with own_summary_rate, other_summary_avg, bias"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        self_bias = data["self_bias"]
        expected_models = ["Claude Opus", "Gemini 3", "GPT 5.2"]
        for model in expected_models:
            assert model in self_bias, f"Missing self_bias entry for {model}"
            entry = self_bias[model]
            assert "own_summary_rate" in entry, f"Missing own_summary_rate for {model}"
            assert "other_summary_avg" in entry, f"Missing other_summary_avg for {model}"
            assert "bias" in entry, f"Missing bias for {model}"
        print(f"✓ self_bias has correct structure: {list(self_bias.keys())}")
    
    def test_results_judge_consistency_structure(self):
        """judge_consistency should have avg_agreement and pairs for each summarizer"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        jc = data["judge_consistency"]
        assert len(jc) == 3, f"Expected 3 summarizers in judge_consistency, got {len(jc)}"
        for summarizer, entry in jc.items():
            assert "avg_agreement" in entry, f"Missing avg_agreement for {summarizer}"
            assert "pairs" in entry, f"Missing pairs for {summarizer}"
        print(f"✓ judge_consistency has correct structure")
    
    def test_results_summary_influence_structure(self):
        """summary_influence should have avg_consistency and pairs for each judge"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        si = data["summary_influence"]
        assert len(si) == 3, f"Expected 3 judges in summary_influence, got {len(si)}"
        for judge, entry in si.items():
            assert "avg_consistency" in entry, f"Missing avg_consistency for {judge}"
            assert "pairs" in entry, f"Missing pairs for {judge}"
        print(f"✓ summary_influence has correct structure")
    
    def test_results_num_matches_200(self):
        """Should have analyzed 200 matches"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        assert data["num_matches"] == 200, f"Expected 200 matches, got {data['num_matches']}"
        print(f"✓ num_matches: {data['num_matches']}")
    
    def test_results_total_evaluations_1800(self):
        """Should have 1800 total evaluations (200 x 9)"""
        response = requests.get(f"{BASE_URL}/api/summary-bias/results?category=q-bio.BM")
        data = response.json()
        
        assert data["total_evaluations"] == 1800, f"Expected 1800 evaluations, got {data['total_evaluations']}"
        print(f"✓ total_evaluations: {data['total_evaluations']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
