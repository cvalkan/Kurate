"""
Tests for REVISED tag-based leaderboard features (iteration 8):
- show_all=true without tags returns ALL papers from all categories (~250)
- primary_category field present for all papers in show_all mode
- tag filter returns only matching papers (~7 for physics.chem-ph)
- global_stats with tags provides global stats fields
- global_comparisons >= comparisons for all papers
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

TEST_TAG = "physics.chem-ph"  # ~7 papers


class TestShowAllWithoutTags:
    """Test show_all=true without tags parameter (new flow: panel open, no tags selected)"""
    
    def test_show_all_without_tags_returns_all_papers(self):
        """GET /api/leaderboard?show_all=true&period=all should return ~250 papers"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        leaderboard = data.get("leaderboard", [])
        total_papers = data.get("total_papers", 0)
        
        print(f"Total papers: {total_papers}")
        print(f"Leaderboard count: {len(leaderboard)}")
        
        # Should have many papers (~250 expected)
        assert total_papers >= 100, f"Expected ~250 papers, got {total_papers}"
        assert len(leaderboard) >= 100, f"Expected ~250 in leaderboard, got {len(leaderboard)}"
        
    def test_show_all_without_tags_has_primary_category(self):
        """Papers should have primary_category field in show_all mode"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        leaderboard = data.get("leaderboard", [])
        assert len(leaderboard) > 0
        
        # Check first 20 papers have primary_category
        for paper in leaderboard[:20]:
            assert "primary_category" in paper, f"Paper {paper.get('id')} missing primary_category"
            assert paper["primary_category"], f"Paper {paper.get('id')} has empty primary_category"
            
        # Check variety of categories (should be multiple categories)
        categories = set(p["primary_category"] for p in leaderboard)
        print(f"Categories in show_all mode: {categories}")
        assert len(categories) >= 2, "Should have multiple categories in show_all mode"
        
    def test_show_all_response_fields(self):
        """Response should have correct fields including show_all flag"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        # Response should echo back show_all=true
        assert data.get("show_all") == True, "show_all should be True"
        assert data.get("tags") is None, "tags should be None in show_all mode without tags"
        assert data.get("category") is None, "category should be None in show_all mode"


class TestTagFilteredLeaderboard:
    """Test tag filter returns only matching papers"""
    
    def test_tag_filter_returns_matching_papers_only(self):
        """GET /api/leaderboard?tags=physics.chem-ph&period=all returns ~7 papers"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        leaderboard = data.get("leaderboard", [])
        total_papers = data.get("total_papers", 0)
        
        print(f"Total papers matching {TEST_TAG}: {total_papers}")
        print(f"Leaderboard count: {len(leaderboard)}")
        
        # Should be around 7 papers for physics.chem-ph
        assert total_papers <= 20, f"Expected ~7 papers for {TEST_TAG}, got {total_papers}"
        assert len(leaderboard) <= 20, f"Expected ~7 in leaderboard for {TEST_TAG}, got {len(leaderboard)}"
        
    def test_tag_filter_papers_have_primary_category(self):
        """Filtered papers should have primary_category field"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        leaderboard = data.get("leaderboard", [])
        if len(leaderboard) > 0:
            for paper in leaderboard:
                assert "primary_category" in paper, f"Paper {paper.get('id')} missing primary_category"


class TestGlobalStatsWithTags:
    """Test global_stats parameter with tags"""
    
    def test_global_stats_includes_global_fields(self):
        """GET /api/leaderboard?tags=xxx&global_stats=true includes global stats"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "global_stats": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        leaderboard = data.get("leaderboard", [])
        assert len(leaderboard) > 0, f"Expected papers for {TEST_TAG}"
        
        paper = leaderboard[0]
        assert "global_wins" in paper, "Missing global_wins"
        assert "global_comparisons" in paper, "Missing global_comparisons"
        assert "global_win_rate" in paper, "Missing global_win_rate"
        
        print(f"First paper global stats: wins={paper['global_wins']}, comparisons={paper['global_comparisons']}, win_rate={paper['global_win_rate']}")
        
    def test_global_comparisons_gte_local_comparisons(self):
        """global_comparisons >= comparisons for all matching papers"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "global_stats": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        leaderboard = data.get("leaderboard", [])
        
        for paper in leaderboard:
            local = paper.get("comparisons", 0)
            global_comp = paper.get("global_comparisons", 0)
            
            print(f"Paper {paper.get('id')[:20]}... - local: {local}, global: {global_comp}")
            
            assert global_comp >= local, f"global_comparisons ({global_comp}) should be >= comparisons ({local}) for paper {paper.get('id')}"


class TestCategoryVsShowAll:
    """Test category mode vs show_all mode return different data"""
    
    def test_category_returns_category_papers(self):
        """GET /api/leaderboard?category=cs.RO returns robotics papers only"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        # Should return ~50 robotics papers
        assert data.get("category") == "cs.RO"
        assert data.get("show_all") is None or data.get("show_all") == False
        
        leaderboard = data.get("leaderboard", [])
        print(f"Category cs.RO: {len(leaderboard)} papers")
        
    def test_show_all_returns_more_than_category(self):
        """show_all=true should return more papers than a single category"""
        res_category = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        res_all = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        
        assert res_category.status_code == 200
        assert res_all.status_code == 200
        
        cat_count = len(res_category.json().get("leaderboard", []))
        all_count = len(res_all.json().get("leaderboard", []))
        
        print(f"Category papers: {cat_count}, All papers: {all_count}")
        
        assert all_count > cat_count, "show_all should return more papers than a single category"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
