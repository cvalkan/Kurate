"""
Standalone GT Benchmark — for datasets with a single aggregate human score per paper.

Uses h1_avg_rating as the ground truth (no multi-reviewer concordance possible).
Computes AI-GT agreement, BT ranking correlation, tie rates, difficulty stratification.
Shared by both pairwise and single-item AI benchmarks for standalone GT datasets.
"""

import math
import numpy as np
from scipy import stats as scipy_stats
from collections import defaultdict, Counter

from core.config import db, logger
from routers.validation_utils import (
    build_content_mode_filter, safe_round, PAPER_LIGHT_PROJECTION,
    norm_tier, STANDALONE_GT_DATASETS,
)
from services.ranking import compute_leaderboard


TIER_SCORE = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}


def _cohens_kappa(agree, total):
    if total == 0:
        return 0.0
    p_o = agree / total
    p_e = 0.5
    return (p_o - p_e) / (1 - p_e) if p_e < 1.0 else 0.0


def _wilson_ci(agree, total, z=1.96):
    if total == 0:
        return [0, 0]
    p = agree / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * (p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5 / denom
    return [round((center - spread) * 100, 1), round((center + spread) * 100, 1)]


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
            if gap > 2:
                return "easy"
            elif gap >= 1:
                return "medium"
            else:
                return "hard"
        return None
    s1 = TIER_SCORE.get(t1, -1)
    s2 = TIER_SCORE.get(t2, -1)
    gap = abs(s1 - s2)
    if gap >= 2:
        return "easy"
    elif gap == 1:
        return "medium"
    else:
        return "hard"


def _rate(a, t):
    return round(a / max(t, 1) * 100, 1)


def _cf_rate(agree, nontie_total, tie_count):
    total = nontie_total + tie_count
    if total == 0:
        return None
    return round((agree + 0.5 * tie_count) / total * 100, 1)


async def compute_standalone_dataset(dataset_id, ai_source="pairwise"):
    """Compute benchmark for one standalone GT dataset.

    ai_source: 'pairwise' (match verdicts) or 'single_item' (single_item_score)
    """
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "h1_avg_rating": 1, "decision": 1,
         "single_item_score": 1, "evaluations": 1}
    ).to_list(5000)

    # Need papers with h1_avg_rating
    papers = [p for p in papers if p.get("h1_avg_rating") is not None]
    if len(papers) < 10:
        return None

    papers_by_id = {p["id"]: p for p in papers}
    paper_ids = sorted(papers_by_id.keys())

    # GT pairwise preferences from h1_avg_rating
    gt_pair = {}
    gt_tie_count = 0
    for i in range(len(paper_ids)):
        for j in range(i + 1, len(paper_ids)):
            a, b = paper_ids[i], paper_ids[j]
            pair = tuple(sorted([a, b]))
            ra = papers_by_id[a]["h1_avg_rating"]
            rb = papers_by_id[b]["h1_avg_rating"]
            if ra == rb:
                gt_tie_count += 1
            else:
                gt_pair[pair] = a if ra > rb else b

    # AI pairwise preferences
    ai_pair = {}
    ai_tie_count = 0

    if ai_source == "pairwise":
        # Try best available content mode
        PREFERRED_MODES = [
            "abstract_plus_summary:opus46",
            "abstract_plus_summary:thinking",
            "abstract_plus_summary",
        ]
        ai_raw = []
        for mode in PREFERRED_MODES:
            mode_filter = build_content_mode_filter(mode)
            ai_raw = await db.validation_matches.find(
                {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
                 **mode_filter},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
            ).to_list(100000)
            if len(ai_raw) >= 20:
                break

        if len(ai_raw) < 20:
            return None

        ai_pair_votes = defaultdict(list)
        for m in ai_raw:
            if m.get("winner_id"):
                ai_pair_votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
        for pair, votes in ai_pair_votes.items():
            c = Counter(votes)
            ai_pair[pair] = c.most_common(1)[0][0]

    elif ai_source == "single_item":
        ai_scores = {p["id"]: p["single_item_score"] for p in papers if p.get("single_item_score") is not None}
        if len(ai_scores) < 10:
            return None
        ai_ids = sorted(ai_scores.keys())
        for i in range(len(ai_ids)):
            for j in range(i + 1, len(ai_ids)):
                a, b = ai_ids[i], ai_ids[j]
                pair = tuple(sorted([a, b]))
                sa, sb = ai_scores[a], ai_scores[b]
                if sa != sb:
                    ai_pair[pair] = a if sa > sb else b
                else:
                    ai_tie_count += 1

    # Controlled pairs: GT has preference AND AI has preference
    controlled_pairs = set(gt_pair.keys()) & set(ai_pair.keys())
    if len(controlled_pairs) < 10:
        return None

    # --- Agreement: AI vs GT ---
    agree = 0
    for pair in controlled_pairs:
        if ai_pair[pair] == gt_pair[pair]:
            agree += 1
    total = len(controlled_pairs)

    # --- GT ties that were excluded (pairs in ai_pair but GT tied) ---
    gt_tie_on_ai_pairs = 0
    for pair in ai_pair:
        if pair not in gt_pair:
            # This pair was a GT tie
            a, b = pair
            if a in papers_by_id and b in papers_by_id:
                ra = papers_by_id[a].get("h1_avg_rating")
                rb = papers_by_id[b].get("h1_avg_rating")
                if ra is not None and rb is not None and ra == rb:
                    gt_tie_on_ai_pairs += 1

    # --- Difficulty stratification ---
    diff_stats = {level: {"agree": 0, "total": 0, "n_pairs": 0, "gt_tie": 0}
                  for level in ["easy", "medium", "hard"]}
    for pair in controlled_pairs:
        diff = _classify_difficulty(pair[0], pair[1], papers_by_id)
        if diff is None:
            continue
        ds = diff_stats[diff]
        ds["n_pairs"] += 1
        ds["total"] += 1
        if ai_pair[pair] == gt_pair[pair]:
            ds["agree"] += 1
    # GT tie counts per difficulty
    for pair in ai_pair:
        if pair in gt_pair:
            continue
        a, b = pair
        if a in papers_by_id and b in papers_by_id:
            ra = papers_by_id[a].get("h1_avg_rating")
            rb = papers_by_id[b].get("h1_avg_rating")
            if ra is not None and rb is not None and ra == rb:
                diff = _classify_difficulty(a, b, papers_by_id)
                if diff and diff in diff_stats:
                    diff_stats[diff]["gt_tie"] += 1

    # --- BT ranking correlation ---
    ai_matches_ctrl = [
        {"paper1_id": p[0], "paper2_id": p[1], "winner_id": ai_pair[p],
         "completed": True, "failed": False}
        for p in controlled_pairs
    ]
    gt_matches = [
        {"paper1_id": p[0], "paper2_id": p[1], "winner_id": gt_pair[p],
         "completed": True, "failed": False}
        for p in controlled_pairs
    ]

    ctrl_paper_ids = set()
    for p in controlled_pairs:
        ctrl_paper_ids.add(p[0])
        ctrl_paper_ids.add(p[1])
    ctrl_papers = [papers_by_id[pid] for pid in ctrl_paper_ids if pid in papers_by_id]

    bt_rho = bt_tau = None
    if len(gt_matches) >= 10 and len(ai_matches_ctrl) >= 10:
        gt_lb = compute_leaderboard(ctrl_papers, gt_matches)
        ai_lb = compute_leaderboard(ctrl_papers, ai_matches_ctrl)
        gt_rank = {e["id"]: e["rank"] for e in gt_lb}
        ai_rank = {e["id"]: e["rank"] for e in ai_lb}
        shared = sorted(set(gt_rank.keys()) & set(ai_rank.keys()))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([gt_rank[p] for p in shared], [ai_rank[p] for p in shared])
            kt, _ = scipy_stats.kendalltau([gt_rank[p] for p in shared], [ai_rank[p] for p in shared])
            if not np.isnan(sp):
                bt_rho = float(sp)
            if not np.isnan(kt):
                bt_tau = float(kt)

    kappa = _cohens_kappa(agree, total)
    gt_total_pairs = len(gt_pair) + gt_tie_count
    gt_tie_frac = round(gt_tie_count / max(gt_total_pairs, 1) * 100, 1)

    return {
        "dataset_id": dataset_id,
        "n_papers": len(papers),
        "controlled_pairs": len(controlled_pairs),
        "ai_source": ai_source,
        "agreement": {
            "rate": _rate(agree, total),
            "agree": agree,
            "total": total,
            "kappa": safe_round(kappa),
            "ci": _wilson_ci(agree, total),
        },
        "gt_tie_rate": gt_tie_frac,
        "gt_tie_on_ai_pairs": gt_tie_on_ai_pairs,
        "ai_tie_count": ai_tie_count if ai_source == "single_item" else 0,
        "coin_flip": {
            "rate": _cf_rate(agree, total, gt_tie_on_ai_pairs),
            "total": total + gt_tie_on_ai_pairs,
        },
        "by_difficulty": {
            level: {
                "rate": _rate(s["agree"], s["total"]),
                "n_pairs": s["n_pairs"],
                "cf_rate": _cf_rate(s["agree"], s["total"], s["gt_tie"]),
            }
            for level, s in diff_stats.items()
        },
        "bt_correlation": {
            "spearman_rho": safe_round(bt_rho) if bt_rho else None,
            "kendall_tau": safe_round(bt_tau) if bt_tau else None,
            "n_papers": len(ctrl_paper_ids),
        },
    }


async def compute_standalone_benchmark(ai_source="pairwise"):
    """Compute pooled benchmark across all standalone GT datasets."""
    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    # Find standalone datasets
    if ai_source == "single_item":
        ds_ids = await db.validation_papers.distinct("dataset_id", {"single_item_score": {"$exists": True}})
        ds_ids = [d for d in ds_ids if d in STANDALONE_GT_DATASETS]
    else:
        ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
        ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)
                  if r["_id"] in STANDALONE_GT_DATASETS]

    per_dataset = []
    pooled_agree = 0
    pooled_total = 0
    pooled_gt_tie = 0
    pooled_pairs = 0
    pooled_papers = 0
    pooled_rhos = []
    pooled_taus = []
    pooled_diff = {level: {"agree": 0, "total": 0, "n_pairs": 0, "gt_tie": 0}
                   for level in ["easy", "medium", "hard"]}

    for ds_id in ds_ids:
        result = await compute_standalone_dataset(ds_id, ai_source)
        if result is None:
            continue
        result["name"] = ds_names.get(ds_id, ds_id)
        per_dataset.append(result)

        ag = result["agreement"]
        pooled_agree += ag["agree"]
        pooled_total += ag["total"]
        pooled_gt_tie += result["gt_tie_on_ai_pairs"]
        pooled_pairs += result["controlled_pairs"]
        pooled_papers += result["n_papers"]

        bt = result.get("bt_correlation", {})
        if bt.get("spearman_rho") is not None:
            pooled_rhos.append(bt["spearman_rho"])
        if bt.get("kendall_tau") is not None:
            pooled_taus.append(bt["kendall_tau"])

        for level in ["easy", "medium", "hard"]:
            dl = result.get("by_difficulty", {}).get(level, {})
            pooled_diff[level]["agree"] += int(dl.get("rate", 0) * dl.get("n_pairs", 0) / 100)
            pooled_diff[level]["total"] += dl.get("n_pairs", 0)
            pooled_diff[level]["n_pairs"] += dl.get("n_pairs", 0)
            # Estimate gt_tie from cf_rate difference
            if dl.get("cf_rate") is not None and dl.get("rate") is not None and dl["n_pairs"] > 0:
                # Back-derive gt_tie: cf_rate = (agree + 0.5*gt_tie) / (total + gt_tie)
                # This is approximate for pooling; use per-dataset values
                pass

    if not per_dataset:
        return {"status": "no_data"}

    pooled_kappa = _cohens_kappa(pooled_agree, pooled_total)
    gt_tie_frac = round(pooled_gt_tie / max(pooled_total + pooled_gt_tie, 1) * 100, 1)

    return {
        "status": "ok",
        "gt_type": "stan",
        "ai_source": ai_source,
        "n_datasets": len(per_dataset),
        "total_controlled_pairs": pooled_pairs,
        "total_papers": pooled_papers,
        "avg_matches_per_paper": round(2 * pooled_pairs / max(pooled_papers, 1), 1),
        "pooled": {
            "agreement": {
                "rate": _rate(pooled_agree, pooled_total),
                "kappa": safe_round(pooled_kappa),
                "pairs": pooled_total,
            },
            "coin_flip": {
                "rate": _cf_rate(pooled_agree, pooled_total, pooled_gt_tie),
                "total": pooled_total + pooled_gt_tie,
            },
            "gt_tie_rate": gt_tie_frac,
            "bt_correlation": {
                "spearman_rho": safe_round(float(np.mean(pooled_rhos))) if pooled_rhos else None,
                "kendall_tau": safe_round(float(np.mean(pooled_taus))) if pooled_taus else None,
            },
            "by_difficulty": {
                level: {
                    "rate": _rate(s["agree"], s["total"]),
                    "n_pairs": s["n_pairs"],
                }
                for level, s in pooled_diff.items()
            },
        },
        "per_dataset": per_dataset,
    }
