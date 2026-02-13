import requests
import sys
import json
import time
from datetime import datetime

class SciPostPairwiseAPITester:
    def __init__(self, base_url="https://research-validator.preview.emergentagent.com/api"):
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
        """Test SciPost pairwise status endpoint (abstract mode)"""
        success, response = self.run_test(
            "SciPost Pairwise Status (Abstract)", 
            "GET", 
            "scipost/pairwise/status", 
            200
        )
        
        if success:
            expected_fields = ['total_pairs', 'ai_completed', 'ai_failed', 'ai_pending', 'fetching', 'running', 'progress', 'by_dimension']
            missing_fields = [field for field in expected_fields if field not in response]
            
            if not missing_fields:
                self.log_test("Pairwise Status Structure Validation", True, f"All required fields present. Total pairs: {response.get('total_pairs', 0)}")
            else:
                self.log_test("Pairwise Status Structure Validation", False, f"Missing fields: {missing_fields}")
        
        return success, response

    def test_scipost_pairwise_extract_status(self):
        """Test SciPost pairwise extract status endpoint"""
        success, response = self.run_test(
            "SciPost Pairwise Extract Status", 
            "GET", 
            "scipost/pairwise-extract/status", 
            200
        )
        
        if success:
            expected_fields = ['total_pairs', 'ai_completed', 'ai_failed', 'ai_pending', 'fetching', 'running', 'progress', 'by_dimension', 'mode']
            missing_fields = [field for field in expected_fields if field not in response]
            
            if not missing_fields:
                mode = response.get('mode', 'unknown')
                self.log_test("Pairwise Extract Status Structure Validation", True, f"All required fields present. Mode: {mode}, Total pairs: {response.get('total_pairs', 0)}")
            else:
                self.log_test("Pairwise Extract Status Structure Validation", False, f"Missing fields: {missing_fields}")
        
        return success, response

    def test_scipost_pairwise_results(self):
        """Test SciPost pairwise results endpoint (abstract mode)"""
        success, response = self.run_test(
            "SciPost Pairwise Results (Abstract)", 
            "GET", 
            "scipost/pairwise/results", 
            200
        )
        
        if success:
            status = response.get('status')
            if status == 'no_data':
                self.log_test("Pairwise Results Validation", True, f"No data available (expected for new system): {response}")
            elif status == 'ok':
                expected_fields = ['total_pairs', 'overall_majority', 'by_dimension', 'by_model_overall', 'inter_model', 'samples']
                missing_fields = [field for field in expected_fields if field not in response]
                
                if not missing_fields:
                    total_pairs = response.get('total_pairs', 0)
                    overall_rate = response.get('overall_majority', {}).get('rate', 0)
                    self.log_test("Pairwise Results Structure Validation", True, f"Results available. Total pairs: {total_pairs}, Overall rate: {overall_rate}%")
                else:
                    self.log_test("Pairwise Results Structure Validation", False, f"Missing fields: {missing_fields}")
            else:
                self.log_test("Pairwise Results Validation", False, f"Unexpected status: {status}")
        
        return success, response

    def test_scipost_pairwise_extract_results(self):
        """Test SciPost pairwise extract results endpoint"""
        success, response = self.run_test(
            "SciPost Pairwise Extract Results", 
            "GET", 
            "scipost/pairwise-extract/results", 
            200
        )
        
        if success:
            status = response.get('status')
            mode = response.get('mode', 'unknown')
            
            if status == 'no_data':
                self.log_test("Pairwise Extract Results Validation", True, f"No data available for extract mode (expected): mode={mode}")
            elif status == 'ok':
                expected_fields = ['total_pairs', 'overall_majority', 'by_dimension', 'by_model_overall', 'inter_model', 'samples', 'mode']
                missing_fields = [field for field in expected_fields if field not in response]
                
                if not missing_fields:
                    total_pairs = response.get('total_pairs', 0)
                    overall_rate = response.get('overall_majority', {}).get('rate', 0)
                    self.log_test("Pairwise Extract Results Structure Validation", True, f"Extract results available. Mode: {mode}, Total pairs: {total_pairs}, Overall rate: {overall_rate}%")
                else:
                    self.log_test("Pairwise Extract Results Structure Validation", False, f"Missing fields: {missing_fields}")
            else:
                self.log_test("Pairwise Extract Results Validation", False, f"Unexpected status: {status}")
        
        return success, response

    def test_scipost_single_item_status(self):
        """Test SciPost single-item status endpoint for comparison"""
        success, response = self.run_test(
            "SciPost Single-Item Status", 
            "GET", 
            "scipost/status", 
            200
        )
        
        if success:
            expected_fields = ['total_comparisons', 'ai_completed', 'ai_failed', 'ai_pending', 'by_dimension', 'fetching', 'running', 'progress']
            missing_fields = [field for field in expected_fields if field not in response]
            
            if not missing_fields:
                self.log_test("Single-Item Status Structure Validation", True, f"All required fields present. Total comparisons: {response.get('total_comparisons', 0)}")
            else:
                self.log_test("Single-Item Status Structure Validation", False, f"Missing fields: {missing_fields}")
        
        return success, response

    def test_scipost_single_item_results(self):
        """Test SciPost single-item results endpoint for comparison"""
        success, response = self.run_test(
            "SciPost Single-Item Results", 
            "GET", 
            "scipost/results", 
            200
        )
        
        if success:
            status = response.get('status')
            if status == 'no_data':
                self.log_test("Single-Item Results Validation", True, f"No data available (expected for new system): {response}")
            elif status == 'ok':
                expected_fields = ['total_comparisons', 'by_dimension', 'by_model', 'model_overall', 'rating_distribution', 'samples']
                missing_fields = [field for field in expected_fields if field not in response]
                
                if not missing_fields:
                    total_comparisons = response.get('total_comparisons', 0)
                    self.log_test("Single-Item Results Structure Validation", True, f"Results available. Total comparisons: {total_comparisons}")
                else:
                    self.log_test("Single-Item Results Structure Validation", False, f"Missing fields: {missing_fields}")
            else:
                self.log_test("Single-Item Results Validation", False, f"Unexpected status: {status}")
        
        return success, response

    def test_validation_datasets(self):
        """Test validation datasets endpoint"""
        success, response = self.run_test(
            "Validation Datasets", 
            "GET", 
            "validation/datasets", 
            200
        )
        
        if success and 'datasets' in response:
            datasets = response['datasets']
            self.log_test("Validation Datasets Structure", True, f"Found {len(datasets)} datasets")
            
            if datasets:
                first_dataset = datasets[0]
                required_fields = ['dataset_id', 'name', 'papers']
                missing_fields = [field for field in required_fields if field not in first_dataset]
                
                if not missing_fields:
                    self.log_test("Dataset Structure Validation", True, f"Dataset structure valid: {first_dataset.get('name', 'Unknown')}")
                else:
                    self.log_test("Dataset Structure Validation", False, f"Missing fields in dataset: {missing_fields}")
        
        return success, response

    def test_endpoint_consistency(self):
        """Test that all endpoints return consistent data structures"""
        print("\n🔄 Testing endpoint consistency...")
        
        # Get all status endpoints
        _, pairwise_status = self.test_scipost_pairwise_status()
        _, extract_status = self.test_scipost_pairwise_extract_status()
        _, single_status = self.test_scipost_single_item_status()
        
        # Get all results endpoints
        _, pairwise_results = self.test_scipost_pairwise_results()
        _, extract_results = self.test_scipost_pairwise_extract_results()
        _, single_results = self.test_scipost_single_item_results()
        
        # Check mode field consistency
        extract_mode = extract_status.get('mode') if extract_status else None
        extract_results_mode = extract_results.get('mode') if extract_results else None
        
        if extract_mode == 'extract' and extract_results_mode == 'extract':
            self.log_test("Mode Field Consistency", True, "Extract mode correctly set in both status and results")
        else:
            self.log_test("Mode Field Consistency", False, f"Mode inconsistency: status={extract_mode}, results={extract_results_mode}")
        
        # Check that pairwise endpoints don't have mode field (abstract is default)
        pairwise_has_mode = 'mode' in (pairwise_status or {})
        pairwise_results_has_mode = 'mode' in (pairwise_results or {})
        
        if not pairwise_has_mode and not pairwise_results_has_mode:
            self.log_test("Abstract Mode Consistency", True, "Abstract mode endpoints don't have mode field (correct default)")
        else:
            self.log_test("Abstract Mode Consistency", False, f"Abstract endpoints unexpectedly have mode field")

    def run_all_tests(self):
        """Run all SciPost pairwise API tests"""
        print("🚀 Starting SciPost Pairwise API Tests")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)
        
        # Test validation datasets first
        self.test_validation_datasets()
        
        # Test SciPost pairwise endpoints
        print("\n📊 Testing SciPost Pairwise (Abstract) Endpoints...")
        self.test_scipost_pairwise_status()
        self.test_scipost_pairwise_results()
        
        print("\n📊 Testing SciPost Pairwise (Extract) Endpoints...")
        self.test_scipost_pairwise_extract_status()
        self.test_scipost_pairwise_extract_results()
        
        print("\n📊 Testing SciPost Single-Item Endpoints (for comparison)...")
        self.test_scipost_single_item_status()
        self.test_scipost_single_item_results()
        
        # Test consistency
        self.test_endpoint_consistency()
        
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