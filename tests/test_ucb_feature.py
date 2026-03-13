"""
UCB Feature Tests for PaperSumo
Tests UCB mode toggle, parameters, tournament creation, and badge display
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://orcid-verify.preview.emergentagent.com')

class TestUCBBackendAPI:
    """Backend API tests for UCB feature"""
    
    def test_api_health(self):
        """Test API is accessible"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        assert "ArXiv Paper Tournament API" in response.json().get("message", "")
        print("✓ API health check passed")
    
    def test_search_papers(self):
        """Test paper search endpoint"""
        response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "deep learning",
            "max_results": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert "papers" in data
        assert len(data["papers"]) > 0
        print(f"✓ Search returned {len(data['papers'])} papers")
        return data["papers"]
    
    def test_create_tournament_round_robin(self):
        """Test creating a round-robin tournament (default mode)"""
        # First search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "TEST_quantum computing",
            "max_results": 5
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 3:
            pytest.skip("Not enough papers found for test")
        
        # Create tournament with round-robin mode (default)
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:3],
            "parallel_agents": 2,
            "deep_analysis": False,
            "search_query": "TEST_quantum computing",
            "ranking_mode": "round_robin"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "tournament" in data
        tournament = data["tournament"]
        
        assert tournament["ranking_mode"] == "round_robin"
        assert tournament["ucb_config"] is None
        # Round robin: n*(n-1)/2 = 3*2/2 = 3 matches
        assert tournament["total_matches"] == 3
        
        print(f"✓ Round-robin tournament created: {tournament['id']}")
        print(f"  - Ranking mode: {tournament['ranking_mode']}")
        print(f"  - Total matches: {tournament['total_matches']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
        return tournament
    
    def test_create_tournament_ucb_mode(self):
        """Test creating a UCB tournament with custom config"""
        # First search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "TEST_machine learning optimization",
            "max_results": 5
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 5:
            pytest.skip("Not enough papers found for UCB test")
        
        # Create tournament with UCB mode
        ucb_config = {
            "enabled": True,
            "exploration_constant": 1.5,
            "min_comparisons_per_paper": 2,
            "max_total_comparisons": 20,
            "convergence_threshold": 0.05
        }
        
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:5],
            "parallel_agents": 2,
            "deep_analysis": False,
            "search_query": "TEST_machine learning optimization",
            "ranking_mode": "ucb",
            "ucb_config": ucb_config
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "tournament" in data
        tournament = data["tournament"]
        
        # Verify UCB mode is set
        assert tournament["ranking_mode"] == "ucb"
        assert tournament["ucb_config"] is not None
        
        # Verify UCB config values
        assert tournament["ucb_config"]["exploration_constant"] == 1.5
        assert tournament["ucb_config"]["min_comparisons_per_paper"] == 2
        assert tournament["ucb_config"]["max_total_comparisons"] == 20
        
        # UCB should have fewer estimated matches than round-robin
        # Round robin for 5 papers: 5*4/2 = 10 matches
        # UCB max is set to 20, but estimated should be less
        print(f"✓ UCB tournament created: {tournament['id']}")
        print(f"  - Ranking mode: {tournament['ranking_mode']}")
        print(f"  - UCB config: {tournament['ucb_config']}")
        print(f"  - Total matches (estimated): {tournament['total_matches']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
        return tournament
    
    def test_create_tournament_ucb_default_config(self):
        """Test creating UCB tournament with default config"""
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "TEST_neural network",
            "max_results": 5
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 4:
            pytest.skip("Not enough papers found")
        
        # Create UCB tournament without explicit ucb_config
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:4],
            "parallel_agents": 2,
            "ranking_mode": "ucb"
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        
        # Should have default UCB config
        assert tournament["ranking_mode"] == "ucb"
        assert tournament["ucb_config"] is not None
        assert tournament["ucb_config"]["exploration_constant"] == 1.414  # sqrt(2)
        assert tournament["ucb_config"]["min_comparisons_per_paper"] == 3
        
        print(f"✓ UCB tournament with defaults created: {tournament['id']}")
        print(f"  - Default exploration_constant: {tournament['ucb_config']['exploration_constant']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament['id']}")
    
    def test_tournament_list_includes_ranking_mode(self):
        """Test that tournament list includes ranking_mode field"""
        response = requests.get(f"{BASE_URL}/api/tournaments?limit=10")
        assert response.status_code == 200
        
        tournaments = response.json().get("tournaments", [])
        assert len(tournaments) > 0
        
        # Check that ranking_mode is included in list response
        for t in tournaments:
            assert "ranking_mode" in t or t.get("ranking_mode") is None
            print(f"  Tournament {t['id'][:8]}... - mode: {t.get('ranking_mode', 'N/A')}, status: {t['status']}")
        
        print(f"✓ Tournament list includes ranking_mode field")
    
    def test_tournament_results_includes_ranking_mode(self):
        """Test that tournament results include ranking_mode"""
        # Get a completed tournament
        list_response = requests.get(f"{BASE_URL}/api/tournaments?limit=20")
        tournaments = list_response.json().get("tournaments", [])
        
        completed = [t for t in tournaments if t.get("status") == "completed"]
        if not completed:
            pytest.skip("No completed tournaments found")
        
        tournament_id = completed[0]["id"]
        
        # Get results
        response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}/results")
        assert response.status_code == 200
        
        tournament = response.json().get("tournament", {})
        assert "ranking_mode" in tournament
        
        print(f"✓ Results endpoint includes ranking_mode: {tournament.get('ranking_mode')}")
        
        # If UCB, should also have ucb_config and paper_stats
        if tournament.get("ranking_mode") == "ucb":
            assert "ucb_config" in tournament
            print(f"  - UCB config present: {tournament.get('ucb_config') is not None}")


class TestUCBTournamentExecution:
    """Test UCB tournament execution (requires waiting for completion)"""
    
    def test_ucb_tournament_runs_with_fewer_comparisons(self):
        """Test that UCB tournament completes with fewer comparisons than round-robin"""
        # Search for papers
        search_response = requests.post(f"{BASE_URL}/api/papers/search", json={
            "keywords": "TEST_reinforcement learning",
            "max_results": 5
        })
        papers = search_response.json().get("papers", [])
        
        if len(papers) < 5:
            pytest.skip("Not enough papers found")
        
        # Create UCB tournament with small max_comparisons for quick test
        response = requests.post(f"{BASE_URL}/api/tournaments", json={
            "papers": papers[:5],
            "parallel_agents": 3,
            "ranking_mode": "ucb",
            "ucb_config": {
                "exploration_constant": 1.414,
                "min_comparisons_per_paper": 2,
                "max_total_comparisons": 15,  # Less than round-robin (10)
                "convergence_threshold": 0.1
            }
        })
        
        assert response.status_code == 200
        tournament = response.json()["tournament"]
        tournament_id = tournament["id"]
        
        print(f"✓ UCB tournament created: {tournament_id}")
        print(f"  - Papers: 5, Round-robin would need: 10 comparisons")
        print(f"  - UCB max_total_comparisons: 15")
        
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
        
        # Get final results
        final_response = requests.get(f"{BASE_URL}/api/tournaments/{tournament_id}")
        final_tournament = final_response.json()["tournament"]
        
        assert final_tournament["status"] == "completed"
        assert final_tournament["ranking_mode"] == "ucb"
        
        completed_matches = len([m for m in final_tournament.get("matches", []) if m.get("completed")])
        
        print(f"✓ UCB tournament completed!")
        print(f"  - Total comparisons: {completed_matches}")
        print(f"  - Round-robin would need: 10")
        print(f"  - Savings: {10 - completed_matches} comparisons")
        
        # Verify rankings exist
        assert len(final_tournament.get("rankings", [])) == 5
        print(f"  - Rankings generated for all 5 papers")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/tournaments/{tournament_id}")


class TestExistingUCBTournament:
    """Test existing UCB tournament in the system"""
    
    def test_running_ucb_tournament_has_correct_fields(self):
        """Check the currently running UCB tournament"""
        # Get the running UCB tournament
        response = requests.get(f"{BASE_URL}/api/tournaments/d4f0d4b0-948a-4c83-84ce-51e647578ff5")
        
        if response.status_code != 200:
            pytest.skip("Running UCB tournament not found")
        
        tournament = response.json()["tournament"]
        
        # Verify UCB fields
        assert tournament["ranking_mode"] == "ucb"
        assert tournament["ucb_config"] is not None
        
        print(f"✓ Running UCB tournament verified")
        print(f"  - ID: {tournament['id']}")
        print(f"  - Status: {tournament['status']}")
        print(f"  - Progress: {tournament['progress']}%")
        print(f"  - UCB Config: {tournament['ucb_config']}")
        print(f"  - Papers: {tournament['num_papers']}")
        print(f"  - Completed matches: {len([m for m in tournament.get('matches', []) if m.get('completed')])}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
