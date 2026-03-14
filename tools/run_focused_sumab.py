#!/usr/bin/env python3
"""Focused run: finish GPT codegen, then Gemini for llm + codegen only."""
import requests, time

API = "https://kurate-bookmarks.preview.emergentagent.com"
TOKEN = "adm_PwgAikZRN0yUbPwU72rgzilv_OTqJYv5pMFHYptbW98"
H = {"Content-Type": "application/json", "X-Admin-Token": TOKEN}

def wait():
    while True:
        try:
            s = requests.get(f"{API}/api/validation/summarizer-ab/status", timeout=10).json()
            if not s.get("running"): return s
            print(f"  [{s.get('dataset_id')}/{s.get('summarizer')}] {s.get('phase','?')}: {s['done']}/{s['total']}", flush=True)
        except Exception as e:
            print(f"  err: {e}", flush=True)
        time.sleep(30)

# 1. Wait for iclr-codegen/gpt to finish (already running)
print("Waiting for iclr-codegen/gpt to finish...")
wait()
print("Done!\n")

# 2. Gemini for iclr-llm
print("Starting iclr-llm/gemini...")
r = requests.post(f"{API}/api/validation/summarizer-ab/run", json={"dataset_id": "iclr-llm", "summarizer": "gemini", "num_pairs": 300}, headers=H, timeout=10)
print(f"  {r.json()}")
wait()
print("Done!\n")

# 3. Gemini for iclr-codegen
print("Starting iclr-codegen/gemini...")
r = requests.post(f"{API}/api/validation/summarizer-ab/run", json={"dataset_id": "iclr-codegen", "summarizer": "gemini", "num_pairs": 300}, headers=H, timeout=10)
print(f"  {r.json()}")
wait()
print("All done!")
