#!/usr/bin/env python3
"""Run extended thinking experiment on all remaining ICLR datasets."""
import asyncio, os, sys, uuid, time, random, itertools
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model
from routers.validation_utils import build_expert_ratings, build_expert_majority
from datetime import datetime, timezone

THINKING_FIELD = "ai_impact_summary_thinking"
THINKING_MODE = "abstract_plus_summary:thinking"
THINKING_MODEL = {"provider": "anthropic", "model": "claude-opus-4-6", "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}}
PARALLEL_GEN = 3
PARALLEL_MATCH = 8

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]

DATASETS = ["iclr-llm", "iclr-molecules", "iclr-optimization", "iclr-ot", "iclr-pdes", "iclr-protein"]


async def generate_summaries(ds):
    papers = await db.validation_papers.find({"dataset_id": ds}, {"_id": 0}).to_list(5000)
    missing = [p for p in papers if not p.get(THINKING_FIELD)]
    if not missing:
        print(f"  [{ds}] All {len(papers)} papers have thinking summaries")
        return
    print(f"  [{ds}] Generating {len(missing)} thinking summaries...")
    sem = asyncio.Semaphore(PARALLEL_GEN)
    done = 0

    async def gen(p):
        nonlocal done
        async with sem:
            r = await generate_precomparison_impact_summary(p, model_override=THINKING_MODEL)
            if r and r.get("summary"):
                await db.validation_papers.update_one(
                    {"dataset_id": ds, "id": p["id"]},
                    {"$set": {THINKING_FIELD: r["summary"]}},
                )
                done += 1
                if done % 10 == 0:
                    print(f"  [{ds}] Generated {done}/{len(missing)}", flush=True)

    await asyncio.gather(*[gen(p) for p in missing], return_exceptions=True)
    print(f"  [{ds}] Generated {done}/{len(missing)} summaries")


async def run_tournament(ds):
    papers = await db.validation_papers.find({"dataset_id": ds}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    pids_with_thinking = {p["id"] for p in papers if p.get(THINKING_FIELD)}

    # Get existing thinking pairs
    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": ds, "content_mode": THINKING_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Build GT for cross-tier filtering
    from routers.validation_utils import build_paper_gt_scores
    gt = build_paper_gt_scores(papers)

    # Replay opus46 cross-tier pairs
    to_replay = []
    async for m in db.validation_matches.find(
        {"dataset_id": ds, "content_mode": "abstract_plus_summary:opus46", "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk in existing:
            continue
        if m["paper1_id"] not in pids_with_thinking or m["paper2_id"] not in pids_with_thinking:
            continue
        g1, g2 = gt.get(m["paper1_id"]), gt.get(m["paper2_id"])
        if g1 is None or g2 is None or g1 == g2:
            continue
        to_replay.append((m["paper1_id"], m["paper2_id"]))
        existing.add(pk)

    print(f"  [{ds}] Replaying {len(to_replay)} opus46 cross-tier pairs")
    if not to_replay:
        return

    sem = asyncio.Semaphore(PARALLEL_MATCH)
    completed = 0
    failed = 0
    start = time.time()

    async def run_one(p1_id, p2_id):
        nonlocal completed, failed
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get(THINKING_FIELD, ""), p2.get(THINKING_FIELD, "")
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
                        "dataset_id": ds,
                        "content_mode": THINKING_MODE,
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
                        print(f"  [{ds}] {completed}/{len(to_replay)} ({completed/el*60:.0f}/min)", flush=True)
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  [{ds}] Error: {e}", flush=True)

    await asyncio.gather(*[run_one(a, b) for a, b in to_replay], return_exceptions=True)
    el = time.time() - start
    print(f"  [{ds}] Done: {completed}/{len(to_replay)} ({failed} failed) in {el:.0f}s")


async def main():
    for ds in DATASETS:
        print(f"\n=== {ds} ===", flush=True)
        await generate_summaries(ds)
        await run_tournament(ds)

    print("\n=== FINAL COUNTS ===")
    for ds in DATASETS:
        n = await db.validation_matches.count_documents(
            {"dataset_id": ds, "content_mode": THINKING_MODE, "completed": True}
        )
        print(f"  {ds}: {n} thinking matches")
    client.close()

asyncio.run(main())
