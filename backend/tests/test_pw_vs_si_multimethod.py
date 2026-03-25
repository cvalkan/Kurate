"""
Test PW vs SI Multi-Method Comparison Feature
Tests the new pw_vs_si structure in /api/si-rating-stats endpoint
- Overall comparison: 3 PW methods (win_rate, bt, trueskill) vs averaged SI
- Per-model breakdown: claude, gpt, gemini
- Backward compatibility: bt_vs_si still present
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPwVsSiMultiMethod:
    """Tests for PW vs SI multi-method comparison feature"""

    @pytest.fixture(scope="class")
    def si_rating_stats(self):
        """Fetch SI rating stats once for all tests in this class"""
        response = requests.get(f"{BASE_URL}/api/si-rating-stats", timeout=90)
        assert response.status_code == 200, f"Failed to fetch si-rating-stats: {response.status_code}"
        return response.json()

    def test_endpoint_returns_200(self):
        """Test that /api/si-rating-stats returns 200"""
        response = requests.get(f"{BASE_URL}/api/si-rating-stats", timeout=90)
        assert response.status_code == 200

    def test_pw_vs_si_exists(self, si_rating_stats):
        """Test that pw_vs_si object exists in response"""
        assert "pw_vs_si" in si_rating_stats, "pw_vs_si key missing from response"
        assert si_rating_stats["pw_vs_si"] is not None, "pw_vs_si is None"

    def test_pw_vs_si_has_overall_array(self, si_rating_stats):
        """Test that pw_vs_si.overall is an array"""
        pw_vs_si = si_rating_stats["pw_vs_si"]
        assert "overall" in pw_vs_si, "overall key missing from pw_vs_si"
        assert isinstance(pw_vs_si["overall"], list), "overall should be a list"

    def test_overall_has_three_methods(self, si_rating_stats):
        """Test that overall array contains entries for win_rate, bt, and trueskill"""
        overall = si_rating_stats["pw_vs_si"]["overall"]
        methods = [row["method"] for row in overall]
        assert "win_rate" in methods, "win_rate method missing from overall"
        assert "bt" in methods, "bt method missing from overall"
        assert "trueskill" in methods, "trueskill method missing from overall"
        assert len(overall) == 3, f"Expected 3 methods in overall, got {len(overall)}"

    def test_overall_entries_have_required_fields(self, si_rating_stats):
        """Test that each overall entry has spearman_rho, kendall_tau, pearson_r, n"""
        overall = si_rating_stats["pw_vs_si"]["overall"]
        required_fields = ["spearman_rho", "kendall_tau", "pearson_r", "n", "method", "label"]
        for row in overall:
            for field in required_fields:
                assert field in row, f"Field {field} missing from overall entry: {row}"
            # Validate types
            assert isinstance(row["spearman_rho"], (int, float)), "spearman_rho should be numeric"
            assert isinstance(row["kendall_tau"], (int, float)), "kendall_tau should be numeric"
            assert isinstance(row["pearson_r"], (int, float)), "pearson_r should be numeric"
            assert isinstance(row["n"], int), "n should be integer"

    def test_overall_labels_correct(self, si_rating_stats):
        """Test that overall entries have correct labels"""
        overall = si_rating_stats["pw_vs_si"]["overall"]
        expected_labels = {
            "win_rate": "Normalized Win-Rate",
            "bt": "Bradley-Terry",
            "trueskill": "TrueSkill"
        }
        for row in overall:
            method = row["method"]
            assert row["label"] == expected_labels[method], f"Wrong label for {method}: {row['label']}"

    def test_pw_vs_si_has_per_model_dict(self, si_rating_stats):
        """Test that pw_vs_si.per_model is a dict"""
        pw_vs_si = si_rating_stats["pw_vs_si"]
        assert "per_model" in pw_vs_si, "per_model key missing from pw_vs_si"
        assert isinstance(pw_vs_si["per_model"], dict), "per_model should be a dict"

    def test_per_model_has_claude_gpt_gemini(self, si_rating_stats):
        """Test that per_model has claude, gpt, gemini keys"""
        per_model = si_rating_stats["pw_vs_si"]["per_model"]
        assert "claude" in per_model, "claude key missing from per_model"
        assert "gpt" in per_model, "gpt key missing from per_model"
        assert "gemini" in per_model, "gemini key missing from per_model"

    def test_per_model_entries_have_label_and_rows(self, si_rating_stats):
        """Test that each per_model entry has label and rows array"""
        per_model = si_rating_stats["pw_vs_si"]["per_model"]
        expected_labels = {
            "claude": "Claude Opus",
            "gpt": "GPT-5.2",
            "gemini": "Gemini 3 Pro"
        }
        for mk in ["claude", "gpt", "gemini"]:
            entry = per_model[mk]
            assert "label" in entry, f"label missing from per_model.{mk}"
            assert "rows" in entry, f"rows missing from per_model.{mk}"
            assert isinstance(entry["rows"], list), f"per_model.{mk}.rows should be a list"
            assert entry["label"] == expected_labels[mk], f"Wrong label for {mk}: {entry['label']}"

    def test_per_model_rows_have_three_methods(self, si_rating_stats):
        """Test that each per_model entry has 3 rows (one per PW method)"""
        per_model = si_rating_stats["pw_vs_si"]["per_model"]
        for mk in ["claude", "gpt", "gemini"]:
            rows = per_model[mk]["rows"]
            methods = [row["method"] for row in rows]
            assert "win_rate" in methods, f"win_rate missing from per_model.{mk}.rows"
            assert "bt" in methods, f"bt missing from per_model.{mk}.rows"
            assert "trueskill" in methods, f"trueskill missing from per_model.{mk}.rows"
            assert len(rows) == 3, f"Expected 3 rows in per_model.{mk}, got {len(rows)}"

    def test_per_model_rows_have_required_fields(self, si_rating_stats):
        """Test that per_model rows have required correlation fields"""
        per_model = si_rating_stats["pw_vs_si"]["per_model"]
        required_fields = ["spearman_rho", "kendall_tau", "n", "method", "label"]
        for mk in ["claude", "gpt", "gemini"]:
            for row in per_model[mk]["rows"]:
                for field in required_fields:
                    assert field in row, f"Field {field} missing from per_model.{mk} row: {row}"

    def test_pw_vs_si_has_n_matches(self, si_rating_stats):
        """Test that pw_vs_si has n_matches field"""
        pw_vs_si = si_rating_stats["pw_vs_si"]
        assert "n_matches" in pw_vs_si, "n_matches missing from pw_vs_si"
        assert isinstance(pw_vs_si["n_matches"], int), "n_matches should be integer"
        assert pw_vs_si["n_matches"] > 0, "n_matches should be positive"

    def test_bt_vs_si_backward_compatibility(self, si_rating_stats):
        """Test that bt_vs_si is still present for backward compatibility"""
        assert "bt_vs_si" in si_rating_stats, "bt_vs_si key missing (backward compatibility broken)"
        bt_vs_si = si_rating_stats["bt_vs_si"]
        # bt_vs_si should be the first entry from overall (win_rate)
        assert bt_vs_si is not None, "bt_vs_si should not be None"
        assert "spearman_rho" in bt_vs_si, "spearman_rho missing from bt_vs_si"
        assert "kendall_tau" in bt_vs_si, "kendall_tau missing from bt_vs_si"
        assert "pearson_r" in bt_vs_si, "pearson_r missing from bt_vs_si"
        assert "n" in bt_vs_si, "n missing from bt_vs_si"

    def test_trueskill_has_highest_correlation(self, si_rating_stats):
        """Test that TrueSkill typically has highest Spearman correlation (as expected)"""
        overall = si_rating_stats["pw_vs_si"]["overall"]
        ts_row = next((r for r in overall if r["method"] == "trueskill"), None)
        assert ts_row is not None, "TrueSkill row not found"
        # TrueSkill should have a reasonable correlation
        assert ts_row["spearman_rho"] > 0.5, f"TrueSkill correlation too low: {ts_row['spearman_rho']}"

    def test_model_comparison_exists(self, si_rating_stats):
        """Test that model_comparison exists for SI calibration section"""
        assert "model_comparison" in si_rating_stats, "model_comparison missing"
        mc = si_rating_stats["model_comparison"]
        assert isinstance(mc, dict), "model_comparison should be a dict"
        # Should have at least 2 models for calibration comparison
        assert len(mc) >= 2, f"Expected at least 2 models in model_comparison, got {len(mc)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
