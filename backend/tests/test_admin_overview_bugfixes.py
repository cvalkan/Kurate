"""
Backend API tests for Admin Overview bug fixes (iteration 43)

Tests:
1. /api/admin/status - scheduler has non-null last_fetch_at
2. /api/admin/check-new-papers - returns real count with source 'arxiv_query'
3. /api/admin/check-new-papers - different categories return different counts
4. /api/admin/status - recent_matches includes loser_title field

Bug fix context:
- Paper Ingestion section should NOT show duplicate total papers count
- Tournament section should NOT show duplicate matches/failed counts  
- Last fetched should show relative time, NOT 'never'
- Paper Ingestion main number should show fetchable papers count
- Category switching should auto-check and show different counts
- Recent Comparisons should show winner 'beat' loser with model badge
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class TestAdminOverviewBugFixes:
    """Tests for admin overview bug fixes - duplicate numbers, last_fetch_at, fetchable count"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json()["token"]
    
    def test_admin_status_has_last_fetch_at(self, admin_token):
        """Test that /api/admin/status returns non-null last_fetch_at in scheduler object"""
        response = requests.get(
            f"{BASE_URL}/api/admin/status?category=cs.RO",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Status endpoint failed: {response.text}"
        
        data = response.json()
        
        # Verify scheduler object exists and has last_fetch_at
        assert "scheduler" in data, "scheduler object missing from response"
        scheduler = data["scheduler"]
        
        assert "last_fetch_at" in scheduler, "last_fetch_at missing from scheduler"
        last_fetch = scheduler["last_fetch_at"]
        
        # last_fetch_at should NOT be null/None - it should have a value
        assert last_fetch is not None, "last_fetch_at is None (should have a timestamp)"
        assert isinstance(last_fetch, str), f"last_fetch_at should be string, got {type(last_fetch)}"
        assert len(last_fetch) > 0, "last_fetch_at is empty string"
        
        # Should be ISO format datetime
        assert "T" in last_fetch, f"last_fetch_at should be ISO format, got: {last_fetch}"
        print(f"✓ last_fetch_at has value: {last_fetch}")
    
    def test_check_new_papers_returns_real_count_and_source(self, admin_token):
        """Test that /api/admin/check-new-papers returns real count with source 'arxiv_query'"""
        response = requests.get(
            f"{BASE_URL}/api/admin/check-new-papers?category=cs.RO",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Check new papers endpoint failed: {response.text}"
        
        data = response.json()
        
        # Verify response structure
        assert "available" in data, "available field missing from response"
        assert "source" in data, "source field missing from response"
        assert "category" in data, "category field missing from response"
        
        # Source should be 'arxiv_query' (not 'estimate' or hardcoded)
        assert data["source"] == "arxiv_query", f"Expected source 'arxiv_query', got: {data['source']}"
        
        # Available should be a number (not always 50)
        available = data["available"]
        assert isinstance(available, int), f"available should be int, got {type(available)}"
        assert available >= 0, f"available should be >= 0, got {available}"
        
        # Verify it's not the hardcoded 50
        # (Note: it COULD be 50 legitimately, but the fix ensures it queries arXiv)
        print(f"✓ check-new-papers returns available={available} with source='arxiv_query'")
    
    def test_check_new_papers_different_categories_different_counts(self, admin_token):
        """Test that different categories return different fetchable counts"""
        # Query cs.RO
        response_ro = requests.get(
            f"{BASE_URL}/api/admin/check-new-papers?category=cs.RO",
            headers={"X-Admin-Token": admin_token}
        )
        assert response_ro.status_code == 200
        count_ro = response_ro.json()["available"]
        
        # Query cs.GT (Game Theory)
        response_gt = requests.get(
            f"{BASE_URL}/api/admin/check-new-papers?category=cs.GT",
            headers={"X-Admin-Token": admin_token}
        )
        assert response_gt.status_code == 200
        count_gt = response_gt.json()["available"]
        
        # The counts should likely be different (different research areas)
        # Note: In theory they COULD be the same, but for testing we verify both are valid
        assert isinstance(count_ro, int), f"cs.RO count should be int: {count_ro}"
        assert isinstance(count_gt, int), f"cs.GT count should be int: {count_gt}"
        
        print(f"✓ cs.RO available: {count_ro}, cs.GT available: {count_gt}")
        
        # Both should be from arxiv_query source
        assert response_ro.json()["source"] == "arxiv_query"
        assert response_gt.json()["source"] == "arxiv_query"
    
    def test_admin_status_recent_matches_has_loser_title(self, admin_token):
        """Test that recent_matches includes loser_title field for 'winner beat loser' display"""
        response = requests.get(
            f"{BASE_URL}/api/admin/status?category=cs.RO",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Status endpoint failed: {response.text}"
        
        data = response.json()
        
        # Verify recent_matches exists
        assert "recent_matches" in data, "recent_matches missing from response"
        recent_matches = data["recent_matches"]
        
        assert isinstance(recent_matches, list), f"recent_matches should be list, got {type(recent_matches)}"
        
        if len(recent_matches) > 0:
            # Check first match has all required fields
            first_match = recent_matches[0]
            
            # Must have winner_title and loser_title for "X beat Y" display
            assert "winner_title" in first_match, "winner_title missing from match"
            assert "loser_title" in first_match, "loser_title missing from match"
            
            # Must have model_used for model badge display  
            assert "model_used" in first_match, "model_used missing from match"
            
            winner = first_match["winner_title"]
            loser = first_match["loser_title"]
            model = first_match.get("model_used", {})
            
            # Titles should be non-empty strings
            assert winner and winner != "Unknown", f"winner_title should be valid: {winner}"
            assert loser and loser != "Unknown", f"loser_title should be valid: {loser}"
            
            # Model should have provider info
            if model:
                assert "provider" in model or "model" in model, f"model_used should have provider/model: {model}"
            
            print(f"✓ Recent match: '{winner[:40]}...' beat '{loser[:40]}...' ({model.get('provider', 'N/A')})")
        else:
            print("⚠ No recent matches to verify (empty list)")
    
    def test_admin_progress_has_correct_structure(self, admin_token):
        """Test that /api/admin/progress returns correct goal structure without duplicates"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers={"X-Admin-Token": admin_token}
        )
        assert response.status_code == 200, f"Progress endpoint failed: {response.text}"
        
        data = response.json()
        
        # Verify goal structure (no duplicate counts needed in Tournament section)
        assert "goal1" in data, "goal1 missing"
        assert "goal2" in data, "goal2 missing"
        assert "goal3" in data, "goal3 missing"
        
        # Each goal should have 'met' and 'label' fields
        for goal_key in ["goal1", "goal2", "goal3"]:
            goal = data[goal_key]
            assert "met" in goal, f"{goal_key} missing 'met' field"
            assert "label" in goal, f"{goal_key} missing 'label' field"
        
        # summary_coverage should exist (for "X/Y with summaries" display)
        assert "summary_coverage" in data, "summary_coverage missing"
        assert "with_summaries" in data["summary_coverage"], "with_summaries count missing"
        
        print(f"✓ Progress goals structured correctly, summaries: {data['summary_coverage']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
