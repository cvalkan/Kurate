"""
Test extraction-stats endpoint for Admin Extraction page.
Verifies that sample_papers is returned and has correct structure.
Iteration 25 - Bug fix verification for missing Sample Papers table.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def admin_token():
    """Get admin token for authenticated requests."""
    response = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"password": ADMIN_PASSWORD},
        timeout=10
    )
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    data = response.json()
    assert "token" in data, "No token in login response"
    return data["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    """Headers with admin authentication."""
    return {
        "X-Admin-Token": admin_token,
        "Content-Type": "application/json"
    }


class TestExtractionStatsEndpoint:
    """Tests for GET /api/admin/extraction-stats endpoint."""
    
    def test_extraction_stats_returns_200(self, admin_headers):
        """Verify endpoint returns 200 OK."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_extraction_stats_has_sample_papers(self, admin_headers):
        """Verify response contains sample_papers array - THE KEY BUG FIX TEST."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        # Skip if still warming up
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        assert "sample_papers" in data, "sample_papers key missing from response"
        assert isinstance(data["sample_papers"], list), "sample_papers should be a list"
    
    def test_sample_papers_has_up_to_50_entries(self, admin_headers):
        """Verify sample_papers contains up to 50 entries."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        sample_papers = data.get("sample_papers", [])
        assert len(sample_papers) <= 50, f"Expected max 50 papers, got {len(sample_papers)}"
        # If there are papers with text, we should have some sample papers
        if data.get("papers_with_text", 0) > 0:
            assert len(sample_papers) > 0, "Expected at least 1 sample paper when papers_with_text > 0"
    
    def test_sample_paper_has_required_fields(self, admin_headers):
        """Verify each sample paper has all required fields."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        sample_papers = data.get("sample_papers", [])
        if len(sample_papers) == 0:
            pytest.skip("No sample papers available")
        
        required_fields = [
            "id", "title", "category", "full_text_chars",
            "sections_found", "intro_chars", "method_chars",
            "results_chars", "conclusion_chars"
        ]
        
        for i, paper in enumerate(sample_papers[:5]):  # Check first 5
            for field in required_fields:
                assert field in paper, f"Paper {i} missing field: {field}"
    
    def test_sample_paper_field_types(self, admin_headers):
        """Verify sample paper fields have correct types."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        sample_papers = data.get("sample_papers", [])
        if len(sample_papers) == 0:
            pytest.skip("No sample papers available")
        
        paper = sample_papers[0]
        
        # String fields
        assert isinstance(paper.get("id"), str), "id should be string"
        assert isinstance(paper.get("title"), str), "title should be string"
        assert isinstance(paper.get("category"), str), "category should be string"
        
        # Integer fields
        assert isinstance(paper.get("full_text_chars"), int), "full_text_chars should be int"
        assert isinstance(paper.get("sections_found"), int), "sections_found should be int"
        assert isinstance(paper.get("intro_chars"), int), "intro_chars should be int"
        assert isinstance(paper.get("method_chars"), int), "method_chars should be int"
        assert isinstance(paper.get("results_chars"), int), "results_chars should be int"
        assert isinstance(paper.get("conclusion_chars"), int), "conclusion_chars should be int"
    
    def test_sections_found_value_range(self, admin_headers):
        """Verify sections_found is between 0 and 4."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        sample_papers = data.get("sample_papers", [])
        for paper in sample_papers:
            sections_found = paper.get("sections_found", -1)
            assert 0 <= sections_found <= 4, f"sections_found={sections_found} out of range [0,4]"


class TestExtractionByCategoryTable:
    """Tests for by_category data in extraction stats."""
    
    def test_by_category_present(self, admin_headers):
        """Verify by_category is present in response."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        assert "by_category" in data, "by_category missing from response"
        assert isinstance(data["by_category"], dict), "by_category should be a dict"
    
    def test_by_category_structure(self, admin_headers):
        """Verify each category has required fields."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        by_category = data.get("by_category", {})
        if len(by_category) == 0:
            pytest.skip("No categories available")
        
        required_keys = ["total", "introduction", "methodology", "results", "conclusion"]
        
        for cat, cat_data in by_category.items():
            for key in required_keys:
                assert key in cat_data, f"Category {cat} missing key: {key}"


class TestSectionExtractionRatesOverall:
    """Tests for overall section extraction rates."""
    
    def test_overall_section_rates_present(self, admin_headers):
        """Verify overall section rates are present."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        assert "overall" in data, "overall missing from response"
        overall = data["overall"]
        
        sections = ["introduction", "methodology", "results", "conclusion"]
        for section in sections:
            assert section in overall, f"overall missing section: {section}"
    
    def test_overall_section_has_rate_fields(self, admin_headers):
        """Verify each overall section has rate, avg_chars, etc."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        overall = data.get("overall", {})
        
        for section_name in ["introduction", "methodology", "results", "conclusion"]:
            section = overall.get(section_name, {})
            assert "rate" in section, f"{section_name} missing 'rate'"
            assert "avg_chars" in section, f"{section_name} missing 'avg_chars'"


class TestOverviewCards:
    """Tests for overview card data (Papers with PDF, All 4 Headers Found, etc)."""
    
    def test_papers_with_text_present(self, admin_headers):
        """Verify papers_with_text count is present."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        assert "papers_with_text" in data, "papers_with_text missing"
        assert isinstance(data["papers_with_text"], int), "papers_with_text should be int"
    
    def test_all_headers_found_present(self, admin_headers):
        """Verify all_headers_found count is present."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        assert "all_headers_found" in data, "all_headers_found missing"
        assert "all_headers_rate" in data, "all_headers_rate missing"
    
    def test_extraction_ratio_present(self, admin_headers):
        """Verify extraction_ratio (for Avg Extracted card) is present."""
        response = requests.get(
            f"{BASE_URL}/api/admin/extraction-stats",
            headers=admin_headers,
            timeout=60
        )
        data = response.json()
        
        if data.get("warming_up"):
            pytest.skip("Cache still warming up")
        
        assert "avg_extracted_chars" in data, "avg_extracted_chars missing"
        assert "extraction_ratio" in data, "extraction_ratio missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
