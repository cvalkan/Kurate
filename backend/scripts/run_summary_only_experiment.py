"""
Summary-Only vs Abstract+Summary Experiment
=============================================
Re-judges existing abstract_plus_summary:thinking pairs using summary-only mode.
Uses Emergent key with high concurrency. Prints correlations every 500 matches.

Run: cd /app/backend && python3 scripts/run_summary_only_experiment.py > /tmp/summary_exp.log 2>&1 &
"""
import asyncio
import os
import sys
import json
import time
import logging
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("summary-exp")

EXPERIMENT_TAG = "summary_only_v1"
CONTENT_MODE = "ai_summary"  # Uses the existing ai_summary path in compare_papers
SOURCE_MODE = "abstract_plus_summary:thinking"
CONCURRENCY = 15  # ~50 RPM budget, each call ~18s → 15 concurrent workers


async def compute_correlations(db):
    """Compute GT correlations for both arms across all datasets."""
    from routers.leaderboard import compute_leaderboard_async
    from routers.validation_utils import build_expert_ratings, build_human_pairwise_matches
    from scipy import stats as scipy_stats
    import numpy as np

    def corr(a, b):
        shared = sorted(set(a.keys()) & set(b.keys()))
        if len(shared) < 5:
            return None
        sp, _ = scipy_stats.spearmanr([a[p] for p in shared], [b[p] for p in shared])
        return round(float(sp), 4) if not np.isnan(sp) else None

    all_ds = set()
    async for doc in db.validation_papers.aggregate([{"$group": {"_id": "$dataset_id"}}]):
        all_ds.add(doc["_id"])

    results = []
    for ds_id in sorted(all_ds):
        papers = []
        async for p in db.validation_papers.find({"dataset_id": ds_id}, {"_id": 0}):
            papers.append(p)
        if len(papers) < 20:
            continue

        avg_ratings = {}
        for p in papers:
            r = p.get("h1_avg_rating")
            if r is None:
                evals = p.get("evaluations", [])
                vals = [e["rating_value"] for e in evals if e.get("rating_value")]
                r = sum(vals) / len(vals) if vals else None
            if r is not None:
                avg_ratings[p["id"]] = r
        if len(avg_ratings) < 10:
            continue

        # Arm A: existing thinking matches
        arm_a = []
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": SOURCE_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
        ):
            if m.get("winner_id"):
                arm_a.append({"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                              "winner_id": m["winner_id"], "completed": True, "failed": False})

        # Arm B: our new summary-only matches
        arm_b = []
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True},
             "content_mode": CONTENT_MODE, "experiment_tag": EXPERIMENT_TAG},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
        ):
            if m.get("winner_id"):
                arm_b.append({"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                              "winner_id": m["winner_id"], "completed": True, "failed": False})

        if len(arm_a) < 20:
            continue

        rho_a = None
        if arm_a:
            lb_a = await compute_leaderboard_async(papers, arm_a)
            wr_a = {e["id"]: e["score"] for e in lb_a}
            rho_a = corr(wr_a, avg_ratings)

        rho_b = None
        if len(arm_b) >= 20:
            lb_b = await compute_leaderboard_async(papers, arm_b)
            wr_b = {e["id"]: e["score"] for e in lb_b}
            rho_b = corr(wr_b, avg_ratings)

        results.append({"ds": ds_id, "n": len(papers), "arm_a": len(arm_a), "arm_b": len(arm_b),
                        "rho_a": rho_a, "rho_b": rho_b})

    return results


def print_correlations(results, total_done, total_target):
    """Pretty-print correlation comparison."""
    log.info(f"\n{'='*75}")
    log.info(f"  INTERMEDIATE RESULTS ({total_done}/{total_target} matches)")
    log.info(f"{'='*75}")
    log.info(f"  {'Dataset':<25} {'Arm A (abs+sum)':>15} {'Arm B (sum only)':>16} {'Δ':>7} {'B matches':>10}")
    log.info(f"  {'-'*75}")

    deltas = []
    for r in results:
        a_str = f"{r['rho_a']:.3f}" if r['rho_a'] is not None else "—"
        b_str = f"{r['rho_b']:.3f}" if r['rho_b'] is not None else "—"
        d = None
        if r['rho_a'] is not None and r['rho_b'] is not None:
            d = r['rho_b'] - r['rho_a']
            deltas.append(d)
        d_str = f"{d:+.3f}" if d is not None else "—"
        log.info(f"  {r['ds']:<25} {a_str:>15} {b_str:>16} {d_str:>7} {r['arm_b']:>10}")

    if deltas:
        import numpy as np
        mean_d = np.mean(deltas)
        n_positive = sum(1 for d in deltas if d > 0)
        log.info(f"  {'-'*75}")
        log.info(f"  Mean Δ(B-A): {mean_d:+.4f}  |  B wins: {n_positive}/{len(deltas)} datasets")
    log.info(f"{'='*75}\n")


async def main():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")

    from motor.motor_asyncio import AsyncIOMotorClient
    from core.config import db
    from services.llm import compare_papers

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "test_database")

    # Use the global db from core.config (has Emergent key configured)

    # Only run ICLR datasets
    ICLR_ONLY = {"iclr-codegen", "iclr-fairness", "iclr-llm", "iclr-molecules",
                 "iclr-optimization", "iclr-ot", "iclr-pdes", "iclr-protein"}
    
    # Collect all source matches (abstract_plus_summary:thinking)
    source_matches = []
    async for m in db.validation_matches.find(
        {"completed": True, "failed": {"$ne": True}, "content_mode": SOURCE_MODE},
        {"_id": 0, "id": 1, "dataset_id": 1, "paper1_id": 1, "paper2_id": 1,
         "winner_id": 1, "model_used": 1}
    ):
        if m["dataset_id"] in ICLR_ONLY:
            source_matches.append(m)

    log.info(f"Source matches ({SOURCE_MODE}): {len(source_matches)}")

    # Check which ones we've already re-judged
    existing_pairs = set()
    async for m in db.validation_matches.find(
        {"experiment_tag": EXPERIMENT_TAG, "content_mode": CONTENT_MODE},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "dataset_id": 1}
    ):
        existing_pairs.add(f"{m['dataset_id']}|{m['paper1_id']}|{m['paper2_id']}")

    todo = [m for m in source_matches
            if f"{m['dataset_id']}|{m['paper1_id']}|{m['paper2_id']}" not in existing_pairs]
    log.info(f"Already done: {len(existing_pairs)}, remaining: {len(todo)}")

    if not todo:
        log.info("All matches already completed!")
        results = await compute_correlations(db)
        print_correlations(results, len(source_matches), len(source_matches))
        return

    # Build paper lookup per dataset (load once)
    datasets = set(m["dataset_id"] for m in todo)
    paper_cache = {}
    for ds_id in datasets:
        papers = {}
        async for p in db.validation_papers.find(
            {"dataset_id": ds_id},
            {"_id": 0, "id": 1, "title": 1, "abstract": 1,
             "ai_impact_summary": 1, "ai_impact_summary_thinking": 1,
             "ai_impact_summary_opus46": 1}
        ):
            papers[p["id"]] = p
        paper_cache[ds_id] = papers
    log.info(f"Loaded papers for {len(datasets)} datasets")

    # Claude Thinking model config (same as tournament)
    model_config = {
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}},
        "key_suffix": "thinking",
    }

    sem = asyncio.Semaphore(CONCURRENCY)
    completed = 0
    failed = 0
    total = len(todo)
    start_time = time.time()
    next_report_at = 500

    async def run_one(match):
        nonlocal completed, failed
        async with sem:
            ds_id = match["dataset_id"]
            papers = paper_cache.get(ds_id, {})
            p1 = papers.get(match["paper1_id"])
            p2 = papers.get(match["paper2_id"])

            if not p1 or not p2:
                failed += 1
                return

            try:
                result = await compare_papers(
                    p1, p2,
                    content_mode=CONTENT_MODE,
                    model_override=model_config,
                )

                # Map "paper1"/"paper2" to actual paper IDs
                winner = result.get("winner")
                if winner == "paper1":
                    winner_id = match["paper1_id"]
                elif winner == "paper2":
                    winner_id = match["paper2_id"]
                else:
                    winner_id = None

                match_doc = {
                    "id": str(uuid.uuid4()),
                    "dataset_id": ds_id,
                    "paper1_id": match["paper1_id"],
                    "paper2_id": match["paper2_id"],
                    "winner_id": winner_id,
                    "model_used": result.get("model_used"),
                    "reasoning": result.get("reasoning", ""),
                    "content_mode": CONTENT_MODE,
                    "experiment_tag": EXPERIMENT_TAG,
                    "source_match_mode": SOURCE_MODE,
                    "completed": True,
                    "failed": winner_id is None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.validation_matches.insert_one(match_doc)
                completed += 1

            except Exception as e:
                failed += 1
                if "rate" in str(e).lower() or "429" in str(e):
                    await asyncio.sleep(5)  # Back off on rate limit

    # Process in batches of 500 for intermediate reporting
    batch_size = 500
    for batch_start in range(0, total, batch_size):
        batch = todo[batch_start:batch_start + batch_size]
        tasks = [run_one(m) for m in batch]
        await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start_time
        rate = (completed + failed) / max(elapsed, 1) * 60
        eta_min = (total - completed - failed) / max(rate, 0.1)
        log.info(f"Progress: {completed + failed}/{total} ({completed} ok, {failed} fail) "
                 f"| {rate:.0f}/min | ETA: {eta_min:.0f}min")

        # Compute and print intermediate correlations
        results = await compute_correlations(db)
        print_correlations(results, completed, total)

    # Final results
    log.info(f"\nExperiment complete: {completed} ok, {failed} failed in {(time.time()-start_time)/60:.1f} min")
    results = await compute_correlations(db)
    print_correlations(results, completed, total)


if __name__ == "__main__":
    asyncio.run(main())
