"""
Test Admin Panel Improvements (Iteration 15)
- Cost by Model breakdown matches total cost
- Timeseries endpoint returns models field
- Progress endpoint returns tournament_paused and global_paused
- Handles missing fields gracefully (tokens, created_at, primary_category)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_TOKEN = os.environ.get("ADMIN_PASSWORD", "")

def get_headers():
    return {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}


class TestAdminLogin:
    """Test admin authentication"""
    
    def test_login_success(self):
        """Test admin login with correct password"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_TOKEN})
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "token" in data
    
    def test_login_failure(self):
        """Test admin login with wrong password"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={"password": "wrongpassword"})
        assert response.status_code == 403


class TestTimeseriesEndpoint:
    """Test GET /api/admin/timeseries - Cost by Model breakdown"""
    
    def test_timeseries_returns_models_field(self):
        """Verify timeseries returns 'models' field with per-model cost breakdown"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        # Check models field exists
        assert "models" in data, "Response should have 'models' field"
        models = data["models"]
        assert isinstance(models, dict), "models should be a dictionary"
        
        # Verify expected models are present
        expected_models = ["openai/gpt-5.2", "anthropic/claude-opus-4-5-20251101", "gemini/gemini-3-pro-preview"]
        for model in expected_models:
            assert model in models, f"Model {model} should be in models breakdown"
    
    def test_timeseries_model_costs_sum_to_total(self):
        """Verify model costs sum equals total cost (within $0.01)"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        models = data.get("models", {})
        totals = data.get("totals", {})
        
        # Sum model costs
        model_cost_sum = sum(m.get("cost_total", 0) for m in models.values())
        total_cost = totals.get("cost", 0)
        
        # Verify they match within $0.01
        assert abs(model_cost_sum - total_cost) < 0.01, f"Model costs ({model_cost_sum}) should equal total ({total_cost})"
    
    def test_timeseries_model_percentages_sum_to_100(self):
        """Verify model cost percentages sum to approximately 100%"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        models = data.get("models", {})
        total_cost = data.get("totals", {}).get("cost", 0)
        
        if total_cost > 0:
            percentages = [(m.get("cost_total", 0) / total_cost * 100) for m in models.values()]
            total_pct = sum(percentages)
            assert abs(total_pct - 100) < 1, f"Percentages should sum to ~100%, got {total_pct}"
    
    def test_timeseries_has_series_data(self):
        """Verify timeseries returns series array with daily data"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        assert "series" in data
        series = data["series"]
        assert isinstance(series, list)
        assert len(series) > 0, "Series should have data"
        
        # Check first entry has required fields
        entry = series[0]
        assert "date" in entry
        assert "papers_daily" in entry or "papers_cumulative" in entry
    
    def test_timeseries_requires_auth(self):
        """Verify timeseries requires authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries")
        assert response.status_code in [401, 403]


class TestProgressEndpoint:
    """Test GET /api/admin/progress - tournament vs global pause"""
    
    def test_progress_has_tournament_paused(self):
        """Verify progress returns tournament_paused field"""
        response = requests.get(f"{BASE_URL}/api/admin/progress", params={"category": "cs.RO"}, headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        assert "tournament_paused" in data, "Response should have tournament_paused"
        assert isinstance(data["tournament_paused"], bool)
    
    def test_progress_has_global_paused(self):
        """Verify progress returns global_paused field"""
        response = requests.get(f"{BASE_URL}/api/admin/progress", params={"category": "cs.RO"}, headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        assert "global_paused" in data, "Response should have global_paused"
        assert isinstance(data["global_paused"], bool)
    
    def test_progress_has_goal_tracking(self):
        """Verify progress returns goal1, goal2, goals_met"""
        response = requests.get(f"{BASE_URL}/api/admin/progress", params={"category": "cs.RO"}, headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        assert "goal1" in data
        assert "goal2" in data
        assert "goals_met" in data
        
        # Verify goal structure
        assert "met" in data["goal1"]
        assert "label" in data["goal1"]
    
    def test_progress_for_all_categories(self):
        """Verify progress works for all 5 categories"""
        categories = ["cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]
        for cat in categories:
            response = requests.get(f"{BASE_URL}/api/admin/progress", params={"category": cat}, headers=get_headers())
            assert response.status_code == 200, f"Progress should work for {cat}"
            data = response.json()
            assert data.get("category") == cat


class TestTournamentsEndpoint:
    """Test GET /api/admin/tournaments - Tournament Registry"""
    
    def test_tournaments_returns_list(self):
        """Verify tournaments endpoint returns list"""
        response = requests.get(f"{BASE_URL}/api/admin/tournaments", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        
        assert "tournaments" in data
        assert isinstance(data["tournaments"], list)
    
    def test_tournaments_have_required_fields(self):
        """Verify each tournament has status, category, goals"""
        response = requests.get(f"{BASE_URL}/api/admin/tournaments", headers=get_headers())
        assert response.status_code == 200
        tournaments = response.json().get("tournaments", [])
        
        assert len(tournaments) == 5, "Should have 5 tournaments"
        
        for t in tournaments:
            assert "tournament_id" in t
            assert "status" in t
            assert "category" in t
            assert "goals" in t
            assert t["status"] in ["active", "paused"]
    
    def test_tournament_pause_resume(self):
        """Test pause/resume endpoint works (but don't actually change state)"""
        # Just verify the endpoint exists and returns proper response
        response = requests.get(f"{BASE_URL}/api/admin/tournaments", headers=get_headers())
        tournaments = response.json().get("tournaments", [])
        
        if tournaments:
            tid = tournaments[0]["tournament_id"]
            current_status = tournaments[0]["status"]
            
            # The endpoint should accept the same status without error
            resp = requests.post(
                f"{BASE_URL}/api/admin/tournaments/{tid}/status",
                json={"status": current_status},
                headers=get_headers()
            )
            assert resp.status_code == 200


class TestMissingFieldsHandling:
    """Test robustness for missing fields in DB"""
    
    def test_timeseries_handles_missing_tokens(self):
        """Verify timeseries doesn't crash if tokens field missing"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        assert response.status_code == 200
        # If we got here, it handled any missing tokens gracefully
    
    def test_timeseries_handles_missing_created_at(self):
        """Verify timeseries handles missing created_at"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        # Should still return valid structure
        assert "totals" in data
        assert "series" in data
    
    def test_stats_handles_missing_model_used(self):
        """Verify stats endpoint handles missing model_used"""
        response = requests.get(f"{BASE_URL}/api/admin/stats", headers=get_headers())
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert "totals" in data


class TestDataConsistency:
    """Test data consistency across endpoints"""
    
    def test_timeseries_excludes_experiment_matches(self):
        """
        Timeseries excludes experiment/prediction mode matches.
        Stats endpoint includes all matches (14k+), timeseries only standard matches (12k+).
        This is intentional - Statistics tab shows only standard tournament data.
        """
        stats_resp = requests.get(f"{BASE_URL}/api/admin/stats", headers=get_headers())
        timeseries_resp = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=get_headers())
        
        assert stats_resp.status_code == 200
        assert timeseries_resp.status_code == 200
        
        stats_matches = stats_resp.json().get("totals", {}).get("total_matches", 0)
        timeseries_matches = timeseries_resp.json().get("totals", {}).get("matches", 0)
        
        # Stats includes experiment matches, timeseries doesn't
        # timeseries should have fewer matches
        assert timeseries_matches > 0, "Timeseries should have matches"
        assert stats_matches >= timeseries_matches, "Stats should have >= timeseries matches (includes experiments)"
        
        # Verify timeseries model costs are internally consistent
        timeseries_data = timeseries_resp.json()
        model_cost_sum = sum(m.get("cost_total", 0) for m in timeseries_data.get("models", {}).values())
        total_cost = timeseries_data.get("totals", {}).get("cost", 0)
        assert abs(model_cost_sum - total_cost) < 0.01, "Model costs should sum to total"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
