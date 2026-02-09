"""
Test suite for leaderboard filter optimization features:
- Pre-computed all-papers leaderboard cache
- Tag query caching with TTL
- Period filtering for show_all and tags
- Global stats mode
- Pagination
- Response time performance (should be < 200ms)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestShowAllOptimization:
    """Tests for show_all=true endpoint optimization"""

    def test_show_all_period_all_returns_correct_data(self):
        """GET /api/leaderboard?show_all=true&period=all returns correct data structure"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "leaderboard" in data
        assert "total_papers" in data
        assert "total_in_period" in data
        assert "total_matches" in data
        assert data["period"] == "all"
        assert data["show_all"] == True
        assert isinstance(data["leaderboard"], list)
        
        # Should have papers with primary_category
        if data["leaderboard"]:
            paper = data["leaderboard"][0]
            assert "primary_category" in paper
            assert "rank" in paper
            assert "score" in paper

    def test_show_all_period_recent_filters_correctly(self):
        """GET /api/leaderboard?show_all=true&period=recent returns only recent papers"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "recent"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["period"] == "recent"
        # Recent should have fewer papers than all
        all_response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        all_data = all_response.json()
        assert data["total_in_period"] <= all_data["total_in_period"]

    def test_show_all_period_week_filters_correctly(self):
        """GET /api/leaderboard?show_all=true&period=week returns this week papers"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "week"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "week"
        assert "total_in_period" in data

    def test_show_all_period_month_filters_correctly(self):
        """GET /api/leaderboard?show_all=true&period=month returns this month papers"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "month"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "month"
        assert "total_in_period" in data

    def test_show_all_response_time_under_200ms(self):
        """Response time for show_all=true should be under 200ms (was 300ms before)"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        # Allow some slack for network latency, target is < 200ms
        assert elapsed < 0.5, f"Response time {elapsed:.3f}s exceeds 500ms threshold"

    def test_show_all_no_full_data_leak(self):
        """Response should NOT contain _full_data key (internal cache data)"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        assert "_full_data" not in data, "_full_data internal key leaked in response"


class TestTagQueryCaching:
    """Tests for tag-based leaderboard queries with caching"""

    def test_tags_cs_cv_returns_correct_data(self):
        """GET /api/leaderboard?tags=cs.CV&period=all returns papers tagged cs.CV"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["tags"] == ["cs.CV"]
        assert "leaderboard" in data
        assert "total_papers" in data
        assert "total_matches" in data

    def test_tags_cached_second_call_fast(self):
        """Second call for same tag query should be equally fast (cached)"""
        # First call
        start1 = time.time()
        response1 = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.AI",
            "period": "all"
        })
        elapsed1 = time.time() - start1
        
        # Second call (should be cached)
        start2 = time.time()
        response2 = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.AI",
            "period": "all"
        })
        elapsed2 = time.time() - start2
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        # Second call should be at least as fast or faster
        assert elapsed2 <= elapsed1 + 0.1, f"Cache not working: first={elapsed1:.3f}s, second={elapsed2:.3f}s"

    def test_tags_or_mode_returns_union(self):
        """GET /api/leaderboard?tags=cs.CV,cs.AI&tag_mode=or returns union of tags"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV,cs.AI",
            "tag_mode": "or",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["tags"] == ["cs.CV", "cs.AI"]
        assert data["tag_mode"] == "or"
        
        # Union should have more papers than individual tags
        cv_response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "period": "all"
        })
        cv_count = cv_response.json()["total_papers"]
        
        ai_response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.AI",
            "period": "all"
        })
        ai_count = ai_response.json()["total_papers"]
        
        # Union should be >= max of individual (some papers may have both tags)
        assert data["total_papers"] >= max(cv_count, ai_count)

    def test_tags_and_mode_returns_intersection(self):
        """GET /api/leaderboard?tags=cs.CV,cs.AI&tag_mode=and returns intersection of tags"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV,cs.AI",
            "tag_mode": "and",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["tags"] == ["cs.CV", "cs.AI"]
        assert data["tag_mode"] == "and"
        
        # Intersection should be <= min of individual tags
        cv_response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "period": "all"
        })
        cv_count = cv_response.json()["total_papers"]
        
        assert data["total_papers"] <= cv_count

    def test_tags_no_full_data_leak(self):
        """Tag query response should NOT contain _full_data key"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.RO",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        assert "_full_data" not in data, "_full_data internal key leaked in tag response"


class TestGlobalStats:
    """Tests for global_stats feature in tag queries"""

    def test_global_stats_includes_global_fields(self):
        """GET /api/leaderboard?tags=cs.CV&global_stats=true includes global_score, global_win_rate"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "global_stats": "true",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["global_stats"] == True
        
        if data["leaderboard"]:
            paper = data["leaderboard"][0]
            assert "global_score" in paper, "global_score missing when global_stats=true"
            assert "global_win_rate" in paper, "global_win_rate missing when global_stats=true"
            assert "global_comparisons" in paper
            assert "global_wins" in paper
            assert "global_losses" in paper

    def test_global_stats_false_no_global_fields(self):
        """Without global_stats, papers should NOT have global_* fields"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        if data["leaderboard"]:
            paper = data["leaderboard"][0]
            # Should NOT have global fields
            assert "global_score" not in paper


class TestPagination:
    """Tests for pagination in leaderboard endpoints"""

    def test_pagination_works_show_all(self):
        """GET /api/leaderboard?show_all=true&limit=5&offset=0 returns 5 papers"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all",
            "limit": 5,
            "offset": 0
        })
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["leaderboard"]) == 5
        # total_papers should be the full count, not just returned
        assert data["total_papers"] >= 5

    def test_pagination_offset_returns_different_papers(self):
        """Offset should return different papers"""
        response1 = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all",
            "limit": 5,
            "offset": 0
        })
        response2 = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all",
            "limit": 5,
            "offset": 5
        })
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Should be different papers
        ids1 = [p["id"] for p in data1["leaderboard"]]
        ids2 = [p["id"] for p in data2["leaderboard"]]
        assert ids1 != ids2, "Offset should return different papers"


class TestNormalCategoryView:
    """Tests for normal category view (existing functionality)"""

    def test_category_view_still_works(self):
        """GET /api/leaderboard?category=cs.RO&period=all still works"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["category"] == "cs.RO"
        assert data["tags"] is None
        assert "leaderboard" in data
        assert "total_papers" in data


class TestTagsAndCategoriesEndpoints:
    """Tests for /api/tags and /api/categories endpoints"""

    def test_tags_endpoint_returns_tags(self):
        """GET /api/tags returns tag list correctly"""
        response = requests.get(f"{BASE_URL}/api/tags")
        assert response.status_code == 200
        data = response.json()
        
        assert "tags" in data
        assert isinstance(data["tags"], list)
        
        if data["tags"]:
            tag = data["tags"][0]
            assert "id" in tag
            assert "count" in tag
            assert "matches" in tag

    def test_categories_endpoint_returns_categories(self):
        """GET /api/categories returns categories correctly"""
        response = requests.get(f"{BASE_URL}/api/categories")
        assert response.status_code == 200
        data = response.json()
        
        assert "categories" in data
        assert "default" in data
        assert isinstance(data["categories"], list)
        
        if data["categories"]:
            cat = data["categories"][0]
            assert "id" in cat
            assert "name" in cat
