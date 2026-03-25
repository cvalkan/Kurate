"""
Test Inter-Model Agreement Feature
Tests the PW Inter-Model and SI Inter-Model tables on the Model Analysis page.
- PW Inter-Model: Shows how similarly models rank papers from their pairwise matches
- SI Inter-Model: Shows how similarly models rate papers directly with Spearman ρ
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPWInterModelAgreement:
    """Tests for PW Inter-Model data in /api/model-correlation endpoint"""
    
    def test_model_correlation_returns_pw_inter_model(self):
        """GET /api/model-correlation returns pw_inter_model array"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        assert "pw_inter_model" in data
        assert isinstance(data["pw_inter_model"], list)
        print(f"pw_inter_model has {len(data['pw_inter_model'])} rows")
    
    def test_pw_inter_model_has_three_model_pairs(self):
        """pw_inter_model should have 3 model pair rows (Claude-Gemini, Claude-GPT, Gemini-GPT)"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        pw = data.get("pw_inter_model", [])
        assert len(pw) == 3, f"Expected 3 model pairs, got {len(pw)}"
        
        # Verify pair names
        pairs = [row.get("pair") for row in pw]
        print(f"Model pairs: {pairs}")
        
        # Check that all pairs use short names
        for pair in pairs:
            assert "Claude" in pair or "GPT" in pair or "Gemini" in pair
            # Should NOT contain raw keys like "anthropic/claude-opus"
            assert "/" not in pair, f"Pair should use short names, got: {pair}"
    
    def test_pw_inter_model_row_structure(self):
        """Each pw_inter_model row has pair name and methods dict with 4 scoring methods"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        pw = data.get("pw_inter_model", [])
        assert len(pw) > 0
        
        for row in pw:
            # Check pair field
            assert "pair" in row
            assert isinstance(row["pair"], str)
            
            # Check methods dict
            assert "methods" in row
            methods = row["methods"]
            assert isinstance(methods, dict)
            
            # Check all 4 scoring methods are present
            expected_methods = ["raw_wr", "reg_wr", "bt", "trueskill"]
            for method in expected_methods:
                assert method in methods, f"Missing method: {method} in row {row['pair']}"
                
                # Each method should have rho and n
                assert "rho" in methods[method], f"Missing rho for {method}"
                assert "n" in methods[method], f"Missing n for {method}"
                
                # Validate rho is a valid correlation (-1 to 1)
                rho = methods[method]["rho"]
                assert -1 <= rho <= 1, f"Invalid rho value: {rho}"
                
                # Validate n is positive
                n = methods[method]["n"]
                assert n > 0, f"Invalid n value: {n}"
            
            print(f"Row '{row['pair']}': {methods}")
    
    def test_model_correlation_returns_method_labels(self):
        """GET /api/model-correlation returns method_labels dict"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        assert "method_labels" in data
        labels = data["method_labels"]
        assert isinstance(labels, dict)
        
        # Check all expected labels
        expected_labels = {
            "raw_wr": "Dashboard (raw win%)",
            "reg_wr": "Regularized WR",
            "bt": "Bradley-Terry",
            "trueskill": "TrueSkill",
        }
        
        for key, expected_label in expected_labels.items():
            assert key in labels, f"Missing label for {key}"
            assert labels[key] == expected_label, f"Wrong label for {key}: {labels[key]}"
        
        print(f"Method labels: {labels}")
    
    def test_model_names_use_short_names(self):
        """Model names should use short names (Claude Opus, GPT-5.2, Gemini 3 Pro)"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        pw = data.get("pw_inter_model", [])
        
        # Expected short names
        expected_short_names = ["Claude Opus", "GPT-5.2", "Gemini 3 Pro"]
        
        for row in pw:
            pair = row.get("pair", "")
            # Check that at least one short name is in the pair
            has_short_name = any(name in pair for name in expected_short_names)
            assert has_short_name, f"Pair '{pair}' doesn't use expected short names"
        
        print("All pairs use short model names")


class TestSIInterModelAgreement:
    """Tests for SI Inter-Model data in /api/si-rating-stats endpoint"""
    
    def test_si_rating_stats_returns_inter_model_si(self):
        """GET /api/si-rating-stats returns inter_model_si dict"""
        response = requests.get(f"{BASE_URL}/api/si-rating-stats", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        assert "inter_model_si" in data
        inter = data["inter_model_si"]
        assert isinstance(inter, dict)
        print(f"inter_model_si has {len(inter)} pairs")
    
    def test_si_inter_model_has_three_pairs(self):
        """inter_model_si should have 3 model pairs"""
        response = requests.get(f"{BASE_URL}/api/si-rating-stats", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        inter = data.get("inter_model_si", {})
        assert len(inter) == 3, f"Expected 3 pairs, got {len(inter)}"
        
        print(f"SI Inter-Model pairs: {list(inter.keys())}")
    
    def test_si_inter_model_pair_structure(self):
        """Each SI inter-model pair has spearman and n fields"""
        response = requests.get(f"{BASE_URL}/api/si-rating-stats", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        inter = data.get("inter_model_si", {})
        
        for pair_name, pair_data in inter.items():
            # Check spearman field
            assert "spearman" in pair_data, f"Missing spearman for {pair_name}"
            spearman = pair_data["spearman"]
            assert -1 <= spearman <= 1, f"Invalid spearman value: {spearman}"
            
            # Check n field
            assert "n" in pair_data, f"Missing n for {pair_name}"
            n = pair_data["n"]
            assert n > 0, f"Invalid n value: {n}"
            
            print(f"Pair '{pair_name}': spearman={spearman}, n={n}")


class TestModelCorrelationEndpoint:
    """General tests for /api/model-correlation endpoint"""
    
    def test_endpoint_returns_200(self):
        """GET /api/model-correlation returns 200"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
    
    def test_endpoint_returns_models_array(self):
        """Response includes models array with short names"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        assert "models" in data
        models = data["models"]
        assert isinstance(models, list)
        assert len(models) >= 3
        
        for model in models:
            assert "key" in model
            assert "short" in model
            print(f"Model: {model['short']} ({model['key']})")
    
    def test_endpoint_with_category_filter(self):
        """Endpoint works with category filter"""
        response = requests.get(f"{BASE_URL}/api/model-correlation?category=cs.RO", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("category") == "cs.RO"
        print(f"Category filter works: {data.get('category')}")


class TestTrueSkillHighestCorrelation:
    """Tests to verify TrueSkill has highest correlation (should be highlighted in UI)"""
    
    def test_trueskill_is_highest_in_pw_inter_model(self):
        """TrueSkill should have highest rho in each PW inter-model row"""
        response = requests.get(f"{BASE_URL}/api/model-correlation", timeout=60)
        assert response.status_code == 200
        data = response.json()
        
        pw = data.get("pw_inter_model", [])
        
        for row in pw:
            methods = row.get("methods", {})
            
            # Find the method with highest rho
            best_method = max(methods.keys(), key=lambda m: methods[m]["rho"])
            best_rho = methods[best_method]["rho"]
            trueskill_rho = methods.get("trueskill", {}).get("rho", 0)
            
            print(f"Row '{row['pair']}': best={best_method} ({best_rho}), trueskill={trueskill_rho}")
            
            # TrueSkill should be the best or very close
            assert best_method == "trueskill" or abs(best_rho - trueskill_rho) < 0.05, \
                f"TrueSkill ({trueskill_rho}) is not highest in {row['pair']}, best is {best_method} ({best_rho})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
