"""
Backend tests for Tie-Allowed Experiment feature.
Tests the tie experiment endpoints that allow AI judges to declare ties.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ai-review-hub-25.preview.emergentagent.com').rstrip('/')


class TestTieExperimentEndpoints:
    """Tests for tie experiment endpoints"""
    
    def test_tie_experiment_status(self):
        """GET /api/validation/tie-experiment/status returns correct status"""
        response = requests.get(f"{BASE_URL}/api/validation/tie-experiment/status")
        assert response.status_code == 200
        
        data = response.json()
        # Verify expected fields exist
        assert "running" in data
        assert "done" in data
        assert "total" in data
        assert "ties" in data
        
        # Verify data types
        assert isinstance(data["running"], bool)
        assert isinstance(data["done"], int)
        assert isinstance(data["total"], int)
        assert isinstance(data["ties"], int)
        
        # Experiment should not be running (it's completed)
        assert data["running"] is False
        print(f"PASS: Tie experiment status returned - running={data['running']}, done={data['done']}, ties={data['ties']}")
    
    def test_tie_experiment_results(self):
        """GET /api/validation/tie-experiment/results returns full analysis"""
        response = requests.get(f"{BASE_URL}/api/validation/tie-experiment/results")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        
        # Verify key metrics exist
        assert "tie_matches" in data
        assert "baseline_accuracy" in data
        assert "tie_accuracy_non_tie" in data
        assert "tie_rate" in data
        assert "total_ties" in data
        assert "lift" in data
        assert "mcnemar" in data
        assert "tie_calibration" in data
        assert "by_dataset" in data
        
        # Verify mcnemar test fields
        mcnemar = data["mcnemar"]
        assert "non_tie_pairs" in mcnemar
        assert "only_baseline" in mcnemar
        assert "only_tie" in mcnemar
        assert "p_value" in mcnemar
        assert "significant" in mcnemar
        
        # Verify tie_calibration fields
        calib = data["tie_calibration"]
        assert "close_pairs_tied" in calib
        assert "far_pairs_tied" in calib
        assert "calibration_ratio" in calib
        
        # Verify by_dataset has iclr-llm
        assert "iclr-llm" in data["by_dataset"]
        iclr_data = data["by_dataset"]["iclr-llm"]
        assert "gap_analysis" in iclr_data
        
        # Verify gap analysis breakdown
        gap = iclr_data["gap_analysis"]
        assert "small" in gap or "medium" in gap or "large" in gap
        
        print(f"PASS: Tie experiment results - {data['tie_matches']} matches, {data['tie_rate']}% tie rate, baseline {data['baseline_accuracy']}%, tie non-tie {data['tie_accuracy_non_tie']}%")
    
    def test_tie_experiment_results_values(self):
        """Verify specific expected values from the completed experiment"""
        response = requests.get(f"{BASE_URL}/api/validation/tie-experiment/results")
        data = response.json()
        
        # Verify completed experiment data matches expected
        # 500 matches completed, 2 ties (0.4% tie rate), baseline 80.9% vs tie non-tie 81.7%
        assert data["tie_matches"] == 500, f"Expected 500 matches, got {data['tie_matches']}"
        assert data["total_ties"] == 2, f"Expected 2 ties, got {data['total_ties']}"
        assert abs(data["tie_rate"] - 0.4) < 0.1, f"Expected ~0.4% tie rate, got {data['tie_rate']}%"
        assert abs(data["baseline_accuracy"] - 80.9) < 1, f"Expected ~80.9% baseline, got {data['baseline_accuracy']}%"
        assert abs(data["tie_accuracy_non_tie"] - 81.7) < 1, f"Expected ~81.7% tie non-tie, got {data['tie_accuracy_non_tie']}%"
        
        print(f"PASS: Tie experiment values verified - 500 matches, 2 ties, 80.9% baseline, 81.7% non-tie accuracy")


class TestAvailableModes:
    """Tests for available modes endpoint with tie mode"""
    
    def test_available_modes_includes_tie(self):
        """GET /api/validation/available-modes?dataset_id=iclr-llm includes tie_v1"""
        response = requests.get(f"{BASE_URL}/api/validation/available-modes?dataset_id=iclr-llm")
        assert response.status_code == 200
        
        data = response.json()
        assert "modes" in data
        
        # Find tie mode
        tie_mode = None
        for mode in data["modes"]:
            if "tie_v1" in str(mode.get("id", "")) or "tie_v1" in str(mode.get("prompt_tag", "")):
                tie_mode = mode
                break
        
        assert tie_mode is not None, f"Tie mode not found in modes: {data['modes']}"
        assert tie_mode["label"] == "Abstract + Summary (Tie-Allowed)", f"Wrong label: {tie_mode['label']}"
        assert tie_mode["matches"] == 500, f"Expected 500 matches, got {tie_mode['matches']}"
        
        print(f"PASS: Tie mode found - {tie_mode['label']} with {tie_mode['matches']} matches")


class TestConvergenceWithTieMode:
    """Tests for convergence endpoint with tie mode"""
    
    def test_convergence_tie_mode(self):
        """GET /api/validation/convergence with tie mode returns valid curve"""
        response = requests.get(
            f"{BASE_URL}/api/validation/convergence",
            params={"dataset_id": "iclr-llm", "content_mode": "abstract_plus_summary:tie_v1"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["dataset_id"] == "iclr-llm"
        assert data["content_mode"] == "abstract_plus_summary:tie_v1"
        
        # Verify convergence curve data
        assert "curve" in data
        assert "total_matches" in data
        assert data["total_matches"] == 500, f"Expected 500 matches, got {data['total_matches']}"
        
        # Verify curve is not empty
        assert len(data["curve"]) > 0, "Convergence curve is empty"
        
        # Verify curve points have expected fields
        point = data["curve"][-1] if data["curve"] else {}
        assert "matches" in point
        assert "spearman" in point
        
        print(f"PASS: Convergence curve for tie mode - {data['total_matches']} matches, {len(data['curve'])} curve points")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
