#!/usr/bin/env python3
"""Run more opus46 and thinking matches for elife-cancer to reach 20 avg/paper."""
import asyncio, sys, os, uuid, time, random, itertools
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import compare_papers, _pick_round_robin_model
from routers.validation_utils import build_paper_gt_scores
from datetime import datetime, timezone

DATASET = "elife-cancer"
MAX_PER_PAPER = 20
PARALLEL = 8

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]


async def run_matches(summary_field, content_mode, label, target_total):
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    pids = {p["id"] for p in papers if p.get(summary_field)}
    gt = build_paper_gt_scores(papers)

    existing = set()
    from collections import Counter
    mc = Counter()
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": content_mode, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        existing.add(pk)
        mc[m["paper1_id"]] += 1
        mc[m["paper2_id"]] += 1

    current = len(existing)
    need = max(target_total - current, 0)
    if need == 0:
        print(f"  [{label}] Already at {current} matches, target {target_total}", flush=True)
        return

    to_run = []
    for a, b in itertools.combinations(list(pids), 2):
        if len(to_run) >= need:
            break
        if a not in gt or b not in gt or gt[a] == gt[b]:
            continue
        pk = tuple(sorted([a, b]))
        if pk in existing:
            continue
        if mc[a] >= MAX_PER_PAPER * 2 or mc[b] >= MAX_PER_PAPER * 2:
            continue
        to_run.append((a, b))
        mc[a] += 1
        mc[b] += 1

    random.shuffle(to_run)
    print(f"  [{label}] Running {len(to_run)} new matches (current: {current}, target: {target_total})", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    start = time.time()

    async def run_one(p1_id, p2_id):
        nonlocal completed
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get(summary_field, ""), p2.get(summary_field, "")
            if not s1 or not s2:
                return
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
                    if completed % 100 == 0:
                        print(f"  [{label}] {completed}/{len(to_run)} ({completed/(time.time()-start)*60:.0f}/min)", flush=True)
            except:
                pass

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    total = current + completed
    print(f"  [{label}] Done: +{completed} = {total} total ({total/80:.1f} avg/paper) in {time.time()-start:.0f}s", flush=True)


async def main():
    target = 80 * MAX_PER_PAPER  # 1600

    print("=== Phase 1: Opus 4.6 matches ===", flush=True)
    await run_matches("ai_impact_summary_opus46", "abstract_plus_summary:opus46", "Opus 4.6", target)

    print("\n=== Phase 2: Thinking matches (replay opus46 pairs) ===", flush=True)
    # For thinking, replay opus46 pairs for fair comparison
    papers = await db.validation_papers.find({"dataset_id": DATASET}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}

    existing_th = set()
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": "abstract_plus_summary:thinking", "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing_th.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    o46_pairs = []
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET, "content_mode": "abstract_plus_summary:opus46", "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk not in existing_th:
            o46_pairs.append((m["paper1_id"], m["paper2_id"]))
            existing_th.add(pk)

    print(f"  [Thinking] Replaying {len(o46_pairs)} opus46 pairs", flush=True)
    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    start = time.time()

    async def run_th(p1_id, p2_id):
        nonlocal completed
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get("ai_impact_summary_thinking", ""), p2.get("ai_impact_summary_thinking", "")
            if not s1 or not s2:
                return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            try:
                result = await compare_papers(p1c, p2c, content_mode="abstract_plus_summary", model_override=judge)
                if result and not result.get("failed"):
                    wk = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()), "dataset_id": DATASET,
                        "content_mode": "abstract_plus_summary:thinking",
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
                    if completed % 100 == 0:
                        print(f"  [Thinking] {completed}/{len(o46_pairs)} ({completed/(time.time()-start)*60:.0f}/min)", flush=True)
            except:
                pass

    await asyncio.gather(*[run_th(a, b) for a, b in o46_pairs], return_exceptions=True)
    print(f"  [Thinking] Done: +{completed} in {time.time()-start:.0f}s", flush=True)

    # Final counts
    for mode in ["abstract_plus_summary:opus46", "abstract_plus_summary:thinking"]:
        n = await db.validation_matches.count_documents({"dataset_id": DATASET, "content_mode": mode, "completed": True})
        print(f"  {mode}: {n} matches ({n/80:.1f} avg/paper)")
    client.close()

asyncio.run(main())
