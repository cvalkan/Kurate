"""
Test Phase 4: Convergence-based architecture + Summary Backfill
- Temporal ranking convergence (Spearman ρ) for Goal 2
- Backfill summaries endpoint
- Summary stats endpoint with pregen_coverage_rate
- Admin settings for convergence_threshold, convergence_rounds
- Paper detail with tabbed summaries
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_PASSWORD = "papersumo2025"
SAMPLE_PAPER_ID = "1b752605-7045-46f2-8308-a2e0142aa8a7"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin token for authenticated requests."""
    resp = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD})
    if resp.status_code != 200:
        pytest.skip("Admin login failed")
    return resp.json().get("token")


@pytest.fixture
def admin_headers(admin_token):
    """Headers with admin authentication."""
    return {"X-Admin-Token": admin_token}


class TestHealthAndBasics:
    """Basic health check tests."""
    
    def test_health_endpoint(self):
        """GET /api/health returns 200."""
        resp = requests.get(f"{BASE_URL}/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        print("✓ Health endpoint working")


class TestAdminProgressConvergence:
    """Test Goal 2 uses Spearman ρ ranking stability."""
    
    def test_progress_returns_convergence_goal2(self, admin_headers):
        """GET /api/admin/progress?category=cs.RO returns convergence-based Goal 2."""
        resp = requests.get(f"{BASE_URL}/api/admin/progress", 
                          params={"category": "cs.RO"},
                          headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # Check Goal 2 structure
        assert "goal2" in data, "goal2 field missing from progress response"
        goal2 = data["goal2"]
        
        # Verify label contains "ρ" (ranking stability)
        assert "ρ" in goal2.get("label", "") or "Ranking stability" in goal2.get("label", ""), \
            f"Goal 2 label should mention ranking stability, got: {goal2.get('label')}"
        
        # Verify new fields exist
        assert "done" in goal2, "goal2.done field missing"
        assert "total" in goal2, "goal2.total field missing"
        assert "snapshots" in goal2, "goal2.snapshots field missing (ranking snapshot count)"
        
        # latest_rho may be null if not enough snapshots
        assert "latest_rho" in goal2, "goal2.latest_rho field missing"
        
        print(f"✓ Goal 2 is convergence-based: {goal2['label']}")
        print(f"  - Done: {goal2['done']}/{goal2['total']}")
        print(f"  - Latest ρ: {goal2['latest_rho']}")
        print(f"  - Snapshots: {goal2['snapshots']}")
    
    def test_progress_goal2_no_ci_reference(self, admin_headers):
        """Verify Goal 2 no longer references CI (confidence interval)."""
        resp = requests.get(f"{BASE_URL}/api/admin/progress",
                          params={"category": "cs.RO"},
                          headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        goal2 = data.get("goal2", {})
        label = goal2.get("label", "")
        
        # Should NOT contain CI-related text
        assert "CI" not in label, f"Goal 2 should not mention CI, got: {label}"
        assert "%" not in label or "ρ" in label, f"Goal 2 should not show percentage CI, got: {label}"
        
        print("✓ Goal 2 correctly replaced CI with ranking stability")


class TestAdminSettings:
    """Test new convergence settings fields."""
    
    def test_settings_has_convergence_fields(self, admin_headers):
        """GET /api/admin/settings returns convergence_threshold, convergence_rounds."""
        resp = requests.get(f"{BASE_URL}/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        settings = data.get("settings", {})
        
        # New convergence fields
        assert "convergence_threshold" in settings, "convergence_threshold field missing"
        assert "convergence_rounds" in settings, "convergence_rounds field missing"
        
        # Verify types and ranges
        ct = settings["convergence_threshold"]
        cr = settings["convergence_rounds"]
        assert isinstance(ct, (int, float)), f"convergence_threshold should be float, got {type(ct)}"
        assert isinstance(cr, int), f"convergence_rounds should be int, got {type(cr)}"
        assert 0.5 <= ct <= 1.0, f"convergence_threshold should be 0.5-1.0, got {ct}"
        assert cr >= 1, f"convergence_rounds should be >= 1, got {cr}"
        
        print(f"✓ Settings has convergence_threshold={ct}, convergence_rounds={cr}")
    
    def test_settings_has_summary_fields(self, admin_headers):
        """GET /api/admin/settings returns summary_source, summary_parallel."""
        resp = requests.get(f"{BASE_URL}/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200
        settings = resp.json().get("settings", {})
        
        assert "summary_source" in settings, "summary_source field missing"
        assert "summary_parallel" in settings, "summary_parallel field missing"
        
        ss = settings["summary_source"]
        assert ss in ["round_robin", "claude", "gemini", "gpt"], f"Invalid summary_source: {ss}"
        
        print(f"✓ Settings has summary_source={ss}, summary_parallel={settings['summary_parallel']}")
    
    def test_settings_has_min_max_matches(self, admin_headers):
        """GET /api/admin/settings returns min_matches_per_paper=3, max_matches_per_paper=20."""
        resp = requests.get(f"{BASE_URL}/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200
        settings = resp.json().get("settings", {})
        
        assert "min_matches_per_paper" in settings, "min_matches_per_paper field missing"
        assert "max_matches_per_paper" in settings, "max_matches_per_paper field missing"
        
        min_m = settings["min_matches_per_paper"]
        max_m = settings["max_matches_per_paper"]
        
        # Per requirements, these should be 3 and 20
        assert min_m == 3, f"Expected min_matches_per_paper=3, got {min_m}"
        assert max_m == 20, f"Expected max_matches_per_paper=20, got {max_m}"
        
        print(f"✓ Settings has min_matches_per_paper={min_m}, max_matches_per_paper={max_m}")
    
    def test_update_convergence_settings(self, admin_headers):
        """PUT /api/admin/settings accepts convergence_threshold and convergence_rounds."""
        # First get current values
        resp = requests.get(f"{BASE_URL}/api/admin/settings", headers=admin_headers)
        original = resp.json().get("settings", {})
        original_ct = original.get("convergence_threshold", 0.95)
        original_cr = original.get("convergence_rounds", 3)
        
        # Update to new values (within valid range)
        new_ct = 0.90 if original_ct == 0.95 else 0.95
        new_cr = 4 if original_cr == 3 else 3
        
        update_resp = requests.put(f"{BASE_URL}/api/admin/settings",
                                   json={"convergence_threshold": new_ct, "convergence_rounds": new_cr},
                                   headers=admin_headers)
        assert update_resp.status_code == 200
        assert update_resp.json().get("success") == True
        
        # Verify updated
        check_resp = requests.get(f"{BASE_URL}/api/admin/settings", headers=admin_headers)
        updated = check_resp.json().get("settings", {})
        assert updated["convergence_threshold"] == new_ct, "convergence_threshold not updated"
        assert updated["convergence_rounds"] == new_cr, "convergence_rounds not updated"
        
        # Restore original
        requests.put(f"{BASE_URL}/api/admin/settings",
                    json={"convergence_threshold": original_ct, "convergence_rounds": original_cr},
                    headers=admin_headers)
        
        print(f"✓ Settings update works: convergence_threshold={new_ct}, convergence_rounds={new_cr}")


class TestBackfillSummariesEndpoint:
    """Test POST /api/admin/backfill-summaries endpoint."""
    
    def test_backfill_summaries_exists(self, admin_headers):
        """POST /api/admin/backfill-summaries endpoint exists and returns summary status."""
        resp = requests.post(f"{BASE_URL}/api/admin/backfill-summaries",
                           json={},
                           headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # Should return status about summary generation
        assert "status" in data, "status field missing"
        assert data["status"] in ["started", "complete", "waiting", "error"], \
            f"Unexpected status: {data['status']}"
        
        print(f"✓ Backfill summaries endpoint works, status={data['status']}")
        if "papers_needing_summaries" in data:
            print(f"  - Papers needing summaries: {data['papers_needing_summaries']}")
        if "papers_with_text" in data:
            print(f"  - Papers with text: {data['papers_with_text']}")
    
    def test_backfill_summaries_with_category(self, admin_headers):
        """POST /api/admin/backfill-summaries with category filter."""
        resp = requests.post(f"{BASE_URL}/api/admin/backfill-summaries",
                           json={"category": "cs.RO"},
                           headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # Should accept category parameter
        if data.get("category"):
            assert data["category"] == "cs.RO"
        
        print(f"✓ Backfill summaries accepts category filter")


class TestSummaryStatsEndpoint:
    """Test GET /api/admin/summary-stats endpoint."""
    
    def test_summary_stats_returns_pregen_coverage(self, admin_headers):
        """GET /api/admin/summary-stats returns pregen_coverage_rate and with_pregen_summaries."""
        resp = requests.get(f"{BASE_URL}/api/admin/summary-stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # Required fields per spec
        assert "pregen_coverage_rate" in data, "pregen_coverage_rate field missing"
        assert "with_pregen_summaries" in data, "with_pregen_summaries field missing"
        assert "total" in data, "total field missing"
        
        # Validate types
        assert isinstance(data["pregen_coverage_rate"], (int, float)), \
            f"pregen_coverage_rate should be numeric, got {type(data['pregen_coverage_rate'])}"
        assert isinstance(data["with_pregen_summaries"], int), \
            f"with_pregen_summaries should be int, got {type(data['with_pregen_summaries'])}"
        
        print(f"✓ Summary stats: {data['with_pregen_summaries']}/{data['total']} papers have pre-gen summaries")
        print(f"  - Coverage rate: {data['pregen_coverage_rate']}%")
    
    def test_summary_stats_with_category(self, admin_headers):
        """GET /api/admin/summary-stats with category filter."""
        resp = requests.get(f"{BASE_URL}/api/admin/summary-stats",
                          params={"category": "cs.RO"},
                          headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert "pregen_coverage_rate" in data
        if data.get("category"):
            assert data["category"] == "cs.RO"
        
        print(f"✓ Summary stats works with category filter")


class TestPaperDetailSummaries:
    """Test paper detail returns summaries field."""
    
    def test_paper_with_summaries(self):
        """GET /api/papers/{id} for paper with summaries returns summaries field."""
        resp = requests.get(f"{BASE_URL}/api/papers/{SAMPLE_PAPER_ID}")
        
        if resp.status_code == 404:
            pytest.skip(f"Sample paper {SAMPLE_PAPER_ID} not found")
        
        assert resp.status_code == 200
        data = resp.json()
        paper = data.get("paper", {})
        
        # Check if paper has summaries field (may not if backfill not complete)
        if "summaries" in paper and paper["summaries"]:
            summaries = paper["summaries"]
            assert isinstance(summaries, dict), f"summaries should be dict, got {type(summaries)}"
            
            # Check for provider:model keys
            for key, value in summaries.items():
                assert ":" in key, f"Summary key should be provider:model format, got {key}"
                assert isinstance(value, str), f"Summary value should be string, got {type(value)}"
            
            print(f"✓ Paper has {len(summaries)} pre-generated summaries")
            for key in summaries.keys():
                print(f"  - {key}")
        else:
            # Paper may not have summaries yet - check for legacy fallback
            if "impact_summary" in paper:
                print("✓ Paper has legacy impact_summary (no pre-gen summaries yet)")
            else:
                print("✓ Paper found but no summaries field yet (backfill in progress)")


class TestConvergenceEndpoint:
    """Test convergence endpoint still works."""
    
    def test_convergence_endpoint_works(self):
        """GET /api/convergence?category=cs.RO returns convergence data."""
        resp = requests.get(f"{BASE_URL}/api/convergence", params={"category": "cs.RO"})
        assert resp.status_code == 200
        data = resp.json()
        
        # Should have curve data
        assert "curve" in data or "data" in data, "convergence response should have curve/data"
        
        print("✓ Convergence endpoint working")


class TestLeaderboardStillWorks:
    """Verify leaderboard is not broken."""
    
    def test_leaderboard_loads(self):
        """GET /api/leaderboard?category=cs.RO returns papers."""
        resp = requests.get(f"{BASE_URL}/api/leaderboard", params={"category": "cs.RO"})
        assert resp.status_code == 200
        data = resp.json()
        
        assert "papers" in data, "papers field missing"
        assert "total" in data, "total field missing"
        assert len(data["papers"]) > 0, "No papers returned"
        
        print(f"✓ Leaderboard returns {len(data['papers'])} papers (total: {data['total']})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
