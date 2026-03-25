"""
Test AI Ranking Quality Scoring Methods Feature
Tests the new scoring method toggle (win_rate, bt, trueskill) and 40%/50% K% tiers
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestAIRankingQualityScoringMethods:
    """Tests for AI Ranking Quality scoring methods and K% tiers"""

    def test_ai_ranking_quality_returns_scoring_methods(self):
        """API returns scoring_methods=['win_rate','bt','trueskill']"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "scoring_methods" in data
        assert data["scoring_methods"] == ["win_rate", "bt", "trueskill"]

    def test_ai_ranking_quality_returns_by_method(self):
        """API returns by_method with all 3 scoring methods"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "by_method" in data
        by_method = data["by_method"]
        assert "win_rate" in by_method
        assert "bt" in by_method
        assert "trueskill" in by_method

    def test_pooled_overlap_table_has_18_rows(self):
        """pooled_overlap_table has 18 rows (3 GT methods × 6 K% tiers)"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        ot = data.get("pooled_overlap_table", [])
        assert len(ot) == 18, f"Expected 18 rows, got {len(ot)}"

    def test_pooled_overlap_table_has_all_k_tiers(self):
        """pooled_overlap_table has 5%, 10%, 20%, 30%, 40%, 50% K% tiers"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        ot = data.get("pooled_overlap_table", [])
        pct_values = set(row.get("pct") for row in ot)
        expected_pcts = {5, 10, 20, 30, 40, 50}
        assert pct_values == expected_pcts, f"Expected K% tiers {expected_pcts}, got {pct_values}"

    def test_pooled_overlap_table_has_all_gt_methods(self):
        """pooled_overlap_table has all 3 GT methods (indiv, maj, avg_rating)"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        ot = data.get("pooled_overlap_table", [])
        gt_values = set(row.get("gt") for row in ot)
        expected_gts = {"indiv", "maj", "avg_rating"}
        assert gt_values == expected_gts, f"Expected GT methods {expected_gts}, got {gt_values}"

    def test_by_method_bt_differs_from_win_rate(self):
        """by_method.bt correlation values differ from by_method.win_rate"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        by_method = data.get("by_method", {})
        
        wr_rho = by_method.get("win_rate", {}).get("pooled_bt", {}).get("indiv", {}).get("spearman_rho")
        bt_rho = by_method.get("bt", {}).get("pooled_bt", {}).get("indiv", {}).get("spearman_rho")
        
        assert wr_rho is not None, "win_rate indiv rho should not be None"
        assert bt_rho is not None, "bt indiv rho should not be None"
        assert wr_rho != bt_rho, f"BT rho ({bt_rho}) should differ from win_rate rho ({wr_rho})"

    def test_by_method_trueskill_differs_from_win_rate(self):
        """by_method.trueskill correlation values differ from by_method.win_rate"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        by_method = data.get("by_method", {})
        
        wr_rho = by_method.get("win_rate", {}).get("pooled_bt", {}).get("indiv", {}).get("spearman_rho")
        ts_rho = by_method.get("trueskill", {}).get("pooled_bt", {}).get("indiv", {}).get("spearman_rho")
        
        assert wr_rho is not None, "win_rate indiv rho should not be None"
        assert ts_rho is not None, "trueskill indiv rho should not be None"
        assert wr_rho != ts_rho, f"TrueSkill rho ({ts_rho}) should differ from win_rate rho ({wr_rho})"

    def test_per_dataset_has_by_method(self):
        """per_dataset[0].by_method contains all 3 methods"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        per_dataset = data.get("per_dataset", [])
        assert len(per_dataset) > 0, "per_dataset should not be empty"
        
        pd0 = per_dataset[0]
        assert "by_method" in pd0, "per_dataset[0] should have by_method"
        by_method = pd0["by_method"]
        assert "win_rate" in by_method
        assert "bt" in by_method
        assert "trueskill" in by_method


class TestAIRankingQualityUnfilteredScoringMethods:
    """Tests for AI Ranking Quality Unfiltered endpoint scoring methods"""

    def test_unfiltered_returns_scoring_methods(self):
        """Unfiltered API returns scoring_methods=['win_rate','bt','trueskill']"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality-unfiltered?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "scoring_methods" in data
        assert data["scoring_methods"] == ["win_rate", "bt", "trueskill"]

    def test_unfiltered_returns_by_method(self):
        """Unfiltered API returns by_method with all 3 scoring methods"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality-unfiltered?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "by_method" in data
        by_method = data["by_method"]
        assert "win_rate" in by_method
        assert "bt" in by_method
        assert "trueskill" in by_method

    def test_unfiltered_pooled_overlap_table_has_18_rows(self):
        """Unfiltered pooled_overlap_table has 18 rows (3 GT × 6 K%)"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality-unfiltered?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        ot = data.get("pooled_overlap_table", [])
        assert len(ot) == 18, f"Expected 18 rows, got {len(ot)}"

    def test_unfiltered_pooled_overlap_table_has_all_k_tiers(self):
        """Unfiltered pooled_overlap_table has 5%, 10%, 20%, 30%, 40%, 50% K% tiers"""
        response = requests.get(f"{BASE_URL}/api/validation/ai-ranking-quality-unfiltered?gt_type=comp", timeout=60)
        assert response.status_code == 200
        data = response.json()
        ot = data.get("pooled_overlap_table", [])
        pct_values = set(row.get("pct") for row in ot)
        expected_pcts = {5, 10, 20, 30, 40, 50}
        assert pct_values == expected_pcts, f"Expected K% tiers {expected_pcts}, got {pct_values}"
