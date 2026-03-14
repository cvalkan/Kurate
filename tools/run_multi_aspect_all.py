#!/usr/bin/env python3
"""Run multi-aspect experiment sequentially across all ICLR datasets."""
import requests
import time
import sys

API = "https://kurate-bookmarks.preview.emergentagent.com"
ADMIN_TOKEN = "adm_PwgAikZRN0yUbPwU72rgzilv_OTqJYv5pMFHYptbW98"
HEADERS = {"Content-Type": "application/json", "X-Admin-Token": ADMIN_TOKEN}

DATASETS = [
    # iclr-codegen already running, skip it
    "iclr-pdes",       # 641 thinking matches
    "iclr-ot",         # 503 thinking matches
    "iclr-fairness",   # 264 thinking matches
    "iclr-protein",    # 259 thinking matches
    "iclr-optimization",  # 162 thinking matches
    "iclr-molecules",  # 158 thinking matches
]

def wait_for_completion():
    """Wait for current run to finish."""
    while True:
        try:
            r = requests.get(f"{API}/api/validation/multi-aspect/status", timeout=10)
            s = r.json()
            if not s.get("running"):
                return s
            print(f"  ... {s['done']}/{s['total']} matches ({s.get('dataset_id', '?')})", flush=True)
        except Exception as e:
            print(f"  status check failed: {e}", flush=True)
        time.sleep(30)

# First wait for codegen to finish
print("Waiting for iclr-codegen to finish...")
wait_for_completion()
print("iclr-codegen done!")

for ds in DATASETS:
    print(f"\nStarting {ds}...")
    r = requests.post(f"{API}/api/validation/multi-aspect/run",
                       json={"dataset_id": ds, "num_pairs": 500},
                       headers=HEADERS, timeout=10)
    print(f"  {r.json()}")
    result = wait_for_completion()
    print(f"  {ds} done: {result.get('done', '?')}/{result.get('total', '?')} matches")

print("\nAll datasets complete!")
