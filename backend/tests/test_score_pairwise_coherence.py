"""
Test Score-Pairwise Coherence feature in Model Analysis API
Tests the new coherence metric that measures how well single-item scores predict pairwise choices
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestScorePairwiseCoherence:
    """Tests for the score_pairwise_coherence feature in /api/model-analysis"""
    
    def test_coherence_key_exists(self):
        """Test that score_pairwise_coherence key is present in API response"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        assert "score_pairwise_coherence" in data, "score_pairwise_coherence key missing from response"
        print("PASS: score_pairwise_coherence key exists")
    
    def test_coherence_status_ok(self):
        """Test that coherence data has status=ok"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        assert coherence.get("status") == "ok", f"Expected status=ok, got {coherence.get('status')}"
        print("PASS: coherence status is ok")
    
    def test_coherence_has_three_models(self):
        """Test that coherence data contains claude, gpt, and gemini models"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        expected_models = {"claude", "gpt", "gemini"}
        actual_models = set(models.keys())
        assert expected_models == actual_models, f"Expected models {expected_models}, got {actual_models}"
        print(f"PASS: All 3 models present: {actual_models}")
    
    def test_model_has_required_fields(self):
        """Test that each model has label, total_pairs, overall_agreement, and bins"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            assert "label" in model_data, f"{model_key} missing 'label'"
            assert "total_pairs" in model_data, f"{model_key} missing 'total_pairs'"
            assert "overall_agreement" in model_data, f"{model_key} missing 'overall_agreement'"
            assert "bins" in model_data, f"{model_key} missing 'bins'"
            print(f"PASS: {model_key} has all required fields")
    
    def test_total_pairs_positive(self):
        """Test that total_pairs > 0 for each model"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            total_pairs = model_data.get("total_pairs", 0)
            assert total_pairs > 0, f"{model_key} has total_pairs={total_pairs}, expected > 0"
            print(f"PASS: {model_key} total_pairs={total_pairs} > 0")
    
    def test_overall_agreement_in_range(self):
        """Test that overall_agreement is between 0 and 1"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            agreement = model_data.get("overall_agreement")
            assert agreement is not None, f"{model_key} overall_agreement is None"
            assert 0 <= agreement <= 1, f"{model_key} overall_agreement={agreement}, expected 0-1"
            print(f"PASS: {model_key} overall_agreement={agreement} in [0,1]")
    
    def test_bins_count_is_six(self):
        """Test that each model has exactly 6 bins"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            bins = model_data.get("bins", [])
            assert len(bins) == 6, f"{model_key} has {len(bins)} bins, expected 6"
            print(f"PASS: {model_key} has 6 bins")
    
    def test_bin_has_required_fields(self):
        """Test that each bin has label, gap_min, gap_max, n, agreement_rate, reversal_rate"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        required_fields = ["label", "gap_min", "gap_max", "n", "agreement_rate", "reversal_rate"]
        
        for model_key, model_data in models.items():
            bins = model_data.get("bins", [])
            for i, bin_data in enumerate(bins):
                for field in required_fields:
                    assert field in bin_data, f"{model_key} bin {i} missing '{field}'"
            print(f"PASS: {model_key} bins have all required fields")
    
    def test_agreement_rate_monotonically_increasing(self):
        """Test that agreement rate generally increases as score gap increases"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            bins = model_data.get("bins", [])
            # Filter bins with valid agreement_rate and n > 0
            valid_bins = [b for b in bins if b.get("agreement_rate") is not None and b.get("n", 0) > 0]
            
            if len(valid_bins) < 2:
                print(f"SKIP: {model_key} has fewer than 2 valid bins")
                continue
            
            # Check that first bin < last bin (overall trend is increasing)
            first_rate = valid_bins[0].get("agreement_rate")
            last_rate = valid_bins[-1].get("agreement_rate")
            assert last_rate >= first_rate, f"{model_key}: first bin rate {first_rate} > last bin rate {last_rate}"
            print(f"PASS: {model_key} agreement rate increases from {first_rate:.3f} to {last_rate:.3f}")
    
    def test_category_filter_works(self):
        """Test that per-category filter returns coherence data"""
        response = requests.get(f"{BASE_URL}/api/model-analysis", params={"category": "cs.RO"})
        assert response.status_code == 200
        data = response.json()
        
        coherence = data.get("score_pairwise_coherence")
        # Coherence may be None for categories with insufficient data
        if coherence is None:
            print("SKIP: cs.RO category has no coherence data (insufficient data)")
            return
        
        assert coherence.get("status") == "ok", f"Expected status=ok for cs.RO, got {coherence.get('status')}"
        models = coherence.get("models", {})
        assert len(models) > 0, "Expected at least one model for cs.RO category"
        print(f"PASS: cs.RO category returns coherence data with {len(models)} models")
    
    def test_gpt_narrow_score_range(self):
        """Test that GPT has fewer pairs at high score gaps (known behavior)"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        gpt = models.get("gpt", {})
        bins = gpt.get("bins", [])
        
        # GPT should have very few pairs at high score gaps (2-3 and 3+)
        high_gap_bins = [b for b in bins if b.get("gap_min", 0) >= 2.0]
        total_high_gap = sum(b.get("n", 0) for b in high_gap_bins)
        
        # Claude should have more pairs at high score gaps
        claude = models.get("claude", {})
        claude_bins = claude.get("bins", [])
        claude_high_gap = [b for b in claude_bins if b.get("gap_min", 0) >= 2.0]
        claude_total_high_gap = sum(b.get("n", 0) for b in claude_high_gap)
        
        print(f"GPT high gap pairs (>=2.0): {total_high_gap}")
        print(f"Claude high gap pairs (>=2.0): {claude_total_high_gap}")
        
        # GPT should have significantly fewer high-gap pairs than Claude
        assert total_high_gap < claude_total_high_gap, "GPT should have fewer high-gap pairs than Claude"
        print("PASS: GPT has narrow score range (fewer high-gap pairs)")


class TestCoherenceIntegration:
    """Integration tests for coherence section"""
    
    def test_api_response_time(self):
        """Test that API responds within reasonable time"""
        import time
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 30, f"API took {elapsed:.2f}s, expected < 30s"
        print(f"PASS: API responded in {elapsed:.2f}s")
    
    def test_coherence_data_consistency(self):
        """Test that coherence data is internally consistent"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            bins = model_data.get("bins", [])
            total_n = sum(b.get("n", 0) for b in bins)
            reported_total = model_data.get("total_pairs", 0)
            
            # Total pairs should equal sum of bin counts
            assert total_n == reported_total, f"{model_key}: sum of bins ({total_n}) != total_pairs ({reported_total})"
            print(f"PASS: {model_key} bin sum ({total_n}) matches total_pairs")
    
    def test_agreement_plus_reversal_equals_one(self):
        """Test that agreement_rate + reversal_rate = 1 for each bin"""
        response = requests.get(f"{BASE_URL}/api/model-analysis")
        assert response.status_code == 200
        data = response.json()
        coherence = data.get("score_pairwise_coherence", {})
        models = coherence.get("models", {})
        
        for model_key, model_data in models.items():
            bins = model_data.get("bins", [])
            for i, bin_data in enumerate(bins):
                if bin_data.get("n", 0) == 0:
                    continue  # Skip empty bins
                agreement = bin_data.get("agreement_rate")
                reversal = bin_data.get("reversal_rate")
                if agreement is not None and reversal is not None:
                    total = agreement + reversal
                    assert abs(total - 1.0) < 0.01, f"{model_key} bin {i}: agreement + reversal = {total}, expected 1.0"
            print(f"PASS: {model_key} agreement + reversal = 1.0 for all bins")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
