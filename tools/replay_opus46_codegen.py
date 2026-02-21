#!/usr/bin/env python3
"""
Generate Opus 4.6 summaries for iclr-codegen papers and replay the tournament
on the exact same pairs as the Opus 4.5 tournament.
"""
import asyncio
import os
import sys
import uuid
import time

sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model
from core.config import logger

DATASET_ID = "iclr-codegen"
SUMMARY_FIELD = "ai_impact_summary_opus46"
SOURCE_MODE = "abstract_plus_summary"
TARGET_MODE = "abstract_plus_summary:opus46"
PARALLEL_SUMMARIES = 5
PARALLEL_MATCHES = 8
MAX_MATCHES_PER_PAPER = 15

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]


async def phase1_generate_summaries():
    """Generate Opus 4.6 summaries for all papers missing them."""
    papers = await db.validation_papers.find(
        {"dataset_id": DATASET_ID},
        {"_id": 0}
    ).to_list(5000)

    missing = [p for p in papers if not p.get(SUMMARY_FIELD)]
    print(f"Phase 1: {len(missing)}/{len(papers)} papers need Opus 4.6 summaries")

    if not missing:
        print("All papers already have Opus 4.6 summaries!")
        return True

    sem = asyncio.Semaphore(PARALLEL_SUMMARIES)
    completed = 0
    failed = 0

    async def gen_one(paper):
        nonlocal completed, failed
        async with sem:
            try:
                model_info = {"provider": "anthropic", "model": "claude-opus-4-6"}
                result = await generate_precomparison_impact_summary(paper, model_override=model_info)
                if result and result.get("summary"):
                    await db.validation_papers.update_one(
                        {"dataset_id": DATASET_ID, "id": paper["id"]},
                        {"$set": {SUMMARY_FIELD: result["summary"]}},
                    )
                    completed += 1
                    print(f"  Summary {completed}/{len(missing)}: {paper.get('title', '')[:60]}")
                else:
                    failed += 1
                    print(f"  FAILED (no result): {paper.get('title', '')[:60]}")
            except Exception as e:
                failed += 1
                print(f"  FAILED ({e}): {paper.get('title', '')[:60]}")

    tasks = [gen_one(p) for p in missing]
    await asyncio.gather(*tasks, return_exceptions=True)
    print(f"Phase 1 complete: {completed} generated, {failed} failed")
    return failed == 0


async def phase2_replay_tournament():
    """Replay the Opus 4.5 tournament with Opus 4.6 summaries on the same pairs."""
    # Get source matches (Opus 4.5)
    source_matches = await db.validation_matches.find(
        {"dataset_id": DATASET_ID, "content_mode": SOURCE_MODE, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "model_key": 1},
    ).to_list(100000)
    print(f"\nPhase 2: {len(source_matches)} source (Opus 4.5) matches found")

    # Already completed target matches
    existing = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": DATASET_ID, "content_mode": TARGET_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add((doc["paper1_id"], doc["paper2_id"]))
    print(f"Already completed: {len(existing)} target matches")

    # Track per-paper match counts
    papers = await db.validation_papers.find({"dataset_id": DATASET_ID}, {"_id": 0, "id": 1}).to_list(5000)
    match_counts = {p["id"]: 0 for p in papers}
    for (p1, p2) in existing:
        match_counts[p1] = match_counts.get(p1, 0) + 1
        match_counts[p2] = match_counts.get(p2, 0) + 1

    # Filter to replay
    to_replay = []
    for m in source_matches:
        pair = (m["paper1_id"], m["paper2_id"])
        if pair in existing or (pair[1], pair[0]) in existing:
            continue
        if match_counts.get(m["paper1_id"], 0) >= MAX_MATCHES_PER_PAPER * 2:
            continue
        if match_counts.get(m["paper2_id"], 0) >= MAX_MATCHES_PER_PAPER * 2:
            continue
        to_replay.append({"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"]})
        match_counts[m["paper1_id"]] = match_counts.get(m["paper1_id"], 0) + 1
        match_counts[m["paper2_id"]] = match_counts.get(m["paper2_id"], 0) + 1

    print(f"To replay: {to_replay_count} matches" if (to_replay_count := len(to_replay)) else "Nothing to replay!")
    if not to_replay:
        return

    # Verify overlap
    source_pairs = set((m["paper1_id"], m["paper2_id"]) for m in source_matches)
    replay_pairs = set((m["paper1_id"], m["paper2_id"]) for m in to_replay)
    overlap = len(replay_pairs & source_pairs)
    print(f"Pair overlap with source: {overlap}/{len(replay_pairs)} ({overlap/len(replay_pairs)*100:.1f}%)")

    # Run replay
    sem = asyncio.Semaphore(PARALLEL_MATCHES)
    completed = 0
    failed = 0
    start = time.time()

    async def run_one(match_info):
        nonlocal completed, failed
        async with sem:
            p1 = await db.validation_papers.find_one({"dataset_id": DATASET_ID, "id": match_info["paper1_id"]}, {"_id": 0})
            p2 = await db.validation_papers.find_one({"dataset_id": DATASET_ID, "id": match_info["paper2_id"]}, {"_id": 0})
            if not p1 or not p2:
                failed += 1
                return

            p1_sum = p1.get(SUMMARY_FIELD, "")
            p2_sum = p2.get(SUMMARY_FIELD, "")
            if not p1_sum or not p2_sum:
                failed += 1
                print(f"  SKIP (missing summary): {p1.get('title','')[:40]} vs {p2.get('title','')[:40]}")
                return

            p1_copy = {**p1, "ai_impact_summary": p1_sum}
            p2_copy = {**p2, "ai_impact_summary": p2_sum}

            judge_model = _pick_round_robin_model()

            try:
                result = await compare_papers(p1_copy, p2_copy, content_mode="abstract_plus_summary", model_override=judge_model)
                if result and not result.get("failed"):
                    result["id"] = str(uuid.uuid4())
                    result["dataset_id"] = DATASET_ID
                    result["content_mode"] = TARGET_MODE
                    result["paper1_id"] = match_info["paper1_id"]
                    result["paper2_id"] = match_info["paper2_id"]
                    result["completed"] = True
                    result["failed"] = False
                    result["replayed_from"] = SOURCE_MODE
                    result["pinned_judge"] = str(judge_model)
                    result.pop("_id", None)
                    await db.validation_matches.insert_one(result)
                    completed += 1
                    if completed % 25 == 0:
                        elapsed = time.time() - start
                        rate = completed / elapsed * 60
                        print(f"  Progress: {completed}/{len(to_replay)} ({rate:.0f}/min)")
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"  Match failed: {e}")

    tasks = [run_one(m) for m in to_replay]
    await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.time() - start
    print(f"\nPhase 2 complete: {completed}/{len(to_replay)} matches replayed ({failed} failed) in {elapsed:.0f}s")


async def verify_results():
    """Verify the replay results."""
    count_source = await db.validation_matches.count_documents({
        "dataset_id": DATASET_ID, "content_mode": SOURCE_MODE, "completed": True
    })
    count_target = await db.validation_matches.count_documents({
        "dataset_id": DATASET_ID, "content_mode": TARGET_MODE, "completed": True
    })
    papers_with_summary = await db.validation_papers.count_documents({
        "dataset_id": DATASET_ID, SUMMARY_FIELD: {"$exists": True, "$ne": ""}
    })
    total_papers = await db.validation_papers.count_documents({"dataset_id": DATASET_ID})

    print(f"\n=== Verification ===")
    print(f"Papers with Opus 4.6 summary: {papers_with_summary}/{total_papers}")
    print(f"Source (Opus 4.5) matches: {count_source}")
    print(f"Target (Opus 4.6) matches: {count_target}")

    # Check pair overlap
    source_pairs = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": DATASET_ID, "content_mode": SOURCE_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        source_pairs.add((doc["paper1_id"], doc["paper2_id"]))

    target_pairs = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": DATASET_ID, "content_mode": TARGET_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        target_pairs.add((doc["paper1_id"], doc["paper2_id"]))

    overlap = len(target_pairs & source_pairs)
    print(f"Pair overlap: {overlap}/{len(target_pairs)} target pairs are in source ({overlap/max(len(target_pairs),1)*100:.1f}%)")


async def main():
    print(f"=== Opus 4.6 Replay for {DATASET_ID} ===\n")
    await phase1_generate_summaries()
    await phase2_replay_tournament()
    await verify_results()
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
