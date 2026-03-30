"""
Deployment Readiness Test Suite for PaperSumo
Tests all major features for the llm-ranker.preview.emergentagent.com deployment.

Features tested:
- Health endpoint
- Leaderboard API with Rating/Gap columns
- Category switching
- Validation Hub datasets
- Paper detail API
- Admin login
- Security headers
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class TestHealthAndBasics:
    """Health check and basic API tests"""
    
    def test_health_endpoint(self):
        """Test /api/health returns 200"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        print(f"PASS: Health endpoint returns ok")

    def test_security_headers_present(self):
        """Test security headers are present on all responses"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        headers = response.headers
        
        # Check HSTS
        assert "Strict-Transport-Security" in headers, "Missing HSTS header"
        print(f"  HSTS: {headers['Strict-Transport-Security']}")
        
        # Check X-Content-Type-Options
        assert "X-Content-Type-Options" in headers, "Missing X-Content-Type-Options"
        assert headers["X-Content-Type-Options"] == "nosniff"
        print(f"  X-Content-Type-Options: {headers['X-Content-Type-Options']}")
        
        # Check X-Frame-Options
        assert "X-Frame-Options" in headers, "Missing X-Frame-Options"
        assert headers["X-Frame-Options"] == "DENY"
        print(f"  X-Frame-Options: {headers['X-Frame-Options']}")
        
        print(f"PASS: All security headers present")


class TestCategoriesAPI:
    """Test categories endpoint"""
    
    def test_get_categories(self):
        """Test /api/categories returns valid categories list"""
        response = requests.get(f"{BASE_URL}/api/categories", timeout=10)
        assert response.status_code == 200
        data = response.json()
        
        assert "categories" in data
        assert "default" in data
        assert len(data["categories"]) > 0
        
        # Check each category has id and name
        for cat in data["categories"]:
            assert "id" in cat
            assert "name" in cat
        
        print(f"PASS: Categories API returns {len(data['categories'])} categories")
        print(f"  Default category: {data['default']}")
        print(f"  Categories: {[c['id'] for c in data['categories']]}")


class TestLeaderboardAPI:
    """Test leaderboard endpoints with Rating/Gap columns"""
    
    def test_leaderboard_robotics(self):
        """Test leaderboard for cs.RO category"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&period=all", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "leaderboard" in data
        assert "total_papers" in data
        assert "total_matches" in data
        
        # Check show_rating_column and show_gap_column settings
        assert "show_rating_column" in data, "Missing show_rating_column in response"
        assert "show_gap_column" in data, "Missing show_gap_column in response"
        
        print(f"PASS: Robotics leaderboard - {data['total_papers']} papers, {data['total_matches']} matches")
        print(f"  show_rating_column: {data['show_rating_column']}")
        print(f"  show_gap_column: {data['show_gap_column']}")
        
        # Check leaderboard entries have expected fields
        if data["leaderboard"]:
            entry = data["leaderboard"][0]
            assert "id" in entry
            assert "title" in entry
            assert "score" in entry
            assert "rank" in entry
            print(f"  Top paper: {entry['title'][:50]}...")
            if "ai_rating" in entry:
                print(f"    ai_rating: {entry.get('ai_rating')}")
            if "sp_score" in entry:
                print(f"    sp_score (Gap): {entry.get('sp_score')}")

    def test_leaderboard_distributed_computing(self):
        """Test leaderboard for cs.DC category"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.DC&period=all", timeout=30)
        assert response.status_code == 200
        data = response.json()
        print(f"PASS: Distributed Computing - {data['total_papers']} papers, {data['total_matches']} matches")

    def test_leaderboard_economics(self):
        """Test leaderboard for econ.GN category"""
        response = requests.get(f"{BASE_URL}/api/leaderboard?category=econ.GN&period=all", timeout=30)
        assert response.status_code == 200
        data = response.json()
        print(f"PASS: Economics - {data['total_papers']} papers, {data['total_matches']} matches")

    def test_leaderboard_period_filter(self):
        """Test period filters work"""
        for period in ["week", "month", "all"]:
            response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&period={period}", timeout=30)
            assert response.status_code == 200
            data = response.json()
            print(f"  Period '{period}': {data.get('total_in_period', 0)} papers")
        print(f"PASS: Period filters work")


class TestValidationDatasetsAPI:
    """Test validation datasets endpoint"""
    
    def test_get_validation_datasets(self):
        """Test /api/validation/datasets returns all experiment datasets"""
        response = requests.get(f"{BASE_URL}/api/validation/datasets", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "datasets" in data
        datasets = data["datasets"]
        assert len(datasets) > 0
        
        # Check for key datasets
        dataset_names = [d.get("name", "") for d in datasets]
        print(f"PASS: Validation datasets API returns {len(datasets)} datasets")
        
        # Look for ICLR, eLife, MIDL datasets
        iclr_count = sum(1 for n in dataset_names if "ICLR" in n)
        elife_count = sum(1 for n in dataset_names if "eLife" in n)
        midl_count = sum(1 for n in dataset_names if "MIDL" in n)
        
        print(f"  ICLR datasets: {iclr_count}")
        print(f"  eLife datasets: {elife_count}")
        print(f"  MIDL datasets: {midl_count}")
        
        # Verify dataset structure
        for ds in datasets[:3]:
            assert "dataset_id" in ds
            assert "name" in ds
            print(f"  Sample: {ds['name']} ({ds.get('papers', 0)} papers)")


class TestPaperDetailAPI:
    """Test paper detail endpoint"""
    
    def test_paper_detail_with_real_paper(self):
        """Get a paper ID from leaderboard and test detail endpoint"""
        # First get a paper ID from leaderboard
        lb_response = requests.get(f"{BASE_URL}/api/leaderboard?category=cs.RO&period=all", timeout=30)
        assert lb_response.status_code == 200
        lb_data = lb_response.json()
        
        if not lb_data.get("leaderboard"):
            pytest.skip("No papers in leaderboard")
        
        paper_id = lb_data["leaderboard"][0]["id"]
        
        # Now test paper detail
        response = requests.get(f"{BASE_URL}/api/papers/{paper_id}", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "paper" in data
        assert "matches" in data
        assert "stats" in data
        
        paper = data["paper"]
        assert "title" in paper
        assert "id" in paper
        
        print(f"PASS: Paper detail API works")
        print(f"  Title: {paper['title'][:60]}...")
        print(f"  Matches: {len(data['matches'])}")
        print(f"  Stats: wins={data['stats']['wins']}, losses={data['stats']['losses']}")
        
        # Check for AI summaries
        if paper.get("summaries"):
            print(f"  Has AI summaries: {list(paper['summaries'].keys())}")
        if paper.get("ai_rating"):
            print(f"  AI rating: {paper['ai_rating']}")


class TestAdminLogin:
    """Test admin login endpoint"""
    
    def test_admin_login_success(self):
        """Test admin login with correct password"""
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": ADMIN_PASSWORD},
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "token" in data
        print(f"PASS: Admin login successful")
        return data["token"]

    def test_admin_login_failure(self):
        """Test admin login with wrong password"""
        response = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"password": "wrongpassword"},
            timeout=10
        )
        assert response.status_code == 403
        print(f"PASS: Admin login correctly rejects wrong password")


class TestTagsAPI:
    """Test tags endpoint"""
    
    def test_get_tags(self):
        """Test /api/tags returns all category tags"""
        response = requests.get(f"{BASE_URL}/api/tags", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "tags" in data
        tags = data["tags"]
        print(f"PASS: Tags API returns {len(tags)} tags")
        
        # Show top tags
        if tags:
            for tag in tags[:5]:
                print(f"  {tag['id']}: {tag.get('count', 0)} papers, {tag.get('matches', 0)} matches")


class TestPromptsAPI:
    """Test public prompts endpoint"""
    
    def test_get_prompts(self):
        """Test /api/prompts returns evaluation prompts"""
        response = requests.get(f"{BASE_URL}/api/prompts", timeout=10)
        assert response.status_code == 200
        data = response.json()
        
        assert "evaluation" in data
        assert "summary" in data
        assert "rating" in data
        
        # Check prompt structure
        for key in ["evaluation", "summary", "rating"]:
            prompt = data[key]
            assert "system_prompt" in prompt
            assert "user_prompt" in prompt
            assert len(prompt["system_prompt"]) > 0
        
        print(f"PASS: Prompts API returns all 3 prompt types")


class TestStatusAPI:
    """Test system status endpoint"""
    
    def test_get_status(self):
        """Test /api/status returns system stats"""
        response = requests.get(f"{BASE_URL}/api/status", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "total_papers" in data
        assert "total_matches" in data
        
        print(f"PASS: Status API")
        print(f"  Total papers: {data['total_papers']}")
        print(f"  Total matches: {data['total_matches']}")
        print(f"  Failed matches: {data.get('failed_matches', 0)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
