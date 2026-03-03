#!/usr/bin/env python3
"""Run multimodel tournaments sequentially for all ICLR datasets."""
import asyncio
import httpx
import time

API_URL = "https://paper-scoring-hub.preview.emergentagent.com"
DATASETS = ["iclr-codegen", "iclr-pdes", "iclr-ot", "iclr-fairness", "iclr-protein", "iclr-molecules", "iclr-optimization"]
MAX_PAIRS = 500

async def get_token():
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API_URL}/api/admin/login", json={"password": "papersumo2025"})
        return r.json()["token"]

async def wait_for_dataset(ds):
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            try:
                r = await c.get(f"{API_URL}/api/validation/status", params={"dataset_id": ds})
                tp = r.json().get("tournament_progress", {})
                done = tp.get("completed_matches", 0)
                total = tp.get("total_matches", 0)
                running = tp.get("running", False)
                print(f"  {ds}: {done}/{total}", flush=True)
                if not running:
                    return
            except Exception as e:
                print(f"  {ds}: poll error: {e}", flush=True)
            await asyncio.sleep(15)

async def run_dataset(token, ds):
    headers = {"X-Admin-Token": token, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.post(f"{API_URL}/api/validation/run-multimodel", headers=headers,
                             json={"dataset_id": ds, "parallel": 30, "max_pairs": MAX_PAIRS, "content_mode": "abstract_plus_summary"})
            status = r.json().get("status")
            if status != "started":
                print(f"  {ds}: {status}", flush=True)
                if status == "already_running":
                    await wait_for_dataset(ds)
                return
        except Exception as e:
            print(f"  {ds}: start error: {e}", flush=True)
            return
    await wait_for_dataset(ds)

async def main():
    token = await get_token()
    print(f"Token acquired", flush=True)
    
    # Wait for iclr-llm (already running)
    print("Waiting for iclr-llm...", flush=True)
    await wait_for_dataset("iclr-llm")
    
    for ds in DATASETS:
        print(f"\n>>> {ds}", flush=True)
        await run_dataset(token, ds)
    
    print("\n=== ALL COMPLETE ===", flush=True)

asyncio.run(main())
