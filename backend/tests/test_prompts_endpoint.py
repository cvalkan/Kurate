"""
Test the /api/prompts public endpoint
Tests for iteration 17: Methodology & Prompts page features
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPromptsEndpoint:
    """Test GET /api/prompts public endpoint"""
    
    def test_prompts_endpoint_returns_200(self):
        """GET /api/prompts should return 200 without authentication"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /api/prompts returns 200 without auth")
    
    def test_prompts_has_evaluation_object(self):
        """Response should contain evaluation prompt object"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        assert response.status_code == 200
        data = response.json()
        
        assert "evaluation" in data, "Response should have 'evaluation' key"
        assert data["evaluation"] is not None, "Evaluation should not be None"
        print("✓ Response contains evaluation prompt object")
    
    def test_evaluation_prompt_has_system_and_user(self):
        """Evaluation prompt should have system_prompt and user_prompt"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        data = response.json()
        
        eval_prompt = data.get("evaluation", {})
        assert "system_prompt" in eval_prompt, "Evaluation should have system_prompt"
        assert "user_prompt" in eval_prompt, "Evaluation should have user_prompt"
        
        # Verify they are non-empty strings
        assert isinstance(eval_prompt["system_prompt"], str), "system_prompt should be a string"
        assert len(eval_prompt["system_prompt"]) > 50, "system_prompt should have meaningful content"
        assert isinstance(eval_prompt["user_prompt"], str), "user_prompt should be a string"
        assert len(eval_prompt["user_prompt"]) > 50, "user_prompt should have meaningful content"
        print("✓ Evaluation prompt has non-empty system_prompt and user_prompt")
    
    def test_prompts_has_summary_object(self):
        """Response should contain summary prompt object (may be None if not configured)"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        data = response.json()
        
        assert "summary" in data, "Response should have 'summary' key"
        print(f"✓ Response contains summary key (value: {'present' if data['summary'] else 'None'})")
    
    def test_summary_prompt_has_system_and_user_if_present(self):
        """If summary prompt exists, it should have system_prompt and user_prompt"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        data = response.json()
        
        summary_prompt = data.get("summary")
        if summary_prompt:
            assert "system_prompt" in summary_prompt, "Summary should have system_prompt"
            assert "user_prompt" in summary_prompt, "Summary should have user_prompt"
            assert isinstance(summary_prompt["system_prompt"], str), "system_prompt should be a string"
            assert isinstance(summary_prompt["user_prompt"], str), "user_prompt should be a string"
            print("✓ Summary prompt has system_prompt and user_prompt")
        else:
            print("✓ Summary prompt is not configured (None) - acceptable")
    
    def test_evaluation_prompt_contains_expected_keywords(self):
        """Evaluation prompt should contain expected AI evaluation keywords"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        data = response.json()
        
        eval_prompt = data.get("evaluation", {})
        system_prompt = eval_prompt.get("system_prompt", "").lower()
        
        # Check for expected keywords in the evaluation system prompt
        expected_keywords = ["scientific", "paper", "impact", "compare"]
        found_keywords = [kw for kw in expected_keywords if kw in system_prompt]
        
        assert len(found_keywords) >= 2, f"Expected at least 2 keywords from {expected_keywords}, found {found_keywords}"
        print(f"✓ Evaluation prompt contains expected keywords: {found_keywords}")
    
    def test_user_prompt_contains_template_variables(self):
        """User prompt should contain template variables like {paper1_title}"""
        response = requests.get(f"{BASE_URL}/api/prompts")
        data = response.json()
        
        user_prompt = data.get("evaluation", {}).get("user_prompt", "")
        
        # Check for template variables
        assert "{paper1_title}" in user_prompt or "{paper2_title}" in user_prompt, \
            "User prompt should contain template variables like {paper1_title}"
        print("✓ User prompt contains template variables for paper data")
    
    def test_prompts_endpoint_is_public(self):
        """Verify endpoint doesn't require any authentication header"""
        response = requests.get(
            f"{BASE_URL}/api/prompts",
            headers={"Content-Type": "application/json"}
            # No Authorization header
        )
        assert response.status_code == 200, f"Endpoint should be public, got {response.status_code}"
        print("✓ /api/prompts is publicly accessible (no auth required)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
