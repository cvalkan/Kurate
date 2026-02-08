"""
Tests for tag-based leaderboard features:
- Global/Local stats toggle (global_stats param)
- Show all papers toggle (show_all param)
- Response fields: matches_tag, primary_category, global_wins, global_comparisons, global_win_rate
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test tag - physics.chem-ph has ~7 papers according to main agent
TEST_TAG = "physics.chem-ph"


class TestTagLeaderboardShowAll:
    """Tests for show_all parameter in tag mode"""
    
    def test_show_all_true_returns_more_papers(self):
        """show_all=true should return all ~250 papers vs ~7 matching papers"""
        # Get with show_all=true
        res_all = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "true",
            "period": "all"
        })
        assert res_all.status_code == 200
        data_all = res_all.json()
        
        # Get with show_all=false (default)
        res_filtered = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "false",
            "period": "all"
        })
        assert res_filtered.status_code == 200
        data_filtered = res_filtered.json()
        
        # show_all should return way more papers
        print(f"show_all=true: {len(data_all['leaderboard'])} papers")
        print(f"show_all=false: {len(data_filtered['leaderboard'])} papers")
        
        assert len(data_all['leaderboard']) > len(data_filtered['leaderboard'])
        # Expect ~250 vs ~7
        assert len(data_all['leaderboard']) >= 100  # Should be significantly more
        assert data_filtered['total_papers'] <= 20  # Should be around 7
        
    def test_show_all_response_has_total_all_papers(self):
        """When show_all=true, total_all_papers should be larger than total_papers"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        # Check field exists
        assert "total_all_papers" in data
        assert "total_papers" in data
        
        # total_all_papers should be larger (all papers displayed)
        # total_papers should be smaller (only papers matching tags)
        print(f"total_all_papers: {data['total_all_papers']}")
        print(f"total_papers: {data['total_papers']}")
        assert data['total_all_papers'] > data['total_papers']
        
    def test_show_all_papers_have_matches_tag_flag(self):
        """Papers should have matches_tag field indicating if they match selected tags"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        papers = data['leaderboard']
        assert len(papers) > 0
        
        # Every paper should have matches_tag field
        for paper in papers[:20]:  # Check first 20
            assert 'matches_tag' in paper, f"Paper {paper.get('id')} missing matches_tag field"
        
        # Some should match, some should not
        matching = [p for p in papers if p['matches_tag']]
        not_matching = [p for p in papers if not p['matches_tag']]
        
        print(f"Papers matching tag: {len(matching)}")
        print(f"Papers not matching tag: {len(not_matching)}")
        
        assert len(matching) > 0, "Should have some matching papers"
        assert len(not_matching) > 0, "Should have some non-matching papers"
        
    def test_show_all_papers_have_primary_category(self):
        """Papers should have primary_category field for category badge display"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        papers = data['leaderboard']
        assert len(papers) > 0
        
        # Every paper should have primary_category
        for paper in papers[:20]:
            assert 'primary_category' in paper, f"Paper {paper.get('id')} missing primary_category"
            assert paper['primary_category'], f"Paper {paper.get('id')} has empty primary_category"
        
        # Check variety of categories
        categories = set(p['primary_category'] for p in papers)
        print(f"Categories found: {categories}")
        assert len(categories) > 1, "Should have multiple categories in show_all mode"


class TestTagLeaderboardGlobalStats:
    """Tests for global_stats parameter in tag mode"""
    
    def test_global_stats_false_no_global_fields(self):
        """When global_stats=false, response should NOT have global stats fields"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "false",
            "global_stats": "false",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        papers = data['leaderboard']
        if len(papers) > 0:
            paper = papers[0]
            # Should NOT have global stats when global_stats=false
            assert 'global_wins' not in paper or paper.get('global_wins') is None
            assert 'global_comparisons' not in paper or paper.get('global_comparisons') is None
            assert 'global_win_rate' not in paper or paper.get('global_win_rate') is None
            print("Confirmed: No global stats fields when global_stats=false")
    
    def test_global_stats_true_has_global_fields(self):
        """When global_stats=true, response should have global stats fields"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "false",
            "global_stats": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        papers = data['leaderboard']
        assert len(papers) > 0, "Should have papers for this tag"
        
        paper = papers[0]
        # Should have global stats fields
        assert 'global_wins' in paper, "Missing global_wins field"
        assert 'global_comparisons' in paper, "Missing global_comparisons field"
        assert 'global_win_rate' in paper, "Missing global_win_rate field"
        
        print(f"Paper global stats - wins: {paper['global_wins']}, comparisons: {paper['global_comparisons']}, win_rate: {paper['global_win_rate']}")
        
    def test_global_comparisons_gte_local_comparisons(self):
        """Global comparisons should be >= local comparisons for any paper"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "false",
            "global_stats": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        papers = data['leaderboard']
        
        for paper in papers:
            local_comparisons = paper.get('comparisons', 0)
            global_comparisons = paper.get('global_comparisons', 0)
            
            print(f"Paper {paper.get('id')}: local={local_comparisons}, global={global_comparisons}")
            
            # Global should always be >= local (more matches in total tournament)
            assert global_comparisons >= local_comparisons, \
                f"Global comparisons ({global_comparisons}) should be >= local ({local_comparisons}) for paper {paper.get('id')}"


class TestTagLeaderboardResponseFlags:
    """Tests for response-level flags"""
    
    def test_show_all_flag_in_response(self):
        """Response should echo back show_all parameter"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        assert 'show_all' in data
        assert data['show_all'] == True
        
    def test_global_stats_flag_in_response(self):
        """Response should echo back global_stats parameter"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "global_stats": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        assert 'global_stats' in data
        assert data['global_stats'] == True
        
    def test_tags_in_response(self):
        """Response should include tags array"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        assert 'tags' in data
        assert TEST_TAG in data['tags']


class TestTagLeaderboardCombined:
    """Tests for combined parameter scenarios"""
    
    def test_show_all_with_global_stats(self):
        """Test show_all=true with global_stats=true together"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": TEST_TAG,
            "show_all": "true",
            "global_stats": "true",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        papers = data['leaderboard']
        assert len(papers) > 100, "Should have many papers with show_all"
        
        # All papers should have global stats
        for paper in papers[:10]:
            assert 'global_comparisons' in paper
            assert 'matches_tag' in paper
            assert 'primary_category' in paper
            
    def test_multiple_tags_or_mode(self):
        """Test multiple tags with OR mode"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "tags": f"{TEST_TAG},cs.RO",
            "tag_mode": "or",
            "show_all": "false",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        # Should have papers from both categories
        papers = data['leaderboard']
        print(f"Papers matching either tag: {len(papers)}")
        assert len(papers) > 7, "OR mode should return more papers than single tag"
        
    def test_without_tag_params_uses_category(self):
        """Without tags param, should use category-based leaderboard"""
        res = requests.get(f"{BASE_URL}/api/leaderboard", params={
            "category": "cs.RO",
            "period": "all"
        })
        assert res.status_code == 200
        data = res.json()
        
        # Should NOT have tag-specific fields
        assert 'show_all' not in data or data.get('show_all') is None
        assert 'tags' in data
        assert data['tags'] is None  # No tags in category mode


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
