"""
Backend API tests for SciPost Pairwise bug fix verification
Tests the fix for KeyError caused by unescaped curly braces in prompt template
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSciPostPairwiseStatus:
    """Test /api/scipost/pairwise/status endpoint"""
    
    def test_status_returns_200(self):
        """Test that status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/status")
        assert response.status_code == 200
        print("SUCCESS: /api/scipost/pairwise/status returns 200")
    
    def test_status_has_required_fields(self):
        """Test that status has all required fields"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/status")
        data = response.json()
        
        required_fields = ["total_pairs", "ai_completed", "ai_failed", "ai_pending", "by_dimension", "fetching", "running", "progress"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        print(f"SUCCESS: Status has all required fields: {required_fields}")
    
    def test_status_shows_3_completed_pairs(self):
        """Test that status shows 3 completed pairs (from the fix verification)"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/status")
        data = response.json()
        
        assert data["total_pairs"] == 3, f"Expected 3 total pairs, got {data['total_pairs']}"
        assert data["ai_completed"] == 3, f"Expected 3 ai_completed, got {data['ai_completed']}"
        assert data["ai_failed"] == 0, f"Expected 0 ai_failed, got {data['ai_failed']}"
        print(f"SUCCESS: Status shows correct counts - total=3, completed=3, failed=0")
    
    def test_status_by_dimension_has_validity(self):
        """Test that by_dimension has validity with 3 pairs"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/status")
        data = response.json()
        
        assert "validity" in data["by_dimension"], "Missing 'validity' in by_dimension"
        assert data["by_dimension"]["validity"] == 3, f"Expected 3 validity pairs, got {data['by_dimension']['validity']}"
        print("SUCCESS: by_dimension shows validity=3")


class TestSciPostPairwiseResults:
    """Test /api/scipost/pairwise/results endpoint"""
    
    def test_results_returns_200(self):
        """Test that results endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        assert response.status_code == 200
        print("SUCCESS: /api/scipost/pairwise/results returns 200")
    
    def test_results_status_is_ok(self):
        """Test that results returns status=ok"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        assert data["status"] == "ok", f"Expected status=ok, got {data['status']}"
        print("SUCCESS: Results returns status=ok")
    
    def test_results_has_valid_data_structure(self):
        """Test that results has valid data structure"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        required_fields = ["total_pairs", "overall_majority", "by_dimension", "inter_model", "samples"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        print(f"SUCCESS: Results has all required fields: {required_fields}")
    
    def test_results_overall_majority_is_valid(self):
        """Test that overall_majority has valid agreement rates"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        overall = data["overall_majority"]
        assert "agree" in overall, "Missing 'agree' in overall_majority"
        assert "total" in overall, "Missing 'total' in overall_majority"
        assert "rate" in overall, "Missing 'rate' in overall_majority"
        
        # Verify 100% agreement (3/3 pairs agree as per bug fix verification)
        assert overall["agree"] == 3, f"Expected 3 agree, got {overall['agree']}"
        assert overall["total"] == 3, f"Expected 3 total, got {overall['total']}"
        assert overall["rate"] == 100.0, f"Expected 100.0% rate, got {overall['rate']}"
        print(f"SUCCESS: Overall majority shows 100% agreement (3/3 pairs)")
    
    def test_results_by_dimension_validity(self):
        """Test that by_dimension has validity with model breakdown"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        assert "validity" in data["by_dimension"], "Missing 'validity' in by_dimension"
        validity = data["by_dimension"]["validity"]
        
        assert "majority" in validity, "Missing 'majority' in validity"
        assert "by_model" in validity, "Missing 'by_model' in validity"
        assert "by_gap" in validity, "Missing 'by_gap' in validity"
        
        # Verify majority agreement rate
        assert validity["majority"]["rate"] == 100.0, f"Expected 100% majority rate, got {validity['majority']['rate']}"
        print(f"SUCCESS: by_dimension.validity shows 100% majority agreement")
    
    def test_results_has_3_models(self):
        """Test that results has 3 AI models (GPT-5.2, Claude Opus, Gemini 3 Pro)"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        by_model = data["by_dimension"]["validity"]["by_model"]
        expected_models = ["openai:gpt-5.2", "anthropic:claude-opus-4-5-20251101", "gemini:gemini-3-pro-preview"]
        
        for model in expected_models:
            assert model in by_model, f"Missing model: {model}"
        print(f"SUCCESS: Results has all 3 expected models")
    
    def test_results_samples_not_empty(self):
        """Test that samples array has 3 samples"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        assert len(data["samples"]) == 3, f"Expected 3 samples, got {len(data['samples'])}"
        print(f"SUCCESS: Results has 3 samples")
    
    def test_results_samples_have_required_fields(self):
        """Test that each sample has required fields"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        required_fields = ["dimension", "paper1_title", "paper2_title", "human_winner", "human_score1", "human_score2", "ai_majority", "majority_agree", "models_agree", "models_total", "score_gap"]
        
        for sample in data["samples"]:
            for field in required_fields:
                assert field in sample, f"Missing field '{field}' in sample"
        print(f"SUCCESS: All samples have required fields")
    
    def test_results_inter_model_agreement(self):
        """Test that inter_model agreement data is present"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        data = response.json()
        
        assert len(data["inter_model"]) > 0, "inter_model should not be empty"
        
        # Check structure of inter_model entries
        for key, value in data["inter_model"].items():
            assert "agree" in value, f"Missing 'agree' in inter_model[{key}]"
            assert "total" in value, f"Missing 'total' in inter_model[{key}]"
            assert "rate" in value, f"Missing 'rate' in inter_model[{key}]"
        print(f"SUCCESS: inter_model agreement data is valid")


class TestOtherValidationEndpoints:
    """Test other validation hub endpoints still work"""
    
    def test_qeios_pairwise_status(self):
        """Test Qeios pairwise status endpoint"""
        response = requests.get(f"{BASE_URL}/api/pairwise/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_pairs"] == 330, f"Expected 330 Qeios pairs, got {data['total_pairs']}"
        print("SUCCESS: Qeios pairwise status shows 330 pairs")
    
    def test_qeios_pairwise_results(self):
        """Test Qeios pairwise results endpoint"""
        response = requests.get(f"{BASE_URL}/api/pairwise/results")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        print("SUCCESS: Qeios pairwise results returns ok")
    
    def test_scipost_single_item_status(self):
        """Test SciPost single-item status endpoint"""
        response = requests.get(f"{BASE_URL}/api/scipost/status")
        assert response.status_code == 200
        data = response.json()
        assert "total_comparisons" in data
        print(f"SUCCESS: SciPost single-item status shows {data['total_comparisons']} comparisons")
    
    def test_scipost_single_item_results(self):
        """Test SciPost single-item results endpoint"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "prompts" in data, "Missing 'prompts' field"
        print("SUCCESS: SciPost single-item results returns ok with prompts")
    
    def test_validation_datasets(self):
        """Test validation datasets endpoint"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        data = response.json()
        assert len(data["datasets"]) == 3, f"Expected 3 datasets, got {len(data['datasets'])}"
        print("SUCCESS: Validation datasets returns 3 datasets")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
