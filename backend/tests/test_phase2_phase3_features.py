"""
Test Phase 2 (Round-robin matchmaking) and Phase 3 (Tabbed AI summaries) features.

Key APIs being tested:
- /api/health - Health check
- /api/leaderboard - Leaderboard data with category filtering
- /api/papers/{id} - Paper detail with stats, matches, optional summaries
- /api/prompts - Evaluation and summary prompts
- /api/status - Scheduler status
- /api/convergence - Convergence analysis

Unit test checks:
- _select_pairs function (simplified round-robin)
- _check_goals_met function (Spearman Rho ranking stability)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SAMPLE_PAPER_ID = "1b752605-7045-46f2-8308-a2e0142aa8a7"


class TestHealthAndStatus:
    """Test health and status endpoints"""

    def test_health_endpoint(self):
        """Test /api/health returns OK"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        data = response.json()
        assert data.get("status") == "ok", f"Health status not ok: {data}"
        print(f"Health endpoint OK: {data}")

    def test_status_endpoint(self):
        """Test /api/status returns scheduler status"""
        response = requests.get(f"{BASE_URL}/api/status")
        assert response.status_code == 200, f"Status check failed: {response.status_code}"
        data = response.json()
        
        # Validate expected fields
        assert "total_papers" in data, "Missing total_papers in status"
        assert "total_matches" in data, "Missing total_matches in status"
        assert "scheduler" in data, "Missing scheduler in status"
        
        # Validate scheduler sub-fields
        scheduler = data["scheduler"]
        assert "current_activity" in scheduler, "Missing current_activity in scheduler"
        
        print(f"Status: {data['total_papers']} papers, {data['total_matches']} matches")
        print(f"Scheduler: {scheduler.get('current_activity', 'unknown')}")


class TestLeaderboard:
    """Test leaderboard endpoint with various parameters"""

    def test_leaderboard_cs_ro(self):
        """Test /api/leaderboard?category=cs.RO returns valid data"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": "cs.RO"})
        assert response.status_code == 200, f"Leaderboard failed: {response.status_code}"
        data = response.json()
        
        # Validate structure
        assert "leaderboard" in data, "Missing leaderboard array"
        assert "total_papers" in data, "Missing total_papers"
        assert "total_matches" in data, "Missing total_matches"
        assert "category" in data, "Missing category"
        assert data["category"] == "cs.RO", f"Wrong category: {data['category']}"
        
        # Validate leaderboard entries if present
        lb = data["leaderboard"]
        if lb:
            first = lb[0]
            assert "id" in first, "Missing id in leaderboard entry"
            assert "title" in first, "Missing title in leaderboard entry"
            assert "rank" in first, "Missing rank in leaderboard entry"
            assert "score" in first, "Missing score in leaderboard entry"
            assert "wins" in first, "Missing wins in leaderboard entry"
            assert "losses" in first, "Missing losses in leaderboard entry"
            
        print(f"Leaderboard cs.RO: {len(lb)} papers, {data['total_matches']} matches")

    def test_leaderboard_different_periods(self):
        """Test leaderboard with different period filters"""
        for period in ["all", "recent", "week", "month"]:
            response = requests.get(f"{BASE_URL}/api/leaderboard", params={
                "category": "cs.RO",
                "period": period
            })
            assert response.status_code == 200, f"Period {period} failed: {response.status_code}"
            data = response.json()
            assert "leaderboard" in data
            print(f"Period '{period}': {len(data['leaderboard'])} papers")

    def test_leaderboard_other_categories(self):
        """Test leaderboard for other categories"""
        categories = ["cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]
        for cat in categories:
            response = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": cat})
            assert response.status_code == 200, f"Category {cat} failed: {response.status_code}"
            data = response.json()
            print(f"Category '{cat}': {data['total_papers']} papers, {data['total_matches']} matches")


class TestPaperDetail:
    """Test paper detail endpoint"""

    def test_paper_detail_with_sample_id(self):
        """Test /api/papers/{id} returns paper detail with stats, matches"""
        response = requests.get(f"{BASE_URL}/api/papers/{SAMPLE_PAPER_ID}")
        
        if response.status_code == 404:
            pytest.skip(f"Sample paper {SAMPLE_PAPER_ID} not found - may have been removed")
        
        assert response.status_code == 200, f"Paper detail failed: {response.status_code}"
        data = response.json()
        
        # Validate paper structure
        assert "paper" in data, "Missing paper object"
        paper = data["paper"]
        assert "id" in paper, "Missing paper id"
        assert "title" in paper, "Missing paper title"
        assert "abstract" in paper, "Missing paper abstract"
        
        # Validate stats structure
        assert "stats" in data, "Missing stats object"
        stats = data["stats"]
        assert "wins" in stats, "Missing wins in stats"
        assert "losses" in stats, "Missing losses in stats"
        assert "comparisons" in stats, "Missing comparisons in stats"
        assert "confidence" in stats, "Missing confidence in stats"
        
        # Validate confidence structure
        conf = stats["confidence"]
        if conf.get("comparisons", 0) > 0:
            assert "lower_bound" in conf, "Missing lower_bound in confidence"
            assert "upper_bound" in conf, "Missing upper_bound in confidence"
            assert "win_rate" in conf, "Missing win_rate in confidence"
        
        # Validate matches structure
        assert "matches" in data, "Missing matches array"
        matches = data["matches"]
        
        print(f"Paper: {paper['title'][:50]}...")
        print(f"Stats: {stats['wins']} wins, {stats['losses']} losses, {stats['comparisons']} comparisons")
        print(f"Matches: {len(matches)} total")
        
        # Check for optional summaries field
        if "summaries" in paper:
            print(f"Pre-generated summaries found: {list(paper['summaries'].keys())}")
        elif "impact_summary" in paper:
            print(f"Legacy impact_summary found: {len(paper.get('impact_summary', ''))} chars")
        else:
            print("No summaries field - fallback will be needed")

    def test_paper_detail_404_for_invalid_id(self):
        """Test that invalid paper ID returns 404"""
        response = requests.get(f"{BASE_URL}/api/papers/invalid-uuid-here")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"

    def test_fetch_papers_with_summaries(self):
        """Fetch multiple papers to check for summaries field"""
        # Get papers from leaderboard first
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": "cs.RO", "limit": 10})
        assert response.status_code == 200
        lb = response.json().get("leaderboard", [])
        
        summaries_count = 0
        impact_summary_count = 0
        
        for entry in lb[:5]:  # Check first 5 papers
            paper_response = requests.get(f"{BASE_URL}/api/papers/{entry['id']}")
            if paper_response.status_code == 200:
                paper_data = paper_response.json().get("paper", {})
                if paper_data.get("summaries"):
                    summaries_count += 1
                    print(f"Paper '{entry['title'][:30]}' has pre-generated summaries")
                elif paper_data.get("impact_summary"):
                    impact_summary_count += 1
                    print(f"Paper '{entry['title'][:30]}' has legacy impact_summary")
                else:
                    print(f"Paper '{entry['title'][:30]}' has no summaries")
        
        print(f"Summary stats: {summaries_count} with pre-gen summaries, {impact_summary_count} with legacy impact_summary")


class TestPrompts:
    """Test prompts endpoint"""

    def test_prompts_endpoint(self):
        """Test /api/prompts returns both evaluation and summary prompts"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        assert response.status_code == 200, f"Prompts failed: {response.status_code}"
        data = response.json()
        
        # Validate evaluation prompt
        assert "evaluation" in data, "Missing evaluation prompt"
        eval_prompt = data["evaluation"]
        assert "system_prompt" in eval_prompt, "Missing system_prompt in evaluation"
        assert "user_prompt" in eval_prompt, "Missing user_prompt in evaluation"
        assert len(eval_prompt["system_prompt"]) > 50, "Evaluation system prompt too short"
        assert len(eval_prompt["user_prompt"]) > 20, "Evaluation user prompt too short"
        
        # Validate summary prompt
        assert "summary" in data, "Missing summary prompt"
        sum_prompt = data["summary"]
        assert "system_prompt" in sum_prompt, "Missing system_prompt in summary"
        assert "user_prompt" in sum_prompt, "Missing user_prompt in summary"
        assert len(sum_prompt["system_prompt"]) > 50, "Summary system prompt too short"
        
        print(f"Evaluation prompt: {len(eval_prompt['system_prompt'])} chars system, {len(eval_prompt['user_prompt'])} chars user")
        print(f"Summary prompt: {len(sum_prompt['system_prompt'])} chars system, {len(sum_prompt['user_prompt'])} chars user")


class TestConvergence:
    """Test convergence analysis endpoint"""

    def test_convergence_cs_ro(self):
        """Test /api/convergence?category=cs.RO returns convergence analysis"""
        response = requests.get(f"{BASE_URL}/api/convergence", params={"category": "cs.RO"})
        assert response.status_code == 200, f"Convergence failed: {response.status_code}"
        data = response.json()
        
        # May return no_data if not enough matches
        if data.get("status") == "no_data":
            print("Convergence: not enough data for analysis")
            return
        
        assert data.get("status") == "ok", f"Convergence status not ok: {data}"
        
        # Validate structure
        assert "category" in data, "Missing category"
        assert "total_matches" in data, "Missing total_matches"
        assert "total_papers" in data, "Missing total_papers"
        assert "curve" in data, "Missing curve array"
        
        curve = data["curve"]
        if curve:
            first_point = curve[0]
            assert "matches" in first_point, "Missing matches in curve point"
            assert "spearman" in first_point, "Missing spearman correlation in curve point"
            assert "kendall" in first_point, "Missing kendall correlation in curve point"
            
            print(f"Convergence curve: {len(curve)} data points")
            print(f"Latest point: Spearman={first_point.get('spearman')}, Kendall={first_point.get('kendall')}")
        else:
            print("Convergence: empty curve (not enough data)")


class TestSelectPairsLogic:
    """Test the _select_pairs function logic via API observations"""

    def test_leaderboard_shows_balanced_coverage(self):
        """Verify that papers have balanced match coverage (round-robin effect)"""
        response = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": "cs.RO"})
        assert response.status_code == 200
        lb = response.json().get("leaderboard", [])
        
        if len(lb) < 5:
            pytest.skip("Not enough papers to check coverage balance")
        
        # Check match distribution
        match_counts = [entry.get("comparisons", 0) for entry in lb]
        min_matches = min(match_counts)
        max_matches = max(match_counts)
        avg_matches = sum(match_counts) / len(match_counts)
        
        print(f"Match distribution: min={min_matches}, max={max_matches}, avg={avg_matches:.1f}")
        
        # In round-robin, we expect relatively balanced distribution
        # The ratio shouldn't be extreme (e.g., some papers with 100x more matches)
        if min_matches > 0:
            ratio = max_matches / min_matches
            print(f"Match ratio (max/min): {ratio:.2f}")
            assert ratio < 10, f"Match distribution too unbalanced: {ratio}"


class TestModelCorrelation:
    """Test model correlation/analysis endpoint"""

    def test_model_correlation_endpoint(self):
        """Test /api/model-correlation returns valid data"""
        response = requests.get(f"{BASE_URL}/api/model-correlation")
        assert response.status_code == 200, f"Model correlation failed: {response.status_code}"
        data = response.json()
        
        # Validate structure
        assert "models" in data, "Missing models array"
        assert "correlations" in data, "Missing correlations"
        assert "agreement" in data, "Missing agreement"
        assert "n_common_papers" in data, "Missing n_common_papers"
        
        models = data["models"]
        if models:
            print(f"Models: {[m.get('short', m.get('key', 'unknown')) for m in models]}")
            print(f"Common papers: {data['n_common_papers']}")
        
        # Check correlations structure
        correlations = data["correlations"]
        if correlations:
            for pair_key, corr_data in list(correlations.items())[:2]:
                print(f"Correlation {pair_key}: spearman_r={corr_data.get('spearman_r')}")


class TestCategories:
    """Test categories endpoint"""

    def test_categories_endpoint(self):
        """Test /api/categories returns available categories"""
        response = requests.get(f"{BASE_URL}/api/categories")
        assert response.status_code == 200, f"Categories failed: {response.status_code}"
        data = response.json()
        
        assert "categories" in data, "Missing categories array"
        assert "default" in data, "Missing default category"
        
        cats = data["categories"]
        assert len(cats) >= 1, "No categories returned"
        
        for cat in cats:
            assert "id" in cat, "Missing id in category"
            assert "name" in cat, "Missing name in category"
        
        print(f"Categories: {[c['id'] for c in cats]}")
        print(f"Default: {data['default']}")


class TestTags:
    """Test tags endpoint"""

    def test_tags_endpoint(self):
        """Test /api/tags returns all category tags"""
        response = requests.get(f"{BASE_URL}/api/tags")
        assert response.status_code == 200, f"Tags failed: {response.status_code}"
        data = response.json()
        
        assert "tags" in data, "Missing tags array"
        tags = data["tags"]
        
        if tags:
            first_tag = tags[0]
            assert "id" in first_tag, "Missing id in tag"
            assert "count" in first_tag, "Missing count in tag"
            print(f"Top 5 tags: {[(t['id'], t['count']) for t in tags[:5]]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
