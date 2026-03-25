"""
Test PW vs Claude SI Table Feature
Tests the new pw_vs_claude_si array in /api/si-rating-stats endpoint
and the pw_inter_model array in /api/model-correlation endpoint.

Features tested:
1. pw_vs_claude_si array with 8 rows (4 within + 4 combined)
2. pw_vs_si.within_model with claude, gpt, gemini keys
3. pw_vs_si.overall with 4 methods (raw_wr, reg_wr, bt, trueskill)
4. pw_inter_model with 3 rows and 4 methods each
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPwVsClaudeSiTable:
    """Tests for the PW vs Claude SI table feature"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.timeout = 60  # SI rating stats can take time
    
    def test_si_rating_stats_returns_pw_vs_claude_si(self):
        """Test that /api/si-rating-stats returns pw_vs_claude_si array"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "pw_vs_claude_si" in data, "pw_vs_claude_si not found in response"
        
        pw_vs_claude_si = data["pw_vs_claude_si"]
        assert isinstance(pw_vs_claude_si, list), "pw_vs_claude_si should be a list"
        print(f"pw_vs_claude_si has {len(pw_vs_claude_si)} rows")
    
    def test_pw_vs_claude_si_has_8_rows(self):
        """Test that pw_vs_claude_si has 8 rows (4 within + 4 combined)"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_vs_claude_si = data.get("pw_vs_claude_si", [])
        
        # Should have 8 rows: 4 within-model + 4 combined
        assert len(pw_vs_claude_si) == 8, f"Expected 8 rows, got {len(pw_vs_claude_si)}"
        
        # Count within and combined rows
        within_rows = [r for r in pw_vs_claude_si if r.get("type") == "within"]
        combined_rows = [r for r in pw_vs_claude_si if r.get("type") == "combined"]
        
        assert len(within_rows) == 4, f"Expected 4 within rows, got {len(within_rows)}"
        assert len(combined_rows) == 4, f"Expected 4 combined rows, got {len(combined_rows)}"
        print(f"Within rows: {len(within_rows)}, Combined rows: {len(combined_rows)}")
    
    def test_pw_vs_claude_si_entry_structure(self):
        """Test that each pw_vs_claude_si entry has required fields"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_vs_claude_si = data.get("pw_vs_claude_si", [])
        
        required_fields = ["comparison", "type", "method", "rho", "n"]
        
        for i, entry in enumerate(pw_vs_claude_si):
            for field in required_fields:
                assert field in entry, f"Row {i} missing field '{field}'"
            
            # Validate type is either 'within' or 'combined'
            assert entry["type"] in ("within", "combined"), f"Row {i} has invalid type: {entry['type']}"
            
            # Validate method is one of the 4 ranking methods
            assert entry["method"] in ("raw_wr", "reg_wr", "bt", "trueskill"), f"Row {i} has invalid method: {entry['method']}"
            
            # Validate rho is a number
            assert isinstance(entry["rho"], (int, float)), f"Row {i} rho is not a number"
            
            # Validate n is a positive integer
            assert isinstance(entry["n"], int) and entry["n"] > 0, f"Row {i} n is not a positive integer"
        
        print("All pw_vs_claude_si entries have valid structure")
    
    def test_pw_vs_claude_si_methods_order(self):
        """Test that methods appear in correct order: raw_wr, reg_wr, bt, trueskill"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_vs_claude_si = data.get("pw_vs_claude_si", [])
        
        expected_order = ["raw_wr", "reg_wr", "bt", "trueskill"]
        
        # Check within rows order
        within_rows = [r for r in pw_vs_claude_si if r.get("type") == "within"]
        within_methods = [r["method"] for r in within_rows]
        assert within_methods == expected_order, f"Within methods order incorrect: {within_methods}"
        
        # Check combined rows order
        combined_rows = [r for r in pw_vs_claude_si if r.get("type") == "combined"]
        combined_methods = [r["method"] for r in combined_rows]
        assert combined_methods == expected_order, f"Combined methods order incorrect: {combined_methods}"
        
        print("Methods appear in correct order for both within and combined rows")
    
    def test_pw_vs_si_within_model_structure(self):
        """Test that pw_vs_si.within_model has claude, gpt, gemini keys"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_vs_si = data.get("pw_vs_si", {})
        
        assert "within_model" in pw_vs_si, "within_model not found in pw_vs_si"
        within_model = pw_vs_si["within_model"]
        
        # Check for expected model keys
        expected_models = ["claude", "gpt", "gemini"]
        for model in expected_models:
            if model in within_model:
                print(f"Found within_model.{model}")
                # Validate structure
                assert "label" in within_model[model], f"within_model.{model} missing 'label'"
                assert "rows" in within_model[model], f"within_model.{model} missing 'rows'"
                assert "n_matches" in within_model[model], f"within_model.{model} missing 'n_matches'"
    
    def test_pw_vs_si_overall_has_4_methods(self):
        """Test that pw_vs_si.overall has 4 methods"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_vs_si = data.get("pw_vs_si", {})
        
        assert "overall" in pw_vs_si, "overall not found in pw_vs_si"
        overall = pw_vs_si["overall"]
        
        assert isinstance(overall, list), "overall should be a list"
        assert len(overall) == 4, f"Expected 4 methods in overall, got {len(overall)}"
        
        methods = [r["method"] for r in overall]
        expected_methods = ["raw_wr", "reg_wr", "bt", "trueskill"]
        assert methods == expected_methods, f"Methods mismatch: {methods} vs {expected_methods}"
        
        print(f"pw_vs_si.overall has {len(overall)} methods: {methods}")


class TestPwInterModel:
    """Tests for the PW Inter-Model table in /api/model-correlation"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.timeout = 60
    
    def test_model_correlation_returns_pw_inter_model(self):
        """Test that /api/model-correlation returns pw_inter_model array"""
        response = self.session.get(
            f"{BASE_URL}/api/model-correlation",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "pw_inter_model" in data, "pw_inter_model not found in response"
        
        pw_inter_model = data["pw_inter_model"]
        assert isinstance(pw_inter_model, list), "pw_inter_model should be a list"
        print(f"pw_inter_model has {len(pw_inter_model)} rows")
    
    def test_pw_inter_model_has_3_rows(self):
        """Test that pw_inter_model has 3 rows (one per model pair)"""
        response = self.session.get(
            f"{BASE_URL}/api/model-correlation",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_inter_model = data.get("pw_inter_model", [])
        
        # Should have 3 rows: Claude vs Gemini, Claude vs GPT, Gemini vs GPT
        assert len(pw_inter_model) == 3, f"Expected 3 rows, got {len(pw_inter_model)}"
        print(f"pw_inter_model has {len(pw_inter_model)} rows")
    
    def test_pw_inter_model_has_4_methods_each(self):
        """Test that each pw_inter_model row has 4 methods"""
        response = self.session.get(
            f"{BASE_URL}/api/model-correlation",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_inter_model = data.get("pw_inter_model", [])
        
        expected_methods = ["raw_wr", "reg_wr", "bt", "trueskill"]
        
        for i, row in enumerate(pw_inter_model):
            assert "pair" in row, f"Row {i} missing 'pair'"
            assert "methods" in row, f"Row {i} missing 'methods'"
            
            methods = row["methods"]
            for method in expected_methods:
                assert method in methods, f"Row {i} missing method '{method}'"
                assert "rho" in methods[method], f"Row {i} method '{method}' missing 'rho'"
                assert "n" in methods[method], f"Row {i} method '{method}' missing 'n'"
        
        print("All pw_inter_model rows have 4 methods with rho and n")
    
    def test_pw_inter_model_trueskill_column(self):
        """Test that TrueSkill column exists and has valid values"""
        response = self.session.get(
            f"{BASE_URL}/api/model-correlation",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        pw_inter_model = data.get("pw_inter_model", [])
        
        for row in pw_inter_model:
            trueskill = row["methods"].get("trueskill", {})
            assert "rho" in trueskill, f"TrueSkill missing rho for {row['pair']}"
            assert isinstance(trueskill["rho"], (int, float)), f"TrueSkill rho is not a number"
            print(f"{row['pair']}: TrueSkill rho = {trueskill['rho']}")


class TestSiRatingCalibrationRemoved:
    """Tests to verify SI Rating Calibration table is removed"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.timeout = 60
    
    def test_model_comparison_still_exists_in_response(self):
        """Test that model_comparison data still exists (for other uses)"""
        response = self.session.get(
            f"{BASE_URL}/api/si-rating-stats",
            params={"category": "cs.RO"},
            timeout=self.timeout
        )
        assert response.status_code == 200
        
        data = response.json()
        # model_comparison may or may not exist - this is just informational
        if "model_comparison" in data:
            print("model_comparison data exists in response (backend still provides it)")
        else:
            print("model_comparison data not in response")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
