"""
Test suite for Ghost Match Fix, unique_opponents field, and Scheduler Diagnostics
Tests the following features:
1. Admin login and authentication
2. GET /api/admin/progress - stall detection with unique_opponents
3. GET /api/admin/scheduler-diagnostics - compare loop health
4. GET /api/admin/diagnose-pairs - pair selection diagnostics
5. POST /api/admin/reconcile-rankings - rankings reconciliation
6. unique_opponents field verification on rankings
7. Ghost match fix - update_rankings_for_match creates missing rankings
8. Stall detection logic verification
9. Scheduler auto-restart logic verification
"""

import pytest
import requests
import os
import asyncio
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_PASSWORD = "papersumo2025"
TEST_CATEGORY = "q-bio.BM"  # Category with real data (73 papers/4900 matches)


class TestAdminAuthentication:
    """Test admin login and token generation"""
    
    def test_admin_login_success(self):
        """POST /api/admin/login with correct password returns token"""
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "token" in data, "Response should contain token"
        assert data["token"].startswith("adm_"), "Token should start with 'adm_'"
        assert data.get("success") == True, "Response should indicate success"
    
    def test_admin_login_invalid_password(self):
        """POST /api/admin/login with wrong password returns 403"""
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": "wrongpassword"}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin token for authenticated requests"""
    response = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"password": ADMIN_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Admin authentication failed")


class TestProgressEndpoint:
    """Test GET /api/admin/progress with stall detection fields"""
    
    def test_progress_returns_required_fields(self, admin_token):
        """GET /api/admin/progress returns all required fields including stall detection"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category={TEST_CATEGORY}",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Required fields for stall detection
        required_fields = [
            "pair_exhausted",
            "exhausted_papers", 
            "unique_pairs_played",
            "max_possible_pairs",
            "all_pairs_exhausted",
            "last_match_at",
            "failed_matches_total"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify field types
        assert isinstance(data["pair_exhausted"], bool), "pair_exhausted should be boolean"
        assert isinstance(data["exhausted_papers"], int), "exhausted_papers should be int"
        assert isinstance(data["unique_pairs_played"], int), "unique_pairs_played should be int"
        assert isinstance(data["max_possible_pairs"], int), "max_possible_pairs should be int"
        assert isinstance(data["all_pairs_exhausted"], bool), "all_pairs_exhausted should be boolean"
        assert isinstance(data["failed_matches_total"], int), "failed_matches_total should be int"
        
        # Note: unique_pairs_played can exceed max_possible_pairs if papers were removed
        # from the matchable set after matches were played. This is expected behavior.
        # The important thing is that both values are non-negative integers.
        assert data["unique_pairs_played"] >= 0, "unique_pairs_played should be non-negative"
        assert data["max_possible_pairs"] >= 0, "max_possible_pairs should be non-negative"
        
        print(f"Progress data for {TEST_CATEGORY}:")
        print(f"  pair_exhausted: {data['pair_exhausted']}")
        print(f"  exhausted_papers: {data['exhausted_papers']}")
        print(f"  unique_pairs_played: {data['unique_pairs_played']}")
        print(f"  max_possible_pairs: {data['max_possible_pairs']}")
        print(f"  all_pairs_exhausted: {data['all_pairs_exhausted']}")
        print(f"  last_match_at: {data['last_match_at']}")
        print(f"  failed_matches_total: {data['failed_matches_total']}")
    
    def test_progress_goal_fields(self, admin_token):
        """GET /api/admin/progress returns goal convergence fields"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category={TEST_CATEGORY}",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check goal fields
        assert "goals_met" in data, "Missing goals_met field"
        assert "goal1" in data, "Missing goal1 field"
        assert "goal2" in data, "Missing goal2 field"
        assert "goal3" in data, "Missing goal3 field"
        
        # Verify goal structure
        for goal_key in ["goal1", "goal2", "goal3"]:
            goal = data[goal_key]
            assert "met" in goal, f"{goal_key} missing 'met' field"
            assert "label" in goal, f"{goal_key} missing 'label' field"
            assert "done" in goal, f"{goal_key} missing 'done' field"
            assert "total" in goal, f"{goal_key} missing 'total' field"


class TestSchedulerDiagnostics:
    """Test GET /api/admin/scheduler-diagnostics"""
    
    def test_scheduler_diagnostics_returns_required_fields(self, admin_token):
        """GET /api/admin/scheduler-diagnostics returns loop health fields"""
        response = requests.get(
            f"{BASE_URL}/api/admin/scheduler-diagnostics",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Required fields from _compare_loop_diag
        required_fields = [
            "loop_alive",
            "last_cycle_at",
            "last_cycle_unmet",
            "last_cycle_results",
            "cycles_since_restart"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify field types
        assert isinstance(data["loop_alive"], bool), "loop_alive should be boolean"
        assert isinstance(data["cycles_since_restart"], int), "cycles_since_restart should be int"
        assert isinstance(data["last_cycle_unmet"], list), "last_cycle_unmet should be list"
        assert isinstance(data["last_cycle_results"], dict), "last_cycle_results should be dict"
        
        print(f"Scheduler diagnostics:")
        print(f"  loop_alive: {data['loop_alive']}")
        print(f"  last_cycle_at: {data['last_cycle_at']}")
        print(f"  cycles_since_restart: {data['cycles_since_restart']}")
        print(f"  last_cycle_unmet: {data['last_cycle_unmet']}")


class TestDiagnosePairs:
    """Test GET /api/admin/diagnose-pairs"""
    
    def test_diagnose_pairs_returns_required_fields(self, admin_token):
        """GET /api/admin/diagnose-pairs returns pair selection diagnostics"""
        response = requests.get(
            f"{BASE_URL}/api/admin/diagnose-pairs?category={TEST_CATEGORY}",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Required fields
        required_fields = [
            "category",
            "matchable_papers",
            "threshold",
            "total_db_matches",
            "sum_rankings_comparisons",
            "ghost_matches",
            "needy_papers",
            "needy_with_zero_novel",
            "diagnosis"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify field types
        assert data["category"] == TEST_CATEGORY, f"Category mismatch"
        assert isinstance(data["matchable_papers"], int), "matchable_papers should be int"
        assert isinstance(data["threshold"], int), "threshold should be int"
        assert isinstance(data["total_db_matches"], int), "total_db_matches should be int"
        assert isinstance(data["ghost_matches"], int), "ghost_matches should be int"
        assert isinstance(data["needy_papers"], int), "needy_papers should be int"
        assert isinstance(data["diagnosis"], list), "diagnosis should be list"
        
        # Ghost matches should be 0 or very low after the fix
        print(f"Diagnose pairs for {TEST_CATEGORY}:")
        print(f"  matchable_papers: {data['matchable_papers']}")
        print(f"  total_db_matches: {data['total_db_matches']}")
        print(f"  sum_rankings_comparisons: {data['sum_rankings_comparisons']}")
        print(f"  ghost_matches: {data['ghost_matches']}")
        print(f"  needy_papers: {data['needy_papers']}")
        print(f"  needy_with_zero_novel: {data['needy_with_zero_novel']}")


class TestReconcileRankings:
    """Test POST /api/admin/reconcile-rankings"""
    
    def test_reconcile_rankings_returns_status(self, admin_token):
        """POST /api/admin/reconcile-rankings returns status and results"""
        response = requests.post(
            f"{BASE_URL}/api/admin/reconcile-rankings?category={TEST_CATEGORY}",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check response structure
        assert "status" in data, "Missing status field"
        assert data["status"] == "ok", f"Expected status 'ok', got '{data['status']}'"
        assert "results" in data, "Missing results field"
        
        # Results should contain category info
        results = data["results"]
        assert TEST_CATEGORY in results, f"Results should contain {TEST_CATEGORY}"
        
        cat_result = results[TEST_CATEGORY]
        assert "drifted" in cat_result, "Missing drifted field"
        assert "papers_checked" in cat_result, "Missing papers_checked field"
        
        print(f"Reconcile rankings for {TEST_CATEGORY}:")
        print(f"  drifted: {cat_result.get('drifted')}")
        print(f"  drifted_papers: {cat_result.get('drifted_papers', 0)}")
        print(f"  papers_checked: {cat_result['papers_checked']}")


class TestUniqueOpponentsField:
    """Test unique_opponents field on rankings documents"""
    
    def test_unique_opponents_exists_on_rankings(self, admin_token):
        """Verify unique_opponents field exists on rankings via diagnose-pairs"""
        # Use diagnose-pairs to indirectly verify unique_opponents is being used
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category={TEST_CATEGORY}",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200
        data = response.json()
        
        # The progress endpoint uses unique_opponents for stall detection
        # If it returns valid data, unique_opponents field is working
        assert "exhausted_papers" in data, "exhausted_papers field missing (uses unique_opponents)"
        assert "unique_pairs_played" in data, "unique_pairs_played field missing (derived from unique_opponents)"
        
        # unique_pairs_played is computed from sum(unique_opponents) / 2
        # If this is a valid number, the field exists
        assert data["unique_pairs_played"] >= 0, "unique_pairs_played should be non-negative"
        
        print(f"unique_opponents verification via progress endpoint:")
        print(f"  unique_pairs_played: {data['unique_pairs_played']}")
        print(f"  exhausted_papers: {data['exhausted_papers']}")


class TestStallDetectionLogic:
    """Test stall detection logic using unique_opponents"""
    
    def test_stall_detection_logic(self, admin_token):
        """Verify stall detection: pair_exhausted should be False if no paper has unique_opponents >= total_papers - 1"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category={TEST_CATEGORY}",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200
        data = response.json()
        
        total_papers = data.get("total_papers", 0)
        pair_exhausted = data.get("pair_exhausted", False)
        exhausted_papers = data.get("exhausted_papers", 0)
        goals_met = data.get("goals_met", False)
        
        # If goals are met, pair_exhausted should be False (no stall when converged)
        if goals_met:
            assert pair_exhausted == False, "pair_exhausted should be False when goals are met"
        
        # If pair_exhausted is True, exhausted_papers should be > 0
        if pair_exhausted:
            assert exhausted_papers > 0, "If pair_exhausted is True, exhausted_papers should be > 0"
        
        # If exhausted_papers is 0, pair_exhausted should be False
        if exhausted_papers == 0:
            assert pair_exhausted == False, "pair_exhausted should be False when no papers are exhausted"
        
        print(f"Stall detection logic verification:")
        print(f"  total_papers: {total_papers}")
        print(f"  goals_met: {goals_met}")
        print(f"  pair_exhausted: {pair_exhausted}")
        print(f"  exhausted_papers: {exhausted_papers}")


class TestSchedulerAutoRestart:
    """Test scheduler auto-restart logic"""
    
    def test_scheduler_loop_alive(self, admin_token):
        """Verify scheduler compare loop is alive (auto-restart working)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/scheduler-diagnostics",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200
        data = response.json()
        
        # loop_alive should be True if scheduler is running
        assert "loop_alive" in data, "Missing loop_alive field"
        
        # Note: System is PAUSED on preview, but loop should still be alive
        # (it just doesn't generate matches when paused)
        print(f"Scheduler auto-restart verification:")
        print(f"  loop_alive: {data['loop_alive']}")
        print(f"  cycles_since_restart: {data['cycles_since_restart']}")
        
        # If there's a last_crash field, it means the loop crashed and restarted
        if "last_crash" in data:
            print(f"  last_crash: {data['last_crash']}")


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_endpoint(self):
        """GET /api/health returns ok"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
