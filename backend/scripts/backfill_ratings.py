"""Backfill ai_rating for papers that have Claude summary but no parsed rating.

These papers were summarized with an older prompt that didn't include JSON scores.
Regenerates the summary with the current prompt (which requires JSON ratings).
"""
import asyncio, os, sys, time
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')

from core.config import db
from services.llm import generate_precomparison_impact_summary, parse_ratings_from_summary
from datetime import datetime, timezone

MODEL_INFO = {
    "provider": "anthropic",
    "model": "claude-opus-4-6",
    "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}},
}
PARALLEL = 10

async def run():
    missing = []
    async for doc in db.papers.find(
        {"summaries.anthropic:claude-opus-4-6:thinking": {"$exists": True},
         "ai_rating": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "categories": 1}
    ):
        missing.append(doc)

    total = len(missing)
    print(f"Backfilling ratings for {total} papers ({PARALLEL}x parallel)", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    fixed = 0
    failed = 0
    t0 = time.time()

    async def fix_one(doc):
        nonlocal fixed, failed
        async with sem:
            try:
                result = await generate_precomparison_impact_summary(doc, model_override=MODEL_INFO)
                if result and result.get("summary"):
                    ratings = parse_ratings_from_summary(result["summary"])
                    if ratings:
                        await db.papers.update_one({"id": doc["id"]}, {"$set": {
                            "summaries.anthropic:claude-opus-4-6:thinking": result["summary"],
                            "summary_dates.anthropic:claude-opus-4-6:thinking": datetime.now(timezone.utc).isoformat(),
                            "ai_rating": ratings["score"],
                            "ai_ratings_by_model.claude": ratings,
                        }})
                        fixed += 1
                    else:
                        failed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  Error: {doc['title'][:40]}: {str(e)[:80]}", flush=True)

            done = fixed + failed
            if done % 20 == 0 or done == total:
                elapsed = time.time() - t0
                print(f"  [{done}/{total}] {fixed} fixed, {failed} failed ({elapsed:.0f}s)", flush=True)

    await asyncio.gather(*[fix_one(doc) for doc in missing])
    print(f"\nDone in {time.time()-t0:.0f}s: {fixed} fixed, {failed} failed", flush=True)

asyncio.run(run())
