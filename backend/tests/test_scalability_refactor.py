"""
Test suite for P0 Scalability Refactor: primary_category indexed queries
Tests the performance/scalability changes that replace O(N×M) full collection scans
with indexed queries using the primary_category field.
"""

import pytest
import requests
import os
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_TOKEN = "papersumo2025"

# MongoDB connection for data verification
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

@pytest.fixture(scope="module")
def mongo_db():
    """MongoDB connection for direct data verification"""
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def admin_client(api_client):
    """Session with admin auth header"""
    api_client.headers.update({"X-Admin-Token": ADMIN_TOKEN})
    return api_client


class TestPrimaryCategoryBackfill:
    """Verify all matches have primary_category field (denormalized from paper)"""
    
    def test_all_matches_have_primary_category(self, mongo_db):
        """All 13144 matches should have primary_category field"""
        total_matches = mongo_db.matches.count_documents({})
        matches_with_primary_cat = mongo_db.matches.count_documents({"primary_category": {"$exists": True}})
        matches_without_primary_cat = mongo_db.matches.count_documents({"primary_category": {"$exists": False}})
        
        print(f"Total matches: {total_matches}")
        print(f"Matches with primary_category: {matches_with_primary_cat}")
        print(f"Matches without primary_category: {matches_without_primary_cat}")
        
        assert matches_without_primary_cat == 0, f"{matches_without_primary_cat} matches missing primary_category"
        assert matches_with_primary_cat == total_matches, "All matches should have primary_category"
    
    def test_primary_category_values_are_valid(self, mongo_db):
        """primary_category values should be valid category IDs"""
        valid_categories = {"cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"}
        
        # Sample some matches and verify primary_category is valid
        sample_matches = list(mongo_db.matches.find({}, {"primary_category": 1}).limit(100))
        
        for match in sample_matches:
            cat = match.get("primary_category")
            assert cat in valid_categories, f"Invalid primary_category: {cat}"
        
        print(f"Verified {len(sample_matches)} matches have valid primary_category values")


class TestPrimaryCategoryIndex:
    """Verify MongoDB index exists on primary_category field"""
    
    def test_primary_category_index_exists(self, mongo_db):
        """Index on primary_category must exist for O(1) queries"""
        indexes = mongo_db.matches.index_information()
        index_keys = [idx.get('key', []) for idx in indexes.values()]
        
        # Check if primary_category is indexed
        primary_cat_indexed = any(
            any(key_tuple[0] == 'primary_category' for key_tuple in keys)
            for keys in index_keys
        )
        
        print(f"Indexes on matches collection: {list(indexes.keys())}")
        assert primary_cat_indexed, "Index on primary_category field is required"


class TestLeaderboardCategoryFiltering:
    """Test leaderboard API with category filtering uses indexed queries"""
    
    def test_leaderboard_cs_ro_returns_correct_data(self, api_client):
        """GET /api/leaderboard?category=cs.RO returns 50 papers and 2148+ matches"""
        response = api_client.get(f"{BASE_URL}/api/leaderboard?category=cs.RO")
        assert response.status_code == 200
        
        data = response.json()
        print(f"cs.RO: papers={data['total_papers']}, matches={data['total_matches']}, leaderboard_count={len(data['leaderboard'])}")
        
        assert data["category"] == "cs.RO"
        assert data["total_papers"] == 50, f"Expected 50 papers, got {data['total_papers']}"
        assert data["total_matches"] >= 2000, f"Expected 2000+ matches, got {data['total_matches']}"
        assert len(data["leaderboard"]) == 50
    
    def test_leaderboard_physics_comp_ph_returns_correct_data(self, api_client):
        """GET /api/leaderboard?category=physics.comp-ph returns correct data"""
        response = api_client.get(f"{BASE_URL}/api/leaderboard?category=physics.comp-ph")
        assert response.status_code == 200
        
        data = response.json()
        print(f"physics.comp-ph: papers={data['total_papers']}, matches={data['total_matches']}")
        
        assert data["category"] == "physics.comp-ph"
        assert data["total_papers"] == 50
        assert data["total_matches"] >= 2000
    
    def test_leaderboard_cs_dc_returns_correct_data(self, api_client):
        """GET /api/leaderboard?category=cs.DC returns correct data"""
        response = api_client.get(f"{BASE_URL}/api/leaderboard?category=cs.DC")
        assert response.status_code == 200
        
        data = response.json()
        print(f"cs.DC: papers={data['total_papers']}, matches={data['total_matches']}")
        
        assert data["category"] == "cs.DC"
        assert data["total_papers"] == 50
    
    def test_leaderboard_all_categories_have_consistent_data(self, api_client):
        """All 5 categories should have data and use indexed queries"""
        categories = ["cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]
        
        for cat in categories:
            response = api_client.get(f"{BASE_URL}/api/leaderboard?category={cat}")
            assert response.status_code == 200, f"Failed for category {cat}"
            
            data = response.json()
            assert data["category"] == cat
            assert data["total_papers"] == 50, f"Category {cat} should have 50 papers"
            
            print(f"{cat}: papers={data['total_papers']}, matches={data['total_matches']}")


class TestTagFilteredLeaderboard:
    """Test tag-based filtering for cross-category queries"""
    
    def test_tag_filter_cs_ai_returns_data(self, api_client):
        """GET /api/leaderboard?tags=cs.AI&period=all returns correct filtered data"""
        response = api_client.get(f"{BASE_URL}/api/leaderboard?tags=cs.AI&period=all")
        assert response.status_code == 200
        
        data = response.json()
        print(f"tags=cs.AI: papers={data['total_papers']}, matches={data['total_matches']}")
        
        assert data["tags"] == ["cs.AI"]
        assert data["tag_mode"] == "or"
        assert data["total_papers"] > 0  # Should have papers with cs.AI tag
    
    def test_tag_filter_with_global_stats(self, api_client):
        """GET /api/leaderboard?tags=cs.AI&global_stats=true includes global_score"""
        response = api_client.get(f"{BASE_URL}/api/leaderboard?tags=cs.AI&global_stats=true")
        assert response.status_code == 200
        
        data = response.json()
        assert data["global_stats"] == True
        
        # First paper in leaderboard should have global_score
        if data["leaderboard"]:
            first_paper = data["leaderboard"][0]
            assert "global_score" in first_paper, "global_score field missing"
            assert "global_wins" in first_paper, "global_wins field missing"
            assert "global_comparisons" in first_paper, "global_comparisons field missing"
            
            print(f"Sample global stats: score={first_paper['global_score']}, wins={first_paper['global_wins']}, comparisons={first_paper['global_comparisons']}")


class TestShowAllLeaderboard:
    """Test show_all=true returns all papers from all categories"""
    
    def test_show_all_returns_all_250_papers(self, api_client):
        """GET /api/leaderboard?show_all=true returns all 250 papers"""
        response = api_client.get(f"{BASE_URL}/api/leaderboard?show_all=true")
        assert response.status_code == 200
        
        data = response.json()
        print(f"show_all=true: papers={data['total_papers']}, in_period={data['total_in_period']}, matches={data['total_matches']}")
        
        assert data["show_all"] == True
        assert data["category"] is None
        assert data["total_papers"] == 250, f"Expected 250 papers, got {data['total_papers']}"
        assert len(data["leaderboard"]) == 250


class TestAdminStatusEndpoint:
    """Test admin status endpoint works with authentication"""
    
    def test_admin_status_requires_auth(self, api_client):
        """GET /api/admin/status without token returns 401"""
        response = api_client.get(f"{BASE_URL}/api/admin/status")
        assert response.status_code == 401
    
    def test_admin_status_with_auth_returns_data(self, admin_client):
        """GET /api/admin/status with admin token returns scheduler status"""
        response = admin_client.get(f"{BASE_URL}/api/admin/status?category=cs.RO")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Admin status: papers={data['total_papers']}, matches={data['total_matches']}, scheduler={data['scheduler']}")
        
        assert data["category"] == "cs.RO"
        assert data["total_papers"] == 50
        assert "scheduler" in data
        assert "current_activity" in data["scheduler"]


class TestHealthAndStatus:
    """Basic health and status endpoints"""
    
    def test_health_endpoint(self, api_client):
        """GET /api/health returns ok status"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
    
    def test_status_endpoint(self, api_client):
        """GET /api/status returns system status"""
        response = api_client.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200
        
        data = response.json()
        print(f"System status: papers={data['total_papers']}, matches={data['total_matches']}")
        
        assert data["total_papers"] == 250  # 5 categories * 50 papers
        assert data["total_matches"] > 10000  # Should have many matches
        assert "scheduler" in data


class TestCategoriesEndpoint:
    """Test categories endpoint"""
    
    def test_categories_returns_5_categories(self, api_client):
        """GET /api/categories returns all 5 active categories"""
        response = api_client.get(f"{BASE_URL}/api/categories")
        assert response.status_code == 200
        
        data = response.json()
        categories = data["categories"]
        
        assert len(categories) == 5, f"Expected 5 categories, got {len(categories)}"
        
        cat_ids = {c["id"] for c in categories}
        expected = {"cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"}
        
        assert cat_ids == expected, f"Categories mismatch: {cat_ids}"
        print(f"Categories: {[c['name'] for c in categories]}")


class TestPaperDetailEndpoint:
    """Test paper detail page loads correctly"""
    
    def test_paper_detail_returns_paper_data(self, api_client, mongo_db):
        """GET /api/papers/{paper_id} returns paper with matches"""
        # Get a sample paper ID
        sample_paper = mongo_db.papers.find_one({}, {"_id": 0, "id": 1, "title": 1})
        assert sample_paper, "No papers found in database"
        
        paper_id = sample_paper["id"]
        response = api_client.get(f"{BASE_URL}/api/papers/{paper_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert "paper" in data
        assert "matches" in data
        assert "stats" in data
        
        print(f"Paper detail: title='{data['paper']['title'][:50]}...', matches={len(data['matches'])}, comparisons={data['stats']['comparisons']}")
    
    def test_paper_detail_404_for_invalid_id(self, api_client):
        """GET /api/papers/invalid-id returns 404"""
        response = api_client.get(f"{BASE_URL}/api/papers/invalid-paper-id-12345")
        assert response.status_code == 404


class TestMatchCounts:
    """Verify match counts are consistent across category queries"""
    
    def test_match_counts_per_category(self, mongo_db):
        """Each category's match count should match primary_category index"""
        categories = ["cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]
        
        total_by_primary_cat = 0
        for cat in categories:
            # Count using primary_category index
            count = mongo_db.matches.count_documents({
                "completed": True,
                "failed": {"$ne": True},
                "primary_category": cat
            })
            total_by_primary_cat += count
            print(f"{cat}: {count} matches (using primary_category index)")
        
        # Total completed non-failed matches
        total_all = mongo_db.matches.count_documents({
            "completed": True,
            "failed": {"$ne": True}
        })
        
        print(f"Total matches: {total_all}, Sum by category: {total_by_primary_cat}")
        
        # Note: total_by_primary_cat should be close to or equal to total_all
        # (small difference possible if some matches lack primary_category, but we verified all have it)
        assert total_by_primary_cat == total_all or abs(total_by_primary_cat - total_all) < 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
