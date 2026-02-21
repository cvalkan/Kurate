#!/usr/bin/env python3
"""Generate missing Opus 4.6 summary and replay tournament for elife-cancer."""
import asyncio, os, sys, uuid, time
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model
from core.config import logger

DS = "elife-cancer"
FIELD = "ai_impact_summary_opus46"
SOURCE = "abstract_plus_summary"
TARGET = "abstract_plus_summary:opus46"
MAX_PER_PAPER = 15
PARALLEL = 8

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]

async def phase1():
    papers = await db.validation_papers.find({"dataset_id": DS}, {"_id": 0}).to_list(5000)
    missing = [p for p in papers if not p.get(FIELD)]
    print(f"Phase 1: {len(missing)} papers need opus46 summaries")
    for p in missing:
        model_info = {"provider": "anthropic", "model": "claude-opus-4-6"}
        result = await generate_precomparison_impact_summary(p, model_override=model_info)
        if result and result.get("summary"):
            await db.validation_papers.update_one(
                {"dataset_id": DS, "id": p["id"]},
                {"$set": {FIELD: result["summary"]}}
            )
            print(f"  Generated: {p.get('title','')[:60]}")
        else:
            print(f"  FAILED: {p.get('title','')[:60]}")
    print("Phase 1 done")

async def phase2():
    source_matches = await db.validation_matches.find(
        {"dataset_id": DS, "content_mode": SOURCE, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "model_key": 1}
    ).to_list(100000)
    print(f"\nPhase 2: {len(source_matches)} source matches")

    existing = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": DS, "content_mode": TARGET, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        existing.add((doc["paper1_id"], doc["paper2_id"]))

    papers = await db.validation_papers.find({"dataset_id": DS}, {"_id": 0, "id": 1}).to_list(5000)
    match_counts = {p["id"]: 0 for p in papers}
    for (p1, p2) in existing:
        match_counts[p1] = match_counts.get(p1, 0) + 1
        match_counts[p2] = match_counts.get(p2, 0) + 1

    to_replay = []
    for m in source_matches:
        pair = (m["paper1_id"], m["paper2_id"])
        if pair in existing or (pair[1], pair[0]) in existing:
            continue
        if match_counts.get(m["paper1_id"], 0) >= MAX_PER_PAPER * 2:
            continue
        if match_counts.get(m["paper2_id"], 0) >= MAX_PER_PAPER * 2:
            continue
        to_replay.append({"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"]})
        match_counts[m["paper1_id"]] = match_counts.get(m["paper1_id"], 0) + 1
        match_counts[m["paper2_id"]] = match_counts.get(m["paper2_id"], 0) + 1

    print(f"To replay: {len(to_replay)} matches (max {MAX_PER_PAPER}/paper)")

    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    start = time.time()

    async def run_one(mi):
        nonlocal completed, failed
        async with sem:
            p1 = await db.validation_papers.find_one({"dataset_id": DS, "id": mi["paper1_id"]}, {"_id": 0})
            p2 = await db.validation_papers.find_one({"dataset_id": DS, "id": mi["paper2_id"]}, {"_id": 0})
            if not p1 or not p2:
                failed += 1; return
            s1, s2 = p1.get(FIELD, ""), p2.get(FIELD, "")
            if not s1 or not s2:
                failed += 1; return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            try:
                result = await compare_papers(p1c, p2c, content_mode="abstract_plus_summary", model_override=judge)
                if result and not result.get("failed"):
                    winner_key = result.get("winner", "paper1")
                    result["id"] = str(uuid.uuid4())
                    result["dataset_id"] = DS
                    result["content_mode"] = TARGET
                    result["paper1_id"] = mi["paper1_id"]
                    result["paper2_id"] = mi["paper2_id"]
                    result["winner_id"] = mi["paper1_id"] if winner_key == "paper1" else mi["paper2_id"]
                    result["completed"] = True
                    result["failed"] = False
                    result["replayed_from"] = SOURCE
                    result["pinned_judge"] = str(judge)
                    result.pop("_id", None)
                    await db.validation_matches.insert_one(result)
                    completed += 1
                    if completed % 25 == 0:
                        elapsed = time.time() - start
                        print(f"  Progress: {completed}/{len(to_replay)} ({completed/elapsed*60:.0f}/min)")
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"  Error: {e}")

    await asyncio.gather(*[run_one(m) for m in to_replay], return_exceptions=True)
    elapsed = time.time() - start
    print(f"\nPhase 2 done: {completed}/{len(to_replay)} ({failed} failed) in {elapsed:.0f}s")

async def verify():
    s = await db.validation_matches.count_documents({"dataset_id": DS, "content_mode": SOURCE, "completed": True})
    t = await db.validation_matches.count_documents({"dataset_id": DS, "content_mode": TARGET, "completed": True})
    w = await db.validation_papers.count_documents({"dataset_id": DS, FIELD: {"$exists": True, "$ne": ""}})
    tot = await db.validation_papers.count_documents({"dataset_id": DS})
    print(f"\n=== Verification ===")
    print(f"Papers with opus46 summary: {w}/{tot}")
    print(f"Source matches: {s}")
    print(f"Target matches: {t}")

async def main():
    print(f"=== Opus 4.6 for {DS} ===")
    await phase1()
    await phase2()
    await verify()
    client.close()

asyncio.run(main())
