import requests
import sys
import json
import time
from datetime import datetime

class ArxivTournamentAPITester:
    def __init__(self, base_url="https://research-eval.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.tournament_id = None
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
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=timeout)

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

    def test_root_endpoint(self):
        """Test root API endpoint"""
        return self.run_test("Root API Endpoint", "GET", "", 200)

    def test_get_categories(self):
        """Test getting arXiv categories"""
        success, response = self.run_test("Get Categories", "GET", "categories", 200)
        
        if success and 'categories' in response:
            categories = response['categories']
            if len(categories) > 0 and all('id' in cat and 'name' in cat for cat in categories):
                self.log_test("Categories Structure Validation", True, f"Found {len(categories)} valid categories")
                return True, response
            else:
                self.log_test("Categories Structure Validation", False, "Invalid category structure")
        
        return success, response

    def test_create_tournament(self):
        """Test creating a tournament"""
        tournament_data = {
            "category": "cs.AI",
            "num_papers": 4,  # Small number for testing
            "parallel_agents": 2
        }
        
        success, response = self.run_test(
            "Create Tournament", 
            "POST", 
            "tournaments", 
            200, 
            tournament_data,
            timeout=60  # Longer timeout for paper fetching
        )
        
        if success and 'tournament' in response:
            tournament = response['tournament']
            if 'id' in tournament:
                self.tournament_id = tournament['id']
                self.log_test("Tournament Creation Validation", True, f"Tournament ID: {self.tournament_id}")
                return True, response
            else:
                self.log_test("Tournament Creation Validation", False, "No tournament ID in response")
        
        return success, response

    def test_start_tournament(self):
        """Test starting a tournament"""
        if not self.tournament_id:
            self.log_test("Start Tournament", False, "No tournament ID available")
            return False, {}
        
        return self.run_test(
            "Start Tournament", 
            "POST", 
            f"tournaments/{self.tournament_id}/start", 
            200
        )

    def test_get_tournament_details(self):
        """Test getting tournament details"""
        if not self.tournament_id:
            self.log_test("Get Tournament Details", False, "No tournament ID available")
            return False, {}
        
        success, response = self.run_test(
            "Get Tournament Details", 
            "GET", 
            f"tournaments/{self.tournament_id}", 
            200
        )
        
        if success and 'tournament' in response:
            tournament = response['tournament']
            required_fields = ['id', 'category', 'status', 'papers', 'matches']
            missing_fields = [field for field in required_fields if field not in tournament]
            
            if not missing_fields:
                self.log_test("Tournament Details Validation", True, f"All required fields present. Status: {tournament.get('status')}")
            else:
                self.log_test("Tournament Details Validation", False, f"Missing fields: {missing_fields}")
        
        return success, response

    def test_list_tournaments(self):
        """Test listing all tournaments"""
        success, response = self.run_test("List Tournaments", "GET", "tournaments", 200)
        
        if success and 'tournaments' in response:
            tournaments = response['tournaments']
            self.log_test("Tournament List Validation", True, f"Found {len(tournaments)} tournaments")
        
        return success, response

    def test_tournament_progress(self):
        """Test tournament progress by polling"""
        if not self.tournament_id:
            self.log_test("Tournament Progress Check", False, "No tournament ID available")
            return False, {}
        
        print(f"\n🔄 Monitoring tournament progress for 30 seconds...")
        
        for i in range(6):  # Check 6 times over 30 seconds
            success, response = self.run_test(
                f"Tournament Progress Check {i+1}", 
                "GET", 
                f"tournaments/{self.tournament_id}", 
                200
            )
            
            if success and 'tournament' in response:
                tournament = response['tournament']
                status = tournament.get('status', 'unknown')
                progress = tournament.get('progress', 0)
                
                print(f"    Status: {status}, Progress: {progress}%")
                
                if status == 'completed':
                    self.log_test("Tournament Completion", True, f"Tournament completed with {progress}% progress")
                    return True, response
                elif status == 'failed':
                    self.log_test("Tournament Completion", False, f"Tournament failed: {tournament.get('current_log', 'No error message')}")
                    return False, response
            
            if i < 5:  # Don't sleep on last iteration
                time.sleep(5)
        
        # Final check
        success, response = self.run_test(
            "Final Tournament Status", 
            "GET", 
            f"tournaments/{self.tournament_id}", 
            200
        )
        
        if success and 'tournament' in response:
            tournament = response['tournament']
            status = tournament.get('status', 'unknown')
            if status in ['completed', 'running']:
                self.log_test("Tournament Progress Monitoring", True, f"Tournament is {status}")
                return True, response
            else:
                self.log_test("Tournament Progress Monitoring", False, f"Tournament status: {status}")
        
        return success, response

    def test_delete_tournament(self):
        """Test deleting a tournament"""
        if not self.tournament_id:
            self.log_test("Delete Tournament", False, "No tournament ID available")
            return False, {}
        
        return self.run_test(
            "Delete Tournament", 
            "DELETE", 
            f"tournaments/{self.tournament_id}", 
            200
        )

    def test_search_papers_keywords(self):
        """Test searching papers by keywords"""
        search_data = {
            "keywords": "transformer attention",
            "max_results": 5
        }
        
        success, response = self.run_test(
            "Search Papers by Keywords", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if success and 'papers' in response:
            papers = response['papers']
            count = response.get('count', 0)
            search_desc = response.get('search_description', '')
            
            if len(papers) > 0 and count == len(papers):
                self.log_test("Search Results Validation", True, f"Found {count} papers, description: {search_desc}")
                
                # Validate paper structure
                first_paper = papers[0]
                required_fields = ['id', 'title', 'authors', 'abstract', 'arxiv_id', 'link']
                missing_fields = [field for field in required_fields if field not in first_paper]
                
                if not missing_fields:
                    self.log_test("Search Paper Structure Validation", True, "All required fields present in papers")
                else:
                    self.log_test("Search Paper Structure Validation", False, f"Missing fields: {missing_fields}")
                
                return True, response
            else:
                self.log_test("Search Results Validation", False, f"Invalid results: papers={len(papers)}, count={count}")
        
        return success, response

    def test_search_papers_author(self):
        """Test searching papers by author"""
        search_data = {
            "author": "Hinton",
            "max_results": 3
        }
        
        success, response = self.run_test(
            "Search Papers by Author", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if success and 'papers' in response:
            papers = response['papers']
            self.log_test("Author Search Validation", True, f"Found {len(papers)} papers by author")
        
        return success, response

    def test_search_papers_category(self):
        """Test searching papers by category"""
        search_data = {
            "category": "cs.AI",
            "max_results": 5
        }
        
        success, response = self.run_test(
            "Search Papers by Category", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if success and 'papers' in response:
            papers = response['papers']
            # Verify papers have the correct category
            if papers and len(papers) > 0:
                first_paper = papers[0]
                categories = first_paper.get('categories', [])
                if 'cs.AI' in categories:
                    self.log_test("Category Filter Validation", True, f"Papers correctly filtered by cs.AI category")
                else:
                    self.log_test("Category Filter Validation", False, f"Papers don't match category filter: {categories}")
        
        return success, response

    def test_search_papers_combined(self):
        """Test searching papers with multiple filters"""
        search_data = {
            "keywords": "machine learning",
            "category": "cs.LG",
            "max_results": 3
        }
        
        success, response = self.run_test(
            "Search Papers with Combined Filters", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if success and 'papers' in response:
            papers = response['papers']
            search_desc = response.get('search_description', '')
            self.log_test("Combined Search Validation", True, f"Found {len(papers)} papers with combined filters: {search_desc}")
        
        return success, response

    def test_search_papers_date_filter(self):
        """Test searching papers with date filters"""
        search_data = {
            "keywords": "neural network",
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "max_results": 5
        }
        
        success, response = self.run_test(
            "Search Papers with Date Filter", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if success and 'papers' in response:
            papers = response['papers']
            # Verify date filtering
            if papers and len(papers) > 0:
                first_paper = papers[0]
                pub_date = first_paper.get('published', '')[:10]  # Get YYYY-MM-DD
                if pub_date >= "2024-01-01" and pub_date <= "2024-12-31":
                    self.log_test("Date Filter Validation", True, f"Papers correctly filtered by date: {pub_date}")
                else:
                    self.log_test("Date Filter Validation", False, f"Date filter not working: {pub_date}")
        
        return success, response

    def test_create_tournament_from_search(self):
        """Test creating tournament from search results"""
        # First search for papers
        search_data = {
            "keywords": "deep learning",
            "max_results": 4
        }
        
        success, search_response = self.run_test(
            "Search for Tournament Creation", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if not success or 'papers' not in search_response:
            self.log_test("Tournament from Search - Search Failed", False, "Could not get papers for tournament")
            return False, {}
        
        papers = search_response['papers']
        if len(papers) < 2:
            self.log_test("Tournament from Search - Insufficient Papers", False, f"Only {len(papers)} papers found, need at least 2")
            return False, {}
        
        # Create tournament from search results
        tournament_data = {
            "category": "custom",
            "papers": papers[:3],  # Use first 3 papers
            "parallel_agents": 2,
            "deep_analysis": False,
            "search_query": search_response.get('search_description', 'test search')
        }
        
        success, response = self.run_test(
            "Create Tournament from Search Results", 
            "POST", 
            "tournaments", 
            200, 
            tournament_data,
            timeout=60
        )
        
        if success and 'tournament' in response:
            tournament = response['tournament']
            if 'id' in tournament:
                # Store this tournament ID for potential cleanup
                search_tournament_id = tournament['id']
                self.log_test("Search Tournament Creation Validation", True, f"Tournament created from search: {search_tournament_id}")
                
                # Clean up immediately
                self.run_test(
                    "Cleanup Search Tournament", 
                    "DELETE", 
                    f"tournaments/{search_tournament_id}", 
                    200
                )
                
                return True, response
            else:
                self.log_test("Search Tournament Creation Validation", False, "No tournament ID in response")
        
        return success, response

    def test_search_empty_criteria(self):
        """Test search with no criteria (should return error)"""
        search_data = {
            "max_results": 5
        }
        
        # This should work as it will fetch recent papers with "all:*" query
        success, response = self.run_test(
            "Search with No Criteria", 
            "POST", 
            "papers/search", 
            200, 
            search_data,
            timeout=30
        )
        
        if success and 'papers' in response:
            papers = response['papers']
            self.log_test("Empty Criteria Search Validation", True, f"Default search returned {len(papers)} papers")
        
        return success, response

    def test_invalid_endpoints(self):
        """Test error handling for invalid requests"""
        # Test invalid category
        invalid_tournament = {
            "category": "invalid.category",
            "num_papers": 5,
            "parallel_agents": 2
        }
        
        success, _ = self.run_test(
            "Invalid Category Error Handling", 
            "POST", 
            "tournaments", 
            400, 
            invalid_tournament
        )
        
        # Test non-existent tournament
        success2, _ = self.run_test(
            "Non-existent Tournament Error Handling", 
            "GET", 
            "tournaments/non-existent-id", 
            404
        )
        
        return success and success2

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting ArXiv Tournament API Tests (Including Search Feature)")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)
        
        # Basic connectivity
        self.test_root_endpoint()
        
        # Core functionality
        self.test_get_categories()
        
        # NEW: Search functionality tests
        print("\n📋 Testing Search Feature...")
        self.test_search_papers_keywords()
        self.test_search_papers_author()
        self.test_search_papers_category()
        self.test_search_papers_combined()
        self.test_search_papers_date_filter()
        self.test_create_tournament_from_search()
        self.test_search_empty_criteria()
        
        # Original tournament functionality
        print("\n🏆 Testing Tournament Creation...")
        self.test_create_tournament()
        self.test_start_tournament()
        self.test_get_tournament_details()
        self.test_list_tournaments()
        
        # Progress monitoring (this takes time)
        print("\n⏱️ Testing Tournament Progress...")
        self.test_tournament_progress()
        
        # Cleanup
        self.test_delete_tournament()
        
        # Error handling
        print("\n🚨 Testing Error Handling...")
        self.test_invalid_endpoints()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print("❌ Some tests failed!")
            return 1

def main():
    tester = ArxivTournamentAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())