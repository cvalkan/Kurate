#!/usr/bin/env python3
"""Run summarizer A/B experiment across ICLR datasets for GPT and Gemini."""
import requests, time

API = "https://kurate-core.preview.emergentagent.com"
ADMIN_TOKEN = "adm_PwgAikZRN0yUbPwU72rgzilv_OTqJYv5pMFHYptbW98"
HEADERS = {"Content-Type": "application/json", "X-Admin-Token": ADMIN_TOKEN}

RUNS = [
    # GPT already running on iclr-llm, will start from iclr-codegen
    ("iclr-codegen", "gpt", 300),
    ("iclr-pdes", "gpt", 300),
    ("iclr-ot", "gpt", 300),
    ("iclr-fairness", "gpt", 300),
    ("iclr-protein", "gpt", 300),
    # Gemini for all
    ("iclr-llm", "gemini", 300),
    ("iclr-codegen", "gemini", 300),
    ("iclr-pdes", "gemini", 300),
    ("iclr-ot", "gemini", 300),
    ("iclr-fairness", "gemini", 300),
    ("iclr-protein", "gemini", 300),
]

def wait():
    while True:
        try:
            r = requests.get(f"{API}/api/validation/summarizer-ab/status", timeout=10)
            s = r.json()
            if not s.get("running"): return s
            print(f"  [{s.get('dataset_id')}/{s.get('summarizer')}] {s.get('phase','?')}: {s['done']}/{s['total']}", flush=True)
        except Exception as e:
            print(f"  status error: {e}", flush=True)
        time.sleep(30)

# Wait for current iclr-llm/gpt to finish
print("Waiting for iclr-llm/gpt...")
wait()
print("Done!")

for ds, summarizer, n in RUNS:
    print(f"\nStarting {ds}/{summarizer} ({n} pairs)...")
    r = requests.post(f"{API}/api/validation/summarizer-ab/run",
                       json={"dataset_id": ds, "summarizer": summarizer, "num_pairs": n},
                       headers=HEADERS, timeout=10)
    print(f"  {r.json()}")
    result = wait()
    print(f"  Done: {result.get('done','?')}/{result.get('total','?')}")

print("\nAll runs complete!")
