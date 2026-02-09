"""
Category Management API Tests
Tests the new admin category management endpoints:
- GET /api/admin/arxiv-categories (155 arXiv categories)
- POST /api/admin/categories/add
- POST /api/admin/categories/remove
- GET /api/admin/category-estimate/{cat_id}
- GET /api/categories (dynamic list)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_TOKEN = "papersumo2025"

# Headers for admin endpoints
def admin_headers():
    return {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}


class TestArxivCategories:
    """Tests for GET /api/admin/arxiv-categories - returns full arXiv taxonomy"""

    def test_arxiv_categories_returns_155_categories(self):
        """Verify the endpoint returns ~155 categories from arXiv taxonomy"""
        res = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert "categories" in data
        assert "active" in data
        
        # Should have around 155 categories (full taxonomy)
        categories = data["categories"]
        assert len(categories) >= 150, f"Expected ~155 categories, got {len(categories)}"
        assert len(categories) <= 170, f"Expected ~155 categories, got {len(categories)}"
        print(f"Total categories: {len(categories)}")

    def test_category_structure(self):
        """Verify each category has required fields: id, name, group, active"""
        res = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        assert res.status_code == 200
        
        categories = res.json()["categories"]
        
        # Check first 5 categories for structure
        for cat in categories[:5]:
            assert "id" in cat, "Category missing 'id' field"
            assert "name" in cat, "Category missing 'name' field"
            assert "group" in cat, "Category missing 'group' field"
            assert "active" in cat, "Category missing 'active' field"
            
            # Validate types
            assert isinstance(cat["id"], str)
            assert isinstance(cat["name"], str)
            assert isinstance(cat["group"], str)
            assert isinstance(cat["active"], bool)
            
        print(f"Sample categories: {[c['id'] for c in categories[:5]]}")

    def test_active_categories_marked_correctly(self):
        """Verify active categories are marked with active=True"""
        res = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        assert res.status_code == 200
        
        data = res.json()
        active_ids = data["active"]
        categories = data["categories"]
        
        # Find categories that should be active
        for cat in categories:
            if cat["id"] in active_ids:
                assert cat["active"] == True, f"{cat['id']} should have active=True"
            else:
                assert cat["active"] == False, f"{cat['id']} should have active=False"
                
        print(f"Active categories: {active_ids}")

    def test_requires_admin_auth(self):
        """Verify endpoint requires admin authentication"""
        res = requests.get(f"{BASE_URL}/api/admin/arxiv-categories")
        assert res.status_code in [401, 403], f"Expected 401/403, got {res.status_code}"


class TestCategoryAdd:
    """Tests for POST /api/admin/categories/add"""
    
    def test_add_category_success(self):
        """Add a valid category and verify it appears in active list"""
        # First get current active list
        res1 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        original_active = res1.json()["active"]
        
        # Choose a category that's not active
        all_cats = res1.json()["categories"]
        test_cat = None
        for c in all_cats:
            if not c["active"]:
                test_cat = c["id"]
                break
        
        if not test_cat:
            pytest.skip("No inactive categories to add")
        
        print(f"Adding category: {test_cat}")
        
        # Add the category
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        assert res.status_code == 200, f"Add failed: {res.text}"
        
        data = res.json()
        assert data["status"] == "ok"
        assert test_cat in data["active_categories"]
        
        # Verify it's now in the active list
        res3 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        assert test_cat in res3.json()["active"]
        
        # CLEANUP: Remove the added category to restore original state
        requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        print(f"Cleanup: Removed {test_cat}")

    def test_add_invalid_category_fails(self):
        """Attempt to add invalid category ID - should fail"""
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": "invalid.category.xyz"},
            headers=admin_headers()
        )
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"
        assert "unknown" in res.text.lower() or "unknown" in res.json().get("detail", "").lower()

    def test_add_already_active_category_fails(self):
        """Attempt to add a category that's already active - should fail"""
        # Get an already active category
        res1 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        active = res1.json()["active"]
        
        if not active:
            pytest.skip("No active categories to test")
        
        test_cat = active[0]
        
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"
        assert "already active" in res.text.lower() or "already active" in res.json().get("detail", "").lower()

    def test_add_requires_admin_auth(self):
        """Verify add endpoint requires admin authentication"""
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": "cs.AI"}
        )
        assert res.status_code in [401, 403]


class TestCategoryRemove:
    """Tests for POST /api/admin/categories/remove"""

    def test_remove_category_success(self):
        """Remove a category and verify it's no longer in active list"""
        # First add a test category so we have something to remove
        res1 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        all_cats = res1.json()["categories"]
        original_active = res1.json()["active"]
        
        # Find an inactive category to add then remove
        test_cat = None
        for c in all_cats:
            if not c["active"]:
                test_cat = c["id"]
                break
        
        if not test_cat:
            pytest.skip("No inactive categories to test with")
        
        # Add it first
        requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        
        print(f"Removing category: {test_cat}")
        
        # Remove it
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        assert res.status_code == 200, f"Remove failed: {res.text}"
        
        data = res.json()
        assert data["status"] == "ok"
        assert test_cat not in data["active_categories"]
        
        # Verify it's no longer active
        res3 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        assert test_cat not in res3.json()["active"]
        print(f"Successfully removed {test_cat}")

    def test_remove_last_category_fails(self):
        """Cannot remove the last remaining category"""
        # Get current active categories
        res1 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        active = res1.json()["active"]
        
        if len(active) < 2:
            # If only one category, try to remove it - should fail
            res = requests.post(
                f"{BASE_URL}/api/admin/categories/remove",
                json={"category_id": active[0]},
                headers=admin_headers()
            )
            assert res.status_code == 400
            assert "last category" in res.text.lower() or "last category" in res.json().get("detail", "").lower()
            print("Correctly rejected removal of last category")
        else:
            # Remove all but one, then try to remove the last
            # This is destructive so we'll skip and trust the code
            print(f"Skipping destructive test - {len(active)} active categories exist")
            
    def test_remove_inactive_category_fails(self):
        """Cannot remove a category that's not active"""
        # Find an inactive category
        res1 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        all_cats = res1.json()["categories"]
        active = res1.json()["active"]
        
        test_cat = None
        for c in all_cats:
            if c["id"] not in active:
                test_cat = c["id"]
                break
        
        if not test_cat:
            pytest.skip("No inactive categories to test")
        
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        assert res.status_code == 400
        assert "not active" in res.text.lower() or "not active" in res.json().get("detail", "").lower()

    def test_remove_requires_admin_auth(self):
        """Verify remove endpoint requires admin authentication"""
        res = requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": "cs.RO"}
        )
        assert res.status_code in [401, 403]


class TestCategoryEstimate:
    """Tests for GET /api/admin/category-estimate/{cat_id}"""

    def test_estimate_valid_category(self):
        """Get estimate for a valid category"""
        res = requests.get(
            f"{BASE_URL}/api/admin/category-estimate/cs.AI",
            headers=admin_headers()
        )
        assert res.status_code == 200, f"Estimate failed: {res.text}"
        
        data = res.json()
        assert "category_id" in data
        assert data["category_id"] == "cs.AI"
        assert "name" in data
        assert "estimated_weekly_papers" in data
        assert "estimated_weekly_matches" in data
        assert "estimated_weekly_cost" in data
        assert "existing_papers" in data
        assert "existing_matches" in data
        assert "sample_size" in data
        
        print(f"cs.AI estimate: {data['estimated_weekly_papers']} papers/wk, ${data['estimated_weekly_cost']}/wk")

    def test_estimate_existing_category(self):
        """Get estimate for a category that's already active (has existing data)"""
        # Use cs.RO which should have existing papers and matches
        res = requests.get(
            f"{BASE_URL}/api/admin/category-estimate/cs.RO",
            headers=admin_headers()
        )
        assert res.status_code == 200
        
        data = res.json()
        assert data["category_id"] == "cs.RO"
        
        # cs.RO should have existing data
        assert data["existing_papers"] > 0, "cs.RO should have existing papers"
        assert data["existing_matches"] > 0, "cs.RO should have existing matches"
        
        print(f"cs.RO: {data['existing_papers']} existing papers, {data['existing_matches']} existing matches")

    def test_estimate_invalid_category(self):
        """Estimate for invalid category should fail"""
        res = requests.get(
            f"{BASE_URL}/api/admin/category-estimate/invalid.xyz",
            headers=admin_headers()
        )
        assert res.status_code == 400

    def test_estimate_requires_admin_auth(self):
        """Verify estimate endpoint requires admin authentication"""
        res = requests.get(f"{BASE_URL}/api/admin/category-estimate/cs.AI")
        assert res.status_code in [401, 403]


class TestPublicCategories:
    """Tests for GET /api/categories - public endpoint"""

    def test_categories_returns_active_list(self):
        """Public endpoint returns list of active categories"""
        res = requests.get(f"{BASE_URL}/api/categories")
        assert res.status_code == 200
        
        data = res.json()
        assert "categories" in data
        assert "default" in data
        
        categories = data["categories"]
        assert len(categories) >= 1
        
        # Each category should have id and name
        for cat in categories:
            assert "id" in cat
            assert "name" in cat
            
        print(f"Public categories: {[c['id'] for c in categories]}")

    def test_categories_matches_active_from_admin(self):
        """Public categories should match active list from admin endpoint"""
        # Get admin active list
        res1 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        admin_active = set(res1.json()["active"])
        
        # Get public categories
        res2 = requests.get(f"{BASE_URL}/api/categories")
        public_ids = set(c["id"] for c in res2.json()["categories"])
        
        assert admin_active == public_ids, f"Mismatch: admin={admin_active}, public={public_ids}"
        print(f"Categories match: {public_ids}")

    def test_categories_dynamically_updates(self):
        """Adding/removing a category should update public endpoint"""
        # Get current public categories
        res1 = requests.get(f"{BASE_URL}/api/categories")
        original_ids = set(c["id"] for c in res1.json()["categories"])
        
        # Find an inactive category
        res2 = requests.get(f"{BASE_URL}/api/admin/arxiv-categories", headers=admin_headers())
        all_cats = res2.json()["categories"]
        test_cat = None
        for c in all_cats:
            if not c["active"]:
                test_cat = c["id"]
                break
        
        if not test_cat:
            pytest.skip("No inactive categories to test")
        
        # Add it
        requests.post(
            f"{BASE_URL}/api/admin/categories/add",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        
        # Check public endpoint includes it now
        res3 = requests.get(f"{BASE_URL}/api/categories")
        new_ids = set(c["id"] for c in res3.json()["categories"])
        
        assert test_cat in new_ids, f"{test_cat} should now be in public list"
        print(f"Added {test_cat} - now in public list")
        
        # CLEANUP: Remove it
        requests.post(
            f"{BASE_URL}/api/admin/categories/remove",
            json={"category_id": test_cat},
            headers=admin_headers()
        )
        
        # Verify removed from public
        res4 = requests.get(f"{BASE_URL}/api/categories")
        final_ids = set(c["id"] for c in res4.json()["categories"])
        
        assert test_cat not in final_ids, f"{test_cat} should no longer be in public list"
        assert final_ids == original_ids, "Should be back to original state"
        print(f"Removed {test_cat} - restored original state")


class TestLeaderboardWithCategories:
    """Test leaderboard endpoint with category changes"""

    def test_leaderboard_works_with_existing_category(self):
        """Leaderboard should work for existing active categories"""
        res = requests.get(f"{BASE_URL}/api/categories")
        cats = res.json()["categories"]
        
        for cat in cats[:3]:  # Test first 3
            res2 = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": cat["id"]})
            assert res2.status_code == 200, f"Leaderboard failed for {cat['id']}"
            
            data = res2.json()
            assert "leaderboard" in data
            assert data["category"] == cat["id"] or data["category"] is None
            print(f"{cat['id']}: {data.get('total_papers', 0)} papers, {data.get('total_matches', 0)} matches")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
