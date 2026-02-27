#!/usr/bin/env python3
"""Run 500 more cross-tier Opus 4.6 matches for elife-microbiology."""
import asyncio, os, sys, uuid, time, random, itertools
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import compare_papers, _pick_round_robin_model
from datetime import datetime, timezone

DATASET = "elife-microbiology"
FIELD = "ai_impact_summary_opus46"
TARGET = "abstract_plus_summary:opus46"
PARALLEL = 8
MAX_NEW = 500

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]

async def main():
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    pids = list(lookup.keys())

    gt = {}
    for p in papers:
        evals = p.get("evaluations", [])
        ratings = [e["rating_value"] for e in evals if e.get("rating_value")]
        if ratings:
            gt[p["id"]] = sum(ratings) / len(ratings)

    existing = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": TARGET, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([doc["paper1_id"], doc["paper2_id"]])))

    all_ct = [(a, b) for a, b in itertools.combinations(pids, 2)
              if a in gt and b in gt and gt[a] != gt[b]
              and tuple(sorted([a, b])) not in existing]
    random.shuffle(all_ct)
    to_run = all_ct[:MAX_NEW]

    print(f"Available: {len(all_ct)}, existing: {len(existing)}, to run: {len(to_run)}")

    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    start = time.time()

    async def run_one(p1_id, p2_id):
        nonlocal completed, failed
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get(FIELD, ""), p2.get(FIELD, "")
            if not s1 or not s2:
                failed += 1
                return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            try:
                result = await compare_papers(p1c, p2c, content_mode="abstract_plus_summary", model_override=judge)
                if result and not result.get("failed"):
                    wk = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()),
                        "dataset_id": DATASET,
                        "content_mode": TARGET,
                        "paper1_id": p1_id, "paper2_id": p2_id,
                        "winner_id": p1_id if wk == "paper1" else p2_id,
                        "completed": True, "failed": False,
                        "model_used": result.get("model_used", judge),
                        "reasoning": result.get("reasoning", ""),
                        "tokens": result.get("tokens", {}),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await db.validation_matches.insert_one(doc)
                    completed += 1
                    if completed % 50 == 0:
                        el = time.time() - start
                        print(f"  {completed}/{len(to_run)} ({completed/el*60:.0f}/min)", flush=True)
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  Error: {e}", flush=True)

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    el = time.time() - start
    print(f"Done: {completed}/{len(to_run)} ({failed} failed) in {el:.0f}s")

    total = await db.validation_matches.count_documents(
        {"dataset_id": DATASET, "content_mode": TARGET, "completed": True}
    )
    print(f"Total opus46 matches now: {total}")
    client.close()

asyncio.run(main())
