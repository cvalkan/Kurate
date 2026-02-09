"""
Test suite for server-side keyword search and virtual scrolling features (Iteration 24)
- Tests GET /api/leaderboard with 'search' query parameter
- Verifies search filters papers by title
- Verifies re-ranking of filtered results (ranks start from 1)
- Tests search with different query combinations (category, show_all, tags)
- Verifies response time for search queries
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSearchWithCategory:
    """Test search parameter with standard category view"""
    
    def test_search_robot_returns_filtered_results(self):
        """GET /api/leaderboard?category=cs.RO&period=week&search=robot returns filtered results"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "week",
            "search": "robot"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "leaderboard" in data
        assert "total_in_period" in data
        
        # All returned papers should have 'robot' in title (case-insensitive)
        for paper in data["leaderboard"]:
            assert "robot" in paper.get("title", "").lower(), f"Paper '{paper.get('title')}' doesn't contain 'robot'"
        
        print(f"✓ Search 'robot' returned {len(data['leaderboard'])} filtered papers")
        
    def test_search_nonexistent_returns_empty(self):
        """GET /api/leaderboard?category=cs.RO&period=week&search=nonexistent returns empty leaderboard"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "week",
            "search": "nonexistent12345xyz"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert "leaderboard" in data
        assert len(data["leaderboard"]) == 0, f"Expected empty leaderboard, got {len(data['leaderboard'])} papers"
        assert data["total_in_period"] == 0
        
        print("✓ Search for nonexistent term returns empty leaderboard")
        
    def test_search_ranks_start_from_one(self):
        """Search results have correct re-ranked ranks starting from 1"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all",
            "search": "robot"
        })
        assert response.status_code == 200
        data = response.json()
        
        leaderboard = data["leaderboard"]
        if len(leaderboard) > 0:
            # Check first paper has rank 1
            assert leaderboard[0]["rank"] == 1, f"First paper should have rank 1, got {leaderboard[0]['rank']}"
            
            # Check ranks are sequential
            for i, paper in enumerate(leaderboard):
                expected_rank = i + 1
                assert paper["rank"] == expected_rank, f"Paper at index {i} should have rank {expected_rank}, got {paper['rank']}"
        
        print(f"✓ Search results have correct re-ranked ranks (1 to {len(leaderboard)})")
        
    def test_no_search_returns_all_papers(self):
        """GET /api/leaderboard?category=cs.RO&period=all (no search) returns all papers as before"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert "leaderboard" in data
        assert len(data["leaderboard"]) > 0
        
        # Compare with empty search
        response_empty = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all",
            "search": ""
        })
        assert response_empty.status_code == 200
        data_empty = response_empty.json()
        
        # Both should return same results
        assert len(data["leaderboard"]) == len(data_empty["leaderboard"])
        
        print(f"✓ No search param returns all {len(data['leaderboard'])} papers (same as empty search)")


class TestSearchWithShowAll:
    """Test search parameter with show_all=true (all papers view)"""
    
    def test_search_with_show_all(self):
        """GET /api/leaderboard?show_all=true&period=all&search=robot filters all-papers view"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all",
            "search": "robot"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert "leaderboard" in data
        assert data.get("show_all") == True
        
        # All returned papers should have 'robot' in title
        for paper in data["leaderboard"]:
            assert "robot" in paper.get("title", "").lower(), f"Paper '{paper.get('title')}' doesn't contain 'robot'"
        
        # Re-ranked starting from 1
        if len(data["leaderboard"]) > 0:
            assert data["leaderboard"][0]["rank"] == 1
        
        print(f"✓ Search with show_all=true returned {len(data['leaderboard'])} filtered papers")


class TestSearchWithTags:
    """Test search parameter with tag filtering"""
    
    def test_search_with_tags(self):
        """GET /api/leaderboard?tags=cs.CV&period=all&search=robot filters tag view"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "period": "all",
            "search": "robot"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert "leaderboard" in data
        assert data.get("tags") == ["cs.CV"]
        
        # All returned papers should have 'robot' in title
        for paper in data["leaderboard"]:
            assert "robot" in paper.get("title", "").lower(), f"Paper '{paper.get('title')}' doesn't contain 'robot'"
        
        print(f"✓ Search with tags=cs.CV returned {len(data['leaderboard'])} filtered papers")
        
    def test_search_with_tag_does_not_leak_full_data(self):
        """Search with tags does not expose _full_data in response"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": "cs.CV",
            "period": "all",
            "search": "robot"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert "_full_data" not in data, "_full_data should not be exposed in API response"
        
        print("✓ Search with tags does not leak _full_data")


class TestSearchResponseTime:
    """Test search query response times"""
    
    def test_search_response_time_under_200ms(self):
        """Response time for search queries is under 200ms"""
        # Warm up cache first
        requests.get(f"{BASE_URL}/api/leaderboard", params={"category": "cs.RO", "period": "all"})
        
        # Measure search query
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all",
            "search": "robot"
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 0.2, f"Response time {elapsed:.3f}s exceeds 200ms threshold"
        
        print(f"✓ Search response time: {elapsed*1000:.0f}ms (under 200ms threshold)")
        
    def test_search_with_show_all_response_time(self):
        """Search with show_all=true response time is reasonable"""
        # Warm up
        requests.get(f"{BASE_URL}/api/leaderboard", params={"show_all": "true", "period": "all"})
        
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all",
            "search": "learning"
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 0.3, f"Response time {elapsed:.3f}s exceeds 300ms threshold"
        
        print(f"✓ Search with show_all response time: {elapsed*1000:.0f}ms")


class TestSearchCaseSensitivity:
    """Test search is case-insensitive"""
    
    def test_search_is_case_insensitive(self):
        """Search is case-insensitive (robot vs ROBOT vs Robot)"""
        # Get results for lowercase
        resp_lower = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO", "period": "all", "search": "robot"
        })
        
        # Get results for uppercase
        resp_upper = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO", "period": "all", "search": "ROBOT"
        })
        
        # Get results for mixed case
        resp_mixed = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO", "period": "all", "search": "Robot"
        })
        
        assert resp_lower.status_code == 200
        assert resp_upper.status_code == 200
        assert resp_mixed.status_code == 200
        
        # All should return same number of results
        count_lower = len(resp_lower.json()["leaderboard"])
        count_upper = len(resp_upper.json()["leaderboard"])
        count_mixed = len(resp_mixed.json()["leaderboard"])
        
        assert count_lower == count_upper == count_mixed, f"Case sensitivity issue: lower={count_lower}, upper={count_upper}, mixed={count_mixed}"
        
        print(f"✓ Search is case-insensitive ({count_lower} results for all case variants)")


class TestSearchWithPeriods:
    """Test search with different period filters"""
    
    def test_search_with_week_period(self):
        """Search works with week period filter"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "week",
            "search": "robot"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("period") == "week"
        # All papers should contain 'robot' in title
        for paper in data["leaderboard"]:
            assert "robot" in paper.get("title", "").lower()
        
        print(f"✓ Search with period=week returned {len(data['leaderboard'])} papers")
        
    def test_search_with_month_period(self):
        """Search works with month period filter"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "month",
            "search": "learning"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("period") == "month"
        # All papers should contain search term
        for paper in data["leaderboard"]:
            assert "learning" in paper.get("title", "").lower()
        
        print(f"✓ Search with period=month returned {len(data['leaderboard'])} papers")


class TestSearchPagination:
    """Test search with pagination parameters"""
    
    def test_search_with_limit_offset(self):
        """Search works with limit and offset pagination"""
        # Get first 5 results
        resp1 = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO", "period": "all", "search": "robot", "limit": 5, "offset": 0
        })
        assert resp1.status_code == 200
        data1 = resp1.json()
        
        # Get next 5 results
        resp2 = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO", "period": "all", "search": "robot", "limit": 5, "offset": 5
        })
        assert resp2.status_code == 200
        data2 = resp2.json()
        
        # Results should be different (if enough papers match)
        if len(data1["leaderboard"]) == 5 and len(data2["leaderboard"]) > 0:
            ids1 = {p["id"] for p in data1["leaderboard"]}
            ids2 = {p["id"] for p in data2["leaderboard"]}
            assert ids1.isdisjoint(ids2), "Paginated results should not overlap"
            print("✓ Pagination returns different papers for different offsets")
        else:
            print(f"✓ Pagination works (only {len(data1['leaderboard']) + len(data2['leaderboard'])} total matching papers)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
