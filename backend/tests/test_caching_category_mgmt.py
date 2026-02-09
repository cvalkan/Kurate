"""
Test suite for Iteration 22 - Caching optimizations and Category Management features

Tests:
1. GET /api/categories - served from pre-computed background cache
2. GET /api/tags - served from pre-computed background cache  
3. GET /api/leaderboard - fast response (cached data)
4. POST /api/admin/categories/add - new categories preset to 'paused'
5. GET /api/admin/tournaments - verify new tournament status='paused'
6. POST /api/admin/tournaments/{id}/status - resume triggers wake scheduler
7. POST /api/admin/categories/remove - removes category
8. PUT /api/admin/settings - settings cache invalidation
"""

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_TOKEN = "papersumo2025"

def get_admin_headers():
    return {
        "Content-Type": "application/json",
        "X-Admin-Token": ADMIN_TOKEN
    }


class TestCachePerformance:
    """Test that public endpoints are served quickly from cache"""
    
    def test_categories_endpoint_fast(self):
        """GET /api/categories should return quickly (cached)"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/categories")
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Should have categories from cache
        assert "categories" in data
        assert len(data["categories"]) > 0
        assert "default" in data
        
        # Response should be fast (< 500ms for cached data)
        assert elapsed < 0.5, f"Categories endpoint took {elapsed:.3f}s, expected < 0.5s"
        print(f"Categories endpoint: {elapsed:.3f}s, {len(data['categories'])} categories")
    
    def test_tags_endpoint_fast(self):
        """GET /api/tags should return quickly (cached)"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/tags")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have tags from cache
        assert "tags" in data
        assert len(data["tags"]) > 0
        
        # Verify tag structure
        for tag in data["tags"][:5]:
            assert "id" in tag
            assert "count" in tag
            assert "matches" in tag
        
        # Response should be fast
        assert elapsed < 0.5, f"Tags endpoint took {elapsed:.3f}s, expected < 0.5s"
        print(f"Tags endpoint: {elapsed:.3f}s, {len(data['tags'])} tags")
    
    def test_leaderboard_category_fast(self):
        """GET /api/leaderboard?category=X should return quickly"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "week"
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        
        assert "leaderboard" in data
        assert data["category"] == "cs.RO"
        assert data["period"] == "week"
        
        # Response should be fast for category-based leaderboard (pre-computed)
        assert elapsed < 1.0, f"Leaderboard took {elapsed:.3f}s, expected < 1.0s"
        print(f"Leaderboard endpoint: {elapsed:.3f}s, {len(data['leaderboard'])} papers")
    
    def test_leaderboard_different_category(self):
        """GET /api/leaderboard for econ.GN should also be fast"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "econ.GN",
            "period": "all"
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["category"] == "econ.GN"
        assert "leaderboard" in data
        
        assert elapsed < 1.0, f"econ.GN leaderboard took {elapsed:.3f}s"
        print(f"econ.GN leaderboard: {elapsed:.3f}s, {len(data['leaderboard'])} papers")


class TestCategoryManagement:
    """Test admin category add/remove functionality with paused state"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Store initial state for cleanup"""
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=get_admin_headers()
        )
        if response.status_code == 200:
            self.initial_categories = response.json().get("settings", {}).get("active_categories", [])
        else:
            self.initial_categories = []
    
    def test_add_category_creates_paused_tournament(self):
        """POST /api/admin/categories/add should create tournament with status='paused'"""
        # Find a category that's not currently active
        test_category = "math.CO"  # Combinatorics - typically not active
        
        # Check if it's already active
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        current_cats = response.json().get("settings", {}).get("active_categories", [])
        
        if test_category in current_cats:
            pytest.skip(f"{test_category} already active, skipping add test")
        
        # Add the category
        response = requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": test_category},
            headers=get_admin_headers()
        )
        assert response.status_code == 200, f"Add category failed: {response.text}"
        data = response.json()
        
        # Verify response indicates paused status
        assert data.get("tournament_status") == "paused", f"Expected paused, got {data.get('tournament_status')}"
        assert test_category in data.get("active_categories", [])
        
        # Verify tournament exists with paused status
        response = requests.get(
            f"{BASE_URL}/api/admin/tournaments",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        tournaments = response.json().get("tournaments", [])
        
        tournament = next(
            (t for t in tournaments if t.get("category") == test_category and t.get("mode") == "standard"),
            None
        )
        assert tournament is not None, f"Tournament for {test_category} not found"
        assert tournament.get("status") == "paused", f"Expected paused, got {tournament.get('status')}"
        
        print(f"Added {test_category}: tournament status = {tournament.get('status')}")
        
        # Cleanup: remove the category
        requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": test_category},
            headers=get_admin_headers()
        )
    
    def test_tournament_resume_triggers_scheduler(self):
        """POST /api/admin/tournaments/{id}/status with status='active' should work"""
        # Get current tournaments
        response = requests.get(
            f"{BASE_URL}/api/admin/tournaments",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        tournaments = response.json().get("tournaments", [])
        
        # Find a paused tournament
        paused = next((t for t in tournaments if t.get("status") == "paused"), None)
        if not paused:
            pytest.skip("No paused tournaments to test resume")
        
        tournament_id = paused.get("tournament_id")
        category = paused.get("category")
        print(f"Testing resume on: {tournament_id}")
        
        # Resume the tournament
        response = requests.post(
            f"{BASE_URL}/api/admin/tournaments/{tournament_id}/status",
            json={"status": "active"},
            headers=get_admin_headers()
        )
        assert response.status_code == 200, f"Resume failed: {response.text}"
        data = response.json()
        assert data.get("tournament_status") == "active"
        
        # Verify tournament is now active
        response = requests.get(
            f"{BASE_URL}/api/admin/tournaments",
            headers=get_admin_headers()
        )
        tournaments = response.json().get("tournaments", [])
        updated = next((t for t in tournaments if t.get("tournament_id") == tournament_id), None)
        assert updated.get("status") == "active", f"Tournament not active: {updated}"
        
        print(f"Tournament {tournament_id} resumed successfully")
        
        # Restore to paused state for other tests
        requests.post(
            f"{BASE_URL}/api/admin/tournaments/{tournament_id}/status",
            json={"status": "paused"},
            headers=get_admin_headers()
        )
    
    def test_remove_category(self):
        """POST /api/admin/categories/remove should remove category from active list"""
        # First add a category to remove
        test_category = "stat.ML"  # Statistical ML
        
        # Check if it's already active
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=get_admin_headers()
        )
        current_cats = response.json().get("settings", {}).get("active_categories", [])
        
        # Add if not present
        if test_category not in current_cats:
            response = requests.post(
                f"{BASE_URL}/api/admin/categories/add",
                json={"category_id": test_category},
                headers=get_admin_headers()
            )
            if response.status_code != 200:
                pytest.skip(f"Could not add {test_category}: {response.text}")
        
        # Now remove it
        response = requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": test_category},
            headers=get_admin_headers()
        )
        assert response.status_code == 200, f"Remove failed: {response.text}"
        data = response.json()
        
        assert test_category not in data.get("active_categories", [])
        print(f"Removed {test_category} successfully")
    
    def test_remove_last_category_protected(self):
        """Cannot remove the last active category"""
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=get_admin_headers()
        )
        current_cats = response.json().get("settings", {}).get("active_categories", [])
        
        if len(current_cats) > 1:
            pytest.skip("More than one category active, can't test last-category protection")
        
        # Try to remove the only category
        response = requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": current_cats[0]},
            headers=get_admin_headers()
        )
        assert response.status_code == 400, "Should reject removing last category"
        print("Last category protection works")


class TestSettingsCacheInvalidation:
    """Test that settings updates are reflected quickly (TTL cache)"""
    
    def test_settings_update_reflected(self):
        """PUT /api/admin/settings changes should be visible within 5s"""
        # Get current settings
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        original_settings = response.json().get("settings", {})
        original_top_k = original_settings.get("top_k_focus", 10)
        
        # Change a setting
        new_top_k = original_top_k + 1 if original_top_k < 20 else original_top_k - 1
        
        response = requests.put(
            f"{BASE_URL}/api/admin/settings",
            json={"top_k_focus": new_top_k},
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        
        # Wait briefly and check it's updated
        time.sleep(1)
        
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        updated_top_k = response.json().get("settings", {}).get("top_k_focus")
        assert updated_top_k == new_top_k, f"Expected {new_top_k}, got {updated_top_k}"
        
        print(f"Settings updated: top_k_focus {original_top_k} -> {new_top_k}")
        
        # Restore original
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            json={"top_k_focus": original_top_k},
            headers=get_admin_headers()
        )


class TestTournamentStatusEndpoint:
    """Test tournament status endpoint variations"""
    
    def test_get_tournaments_list(self):
        """GET /api/admin/tournaments should return all tournaments"""
        response = requests.get(
            f"{BASE_URL}/api/admin/tournaments",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "tournaments" in data
        tournaments = data["tournaments"]
        
        # Verify each tournament has required fields
        for t in tournaments:
            assert "tournament_id" in t
            assert "category" in t
            assert "status" in t
            assert t["status"] in ("active", "paused")
            assert "mode" in t
        
        # Count active vs paused
        active = sum(1 for t in tournaments if t["status"] == "active")
        paused = sum(1 for t in tournaments if t["status"] == "paused")
        print(f"Tournaments: {len(tournaments)} total, {active} active, {paused} paused")
    
    def test_invalid_status_rejected(self):
        """POST tournament status with invalid value should fail"""
        # Get any tournament ID
        response = requests.get(
            f"{BASE_URL}/api/admin/tournaments",
            headers=get_admin_headers()
        )
        tournaments = response.json().get("tournaments", [])
        if not tournaments:
            pytest.skip("No tournaments to test")
        
        tournament_id = tournaments[0]["tournament_id"]
        
        # Try invalid status
        response = requests.post(
            f"{BASE_URL}/api/admin/tournaments/{tournament_id}/status",
            json={"status": "invalid_status"},
            headers=get_admin_headers()
        )
        assert response.status_code == 400, f"Should reject invalid status, got {response.status_code}"
        print("Invalid status correctly rejected")
    
    def test_nonexistent_tournament_404(self):
        """POST status on non-existent tournament should 404"""
        response = requests.post(
            f"{BASE_URL}/api/admin/tournaments/nonexistent-tournament-id/status",
            json={"status": "active"},
            headers=get_admin_headers()
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("Non-existent tournament correctly returns 404")


class TestCategoriesServedFromCache:
    """Verify categories/tags are served from pre-computed cache, not DB"""
    
    def test_categories_consistent_across_calls(self):
        """Multiple GET /api/categories calls should return same data (cached)"""
        responses = []
        for i in range(3):
            resp = requests.get(f"{BASE_URL}/api/categories")
            assert resp.status_code == 200
            responses.append(resp.json())
            time.sleep(0.1)
        
        # All responses should have same categories
        cat_ids_0 = [c["id"] for c in responses[0]["categories"]]
        for i, resp in enumerate(responses[1:], 1):
            cat_ids = [c["id"] for c in resp["categories"]]
            assert cat_ids == cat_ids_0, f"Call {i} returned different categories"
        
        print(f"All 3 calls returned consistent {len(cat_ids_0)} categories")
    
    def test_tags_consistent_across_calls(self):
        """Multiple GET /api/tags calls should return same data (cached)"""
        responses = []
        for i in range(3):
            resp = requests.get(f"{BASE_URL}/api/tags")
            assert resp.status_code == 200
            responses.append(resp.json())
            time.sleep(0.1)
        
        # All responses should have same tags
        tag_ids_0 = [t["id"] for t in responses[0]["tags"]]
        for i, resp in enumerate(responses[1:], 1):
            tag_ids = [t["id"] for t in resp["tags"]]
            assert tag_ids == tag_ids_0, f"Call {i} returned different tags"
        
        print(f"All 3 calls returned consistent {len(tag_ids_0)} tags")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
