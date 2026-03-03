#!/usr/bin/env python3
"""Phase 2: Run multimodel on GPT/Gemini SUMMARIZER modes.
This fills in Opus 4.5/4.6 as judges on pairs that currently only have GPT/Gemini judge verdicts.
Run after run_multimodel_batch.py completes.
"""
import asyncio
import httpx

API_URL = "https://paper-scoring-hub.preview.emergentagent.com"
DATASETS = ["iclr-llm", "iclr-codegen", "iclr-pdes", "iclr-ot", "iclr-fairness", "iclr-protein", "iclr-molecules", "iclr-optimization"]
MODES = ["abstract_plus_summary:gpt_summary", "abstract_plus_summary:gemini_summary"]
MAX_PAIRS = 500

async def get_token():
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API_URL}/api/admin/login", json={"password": "papersumo2025"})
        return r.json()["token"]

async def wait_idle(ds):
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            try:
                r = await c.get(f"{API_URL}/api/validation/status", params={"dataset_id": ds})
                if not r.json().get("tournament_progress", {}).get("running", False):
                    return
            except:
                pass
            await asyncio.sleep(10)

async def run_one(token, ds, mode):
    headers = {"X-Admin-Token": token, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.post(f"{API_URL}/api/validation/run-multimodel", headers=headers,
                             json={"dataset_id": ds, "parallel": 30, "max_pairs": MAX_PAIRS, "content_mode": mode})
            status = r.json().get("status")
            if status == "started":
                print(f"  {ds} ({mode.split(':')[1]}): started", flush=True)
            else:
                print(f"  {ds} ({mode.split(':')[1]}): {status}", flush=True)
                return
        except Exception as e:
            print(f"  {ds}: error: {e}", flush=True)
            return
    
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            await asyncio.sleep(15)
            try:
                r = await c.get(f"{API_URL}/api/validation/status", params={"dataset_id": ds})
                tp = r.json().get("tournament_progress", {})
                done = tp.get("completed_matches", 0)
                total = tp.get("total_matches", 0)
                print(f"  {ds} ({mode.split(':')[1]}): {done}/{total}", flush=True)
                if not tp.get("running", False):
                    return
            except:
                pass

async def main():
    token = await get_token()
    print("Phase 2: Multimodel on GPT/Gemini summarizer modes", flush=True)
    
    for mode in MODES:
        print(f"\n=== Mode: {mode} ===", flush=True)
        for ds in DATASETS:
            await wait_idle(ds)
            await run_one(token, ds, mode)
    
    print("\n=== PHASE 2 COMPLETE ===", flush=True)

asyncio.run(main())
