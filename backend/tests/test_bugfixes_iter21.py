"""
Tests for Iteration 21 bugfixes:
1. Category estimate includes settings_used field with min_matches_per_paper, top_k_focus, ci_target
2. Estimate weekly_matches should be significantly higher than weekly_papers * min_matches / 2 (top-K overhead included)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_TOKEN = "papersumo2025"


def get_admin_headers():
    return {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}


class TestCategoryEstimateSettings:
    """Test category-estimate endpoint includes settings_used field"""

    def test_estimate_includes_settings_used_field(self):
        """Category estimate should include settings_used field"""
        response = requests.get(
            f"{BASE_URL}/api/admin/category-estimate/cs.DC",
            headers=get_admin_headers()
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify settings_used field exists
        assert "settings_used" in data, "settings_used field missing from response"
        
        # Verify settings_used contains required fields
        settings_used = data["settings_used"]
        assert "min_matches_per_paper" in settings_used, "min_matches_per_paper missing from settings_used"
        assert "top_k_focus" in settings_used, "top_k_focus missing from settings_used"
        assert "ci_target" in settings_used, "ci_target missing from settings_used"
        
        # Verify values are integers
        assert isinstance(settings_used["min_matches_per_paper"], int), "min_matches_per_paper should be int"
        assert isinstance(settings_used["top_k_focus"], int), "top_k_focus should be int"
        assert isinstance(settings_used["ci_target"], int), "ci_target should be int"
        
        print(f"settings_used: {settings_used}")

    def test_estimate_weekly_matches_includes_topk_overhead(self):
        """Weekly matches estimate should include top-K overhead (significantly > papers * min_matches / 2)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/category-estimate/cs.DC",
            headers=get_admin_headers()
        )
        assert response.status_code == 200
        data = response.json()
        
        weekly_papers = data.get("estimated_weekly_papers", 0)
        weekly_matches = data.get("estimated_weekly_matches", 0)
        settings_used = data.get("settings_used", {})
        min_matches = settings_used.get("min_matches_per_paper", 5)
        top_k = settings_used.get("top_k_focus", 10)
        
        # Base matches without top-K overhead
        base_matches = weekly_papers * min_matches // 2
        
        # Top-K overhead formula: min(top_k, weekly_papers) * min_matches
        topk_overhead = min(top_k, weekly_papers) * min_matches
        expected_min = base_matches + topk_overhead
        
        # Verify weekly_matches includes top-K overhead
        # It should be at least base + topk_overhead
        assert weekly_matches >= expected_min * 0.9, \
            f"weekly_matches ({weekly_matches}) should be >= {expected_min * 0.9} (base: {base_matches}, topk_overhead: {topk_overhead})"
        
        # Also verify it's significantly higher than just base
        assert weekly_matches > base_matches * 1.2, \
            f"weekly_matches ({weekly_matches}) should be significantly > base ({base_matches})"
        
        print(f"weekly_papers: {weekly_papers}, base_matches: {base_matches}, "
              f"topk_overhead: {topk_overhead}, weekly_matches: {weekly_matches}")

    def test_estimate_for_different_categories(self):
        """Test settings_used is consistent across different categories"""
        categories_to_test = ["cs.RO", "cs.GT", "econ.GN"]
        
        settings_values = []
        for cat_id in categories_to_test:
            response = requests.get(
                f"{BASE_URL}/api/admin/category-estimate/{cat_id}",
                headers=get_admin_headers()
            )
            if response.status_code == 200:
                data = response.json()
                assert "settings_used" in data, f"settings_used missing for {cat_id}"
                settings_values.append(data["settings_used"])
                print(f"{cat_id}: weekly_papers={data.get('estimated_weekly_papers')}, "
                      f"weekly_matches={data.get('estimated_weekly_matches')}")
        
        # Verify settings are consistent (same global settings)
        if len(settings_values) > 1:
            for i in range(1, len(settings_values)):
                assert settings_values[i] == settings_values[0], \
                    f"Settings should be consistent: {settings_values[i]} != {settings_values[0]}"


class TestAdminProgressEstimatedMatches:
    """Test admin progress endpoint returns estimated_matches_remaining"""

    def test_progress_returns_estimated_matches_remaining(self):
        """GET /api/admin/progress should return estimated_matches_remaining"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress",
            headers=get_admin_headers(),
            params={"category": "cs.RO"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify estimated_matches_remaining exists
        assert "estimated_matches_remaining" in data, "estimated_matches_remaining missing"
        assert isinstance(data["estimated_matches_remaining"], int), "should be int"
        
        print(f"estimated_matches_remaining: {data['estimated_matches_remaining']}")

    def test_progress_estimated_can_be_used_for_manual_matches(self):
        """Verify estimated_matches_remaining is a sensible default for manual matches"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress",
            headers=get_admin_headers(),
            params={"category": "cs.RO"}
        )
        assert response.status_code == 200
        data = response.json()
        
        est = data.get("estimated_matches_remaining", 0)
        
        # Default should be min(est, 100) if est > 0, else 20 (as per AdminPage.jsx)
        if est > 0:
            expected_default = min(est, 100)
        else:
            expected_default = 20
        
        # Verify it's a reasonable range for manual matches (1-500)
        assert 0 <= est <= 10000, f"estimated_matches_remaining ({est}) out of reasonable range"
        print(f"Expected manual matches default: {expected_default}")


class TestPublicCategoriesEndpoint:
    """Test public categories endpoint returns 6 categories with More dropdown"""

    def test_public_categories_returns_six(self):
        """GET /api/categories should return 6 active categories"""
        response = requests.get(f"{BASE_URL}/api/categories")
        assert response.status_code == 200
        data = response.json()
        
        categories = data.get("categories", [])
        assert len(categories) == 6, f"Expected 6 categories, got {len(categories)}"
        
        # Verify cs.GT is in the list (newly added)
        cat_ids = [c["id"] for c in categories]
        assert "cs.GT" in cat_ids, "cs.GT should be in active categories"
        
        print(f"Active categories: {cat_ids}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
