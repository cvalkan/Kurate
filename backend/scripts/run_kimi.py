import asyncio, os, time
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

import sys
sys.path.insert(0, '/app/backend')

from core.config import db
from services.llm import generate_precomparison_impact_summary, parse_ratings_from_summary
from datetime import datetime, timezone

KIMI_KEY = os.environ["KIMI_API_KEY"]
MODEL_INFO = {
    "provider": "openai",
    "model": "kimi-k2.6",
    "api_key": KIMI_KEY,
    "api_base": "https://api.moonshot.ai/v1",
}
SUMMARY_KEY = "openai:kimi-k2_6"
PARALLEL = 20

async def run():
    paper_ids = []
    async for doc in db.papers.find(
        {"summaries.openai:gpt-5_5": {"$exists": True},
         f"summaries.{SUMMARY_KEY}": {"$exists": False},
         "full_text": {"$ne": None}},
        {"_id": 0, "id": 1}
    ):
        paper_ids.append(doc["id"])

    total = len(paper_ids)
    print(f"Generating Kimi K2.6 summaries for {total} papers ({PARALLEL}x parallel)", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    generated = 0
    failed = 0
    t0 = time.time()

    async def gen_one(paper_id):
        nonlocal generated, failed
        async with sem:
            paper = await db.papers.find_one(
                {"id": paper_id},
                {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "categories": 1}
            )
            if not paper:
                return
            check = await db.papers.find_one({"id": paper_id, f"summaries.{SUMMARY_KEY}": {"$exists": True}}, {"_id": 0, "id": 1})
            if check:
                return
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
                        update["ai_ratings_by_model.kimi"] = ratings
                    await db.papers.update_one({"id": paper_id}, {"$set": update})
                    generated += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  Error: {str(e)[:100]}", flush=True)

            done = generated + failed
            if done % 25 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {generated} ok, {failed} fail ({rate:.1f}/s, ETA {eta:.0f}s)", flush=True)

    tasks = [gen_one(pid) for pid in paper_ids]
    await asyncio.gather(*tasks)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s: {generated} generated, {failed} failed", flush=True)

asyncio.run(run())
