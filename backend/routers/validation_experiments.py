"""
Validation Experiment Endpoints

Extended Thinking, Tie-Allowed, Multi-Aspect, and Summarizer A/B experiments.
Extracted from the main validation router for maintainability.
"""
import asyncio
import uuid
import random
import time as _time
from datetime import datetime, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger, DEFAULT_EVALUATION_PROMPT, TIE_ALLOWED_PROMPT, MULTI_ASPECT_PROMPT
from core.auth import verify_admin, get_settings
from services.llm import compare_papers, generate_precomparison_impact_summary
from services.ranking import compute_leaderboard, compute_leaderboard_async
from services.task_tracker import TaskTracker
import numpy as np
from scipy import stats as scipy_stats
from routers.validation_utils import (
    TIER_ORDER, RANKABLE_TIERS, norm_tier,
    build_expert_ratings, build_human_pairwise_matches, build_expert_majority, build_ai_majority,
    build_content_mode_filter, safe_round, interp, cache_get, cache_set,
    PAPER_LIGHT_PROJECTION, build_paper_gt_scores, filter_cross_tier_matches, is_cross_tier_pair,
    build_ensemble_matches,
    invalidate_all_caches, ae_cache, sumab_results_cache, CONSISTENCY_TTL,
)

router = APIRouter(prefix="/api/validation")

# ─── Extended Thinking Experiment ──────────────────────────────────────────────

_thinking_state = {"running": False, "done": 0, "total": 0, "step": "", "dataset_id": ""}
_thinking_task = None

THINKING_FIELD = "ai_impact_summary_thinking"
THINKING_MODE = "abstract_plus_summary:thinking"
THINKING_MODEL = {"provider": "anthropic", "model": "claude-opus-4-6", "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}}


@router.post("/extended-thinking/run", dependencies=[Depends(verify_admin)])
async def start_extended_thinking(request: Request):
    global _thinking_task
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    dataset_id = body.get("dataset_id", "iclr-codegen")
    num_pairs = body.get("num_pairs", 200)

    if _thinking_state["running"]:
        raise HTTPException(409, "Already running")

    async def _bg():
        global _thinking_task
        _tracker = TaskTracker("extended_thinking")
        _tid = await _tracker.start(metadata={"dataset_id": dataset_id, "num_pairs": num_pairs})
        try:
            await _run_extended_thinking(dataset_id, num_pairs)
            await _tracker.complete(_tid)
        except Exception as e:
            logger.error(f"Extended thinking experiment failed: {e}")
            await _tracker.fail(_tid, error=str(e)[:200])
        finally:
            _thinking_state["running"] = False
            _thinking_task = None

    _thinking_task = asyncio.create_task(_bg())
    return {"status": "started", "dataset_id": dataset_id, "num_pairs": num_pairs}


@router.post("/extended-thinking/stop", dependencies=[Depends(verify_admin)])
async def stop_extended_thinking():
    global _thinking_task
    _thinking_state["running"] = False
    if _thinking_task and not _thinking_task.done():
        _thinking_task.cancel()
    return {"status": "stopping"}


@router.get("/extended-thinking/status")
async def extended_thinking_status():
    return _thinking_state


@router.get("/extended-thinking/results")
async def extended_thinking_results():
    """Compute accuracy comparison: opus46 baseline vs thinking summaries."""
    from routers.validation_utils import extended_thinking_cache
    if extended_thinking_cache["data"]:
        return extended_thinking_cache["data"]
    result = await _compute_extended_thinking_results()
    if result.get("status") != "no_data":
        extended_thinking_cache["data"] = result
    return result


async def _compute_extended_thinking_results():
    """Compute accuracy comparison: opus46 baseline vs thinking summaries.
    Uses same GT method as tournament page (AI vs individual expert preferences)."""
    import math

    # Find datasets with thinking matches
    pipeline = [
        {"$match": {"content_mode": THINKING_MODE, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
    ]
    ds_counts = {r["_id"]: r["count"] async for r in db.validation_matches.aggregate(pipeline)}
    if not ds_counts:
        return {"status": "no_data"}

    all_datasets = list(ds_counts.keys())
    pooled_a = pooled_b = pooled_c = pooled_d = 0
    by_dataset = {}

    for ds_id in all_datasets:
        papers = await db.validation_papers.find(
            {"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION
        ).to_list(5000)

        # Build expert pairwise preferences → majority vote per pair (same as tournament page)
        # For multi-reviewer datasets (ICLR): uses majority vote (≥2 votes required)
        # For single/sparse-reviewer datasets (eLife): falls back to individual expert preferences
        expert_ratings = build_expert_ratings(papers)
        expert_majority = build_expert_majority(expert_ratings)
        
        # Count total non-tie expert preferences to decide if majority is sufficient
        total_expert_pairs = 0
        for exp, ratings in expert_ratings.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    if ratings[pids[i]] != ratings[pids[j]]:
                        total_expert_pairs += 1
        
        # Use majority if it covers at least 10% of expert preferences; otherwise individual prefs
        if len(expert_majority) >= max(20, total_expert_pairs * 0.1):
            expert_prefs = expert_majority
        else:
            # Fall back to individual expert preferences (any non-tie vote counts)
            expert_prefs = {}
            for exp, ratings in expert_ratings.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        a, b = pids[i], pids[j]
                        if ratings[a] != ratings[b]:
                            pk = tuple(sorted([a, b]))
                            expert_prefs[pk] = a if ratings[a] > ratings[b] else b

        # Load baseline (opus46) and thinking matches — last-write-wins per pair
        baseline = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": "abstract_plus_summary:opus46"},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            baseline[pk] = m["winner_id"]

        thinking = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": THINKING_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            thinking[pk] = m["winner_id"]

        # McNemar on common pairs that have expert GT
        common = set(baseline.keys()) & set(thinking.keys()) & set(expert_prefs.keys())
        a = b = c = d_val = 0
        for pk in common:
            gt_winner = expert_prefs[pk]
            bl_ok = baseline[pk] == gt_winner
            th_ok = thinking[pk] == gt_winner
            if bl_ok and th_ok: a += 1
            elif bl_ok and not th_ok: b += 1
            elif not bl_ok and th_ok: c += 1
            else: d_val += 1

        total = a + b + c + d_val
        if total > 0:
            bl_acc = round((a + b) / total * 100, 1)
            th_acc = round((a + c) / total * 100, 1)
            by_dataset[ds_id] = {"pairs": total, "baseline": bl_acc, "thinking": th_acc, "lift": round(th_acc - bl_acc, 1)}
            pooled_a += a; pooled_b += b; pooled_c += c; pooled_d += d_val

    total_p = pooled_a + pooled_b + pooled_c + pooled_d
    if total_p == 0:
        return {"status": "no_data"}

    bl_p = round((pooled_a + pooled_b) / total_p * 100, 1)
    th_p = round((pooled_a + pooled_c) / total_p * 100, 1)
    mcnemar = {"pairs": total_p, "only_baseline": pooled_b, "only_thinking": pooled_c}
    if pooled_b + pooled_c > 0:
        chi2 = (abs(pooled_b - pooled_c) - 1)**2 / (pooled_b + pooled_c)
        p_val = math.erfc(math.sqrt(chi2 / 2))
        mcnemar.update({"chi2": round(chi2, 3), "p_value": round(p_val, 4), "significant": p_val < 0.05})
    else:
        mcnemar.update({"chi2": 0, "p_value": 1.0, "significant": False})

    n_thinking = await db.validation_papers.count_documents({THINKING_FIELD: {"$exists": True, "$ne": ""}})
    n_thinking_matches = sum(ds_counts.values())

    return {
        "status": "ok",
        "papers_with_thinking": n_thinking,
        "thinking_matches": n_thinking_matches,
        "baseline_accuracy": bl_p,
        "thinking_accuracy": th_p,
        "baseline_gt_pairs": total_p,
        "lift": round(th_p - bl_p, 1),
        "mcnemar": mcnemar,
        "by_dataset": by_dataset,
    }


async def _run_extended_thinking(dataset_id: str, num_pairs: int):
    """Phase 1: Generate thinking summaries. Phase 2: Run tournament on cross-tier pairs."""
    from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model
    import itertools

    _thinking_state.update({"running": True, "done": 0, "total": 0, "step": "generating_summaries", "dataset_id": dataset_id})

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}

    # Phase 1: Generate thinking summaries for papers that don't have one
    missing = [p for p in papers if not p.get(THINKING_FIELD)]
    _thinking_state["total"] = len(missing)
    logger.info(f"Extended thinking [{dataset_id}]: generating {len(missing)} thinking summaries")

    sem = asyncio.Semaphore(3)  # Lower parallelism — thinking uses more tokens
    gen_done = 0

    async def gen_one(p):
        nonlocal gen_done
        if not _thinking_state["running"]:
            return
        async with sem:
            result = await generate_precomparison_impact_summary(p, model_override=THINKING_MODEL)
            if result and result.get("summary"):
                await db.validation_papers.update_one(
                    {"dataset_id": dataset_id, "id": p["id"]},
                    {"$set": {THINKING_FIELD: result["summary"]}},
                )
                gen_done += 1
                _thinking_state["done"] = gen_done

    await asyncio.gather(*[gen_one(p) for p in missing], return_exceptions=True)
    logger.info(f"Extended thinking [{dataset_id}]: generated {gen_done} summaries")

    if not _thinking_state["running"]:
        return

    # Phase 2: Replay opus46 baseline pairs with thinking summaries
    _thinking_state.update({"step": "tournament", "done": 0})

    # Reload papers with thinking summaries
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    pids_with_thinking = {p["id"] for p in papers if p.get(THINKING_FIELD)}

    # Get existing thinking match pairs to skip
    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": THINKING_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Load opus46 baseline pairs — replay THESE exact pairs for a fair comparison
    from routers.validation_utils import build_paper_gt_scores
    gt = build_paper_gt_scores(papers)
    baseline_pairs = []
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": "abstract_plus_summary:opus46", "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk in existing:
            continue  # already replayed
        if m["paper1_id"] not in pids_with_thinking or m["paper2_id"] not in pids_with_thinking:
            continue  # no thinking summary
        # Cross-tier only
        g1, g2 = gt.get(m["paper1_id"]), gt.get(m["paper2_id"])
        if g1 is None or g2 is None or g1 == g2:
            continue
        baseline_pairs.append((m["paper1_id"], m["paper2_id"]))
        existing.add(pk)  # dedup

    random.shuffle(baseline_pairs)
    to_run = baseline_pairs[:num_pairs]
    _thinking_state["total"] = len(to_run)
    logger.info(f"Extended thinking [{dataset_id}]: replaying {len(to_run)} opus46 cross-tier pairs (of {len(baseline_pairs)} available)")

    sem2 = asyncio.Semaphore(8)
    completed = 0

    async def run_one(p1_id, p2_id):
        nonlocal completed
        if not _thinking_state["running"]:
            return
        async with sem2:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            s1, s2 = p1.get(THINKING_FIELD, ""), p2.get(THINKING_FIELD, "")
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
                        "id": str(uuid.uuid4()),
                        "dataset_id": dataset_id,
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
                    _thinking_state["done"] = completed
                    if completed % 50 == 0:
                        invalidate_all_caches(dataset_id)
            except Exception as e:
                logger.warning(f"Extended thinking match failed: {e}")

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    invalidate_all_caches(dataset_id)
    logger.info(f"Extended thinking [{dataset_id}]: completed {completed}/{len(to_run)} matches")


# ═══════════════════════════════════════════════════════════════════════════════
# Tie-Allowed Experiment
# ═══════════════════════════════════════════════════════════════════════════════

TIE_MODE = "abstract_plus_summary:tie_v1"
_tie_state = {"running": False, "done": 0, "total": 0, "dataset_id": None, "ties": 0}
_tie_task = None


@router.post("/tie-experiment/run", dependencies=[Depends(verify_admin)])
async def start_tie_experiment(request: Request):
    global _tie_task
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    dataset_id = body.get("dataset_id", "iclr-llm")
    num_pairs = body.get("num_pairs", 500)

    if _tie_state["running"]:
        raise HTTPException(409, "Already running")

    async def _bg():
        global _tie_task
        _tracker = TaskTracker("tie_experiment")
        _tid = await _tracker.start(metadata={"dataset_id": dataset_id, "num_pairs": num_pairs})
        try:
            await _run_tie_experiment(dataset_id, num_pairs)
            await _tracker.complete(_tid)
        except Exception as e:
            logger.error(f"Tie experiment failed: {e}")
            await _tracker.fail(_tid, error=str(e)[:200])
        finally:
            _tie_state["running"] = False
            _tie_task = None

    _tie_task = asyncio.create_task(_bg())
    return {"status": "started", "dataset_id": dataset_id, "num_pairs": num_pairs}


@router.post("/tie-experiment/stop", dependencies=[Depends(verify_admin)])
async def stop_tie_experiment():
    global _tie_task
    _tie_state["running"] = False
    if _tie_task and not _tie_task.done():
        _tie_task.cancel()
    return {"status": "stopping"}


@router.get("/tie-experiment/status")
async def tie_experiment_status():
    return _tie_state


@router.get("/tie-experiment/results")
async def tie_experiment_results():
    """Compute tie experiment analysis: tie rate, accuracy, calibration against opus46 baseline."""
    import math

    BASELINE_MODE = "abstract_plus_summary:opus46"

    # Find datasets with tie matches
    pipeline = [
        {"$match": {"content_mode": TIE_MODE, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
    ]
    ds_counts = {r["_id"]: r["count"] async for r in db.validation_matches.aggregate(pipeline)}
    if not ds_counts:
        return {"status": "no_data"}

    all_datasets = list(ds_counts.keys())
    pooled = {"a": 0, "b": 0, "c": 0, "d": 0, "ties_correct": 0, "ties_wrong": 0, "ties_total": 0}
    by_dataset = {}

    for ds_id in all_datasets:
        papers = await db.validation_papers.find(
            {"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION
        ).to_list(5000)

        expert_ratings = build_expert_ratings(papers)
        expert_majority = build_expert_majority(expert_ratings)

        # Fall back to individual expert preferences if majority is too sparse
        total_expert_pairs = sum(
            1 for exp, ratings in expert_ratings.items()
            for i, a in enumerate(ratings) for b in list(ratings)[i+1:]
            if ratings[a] != ratings[b]
        )
        if len(expert_majority) >= max(20, total_expert_pairs * 0.1):
            expert_prefs = expert_majority
        else:
            expert_prefs = {}
            for exp, ratings in expert_ratings.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        a, b = pids[i], pids[j]
                        if ratings[a] != ratings[b]:
                            expert_prefs[tuple(sorted([a, b]))] = a if ratings[a] > ratings[b] else b

        # Build GT score map for gap analysis
        gt_scores = build_paper_gt_scores(papers)

        # Load baseline (opus46) and tie matches
        baseline = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": BASELINE_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            baseline[pk] = m["winner_id"]

        tie_matches = {}
        tie_outcomes = {}  # pk -> "paper1"/"paper2"/"tie"
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": TIE_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "outcome": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            tie_matches[pk] = m.get("winner_id")  # None for ties
            tie_outcomes[pk] = m.get("outcome", "paper1" if m.get("winner_id") == m["paper1_id"] else "paper2")

        # Analyze on common pairs that have expert GT
        common = set(baseline.keys()) & set(tie_matches.keys()) & set(expert_prefs.keys())

        total_ties = 0
        tie_correct_close = 0  # tie when GT gap is small (<=1)
        tie_wrong_far = 0  # tie when GT gap is large (>=2)
        a = b = c = d_val = 0
        by_gap = defaultdict(lambda: {"baseline_correct": 0, "tie_correct": 0, "tie_declared": 0, "total": 0})

        for pk in common:
            gt_winner = expert_prefs[pk]
            bl_ok = baseline[pk] == gt_winner
            is_tie = tie_outcomes.get(pk) == "tie"

            # Score gap
            g1 = gt_scores.get(pk[0])
            g2 = gt_scores.get(pk[1])
            gap = abs(g1 - g2) if g1 is not None and g2 is not None else None
            gap_bucket = "small" if gap is not None and gap <= 1 else ("medium" if gap is not None and gap <= 2 else "large")

            by_gap[gap_bucket]["total"] += 1
            if bl_ok:
                by_gap[gap_bucket]["baseline_correct"] += 1

            if is_tie:
                total_ties += 1
                by_gap[gap_bucket]["tie_declared"] += 1
                if gap is not None and gap <= 1:
                    tie_correct_close += 1
                elif gap is not None and gap >= 2:
                    tie_wrong_far += 1
            else:
                tie_ok = tie_matches[pk] == gt_winner
                if tie_ok:
                    by_gap[gap_bucket]["tie_correct"] += 1
                # McNemar: only on non-tie decisions
                if bl_ok and tie_ok: a += 1
                elif bl_ok and not tie_ok: b += 1
                elif not bl_ok and tie_ok: c += 1
                else: d_val += 1

        total = a + b + c + d_val
        non_tie_total = total  # excludes ties
        all_total = non_tie_total + total_ties

        if all_total == 0:
            continue

        bl_acc = round((a + b) / non_tie_total * 100, 1) if non_tie_total else 0
        tie_acc = round((a + c) / non_tie_total * 100, 1) if non_tie_total else 0
        tie_rate = round(total_ties / all_total * 100, 1) if all_total else 0

        # Gap analysis
        gap_analysis = {}
        for bucket in ["small", "medium", "large"]:
            g = by_gap[bucket]
            if g["total"] > 0:
                gap_analysis[bucket] = {
                    "total": g["total"],
                    "baseline_accuracy": round(g["baseline_correct"] / g["total"] * 100, 1),
                    "tie_rate": round(g["tie_declared"] / g["total"] * 100, 1),
                    "non_tie_in_bucket": g["total"] - g["tie_declared"],
                    "tie_accuracy": round(g["tie_correct"] / max(g["total"] - g["tie_declared"], 1) * 100, 1),
                }

        by_dataset[ds_id] = {
            "pairs": all_total,
            "baseline_accuracy": bl_acc,
            "tie_accuracy_non_tie": tie_acc,
            "tie_rate": tie_rate,
            "ties": total_ties,
            "lift": round(tie_acc - bl_acc, 1),
            "gap_analysis": gap_analysis,
            "tie_calibration": {
                "close_pairs_tied": tie_correct_close,
                "far_pairs_tied": tie_wrong_far,
                "total_ties": total_ties,
            },
        }

        pooled["a"] += a
        pooled["b"] += b
        pooled["c"] += c
        pooled["d"] += d_val
        pooled["ties_total"] += total_ties
        pooled["ties_correct"] += tie_correct_close
        pooled["ties_wrong"] += tie_wrong_far

    total_p = pooled["a"] + pooled["b"] + pooled["c"] + pooled["d"]
    all_p = total_p + pooled["ties_total"]
    if all_p == 0:
        return {"status": "no_data"}

    bl_p = round((pooled["a"] + pooled["b"]) / max(total_p, 1) * 100, 1)
    tie_p = round((pooled["a"] + pooled["c"]) / max(total_p, 1) * 100, 1)
    tie_rate_p = round(pooled["ties_total"] / all_p * 100, 1)

    mcnemar = {"non_tie_pairs": total_p, "only_baseline": pooled["b"], "only_tie": pooled["c"]}
    if pooled["b"] + pooled["c"] > 0:
        chi2 = (abs(pooled["b"] - pooled["c"]) - 1) ** 2 / (pooled["b"] + pooled["c"])
        p_val = math.erfc(math.sqrt(chi2 / 2))
        mcnemar.update({"chi2": round(chi2, 3), "p_value": round(p_val, 4), "significant": p_val < 0.05})
    else:
        mcnemar.update({"chi2": 0, "p_value": 1.0, "significant": False})

    n_tie_matches = sum(ds_counts.values())

    return {
        "status": "ok",
        "tie_matches": n_tie_matches,
        "baseline_accuracy": bl_p,
        "tie_accuracy_non_tie": tie_p,
        "tie_rate": tie_rate_p,
        "total_ties": pooled["ties_total"],
        "total_pairs_with_gt": all_p,
        "lift": round(tie_p - bl_p, 1),
        "mcnemar": mcnemar,
        "tie_calibration": {
            "close_pairs_tied": pooled["ties_correct"],
            "far_pairs_tied": pooled["ties_wrong"],
            "total_ties": pooled["ties_total"],
            "calibration_ratio": round(pooled["ties_correct"] / max(pooled["ties_total"], 1) * 100, 1),
        },
        "by_dataset": by_dataset,
    }


async def _run_tie_experiment(dataset_id: str, num_pairs: int):
    """Replay opus46 baseline cross-tier pairs with the tie-allowed prompt."""
    from services.llm import compare_papers, _pick_round_robin_model

    _tie_state.update({"running": True, "done": 0, "total": 0, "ties": 0, "dataset_id": dataset_id})

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    gt = build_paper_gt_scores(papers)

    # Get existing tie experiment pairs to skip
    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": TIE_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Load opus46 baseline pairs — replay these for fair comparison
    baseline_pairs = []
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": "abstract_plus_summary:opus46", "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk in existing:
            continue
        # Cross-tier only
        g1, g2 = gt.get(m["paper1_id"]), gt.get(m["paper2_id"])
        if g1 is None or g2 is None or g1 == g2:
            continue
        baseline_pairs.append((m["paper1_id"], m["paper2_id"]))
        existing.add(pk)

    random.shuffle(baseline_pairs)
    to_run = baseline_pairs[:num_pairs]
    _tie_state["total"] = len(to_run)
    logger.info(f"Tie experiment [{dataset_id}]: replaying {len(to_run)} opus46 cross-tier pairs (of {len(baseline_pairs)} available)")

    sem = asyncio.Semaphore(8)
    completed = 0
    ties = 0

    async def run_one(p1_id, p2_id):
        nonlocal completed, ties
        if not _tie_state["running"]:
            return
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            # Use opus46 summaries
            s1, s2 = p1.get("ai_impact_summary_opus46", p1.get("ai_impact_summary", "")), p2.get("ai_impact_summary_opus46", p2.get("ai_impact_summary", ""))
            if not s1 or not s2:
                return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            # Random flip for positional bias
            if random.random() < 0.5:
                p1c, p2c = p2c, p1c
                p1_id, p2_id = p2_id, p1_id
            try:
                result = await compare_papers(p1c, p2c, TIE_ALLOWED_PROMPT,
                    content_mode="abstract_plus_summary", model_override=judge, allow_tie=True)
                if result and not result.get("failed"):
                    wk = result.get("winner", "paper1")
                    is_tie = wk == "tie"
                    doc = {
                        "id": str(uuid.uuid4()),
                        "dataset_id": dataset_id,
                        "content_mode": TIE_MODE,
                        "prompt_tag": "tie_v1",
                        "paper1_id": p1_id,
                        "paper2_id": p2_id,
                        "winner_id": None if is_tie else (p1_id if wk == "paper1" else p2_id),
                        "outcome": wk,  # "paper1", "paper2", or "tie"
                        "completed": True,
                        "failed": False,
                        "model_used": result.get("model_used", judge),
                        "reasoning": result.get("reasoning", ""),
                        "tokens": result.get("tokens", {}),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await db.validation_matches.insert_one(doc)
                    completed += 1
                    if is_tie:
                        ties += 1
                    _tie_state["done"] = completed
                    _tie_state["ties"] = ties
                    if completed % 50 == 0:
                        invalidate_all_caches(dataset_id)
            except Exception as e:
                logger.warning(f"Tie experiment match failed: {e}")

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    invalidate_all_caches(dataset_id)
    logger.info(f"Tie experiment [{dataset_id}]: completed {completed}/{len(to_run)} matches, {ties} ties ({round(ties/max(completed,1)*100,1)}%)")



# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Aspect Judging Experiment
# ═══════════════════════════════════════════════════════════════════════════════

MULTI_ASPECT_MODE = "abstract_plus_summary:multi_aspect"
_ma_state = {"running": False, "done": 0, "total": 0, "dataset_id": None}
_ma_task = None


@router.post("/multi-aspect/run", dependencies=[Depends(verify_admin)])
async def start_multi_aspect(request: Request):
    global _ma_task
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    dataset_id = body.get("dataset_id", "iclr-llm")
    num_pairs = body.get("num_pairs", 500)

    if _ma_state["running"]:
        raise HTTPException(409, "Already running")

    async def _bg():
        global _ma_task
        _tracker = TaskTracker("multi_aspect")
        _tid = await _tracker.start(metadata={"dataset_id": dataset_id, "num_pairs": num_pairs})
        try:
            await _run_multi_aspect(dataset_id, num_pairs)
            await _tracker.complete(_tid)
        except Exception as e:
            logger.error(f"Multi-aspect experiment failed: {e}")
            await _tracker.fail(_tid, error=str(e)[:200])
        finally:
            _ma_state["running"] = False
            _ma_task = None

    _ma_task = asyncio.create_task(_bg())
    return {"status": "started", "dataset_id": dataset_id, "num_pairs": num_pairs}


@router.post("/multi-aspect/stop", dependencies=[Depends(verify_admin)])
async def stop_multi_aspect():
    global _ma_task
    _ma_state["running"] = False
    if _ma_task and not _ma_task.done():
        _ma_task.cancel()
    return {"status": "stopping"}


@router.get("/multi-aspect/status")
async def multi_aspect_status():
    return _ma_state


@router.get("/multi-aspect/results")
async def multi_aspect_results():
    """Analyze multi-aspect experiment results."""
    from routers.validation_utils import multi_aspect_cache
    if multi_aspect_cache["data"]:
        return multi_aspect_cache["data"]
    result = await _compute_multi_aspect_results()
    if result.get("status") != "no_data":
        multi_aspect_cache["data"] = result
    return result


async def _compute_multi_aspect_results():
    """Analyze multi-aspect experiment: per-dimension accuracy, aggregate, optimal weighting."""
    from core.config import MULTI_ASPECT_DIMENSIONS
    import math

    BASELINE_MODE = "abstract_plus_summary:thinking"  # same input as multi-aspect (thinking summaries)

    pipeline = [
        {"$match": {"content_mode": MULTI_ASPECT_MODE, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
    ]
    ds_counts = {r["_id"]: r["count"] async for r in db.validation_matches.aggregate(pipeline)}
    if not ds_counts:
        return {"status": "no_data"}

    all_datasets = list(ds_counts.keys())
    # Pooled stats
    pooled_dim = {d: {"correct": 0, "total": 0} for d in MULTI_ASPECT_DIMENSIONS}
    pooled_agg = {"correct": 0, "total": 0}
    pooled_baseline = {"correct": 0, "total": 0}
    pooled_agreement = {"all_agree": 0, "total": 0}
    by_dataset = {}

    for ds_id in all_datasets:
        papers = await db.validation_papers.find(
            {"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION
        ).to_list(5000)

        expert_ratings = build_expert_ratings(papers)
        expert_majority = build_expert_majority(expert_ratings)
        total_expert_pairs = sum(
            1 for exp, ratings in expert_ratings.items()
            for i, a in enumerate(ratings) for b in list(ratings)[i+1:]
            if ratings[a] != ratings[b]
        )
        if len(expert_majority) >= max(20, total_expert_pairs * 0.1):
            expert_prefs = expert_majority
        else:
            expert_prefs = {}
            for exp, ratings in expert_ratings.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        a, b = pids[i], pids[j]
                        if ratings[a] != ratings[b]:
                            expert_prefs[tuple(sorted([a, b]))] = a if ratings[a] > ratings[b] else b

        # Load baseline
        baseline = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": BASELINE_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            baseline[pk] = m["winner_id"]

        # Load multi-aspect matches
        ma_matches = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": MULTI_ASPECT_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "aspect_winners": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            ma_matches[pk] = m

        common = set(baseline.keys()) & set(ma_matches.keys()) & set(expert_prefs.keys())
        if not common:
            continue

        dim_correct = {d: 0 for d in MULTI_ASPECT_DIMENSIONS}
        dim_total = {d: 0 for d in MULTI_ASPECT_DIMENSIONS}
        agg_correct = agg_total = bl_correct = bl_total = 0
        all_agree_count = 0

        for pk in common:
            gt = expert_prefs[pk]
            m = ma_matches[pk]
            aspects = m.get("aspect_winners", {})

            # Per-dimension accuracy
            for dim in MULTI_ASPECT_DIMENSIONS:
                dim_winner = aspects.get(dim)
                if dim_winner and dim_winner in (pk[0], pk[1]):
                    dim_total[dim] += 1
                    if dim_winner == gt:
                        dim_correct[dim] += 1

            # Aggregate (majority of 5 dimensions)
            agg_winner = m.get("winner_id")
            if agg_winner:
                agg_total += 1
                if agg_winner == gt:
                    agg_correct += 1

            # Baseline
            bl_total += 1
            if baseline[pk] == gt:
                bl_correct += 1

            # All-agree rate
            dim_votes = set(aspects.get(d) for d in MULTI_ASPECT_DIMENSIONS if aspects.get(d))
            if len(dim_votes) == 1:
                all_agree_count += 1

        ds_result = {
            "pairs": len(common),
            "per_dimension": {},
            "aggregate": {"correct": agg_correct, "total": agg_total, "rate": round(agg_correct / max(agg_total, 1) * 100, 1)},
            "baseline": {"correct": bl_correct, "total": bl_total, "rate": round(bl_correct / max(bl_total, 1) * 100, 1)},
            "agreement": {"all_agree": all_agree_count, "total": len(common), "rate": round(all_agree_count / max(len(common), 1) * 100, 1)},
        }
        for dim in MULTI_ASPECT_DIMENSIONS:
            ds_result["per_dimension"][dim] = {
                "correct": dim_correct[dim], "total": dim_total[dim],
                "rate": round(dim_correct[dim] / max(dim_total[dim], 1) * 100, 1),
            }
            pooled_dim[dim]["correct"] += dim_correct[dim]
            pooled_dim[dim]["total"] += dim_total[dim]

        pooled_agg["correct"] += agg_correct
        pooled_agg["total"] += agg_total
        pooled_baseline["correct"] += bl_correct
        pooled_baseline["total"] += bl_total
        pooled_agreement["all_agree"] += all_agree_count
        pooled_agreement["total"] += len(common)
        by_dataset[ds_id] = ds_result

    if not pooled_agg["total"]:
        return {"status": "no_data"}

    # McNemar: aggregate vs baseline
    a = b = c = d_val = 0
    for ds_id in all_datasets:
        papers = await db.validation_papers.find({"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION).to_list(5000)
        expert_ratings = build_expert_ratings(papers)
        expert_majority = build_expert_majority(expert_ratings)
        total_ep = sum(1 for exp, ratings in expert_ratings.items() for i, aa in enumerate(ratings) for bb in list(ratings)[i+1:] if ratings[aa] != ratings[bb])
        if len(expert_majority) >= max(20, total_ep * 0.1):
            ep = expert_majority
        else:
            ep = {}
            for exp, ratings in expert_ratings.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        aa, bb = pids[i], pids[j]
                        if ratings[aa] != ratings[bb]:
                            ep[tuple(sorted([aa, bb]))] = aa if ratings[aa] > ratings[bb] else bb

        bl2 = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": BASELINE_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}):
            bl2[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m["winner_id"]
        ma2 = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": MULTI_ASPECT_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}):
            ma2[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m["winner_id"]
        for pk in set(bl2) & set(ma2) & set(ep):
            gt = ep[pk]
            bl_ok = bl2[pk] == gt
            ma_ok = ma2[pk] == gt
            if bl_ok and ma_ok: a += 1
            elif bl_ok and not ma_ok: b += 1
            elif not bl_ok and ma_ok: c += 1
            else: d_val += 1

    mcnemar = {"pairs": a + b + c + d_val, "only_baseline": b, "only_multi_aspect": c}
    if b + c > 0:
        chi2 = (abs(b - c) - 1) ** 2 / (b + c)
        p_val = math.erfc(math.sqrt(chi2 / 2))
        mcnemar.update({"chi2": round(chi2, 3), "p_value": round(p_val, 4), "significant": p_val < 0.05})
    else:
        mcnemar.update({"chi2": 0, "p_value": 1.0, "significant": False})

    dim_labels = {
        "novelty": "Novelty & Innovation", "applications": "Real-World Applications",
        "rigor": "Methodological Rigor", "breadth": "Breadth of Impact", "timeliness": "Timeliness & Relevance",
    }

    # ── Agreement filter analysis: ranking ρ + accuracy when holistic agrees with MA variants ──
    from services.ranking import compute_leaderboard
    import numpy as _np

    agreement_strategies = {}
    for ds_id in all_datasets:
        papers = await db.validation_papers.find({"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION).to_list(5000)
        paper_list = [{"id": p["id"], "title": p.get("title", "")} for p in papers]

        er2 = build_expert_ratings(papers)
        hm2 = []
        for exp, ratings in er2.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    aa, bb = pids[i], pids[j]
                    if ratings[aa] != ratings[bb]:
                        hm2.append({"paper1_id": aa, "paper2_id": bb,
                            "winner_id": aa if ratings[aa] > ratings[bb] else bb, "completed": True, "failed": False})

        # Expert prefs for accuracy
        em3 = build_expert_majority(er2)
        total_ep3 = sum(1 for exp, ratings in er2.items() for i, aa in enumerate(ratings) for bb in list(ratings)[i+1:] if ratings[aa] != ratings[bb])
        ep3 = em3 if len(em3) >= max(20, total_ep3 * 0.1) else {}
        if not ep3:
            for exp, ratings in er2.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        aa, bb = pids[i], pids[j]
                        if ratings[aa] != ratings[bb]:
                            ep3[tuple(sorted([aa, bb]))] = aa if ratings[aa] > ratings[bb] else bb

        hol_map = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": BASELINE_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}):
            hol_map[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m["winner_id"]

        ma_raw = {}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": MULTI_ASPECT_MODE},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "aspect_winners": 1}):
            ma_raw[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m

        cp = set(hol_map) & set(ma_raw)
        if len(cp) < 20:
            continue

        # Dim accuracies for Bayesian weights
        da = {}
        for dim in MULTI_ASPECT_DIMENSIONS:
            cor = tot = 0
            for pk in cp:
                if pk not in ep3: continue
                dw = ma_raw[pk].get("aspect_winners", {}).get(dim)
                if dw: tot += 1; cor += (1 if dw == ep3[pk] else 0)
            da[dim] = cor / max(tot, 1)
        bw = _np.array([max(_np.log(max(da[d], 0.01) / max(1-da[d], 0.01)), 0) for d in MULTI_ASPECT_DIMENSIONS])

        def _nar_winner(pk):
            aw = ma_raw[pk].get("aspect_winners", {})
            votes = [aw.get("novelty"), aw.get("applications"), aw.get("rigor")]
            votes = [v for v in votes if v]
            if len(votes) >= 2:
                c = Counter(votes)
                return c.most_common(1)[0][0]
            return ma_raw[pk]["winner_id"]

        def _bayes_winner(pk):
            aw = ma_raw[pk].get("aspect_winners", {})
            s1 = sum(bw[i] for i, d in enumerate(MULTI_ASPECT_DIMENSIONS) if aw.get(d) == pk[0])
            s2 = sum(bw[i] for i, d in enumerate(MULTI_ASPECT_DIMENSIONS) if aw.get(d) == pk[1])
            return pk[0] if s1 > s2 else pk[1] if s2 > s1 else ma_raw[pk]["winner_id"]

        filters = {
            "H+MA Agree": {pk for pk in cp if hol_map[pk] == ma_raw[pk]["winner_id"]},
            "H+Bayes Agree": {pk for pk in cp if hol_map[pk] == _bayes_winner(pk)},
            "H+NAR Agree": {pk for pk in cp if hol_map[pk] == _nar_winner(pk)},
        }

        for fname, pair_set in filters.items():
            matches = [{"paper1_id": pk[0], "paper2_id": pk[1], "winner_id": hol_map[pk],
                        "completed": True, "failed": False} for pk in pair_set]
            if len(matches) < 10: continue

            # Ranking correlation
            try:
                ai_lb = await compute_leaderboard_async(paper_list, matches)
                h_lb = await compute_leaderboard_async(paper_list, hm2)
                ai_s = {e["id"]: e["score"] for e in ai_lb}
                h_s = {e["id"]: e["score"] for e in h_lb}
                common_ids = sorted(set(ai_s) & set(h_s))
                if len(common_ids) >= 10:
                    rho, _ = scipy_stats.spearmanr([ai_s[c] for c in common_ids], [h_s[c] for c in common_ids])
                    rho = safe_round(rho)
                else:
                    rho = None
            except Exception:
                rho = None

            # Accuracy
            cor = tot = 0
            for pk in pair_set:
                if pk in ep3: tot += 1; cor += (1 if hol_map[pk] == ep3[pk] else 0)
            acc = round(cor / max(tot, 1) * 100, 1)

            if fname not in agreement_strategies:
                agreement_strategies[fname] = {"rho_sum": 0, "rho_n": 0, "correct": 0, "total": 0, "pairs": 0, "by_ds": {}}
            s = agreement_strategies[fname]
            if rho is not None:
                s["rho_sum"] += rho * len(pair_set)
                s["rho_n"] += len(pair_set)
            s["correct"] += cor; s["total"] += tot; s["pairs"] += len(pair_set)
            s["by_ds"][ds_id] = {"rho": rho, "acc": acc, "pairs": len(pair_set), "coverage": round(len(pair_set)/len(cp)*100, 1)}

    # Also compute holistic baseline ρ per dataset for comparison
    hol_rho_sum = hol_rho_n = hol_correct = hol_total = hol_pairs = 0
    for ds_id in all_datasets:
        ds_entry = by_dataset.get(ds_id)
        if not ds_entry: continue
        # Reuse the baseline data already computed
        hol_correct += ds_entry["baseline"]["correct"]
        hol_total += ds_entry["baseline"]["total"]
        hol_pairs += ds_entry["pairs"]

    # Format agreement strategies for response
    agree_results = {}
    for fname, s in agreement_strategies.items():
        agree_results[fname] = {
            "avg_rho": round(s["rho_sum"] / max(s["rho_n"], 1), 4),
            "accuracy": round(s["correct"] / max(s["total"], 1) * 100, 1),
            "correct": s["correct"], "total": s["total"], "pairs": s["pairs"],
            "avg_coverage": round(s["pairs"] / max(pooled_agg["total"], 1) * 100, 1),
            "by_dataset": s["by_ds"],
        }

    return {
        "status": "ok",
        "total_matches": sum(ds_counts.values()),
        "per_dimension": {dim: {**pooled_dim[dim], "rate": round(pooled_dim[dim]["correct"] / max(pooled_dim[dim]["total"], 1) * 100, 1), "label": dim_labels.get(dim, dim)} for dim in MULTI_ASPECT_DIMENSIONS},
        "aggregate": {**pooled_agg, "rate": round(pooled_agg["correct"] / max(pooled_agg["total"], 1) * 100, 1)},
        "baseline": {**pooled_baseline, "rate": round(pooled_baseline["correct"] / max(pooled_baseline["total"], 1) * 100, 1)},
        "lift": round(pooled_agg["correct"] / max(pooled_agg["total"], 1) * 100 - pooled_baseline["correct"] / max(pooled_baseline["total"], 1) * 100, 1),
        "mcnemar": mcnemar,
        "dimension_agreement": {**pooled_agreement, "rate": round(pooled_agreement["all_agree"] / max(pooled_agreement["total"], 1) * 100, 1)},
        "agreement_filters": agree_results,
        "by_dataset": by_dataset,
    }


async def _run_multi_aspect(dataset_id: str, num_pairs: int):
    """Replay thinking baseline cross-tier pairs with multi-aspect prompt."""
    from services.llm import compare_papers, _pick_round_robin_model
    from core.config import MULTI_ASPECT_PROMPT, MULTI_ASPECT_DIMENSIONS

    _ma_state.update({"running": True, "done": 0, "total": 0, "dataset_id": dataset_id})

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    gt = build_paper_gt_scores(papers)

    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": MULTI_ASPECT_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Replay thinking baseline pairs for fair comparison (same input type)
    baseline_pairs = []
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": "abstract_plus_summary:thinking", "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk in existing:
            continue
        g1, g2 = gt.get(m["paper1_id"]), gt.get(m["paper2_id"])
        if g1 is None or g2 is None or g1 == g2:
            continue
        baseline_pairs.append((m["paper1_id"], m["paper2_id"]))
        existing.add(pk)

    # If not enough thinking pairs, also use opus46 pairs (they'll still get thinking summaries)
    if len(baseline_pairs) < num_pairs:
        async for m in db.validation_matches.find(
            {"dataset_id": dataset_id, "content_mode": "abstract_plus_summary:opus46", "completed": True, "failed": {"$ne": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ):
            pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            if pk in existing:
                continue
            g1, g2 = gt.get(m["paper1_id"]), gt.get(m["paper2_id"])
            if g1 is None or g2 is None or g1 == g2:
                continue
            baseline_pairs.append((m["paper1_id"], m["paper2_id"]))
            existing.add(pk)

    random.shuffle(baseline_pairs)
    to_run = baseline_pairs[:num_pairs]
    _ma_state["total"] = len(to_run)
    logger.info(f"Multi-aspect [{dataset_id}]: replaying {len(to_run)} thinking cross-tier pairs")

    sem = asyncio.Semaphore(8)
    completed = 0

    async def run_one(p1_id, p2_id):
        nonlocal completed
        if not _ma_state["running"]:
            return
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            # Use thinking summaries (best available)
            s1 = p1.get("ai_impact_summary_thinking", p1.get("ai_impact_summary_opus46", p1.get("ai_impact_summary", "")))
            s2 = p2.get("ai_impact_summary_thinking", p2.get("ai_impact_summary_opus46", p2.get("ai_impact_summary", "")))
            if not s1 or not s2:
                return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            if random.random() < 0.5:
                p1c, p2c = p2c, p1c
                p1_id, p2_id = p2_id, p1_id
            try:
                result = await compare_papers(p1c, p2c, MULTI_ASPECT_PROMPT,
                    content_mode="abstract_plus_summary", model_override=judge, multi_aspect=True)
                if result and not result.get("failed"):
                    # Map dimension winners to paper IDs
                    aspect_winners = {}
                    for dim in MULTI_ASPECT_DIMENSIONS:
                        dw = result.get(dim)
                        if dw == "paper1":
                            aspect_winners[dim] = p1_id
                        elif dw == "paper2":
                            aspect_winners[dim] = p2_id

                    agg_winner_key = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()),
                        "dataset_id": dataset_id,
                        "content_mode": MULTI_ASPECT_MODE,
                        "prompt_tag": "multi_aspect",
                        "paper1_id": p1_id, "paper2_id": p2_id,
                        "winner_id": p1_id if agg_winner_key == "paper1" else p2_id,
                        "aspect_winners": aspect_winners,
                        "completed": True, "failed": False,
                        "model_used": result.get("model_used", judge),
                        "reasoning": result.get("reasoning", ""),
                        "tokens": result.get("tokens", {}),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await db.validation_matches.insert_one(doc)
                    completed += 1
                    _ma_state["done"] = completed
                    if completed % 50 == 0:
                        invalidate_all_caches(dataset_id)
            except Exception as e:
                logger.warning(f"Multi-aspect match failed: {e}")

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    invalidate_all_caches(dataset_id)
    logger.info(f"Multi-aspect [{dataset_id}]: completed {completed}/{len(to_run)} matches")


# ═══════════════════════════════════════════════════════════════════════════════
# Summarizer A/B Experiment (GPT / Gemini / Opus summaries comparison)
# ═══════════════════════════════════════════════════════════════════════════════

SUMMARIZER_MODELS = {
    "gpt": {"provider": "openai", "model": "gpt-5.2"},
    "gemini": {"provider": "gemini", "model": "gemini-3-pro-preview"},
}
_sumab_state = {"running": False, "phase": "", "done": 0, "total": 0, "dataset_id": None, "summarizer": None}
_sumab_task = None


async def _persist_sumab_task(dataset_id: str, summarizer: str, num_pairs: int, status: str = "queued"):
    """Write or update a summarizer-ab task in MongoDB so it survives restarts."""
    await db.summarizer_ab_tasks.update_one(
        {"dataset_id": dataset_id, "summarizer": summarizer},
        {"$set": {
            "dataset_id": dataset_id,
            "summarizer": summarizer,
            "num_pairs": num_pairs,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, "$setOnInsert": {
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def _mark_sumab_complete(dataset_id: str, summarizer: str):
    """Mark a summarizer-ab task as complete in MongoDB."""
    await db.summarizer_ab_tasks.update_one(
        {"dataset_id": dataset_id, "summarizer": summarizer},
        {"$set": {"status": "complete", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )


async def resume_incomplete_summarizer_ab():
    """Startup task: resume tasks that were actually running when the server stopped.

    Only resumes tasks with status='running' that were updated recently (within 1 hour).
    Stale 'running' tasks (from a previous session/deploy) are marked as 'interrupted'
    and skipped — use the admin API to re-queue if needed.
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    # Mark stale "running" tasks as interrupted (older than 1 hour)
    stale = await db.summarizer_ab_tasks.update_many(
        {"status": "running", "updated_at": {"$lt": cutoff}},
        {"$set": {"status": "interrupted", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if stale.modified_count:
        logger.info(f"Marked {stale.modified_count} stale summarizer-ab tasks as interrupted")

    # Only resume recently-running tasks
    incomplete = await db.summarizer_ab_tasks.find(
        {"status": "running"},
        {"_id": 0},
    ).to_list(5)  # Max 5 at a time

    if not incomplete:
        return

    logger.info(f"Resuming {len(incomplete)} incomplete summarizer-ab tasks")

    for task in incomplete:
        ds = task["dataset_id"]
        summarizer = task["summarizer"]
        num_pairs = task.get("num_pairs", 300)

        if summarizer not in SUMMARIZER_MODELS:
            logger.warning(f"Unknown summarizer '{summarizer}' in queued task, skipping")
            await _mark_sumab_complete(ds, summarizer)
            continue

        logger.info(f"Resuming summarizer-ab: {ds}/{summarizer} ({num_pairs} pairs)")
        await _persist_sumab_task(ds, summarizer, num_pairs, status="running")

        try:
            await _run_summarizer_ab(ds, summarizer, num_pairs)
            await _mark_sumab_complete(ds, summarizer)
            logger.info(f"Resumed summarizer-ab complete: {ds}/{summarizer}")
        except Exception as e:
            logger.error(f"Resumed summarizer-ab failed: {ds}/{summarizer}: {e}")
            # Leave as "running" so it's retried on next restart
            await _persist_sumab_task(ds, summarizer, num_pairs, status="queued")


# ae_cache imported from validation_utils
# sumab_results_cache imported from validation_utils


@router.get("/assessor-evaluator/results")
async def assessor_evaluator_results():
    """Full summarizer × judge matrix — cached 1h."""
    import time as _t
    if ae_cache["data"]:
        return ae_cache["data"]
    result = await _compute_assessor_evaluator()
    if result.get("status") == "ok":
        ae_cache["data"] = result
        ae_cache["ts"] = _t.time()
    return result


async def _compute_assessor_evaluator():
    """Full summarizer × judge matrix on same pairs."""
    import scipy.stats

    SUM_MODES = {
        "Opus 4.5": "abstract_plus_summary",
        "Opus 4.6": "abstract_plus_summary:opus46",
        "Opus 4.6 Thinking": "abstract_plus_summary:thinking",
        "GPT-5.2": "abstract_plus_summary:gpt_summary",
        "Gemini 3 Pro": "abstract_plus_summary:gemini_summary",
    }
    JUDGES = ["Opus 4.6", "GPT-5.2", "Gemini 3 Pro"]

    def _short(mu):
        model = mu.get("model", "")
        if "claude" in model and "4-6" in model: return "Opus 4.6"
        if "claude" in model: return "Opus 4.5"
        if "gpt" in model: return "GPT-5.2"
        if "gemini" in model: return "Gemini 3 Pro"
        return model

    datasets = ["iclr-llm", "iclr-codegen"]
    ds_meta = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {"iclr-llm": "ICLR LLM", "iclr-codegen": "ICLR Code Gen"}
    ds_names.update({d["dataset_id"]: d.get("name", d["dataset_id"]) for d in ds_meta})
    ds_pipeline = [
        {"$match": {"content_mode": {"$in": ["abstract_plus_summary:gpt_summary", "abstract_plus_summary:gemini_summary"]}, "completed": True}},
        {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 30}}},
    ]
    extra = [r["_id"] async for r in db.validation_matches.aggregate(ds_pipeline)]
    for ds in extra:
        if ds not in datasets:
            datasets.append(ds)
    by_dataset = {}
    pooled_cells = defaultdict(lambda: {"rho_vals": [], "correct": 0, "total": 0})

    for ds_id in datasets:
        papers = await db.validation_papers.find({"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION).to_list(5000)
        paper_list = [{"id": p["id"], "title": p.get("title", "")} for p in papers]

        er = build_expert_ratings(papers)
        em = build_expert_majority(er)
        total_ep = sum(1 for exp, ratings in er.items() for i, a in enumerate(ratings) for b in list(ratings)[i+1:] if ratings[a] != ratings[b])
        ep = em if len(em) >= max(20, total_ep * 0.1) else {}
        if not ep:
            for exp, ratings in er.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        a, b = pids[i], pids[j]
                        if ratings[a] != ratings[b]:
                            ep[tuple(sorted([a, b]))] = a if ratings[a] > ratings[b] else b

        hm = []
        for exp, ratings in er.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    if ratings[a] != ratings[b]:
                        hm.append({"paper1_id": a, "paper2_id": b, "winner_id": a if ratings[a] > ratings[b] else b, "completed": True, "failed": False})

        mode_data = {}
        for sum_name, cm in SUM_MODES.items():
            pbj = defaultdict(dict)
            async for m in db.validation_matches.find(
                {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": cm},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}):
                pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
                pbj[pk][_short(m.get("model_used", {}))] = m["winner_id"]
            if pbj: mode_data[sum_name] = pbj

        shared = None
        avail = []
        for name, data in mode_data.items():
            if len(data) < 20: continue
            avail.append(name)
            shared = set(data.keys()) if shared is None else shared & set(data.keys())
        if not shared or len(shared) < 15: continue

        ds_cells = []
        for sum_name in avail:
            data = mode_data[sum_name]
            # Round-robin
            rr = []
            for pk in shared:
                if pk not in data: continue
                c = Counter(data[pk].values())
                rr.append({"paper1_id": pk[0], "paper2_id": pk[1], "winner_id": c.most_common(1)[0][0], "completed": True, "failed": False})

            rr_rho = None
            try:
                ai_lb = await compute_leaderboard_async(paper_list, rr)
                h_lb = await compute_leaderboard_async(paper_list, hm)
                ai_s = {e["id"]: e["score"] for e in ai_lb}
                h_s = {e["id"]: e["score"] for e in h_lb}
                ci = sorted(set(ai_s) & set(h_s))
                if len(ci) >= 10:
                    rr_rho = safe_round(scipy.stats.spearmanr([ai_s[x] for x in ci], [h_s[x] for x in ci])[0])
            except Exception: pass

            rr_c = sum(1 for m in rr if tuple(sorted([m["paper1_id"], m["paper2_id"]])) in ep and m["winner_id"] == ep[tuple(sorted([m["paper1_id"], m["paper2_id"]]))])
            rr_t = sum(1 for m in rr if tuple(sorted([m["paper1_id"], m["paper2_id"]])) in ep)
            rr_acc = round(rr_c / max(rr_t, 1) * 100, 1)

            cell = {"summarizer": sum_name, "judge": "Round-Robin", "rho": rr_rho, "accuracy": rr_acc, "correct": rr_c, "total": rr_t, "pairs": len(rr)}
            ds_cells.append(cell)
            key = f"{sum_name}|Round-Robin"
            if rr_rho is not None: pooled_cells[key]["rho_vals"].append(rr_rho)
            pooled_cells[key]["correct"] += rr_c; pooled_cells[key]["total"] += rr_t

            # Per judge
            for judge in JUDGES:
                jm = [{"paper1_id": pk[0], "paper2_id": pk[1], "winner_id": data[pk][judge], "completed": True, "failed": False}
                      for pk in shared if pk in data and judge in data[pk]]
                if len(jm) < 10: continue

                j_rho = None
                try:
                    ai_lb = await compute_leaderboard_async(paper_list, jm)
                    h_lb = await compute_leaderboard_async(paper_list, hm)
                    ai_s = {e["id"]: e["score"] for e in ai_lb}
                    h_s = {e["id"]: e["score"] for e in h_lb}
                    ci = sorted(set(ai_s) & set(h_s))
                    if len(ci) >= 10:
                        j_rho = safe_round(scipy.stats.spearmanr([ai_s[x] for x in ci], [h_s[x] for x in ci])[0])
                except Exception: pass

                j_c = sum(1 for m in jm if tuple(sorted([m["paper1_id"], m["paper2_id"]])) in ep and m["winner_id"] == ep[tuple(sorted([m["paper1_id"], m["paper2_id"]]))])
                j_t = sum(1 for m in jm if tuple(sorted([m["paper1_id"], m["paper2_id"]])) in ep)
                j_acc = round(j_c / max(j_t, 1) * 100, 1)

                cell = {"summarizer": sum_name, "judge": judge, "rho": j_rho, "accuracy": j_acc, "correct": j_c, "total": j_t, "pairs": len(jm)}
                ds_cells.append(cell)
                key = f"{sum_name}|{judge}"
                if j_rho is not None: pooled_cells[key]["rho_vals"].append(j_rho)
                pooled_cells[key]["correct"] += j_c; pooled_cells[key]["total"] += j_t

        by_dataset[ds_id] = {"name": ds_names.get(ds_id, ds_id), "shared_pairs": len(shared), "cells": ds_cells}

    pooled = {}
    for key, v in pooled_cells.items():
        sum_name, judge = key.split("|")
        pooled[key] = {"summarizer": sum_name, "judge": judge,
                        "avg_rho": round(np.mean(v["rho_vals"]), 4) if v["rho_vals"] else None,
                        "accuracy": round(v["correct"] / max(v["total"], 1) * 100, 1),
                        "correct": v["correct"], "total": v["total"]}

    return {"status": "ok", "by_dataset": by_dataset, "pooled": pooled,
            "summarizers": list(SUM_MODES.keys()), "judges": ["Round-Robin"] + JUDGES}



@router.get("/summarizer-ab/results")
async def summarizer_ab_results():
    """Same-pair comparison — cached 1h."""
    import time as _t
    if sumab_results_cache["data"]:
        return sumab_results_cache["data"]
    result = await _compute_summarizer_ab_results()
    if result.get("status") == "ok":
        sumab_results_cache["data"] = result
        sumab_results_cache["ts"] = _t.time()
    return result


async def _compute_summarizer_ab_results():
    """Same-pair comparison of all summarizer models.

    CRITICAL: Pooled results only aggregate over datasets where ALL compared
    modes have data, so every summarizer row uses the exact same set of pairs.
    """
    SUM_MODES = {
        "Opus 4.5": "abstract_plus_summary",
        "Opus 4.6": "abstract_plus_summary:opus46",
        "Opus 4.6 Thinking": "abstract_plus_summary:thinking",
        "GPT-5.2": "abstract_plus_summary:gpt_summary",
        "Gemini 3 Pro": "abstract_plus_summary:gemini_summary",
    }

    # Only ICLR and eLife datasets (no Qeios, ResearchHub, etc.)
    ALLOWED_PREFIXES = ("iclr-", "elife-")

    datasets = ["iclr-llm", "iclr-codegen"]
    ds_meta = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {"iclr-llm": "ICLR LLM", "iclr-codegen": "ICLR Code Gen"}
    ds_names.update({d["dataset_id"]: d.get("name", d["dataset_id"]) for d in ds_meta})
    # Auto-discover ICLR/eLife datasets with summarizer data
    sum_modes_list = list(SUM_MODES.values())
    ds_pipeline = [
        {"$match": {"content_mode": {"$in": sum_modes_list}, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 30}}},
    ]
    extra = [r["_id"] async for r in db.validation_matches.aggregate(ds_pipeline)]
    for ds in extra:
        if ds not in datasets and any(ds.startswith(p) for p in ALLOWED_PREFIXES):
            datasets.append(ds)

    by_dataset = {}

    for ds_id in datasets:
        papers = await db.validation_papers.find({"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION).to_list(5000)
        paper_list = [{"id": p["id"], "title": p.get("title", "")} for p in papers]

        expert_ratings = build_expert_ratings(papers)
        expert_majority = build_expert_majority(expert_ratings)
        total_ep = sum(1 for exp, ratings in expert_ratings.items() for i, a in enumerate(ratings) for b in list(ratings)[i+1:] if ratings[a] != ratings[b])
        ep = expert_majority if len(expert_majority) >= max(20, total_ep * 0.1) else {}
        if not ep:
            for exp, ratings in expert_ratings.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        a, b = pids[i], pids[j]
                        if ratings[a] != ratings[b]:
                            ep[tuple(sorted([a, b]))] = a if ratings[a] > ratings[b] else b

        human_matches = []
        for exp, ratings in expert_ratings.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    if ratings[a] != ratings[b]:
                        human_matches.append({"paper1_id": a, "paper2_id": b,
                            "winner_id": a if ratings[a] > ratings[b] else b, "completed": True, "failed": False})

        mode_map = {}
        for name, cm in SUM_MODES.items():
            pairs = {}
            async for m in db.validation_matches.find(
                {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}, "content_mode": cm},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}):
                pairs[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m["winner_id"]
            if pairs:
                mode_map[name] = pairs

        # Find intersection of all available modes
        shared = None
        available_modes = []
        for name, pairs in mode_map.items():
            if len(pairs) < 30: continue
            available_modes.append(name)
            if shared is None: shared = set(pairs.keys())
            else: shared &= set(pairs.keys())

        if not shared or len(shared) < 20:
            continue

        ds_result = {"name": ds_names.get(ds_id, ds_id), "shared_pairs": len(shared), "modes": {}}
        for name in available_modes:
            matches_sub = [{"paper1_id": pk[0], "paper2_id": pk[1], "winner_id": mode_map[name][pk],
                            "completed": True, "failed": False} for pk in shared]
            # Ranking correlation
            rho = None
            try:
                ai_lb = await compute_leaderboard_async(paper_list, matches_sub)
                h_lb = await compute_leaderboard_async(paper_list, human_matches)
                ai_s = {e["id"]: e["score"] for e in ai_lb}
                h_s = {e["id"]: e["score"] for e in h_lb}
                common_ids = sorted(set(ai_s) & set(h_s))
                if len(common_ids) >= 10:
                    import scipy.stats
                    r, _ = scipy.stats.spearmanr([ai_s[c] for c in common_ids], [h_s[c] for c in common_ids])
                    rho = safe_round(r)
            except Exception:
                pass

            # Accuracy — only pairs where experts disagree (ties excluded)
            correct = total = 0
            for pk in shared:
                if pk in ep:
                    total += 1
                    if mode_map[name][pk] == ep[pk]: correct += 1
            acc = round(correct / max(total, 1) * 100, 1)
            expert_ties = len(shared) - total

            # Average matches per paper for this mode
            paper_match_count = defaultdict(int)
            for pk in shared:
                paper_match_count[pk[0]] += 1
                paper_match_count[pk[1]] += 1
            n_papers_involved = len(paper_match_count)
            avg_mpp = round(sum(paper_match_count.values()) / max(n_papers_involved, 1), 1)

            ds_result["modes"][name] = {"rho": rho, "accuracy": acc, "correct": correct, "total": total, "avg_mpp": avg_mpp, "papers": n_papers_involved, "expert_ties": expert_ties}

        by_dataset[ds_id] = ds_result

    if not by_dataset:
        return {"status": "no_data"}

    # --- Pooled aggregation: only over datasets where ALL modes have data ---
    # Step 1: Find which modes appear in which datasets
    mode_datasets = defaultdict(set)  # mode_name -> set of ds_ids
    for ds_id, ds in by_dataset.items():
        for mode_name in ds["modes"]:
            mode_datasets[mode_name].add(ds_id)

    # Step 2: For the pooled table, find the set of datasets where
    # ALL modes that appear in ≥2 datasets are present (intersection).
    # This ensures every row in the pooled table uses the exact same datasets/pairs.
    all_mode_names = sorted(mode_datasets.keys())
    # Only include modes present in ≥2 datasets (avoids single-dataset noise)
    poolable_modes = [m for m in all_mode_names if len(mode_datasets[m]) >= 2]
    if poolable_modes:
        # Datasets where ALL poolable modes have data
        pooled_ds = set.intersection(*(mode_datasets[m] for m in poolable_modes))
    else:
        pooled_ds = set()

    pooled_results = {}
    if pooled_ds:
        for mode_name in poolable_modes:
            rho_vals = []
            correct_sum = 0
            total_sum = 0
            mpp_vals = []
            for ds_id in pooled_ds:
                v = by_dataset[ds_id]["modes"].get(mode_name)
                if v:
                    if v.get("rho") is not None:
                        rho_vals.append(v["rho"])
                    correct_sum += v["correct"]
                    total_sum += v["total"]
                    if v.get("avg_mpp"):
                        mpp_vals.append(v["avg_mpp"])
            pooled_results[mode_name] = {
                "avg_rho": round(sum(rho_vals) / max(len(rho_vals), 1), 4) if rho_vals else None,
                "accuracy": round(correct_sum / max(total_sum, 1) * 100, 1),
                "correct": correct_sum, "total": total_sum,
                "datasets": len(rho_vals),
                "avg_mpp": round(sum(mpp_vals) / max(len(mpp_vals), 1), 1) if mpp_vals else 0,
            }

    return {"status": "ok", "by_dataset": by_dataset, "pooled": pooled_results,
            "pooled_datasets": sorted(pooled_ds), "pooled_modes": poolable_modes}


@router.post("/summarizer-ab/run", dependencies=[Depends(verify_admin)])
async def start_summarizer_ab(request: Request):
    global _sumab_task
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    dataset_id = body.get("dataset_id", "iclr-llm")
    summarizer = body.get("summarizer", "gpt")  # "gpt" or "gemini"
    num_pairs = body.get("num_pairs", 300)

    if _sumab_state["running"]:
        raise HTTPException(409, "Already running")
    if summarizer not in SUMMARIZER_MODELS:
        raise HTTPException(400, f"Invalid summarizer: {summarizer}")

    # Persist task in MongoDB so it survives restarts
    await _persist_sumab_task(dataset_id, summarizer, num_pairs, status="running")

    async def _bg():
        global _sumab_task
        try:
            await _run_summarizer_ab(dataset_id, summarizer, num_pairs)
            await _mark_sumab_complete(dataset_id, summarizer)
        except Exception as e:
            logger.error(f"Summarizer A/B failed: {e}")
            # Mark as queued so startup resume picks it up
            await _persist_sumab_task(dataset_id, summarizer, num_pairs, status="queued")
        finally:
            _sumab_state["running"] = False
            _sumab_task = None

    _sumab_task = asyncio.create_task(_bg())
    return {"status": "started", "dataset_id": dataset_id, "summarizer": summarizer, "num_pairs": num_pairs}


@router.post("/summarizer-ab/stop", dependencies=[Depends(verify_admin)])
async def stop_summarizer_ab():
    global _sumab_task
    _sumab_state["running"] = False
    if _sumab_task and not _sumab_task.done():
        _sumab_task.cancel()
    # Mark any running tasks as complete (user explicitly stopped)
    await db.summarizer_ab_tasks.update_many(
        {"status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "stopped", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "stopping"}


@router.get("/summarizer-ab/status")
async def summarizer_ab_status():
    # Include persistent queue info alongside in-memory state
    queue = await db.summarizer_ab_tasks.find({}, {"_id": 0}).to_list(100)
    return {**_sumab_state, "queue": queue}


@router.post("/summarizer-ab/queue-batch", dependencies=[Depends(verify_admin)])
async def queue_summarizer_ab_batch(request: Request):
    """Queue GPT+Gemini summary generation for specified datasets.

    Requires {"datasets": ["iclr-fairness", ...]}. No auto-detect — explicit list only.
    Also accepts {"summarizers": ["gpt"]} to limit to specific summarizers (default: both).
    """
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    requested_datasets = body.get("datasets", [])
    summarizers = body.get("summarizers", ["gpt", "gemini"])
    num_pairs = body.get("num_pairs", 300)

    if not requested_datasets:
        raise HTTPException(400, "datasets list is required")

    queued = []
    for ds_id in requested_datasets:
        for summarizer in summarizers:
            if summarizer not in SUMMARIZER_MODELS:
                continue
            # Skip if already complete
            existing = await db.summarizer_ab_tasks.find_one(
                {"dataset_id": ds_id, "summarizer": summarizer}, {"_id": 0, "status": 1}
            )
            if existing and existing.get("status") == "complete":
                continue
            await _persist_sumab_task(ds_id, summarizer, num_pairs, status="queued")
            queued.append(f"{ds_id}/{summarizer}")

    # Kick off the resume loop if not already running
    if queued and not _sumab_state["running"]:
        async def _bg():
            try:
                await resume_incomplete_summarizer_ab()
            except Exception as e:
                logger.error(f"Batch summarizer-ab failed: {e}")
        asyncio.create_task(_bg())

    return {"status": "queued", "queued": queued, "count": len(queued)}


async def _run_summarizer_ab(dataset_id: str, summarizer: str, num_pairs: int):
    """Generate summaries with GPT/Gemini, then run round-robin tournament on same pairs as opus46."""
    from services.llm import generate_precomparison_impact_summary, compare_papers, _pick_round_robin_model

    model_info = SUMMARIZER_MODELS[summarizer]
    sum_field = f"ai_impact_summary_{summarizer}"
    content_mode = f"abstract_plus_summary:{summarizer}_summary"

    _sumab_state.update({"running": True, "phase": "generating summaries", "done": 0, "total": 0,
                         "dataset_id": dataset_id, "summarizer": summarizer})

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}

    # Phase 1: Generate summaries for papers that don't have them yet
    need_summary = [p for p in papers if not p.get(sum_field)]
    _sumab_state["total"] = len(need_summary)
    logger.info(f"Summarizer A/B [{dataset_id}/{summarizer}]: generating {len(need_summary)} summaries")

    sem = asyncio.Semaphore(4)
    gen_done = 0

    async def _gen_one(p):
        nonlocal gen_done
        if not _sumab_state["running"]:
            return
        async with sem:
            try:
                result = await generate_precomparison_impact_summary(p, model_override=model_info)
                if result and result.get("summary"):
                    await db.validation_papers.update_one(
                        {"id": p["id"], "dataset_id": dataset_id},
                        {"$set": {sum_field: result["summary"]}}
                    )
                    lookup[p["id"]][sum_field] = result["summary"]
                    gen_done += 1
                    _sumab_state["done"] = gen_done
            except Exception as e:
                logger.warning(f"Summary gen failed for {p.get('title', '')[:40]}: {e}")

    await asyncio.gather(*[_gen_one(p) for p in need_summary], return_exceptions=True)

    # Phase 2: Run tournament on same pairs as opus46 baseline
    _sumab_state.update({"phase": "running matches", "done": 0})
    gt = build_paper_gt_scores(papers)

    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": content_mode, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Replay opus46 pairs
    baseline_pairs = []
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": "abstract_plus_summary:opus46", "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        pk = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pk in existing:
            continue
        g1, g2 = gt.get(m["paper1_id"]), gt.get(m["paper2_id"])
        if g1 is None or g2 is None or g1 == g2:
            continue
        baseline_pairs.append((m["paper1_id"], m["paper2_id"]))
        existing.add(pk)

    random.shuffle(baseline_pairs)
    to_run = baseline_pairs[:num_pairs]
    _sumab_state["total"] = len(to_run)
    logger.info(f"Summarizer A/B [{dataset_id}/{summarizer}]: running {len(to_run)} matches")

    match_sem = asyncio.Semaphore(8)
    completed = 0

    async def run_one(p1_id, p2_id):
        nonlocal completed
        if not _sumab_state["running"]:
            return
        async with match_sem:
            p1, p2 = lookup.get(p1_id, {}), lookup.get(p2_id, {})
            s1 = p1.get(sum_field, "")
            s2 = p2.get(sum_field, "")
            if not s1 or not s2:
                return
            p1c = {**p1, "ai_impact_summary": s1}
            p2c = {**p2, "ai_impact_summary": s2}
            judge = _pick_round_robin_model()
            if random.random() < 0.5:
                p1c, p2c = p2c, p1c
                p1_id, p2_id = p2_id, p1_id
            try:
                result = await compare_papers(p1c, p2c, content_mode="abstract_plus_summary", model_override=judge)
                if result and not result.get("failed"):
                    wk = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()),
                        "dataset_id": dataset_id,
                        "content_mode": content_mode,
                        "prompt_tag": f"{summarizer}_summary",
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
                    _sumab_state["done"] = completed
                    if completed % 50 == 0:
                        invalidate_all_caches(dataset_id)
            except Exception as e:
                logger.warning(f"Summarizer A/B match failed: {e}")

    await asyncio.gather(*[run_one(a, b) for a, b in to_run], return_exceptions=True)
    invalidate_all_caches(dataset_id)
    # Invalidate experiment caches so results page picks up new data
    sumab_results_cache["data"] = None
    ae_cache["data"] = None
    logger.info(f"Summarizer A/B [{dataset_id}/{summarizer}]: completed {completed}/{len(to_run)} matches")



# ─── Judge Comparison Analysis ─────────────────────────────────────────────────

_judge_comparison_cache = {"data": None}


@router.get("/judge-comparison/results")
async def judge_comparison_results():
    if _judge_comparison_cache["data"]:
        return _judge_comparison_cache["data"]
    result = await _compute_judge_comparison()
    if result.get("status") == "ok":
        _judge_comparison_cache["data"] = result
    return result


async def _compute_judge_comparison():
    """Compare judge accuracy and ranking correlation on identical pairs.

    Uses pairs where ALL 4 judges evaluated the same pair on abstract_plus_summary mode.
    Round-robin simulated by randomly selecting one judge per pair (100 trials).
    """
    import random as _random
    from collections import defaultdict

    JUDGE_MODELS = {
        "gpt-5.2": "GPT-5.2",
        "claude-opus-4-5-20251101": "Opus 4.5",
        "claude-opus-4-6": "Opus 4.6",
        "gemini-3-pro-preview": "Gemini 3 Pro",
    }
    ALL_JUDGES = ["Opus 4.6", "Opus 4.5", "GPT-5.2", "Gemini 3 Pro"]
    CYCLE_RATES = {"Opus 4.6": 0.61, "Gemini 3 Pro": 1.13, "Opus 4.5": 1.23, "GPT-5.2": 1.68}

    DATASETS = ["iclr-llm", "iclr-codegen", "iclr-pdes", "iclr-ot", "iclr-fairness",
                 "iclr-protein", "iclr-molecules", "iclr-optimization"]

    judge_acc = {j: {"correct": 0, "total": 0} for j in ALL_JUDGES}
    judge_rhos = {j: [] for j in ALL_JUDGES}
    rr_acc = {"correct": 0, "total": 0}
    rr_rhos = []
    mv_acc = {"correct": 0, "total": 0}
    mv_rhos = []
    per_dataset = []

    for ds_id in DATASETS:
        papers = await db.validation_papers.find({"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION).to_list(500)
        if not papers:
            continue
        paper_lookup = {p["id"]: p for p in papers}

        # Ground truth
        er = build_expert_ratings(papers)
        em = build_expert_majority(er)
        total_ep = sum(1 for exp, ratings in er.items()
                       for i, a in enumerate(ratings) for b in list(ratings)[i+1:]
                       if ratings[a] != ratings[b])
        ep = em if len(em) >= max(20, total_ep * 0.1) else {}
        if not ep:
            for exp, ratings in er.items():
                pids = list(ratings.keys())
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        a, b = pids[i], pids[j]
                        if ratings[a] != ratings[b]:
                            ep[tuple(sorted([a, b]))] = a if ratings[a] > ratings[b] else b
        if len(ep) < 20:
            continue

        # Human BT ranking
        human_matches = []
        for exp, ratings in er.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    if ratings[a] != ratings[b]:
                        human_matches.append({"paper1_id": a, "paper2_id": b,
                            "winner_id": a if ratings[a] > ratings[b] else b,
                            "completed": True, "failed": False})
        h_ids = {m["paper1_id"] for m in human_matches} | {m["paper2_id"] for m in human_matches}
        h_papers = [p for p in papers if p["id"] in h_ids]
        gt_lb = compute_leaderboard(h_papers, human_matches)
        gt_rank = {e["id"]: e["rank"] for e in gt_lb}

        # Matches per judge
        judge_verdicts = {j: {} for j in ALL_JUDGES}
        async for m in db.validation_matches.find(
            {"dataset_id": ds_id, "content_mode": "abstract_plus_summary",
             "completed": True, "failed": {"$ne": True}, "model_used.model": {"$exists": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used.model": 1}
        ):
            judge = JUDGE_MODELS.get(m["model_used"]["model"])
            if judge:
                pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
                judge_verdicts[judge][pair] = m["winner_id"]

        # 4-judge intersection with GT
        sets_4 = [set(judge_verdicts[j].keys()) for j in ALL_JUDGES]
        if not all(sets_4):
            continue
        common = set.intersection(*sets_4) & set(ep.keys())
        if len(common) < 20:
            continue

        # Cap at 200 pairs per dataset for balanced comparison
        MAX_PAIRS_PER_DS = 200
        if len(common) > MAX_PAIRS_PER_DS:
            _rng = _random.Random(42 + hash(ds_id))  # deterministic per dataset
            common = set(_rng.sample(sorted(common), MAX_PAIRS_PER_DS))

        common_paper_ids = set()
        for p in common:
            common_paper_ids.add(p[0])
            common_paper_ids.add(p[1])
        common_papers = [paper_lookup[pid] for pid in common_paper_ids if pid in paper_lookup]

        # Average matches per paper
        paper_match_count = defaultdict(int)
        for p in common:
            paper_match_count[p[0]] += 1
            paper_match_count[p[1]] += 1
        ds_avg_mpp = round(sum(paper_match_count.values()) / max(len(paper_match_count), 1), 1)

        ds_row = {"dataset_id": ds_id, "name": ds_id.replace("iclr-", "ICLR ").replace("-", " ").title(), "pairs": len(common), "avg_mpp": ds_avg_mpp}

        # Per-judge accuracy + rho
        for judge in ALL_JUDGES:
            jv = judge_verdicts[judge]
            correct = sum(1 for p in common if jv.get(p) == ep[p])
            judge_acc[judge]["correct"] += correct
            judge_acc[judge]["total"] += len(common)

            j_matches = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": jv[p],
                          "completed": True, "failed": False} for p in common]
            ai_lb = compute_leaderboard(common_papers, j_matches)
            ai_rank = {e["id"]: e["rank"] for e in ai_lb}
            shared_ids = sorted(set(ai_rank) & set(gt_rank))
            if len(shared_ids) >= 5:
                rho, _ = scipy_stats.spearmanr([ai_rank[pid] for pid in shared_ids],
                                                [gt_rank[pid] for pid in shared_ids])
                if not np.isnan(rho):
                    judge_rhos[judge].append(rho)

            key = judge.lower().replace(" ", "").replace(".", "").replace("-", "")
            ds_row[f"{key}_acc"] = round(correct / len(common) * 100, 1)

        # Round-robin simulation (100 trials)
        trial_accs = []
        trial_rhos = []
        for _ in range(100):
            rr_matches_trial = []
            rr_correct_trial = 0
            for pair in common:
                judge = _random.choice(ALL_JUDGES)
                winner = judge_verdicts[judge][pair]
                rr_matches_trial.append({"paper1_id": pair[0], "paper2_id": pair[1],
                    "winner_id": winner, "completed": True, "failed": False})
                if winner == ep[pair]:
                    rr_correct_trial += 1
            trial_accs.append(rr_correct_trial / len(common) * 100)
            rr_lb = compute_leaderboard(common_papers, rr_matches_trial)
            rr_rank = {e["id"]: e["rank"] for e in rr_lb}
            shared_ids = sorted(set(rr_rank) & set(gt_rank))
            if len(shared_ids) >= 5:
                rho, _ = scipy_stats.spearmanr([rr_rank[pid] for pid in shared_ids],
                                                [gt_rank[pid] for pid in shared_ids])
                if not np.isnan(rho):
                    trial_rhos.append(rho)

        avg_rr_acc = np.mean(trial_accs)
        rr_acc["correct"] += int(avg_rr_acc * len(common) / 100)
        rr_acc["total"] += len(common)
        if trial_rhos:
            rr_rhos.append(np.mean(trial_rhos))
        ds_row["rr_acc"] = round(avg_rr_acc, 1)

        # Majority vote
        mv_correct_ds = 0
        mv_matches_ds = []
        for pair in common:
            votes = defaultdict(int)
            for judge in ALL_JUDGES:
                votes[judge_verdicts[judge][pair]] += 1
            winner = max(votes, key=votes.get)
            mv_matches_ds.append({"paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": winner, "completed": True, "failed": False})
            if winner == ep[pair]:
                mv_correct_ds += 1
        mv_acc["correct"] += mv_correct_ds
        mv_acc["total"] += len(common)
        mv_lb = compute_leaderboard(common_papers, mv_matches_ds)
        mv_rank = {e["id"]: e["rank"] for e in mv_lb}
        shared_ids = sorted(set(mv_rank) & set(gt_rank))
        if len(shared_ids) >= 5:
            rho, _ = scipy_stats.spearmanr([mv_rank[pid] for pid in shared_ids],
                                            [gt_rank[pid] for pid in shared_ids])
            if not np.isnan(rho):
                mv_rhos.append(rho)
        ds_row["mv_acc"] = round(mv_correct_ds / len(common) * 100, 1)

        # Rename keys for frontend
        ds_row["opus46_acc"] = ds_row.pop("opus46_acc", None)
        ds_row["opus45_acc"] = ds_row.pop("opus45_acc", None)
        ds_row["gpt52_acc"] = ds_row.pop("gpt52_acc", None)
        ds_row["gemini3pro_acc"] = ds_row.pop("gemini3pro_acc", None)
        per_dataset.append(ds_row)

    total_pairs = judge_acc["Opus 4.6"]["total"]
    if total_pairs < 50:
        return {"status": "no_data"}

    # Pooled avg matches per paper
    pooled_avg_mpp = round(np.mean([ds["avg_mpp"] for ds in per_dataset if ds.get("avg_mpp")]), 1) if per_dataset else 0

    # Build judge results
    judges = []
    for j in ALL_JUDGES:
        s = judge_acc[j]
        rhos = judge_rhos[j]
        judges.append({
            "name": j,
            "cycle_rate": CYCLE_RATES.get(j),
            "accuracy": round(s["correct"] / s["total"] * 100, 1),
            "avg_rho": round(np.mean(rhos), 3) if rhos else 0,
            "total_pairs": s["total"],
            "avg_mpp": pooled_avg_mpp,
            "n_datasets": len(rhos),
        })

    # Correlations
    rates = [CYCLE_RATES[j] for j in ALL_JUDGES]
    accs = [judge_acc[j]["correct"] / judge_acc[j]["total"] * 100 for j in ALL_JUDGES]
    rhos_avg = [np.mean(judge_rhos[j]) if judge_rhos[j] else 0 for j in ALL_JUDGES]
    acc_sr, acc_sp = scipy_stats.spearmanr(rates, accs)
    rho_sr, rho_sp = scipy_stats.spearmanr(rates, rhos_avg)

    return {
        "status": "ok",
        "total_pairs": total_pairs,
        "n_datasets": len(per_dataset),
        "judges": judges,
        "round_robin": {
            "accuracy": round(rr_acc["correct"] / rr_acc["total"] * 100, 1),
            "avg_rho": round(np.mean(rr_rhos), 3) if rr_rhos else 0,
            "total_pairs": rr_acc["total"],
            "avg_mpp": pooled_avg_mpp,
        },
        "majority_vote": {
            "accuracy": round(mv_acc["correct"] / mv_acc["total"] * 100, 1),
            "avg_rho": round(np.mean(mv_rhos), 3) if mv_rhos else 0,
            "total_pairs": mv_acc["total"],
            "avg_mpp": pooled_avg_mpp,
        },
        "cycle_correlation": {
            "acc_spearman_r": round(acc_sr, 3) if not np.isnan(acc_sr) else 0,
            "acc_spearman_p": round(acc_sp, 3) if not np.isnan(acc_sp) else 1,
            "rho_spearman_r": round(rho_sr, 3) if not np.isnan(rho_sr) else 0,
            "rho_spearman_p": round(rho_sp, 3) if not np.isnan(rho_sp) else 1,
        },
        "per_dataset": per_dataset,
    }
