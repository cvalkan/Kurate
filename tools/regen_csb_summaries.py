#!/usr/bin/env python3
"""Re-generate missing summaries for elife-comp-sys-bio with Opus 4.6 Thinking + full text."""
import asyncio, sys
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary

DATASET = "elife-comp-sys-bio"
MODEL = {"provider": "anthropic", "model": "claude-opus-4-6", "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}}

client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["test_database"]

async def main():
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    
    # Only papers that need summaries AND have full text
    missing = [p for p in papers if not p.get("ai_impact_summary") and p.get("full_text")]
    no_text = [p for p in papers if not p.get("ai_impact_summary") and not p.get("full_text")]
    
    print(f"Total: {len(papers)}, need summary: {len(missing)}, no full text: {len(no_text)}", flush=True)
    if no_text:
        print(f"WARNING: {len(no_text)} papers have no full text — skipping", flush=True)
    
    sem = asyncio.Semaphore(3)
    done = 0
    
    async def gen(p):
        nonlocal done
        async with sem:
            # Verify full text is present
            if not p.get("full_text"):
                print(f"  SKIP {p['id'][:8]}: no full text", flush=True)
                return
            r = await generate_precomparison_impact_summary(p, model_override=MODEL)
            if r and r.get("summary"):
                await db.validation_papers.update_one(
                    {"dataset_id": DATASET, "id": p["id"]},
                    {"$set": {
                        "ai_impact_summary": r["summary"],
                        "ai_impact_summary_thinking": r["summary"],
                        "ai_impact_summary_model": "claude-opus-4-6-thinking",
                    }}
                )
                done += 1
                if done % 5 == 0:
                    print(f"  {done}/{len(missing)}", flush=True)
    
    await asyncio.gather(*[gen(p) for p in missing], return_exceptions=True)
    
    # Final verification
    ok = 0
    async for p in db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0, "ai_impact_summary_model": 1, "full_text": 1, "ai_impact_summary": 1}):
        if p.get("ai_impact_summary") and p.get("ai_impact_summary_model") == "claude-opus-4-6-thinking":
            ok += 1
    
    print(f"\nFinal: {ok}/80 papers have Opus 4.6 Thinking summaries based on full text")
    client.close()

asyncio.run(main())
