"""
Tests for iteration 9 features:
1. Infinite scroll - verify leaderboard returns 250 papers (frontend renders 50 at a time)
2. Status bar count fix - verify total_papers vs leaderboard length
3. Paper categories - verify GET /api/papers/:id includes categories array
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPaperCategories:
    """Test paper detail endpoint includes categories array"""
    
    def test_paper_detail_includes_categories(self):
        """GET /api/papers/:id should include categories array"""
        # First get a paper id from leaderboard
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        assert response.status_code == 200
        leaderboard = response.json().get("leaderboard", [])
        assert len(leaderboard) > 0, "No papers in leaderboard"
        
        paper_id = leaderboard[0]["id"]
        
        # Fetch paper detail
        detail_response = requests.get(f"{BASE_URL}/api/papers/{paper_id}")
        assert detail_response.status_code == 200
        
        data = detail_response.json()
        paper = data.get("paper", {})
        
        # Verify categories field exists and is a list
        assert "categories" in paper, "Paper should have 'categories' field"
        assert isinstance(paper["categories"], list), "categories should be a list"
        assert len(paper["categories"]) > 0, "Paper should have at least one category"
        print(f"Paper {paper_id} has categories: {paper['categories']}")
    
    def test_paper_with_multiple_categories(self):
        """Verify papers can have multiple categories"""
        # Get all papers to find one with multiple categories
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert response.status_code == 200
        leaderboard = response.json().get("leaderboard", [])
        
        # Check papers until we find one with multiple categories
        found_multi_cat = False
        for paper in leaderboard[:50]:
            detail_response = requests.get(f"{BASE_URL}/api/papers/{paper['id']}")
            if detail_response.status_code == 200:
                categories = detail_response.json().get("paper", {}).get("categories", [])
                if len(categories) > 1:
                    print(f"Found paper with multiple categories: {categories}")
                    found_multi_cat = True
                    break
        
        assert found_multi_cat, "Should find at least one paper with multiple categories"


class TestStatusBarCount:
    """Test status bar count shows correct filtered vs total counts"""
    
    def test_recent_period_different_count(self):
        """Period filter 'recent' should return different leaderboard length vs total_papers"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "recent"
        })
        assert response.status_code == 200
        
        data = response.json()
        total_papers = data.get("total_papers", 0)
        leaderboard_len = len(data.get("leaderboard", []))
        
        print(f"Recent period: total_papers={total_papers}, leaderboard_len={leaderboard_len}")
        
        # Total papers should be >= leaderboard length
        assert total_papers >= leaderboard_len, "total_papers should be >= filtered count"
        
        # In this case recent typically shows fewer papers
        if leaderboard_len < total_papers:
            print(f"✓ Status bar should show '{leaderboard_len} papers ({total_papers} total)'")
    
    def test_all_time_same_count(self):
        """Period filter 'all' should show same count as total"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        assert response.status_code == 200
        
        data = response.json()
        total_papers = data.get("total_papers", 0)
        leaderboard_len = len(data.get("leaderboard", []))
        
        print(f"All time: total_papers={total_papers}, leaderboard_len={leaderboard_len}")
        
        # For "all" period, counts should match
        assert total_papers == leaderboard_len, "All time should show all papers"
        print(f"✓ Status bar should show '{leaderboard_len} papers' (no parenthetical)")


class TestInfiniteScrollData:
    """Test backend returns enough data for infinite scroll"""
    
    def test_show_all_returns_250_papers(self):
        """show_all with All Time should return 250 papers for infinite scroll"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert response.status_code == 200
        
        data = response.json()
        leaderboard = data.get("leaderboard", [])
        total_papers = data.get("total_papers", 0)
        
        print(f"show_all + all time: {len(leaderboard)} papers returned, total: {total_papers}")
        
        # Should return 250 papers (all papers across categories)
        assert len(leaderboard) == 250, f"Expected 250 papers, got {len(leaderboard)}"
        assert total_papers == 250, f"Expected total_papers=250, got {total_papers}"
    
    def test_papers_have_required_fields(self):
        """All papers in leaderboard should have required fields for display"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "show_all": "true",
            "period": "all"
        })
        assert response.status_code == 200
        
        leaderboard = response.json().get("leaderboard", [])
        
        required_fields = ["id", "rank", "title", "score"]
        
        for paper in leaderboard[:10]:  # Check first 10 papers
            for field in required_fields:
                assert field in paper, f"Paper missing required field: {field}"
        
        print(f"✓ All checked papers have required fields: {required_fields}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
