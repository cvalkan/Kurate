"""
Unified Human vs AI Benchmark

Computes PW and SI metrics on the EXACT SAME pair set per dataset,
enabling direct apples-to-apples comparison.

For each dataset, the controlled set is the 3-way intersection:
  GT has preference + PW match exists + SI scores exist (non-tie)
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


def _cohens_kappa(agree, total):
    if total == 0:
        return 0.0
    p_o = agree / total
    return (p_o - 0.5) / 0.5 if 0.5 < 1.0 else 0.0


def _rate(a, t):
    return round(a / max(t, 1) * 100, 1)


def _cf_rate(agree, nontie_total, tie_count):
    total = nontie_total + tie_count
    if total == 0:
        return None
    return round((agree + 0.5 * tie_count) / total * 100, 1)


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
    """Compute unified PW+SI benchmark on the 3-way intersection for one dataset."""
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id},
        PAPER_LIGHT_PROJECTION
    ).to_list(5000)
    if not papers:
        return None

    papers_by_id = {p["id"]: p for p in papers}

    # --- GT preferences ---
    if gt_type == "comp":
        expert_ratings = build_expert_ratings(papers)
        experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}
        if len(experts_with_data) < 2:
            return None
        # Expert pair preferences (non-tie)
        expert_pair_prefs = defaultdict(dict)
        for exp, ratings in experts_with_data.items():
            rated_ids = list(ratings.keys())
            for i in range(len(rated_ids)):
                for j in range(i + 1, len(rated_ids)):
                    a, b = rated_ids[i], rated_ids[j]
                    if ratings[a] == ratings[b]:
                        continue
                    pair = tuple(sorted([a, b]))
                    expert_pair_prefs[pair][exp] = a if ratings[a] > ratings[b] else b
        # Expert majority
        expert_majority = {}
        for pair, votes in expert_pair_prefs.items():
            if len(votes) < 2:
                continue
            c = Counter(votes.values())
            best, n = c.most_common(1)[0]
            if n > len(votes) / 2:
                expert_majority[pair] = best
        gt_pairs = {p for p in expert_pair_prefs if len(expert_pair_prefs[p]) >= 2}
    else:
        # Standalone GT: h1_avg_rating
        expert_pair_prefs = None
        expert_majority = None
        experts_with_data = None
        gt_pairs = set()
        paper_ids = sorted(p["id"] for p in papers if p.get("h1_avg_rating") is not None)
        gt_verdict = {}
        for i in range(len(paper_ids)):
            for j in range(i + 1, len(paper_ids)):
                a, b = paper_ids[i], paper_ids[j]
                ra = papers_by_id[a]["h1_avg_rating"]
                rb = papers_by_id[b]["h1_avg_rating"]
                if ra != rb:
                    pair = tuple(sorted([a, b]))
                    gt_pairs.add(pair)
                    gt_verdict[pair] = a if ra > rb else b

    # --- PW AI preferences ---
    PREFERRED_MODES = ["abstract_plus_summary:opus46", "abstract_plus_summary:thinking", "abstract_plus_summary"]
    pw_pair = {}
    for mode in PREFERRED_MODES:
        mode_filter = build_content_mode_filter(mode)
        ai_raw = await db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}, **mode_filter},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ).to_list(100000)
        if len(ai_raw) >= 20:
            pw_votes = defaultdict(list)
            for m in ai_raw:
                if m.get("winner_id"):
                    pw_votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
            for pair, votes in pw_votes.items():
                c = Counter(votes)
                pw_pair[pair] = c.most_common(1)[0][0]
            break

    # --- SI AI preferences ---
    si_pair = {}
    si_scores = {p["id"]: p["single_item_score"] for p in papers if p.get("single_item_score") is not None}
    si_ids = sorted(si_scores.keys())
    for i in range(len(si_ids)):
        for j in range(i + 1, len(si_ids)):
            a, b = si_ids[i], si_ids[j]
            if si_scores[a] != si_scores[b]:
                si_pair[tuple(sorted([a, b]))] = a if si_scores[a] > si_scores[b] else b

    # --- 3-way intersection ---
    controlled = gt_pairs & set(pw_pair.keys()) & set(si_pair.keys())
    if len(controlled) < 10:
        return None

    ctrl_paper_ids = set()
    for p in controlled:
        ctrl_paper_ids.add(p[0])
        ctrl_paper_ids.add(p[1])
    ctrl_papers = [papers_by_id[pid] for pid in ctrl_paper_ids if pid in papers_by_id]

    # --- Agreement: PW vs GT, SI vs GT ---
    if gt_type == "comp":
        # AI vs individual expert
        pw_ah_agree = pw_ah_total = si_ah_agree = si_ah_total = 0
        hh_agree = hh_total = 0
        for pair in controlled:
            for exp, winner in expert_pair_prefs[pair].items():
                pw_ah_total += 1
                si_ah_total += 1
                if pw_pair[pair] == winner:
                    pw_ah_agree += 1
                if si_pair[pair] == winner:
                    si_ah_agree += 1
            # H-H
            voters = list(expert_pair_prefs[pair].values())
            for i in range(len(voters)):
                for j in range(i + 1, len(voters)):
                    hh_total += 1
                    if voters[i] == voters[j]:
                        hh_agree += 1

        # AI vs committee
        pw_ac_agree = pw_ac_total = si_ac_agree = si_ac_total = 0
        for pair in controlled:
            if pair in expert_majority:
                pw_ac_total += 1
                si_ac_total += 1
                if pw_pair[pair] == expert_majority[pair]:
                    pw_ac_agree += 1
                if si_pair[pair] == expert_majority[pair]:
                    si_ac_agree += 1

        # Tie counts for coin-flip
        hh_tie_one = hh_tie_both = pw_ah_tie = si_ah_tie = 0
        for pair in controlled:
            paper_a, paper_b = pair
            experts_for_pair = []
            for exp, ratings in experts_with_data.items():
                if paper_a in ratings and paper_b in ratings:
                    has_pref = ratings[paper_a] != ratings[paper_b]
                    experts_for_pair.append((exp, has_pref))
            for i in range(len(experts_for_pair)):
                for j in range(i + 1, len(experts_for_pair)):
                    _, e1p = experts_for_pair[i]
                    _, e2p = experts_for_pair[j]
                    if e1p and e2p:
                        pass
                    elif not e1p and not e2p:
                        hh_tie_both += 1
                    else:
                        hh_tie_one += 1
            for _, has_pref in experts_for_pair:
                if not has_pref:
                    pw_ah_tie += 1
                    si_ah_tie += 1
    else:
        # Standalone: AI vs GT (h1_avg_rating)
        hh_agree = hh_total = hh_tie_one = hh_tie_both = 0
        pw_ah_agree = pw_ah_total = si_ah_agree = si_ah_total = 0
        pw_ah_tie = si_ah_tie = 0
        pw_ac_agree = pw_ac_total = si_ac_agree = si_ac_total = 0
        for pair in controlled:
            pw_ah_total += 1
            si_ah_total += 1
            if pw_pair[pair] == gt_verdict[pair]:
                pw_ah_agree += 1
            if si_pair[pair] == gt_verdict[pair]:
                si_ah_agree += 1
        pw_ac_agree, pw_ac_total = pw_ah_agree, pw_ah_total
        si_ac_agree, si_ac_total = si_ah_agree, si_ah_total
        # GT tie count (pairs in pw_pair & si_pair but NOT in gt_pairs)
        gt_tie_on_ctrl = 0
        all_ai_pairs = set(pw_pair.keys()) & set(si_pair.keys())
        for pair in all_ai_pairs:
            if pair not in gt_pairs:
                a, b = pair
                if a in papers_by_id and b in papers_by_id:
                    ra = papers_by_id[a].get("h1_avg_rating")
                    rb = papers_by_id[b].get("h1_avg_rating")
                    if ra is not None and rb is not None and ra == rb:
                        gt_tie_on_ctrl += 1

    # --- Difficulty ---
    diff_stats = {level: {"pw_agree": 0, "si_agree": 0, "total": 0, "n_pairs": 0,
                          "hh_agree": 0, "hh_total": 0}
                  for level in ["easy", "medium", "hard"]}
    for pair in controlled:
        diff = _classify_difficulty(pair[0], pair[1], papers_by_id)
        if diff is None:
            continue
        ds = diff_stats[diff]
        ds["n_pairs"] += 1
        if gt_type == "comp":
            for exp, winner in expert_pair_prefs[pair].items():
                ds["total"] += 1
                if pw_pair[pair] == winner:
                    ds["pw_agree"] += 1
                if si_pair[pair] == winner:
                    ds["si_agree"] += 1
            voters = list(expert_pair_prefs[pair].values())
            for i in range(len(voters)):
                for j in range(i + 1, len(voters)):
                    ds["hh_total"] += 1
                    if voters[i] == voters[j]:
                        ds["hh_agree"] += 1
        else:
            ds["total"] += 1
            if pw_pair[pair] == gt_verdict[pair]:
                ds["pw_agree"] += 1
            if si_pair[pair] == gt_verdict[pair]:
                ds["si_agree"] += 1

    # --- BT ranking correlations ---
    pw_matches = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": pw_pair[p],
                   "completed": True, "failed": False} for p in controlled]
    si_matches = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": si_pair[p],
                   "completed": True, "failed": False} for p in controlled]

    def _bt_rho(matches):
        if len(matches) < 10:
            return None
        lb = compute_leaderboard(ctrl_papers, matches)
        ai_rank = {e["id"]: e["rank"] for e in lb}
        # vs h1_avg_rating
        avg_map = {pid: papers_by_id[pid].get("h1_avg_rating") for pid in ctrl_paper_ids
                   if papers_by_id.get(pid, {}).get("h1_avg_rating") is not None}
        if not avg_map:
            # Compute from evaluations
            for pid in ctrl_paper_ids:
                p = papers_by_id.get(pid)
                if p:
                    evals = p.get("evaluations", [])
                    vals = [e["rating_value"] for e in evals if e.get("rating_value")]
                    if vals:
                        avg_map[pid] = sum(vals) / len(vals)
        shared = sorted(set(ai_rank.keys()) & set(avg_map.keys()))
        if len(shared) < 5:
            return None
        sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in shared],
                                       [-avg_map[p] for p in shared])
        return safe_round(float(sp)) if not np.isnan(sp) else None

    pw_rho = _bt_rho(pw_matches)
    si_rho = _bt_rho(si_matches)

    # Coin-flip rates
    hh_cf = _cf_rate(hh_agree, hh_total, hh_tie_one + hh_tie_both) if gt_type == "comp" else None
    pw_cf = _cf_rate(pw_ah_agree, pw_ah_total, pw_ah_tie)
    si_cf = _cf_rate(si_ah_agree, si_ah_total, si_ah_tie)
    hh_tie_rate = round((hh_tie_one + hh_tie_both) / max(hh_total + hh_tie_one + hh_tie_both, 1) * 100, 1) if gt_type == "comp" else None

    return {
        "dataset_id": dataset_id,
        "n_papers": len(ctrl_paper_ids),
        "controlled_pairs": len(controlled),
        "pw": {
            "ai_human": {"rate": _rate(pw_ah_agree, pw_ah_total), "agree": pw_ah_agree, "total": pw_ah_total},
            "ai_committee": {"rate": _rate(pw_ac_agree, pw_ac_total), "agree": pw_ac_agree, "total": pw_ac_total},
            "coin_flip": pw_cf,
            "bt_rho": pw_rho,
        },
        "si": {
            "ai_human": {"rate": _rate(si_ah_agree, si_ah_total), "agree": si_ah_agree, "total": si_ah_total},
            "ai_committee": {"rate": _rate(si_ac_agree, si_ac_total), "agree": si_ac_agree, "total": si_ac_total},
            "coin_flip": si_cf,
            "bt_rho": si_rho,
        },
        "hh": {
            "rate": _rate(hh_agree, hh_total) if hh_total > 0 else None,
            "coin_flip": hh_cf,
            "tie_rate": hh_tie_rate,
        } if gt_type == "comp" else {"rate": None, "coin_flip": None, "tie_rate": None},
        "gt_tie_rate": round(gt_tie_on_ctrl / max(len(controlled) + gt_tie_on_ctrl, 1) * 100, 1) if gt_type == "stan" else None,
        "by_difficulty": {
            level: {
                "pw_rate": _rate(s["pw_agree"], s["total"]),
                "si_rate": _rate(s["si_agree"], s["total"]),
                "hh_rate": _rate(s["hh_agree"], s["hh_total"]) if s["hh_total"] > 0 else None,
                "n_pairs": s["n_pairs"],
            }
            for level, s in diff_stats.items()
        },
    }


@router.get("/unified-benchmark")
async def unified_benchmark(gt_type: str = Query("comp")):
    """Unified PW vs SI benchmark on the exact same pairs."""
    cache = _unified_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    result = await _compute_unified_benchmark(gt_type)
    if result.get("status") == "ok":
        _unified_cache[gt_type] = {"data": result}
    return result


async def _compute_unified_benchmark(gt_type):
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS

    if gt_type == "comp":
        ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
        ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)
                  if r["_id"] in allowed]
    else:
        ds_ids = [d for d in await db.validation_papers.distinct("dataset_id") if d in allowed]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    per_dataset = []
    pooled = {"pw_ah": [0, 0], "si_ah": [0, 0], "pw_ac": [0, 0], "si_ac": [0, 0],
              "hh": [0, 0], "pw_rhos": [], "si_rhos": [],
              "pairs": 0, "papers": 0,
              "hh_tie_one": 0, "hh_tie_both": 0, "pw_ah_tie": 0, "si_ah_tie": 0,
              "gt_tie": 0,
              "diff": {level: {"pw": 0, "si": 0, "hh": 0, "hh_t": 0, "total": 0, "n_pairs": 0}
                       for level in ["easy", "medium", "hard"]}}

    for ds_id in ds_ids:
        result = await _compute_unified_dataset(ds_id, gt_type)
        if result is None:
            continue
        result["name"] = ds_names.get(ds_id, ds_id)
        per_dataset.append(result)

        pooled["pw_ah"][0] += result["pw"]["ai_human"]["agree"]
        pooled["pw_ah"][1] += result["pw"]["ai_human"]["total"]
        pooled["si_ah"][0] += result["si"]["ai_human"]["agree"]
        pooled["si_ah"][1] += result["si"]["ai_human"]["total"]
        pooled["pw_ac"][0] += result["pw"]["ai_committee"]["agree"]
        pooled["pw_ac"][1] += result["pw"]["ai_committee"]["total"]
        pooled["si_ac"][0] += result["si"]["ai_committee"]["agree"]
        pooled["si_ac"][1] += result["si"]["ai_committee"]["total"]
        pooled["pairs"] += result["controlled_pairs"]
        pooled["papers"] += result["n_papers"]

        if result["pw"]["bt_rho"] is not None:
            pooled["pw_rhos"].append(result["pw"]["bt_rho"])
        if result["si"]["bt_rho"] is not None:
            pooled["si_rhos"].append(result["si"]["bt_rho"])

        for level in ["easy", "medium", "hard"]:
            dl = result.get("by_difficulty", {}).get(level, {})
            pd = pooled["diff"][level]
            pd["pw"] += int(dl.get("pw_rate", 0) * dl.get("n_pairs", 0) / 100)
            pd["si"] += int(dl.get("si_rate", 0) * dl.get("n_pairs", 0) / 100)
            pd["n_pairs"] += dl.get("n_pairs", 0)
            pd["total"] += dl.get("n_pairs", 0)

    if not per_dataset:
        return {"status": "no_data"}

    pw_pooled_rho = safe_round(float(np.mean(pooled["pw_rhos"]))) if pooled["pw_rhos"] else None
    si_pooled_rho = safe_round(float(np.mean(pooled["si_rhos"]))) if pooled["si_rhos"] else None

    return {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(per_dataset),
        "total_controlled_pairs": pooled["pairs"],
        "total_papers": pooled["papers"],
        "avg_matches_per_paper": round(2 * pooled["pairs"] / max(pooled["papers"], 1), 1),
        "pooled": {
            "pw_accuracy": _rate(pooled["pw_ah"][0], pooled["pw_ah"][1]),
            "si_accuracy": _rate(pooled["si_ah"][0], pooled["si_ah"][1]),
            "pw_comm_accuracy": _rate(pooled["pw_ac"][0], pooled["pw_ac"][1]),
            "si_comm_accuracy": _rate(pooled["si_ac"][0], pooled["si_ac"][1]),
            "pw_rho": pw_pooled_rho,
            "si_rho": si_pooled_rho,
            "by_difficulty": {
                level: {
                    "pw_rate": _rate(s["pw"], s["total"]),
                    "si_rate": _rate(s["si"], s["total"]),
                    "n_pairs": s["n_pairs"],
                }
                for level, s in pooled["diff"].items()
            },
        },
        "per_dataset": per_dataset,
    }
