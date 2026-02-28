"""
Test ensemble (virtual tournament) modes: Majority Vote and Unanimity.
These modes are derived from multi-model (3 LLM) match data without new LLM calls.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
DATASET_ID = "iclr-llm"


class TestAvailableModes:
    """Test that ensemble modes appear in available-modes endpoint"""
    
    def test_available_modes_includes_majority(self):
        response = requests.get(f"{BASE_URL}/api/validation/available-modes?dataset_id={DATASET_ID}")
        assert response.status_code == 200
        data = response.json()
        
        modes = {m['id']: m for m in data['modes']}
        assert 'ensemble:majority' in modes, "Missing ensemble:majority mode"
        
        majority = modes['ensemble:majority']
        assert majority['label'] == 'Majority Vote (3 models)'
        assert majority['matches'] > 0
        print(f"Majority Vote mode: {majority['matches']} matches")
    
    def test_available_modes_includes_unanimity(self):
        response = requests.get(f"{BASE_URL}/api/validation/available-modes?dataset_id={DATASET_ID}")
        assert response.status_code == 200
        data = response.json()
        
        modes = {m['id']: m for m in data['modes']}
        assert 'ensemble:unanimity' in modes, "Missing ensemble:unanimity mode"
        
        unanimity = modes['ensemble:unanimity']
        assert unanimity['label'] == 'Unanimous (3/3 agree)'
        assert unanimity['matches'] > 0
        print(f"Unanimity mode: {unanimity['matches']} matches")


class TestPairwiseResults:
    """Test pairwise-results endpoint for ensemble modes"""
    
    def test_majority_pairwise_results(self):
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results?dataset_id={DATASET_ID}&content_mode=ensemble:majority")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert 'correlation' in data
        assert 'spearman_rho' in data['correlation']
        
        rho = data['correlation']['spearman_rho']
        assert -1 <= rho <= 1, f"Invalid spearman_rho: {rho}"
        print(f"Majority Vote Spearman ρ = {rho:.4f}")
        
        # Verify match count
        assert data['ai_matches'] > 1000, f"Expected >1000 matches, got {data['ai_matches']}"
    
    def test_unanimity_pairwise_results(self):
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results?dataset_id={DATASET_ID}&content_mode=ensemble:unanimity")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert 'correlation' in data
        assert 'spearman_rho' in data['correlation']
        
        rho = data['correlation']['spearman_rho']
        assert -1 <= rho <= 1, f"Invalid spearman_rho: {rho}"
        print(f"Unanimity Spearman ρ = {rho:.4f}")
        
        # Verify match count
        assert data['ai_matches'] > 500, f"Expected >500 matches, got {data['ai_matches']}"


class TestAgreementAnalysis:
    """Test agreement-analysis endpoint for ensemble modes"""
    
    def test_majority_agreement(self):
        response = requests.get(f"{BASE_URL}/api/validation/agreement-analysis?dataset_id={DATASET_ID}&content_mode=ensemble:majority")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert 'ai_expert' in data
        assert 'ai_majority' in data
        
        ai_expert_rate = data['ai_expert']['rate']
        assert 0 <= ai_expert_rate <= 100
        print(f"Majority Vote AI-Expert agreement: {ai_expert_rate}%")
    
    def test_unanimity_agreement(self):
        response = requests.get(f"{BASE_URL}/api/validation/agreement-analysis?dataset_id={DATASET_ID}&content_mode=ensemble:unanimity")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert 'ai_expert' in data
        assert 'ai_majority' in data
        
        ai_expert_rate = data['ai_expert']['rate']
        assert 0 <= ai_expert_rate <= 100
        print(f"Unanimity AI-Expert agreement: {ai_expert_rate}%")
    
    def test_unanimity_accuracy_higher_than_majority(self):
        """Sanity check: Unanimity should have higher accuracy than majority vote"""
        majority_resp = requests.get(f"{BASE_URL}/api/validation/agreement-analysis?dataset_id={DATASET_ID}&content_mode=ensemble:majority")
        unanimity_resp = requests.get(f"{BASE_URL}/api/validation/agreement-analysis?dataset_id={DATASET_ID}&content_mode=ensemble:unanimity")
        
        assert majority_resp.status_code == 200
        assert unanimity_resp.status_code == 200
        
        majority_rate = majority_resp.json()['ai_expert']['rate']
        unanimity_rate = unanimity_resp.json()['ai_expert']['rate']
        
        print(f"Majority AI-Expert: {majority_rate}%, Unanimity AI-Expert: {unanimity_rate}%")
        assert unanimity_rate > majority_rate, f"Expected unanimity ({unanimity_rate}%) > majority ({majority_rate}%)"


class TestConvergence:
    """Test convergence endpoint for ensemble modes"""
    
    def test_majority_convergence(self):
        response = requests.get(f"{BASE_URL}/api/validation/convergence?dataset_id={DATASET_ID}&content_mode=ensemble:majority")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert 'curve' in data
        assert len(data['curve']) > 0, "Empty convergence curve"
        
        # Check curve structure
        for point in data['curve']:
            assert 'matches' in point
            assert 'spearman' in point
        
        print(f"Majority Vote convergence curve has {len(data['curve'])} points")
    
    def test_unanimity_convergence(self):
        response = requests.get(f"{BASE_URL}/api/validation/convergence?dataset_id={DATASET_ID}&content_mode=ensemble:unanimity")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert 'curve' in data
        assert len(data['curve']) > 0, "Empty convergence curve"
        
        print(f"Unanimity convergence curve has {len(data['curve'])} points")
    
    def test_convergence_all_includes_ensemble_modes(self):
        """Verify convergence-all endpoint includes both ensemble modes"""
        response = requests.get(f"{BASE_URL}/api/validation/convergence-all?dataset_id={DATASET_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        modes = list(data['modes'].keys())
        
        assert 'ensemble:majority' in modes, f"Missing ensemble:majority in {modes}"
        assert 'ensemble:unanimity' in modes, f"Missing ensemble:unanimity in {modes}"
        
        print(f"All modes in convergence-all: {modes}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
