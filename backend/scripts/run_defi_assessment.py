"""Generate Claude 4.6 Thinking summaries for unassessed DeFi papers.

Self-contained: reads full_text from defi_papers, writes summary + rating back to defi_papers.
No dependency on the main tournament pipeline.
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
SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
PARALLEL = 10

async def run():
    papers = []
    async for doc in db.defi_papers.find(
        {"group": "blockchain_ai_agents",
         "full_text": {"$exists": True, "$ne": None, "$ne": ""},
         f"summaries.{SUMMARY_KEY}": {"$exists": False}},
        {"_id": 1, "title": 1, "abstract": 1, "full_text": 1}
    ):
        papers.append(doc)

    total = len(papers)
    print(f"Generating Claude 4.6 Thinking summaries for {total} DeFi papers ({PARALLEL}x parallel)", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    generated = 0
    failed = 0
    t0 = time.time()

    async def gen_one(doc):
        nonlocal generated, failed
        async with sem:
            paper = {
                "title": doc.get("title", ""),
                "abstract": doc.get("abstract", ""),
                "full_text": doc["full_text"],
                "categories": ["defi"],
            }
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=MODEL_INFO)
                if result and result.get("summary") and len(result["summary"]) > 50:
                    update = {
                        f"summaries.{SUMMARY_KEY}": result["summary"],
                        f"summary_dates.{SUMMARY_KEY}": datetime.now(timezone.utc).isoformat(),
                    }
                    if result.get("tokens"):
                        update[f"summary_tokens.{SUMMARY_KEY}"] = result["tokens"]
                    ratings = parse_ratings_from_summary(result["summary"])
                    if ratings:
                        update["ai_rating"] = ratings["score"]
                        update["summary_scores"] = ratings
                    await db.defi_papers.update_one({"_id": doc["_id"]}, {"$set": update})
                    generated += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  Error: {doc['title'][:50]}: {str(e)[:100]}", flush=True)

            done = generated + failed
            if done % 10 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {generated} ok, {failed} fail (ETA {eta:.0f}s)", flush=True)

    await asyncio.gather(*[gen_one(p) for p in papers])

    elapsed = time.time() - t0
    assessed = await db.defi_papers.count_documents({"group": "blockchain_ai_agents", "ai_rating": {"$exists": True}})
    print(f"\nDone in {elapsed:.0f}s: {generated} generated, {failed} failed")
    print(f"Total assessed: {assessed}/237", flush=True)

asyncio.run(run())
