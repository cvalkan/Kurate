#!/usr/bin/env python3
"""Generate Opus 4.6 + Thinking summaries and run tournaments for elife-comp-sys-bio."""
import asyncio, os, sys, uuid, time, random, itertools
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model
from routers.validation_utils import build_paper_gt_scores
from datetime import datetime, timezone

DATASET = "elife-comp-sys-bio"
O46_FIELD = "ai_impact_summary_opus46"
TH_FIELD = "ai_impact_summary_thinking"
O46_MODE = "abstract_plus_summary:opus46"
TH_MODE = "abstract_plus_summary:thinking"
O46_MODEL = {"provider": "anthropic", "model": "claude-opus-4-6"}
TH_MODEL = {"provider": "anthropic", "model": "claude-opus-4-6", "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}}
MAX_PER_PAPER = 15
PARALLEL_GEN = 3
PARALLEL_MATCH = 8

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]


async def wait_for_base_summaries():
    """Wait for Opus 4.5 summaries to finish (triggered via API)."""
    while True:
        n = await db.validation_papers.count_documents({"dataset_id": DATASET, "ai_impact_summary": {"$exists": True, "$ne": ""}})
        total = await db.validation_papers.count_documents({"dataset_id": DATASET})
        print(f"  Waiting for base summaries: {n}/{total}", flush=True)
        if n >= total * 0.9:
            break
        await asyncio.sleep(30)


async def generate_summaries(field, model, label):
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    missing = [p for p in papers if not p.get(field)]
    if not missing:
        print(f"  All {len(papers)} papers have {label} summaries", flush=True)
        return
    print(f"  Generating {len(missing)} {label} summaries...", flush=True)
    sem = asyncio.Semaphore(PARALLEL_GEN)
    done = 0

    async def gen(p):
        nonlocal done
        async with sem:
            r = await generate_precomparison_impact_summary(p, model_override=model)
            if r and r.get("summary"):
                await db.validation_papers.update_one(
                    {"dataset_id": DATASET, "id": p["id"]},
                    {"$set": {field: r["summary"]}},
                )
                done += 1
                if done % 10 == 0:
                    print(f"  {label}: {done}/{len(missing)}", flush=True)

    await asyncio.gather(*[gen(p) for p in missing], return_exceptions=True)
    print(f"  {label}: {done}/{len(missing)} done", flush=True)


async def run_matches(summary_field, content_mode, label):
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    pids = {p["id"] for p in papers if p.get(summary_field)}
    gt = build_paper_gt_scores(papers)

    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": content_mode, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    from collections import Counter
    mc = Counter()
    for pk in existing:
        mc[pk[0]] += 1; mc[pk[1]] += 1

    to_run = []
    for a, b in itertools.combinations(list(pids), 2):
        if a not in gt or b not in gt or gt[a] == gt[b]: continue
        pk = tuple(sorted([a, b]))
        if pk in existing: continue
        if mc[a] >= MAX_PER_PAPER * 2 or mc[b] >= MAX_PER_PAPER * 2: continue
        to_run.append((a, b))
        mc[a] += 1; mc[b] += 1

    random.shuffle(to_run)
    print(f"  {label}: {len(to_run)} cross-tier pairs (existing: {len(existing)})", flush=True)
    if not to_run: return

    sem = asyncio.Semaphore(PARALLEL_MATCH)
    completed = 0
    start = time.time()

    async def run_one(p1_id, p2_id):
        nonlocal completed
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get(summary_field, ""), p2.get(summary_field, "")
            if not s1 or not s2: return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            try:
                result = await compare_papers(p1c, p2c, content_mode="abstract_plus_summary", model_override=judge)
                if result and not result.get("failed"):
                    wk = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()), "dataset_id": DATASET, "content_mode": content_mode,
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
                        print(f"  {label}: {completed}/{len(to_run)} ({completed/(time.time()-start)*60:.0f}/min)", flush=True)
            except: pass

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    print(f"  {label}: done {completed}/{len(to_run)} in {time.time()-start:.0f}s", flush=True)


async def main():
    print("=== Phase 0: Wait for base summaries ===", flush=True)
    await wait_for_base_summaries()

    print("\n=== Phase 1: Opus 4.6 summaries ===", flush=True)
    await generate_summaries(O46_FIELD, O46_MODEL, "Opus 4.6")

    print("\n=== Phase 2: Thinking summaries ===", flush=True)
    await generate_summaries(TH_FIELD, TH_MODEL, "Thinking")

    print("\n=== Phase 3: Opus 4.6 tournament ===", flush=True)
    await run_matches(O46_FIELD, O46_MODE, "Opus 4.6")

    print("\n=== Phase 4: Replay as Thinking tournament ===", flush=True)
    # Replay opus46 pairs with thinking summaries
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}

    existing_th = set()
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": TH_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing_th.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    o46_pairs = []
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": O46_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk not in existing_th:
            o46_pairs.append((m["paper1_id"], m["paper2_id"]))
            existing_th.add(pk)

    print(f"  Replaying {len(o46_pairs)} opus46 pairs with thinking summaries", flush=True)
    sem = asyncio.Semaphore(PARALLEL_MATCH)
    completed = 0
    start = time.time()

    async def run_th(p1_id, p2_id):
        nonlocal completed
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get(TH_FIELD, ""), p2.get(TH_FIELD, "")
            if not s1 or not s2: return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            try:
                result = await compare_papers(p1c, p2c, content_mode="abstract_plus_summary", model_override=judge)
                if result and not result.get("failed"):
                    wk = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()), "dataset_id": DATASET, "content_mode": TH_MODE,
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
                        print(f"  Thinking: {completed}/{len(o46_pairs)} ({completed/(time.time()-start)*60:.0f}/min)", flush=True)
            except: pass

    await asyncio.gather(*[run_th(a, b) for a, b in o46_pairs], return_exceptions=True)
    print(f"  Thinking: done {completed}/{len(o46_pairs)} in {time.time()-start:.0f}s", flush=True)

    # Final counts
    for mode in [O46_MODE, TH_MODE, "abstract_plus_summary"]:
        n = await db.validation_matches.count_documents({"dataset_id": DATASET, "content_mode": mode, "completed": True})
        print(f"  {mode}: {n} matches")
    client.close()

asyncio.run(main())
