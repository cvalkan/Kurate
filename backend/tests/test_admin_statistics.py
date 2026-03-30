"""
Test Admin Statistics and Pause/Resume features
Tests for iteration 14: Admin Statistics tab and pause/resume consistency
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_TOKEN = os.environ.get("ADMIN_PASSWORD", "")

@pytest.fixture
def admin_headers():
    """Admin authentication headers"""
    return {"X-Admin-Token": ADMIN_TOKEN}


class TestAdminTimeseries:
    """Tests for GET /api/admin/timeseries endpoint"""
    
    def test_timeseries_endpoint_returns_data(self, admin_headers):
        """Test timeseries endpoint returns daily series data"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "series" in data
        assert "totals" in data
        assert "categories" in data
        
        # Validate totals structure
        totals = data["totals"]
        assert "papers" in totals
        assert "matches" in totals
        assert "tokens" in totals
        assert "cost" in totals
        
        print(f"Timeseries totals: papers={totals['papers']}, matches={totals['matches']}, cost=${totals['cost']}")
    
    def test_timeseries_series_structure(self, admin_headers):
        """Test each series entry has required fields"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        series = data["series"]
        assert len(series) > 0, "Series should not be empty"
        
        # Check first entry structure
        entry = series[0]
        assert "date" in entry
        assert "papers_daily" in entry
        assert "papers_cumulative" in entry
        assert "matches_daily" in entry
        assert "matches_cumulative" in entry
        assert "tokens_daily" in entry
        assert "tokens_cumulative" in entry
        assert "cost_daily" in entry
        assert "cost_cumulative" in entry
        
        print(f"First entry date: {entry['date']}")
        print(f"Sample values: papers_cumulative={entry['papers_cumulative']}, matches_cumulative={entry['matches_cumulative']}")
    
    def test_timeseries_per_category_fields(self, admin_headers):
        """Test per-category breakdown fields exist"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        categories = data["categories"]
        assert len(categories) >= 5, f"Expected at least 5 categories, got {len(categories)}"
        
        # Check per-category fields in series
        series = data["series"]
        last_entry = series[-1]
        
        for cat in categories:
            assert f"papers_cumulative_{cat}" in last_entry, f"Missing papers_cumulative_{cat}"
            assert f"matches_cumulative_{cat}" in last_entry, f"Missing matches_cumulative_{cat}"
            assert f"tokens_cumulative_{cat}" in last_entry, f"Missing tokens_cumulative_{cat}"
            assert f"cost_cumulative_{cat}" in last_entry, f"Missing cost_cumulative_{cat}"
        
        print(f"Categories with per-category fields: {categories}")
    
    def test_timeseries_requires_auth(self):
        """Test timeseries endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/timeseries")
        assert response.status_code in [401, 403], "Should require authentication"


class TestAdminProgress:
    """Tests for GET /api/admin/progress endpoint"""
    
    def test_progress_includes_pause_fields(self, admin_headers):
        """Test progress includes tournament_paused and global_paused fields"""
        response = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.RO", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check pause status fields exist
        assert "paused" in data, "Missing 'paused' field"
        assert "global_paused" in data, "Missing 'global_paused' field"
        assert "tournament_paused" in data, "Missing 'tournament_paused' field"
        
        print(f"Pause status: paused={data['paused']}, global_paused={data['global_paused']}, tournament_paused={data['tournament_paused']}")
    
    def test_progress_goal_fields(self, admin_headers):
        """Test progress includes goal tracking fields"""
        response = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.RO", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "goals_met" in data
        assert "goal1" in data
        assert "goal2" in data
        
        # Check goal structure
        goal1 = data["goal1"]
        assert "met" in goal1
        assert "label" in goal1
        
        goal2 = data["goal2"]
        assert "met" in goal2
        assert "label" in goal2
        assert "done" in goal2
        assert "total" in goal2
        
        print(f"Goals: goal1_met={goal1['met']}, goal2_met={goal2['met']}, goals_met={data['goals_met']}")
    
    def test_progress_estimated_fields(self, admin_headers):
        """Test progress includes estimated remaining matches"""
        response = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.DC", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "estimated_matches_remaining" in data
        assert "estimated_minutes" in data
        assert "total_papers" in data
        assert "total_matches" in data
        
        print(f"Progress: {data['total_papers']} papers, {data['total_matches']} matches, {data['estimated_matches_remaining']} remaining")
    
    def test_progress_per_category(self, admin_headers):
        """Test progress works for different categories"""
        categories = ["cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]
        
        for cat in categories:
            response = requests.get(f"{BASE_URL}/api/admin/progress?category={cat}", headers=admin_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["category"] == cat
            print(f"Category {cat}: papers={data['total_papers']}, matches={data['total_matches']}")


class TestAdminTournaments:
    """Tests for tournament pause/resume functionality"""
    
    def test_get_tournaments_list(self, admin_headers):
        """Test getting list of tournaments"""
        response = requests.get(f"{BASE_URL}/api/admin/tournaments", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "tournaments" in data
        tournaments = data["tournaments"]
        assert len(tournaments) >= 5, f"Expected at least 5 tournaments, got {len(tournaments)}"
        
        for t in tournaments:
            assert "tournament_id" in t
            assert "category" in t
            assert "status" in t
            assert "mode" in t
            print(f"Tournament: {t['category']} - status={t['status']}")
    
    def test_tournament_has_stats(self, admin_headers):
        """Test tournaments have stats field"""
        response = requests.get(f"{BASE_URL}/api/admin/tournaments", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        for t in data["tournaments"]:
            assert "stats" in t, f"Tournament {t['category']} missing stats"
            stats = t["stats"]
            assert "papers" in stats
            assert "matches" in stats
            print(f"Tournament {t['category']}: {stats['papers']} papers, {stats['matches']} matches")
    
    def test_tournament_has_goals(self, admin_headers):
        """Test tournaments have goals field"""
        response = requests.get(f"{BASE_URL}/api/admin/tournaments", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        for t in data["tournaments"]:
            assert "goals" in t, f"Tournament {t['category']} missing goals"
            goals = t["goals"]
            assert "min_matches" in goals
            assert "ci_target" in goals
            print(f"Tournament {t['category']}: min_matches={goals['min_matches']}, ci_target={goals['ci_target']}")


class TestAdminStats:
    """Tests for GET /api/admin/stats endpoint"""
    
    def test_stats_model_breakdown(self, admin_headers):
        """Test stats returns model usage breakdown"""
        response = requests.get(f"{BASE_URL}/api/admin/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "models" in data
        assert "totals" in data
        
        models = data["models"]
        assert len(models) >= 1, "Should have at least 1 model"
        
        # Check model stats structure
        for model_name, stats in models.items():
            assert "matches" in stats
            assert "input_tokens" in stats
            assert "output_tokens" in stats
            assert "cost_total" in stats
            print(f"Model {model_name}: {stats['matches']} calls, ${stats['cost_total']:.2f}")
    
    def test_stats_totals(self, admin_headers):
        """Test stats totals are calculated correctly"""
        response = requests.get(f"{BASE_URL}/api/admin/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        totals = data["totals"]
        assert "input_tokens" in totals
        assert "output_tokens" in totals
        assert "total_tokens" in totals
        assert "total_matches" in totals
        assert "total_cost" in totals
        
        # Verify totals calculation
        assert totals["total_tokens"] == totals["input_tokens"] + totals["output_tokens"]
        print(f"Stats totals: {totals['total_matches']} matches, ${totals['total_cost']:.2f} cost")


class TestAdminTabNavigation:
    """Tests for admin panel tab structure"""
    
    def test_admin_login(self):
        """Test admin login endpoint"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_TOKEN})
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
    
    def test_admin_settings_access(self, admin_headers):
        """Test admin settings are accessible"""
        response = requests.get(f"{BASE_URL}/api/admin/settings", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
    
    def test_admin_prompt_access(self, admin_headers):
        """Test admin prompt is accessible"""
        response = requests.get(f"{BASE_URL}/api/admin/prompt", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "system_prompt" in data
        assert "user_prompt" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
