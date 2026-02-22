#!/usr/bin/env python3
"""Generate missing AI Impact Assessments for all 813 leaderboard papers."""
import asyncio, os, sys, time
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary
from services.scheduler import _summary_model_key
from core.config import TOURNAMENT_MODELS, logger

PARALLEL = 5
client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]

async def main():
    papers = await db.papers.find({}, {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "summaries": 1}).to_list(5000)
    
    model_keys = [_summary_model_key(m) for m in TOURNAMENT_MODELS]
    
    # Find papers missing any summary
    work = []  # (paper, model_info, model_key)
    for p in papers:
        existing = p.get("summaries") or {}
        for model_info in TOURNAMENT_MODELS:
            mk = _summary_model_key(model_info)
            if mk not in existing or not isinstance(existing.get(mk), str) or len(existing.get(mk, "")) < 50:
                work.append((p, model_info, mk))
    
    print(f"Papers: {len(papers)}, missing summaries: {len(work)}")
    if not work:
        print("All papers have all 3 summaries!")
        return
    
    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    start = time.time()
    
    async def gen_one(paper, model_info, mk):
        nonlocal completed, failed
        async with sem:
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=model_info)
                if result and result.get("summary") and len(result["summary"]) > 50:
                    await db.papers.update_one(
                        {"id": paper["id"]},
                        {"$set": {f"summaries.{mk}": result["summary"]}}
                    )
                    completed += 1
                    if completed % 10 == 0:
                        el = time.time() - start
                        print(f"  {completed}/{len(work)} ({completed/el*60:.0f}/min)")
                else:
                    failed += 1
                    print(f"  FAILED (no result): {paper.get('title','')[:50]} [{mk}]")
            except Exception as e:
                failed += 1
                print(f"  FAILED: {paper.get('title','')[:50]} [{mk}]: {e}")
    
    await asyncio.gather(*[gen_one(p, mi, mk) for p, mi, mk in work], return_exceptions=True)
    el = time.time() - start
    print(f"\nDone: {completed}/{len(work)} generated, {failed} failed, {el:.0f}s")
    
    # Verify
    after = await db.papers.count_documents({"summaries": {"$exists": True, "$ne": {}}})
    full3 = 0
    async for p in db.papers.find({}, {"_id": 0, "summaries": 1}):
        s = p.get("summaries") or {}
        if len([k for k, v in s.items() if isinstance(v, str) and len(v) > 50]) >= 3:
            full3 += 1
    print(f"\nFinal: {after}/{len(papers)} with summaries, {full3} with all 3 models")
    
    client.close()

asyncio.run(main())
