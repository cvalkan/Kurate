"""
Match Count Consistency Tests - Iteration 19
Tests that /api/admin/status, /api/admin/progress, and /api/leaderboard 
show the SAME match count for each category.
Also verifies experiment matches are excluded from tournament operations.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_TOKEN = "papersumo2025"

# Expected match counts from main agent
EXPECTED_COUNTS = {
    "cs.RO": 3774,
    "cs.DC": 2828,
    "econ.GN": 2182,
    "physics.comp-ph": 2305,
    "q-bio.BM": 1897,
}

# Total should be sum of all standard matches
EXPECTED_TOTAL = sum(EXPECTED_COUNTS.values())  # 12986


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": ADMIN_TOKEN}


class TestMatchCountConsistency:
    """Verify match counts are consistent across all three views for each category."""

    @pytest.mark.parametrize("category,expected_count", list(EXPECTED_COUNTS.items()))
    def test_admin_status_match_count(self, admin_headers, category, expected_count):
        """Test /api/admin/status returns correct match count for category."""
        response = requests.get(
            f"{BASE_URL}/api/admin/status?category={category}",
            headers=admin_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["total_matches"] == expected_count, \
            f"Admin status {category}: expected {expected_count}, got {data['total_matches']}"
        assert data["category"] == category

    @pytest.mark.parametrize("category,expected_count", list(EXPECTED_COUNTS.items()))
    def test_admin_progress_match_count(self, admin_headers, category, expected_count):
        """Test /api/admin/progress returns correct match count for category."""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category={category}",
            headers=admin_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["total_matches"] == expected_count, \
            f"Admin progress {category}: expected {expected_count}, got {data['total_matches']}"
        assert data["category"] == category

    @pytest.mark.parametrize("category,expected_count", list(EXPECTED_COUNTS.items()))
    def test_leaderboard_match_count(self, category, expected_count):
        """Test /api/leaderboard returns correct match count for category."""
        response = requests.get(f"{BASE_URL}/api/leaderboard?category={category}&limit=1")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["total_matches"] == expected_count, \
            f"Leaderboard {category}: expected {expected_count}, got {data['total_matches']}"
        assert data["category"] == category

    def test_all_views_match_for_csro(self, admin_headers):
        """Verify cs.RO has identical match counts across all three views."""
        status_resp = requests.get(f"{BASE_URL}/api/admin/status?category=cs.RO", headers=admin_headers)
        progress_resp = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.RO", headers=admin_headers)
        leaderboard_resp = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&limit=1")

        assert status_resp.status_code == 200
        assert progress_resp.status_code == 200
        assert leaderboard_resp.status_code == 200

        status_count = status_resp.json()["total_matches"]
        progress_count = progress_resp.json()["total_matches"]
        leaderboard_count = leaderboard_resp.json()["total_matches"]

        assert status_count == progress_count == leaderboard_count == EXPECTED_COUNTS["cs.RO"], \
            f"cs.RO mismatch: status={status_count}, progress={progress_count}, leaderboard={leaderboard_count}"

    def test_all_views_match_for_csdc(self, admin_headers):
        """Verify cs.DC has identical match counts across all three views."""
        status_resp = requests.get(f"{BASE_URL}/api/admin/status?category=cs.DC", headers=admin_headers)
        progress_resp = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.DC", headers=admin_headers)
        leaderboard_resp = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.DC&limit=1")

        assert status_resp.status_code == 200
        assert progress_resp.status_code == 200
        assert leaderboard_resp.status_code == 200

        status_count = status_resp.json()["total_matches"]
        progress_count = progress_resp.json()["total_matches"]
        leaderboard_count = leaderboard_resp.json()["total_matches"]

        assert status_count == progress_count == leaderboard_count == EXPECTED_COUNTS["cs.DC"], \
            f"cs.DC mismatch: status={status_count}, progress={progress_count}, leaderboard={leaderboard_count}"

    def test_all_views_match_for_econgn(self, admin_headers):
        """Verify econ.GN has identical match counts across all three views."""
        status_resp = requests.get(f"{BASE_URL}/api/admin/status?category=econ.GN", headers=admin_headers)
        progress_resp = requests.get(f"{BASE_URL}/api/admin/progress?category=econ.GN", headers=admin_headers)
        leaderboard_resp = requests.get(f"{BASE_URL}/api/leaderboard?category=econ.GN&limit=1")

        assert status_resp.status_code == 200
        assert progress_resp.status_code == 200
        assert leaderboard_resp.status_code == 200

        status_count = status_resp.json()["total_matches"]
        progress_count = progress_resp.json()["total_matches"]
        leaderboard_count = leaderboard_resp.json()["total_matches"]

        assert status_count == progress_count == leaderboard_count == EXPECTED_COUNTS["econ.GN"], \
            f"econ.GN mismatch: status={status_count}, progress={progress_count}, leaderboard={leaderboard_count}"


class TestSchedulerStatus:
    """Test scheduler status correctly reflects tournament states."""

    def test_csro_not_goals_met_idle(self, admin_headers):
        """cs.RO should NOT show 'Goals met — idle' since Goal 3 is not met."""
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        data = response.json()
        
        # cs.RO should be 'Tournament paused' not 'Goals met — idle'
        scheduler_cats = data["scheduler"]["categories"]
        assert scheduler_cats["cs.RO"] != "Goals met — idle", \
            f"cs.RO incorrectly shows 'Goals met — idle': {scheduler_cats['cs.RO']}"
        # It should show 'Tournament paused'
        assert "paused" in scheduler_cats["cs.RO"].lower(), \
            f"cs.RO should show 'Tournament paused', got: {scheduler_cats['cs.RO']}"

    def test_csro_progress_goals_met_false(self, admin_headers):
        """cs.RO goals_met should be False (Goal 3 not met: 10/21)."""
        response = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.RO", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data["goals_met"] == False, \
            f"cs.RO goals_met should be False, got: {data['goals_met']}"
        
        # Verify Goal 3 is not met
        assert data["goal3"]["met"] == False, \
            f"cs.RO Goal 3 should not be met, got: {data['goal3']}"
        assert data["goal3"]["done"] == 10, \
            f"cs.RO Goal 3 done should be 10, got: {data['goal3']['done']}"
        assert data["goal3"]["total"] == 21, \
            f"cs.RO Goal 3 total should be 21, got: {data['goal3']['total']}"

    def test_csdc_progress_goals_met_true(self, admin_headers):
        """cs.DC goals_met should be True."""
        response = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.DC", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data["goals_met"] == True, \
            f"cs.DC goals_met should be True, got: {data['goals_met']}"

    def test_other_categories_goals_met_idle(self):
        """Other categories (cs.DC, econ.GN, etc.) should show 'Goals met — idle'."""
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        data = response.json()
        
        scheduler_cats = data["scheduler"]["categories"]
        for cat in ["cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]:
            assert scheduler_cats[cat] == "Goals met — idle", \
                f"{cat} should show 'Goals met — idle', got: {scheduler_cats[cat]}"


class TestPaperDetailMatchCount:
    """Verify paper detail endpoint shows correct match count."""

    def test_top_robotics_paper_match_count(self):
        """Paper detail for top cs.RO paper should show 152 matches (from leaderboard)."""
        paper_id = "eaa080f2-dcf2-406f-be8b-3a474452b0da"
        
        # Get paper detail
        response = requests.get(f"{BASE_URL}/api/papers/{paper_id}")
        assert response.status_code == 200
        data = response.json()
        
        paper_comparisons = data["stats"]["comparisons"]
        
        # Get leaderboard to verify
        lb_response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&limit=1")
        assert lb_response.status_code == 200
        lb_data = lb_response.json()
        
        leaderboard_comparisons = lb_data["leaderboard"][0]["comparisons"]
        
        # Paper detail should match leaderboard
        assert paper_comparisons == leaderboard_comparisons, \
            f"Paper detail matches ({paper_comparisons}) != leaderboard ({leaderboard_comparisons})"
        
        # Should be 152 as expected
        assert paper_comparisons == 152, \
            f"Expected 152 matches for top paper, got {paper_comparisons}"


class TestPublicStatusTotalMatches:
    """Verify public /api/status total_matches is sum of all category standard matches."""

    def test_public_status_total_matches(self):
        """Public status should show correct total (no experiment inflation)."""
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        data = response.json()
        
        total_matches = data["total_matches"]
        
        assert total_matches == EXPECTED_TOTAL, \
            f"Expected total_matches={EXPECTED_TOTAL}, got {total_matches}"


class TestRecentMatchesNoExperimentMode:
    """Verify recent matches in admin status don't include experiment matches."""

    def test_admin_status_recent_matches_no_mode(self, admin_headers):
        """Recent matches should not have 'mode' field (standard matches only)."""
        response = requests.get(f"{BASE_URL}/api/admin/status?category=cs.RO", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        recent_matches = data["recent_matches"]
        assert len(recent_matches) > 0, "Should have recent matches"
        
        for match in recent_matches:
            # Standard matches should NOT have a 'mode' field
            assert "mode" not in match, \
                f"Recent match should not have 'mode' field: {match.get('id')}"


class TestCrossCategoryIsolation:
    """Verify match counts are properly isolated per category."""

    def test_categories_have_different_counts(self, admin_headers):
        """Each category should have its own distinct match count."""
        counts = {}
        for category in EXPECTED_COUNTS.keys():
            response = requests.get(
                f"{BASE_URL}/api/admin/status?category={category}",
                headers=admin_headers
            )
            assert response.status_code == 200
            counts[category] = response.json()["total_matches"]
        
        # Verify all counts match expected
        for cat, count in counts.items():
            assert count == EXPECTED_COUNTS[cat], \
                f"{cat}: expected {EXPECTED_COUNTS[cat]}, got {count}"
        
        # Verify sum equals total
        assert sum(counts.values()) == EXPECTED_TOTAL, \
            f"Sum of category counts ({sum(counts.values())}) != expected total ({EXPECTED_TOTAL})"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
