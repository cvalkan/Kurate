"""
SciPost Dimension Analysis improvements tests - Iteration 28
Features tested:
- Referee ID column in results (samples include 'referee' and 'submission_id' fields)
- Prompts field in results (template, dimension_tasks, system keys)
- Backend responses have correct structure for new tooltip information
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

class TestSciPostStatus:
    """Test /api/scipost/status endpoint"""
    
    def test_status_endpoint_returns_200(self):
        response = requests.get(f"{BASE_URL}/api/scipost/status")
        assert response.status_code == 200, f"Status endpoint failed: {response.text}"
        print("✓ GET /api/scipost/status returns 200")
    
    def test_status_has_required_fields(self):
        response = requests.get(f"{BASE_URL}/api/scipost/status")
        data = response.json()
        required_fields = ['total_comparisons', 'ai_completed', 'ai_failed', 'ai_pending', 'by_dimension']
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        print(f"✓ Status has required fields: {required_fields}")


class TestSciPostResults:
    """Test /api/scipost/results endpoint - New features: prompts and referee fields"""
    
    def test_results_endpoint_returns_200(self):
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        assert response.status_code == 200, f"Results endpoint failed: {response.text}"
        print("✓ GET /api/scipost/results returns 200")
    
    def test_results_has_status_ok(self):
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        assert data.get('status') == 'ok', f"Expected status=ok, got: {data.get('status')}"
        print("✓ Results returns status=ok")
    
    def test_results_has_total_comparisons(self):
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        total = data.get('total_comparisons', 0)
        assert total > 0, f"Expected total_comparisons > 0, got: {total}"
        print(f"✓ Results has {total} total comparisons")
    
    # ------ NEW FEATURE: Prompts field ------
    def test_results_has_prompts_field(self):
        """Verify results contain prompts field for 'View LLM Prompts' feature"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        assert 'prompts' in data, "Missing 'prompts' field in results"
        print("✓ Results has 'prompts' field")
    
    def test_prompts_has_template_key(self):
        """Verify prompts contain template key"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        prompts = data.get('prompts', {})
        assert 'template' in prompts, "Missing 'template' key in prompts"
        assert len(prompts['template']) > 100, "Template appears too short"
        print(f"✓ Prompts has 'template' key with {len(prompts['template'])} chars")
    
    def test_prompts_has_dimension_tasks_key(self):
        """Verify prompts contain dimension_tasks for all 4 dimensions"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        prompts = data.get('prompts', {})
        assert 'dimension_tasks' in prompts, "Missing 'dimension_tasks' key in prompts"
        dimension_tasks = prompts['dimension_tasks']
        expected_dims = ['validity', 'significance', 'originality', 'clarity']
        for dim in expected_dims:
            assert dim in dimension_tasks, f"Missing dimension task for: {dim}"
            assert len(dimension_tasks[dim]) > 20, f"Dimension task for {dim} too short"
        print(f"✓ Prompts has dimension_tasks for: {expected_dims}")
    
    def test_prompts_has_system_key(self):
        """Verify prompts contain system prompt"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        prompts = data.get('prompts', {})
        assert 'system' in prompts, "Missing 'system' key in prompts"
        assert len(prompts['system']) > 10, "System prompt appears too short"
        print(f"✓ Prompts has 'system' key: '{prompts['system'][:50]}...'")
    
    # ------ NEW FEATURE: Referee field in samples ------
    def test_samples_has_referee_field(self):
        """Verify samples include referee field for 'Why papers repeat' explanation"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        samples = data.get('samples', [])
        assert len(samples) > 0, "No samples returned"
        
        # Check first 5 samples have referee field
        for i, sample in enumerate(samples[:5]):
            assert 'referee' in sample, f"Sample {i} missing 'referee' field"
            assert sample['referee'], f"Sample {i} has empty referee field"
        print(f"✓ Samples have 'referee' field (e.g., '{samples[0].get('referee')}')")
    
    def test_samples_has_submission_id_field(self):
        """Verify samples include submission_id field"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        samples = data.get('samples', [])
        assert len(samples) > 0, "No samples returned"
        
        # Check first 5 samples have submission_id field
        for i, sample in enumerate(samples[:5]):
            assert 'submission_id' in sample, f"Sample {i} missing 'submission_id' field"
            assert sample['submission_id'], f"Sample {i} has empty submission_id field"
        print(f"✓ Samples have 'submission_id' field (e.g., '{samples[0].get('submission_id')}')")
    
    def test_samples_have_dimension_field(self):
        """Verify samples have dimension field showing which dimension was evaluated"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        samples = data.get('samples', [])
        assert len(samples) > 0, "No samples returned"
        
        valid_dimensions = ['validity', 'significance', 'originality', 'clarity']
        for i, sample in enumerate(samples[:5]):
            assert 'dimension' in sample, f"Sample {i} missing 'dimension' field"
            assert sample['dimension'] in valid_dimensions, f"Sample {i} has invalid dimension: {sample['dimension']}"
        print(f"✓ Samples have valid 'dimension' field")
    
    def test_same_paper_multiple_referees(self):
        """Verify the same paper can appear with different referees (explains why papers repeat)"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        samples = data.get('samples', [])
        
        # Group by submission_id and count unique referees
        paper_referees = {}
        for sample in samples:
            sid = sample.get('submission_id')
            referee = sample.get('referee')
            if sid and referee:
                if sid not in paper_referees:
                    paper_referees[sid] = set()
                paper_referees[sid].add(referee)
        
        # Find papers with multiple referees
        papers_with_multiple = {k: v for k, v in paper_referees.items() if len(v) > 1}
        print(f"✓ Found {len(papers_with_multiple)} papers with multiple referees")
        if papers_with_multiple:
            example_sid = list(papers_with_multiple.keys())[0]
            print(f"  Example: {example_sid} has referees: {papers_with_multiple[example_sid]}")
    
    # ------ Data structure verification ------
    def test_by_dimension_structure(self):
        """Verify by_dimension has stats for all 4 dimensions"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        by_dim = data.get('by_dimension', {})
        expected_dims = ['validity', 'significance', 'originality', 'clarity']
        
        for dim in expected_dims:
            assert dim in by_dim, f"Missing dimension: {dim}"
            dim_stats = by_dim[dim]
            assert 'close_rate' in dim_stats, f"Missing close_rate for {dim}"
            assert 'mae' in dim_stats, f"Missing mae for {dim}"
            assert 'total' in dim_stats, f"Missing total for {dim}"
        print(f"✓ by_dimension has stats for all dimensions: {expected_dims}")
    
    def test_model_overall_structure(self):
        """Verify model_overall has per-model accuracy"""
        response = requests.get(f"{BASE_URL}/api/scipost/results")
        data = response.json()
        model_overall = data.get('model_overall', {})
        
        assert len(model_overall) > 0, "model_overall is empty"
        for model_key, stats in model_overall.items():
            assert 'close_rate' in stats, f"Missing close_rate for model: {model_key}"
            assert 'total' in stats, f"Missing total for model: {model_key}"
        print(f"✓ model_overall has {len(model_overall)} models with close_rate and total")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
