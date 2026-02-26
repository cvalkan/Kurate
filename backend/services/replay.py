"""
Match Replay Pipeline — Deeper Dive Experiment Phase 2

Replays existing ICLR validation matches under three conditions:
  1. Control: Same original assessments, re-run (measures LLM stochasticity)
  2. Treatment: Enhanced assessments where available, original otherwise
  
Compares verdict flip rates between control and treatment to isolate
the effect of deeper analysis from random LLM variance.

Statistical analysis: McNemar's test, human agreement lift, per-category breakdown.
"""
import asyncio
import uuid
import random
import json
import re
from datetime import datetime, timezone
from collections import defaultdict, Counter
from typing import Optional
from core.config import db, logger


# --- Configuration ---

# Which ICLR datasets to replay
REPLAY_DATASETS = [
    "iclr-codegen", "iclr-fairness", "iclr-llm", "iclr-molecules",
    "iclr-optimization", "iclr-ot", "iclr-pdes", "iclr-protein",
]

# Source content modes to replay (Opus 4.5 and 4.6 experiments)
SOURCE_MODES = ["abstract_plus_summary", "abstract_plus_summary:opus46"]

# How many matches to replay per condition (None = all available)
MAX_MATCHES_PER_CONDITION = None

# Collection for storing replay results
REPLAY_COLLECTION = "deeper_dive_replays"


# --- Pair Selection ---

async def select_replay_pairs(max_pairs: int = None) -> dict:
    """Select match pairs to replay, stratified by deeper-dive recommendation status.
    
    Returns:
        {
            "pairs": [{"paper1_id", "paper2_id", "dataset_id", "original_winner_id",
                        "original_match_id", "content_mode", "stratum", "human_ground_truth"}],
            "strata": {"both_recommended": N, "one_recommended": N, "neither_recommended": N},
            "papers": {paper_id: {"has_enhanced": bool, "recommended": bool, "decision": str}}
        }
    """
    # Load deeper dive experiment results to know which papers are recommended
    experiment = await db.settings.find_one({"key": "deeper_dive_experiment"}, {"_id": 0})
    experiment_results = experiment.get("results", []) if experiment else []
    
    # Build lookup: title -> recommendation status + enhanced assessment
    recommended_titles = set()
    enhanced_titles = {}
    for r in experiment_results:
        if r.get("parse_ok") and r.get("deeper_dive_recommended"):
            recommended_titles.add(r["title"])
            if r.get("enhanced_assessment"):
                enhanced_titles[r["title"]] = r["enhanced_assessment"]

    # Load all ICLR validation papers
    paper_lookup = {}  # id -> paper data
    title_to_id = {}
    async for p in db.validation_papers.find(
        {"dataset_id": {"$in": REPLAY_DATASETS}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "decision": 1, "dataset_id": 1,
         "ai_impact_summary_claude": 1, "ai_impact_summary_opus46": 1, "ai_impact_summary": 1},
    ):
        paper_lookup[p["id"]] = p
        title_to_id[p["title"]] = p["id"]

    # Map recommendation status to validation paper IDs
    paper_meta = {}
    for pid, p in paper_lookup.items():
        title = p["title"]
        is_rec = title in recommended_titles
        has_enhanced = title in enhanced_titles
        paper_meta[pid] = {
            "recommended": is_rec,
            "has_enhanced": has_enhanced,
            "enhanced_assessment": enhanced_titles.get(title),
            "decision": p.get("decision", ""),
        }

    # Load existing matches to replay
    match_query = {
        "completed": True,
        "failed": {"$ne": True},
        "dataset_id": {"$in": REPLAY_DATASETS},
        "content_mode": {"$in": SOURCE_MODES},
    }
    matches = await db.validation_matches.find(match_query, {"_id": 0}).to_list(50000)

    # Deduplicate pairs (same two papers may have been compared multiple times)
    seen_pairs = set()
    pairs = []
    for m in matches:
        p1, p2 = m["paper1_id"], m["paper2_id"]
        pair_key = tuple(sorted([p1, p2])) + (m.get("content_mode", ""),)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        if p1 not in paper_meta or p2 not in paper_meta:
            continue

        # Determine stratum
        p1_rec = paper_meta[p1]["recommended"]
        p2_rec = paper_meta[p2]["recommended"]
        if p1_rec and p2_rec:
            stratum = "both_recommended"
        elif p1_rec or p2_rec:
            stratum = "one_recommended"
        else:
            stratum = "neither_recommended"

        # Human ground truth: which paper has higher ICLR acceptance tier?
        human_gt = _compute_human_ground_truth(
            paper_lookup.get(p1, {}), paper_lookup.get(p2, {})
        )

        pairs.append({
            "paper1_id": p1,
            "paper2_id": p2,
            "dataset_id": m["dataset_id"],
            "content_mode": m.get("content_mode", "abstract_plus_summary"),
            "original_winner_id": m.get("winner_id"),
            "original_match_id": m["id"],
            "stratum": stratum,
            "human_ground_truth": human_gt,  # "paper1" | "paper2" | "tie" | "unknown"
        })

    random.shuffle(pairs)
    if max_pairs:
        pairs = pairs[:max_pairs]

    strata = Counter(p["stratum"] for p in pairs)

    return {
        "pairs": pairs,
        "strata": dict(strata),
        "paper_meta": paper_meta,
    }


# ICLR decision tier ordering (higher = better)
_DECISION_TIER = {
    "accept (oral)": 4,
    "accept (spotlight)": 3,
    "accept (poster)": 2,
    "withdrawn": 1,
    "desk rejected": 0,
    "reject": 0,
}


def _compute_human_ground_truth(paper1: dict, paper2: dict) -> str:
    """Determine which paper humans ranked higher based on ICLR acceptance tier."""
    d1 = _DECISION_TIER.get(paper1.get("decision", "").lower().strip(), -1)
    d2 = _DECISION_TIER.get(paper2.get("decision", "").lower().strip(), -1)
    if d1 < 0 or d2 < 0:
        return "unknown"
    if d1 > d2:
        return "paper1"
    elif d2 > d1:
        return "paper2"
    return "tie"


# --- Match Replay ---

async def replay_match(
    paper1: dict, paper2: dict,
    condition: str,  # "control" or "treatment"
    paper_meta: dict,
    prompt_config: dict = None,
) -> dict:
    """Replay a single match under the given condition.
    
    - control: uses original assessments (ai_impact_summary_claude or ai_impact_summary_opus46)
    - treatment: uses enhanced assessment where available, original otherwise
    """
    from services.llm import compare_papers
    from core.config import DEFAULT_EVALUATION_PROMPT

    if prompt_config is None:
        prompt_config = DEFAULT_EVALUATION_PROMPT

    # Build paper dicts with the appropriate summary
    def _get_assessment(paper, meta):
        if condition == "treatment" and meta.get("enhanced_assessment"):
            return meta["enhanced_assessment"]
        # Fall back to original assessment
        return (paper.get("ai_impact_summary_opus46")
                or paper.get("ai_impact_summary_claude")
                or paper.get("ai_impact_summary")
                or paper.get("abstract", "")[:1500])

    meta1 = paper_meta.get(paper1["id"], {})
    meta2 = paper_meta.get(paper2["id"], {})

    p1_with_summary = {**paper1, "ai_impact_summary": _get_assessment(paper1, meta1)}
    p2_with_summary = {**paper2, "ai_impact_summary": _get_assessment(paper2, meta2)}

    result = await compare_papers(
        p1_with_summary, p2_with_summary,
        prompt_config=prompt_config,
        content_mode="abstract_plus_summary",
    )

    winner_id = paper1["id"] if result["winner"] == "paper1" else paper2["id"]

    return {
        "winner_id": winner_id,
        "winner": result["winner"],
        "reasoning": result.get("reasoning", ""),
        "model_used": result.get("model_used", {}),
        "tokens": result.get("tokens", {}),
        "condition": condition,
        "p1_used_enhanced": condition == "treatment" and bool(meta1.get("enhanced_assessment")),
        "p2_used_enhanced": condition == "treatment" and bool(meta2.get("enhanced_assessment")),
    }


async def run_replay_experiment(
    max_pairs: int = 200,
    conditions: list = None,
    parallel: int = 3,
):
    """Run the full replay experiment.
    
    Args:
        max_pairs: Max pairs to replay per condition
        conditions: ["control", "treatment"] or subset
        parallel: Concurrent LLM calls
    """
    if conditions is None:
        conditions = ["control", "treatment"]

    logger.info(f"Replay experiment starting: max_pairs={max_pairs}, conditions={conditions}")

    # Select pairs
    selection = await select_replay_pairs(max_pairs=max_pairs)
    pairs = selection["pairs"]
    paper_meta = selection["paper_meta"]

    logger.info(f"Selected {len(pairs)} pairs. Strata: {selection['strata']}")

    # Load paper data for selected pairs
    paper_ids = set()
    for p in pairs:
        paper_ids.add(p["paper1_id"])
        paper_ids.add(p["paper2_id"])

    papers = {}
    async for p in db.validation_papers.find(
        {"id": {"$in": list(paper_ids)}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "decision": 1, "dataset_id": 1,
         "ai_impact_summary_claude": 1, "ai_impact_summary_opus46": 1, "ai_impact_summary": 1},
    ):
        papers[p["id"]] = p

    # Initialize progress tracking
    total_replays = len(pairs) * len(conditions)
    await db.settings.update_one(
        {"key": "replay_progress"},
        {"$set": {"key": "replay_progress", "running": True, "done": 0,
                  "total": total_replays, "errors": 0,
                  "strata": selection["strata"],
                  "conditions": conditions}},
        upsert=True,
    )

    sem = asyncio.Semaphore(parallel)
    results = []
    done = 0
    errors = 0

    for pair in pairs:
        p1 = papers.get(pair["paper1_id"])
        p2 = papers.get(pair["paper2_id"])
        if not p1 or not p2:
            continue

        for condition in conditions:
            async with sem:
                try:
                    replay_result = await replay_match(p1, p2, condition, paper_meta)

                    record = {
                        "id": str(uuid.uuid4()),
                        "pair_id": pair["original_match_id"],
                        "paper1_id": pair["paper1_id"],
                        "paper2_id": pair["paper2_id"],
                        "dataset_id": pair["dataset_id"],
                        "content_mode": pair["content_mode"],
                        "stratum": pair["stratum"],
                        "human_ground_truth": pair["human_ground_truth"],
                        "original_winner_id": pair["original_winner_id"],
                        "replay_winner_id": replay_result["winner_id"],
                        "flipped": replay_result["winner_id"] != pair["original_winner_id"],
                        "condition": condition,
                        "reasoning": replay_result["reasoning"],
                        "model_used": replay_result["model_used"],
                        "tokens": replay_result["tokens"],
                        "p1_used_enhanced": replay_result["p1_used_enhanced"],
                        "p2_used_enhanced": replay_result["p2_used_enhanced"],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }

                    # Check agreement with human ground truth
                    if pair["human_ground_truth"] in ("paper1", "paper2"):
                        gt_winner = pair["paper1_id"] if pair["human_ground_truth"] == "paper1" else pair["paper2_id"]
                        record["original_agrees_human"] = pair["original_winner_id"] == gt_winner
                        record["replay_agrees_human"] = replay_result["winner_id"] == gt_winner

                    results.append(record)
                    await db[REPLAY_COLLECTION].insert_one({**record, "_id": None})

                except Exception as e:
                    errors += 1
                    logger.warning(f"Replay failed: {pair['original_match_id']} [{condition}]: {e}")

                done += 1
                if done % 10 == 0:
                    await db.settings.update_one(
                        {"key": "replay_progress"},
                        {"$set": {"done": done, "errors": errors}},
                    )

    # Compute and save analysis
    analysis = compute_replay_analysis(results)

    await db.settings.update_one(
        {"key": "replay_results"},
        {"$set": {"key": "replay_results", "analysis": analysis,
                  "total_replays": len(results),
                  "completed_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    await db.settings.update_one(
        {"key": "replay_progress"},
        {"$set": {"running": False, "done": done, "errors": errors}},
    )

    logger.info(f"Replay experiment complete: {len(results)} replays, {errors} errors")
    return analysis


# --- Statistical Analysis ---

def compute_replay_analysis(results: list) -> dict:
    """Compute statistical analysis of replay results."""
    control = [r for r in results if r["condition"] == "control"]
    treatment = [r for r in results if r["condition"] == "treatment"]

    analysis = {
        "total_replays": len(results),
        "control_count": len(control),
        "treatment_count": len(treatment),
    }

    # --- Flip rates ---
    control_flips = sum(1 for r in control if r["flipped"])
    treatment_flips = sum(1 for r in treatment if r["flipped"])

    analysis["flip_rates"] = {
        "control": round(control_flips / max(len(control), 1) * 100, 1),
        "treatment": round(treatment_flips / max(len(treatment), 1) * 100, 1),
        "control_flips": control_flips,
        "treatment_flips": treatment_flips,
        "net_effect": round(
            (treatment_flips / max(len(treatment), 1) - control_flips / max(len(control), 1)) * 100, 1
        ),
    }

    # --- Flip rates by stratum ---
    strata_analysis = {}
    for stratum in ["both_recommended", "one_recommended", "neither_recommended"]:
        c = [r for r in control if r["stratum"] == stratum]
        t = [r for r in treatment if r["stratum"] == stratum]
        c_flips = sum(1 for r in c if r["flipped"])
        t_flips = sum(1 for r in t if r["flipped"])
        strata_analysis[stratum] = {
            "control": {"total": len(c), "flips": c_flips, "rate": round(c_flips / max(len(c), 1) * 100, 1)},
            "treatment": {"total": len(t), "flips": t_flips, "rate": round(t_flips / max(len(t), 1) * 100, 1)},
        }
    analysis["by_stratum"] = strata_analysis

    # --- Human agreement ---
    def _agreement_stats(matches):
        with_gt = [r for r in matches if "original_agrees_human" in r]
        if not with_gt:
            return {"total": 0, "original_agreement": 0, "replay_agreement": 0}
        orig_agree = sum(1 for r in with_gt if r.get("original_agrees_human"))
        replay_agree = sum(1 for r in with_gt if r.get("replay_agrees_human"))
        return {
            "total": len(with_gt),
            "original_agreement": round(orig_agree / len(with_gt) * 100, 1),
            "replay_agreement": round(replay_agree / len(with_gt) * 100, 1),
            "lift": round((replay_agree - orig_agree) / len(with_gt) * 100, 1),
        }

    analysis["human_agreement"] = {
        "control": _agreement_stats(control),
        "treatment": _agreement_stats(treatment),
    }

    # --- McNemar's test ---
    # For paired binary outcomes: did the verdict flip?
    # Compare control vs treatment for the same pairs
    control_by_pair = {r["pair_id"]: r["flipped"] for r in control}
    treatment_by_pair = {r["pair_id"]: r["flipped"] for r in treatment}

    # Build contingency: control_flip/no_flip × treatment_flip/no_flip
    common_pairs = set(control_by_pair.keys()) & set(treatment_by_pair.keys())
    a = sum(1 for p in common_pairs if control_by_pair[p] and treatment_by_pair[p])      # both flip
    b = sum(1 for p in common_pairs if control_by_pair[p] and not treatment_by_pair[p])   # only control flips
    c = sum(1 for p in common_pairs if not control_by_pair[p] and treatment_by_pair[p])   # only treatment flips
    d = sum(1 for p in common_pairs if not control_by_pair[p] and not treatment_by_pair[p])  # neither flips

    analysis["mcnemar"] = {
        "common_pairs": len(common_pairs),
        "both_flip": a,
        "only_control_flips": b,
        "only_treatment_flips": c,
        "neither_flips": d,
    }

    # McNemar's chi-squared statistic
    if b + c > 0:
        chi2 = (abs(b - c) - 1) ** 2 / (b + c)  # with continuity correction
        # Approximate p-value from chi2 with 1 df
        # Using normal approximation: p ≈ erfc(sqrt(chi2/2))
        import math
        p_value = math.erfc(math.sqrt(chi2 / 2))
        analysis["mcnemar"]["chi2"] = round(chi2, 3)
        analysis["mcnemar"]["p_value"] = round(p_value, 4)
        analysis["mcnemar"]["significant"] = p_value < 0.05
    else:
        analysis["mcnemar"]["chi2"] = 0
        analysis["mcnemar"]["p_value"] = 1.0
        analysis["mcnemar"]["significant"] = False

    # --- Flip directionality (toward or away from human GT) ---
    flips_toward_human = 0
    flips_away_from_human = 0
    for r in treatment:
        if not r["flipped"] or r.get("human_ground_truth") not in ("paper1", "paper2"):
            continue
        gt_winner = r["paper1_id"] if r["human_ground_truth"] == "paper1" else r["paper2_id"]
        orig_correct = r["original_winner_id"] == gt_winner
        replay_correct = r["replay_winner_id"] == gt_winner
        if not orig_correct and replay_correct:
            flips_toward_human += 1
        elif orig_correct and not replay_correct:
            flips_away_from_human += 1

    analysis["flip_direction"] = {
        "toward_human": flips_toward_human,
        "away_from_human": flips_away_from_human,
        "net_toward": flips_toward_human - flips_away_from_human,
    }

    # --- Per-dataset breakdown ---
    by_dataset = {}
    for ds in set(r["dataset_id"] for r in results):
        ds_control = [r for r in control if r["dataset_id"] == ds]
        ds_treatment = [r for r in treatment if r["dataset_id"] == ds]
        by_dataset[ds] = {
            "control_flips": sum(1 for r in ds_control if r["flipped"]),
            "control_total": len(ds_control),
            "treatment_flips": sum(1 for r in ds_treatment if r["flipped"]),
            "treatment_total": len(ds_treatment),
            "human_agreement_control": _agreement_stats(ds_control),
            "human_agreement_treatment": _agreement_stats(ds_treatment),
        }
    analysis["by_dataset"] = by_dataset

    return analysis
