#!/usr/bin/env python3
"""
Quick admin auth test with correct header format
"""

import requests
import json

API_BASE = "https://scale-fix.preview.emergentagent.com/api"

def test_admin_auth():
    print("Testing admin authentication...")
    
    # Step 1: Login to get token
    response = requests.post(f"{API_BASE}/admin/login", 
                            json={"password": "papersumo2025"},
                            headers={"Content-Type": "application/json"})
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code}")
        return None
    
    data = response.json()
    if not data.get("success") or "token" not in data:
        print(f"❌ Login response invalid: {data}")
        return None
    
    token = data["token"]
    print(f"✅ Login successful, token: {token[:20]}...")
    
    # Step 2: Test admin endpoints with correct header
    headers = {"x-admin-token": token}
    
    endpoints = [
        "/admin/status?category=cs.RO",
        "/admin/progress?category=cs.RO",
        "/admin/settings"
    ]
    
    for endpoint in endpoints:
        response = requests.get(f"{API_BASE}{endpoint}", headers=headers)
        print(f"{endpoint} -> {response.status_code}")
        
        if response.status_code == 200:
            print(f"✅ {endpoint} working")
        elif response.status_code == 500:
            print(f"❌ {endpoint} - Server error")
            try:
                error_data = response.json()
                print(f"   Error: {error_data}")
            except:
                print(f"   Raw: {response.text[:200]}")
        else:
            print(f"⚠️  {endpoint} - Status {response.status_code}")

if __name__ == "__main__":
    test_admin_auth()