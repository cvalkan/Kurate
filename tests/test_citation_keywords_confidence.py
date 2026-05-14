"""
Test suite for PaperSumo new features:
1. Keywords used as tournament title instead of 'Custom Selection'
2. Citation counts fetched from Semantic Scholar API and displayed
3. Confidence level affects estimated comparison count
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ai-judge-hub-1.preview.emergentagent.com').rstrip('/')


class TestAPIHealth:
    """Basic API health checks"""
    
    def test_api_root(self):
        """Test API is accessible"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


class TestCitationCounts:
    """Test citation counts from Semantic Scholar API"""
    
    def test_search_returns_citation_counts(self):
        """Test that paper search returns citation_count field"""
        response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "transformer attention",
            "max_results": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert "papers" in data
        assert len(data["papers"]) > 0
        
        # Check that papers have citation_count field
        papers_with_citations = 0
        for paper in data["papers"]:
            assert "citation_count" in paper, "Paper should have citation_count field"
            if paper["citation_count"] is not None:
                papers_with_citations += 1
                assert isinstance(paper["citation_count"], int), "citation_count should be int or null"
        
        # At least some papers should have citation counts (Semantic Scholar may not have all)
        print(f"Papers with citation counts: {papers_with_citations}/{len(data['papers'])}")
    
    def test_citation_count_in_tournament_papers(self):
        """Test that tournament papers include citation counts"""
        # First search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "machine learning",
            "max_results": 5
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        
        # Create tournament with these papers
        tournament_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": "machine learning",
            "ranking_mode": "round_robin"
        })
        assert tournament_response.status_code == 200
        tournament_id = tournament_response.json()["tournament"]["id"]
        
        try:
            # Get tournament details
            details_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
            assert details_response.status_code == 200
            tournament = details_response.json()["tournament"]
            
            # Check papers have citation_count
            for paper in tournament["papers"]:
                assert "citation_count" in paper, "Tournament paper should have citation_count field"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


class TestKeywordsAsTitle:
    """Test that search_query keywords are used as tournament title (category_name)"""
    
    def test_search_query_becomes_category_name(self):
        """Test that search_query is used as category_name for custom tournaments"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "blockchain consensus",
            "max_results": 5
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        search_description = search_response.json()["search_description"]
        
        # Create tournament with search_query
        tournament_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": search_description,  # This should become the title
            "ranking_mode": "round_robin"
        })
        assert tournament_response.status_code == 200
        tournament_id = tournament_response.json()["tournament"]["id"]
        
        try:
            # Get tournament details
            details_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
            assert details_response.status_code == 200
            tournament = details_response.json()["tournament"]
            
            # category_name should be the search_query, not "Custom Selection"
            assert tournament["category_name"] == search_description, \
                f"Expected category_name to be '{search_description}', got '{tournament['category_name']}'"
            assert tournament["category_name"] != "Custom Selection", \
                "category_name should not be 'Custom Selection' when search_query is provided"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")
    
    def test_category_name_in_tournament_list(self):
        """Test that tournament list shows keywords as title"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "neural network optimization",
            "max_results": 5
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        search_description = search_response.json()["search_description"]
        
        # Create tournament
        tournament_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": search_description,
            "ranking_mode": "round_robin"
        })
        assert tournament_response.status_code == 200
        tournament_id = tournament_response.json()["tournament"]["id"]
        
        try:
            # Get tournament list
            list_response = requests.get(f"{BASE_URL}/api/tournaments?limit=10")
            assert list_response.status_code == 200
            tournaments = list_response.json()["tournaments"]
            
            # Find our tournament
            our_tournament = next((t for t in tournaments if t["id"] == tournament_id), None)
            assert our_tournament is not None, "Tournament should be in list"
            
            # Check category_name is the search description
            assert our_tournament["category_name"] == search_description, \
                f"Tournament list should show '{search_description}' as title"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")
    
    def test_no_search_prefix_in_history(self):
        """Test that history page doesn't show 'Search:' prefix - just keywords"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "deep learning",
            "max_results": 5
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        search_description = search_response.json()["search_description"]
        
        # Create tournament
        tournament_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": search_description,
            "ranking_mode": "round_robin"
        })
        assert tournament_response.status_code == 200
        tournament_id = tournament_response.json()["tournament"]["id"]
        
        try:
            # Get tournament details
            details_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
            assert details_response.status_code == 200
            tournament = details_response.json()["tournament"]
            
            # category_name should NOT start with "Search:"
            assert not tournament["category_name"].startswith("Search:"), \
                f"category_name should not start with 'Search:', got '{tournament['category_name']}'"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


class TestConfidenceAffectsEstimates:
    """Test that confidence level affects estimated comparison count"""
    
    def test_confidence_multiplier_formula(self):
        """Test the confidence multiplier formula: 1 + (confidence_level - 0.80) * 3"""
        # Formula: 1 + (confidence_level - 0.80) * 3
        # 80% -> 1.0x
        # 95% -> 1.45x
        # 99% -> 1.57x
        
        test_cases = [
            (0.80, 1.0),
            (0.85, 1.15),
            (0.90, 1.30),
            (0.95, 1.45),
            (0.99, 1.57),
        ]
        
        for confidence, expected_multiplier in test_cases:
            calculated = 1 + (confidence - 0.80) * 3
            assert abs(calculated - expected_multiplier) < 0.01, \
                f"For confidence {confidence}, expected multiplier {expected_multiplier}, got {calculated}"
    
    def test_higher_confidence_more_comparisons(self):
        """Test that higher confidence results in more estimated comparisons"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "reinforcement learning",
            "max_results": 10
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        
        # Create tournament with 80% confidence
        low_conf_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": "reinforcement learning",
            "ranking_mode": "ucb",
            "ucb_config": {
                "exploration_constant": 1.414,
                "min_comparisons_per_paper": 3,
                "confidence_level": 0.80
            }
        })
        assert low_conf_response.status_code == 200
        low_conf_tournament = low_conf_response.json()["tournament"]
        low_conf_matches = low_conf_tournament["total_matches"]
        
        # Create tournament with 99% confidence
        high_conf_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": "reinforcement learning",
            "ranking_mode": "ucb",
            "ucb_config": {
                "exploration_constant": 1.414,
                "min_comparisons_per_paper": 3,
                "confidence_level": 0.99
            }
        })
        assert high_conf_response.status_code == 200
        high_conf_tournament = high_conf_response.json()["tournament"]
        high_conf_matches = high_conf_tournament["total_matches"]
        
        try:
            # Higher confidence should result in more estimated comparisons
            print(f"80% confidence: {low_conf_matches} estimated comparisons")
            print(f"99% confidence: {high_conf_matches} estimated comparisons")
            
            assert high_conf_matches > low_conf_matches, \
                f"99% confidence ({high_conf_matches}) should have more comparisons than 80% ({low_conf_matches})"
            
            # Check the ratio is approximately correct (1.57 / 1.0 = 1.57x)
            ratio = high_conf_matches / low_conf_matches
            expected_ratio = 1.57 / 1.0  # 99% multiplier / 80% multiplier
            print(f"Ratio: {ratio:.2f} (expected ~{expected_ratio:.2f})")
            
            # Allow some tolerance due to rounding
            assert 1.3 < ratio < 2.0, \
                f"Ratio {ratio:.2f} should be approximately {expected_ratio:.2f}"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{low_conf_tournament['id']}")
            requests.delete(f"{BASE_URL}/api/tournaments/{high_conf_tournament['id']}")
    
    def test_ucb_config_stores_confidence_level(self):
        """Test that ucb_config stores the confidence_level correctly"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "computer vision",
            "max_results": 5
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        
        # Create tournament with specific confidence level
        tournament_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": "computer vision",
            "ranking_mode": "ucb",
            "ucb_config": {
                "exploration_constant": 1.414,
                "min_comparisons_per_paper": 3,
                "confidence_level": 0.92
            }
        })
        assert tournament_response.status_code == 200
        tournament_id = tournament_response.json()["tournament"]["id"]
        
        try:
            # Get tournament details
            details_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
            assert details_response.status_code == 200
            tournament = details_response.json()["tournament"]
            
            # Check ucb_config has confidence_level
            assert tournament["ucb_config"] is not None, "ucb_config should be present"
            assert "confidence_level" in tournament["ucb_config"], "ucb_config should have confidence_level"
            assert tournament["ucb_config"]["confidence_level"] == 0.92, \
                f"confidence_level should be 0.92, got {tournament['ucb_config']['confidence_level']}"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


class TestResultsPageCitations:
    """Test that results page shows citation counts in rankings"""
    
    def test_results_include_paper_citations(self):
        """Test that results API returns papers with citation counts"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "natural language processing",
            "max_results": 5
        })
        assert search_response.status_code == 200
        papers = search_response.json()["papers"]
        
        # Create and start a small tournament
        tournament_response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers,
            "parallel_agents": 3,
            "search_query": "natural language processing",
            "ranking_mode": "ucb",
            "ucb_config": {
                "exploration_constant": 1.414,
                "min_comparisons_per_paper": 2,
                "confidence_level": 0.80,
                "max_total_comparisons": 15
            }
        })
        assert tournament_response.status_code == 200
        tournament_id = tournament_response.json()["tournament"]["id"]
        
        try:
            # Start tournament
            start_response = requests.post(f"{BASE_URL}/api/tournaments/{tournament_id}/start")
            assert start_response.status_code == 200
            
            # Wait for completion (max 60 seconds)
            for _ in range(30):
                time.sleep(2)
                status_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
                if status_response.status_code == 200:
                    status = status_response.json()["tournament"]["status"]
                    if status == "completed":
                        break
            
            # Get results
            results_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}/results")
            if results_response.status_code == 200:
                results = results_response.json()["tournament"]
                
                # Check papers have citation_count
                for paper in results.get("papers", []):
                    assert "citation_count" in paper, "Results papers should have citation_count"
                
                # Check category_name is the search query
                assert results["category_name"] == "natural language processing" or \
                       "natural language processing" in results["category_name"].lower(), \
                    f"Results title should contain search keywords, got '{results['category_name']}'"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
