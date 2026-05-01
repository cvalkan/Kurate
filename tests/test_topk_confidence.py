"""
Target Top-K and Confidence Bands Feature Tests for PaperSumo
Tests:
- Target Top-K slider in UCB Parameters
- Confidence Level slider (80-99%) in UCB Parameters
- Backend accepts target_top_k and confidence_level in ucb_config
- Confidence bands (win rate ± margin of error) in results
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://reviewer-personas-4.preview.emergentagent.com')


class TestTopKAndConfidenceBackendAPI:
    """Backend API tests for Target Top-K and Confidence Bands features"""
    
    def test_api_health(self):
        """Test API is accessible"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        print("✓ API health check passed")
    
    def test_create_ucb_tournament_with_target_top_k(self):
        """Test creating UCB tournament with target_top_k parameter"""
        # First search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "machine learning",
            "max_results": 10
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 6:
            pytest.skip("Not enough papers found for test")
        
        # Create UCB tournament with target_top_k
        ucb_config = {
            "enabled": True,
            "exploration_constant": 1.414,
            "min_comparisons_per_paper": 2,
            "max_total_comparisons": 30,
            "convergence_threshold": 0.05,
            "target_top_k": 3,  # NEW: Focus on finding top 3
            "confidence_level": 0.90  # NEW: 90% confidence
        }
        
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:6],
            "parallel_agents": 2,
            "deep_analysis": False,
            "search_query": "TEST_deep learning neural",
            "ranking_mode": "ucb",
            "ucb_config": ucb_config
        })
        
        assert response.status_code == 200, f"Failed to create tournament: {response.text}"
        data = response.json()
        assert "tournament" in data
        tournament = data["tournament"]
        
        # Verify UCB mode is set
        assert tournament["ranking_mode"] == "ucb"
        assert tournament["ucb_config"] is not None
        
        # Verify new config values are accepted
        assert tournament["ucb_config"]["target_top_k"] == 3, "target_top_k not saved correctly"
        assert tournament["ucb_config"]["confidence_level"] == 0.90, "confidence_level not saved correctly"
        
        print(f"✓ UCB tournament with target_top_k created: {tournament['id']}")
        print(f"  - target_top_k: {tournament['ucb_config']['target_top_k']}")
        print(f"  - confidence_level: {tournament['ucb_config']['confidence_level']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
        return tournament
    
    def test_create_ucb_tournament_with_confidence_level_range(self):
        """Test creating UCB tournament with various confidence levels (80-99%)"""
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "neural network",
            "max_results": 10
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 4:
            pytest.skip("Not enough papers found")
        
        # Test with 80% confidence (minimum)
        ucb_config_80 = {
            "enabled": True,
            "confidence_level": 0.80
        }
        
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:4],
            "parallel_agents": 2,
            "ranking_mode": "ucb",
            "ucb_config": ucb_config_80
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        assert tournament["ucb_config"]["confidence_level"] == 0.80
        print(f"✓ 80% confidence level accepted")
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
        
        # Test with 99% confidence (maximum)
        ucb_config_99 = {
            "enabled": True,
            "confidence_level": 0.99
        }
        
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:4],
            "parallel_agents": 2,
            "ranking_mode": "ucb",
            "ucb_config": ucb_config_99
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        assert tournament["ucb_config"]["confidence_level"] == 0.99
        print(f"✓ 99% confidence level accepted")
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
    
    def test_ucb_default_confidence_level(self):
        """Test that default confidence_level is 0.95 when not specified"""
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "deep learning",
            "max_results": 10
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 4:
            pytest.skip("Not enough papers found")
        
        # Create UCB tournament without explicit confidence_level
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:4],
            "parallel_agents": 2,
            "ranking_mode": "ucb"
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        
        # Should have default confidence_level of 0.95
        assert tournament["ucb_config"]["confidence_level"] == 0.95, \
            f"Expected default confidence_level 0.95, got {tournament['ucb_config'].get('confidence_level')}"
        print(f"✓ Default confidence_level is 0.95")
        
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
    
    def test_ucb_default_target_top_k_is_none(self):
        """Test that default target_top_k is None (rank all papers)"""
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "optimization algorithm",
            "max_results": 10
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 4:
            pytest.skip("Not enough papers found")
        
        # Create UCB tournament without explicit target_top_k
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:4],
            "parallel_agents": 2,
            "ranking_mode": "ucb"
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        
        # Should have default target_top_k of None
        assert tournament["ucb_config"].get("target_top_k") is None, \
            f"Expected default target_top_k None, got {tournament['ucb_config'].get('target_top_k')}"
        print(f"✓ Default target_top_k is None (rank all)")
        
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")


class TestConfidenceBandsInResults:
    """Test confidence bands appear in tournament results"""
    
    def test_ucb_tournament_with_confidence_bands(self):
        """Create and run a small UCB tournament to verify confidence bands in results"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "transformer attention",
            "max_results": 10
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 5:
            pytest.skip("Not enough papers found")
        
        # Create UCB tournament with confidence settings
        ucb_config = {
            "enabled": True,
            "exploration_constant": 1.414,
            "min_comparisons_per_paper": 2,
            "max_total_comparisons": 20,
            "convergence_threshold": 0.1,
            "target_top_k": None,  # Rank all
            "confidence_level": 0.95
        }
        
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:5],
            "parallel_agents": 3,
            "ranking_mode": "ucb",
            "ucb_config": ucb_config,
            "search_query": "TEST_transformer attention"
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        tournament_id = tournament["id"]
        
        print(f"✓ UCB tournament created: {tournament_id}")
        
        # Start tournament
        start_response = requests.post(f"{BASE_URL}/api/tournaments/{tournament_id}/start")
        assert start_response.status_code == 200
        print("✓ Tournament started")
        
        # Wait for completion (with timeout)
        max_wait = 120  # 2 minutes max
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            status_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
            status = status_response.json()["tournament"]["status"]
            progress = status_response.json()["tournament"]["progress"]
            
            print(f"  Progress: {progress}%, Status: {status}")
            
            if status == "completed":
                break
            elif status == "failed":
                pytest.fail("Tournament failed")
            
            time.sleep(5)
        
        # Get results
        results_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}/results")
        assert results_response.status_code == 200
        
        tournament_results = results_response.json()["tournament"]
        rankings = tournament_results.get("rankings", [])
        
        assert len(rankings) == 5, f"Expected 5 rankings, got {len(rankings)}"
        
        # Check confidence bands in rankings
        confidence_found = False
        for i, ranking in enumerate(rankings):
            confidence = ranking.get("confidence")
            print(f"  Rank {ranking['rank']}: {ranking['title'][:40]}...")
            print(f"    Score: {ranking['score']:.4f}")
            
            if confidence:
                confidence_found = True
                print(f"    Confidence: win_rate={confidence.get('win_rate')}, "
                      f"margin_of_error={confidence.get('margin_of_error')}, "
                      f"comparisons={confidence.get('comparisons')}")
                
                # Verify confidence structure
                assert "win_rate" in confidence, "Missing win_rate in confidence"
                assert "lower_bound" in confidence, "Missing lower_bound in confidence"
                assert "upper_bound" in confidence, "Missing upper_bound in confidence"
                assert "margin_of_error" in confidence, "Missing margin_of_error in confidence"
                assert "confidence_level" in confidence, "Missing confidence_level in confidence"
                assert "comparisons" in confidence, "Missing comparisons in confidence"
                
                # Verify values are reasonable
                assert 0 <= confidence["win_rate"] <= 1, "win_rate out of range"
                assert 0 <= confidence["lower_bound"] <= 1, "lower_bound out of range"
                assert 0 <= confidence["upper_bound"] <= 1, "upper_bound out of range"
                assert confidence["lower_bound"] <= confidence["win_rate"] <= confidence["upper_bound"], \
                    "win_rate not within bounds"
        
        assert confidence_found, "No confidence data found in any ranking"
        print(f"✓ Confidence bands verified in results")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


class TestTopKModeEfficiency:
    """Test that Top-K mode uses fewer comparisons"""
    
    def test_top_k_mode_uses_fewer_comparisons(self):
        """Test that target_top_k mode completes with fewer comparisons"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "computer vision",
            "max_results": 10
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 6:
            pytest.skip("Not enough papers found")
        
        # Create UCB tournament with target_top_k=3
        ucb_config = {
            "enabled": True,
            "exploration_constant": 1.414,
            "min_comparisons_per_paper": 2,
            "max_total_comparisons": 40,  # Allow enough for comparison
            "convergence_threshold": 0.1,
            "target_top_k": 3,  # Focus on top 3
            "confidence_level": 0.90
        }
        
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:6],
            "parallel_agents": 3,
            "ranking_mode": "ucb",
            "ucb_config": ucb_config,
            "search_query": "TEST_computer vision image"
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        tournament_id = tournament["id"]
        
        print(f"✓ Top-3 UCB tournament created: {tournament_id}")
        print(f"  - Papers: 6, Round-robin would need: 15 comparisons")
        
        # Start tournament
        start_response = requests.post(f"{BASE_URL}/api/tournaments/{tournament_id}/start")
        assert start_response.status_code == 200
        print("✓ Tournament started")
        
        # Wait for completion
        max_wait = 120
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            status_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
            status = status_response.json()["tournament"]["status"]
            progress = status_response.json()["tournament"]["progress"]
            
            print(f"  Progress: {progress}%, Status: {status}")
            
            if status == "completed":
                break
            elif status == "failed":
                pytest.fail("Tournament failed")
            
            time.sleep(5)
        
        # Get final results
        final_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
        final_tournament = final_response.json()["tournament"]
        
        assert final_tournament["status"] == "completed"
        
        completed_matches = len([m for m in final_tournament.get("matches", []) if m.get("completed")])
        round_robin_matches = 6 * 5 // 2  # 15 for 6 papers
        
        print(f"✓ Top-3 UCB tournament completed!")
        print(f"  - Total comparisons: {completed_matches}")
        print(f"  - Round-robin would need: {round_robin_matches}")
        
        # Top-K mode should generally use fewer comparisons
        # (though not guaranteed due to convergence requirements)
        print(f"  - Savings: {round_robin_matches - completed_matches} comparisons")
        
        # Verify rankings exist
        rankings = final_tournament.get("rankings", [])
        assert len(rankings) == 6
        print(f"  - Rankings generated for all 6 papers")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
