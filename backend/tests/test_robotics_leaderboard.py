"""
Test suite for Robotics Paper Leaderboard API
Tests: Health, Leaderboard, Paper Detail, Status, Admin Authentication, Admin Settings, Admin Prompt
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://ai-judge-hub-1.preview.emergentagent.com"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_HEADERS = {"X-Admin-Token": ADMIN_PASSWORD, "Content-Type": "application/json"}


# --- PUBLIC ENDPOINTS ---

class TestHealthEndpoint:
    """Test /api/health endpoint"""
    
    def test_health_returns_ok(self):
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        print(f"✓ Health check passed: {data}")


class TestLeaderboardEndpoint:
    """Test /api/leaderboard endpoint with various filters"""
    
    def test_leaderboard_returns_data(self):
        response = requests.get(f"{BASE_URL}/api/leaderboard")
        assert response.status_code == 200
        data = response.json()
        assert "leaderboard" in data
        assert "total_papers" in data
        assert "total_matches" in data
        assert "period" in data
        print(f"✓ Leaderboard returned {len(data['leaderboard'])} papers")
    
    def test_leaderboard_paper_structure(self):
        """Verify each paper has required fields"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?period=all")
        assert response.status_code == 200
        data = response.json()
        
        if data["leaderboard"]:
            paper = data["leaderboard"][0]
            required_fields = ["id", "rank", "title", "authors", "bt_score", 
                            "wins", "losses", "comparisons", "confidence", "published"]
            for field in required_fields:
                assert field in paper, f"Missing field: {field}"
            
            # Verify confidence structure
            assert "win_rate" in paper["confidence"]
            assert "lower_bound" in paper["confidence"]
            assert "upper_bound" in paper["confidence"]
            print(f"✓ Paper structure valid with all required fields")
        else:
            print("⚠ No papers in leaderboard to verify structure")
    
    def test_leaderboard_filter_today(self):
        """Test today filter"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?period=today")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "today"
        print(f"✓ Today filter returned {len(data['leaderboard'])} papers")
    
    def test_leaderboard_filter_week(self):
        """Test week filter"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?period=week")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "week"
        print(f"✓ Week filter returned {len(data['leaderboard'])} papers")
    
    def test_leaderboard_filter_month(self):
        """Test month filter"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?period=month")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "month"
        print(f"✓ Month filter returned {len(data['leaderboard'])} papers")
    
    def test_leaderboard_filter_all(self):
        """Test all filter (default)"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?period=all")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "all"
        assert data["total_papers"] > 0
        print(f"✓ All filter returned {data['total_papers']} papers")


class TestPaperDetailEndpoint:
    """Test /api/papers/{id} endpoint"""
    
    @pytest.fixture
    def paper_id(self):
        """Get a valid paper ID from leaderboard"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?period=all")
        data = response.json()
        if data["leaderboard"]:
            return data["leaderboard"][0]["id"]
        pytest.skip("No papers available for testing")
    
    def test_paper_detail_returns_data(self, paper_id):
        response = requests.get(f"{BASE_URL}/api/papers/{paper_id}")
        assert response.status_code == 200
        data = response.json()
        assert "paper" in data
        assert "matches" in data
        assert "stats" in data
        print(f"✓ Paper detail returned for ID: {paper_id}")
    
    def test_paper_detail_structure(self, paper_id):
        response = requests.get(f"{BASE_URL}/api/papers/{paper_id}")
        assert response.status_code == 200
        data = response.json()
        
        # Paper fields
        paper = data["paper"]
        assert "id" in paper
        assert "title" in paper
        assert "authors" in paper
        assert "abstract" in paper
        
        # Stats fields
        stats = data["stats"]
        assert "wins" in stats
        assert "losses" in stats
        assert "comparisons" in stats
        assert "confidence" in stats
        print(f"✓ Paper detail structure valid: {paper['title'][:50]}...")
    
    def test_paper_detail_matches_structure(self, paper_id):
        response = requests.get(f"{BASE_URL}/api/papers/{paper_id}")
        assert response.status_code == 200
        data = response.json()
        
        if data["matches"]:
            match = data["matches"][0]
            assert "id" in match
            assert "opponent_id" in match
            assert "opponent_title" in match
            assert "won" in match
            assert "reasoning" in match
            print(f"✓ Match structure valid with {len(data['matches'])} matches")
        else:
            print("⚠ No matches for this paper")
    
    def test_paper_detail_not_found(self):
        response = requests.get(f"{BASE_URL}/api/papers/non-existent-id")
        assert response.status_code == 404
        print("✓ Non-existent paper returns 404")


class TestStatusEndpoint:
    """Test /api/status endpoint"""
    
    def test_status_returns_data(self):
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "total_papers" in data
        assert "total_matches" in data
        assert "failed_matches" in data
        assert "scheduler" in data
        print(f"✓ Status returned: {data['total_papers']} papers, {data['total_matches']} matches")
    
    def test_status_scheduler_fields(self):
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        data = response.json()
        
        scheduler = data["scheduler"]
        assert "is_fetching" in scheduler
        assert "is_processing" in scheduler
        assert "current_activity" in scheduler
        print(f"✓ Scheduler status: {scheduler['current_activity']}")


# --- ADMIN ENDPOINTS ---

class TestAdminLogin:
    """Test /api/admin/login endpoint"""
    
    def test_login_correct_password(self):
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": ADMIN_PASSWORD},
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data
        print(f"✓ Login successful with correct password")
    
    def test_login_wrong_password(self):
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": "wrongpassword"},
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 403
        print("✓ Login rejected with wrong password (403)")


class TestAdminSettings:
    """Test /api/admin/settings endpoints"""
    
    def test_settings_requires_auth(self):
        """Settings endpoint without auth header"""
        response = requests.get(f"{BASE_URL}/api/admin/settings")
        assert response.status_code == 401
        print("✓ Settings requires auth (401 without token)")
    
    def test_settings_get_authenticated(self):
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        settings = data["settings"]
        assert "fetch_interval_hours" in settings
        assert "max_papers_per_fetch" in settings
        assert "comparisons_per_round" in settings
        print(f"✓ Settings retrieved: {list(settings.keys())}")
    
    def test_settings_update(self):
        """Test settings update - change and revert a value"""
        # Get current settings
        get_response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=ADMIN_HEADERS
        )
        original_value = get_response.json()["settings"]["top_k_focus"]
        
        # Update to new value
        new_value = original_value + 1
        update_response = requests.put(
            f"{BASE_URL}/api/admin/settings",
            json={"top_k_focus": new_value},
            headers=ADMIN_HEADERS
        )
        assert update_response.status_code == 200
        assert update_response.json()["success"] is True
        
        # Verify update
        verify_response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=ADMIN_HEADERS
        )
        assert verify_response.json()["settings"]["top_k_focus"] == new_value
        
        # Revert back
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            json={"top_k_focus": original_value},
            headers=ADMIN_HEADERS
        )
        print(f"✓ Settings update working (top_k_focus: {original_value} -> {new_value} -> reverted)")


class TestAdminStatus:
    """Test /api/admin/status endpoint"""
    
    def test_admin_status_requires_auth(self):
        response = requests.get(f"{BASE_URL}/api/admin/status")
        assert response.status_code == 401
        print("✓ Admin status requires auth (401)")
    
    def test_admin_status_authenticated(self):
        response = requests.get(
            f"{BASE_URL}/api/admin/status",
            headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_papers" in data
        assert "total_matches" in data
        assert "scheduler" in data
        assert "recent_matches" in data
        print(f"✓ Admin status returned: {data['total_papers']} papers, {data['total_matches']} matches, {len(data['recent_matches'])} recent matches")


class TestAdminPrompt:
    """Test /api/admin/prompt endpoints"""
    
    def test_prompt_get(self):
        response = requests.get(
            f"{BASE_URL}/api/admin/prompt",
            headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "system_prompt" in data
        assert "user_prompt" in data
        assert "is_custom" in data
        print(f"✓ Prompt retrieved, is_custom: {data['is_custom']}")
    
    def test_prompt_update_and_reset(self):
        """Test prompt update and reset flow"""
        # Get original
        original = requests.get(
            f"{BASE_URL}/api/admin/prompt",
            headers=ADMIN_HEADERS
        ).json()
        
        # Update with custom prompt
        custom_system = "Custom test system prompt"
        custom_user = "Custom test user prompt"
        update_response = requests.put(
            f"{BASE_URL}/api/admin/prompt",
            json={"system_prompt": custom_system, "user_prompt": custom_user},
            headers=ADMIN_HEADERS
        )
        assert update_response.status_code == 200
        
        # Verify update
        verify = requests.get(
            f"{BASE_URL}/api/admin/prompt",
            headers=ADMIN_HEADERS
        ).json()
        assert verify["is_custom"] is True
        assert verify["system_prompt"] == custom_system
        
        # Reset to default
        reset_response = requests.delete(
            f"{BASE_URL}/api/admin/prompt",
            headers=ADMIN_HEADERS
        )
        assert reset_response.status_code == 200
        
        # Verify reset
        final = requests.get(
            f"{BASE_URL}/api/admin/prompt",
            headers=ADMIN_HEADERS
        ).json()
        assert final["is_custom"] is False
        print("✓ Prompt update and reset working")


class TestAdminFetch:
    """Test /api/admin/fetch endpoint - just verify it accepts request"""
    
    def test_fetch_requires_auth(self):
        response = requests.post(f"{BASE_URL}/api/admin/fetch")
        assert response.status_code == 401
        print("✓ Fetch requires auth (401)")
    
    def test_fetch_endpoint_exists(self):
        """Verify endpoint exists and is callable"""
        response = requests.post(
            f"{BASE_URL}/api/admin/fetch",
            headers=ADMIN_HEADERS
        )
        # Can return 200 (success) or already_fetching status
        assert response.status_code == 200
        print(f"✓ Fetch endpoint responds: {response.json()}")


class TestAdminCompare:
    """Test /api/admin/compare endpoint"""
    
    def test_compare_requires_auth(self):
        response = requests.post(f"{BASE_URL}/api/admin/compare")
        assert response.status_code == 401
        print("✓ Compare requires auth (401)")
    
    def test_compare_endpoint_exists(self):
        """Verify endpoint exists and is callable"""
        response = requests.post(
            f"{BASE_URL}/api/admin/compare",
            headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        print(f"✓ Compare endpoint responds: {data}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
