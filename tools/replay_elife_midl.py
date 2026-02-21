#!/usr/bin/env python3
"""Generate missing Opus 4.6 summaries and replay tournaments for multiple datasets."""
import asyncio, os, sys, uuid, time
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model
from core.config import logger

DATASETS = ["elife-microbiology", "elife-neuro-100", "midl-medical-imaging"]
FIELD = "ai_impact_summary_opus46"
SOURCE = "abstract_plus_summary"
TARGET = "abstract_plus_summary:opus46"
MAX_PER_PAPER = 15
PARALLEL = 8

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]

async def generate_summaries(ds):
    papers = await db.validation_papers.find({"dataset_id": ds}, {"_id": 0}).to_list(5000)
    missing = [p for p in papers if not p.get(FIELD)]
    if not missing:
        print(f"  [{ds}] All {len(papers)} papers have opus46 summaries")
        return
    print(f"  [{ds}] Generating {len(missing)} missing summaries...")
    sem = asyncio.Semaphore(3)
    done = 0
    async def gen(p):
        nonlocal done
        async with sem:
            r = await generate_precomparison_impact_summary(p, model_override={"provider": "anthropic", "model": "claude-opus-4-6"})
            if r and r.get("summary"):
                await db.validation_papers.update_one({"dataset_id": ds, "id": p["id"]}, {"$set": {FIELD: r["summary"]}})
                done += 1
    await asyncio.gather(*[gen(p) for p in missing], return_exceptions=True)
    print(f"  [{ds}] Generated {done}/{len(missing)} summaries")

async def replay(ds):
    source_matches = await db.validation_matches.find(
        {"dataset_id": ds, "content_mode": SOURCE, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ).to_list(100000)

    existing = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": ds, "content_mode": TARGET, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        existing.add((doc["paper1_id"], doc["paper2_id"]))

    papers = await db.validation_papers.find({"dataset_id": ds}, {"_id": 0, "id": 1}).to_list(5000)
    mc = {p["id"]: 0 for p in papers}
    for (p1, p2) in existing:
        mc[p1] = mc.get(p1, 0) + 1
        mc[p2] = mc.get(p2, 0) + 1

    to_replay = []
    for m in source_matches:
        pair = (m["paper1_id"], m["paper2_id"])
        if pair in existing or (pair[1], pair[0]) in existing:
            continue
        if mc.get(m["paper1_id"], 0) >= MAX_PER_PAPER * 2:
            continue
        if mc.get(m["paper2_id"], 0) >= MAX_PER_PAPER * 2:
            continue
        to_replay.append({"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"]})
        mc[m["paper1_id"]] = mc.get(m["paper1_id"], 0) + 1
        mc[m["paper2_id"]] = mc.get(m["paper2_id"], 0) + 1

    print(f"  [{ds}] {len(source_matches)} source, {len(existing)} existing, {len(to_replay)} to replay")
    if not to_replay:
        return

    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    start = time.time()

    async def run_one(mi):
        nonlocal completed, failed
        async with sem:
            p1 = await db.validation_papers.find_one({"dataset_id": ds, "id": mi["paper1_id"]}, {"_id": 0})
            p2 = await db.validation_papers.find_one({"dataset_id": ds, "id": mi["paper2_id"]}, {"_id": 0})
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
                    wk = result.get("winner", "paper1")
                    result["id"] = str(uuid.uuid4())
                    result["dataset_id"] = ds
                    result["content_mode"] = TARGET
                    result["paper1_id"] = mi["paper1_id"]
                    result["paper2_id"] = mi["paper2_id"]
                    result["winner_id"] = mi["paper1_id"] if wk == "paper1" else mi["paper2_id"]
                    result["completed"] = True
                    result["failed"] = False
                    result["replayed_from"] = SOURCE
                    result["pinned_judge"] = str(judge)
                    result.pop("_id", None)
                    await db.validation_matches.insert_one(result)
                    completed += 1
                    if completed % 50 == 0:
                        el = time.time() - start
                        print(f"  [{ds}] {completed}/{len(to_replay)} ({completed/el*60:.0f}/min)")
                else:
                    failed += 1
            except Exception as e:
                failed += 1

    await asyncio.gather(*[run_one(m) for m in to_replay], return_exceptions=True)
    el = time.time() - start
    print(f"  [{ds}] Done: {completed}/{len(to_replay)} ({failed} failed) in {el:.0f}s")

async def main():
    for ds in DATASETS:
        print(f"\n=== {ds} ===")
        await generate_summaries(ds)
        await replay(ds)

    # Final verification
    print("\n=== FINAL VERIFICATION ===")
    for ds in DATASETS:
        s = await db.validation_matches.count_documents({"dataset_id": ds, "content_mode": SOURCE, "completed": True})
        t = await db.validation_matches.count_documents({"dataset_id": ds, "content_mode": TARGET, "completed": True})
        w = await db.validation_papers.count_documents({"dataset_id": ds, FIELD: {"$exists": True, "$ne": ""}})
        tot = await db.validation_papers.count_documents({"dataset_id": ds})
        print(f"{ds}: papers={w}/{tot}, source={s}, target={t}")
    client.close()

asyncio.run(main())
