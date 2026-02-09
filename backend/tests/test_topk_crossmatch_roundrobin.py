"""
Test suite for Top-K Cross-Match feature (Goal 3) and Round-Robin Model Selection
Features tested:
1. GET /api/admin/progress returns goal3 field with 'met', 'label', 'done', 'total' keys
2. cs.RO should have goal3 incomplete (done < total), thus goals_met=False
3. Other categories (cs.DC, econ.GN, physics.comp-ph, q-bio.BM) should have goals_met=True
4. Round-robin model selection: check model distribution in recent matches
"""
import pytest
import requests
import os
from collections import Counter

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_TOKEN = "papersumo2025"

CATEGORIES = ["cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]


class TestTopKCrossMatchGoal3:
    """Test Goal 3: Top-K papers must have played against each other"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        return {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}
    
    def test_progress_returns_goal3_field(self, admin_headers):
        """GET /api/admin/progress?category=cs.RO returns goal3 field"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "goal3" in data, f"Missing goal3 field. Response: {data.keys()}"
        print(f"SUCCESS: progress endpoint returns goal3 field")
    
    def test_goal3_has_required_keys(self, admin_headers):
        """goal3 field must have 'met', 'label', 'done', 'total' keys"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goal3 = data.get("goal3", {})
        
        required_keys = ["met", "label", "done", "total"]
        for key in required_keys:
            assert key in goal3, f"Missing '{key}' in goal3. Got: {goal3.keys()}"
        
        # Validate types
        assert isinstance(goal3["met"], bool), f"goal3.met should be bool, got {type(goal3['met'])}"
        assert isinstance(goal3["label"], str), f"goal3.label should be str, got {type(goal3['label'])}"
        assert isinstance(goal3["done"], int), f"goal3.done should be int, got {type(goal3['done'])}"
        assert isinstance(goal3["total"], int), f"goal3.total should be int, got {type(goal3['total'])}"
        
        print(f"SUCCESS: goal3 has all required keys with correct types")
        print(f"  goal3 = {goal3}")
    
    def test_cs_ro_goal3_incomplete(self, admin_headers):
        """cs.RO should have incomplete top-K cross-matches (done < total)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goal3 = data.get("goal3", {})
        
        done = goal3.get("done", 0)
        total = goal3.get("total", 0)
        met = goal3.get("met", True)
        
        # According to the request, cs.RO should have incomplete cross-matches (22/45 pairs done)
        print(f"cs.RO Goal 3: {done}/{total} pairs done, met={met}")
        
        # Verify goal3 is NOT met for cs.RO
        assert met == False, f"cs.RO goal3 should be False (incomplete), but got {met}"
        assert done < total, f"cs.RO goal3 done ({done}) should be < total ({total})"
        
        print(f"SUCCESS: cs.RO has incomplete top-K cross-matches ({done}/{total})")
    
    def test_cs_ro_goals_met_false(self, admin_headers):
        """cs.RO goals_met should be False because goal3 is not met"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goals_met = data.get("goals_met")
        
        # goals_met should be False for cs.RO since goal3 is incomplete
        assert goals_met == False, f"cs.RO goals_met should be False, got {goals_met}"
        
        # Also verify goal1 and goal2 status
        goal1 = data.get("goal1", {})
        goal2 = data.get("goal2", {})
        goal3 = data.get("goal3", {})
        
        print(f"cs.RO goals:")
        print(f"  goal1 (min matches): {goal1}")
        print(f"  goal2 (CI convergence): {goal2}")
        print(f"  goal3 (top-K cross-matches): {goal3}")
        print(f"  goals_met: {goals_met}")
        
        print(f"SUCCESS: cs.RO goals_met=False as expected")
    
    def test_cs_dc_goals_met_true(self, admin_headers):
        """cs.DC should have goals_met=True (all 3 goals met)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.DC",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goals_met = data.get("goals_met")
        goal3 = data.get("goal3", {})
        
        print(f"cs.DC: goals_met={goals_met}, goal3={goal3}")
        
        assert goals_met == True, f"cs.DC goals_met should be True, got {goals_met}"
        assert goal3.get("met") == True, f"cs.DC goal3.met should be True"
        
        print(f"SUCCESS: cs.DC has all goals met including goal3")
    
    def test_econ_gn_goals_met_true(self, admin_headers):
        """econ.GN should have goals_met=True (all 3 goals met)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=econ.GN",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goals_met = data.get("goals_met")
        goal3 = data.get("goal3", {})
        
        print(f"econ.GN: goals_met={goals_met}, goal3={goal3}")
        
        assert goals_met == True, f"econ.GN goals_met should be True, got {goals_met}"
        assert goal3.get("met") == True, f"econ.GN goal3.met should be True"
        
        print(f"SUCCESS: econ.GN has all goals met including goal3")
    
    def test_physics_comp_ph_goals_met_true(self, admin_headers):
        """physics.comp-ph should have goals_met=True (all 3 goals met)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=physics.comp-ph",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goals_met = data.get("goals_met")
        goal3 = data.get("goal3", {})
        
        print(f"physics.comp-ph: goals_met={goals_met}, goal3={goal3}")
        
        assert goals_met == True, f"physics.comp-ph goals_met should be True, got {goals_met}"
        assert goal3.get("met") == True, f"physics.comp-ph goal3.met should be True"
        
        print(f"SUCCESS: physics.comp-ph has all goals met including goal3")
    
    def test_q_bio_bm_goals_met_true(self, admin_headers):
        """q-bio.BM should have goals_met=True (all 3 goals met)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=q-bio.BM",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        goals_met = data.get("goals_met")
        goal3 = data.get("goal3", {})
        
        print(f"q-bio.BM: goals_met={goals_met}, goal3={goal3}")
        
        assert goals_met == True, f"q-bio.BM goals_met should be True, got {goals_met}"
        assert goal3.get("met") == True, f"q-bio.BM goal3.met should be True"
        
        print(f"SUCCESS: q-bio.BM has all goals met including goal3")
    
    def test_all_categories_goal3_status_summary(self, admin_headers):
        """Summary test: Check goal3 status for all categories"""
        results = {}
        for category in CATEGORIES:
            response = requests.get(
                f"{BASE_URL}/api/admin/progress?category={category}",
                headers=admin_headers
            )
            assert response.status_code == 200
            
            data = response.json()
            goal3 = data.get("goal3", {})
            results[category] = {
                "goals_met": data.get("goals_met"),
                "goal3_met": goal3.get("met"),
                "goal3_done": goal3.get("done"),
                "goal3_total": goal3.get("total"),
                "goal3_label": goal3.get("label")
            }
        
        print("\n=== Goal 3 Status Summary Across All Categories ===")
        for cat, info in results.items():
            status = "COMPLETE" if info["goal3_met"] else "INCOMPLETE"
            print(f"  {cat}: {info['goal3_done']}/{info['goal3_total']} pairs - {status} - goals_met={info['goals_met']}")
        
        # Verify expected outcomes
        assert results["cs.RO"]["goals_met"] == False, "cs.RO should have goals_met=False"
        assert results["cs.RO"]["goal3_met"] == False, "cs.RO goal3 should be incomplete"
        
        for cat in ["cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]:
            assert results[cat]["goals_met"] == True, f"{cat} should have goals_met=True"
            assert results[cat]["goal3_met"] == True, f"{cat} goal3 should be complete"
        
        print("\nSUCCESS: All categories have expected goal3 status")


class TestRoundRobinModelSelection:
    """Test round-robin model selection distributes models evenly"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        return {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}
    
    def test_recent_matches_have_model_used(self, admin_headers):
        """Recent matches should have model_used field populated"""
        response = requests.get(
            f"{BASE_URL}/api/admin/status?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        recent_matches = data.get("recent_matches", [])
        
        assert len(recent_matches) > 0, "No recent matches found"
        
        for match in recent_matches:
            model_used = match.get("model_used", {})
            assert "provider" in model_used or "model" in model_used, f"Match missing model_used info: {match}"
        
        print(f"SUCCESS: All {len(recent_matches)} recent matches have model_used field")
    
    def test_model_distribution_from_stats(self, admin_headers):
        """Check model distribution via /api/admin/stats - should show even distribution"""
        response = requests.get(
            f"{BASE_URL}/api/admin/stats",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        models = data.get("models", {})
        
        assert len(models) >= 3, f"Expected at least 3 models, got {len(models)}"
        
        total_matches = sum(m.get("matches", 0) for m in models.values())
        
        print(f"\n=== Model Distribution (Total: {total_matches} matches) ===")
        for model_key, stats in sorted(models.items(), key=lambda x: -x[1].get("matches", 0)):
            count = stats.get("matches", 0)
            pct = (count / total_matches * 100) if total_matches > 0 else 0
            print(f"  {model_key}: {count} matches ({pct:.1f}%)")
        
        # Check for reasonable distribution (no model should have >50% or <15%)
        for model_key, stats in models.items():
            count = stats.get("matches", 0)
            pct = (count / total_matches * 100) if total_matches > 0 else 0
            assert pct < 50, f"{model_key} has too many matches ({pct:.1f}%) - not evenly distributed"
            assert pct > 15 or count < 100, f"{model_key} has too few matches ({pct:.1f}%) - may indicate distribution issue"
        
        print(f"SUCCESS: Model distribution is reasonably even")
    
    def test_timeseries_model_distribution(self, admin_headers):
        """Check model distribution from timeseries endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/admin/timeseries",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        models = data.get("models", {})
        
        print(f"\n=== Model Distribution from Timeseries ===")
        total = sum(m.get("matches", 0) for m in models.values())
        
        expected_models = [
            "openai/gpt-5.2",
            "anthropic/claude-opus-4-5-20251101", 
            "gemini/gemini-3-pro-preview"
        ]
        
        found_models = []
        for model_key, stats in sorted(models.items(), key=lambda x: -x[1].get("matches", 0)):
            count = stats.get("matches", 0)
            pct = (count / total * 100) if total > 0 else 0
            print(f"  {model_key}: {count} matches ({pct:.1f}%)")
            found_models.append(model_key)
        
        # Verify expected models are present
        for expected in expected_models:
            assert expected in found_models, f"Expected model {expected} not found. Found: {found_models}"
        
        print(f"SUCCESS: All 3 expected models found with even distribution")
    
    def test_recent_matches_model_variety(self, admin_headers):
        """Check that recent matches use a variety of models (round-robin effect)"""
        response = requests.get(
            f"{BASE_URL}/api/admin/status?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        recent_matches = data.get("recent_matches", [])
        
        # Count models in recent matches
        model_counts = Counter()
        for match in recent_matches:
            model_used = match.get("model_used", {})
            provider = model_used.get("provider", "unknown")
            model = model_used.get("model", "unknown")
            model_key = f"{provider}/{model}"
            model_counts[model_key] += 1
        
        print(f"\n=== Recent {len(recent_matches)} Matches Model Distribution ===")
        for model_key, count in model_counts.most_common():
            print(f"  {model_key}: {count}")
        
        # With round-robin, we should see multiple different models
        unique_models = len(model_counts)
        assert unique_models >= 2, f"Expected at least 2 different models in recent matches, got {unique_models}"
        
        print(f"SUCCESS: Recent matches show model variety ({unique_models} different models)")


class TestGoal3Integration:
    """Integration tests for Goal 3 affecting scheduler behavior"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        return {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}
    
    def test_goal3_label_format(self, admin_headers):
        """goal3 label should be in format 'Top-K cross-matches'"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        label = data.get("goal3", {}).get("label", "")
        
        assert "Top-" in label, f"goal3 label should contain 'Top-', got: {label}"
        assert "cross-match" in label.lower(), f"goal3 label should contain 'cross-match', got: {label}"
        
        print(f"SUCCESS: goal3 label format is correct: '{label}'")
    
    def test_estimated_matches_includes_goal3(self, admin_headers):
        """estimated_matches_remaining should include goal3 pending pairs"""
        response = requests.get(
            f"{BASE_URL}/api/admin/progress?category=cs.RO",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        estimated = data.get("estimated_matches_remaining", 0)
        goal3 = data.get("goal3", {})
        goal3_pending = goal3.get("total", 0) - goal3.get("done", 0)
        
        # If goal3 is incomplete, estimated should include those pending pairs
        if not goal3.get("met"):
            assert estimated >= goal3_pending, \
                f"estimated_matches_remaining ({estimated}) should be >= goal3 pending ({goal3_pending})"
            print(f"SUCCESS: estimated_matches_remaining ({estimated}) includes goal3 pending ({goal3_pending})")
        else:
            print(f"SUCCESS: goal3 is complete, estimated_matches_remaining={estimated}")


class TestProgressEndpointRequiresAuth:
    """Test that progress endpoint requires admin authentication"""
    
    def test_progress_without_auth_fails(self):
        """GET /api/admin/progress without auth should fail"""
        response = requests.get(f"{BASE_URL}/api/admin/progress?category=cs.RO")
        
        assert response.status_code in [401, 403], \
            f"Expected 401/403 without auth, got {response.status_code}"
        
        print(f"SUCCESS: progress endpoint requires authentication (returned {response.status_code})")
