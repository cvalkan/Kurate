"""
Unified Human vs AI Benchmark — Full-Data Comparison

Evaluates PW and SI each on their OWN full data against the same GT (h1_avg_rating).
This is the practically relevant comparison: "what ranking does each method produce
with the data it naturally generates?"

PW: evaluated on all actual pairwise matches
SI: evaluated on all C(n,2) pairs from scored papers
Both compared against the same h1_avg_rating ground truth.
"""

import math
import numpy as np
from scipy import stats as scipy_stats
from collections import defaultdict, Counter
from fastapi import APIRouter, Query

from core.config import db, logger
from routers.validation_utils import (
    build_expert_ratings, build_content_mode_filter, safe_round,
    PAPER_LIGHT_PROJECTION, norm_tier,
    COMPARATIVE_GT_DATASETS, STANDALONE_GT_DATASETS,
)
from services.ranking import compute_leaderboard

router = APIRouter(prefix="/api/validation")

_unified_cache = {"comp": {"data": None}, "stan": {"data": None}}

TIER_SCORE = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}


def _rate(a, t):
    return round(a / max(t, 1) * 100, 1)


def _classify_difficulty(p1_id, p2_id, papers_by_id):
    p1 = papers_by_id.get(p1_id, {})
    p2 = papers_by_id.get(p2_id, {})
    t1 = norm_tier(p1.get("decision"))
    t2 = norm_tier(p2.get("decision"))
    if t1 is None or t2 is None:
        r1 = p1.get("h1_avg_rating")
        r2 = p2.get("h1_avg_rating")
        if r1 is not None and r2 is not None:
            gap = abs(r1 - r2)
            return "easy" if gap > 2 else ("medium" if gap >= 1 else "hard")
        return None
    gap = abs(TIER_SCORE.get(t1, -1) - TIER_SCORE.get(t2, -1))
    return "easy" if gap >= 2 else ("medium" if gap == 1 else "hard")


async def _compute_unified_dataset(dataset_id, gt_type):
    """Evaluate PW and SI each on their full data against h1_avg_rating GT."""
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id}, PAPER_LIGHT_PROJECTION
    ).to_list(5000)
    if not papers:
        return None

    papers_by_id = {p["id"]: p for p in papers}

    # GT: h1_avg_rating per paper
    gt = {}
    for p in papers:
        r = p.get("h1_avg_rating")
        if r is None:
            evals = p.get("evaluations", [])
            vals = [e["rating_value"] for e in evals if e.get("rating_value")]
            r = sum(vals) / len(vals) if vals else None
        if r is not None:
            gt[p["id"]] = r

    if len(gt) < 10:
        return None

    # --- PW: load pairwise matches using same mode selection as summary table ---
    sample_p = papers[0] if papers else {}
    sample_full = await db.validation_papers.find_one(
        {"id": sample_p.get("id"), "dataset_id": dataset_id},
        {"_id": 0, "ai_impact_summary_thinking": 1}
    ) if sample_p else None
    has_thinking = bool(sample_full and sample_full.get("ai_impact_summary_thinking"))
    pw_content_mode = "abstract_plus_summary:thinking" if has_thinking else "abstract_plus_summary"
    pw_count_check = await db.validation_matches.count_documents(
        {"dataset_id": dataset_id, "completed": True, "content_mode": pw_content_mode})
    if pw_count_check == 0:
        pw_content_mode = "abstract_plus_summary"

    pw_matches_raw = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": pw_content_mode},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)

    # PW accuracy: each match vs h1_avg_rating ordering
    pw_correct = pw_total = 0
    pw_diff = {lvl: [0, 0, 0] for lvl in ["easy", "medium", "hard"]}  # [correct, total, n_pairs]
    pw_pairs_seen = set()
    for m in pw_matches_raw:
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        if not w or p1 not in gt or p2 not in gt or gt[p1] == gt[p2]:
            continue
        pw_total += 1
        human_winner = p1 if gt[p1] > gt[p2] else p2
        if w == human_winner:
            pw_correct += 1
        pair = tuple(sorted([p1, p2]))
        if pair not in pw_pairs_seen:
            pw_pairs_seen.add(pair)
            diff = _classify_difficulty(p1, p2, papers_by_id)
            if diff:
                pw_diff[diff][2] += 1
        diff = _classify_difficulty(p1, p2, papers_by_id)
        if diff:
            pw_diff[diff][1] += 1
            if w == human_winner:
                pw_diff[diff][0] += 1

    # PW BT ranking vs h1_avg_rating (using BT score, matching summary table)
    pw_rho = None
    if pw_matches_raw:
        paper_dicts = [{"id": pid, "title": ""} for pid in gt]
        pw_bt_matches = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                          "winner_id": m["winner_id"], "completed": True, "failed": False}
                         for m in pw_matches_raw if m.get("winner_id")]
        if len(pw_bt_matches) >= 10:
            lb = compute_leaderboard(paper_dicts, pw_bt_matches)
            bt_scores = {e["id"]: e["score"] for e in lb}
            shared = sorted(set(bt_scores.keys()) & set(gt.keys()))
            if len(shared) >= 5:
                sp, _ = scipy_stats.spearmanr([bt_scores[p] for p in shared],
                                               [gt[p] for p in shared])
                if not np.isnan(sp):
                    pw_rho = safe_round(float(sp))

    # --- SI: all C(n,2) pairs from scored papers ---
    si_scores = {p["id"]: p.get("single_item_score") for p in papers
                 if p.get("single_item_score") is not None}

    # Fallback: if DB has no SI scores, try loading from precomputed cache
    if not si_scores:
        try:
            from routers.validation_experiments import _SINGLE_ITEM_CACHE
            si_cache = _SINGLE_ITEM_CACHE.get("data", {})
            if si_cache.get("status") == "ok":
                for ds_data in si_cache.get("datasets", []):
                    if ds_data.get("dataset_id") == dataset_id:
                        for p_data in ds_data.get("papers", []):
                            pid = p_data.get("id")
                            score = p_data.get("ai_score") or p_data.get("single_item_score")
                            if pid and score is not None and pid in gt:
                                si_scores[pid] = score
                        break
        except Exception:
            pass

    si_correct = si_total = 0
    si_diff = {lvl: [0, 0, 0] for lvl in ["easy", "medium", "hard"]}
    si_ids = sorted(set(si_scores.keys()) & set(gt.keys()))
    for i in range(len(si_ids)):
        for j in range(i + 1, len(si_ids)):
            a, b = si_ids[i], si_ids[j]
            if gt[a] == gt[b]:
                continue
            if si_scores[a] == si_scores[b]:
                continue  # SI tie
            si_total += 1
            human_winner = a if gt[a] > gt[b] else b
            si_winner = a if si_scores[a] > si_scores[b] else b
            if si_winner == human_winner:
                si_correct += 1
            diff = _classify_difficulty(a, b, papers_by_id)
            if diff:
                si_diff[diff][1] += 1
                si_diff[diff][2] += 1
                if si_winner == human_winner:
                    si_diff[diff][0] += 1

    # SI BT ranking vs h1_avg_rating (direct Spearman of scores)
    si_rho = None
    si_shared = sorted(set(si_scores.keys()) & set(gt.keys()))
    if len(si_shared) >= 5:
        sp, _ = scipy_stats.spearmanr([si_scores[p] for p in si_shared],
                                       [gt[p] for p in si_shared])
        if not np.isnan(sp):
            si_rho = safe_round(float(sp))

    if pw_total < 10 and si_total < 10:
        return None

    # --- Intersection: same-pair comparison (PW majority verdict vs SI on common pairs) ---
    pw_verdict = {}
    pw_pair_votes = defaultdict(list)
    for m in pw_matches_raw:
        if m.get("winner_id"):
            pw_pair_votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
    for pair, votes in pw_pair_votes.items():
        c = Counter(votes)
        pw_verdict[pair] = c.most_common(1)[0][0]

    si_verdict = {}
    for i in range(len(si_ids)):
        for j in range(i + 1, len(si_ids)):
            a, b = si_ids[i], si_ids[j]
            if si_scores[a] != si_scores[b]:
                si_verdict[tuple(sorted([a, b]))] = a if si_scores[a] > si_scores[b] else b

    common_pairs = set(pw_verdict.keys()) & set(si_verdict.keys())
    int_pw_correct = int_si_correct = int_total = 0
    int_gaps = []
    for pair in common_pairs:
        a, b = pair
        if a not in gt or b not in gt or gt[a] == gt[b]:
            continue
        int_total += 1
        human_winner = a if gt[a] > gt[b] else b
        int_gaps.append(abs(gt[a] - gt[b]))
        if pw_verdict[pair] == human_winner:
            int_pw_correct += 1
        if si_verdict[pair] == human_winner:
            int_si_correct += 1

    return {
        "dataset_id": dataset_id,
        "n_papers": len(gt),
        "pw": {
            "accuracy": _rate(pw_correct, pw_total),
            "correct": pw_correct, "total": pw_total,
            "pairs": len(pw_pairs_seen),
            "bt_rho": pw_rho,
            "mode": pw_content_mode,
            "by_difficulty": {lvl: {"rate": _rate(v[0], v[1]), "n_pairs": v[2]} for lvl, v in pw_diff.items()},
        },
        "si": {
            "accuracy": _rate(si_correct, si_total),
            "correct": si_correct, "total": si_total,
            "pairs": si_total,
            "n_scored": len(si_scores),
            "bt_rho": si_rho,
            "by_difficulty": {lvl: {"rate": _rate(v[0], v[1]), "n_pairs": v[2]} for lvl, v in si_diff.items()},
        },
        "intersection": {
            "pw_accuracy": _rate(int_pw_correct, int_total),
            "si_accuracy": _rate(int_si_correct, int_total),
            "pairs": int_total,
            "avg_h1_gap": round(float(np.mean(int_gaps)), 2) if int_gaps else 0,
        },
    }


@router.get("/unified-benchmark")
async def unified_benchmark(gt_type: str = Query("comp")):
    """Unified PW vs SI benchmark — each method on its full data."""
    from core.cache import get_cached, set_cached
    cache = _unified_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    cached = await get_cached(f"unified_benchmark_{gt_type}")
    if cached:
        _unified_cache[gt_type] = {"data": cached}
        return cached
    result = await _compute_unified_benchmark(gt_type)
    if result.get("status") == "ok":
        _unified_cache[gt_type] = {"data": result}
        await set_cached(f"unified_benchmark_{gt_type}", result)
    return result


async def _compute_unified_benchmark(gt_type):
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS

    ds_ids = [d for d in await db.validation_papers.distinct("dataset_id") if d in allowed]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    per_dataset = []
    pooled = {
        "pw_correct": 0, "pw_total": 0, "si_correct": 0, "si_total": 0,
        "pw_rhos": [], "si_rhos": [],
        "pw_papers": 0, "si_papers": 0,
        "pw_diff": {lvl: [0, 0, 0] for lvl in ["easy", "medium", "hard"]},
        "si_diff": {lvl: [0, 0, 0] for lvl in ["easy", "medium", "hard"]},
        "int_pw_correct": 0, "int_si_correct": 0, "int_total": 0,
    }

    for ds_id in ds_ids:
        result = await _compute_unified_dataset(ds_id, gt_type)
        if result is None:
            continue
        result["name"] = ds_names.get(ds_id, ds_id)
        per_dataset.append(result)

        pooled["pw_correct"] += result["pw"]["correct"]
        pooled["pw_total"] += result["pw"]["total"]
        pooled["si_correct"] += result["si"]["correct"]
        pooled["si_total"] += result["si"]["total"]
        pooled["pw_papers"] += result["n_papers"]
        pooled["si_papers"] += result["si"].get("n_scored", 0)

        intr = result.get("intersection", {})
        pooled["int_pw_correct"] += int(intr.get("pw_accuracy", 0) * intr.get("pairs", 0) / 100)
        pooled["int_si_correct"] += int(intr.get("si_accuracy", 0) * intr.get("pairs", 0) / 100)
        pooled["int_total"] += intr.get("pairs", 0)

        if result["pw"]["bt_rho"] is not None:
            pooled["pw_rhos"].append(result["pw"]["bt_rho"])
        if result["si"]["bt_rho"] is not None:
            pooled["si_rhos"].append(result["si"]["bt_rho"])

        for lvl in ["easy", "medium", "hard"]:
            for method, key in [("pw", "pw_diff"), ("si", "si_diff")]:
                dl = result[method].get("by_difficulty", {}).get(lvl, {})
                pooled[key][lvl][0] += int(dl.get("rate", 0) * dl.get("n_pairs", 0) / 100)
                pooled[key][lvl][1] += dl.get("n_pairs", 0)
                pooled[key][lvl][2] += dl.get("n_pairs", 0)

    if not per_dataset:
        return {"status": "no_data"}

    pw_rho_avg = safe_round(float(np.mean(pooled["pw_rhos"]))) if pooled["pw_rhos"] else None
    si_rho_avg = safe_round(float(np.mean(pooled["si_rhos"]))) if pooled["si_rhos"] else None

    return {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(per_dataset),
        "pooled": {
            "pw_accuracy": _rate(pooled["pw_correct"], pooled["pw_total"]),
            "si_accuracy": _rate(pooled["si_correct"], pooled["si_total"]),
            "pw_pairs": pooled["pw_total"],
            "si_pairs": pooled["si_total"],
            "pw_rho": pw_rho_avg,
            "si_rho": si_rho_avg,
            "by_difficulty": {
                lvl: {
                    "pw_rate": _rate(pooled["pw_diff"][lvl][0], pooled["pw_diff"][lvl][1]),
                    "si_rate": _rate(pooled["si_diff"][lvl][0], pooled["si_diff"][lvl][1]),
                    "pw_pairs": pooled["pw_diff"][lvl][2],
                    "si_pairs": pooled["si_diff"][lvl][2],
                }
                for lvl in ["easy", "medium", "hard"]
            },
            "intersection": {
                "pw_accuracy": _rate(pooled["int_pw_correct"], pooled["int_total"]),
                "si_accuracy": _rate(pooled["int_si_correct"], pooled["int_total"]),
                "pairs": pooled["int_total"],
            },
        },
        "per_dataset": per_dataset,
    }
