"""
Test cases for Aggregate/Average toggle functionality on Model Correlation page.
Tests that the API returns different rho values for aggregate vs average mode.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAvgPwVsSiToggle:
    """Tests for avg_pw_vs_si and avg_pw_inter_model API fields"""
    
    def test_api_returns_avg_pw_vs_si_for_all_categories(self):
        """GET /api/model-analysis (no category) should return avg_pw_vs_si field"""
        response = requests.get(f"{BASE_URL}/api/model-analysis", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('status') == 'ok'
        
        # avg_pw_vs_si should be present and non-null for All Categories
        avg_pw_vs_si = data.get('avg_pw_vs_si')
        assert avg_pw_vs_si is not None, "avg_pw_vs_si should not be null for All Categories"
        assert 'per_model' in avg_pw_vs_si, "avg_pw_vs_si should have per_model key"
        assert 'within_model' in avg_pw_vs_si, "avg_pw_vs_si should have within_model key"
    
    def test_avg_pw_vs_si_has_claude_data(self):
        """avg_pw_vs_si.per_model should have claude data with rows"""
        response = requests.get(f"{BASE_URL}/api/model-analysis", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        avg_pw_vs_si = data.get('avg_pw_vs_si', {})
        per_model = avg_pw_vs_si.get('per_model', {})
        
        assert 'claude' in per_model, "avg_pw_vs_si.per_model should have claude key"
        claude_data = per_model['claude']
        assert 'rows' in claude_data, "claude data should have rows"
        assert len(claude_data['rows']) > 0, "claude rows should not be empty"
    
    def test_avg_rho_differs_from_aggregate_rho(self):
        """avg_pw_vs_si.per_model.claude.rows[0].spearman_rho should differ from pw_vs_si"""
        response = requests.get(f"{BASE_URL}/api/model-analysis", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        
        # Get aggregate rho (from pw_vs_si)
        pw_vs_si = data.get('pw_vs_si', {})
        agg_claude_rows = pw_vs_si.get('per_model', {}).get('claude', {}).get('rows', [])
        agg_reg_wr = next((r for r in agg_claude_rows if 'reg_wr' in r.get('method', '')), None)
        
        # Get average rho (from avg_pw_vs_si)
        avg_pw_vs_si = data.get('avg_pw_vs_si', {})
        avg_claude_rows = avg_pw_vs_si.get('per_model', {}).get('claude', {}).get('rows', [])
        avg_reg_wr = next((r for r in avg_claude_rows if 'reg_wr' in r.get('method', '')), None)
        
        assert agg_reg_wr is not None, "Aggregate Reg WR row should exist"
        assert avg_reg_wr is not None, "Average Reg WR row should exist"
        
        agg_rho = agg_reg_wr.get('spearman_rho')
        avg_rho = avg_reg_wr.get('spearman_rho')
        
        assert agg_rho is not None, "Aggregate rho should not be None"
        assert avg_rho is not None, "Average rho should not be None"
        assert agg_rho != avg_rho, f"Aggregate rho ({agg_rho}) should differ from Average rho ({avg_rho})"
        
        # Expected values based on preview data
        assert abs(agg_rho - 0.817) < 0.01, f"Aggregate rho should be ~0.817, got {agg_rho}"
        assert abs(avg_rho - 0.843) < 0.01, f"Average rho should be ~0.843, got {avg_rho}"
    
    def test_api_returns_avg_pw_inter_model(self):
        """GET /api/model-analysis should return avg_pw_inter_model as non-empty array"""
        response = requests.get(f"{BASE_URL}/api/model-analysis", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        avg_pw_inter_model = data.get('avg_pw_inter_model')
        
        assert avg_pw_inter_model is not None, "avg_pw_inter_model should not be null"
        assert isinstance(avg_pw_inter_model, list), "avg_pw_inter_model should be a list"
        assert len(avg_pw_inter_model) > 0, "avg_pw_inter_model should not be empty"
        
        # Check structure of first row
        first_row = avg_pw_inter_model[0]
        assert 'pair' in first_row, "Row should have pair key"
        assert 'methods' in first_row, "Row should have methods key"
        assert 'reg_wr' in first_row['methods'], "Methods should have reg_wr"
    
    def test_avg_pw_vs_si_null_for_specific_category(self):
        """When a specific category is selected, avg_pw_vs_si should be null"""
        response = requests.get(f"{BASE_URL}/api/model-analysis?category=cs.RO", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('category') == 'cs.RO', "Category should be cs.RO"
        
        # avg_pw_vs_si should be null for specific category
        avg_pw_vs_si = data.get('avg_pw_vs_si')
        assert avg_pw_vs_si is None, "avg_pw_vs_si should be null for specific category"
        
        # avg_pw_inter_model should also be null
        avg_pw_inter_model = data.get('avg_pw_inter_model')
        assert avg_pw_inter_model is None, "avg_pw_inter_model should be null for specific category"
    
    def test_pw_vs_si_still_works_for_specific_category(self):
        """pw_vs_si (aggregate) should still work for specific category"""
        response = requests.get(f"{BASE_URL}/api/model-analysis?category=cs.RO", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        pw_vs_si = data.get('pw_vs_si')
        
        # pw_vs_si should still be present for specific category
        assert pw_vs_si is not None, "pw_vs_si should not be null for specific category"
        assert 'per_model' in pw_vs_si, "pw_vs_si should have per_model"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
