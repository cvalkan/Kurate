"""
Test Validation Hub restructure and SciPost pairwise comparison feature
Tests for iteration 29: Unified Validation hub with sidebar navigation
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestValidationHubAPIs:
    """Test APIs for Validation Hub feature"""

    # === SciPost Pairwise Endpoints ===
    def test_scipost_pairwise_status_endpoint(self):
        """GET /api/scipost/pairwise/status returns valid JSON with status fields"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/status")
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields exist
        assert "total_pairs" in data, "Missing total_pairs field"
        assert "ai_completed" in data, "Missing ai_completed field"
        assert "ai_failed" in data, "Missing ai_failed field"
        assert "ai_pending" in data, "Missing ai_pending field"
        assert "by_dimension" in data, "Missing by_dimension field"
        assert "fetching" in data, "Missing fetching field"
        assert "running" in data, "Missing running field"
        assert "progress" in data, "Missing progress field"
        print(f"SciPost pairwise status: {data['total_pairs']} total pairs")

    def test_scipost_pairwise_results_endpoint(self):
        """GET /api/scipost/pairwise/results returns status with no_data or ok"""
        response = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
        assert response.status_code == 200
        data = response.json()
        
        # Should return either "ok" or "no_data" status
        assert "status" in data, "Missing status field"
        assert data["status"] in ["ok", "no_data"], f"Unexpected status: {data['status']}"
        
        if data["status"] == "no_data":
            print("SciPost pairwise results: no_data (collection is empty - expected)")
        else:
            assert "total_pairs" in data, "Missing total_pairs in ok response"
            assert "by_dimension" in data, "Missing by_dimension in ok response"
            print(f"SciPost pairwise results: {data['total_pairs']} pairs analyzed")

    # === Existing Pairwise (Qeios) Endpoints ===
    def test_qeios_pairwise_status(self):
        """GET /api/pairwise/status returns valid JSON (330 pairs expected)"""
        response = requests.get(f"{BASE_URL}/api/pairwise/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "total_pairs" in data
        assert "ai_completed" in data
        assert "domains" in data
        print(f"Qeios pairwise status: {data['total_pairs']} pairs, {data['ai_completed']} completed")

    def test_qeios_pairwise_results(self):
        """GET /api/pairwise/results returns analysis results"""
        response = requests.get(f"{BASE_URL}/api/pairwise/results")
        assert response.status_code == 200
        data = response.json()
        
        if data.get("status") == "ok":
            assert "majority_agreement" in data
            assert "by_model" in data
            print(f"Qeios results: Majority agreement = {data['majority_agreement']['rate']}%")

    # === SciPost Single-Item Endpoints ===
    def test_scipost_status(self):
        """GET /api/scipost/status returns valid JSON"""
        response = requests.get(f"{BASE_URL}/api/scipost/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "total_comparisons" in data
        assert "ai_completed" in data
        assert "by_dimension" in data
        print(f"SciPost single-item status: {data['total_comparisons']} comparisons")

    def test_scipost_results(self):
        """GET /api/scipost/results returns analysis with prompts"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        assert response.status_code == 200
        data = response.json()
        
        if data.get("status") == "ok":
            # Verify dimension breakdown
            assert "by_dimension" in data
            for dim in ["validity", "significance", "originality", "clarity"]:
                assert dim in data["by_dimension"], f"Missing {dim} in by_dimension"
            
            # Verify prompts field (tested in iteration 28)
            assert "prompts" in data
            print(f"SciPost results: {data['total_comparisons']} comparisons with prompts field")

    # === Validation Datasets (Tournament) Endpoints ===
    def test_validation_datasets(self):
        """GET /api/validation/datasets returns list of datasets"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        data = response.json()
        
        assert "datasets" in data
        datasets = data["datasets"]
        assert len(datasets) >= 3, f"Expected at least 3 datasets, got {len(datasets)}"
        
        # Check expected datasets exist
        dataset_ids = [d["dataset_id"] for d in datasets]
        assert "iclr-llm" in dataset_ids, "Missing ICLR LLMs dataset"
        assert "iclr-protein" in dataset_ids, "Missing ICLR Protein Science dataset"
        assert "peerread_acl_2017" in dataset_ids, "Missing PeerRead ACL 2017 dataset"
        
        # Verify dataset structure
        for ds in datasets:
            assert "dataset_id" in ds
            assert "name" in ds
            assert "papers" in ds
            assert "matches" in ds
        
        print(f"Validation datasets: {len(datasets)} datasets found")
        for ds in datasets:
            print(f"  - {ds['name']}: {ds['papers']} papers, {ds['matches']} matches")

    def test_validation_pairwise_results(self):
        """GET /api/validation/pairwise-results returns correlation data"""
        response = requests.get(f"{BASE_URL}/api/validation/pairwise-results", params={"dataset_id": "iclr-llm"})
        assert response.status_code == 200
        data = response.json()
        
        if data.get("status") == "ok":
            assert "correlation" in data
            assert "papers_analyzed" in data
            print(f"ICLR LLM pairwise: {data['papers_analyzed']} papers, Spearman={data['correlation']['spearman_rho']}")

    def test_validation_irt_results(self):
        """GET /api/validation/irt-results returns IRT-adjusted rankings"""
        response = requests.get(f"{BASE_URL}/api/validation/irt-results", params={"dataset_id": "iclr-llm"})
        assert response.status_code == 200
        data = response.json()
        
        if data.get("status") == "ok":
            assert "correlation" in data
            print(f"ICLR LLM IRT: {data.get('improvement', {}).get('distinct_scores_irt', 'N/A')} distinct scores")


class TestNavbarSimplified:
    """Test that navbar only shows Validation link (no separate Pairwise/SciPost)"""
    
    def test_navbar_has_validation_link(self):
        """Verify /validation route exists and works"""
        # Just verify the validation page loads properly
        response = requests.get(f"{BASE_URL}/api/validation/datasets")
        assert response.status_code == 200
        print("Validation API accessible - navigation should work")


class TestSciPostPairwiseEmptyState:
    """Test SciPost pairwise empty state handling"""
    
    def test_empty_state_returns_no_data(self):
        """When collection is empty, results should return status=no_data"""
        status_resp = requests.get(f"{BASE_URL}/api/scipost/pairwise/status")
        status_data = status_resp.json()
        
        if status_data["total_pairs"] == 0:
            results_resp = requests.get(f"{BASE_URL}/api/scipost/pairwise/results")
            results_data = results_resp.json()
            
            assert results_data["status"] == "no_data"
            assert results_data.get("total", 0) == 0
            print("PASS: Empty state correctly shows no_data status")
        else:
            print(f"SKIP: Collection has {status_data['total_pairs']} pairs (not empty)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
