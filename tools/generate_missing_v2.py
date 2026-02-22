#!/usr/bin/env python3
"""Generate missing AI summaries — respects fallback keys (won't re-generate Opus 4.6 for papers with 4.5)."""
import asyncio, os, sys, time
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary
from services.scheduler import _summary_model_key, _get_paper_summary
from core.config import TOURNAMENT_MODELS

PARALLEL = 5
client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]

async def main():
    papers = await db.papers.find({}, {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "summaries": 1}).to_list(5000)
    
    work = []
    for p in papers:
        for model_info in TOURNAMENT_MODELS:
            mk = _summary_model_key(model_info)
            # _get_paper_summary checks the key AND fallbacks (e.g., 4.5 for 4.6)
            if not _get_paper_summary(p, mk):
                work.append((p, model_info, mk))
    
    print(f"Papers: {len(papers)}, truly missing summaries: {len(work)}")
    if not work:
        print("All papers have summaries (including fallbacks)!")
        return
    
    # Show breakdown
    from collections import Counter
    by_key = Counter(mk for _, _, mk in work)
    for k, v in by_key.most_common():
        print(f"  {k}: {v} missing")
    
    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    start = time.time()
    
    async def gen_one(paper, model_info, mk):
        nonlocal completed, failed
        async with sem:
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=model_info)
                if result and result.get("summary") and len(str(result["summary"])) > 50:
                    summary_val = str(result["summary"])
                    await db.papers.update_one(
                        {"id": paper["id"]},
                        {"$set": {f"summaries.{mk}": summary_val}}
                    )
                    completed += 1
                    if completed % 10 == 0:
                        el = time.time() - start
                        print(f"  {completed}/{len(work)} ({completed/el*60:.0f}/min)")
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"  FAILED: {paper.get('title','')[:40]} [{mk}]: {e}")
    
    await asyncio.gather(*[gen_one(p, mi, mk) for p, mi, mk in work], return_exceptions=True)
    el = time.time() - start
    print(f"\nDone: {completed}/{len(work)} generated, {failed} failed, {el:.0f}s")
    client.close()

asyncio.run(main())
