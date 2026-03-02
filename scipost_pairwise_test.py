import requests
import sys
import json
import time
from datetime import datetime

class SciPostPairwiseAPITester:
    def __init__(self, base_url="https://paper-scoring-hub.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
        
        result = {
            "test": name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"    Details: {details}")

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=30):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        print(f"\n🔍 Testing {name}...")
        print(f"    URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=timeout)

            success = response.status_code == expected_status
            
            if success:
                try:
                    response_data = response.json()
                    self.log_test(name, True, f"Status: {response.status_code}, Response keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'Non-dict response'}")
                    return True, response_data
                except:
                    self.log_test(name, True, f"Status: {response.status_code}, Non-JSON response")
                    return True, {}
            else:
                try:
                    error_data = response.json()
                    self.log_test(name, False, f"Expected {expected_status}, got {response.status_code}. Error: {error_data}")
                except:
                    self.log_test(name, False, f"Expected {expected_status}, got {response.status_code}. Response: {response.text[:200]}")
                return False, {}

        except requests.exceptions.Timeout:
            self.log_test(name, False, f"Request timeout after {timeout}s")
            return False, {}
        except Exception as e:
            self.log_test(name, False, f"Request error: {str(e)}")
            return False, {}

    def test_scipost_pairwise_status(self):
        """Test SciPost pairwise status endpoint"""
        success, response = self.run_test(
            "SciPost Pairwise Status", 
            "GET", 
            "scipost/pairwise/status", 
            200
        )
        
        if success:
            # Check if response contains mode information
            if 'mode' in response:
                mode = response['mode']
                self.log_test("Pairwise Status Mode Check", True, f"Mode field present: {mode}")
                
                # Validate other expected fields
                expected_fields = ['total_pairs', 'ai_completed', 'ai_failed', 'ai_pending', 'by_dimension', 'fetching', 'running', 'progress']
                missing_fields = [field for field in expected_fields if field not in response]
                
                if not missing_fields:
                    self.log_test("Pairwise Status Structure", True, "All expected fields present")
                else:
                    self.log_test("Pairwise Status Structure", False, f"Missing fields: {missing_fields}")
                    
            else:
                self.log_test("Pairwise Status Mode Check", False, "Mode field missing from response")
        
        return success, response

    def test_scipost_pairwise_extract_status(self):
        """Test SciPost pairwise-extract status endpoint"""
        success, response = self.run_test(
            "SciPost Pairwise-Extract Status", 
            "GET", 
            "scipost/pairwise-extract/status", 
            200
        )
        
        if success:
            # Check if response contains mode information
            if 'mode' in response:
                mode = response['mode']
                self.log_test("Pairwise-Extract Status Mode Check", True, f"Mode field present: {mode}")
                
                # Validate other expected fields
                expected_fields = ['total_pairs', 'ai_completed', 'ai_failed', 'ai_pending', 'by_dimension', 'fetching', 'running', 'progress']
                missing_fields = [field for field in expected_fields if field not in response]
                
                if not missing_fields:
                    self.log_test("Pairwise-Extract Status Structure", True, "All expected fields present")
                else:
                    self.log_test("Pairwise-Extract Status Structure", False, f"Missing fields: {missing_fields}")
                    
            else:
                self.log_test("Pairwise-Extract Status Mode Check", False, "Mode field missing from response")
        
        return success, response

    def test_scipost_regular_status(self):
        """Test regular SciPost status endpoint for comparison"""
        success, response = self.run_test(
            "SciPost Regular Status", 
            "GET", 
            "scipost/status", 
            200
        )
        
        if success:
            # This endpoint should not have mode field (for comparison)
            expected_fields = ['total_comparisons', 'ai_completed', 'ai_failed', 'ai_pending', 'by_dimension', 'fetching', 'running', 'progress']
            missing_fields = [field for field in expected_fields if field not in response]
            
            if not missing_fields:
                self.log_test("Regular Status Structure", True, "All expected fields present")
            else:
                self.log_test("Regular Status Structure", False, f"Missing fields: {missing_fields}")
        
        return success, response

    def test_scipost_pairwise_results(self):
        """Test SciPost pairwise results endpoint"""
        success, response = self.run_test(
            "SciPost Pairwise Results", 
            "GET", 
            "scipost/pairwise/results", 
            200
        )
        
        if success and response.get('status') == 'ok':
            # Check if mode is included in results
            if 'mode' in response:
                mode = response['mode']
                self.log_test("Pairwise Results Mode Check", True, f"Mode field present in results: {mode}")
            else:
                self.log_test("Pairwise Results Mode Check", False, "Mode field missing from results")
        
        return success, response

    def test_scipost_pairwise_extract_results(self):
        """Test SciPost pairwise-extract results endpoint"""
        success, response = self.run_test(
            "SciPost Pairwise-Extract Results", 
            "GET", 
            "scipost/pairwise-extract/results", 
            200
        )
        
        if success and response.get('status') == 'ok':
            # Check if mode is included in results
            if 'mode' in response:
                mode = response['mode']
                self.log_test("Pairwise-Extract Results Mode Check", True, f"Mode field present in results: {mode}")
            else:
                self.log_test("Pairwise-Extract Results Mode Check", False, "Mode field missing from results")
        
        return success, response

    def test_mode_consistency(self):
        """Test that modes are consistent between status and results endpoints"""
        # Get pairwise status
        success1, pairwise_status = self.run_test(
            "Pairwise Status for Mode Consistency", 
            "GET", 
            "scipost/pairwise/status", 
            200
        )
        
        # Get pairwise results
        success2, pairwise_results = self.run_test(
            "Pairwise Results for Mode Consistency", 
            "GET", 
            "scipost/pairwise/results", 
            200
        )
        
        if success1 and success2:
            status_mode = pairwise_status.get('mode')
            results_mode = pairwise_results.get('mode')
            
            if status_mode and results_mode and status_mode == results_mode:
                self.log_test("Pairwise Mode Consistency", True, f"Status and results both have mode: {status_mode}")
            else:
                self.log_test("Pairwise Mode Consistency", False, f"Mode mismatch - Status: {status_mode}, Results: {results_mode}")
        
        # Get pairwise-extract status
        success3, extract_status = self.run_test(
            "Pairwise-Extract Status for Mode Consistency", 
            "GET", 
            "scipost/pairwise-extract/status", 
            200
        )
        
        # Get pairwise-extract results
        success4, extract_results = self.run_test(
            "Pairwise-Extract Results for Mode Consistency", 
            "GET", 
            "scipost/pairwise-extract/results", 
            200
        )
        
        if success3 and success4:
            status_mode = extract_status.get('mode')
            results_mode = extract_results.get('mode')
            
            if status_mode and results_mode and status_mode == results_mode:
                self.log_test("Pairwise-Extract Mode Consistency", True, f"Status and results both have mode: {status_mode}")
            else:
                self.log_test("Pairwise-Extract Mode Consistency", False, f"Mode mismatch - Status: {status_mode}, Results: {results_mode}")

    def run_all_tests(self):
        """Run all SciPost pairwise API tests"""
        print("🚀 Starting SciPost Pairwise API Tests")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)
        
        # Test the main endpoints that should have mode
        self.test_scipost_pairwise_status()
        self.test_scipost_pairwise_extract_status()
        
        # Test regular status for comparison
        self.test_scipost_regular_status()
        
        # Test results endpoints
        self.test_scipost_pairwise_results()
        self.test_scipost_pairwise_extract_results()
        
        # Test mode consistency
        self.test_mode_consistency()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All SciPost pairwise tests passed!")
            return 0
        else:
            print("❌ Some SciPost pairwise tests failed!")
            return 1

def main():
    tester = SciPostPairwiseAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())