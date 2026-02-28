#!/usr/bin/env python3
"""Generate Opus 4.6 Thinking summaries as the primary summary for elife-comp-sys-bio."""
import asyncio, sys
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary

DATASET = "elife-comp-sys-bio"
FIELD = "ai_impact_summary"
MODEL = {"provider": "anthropic", "model": "claude-opus-4-6", "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}}

client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["test_database"]

async def main():
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    missing = [p for p in papers if not p.get(FIELD)]
    print(f"Generating {len(missing)} Opus 4.6 Thinking summaries...", flush=True)
    
    sem = asyncio.Semaphore(3)
    done = 0
    
    async def gen(p):
        nonlocal done
        async with sem:
            r = await generate_precomparison_impact_summary(p, model_override=MODEL)
            if r and r.get("summary"):
                await db.validation_papers.update_one(
                    {"dataset_id": DATASET, "id": p["id"]},
                    {"$set": {
                        FIELD: r["summary"],
                        "ai_impact_summary_thinking": r["summary"],
                        "ai_impact_summary_model": "claude-opus-4-6-thinking",
                    }}
                )
                done += 1
                if done % 10 == 0:
                    print(f"  {done}/{len(missing)}", flush=True)
    
    await asyncio.gather(*[gen(p) for p in missing], return_exceptions=True)
    print(f"Done: {done}/{len(missing)}")
    client.close()

asyncio.run(main())
