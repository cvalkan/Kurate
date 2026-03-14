"""
Human vs AI Agreement Benchmark

Computes a comprehensive comparison of inter-human and AI-human agreement rates
across all controlled same-pair datasets. Inspired by the NeurIPS 2014
reproducibility experiment (Shah & Horvitz).

Layers:
1. Inter-rater correlation rho from raw ratings
2. Theoretical Thurstonian ceiling
3. Controlled same-pair pairwise agreement (H-H, H-Committee, AI-H, AI-Committee)
4. Stratification by difficulty (cross-tier, adjacent-tier, within-tier)
5. BT rank correlation (Spearman)
6. Cohen's kappa (chance-corrected agreement)
"""

import math
import numpy as np
from scipy import stats as scipy_stats
from collections import defaultdict, Counter
from itertools import combinations
from fastapi import APIRouter, Query
from typing import Optional

from core.config import db, logger
from routers.validation_utils import (
    build_expert_ratings, build_expert_majority, build_content_mode_filter,
    safe_round, PAPER_LIGHT_PROJECTION, norm_tier, TIER_ORDER,
)
from services.ranking import compute_leaderboard

router = APIRouter(prefix="/api/validation")

_benchmark_cache = {"data": None}


def _phi(x):
    """Standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _cohens_kappa(agree, total):
    """Cohen's kappa for binary pairwise agreement.
    For pairwise comparisons with balanced base rates, P_e ~ 0.5."""
    if total == 0:
        return 0.0
    p_o = agree / total
    p_e = 0.5  # chance agreement for balanced pairwise comparisons
    if p_e >= 1.0:
        return 0.0
    return (p_o - p_e) / (1 - p_e)


def _wilson_ci(agree, total, z=1.96):
    """Wilson score confidence interval."""
    if total == 0:
        return [0, 0]
    p = agree / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * (p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5 / denom
    return [round((center - spread) * 100, 1), round((center + spread) * 100, 1)]


def _inter_rater_rho(expert_ratings: dict):
    """Compute average inter-rater Pearson correlation from raw ratings.
    Only uses reviewer pairs that rated >= 5 common papers."""
    experts = list(expert_ratings.keys())
    if len(experts) < 2:
        return None, 0, 0

    rhos = []
    total_pairs = 0
    for i, e1 in enumerate(experts):
        for e2 in experts[i + 1:]:
            common = set(expert_ratings[e1].keys()) & set(expert_ratings[e2].keys())
            if len(common) < 5:
                continue
            pids = sorted(common)
            r1 = [expert_ratings[e1][pid] for pid in pids]
            r2 = [expert_ratings[e2][pid] for pid in pids]
            rho, _ = scipy_stats.pearsonr(r1, r2)
            if not np.isnan(rho):
                rhos.append(rho)
                total_pairs += 1

    if not rhos:
        return None, len(experts), 0
    return float(np.mean(rhos)), len(experts), total_pairs


def _thurstonian_ceiling(rho, score_gaps):
    """Compute theoretical pairwise agreement ceiling from inter-rater rho.

    Thurstonian model:
      s_i = q + eps_i, where eps ~ N(0, sigma^2)
      rho = Var(q) / (Var(q) + sigma^2)
      sigma^2 = Var(q) * (1/rho - 1) if rho > 0

    For two reviewers on a pair with quality gap delta_q:
      P(both agree on ordering) = Phi(dq/sqrt(2*sigma^2))^2 + (1 - Phi(dq/sqrt(2*sigma^2)))^2

    Returns ceiling agreement rates at different gap levels and overall.
    """
    if rho is None or rho <= 0:
        return {"overall": 50.0, "note": "rho <= 0, ceiling is chance"}

    # Estimate sigma from rho and observed score variance
    if not score_gaps:
        return {"overall": 50.0, "note": "no score gaps available"}

    var_q = float(np.var(score_gaps)) if len(score_gaps) > 1 else 1.0
    if var_q == 0:
        var_q = 1.0
    sigma_sq = var_q * (1 / rho - 1)
    if sigma_sq <= 0:
        sigma_sq = 0.01

    # Compute ceiling for actual observed gaps
    ceiling_rates = []
    for dq in score_gaps:
        if dq == 0:
            ceiling_rates.append(0.5)
            continue
        z = abs(dq) / math.sqrt(2 * sigma_sq)
        p_correct = _phi(z)
        p_agree = p_correct ** 2 + (1 - p_correct) ** 2
        ceiling_rates.append(p_agree)

    overall = float(np.mean(ceiling_rates)) * 100

    # Ceiling at different gap buckets
    small_gaps = [r for r, g in zip(ceiling_rates, score_gaps) if 0 < abs(g) <= 1]
    med_gaps = [r for r, g in zip(ceiling_rates, score_gaps) if 1 < abs(g) <= 2]
    large_gaps = [r for r, g in zip(ceiling_rates, score_gaps) if abs(g) > 2]

    return {
        "overall": round(overall, 1),
        "small_gap": round(float(np.mean(small_gaps)) * 100, 1) if small_gaps else None,
        "medium_gap": round(float(np.mean(med_gaps)) * 100, 1) if med_gaps else None,
        "large_gap": round(float(np.mean(large_gaps)) * 100, 1) if large_gaps else None,
        "sigma_sq": round(sigma_sq, 4),
        "rho_used": round(rho, 4),
    }


# Tier-based difficulty classification
TIER_SCORE = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}


def _classify_difficulty(p1_id, p2_id, papers_by_id):
    """Classify a pair as cross-tier (easy), adjacent-tier (medium), or within-tier (hard)."""
    p1 = papers_by_id.get(p1_id, {})
    p2 = papers_by_id.get(p2_id, {})
    t1 = norm_tier(p1.get("decision"))
    t2 = norm_tier(p2.get("decision"))
    if t1 is None or t2 is None:
        # Fall back to score gap
        evals1 = p1.get("evaluations", [])
        evals2 = p2.get("evaluations", [])
        r1 = [e["rating_value"] for e in evals1 if e.get("rating_value")]
        r2 = [e["rating_value"] for e in evals2 if e.get("rating_value")]
        if r1 and r2:
            gap = abs(sum(r1) / len(r1) - sum(r2) / len(r2))
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
        return "easy"      # cross-tier (e.g., oral vs reject)
    elif gap == 1:
        return "medium"    # adjacent-tier (e.g., spotlight vs poster)
    else:
        return "hard"      # within-tier (e.g., poster vs poster)


async def _compute_dataset_benchmark(dataset_id: str):
    """Compute all benchmark metrics for a single dataset."""
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id}, PAPER_LIGHT_PROJECTION
    ).to_list(5000)
    if not papers:
        return None

    papers_by_id = {p["id"]: p for p in papers}
    expert_ratings = build_expert_ratings(papers)

    # Need at least 2 experts with overlapping ratings
    experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}
    if len(experts_with_data) < 2:
        return None

    # --- Layer 1: Inter-rater correlation rho ---
    rho, n_experts, n_pairs = _inter_rater_rho(experts_with_data)

    # Collect all score gaps for Thurstonian model
    all_ratings = defaultdict(list)
    for exp, ratings in experts_with_data.items():
        for pid, val in ratings.items():
            all_ratings[pid].append(val)
    avg_scores = {pid: sum(vals) / len(vals) for pid, vals in all_ratings.items() if vals}

    # --- Layer 2: Theoretical ceiling ---
    # Compute score gaps only for controlled non-tie pairs (same set used in agreement analysis)
    # This is deferred until after we know the controlled pairs set

    # --- Layer 3: Controlled same-pair pairwise agreement ---
    # Build expert pairwise preferences
    expert_pair_prefs = defaultdict(dict)  # pair -> {expert: winner}
    for exp, ratings in experts_with_data.items():
        rated_ids = list(ratings.keys())
        for i in range(len(rated_ids)):
            for j in range(i + 1, len(rated_ids)):
                a, b = rated_ids[i], rated_ids[j]
                if ratings[a] == ratings[b]:
                    continue
                pair = tuple(sorted([a, b]))
                expert_pair_prefs[pair][exp] = a if ratings[a] > ratings[b] else b

    # Expert majority vote
    expert_majority = {}
    for pair, votes in expert_pair_prefs.items():
        if len(votes) < 2:
            continue
        c = Counter(votes.values())
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            expert_majority[pair] = best

    # Load AI matches — only use opus46 summaries (best config)
    mode_filter = build_content_mode_filter("abstract_plus_summary:opus46")
    ai_raw = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         **mode_filter},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)
    ai_mode_used = "abstract_plus_summary:opus46"

    if len(ai_raw) < 20:
        return None

    ai_pair_votes = defaultdict(list)
    for m in ai_raw:
        if m.get("winner_id"):
            ai_pair_votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
    ai_pair = {}
    for pair, votes in ai_pair_votes.items():
        c = Counter(votes)
        ai_pair[pair] = c.most_common(1)[0][0]

    # Controlled set: pairs with both human prefs AND AI verdicts
    controlled_pairs = set(expert_pair_prefs.keys()) & set(ai_pair.keys())
    # Further restrict to pairs with 2+ expert opinions for reliability
    controlled_pairs = {p for p in controlled_pairs if len(expert_pair_prefs[p]) >= 2}

    if len(controlled_pairs) < 10:
        return None

    # --- Layer 2: Theoretical ceiling (using controlled pairs' score gaps) ---
    controlled_score_gaps = []
    for pair in controlled_pairs:
        s1 = avg_scores.get(pair[0])
        s2 = avg_scores.get(pair[1])
        if s1 is not None and s2 is not None:
            controlled_score_gaps.append(s1 - s2)
    ceiling = _thurstonian_ceiling(rho, controlled_score_gaps) if rho and controlled_score_gaps else None

    # Human-Human agreement (expert vs expert on same pairs)
    hh_agree = hh_total = 0
    for pair in controlled_pairs:
        voters = list(expert_pair_prefs[pair].values())
        for i in range(len(voters)):
            for j in range(i + 1, len(voters)):
                hh_total += 1
                if voters[i] == voters[j]:
                    hh_agree += 1

    # Human-Committee agreement (individual expert vs majority)
    hc_agree = hc_total = 0
    for pair in controlled_pairs:
        if pair not in expert_majority:
            continue
        for exp, winner in expert_pair_prefs[pair].items():
            hc_total += 1
            if winner == expert_majority[pair]:
                hc_agree += 1

    # Human-Committee LOO (leave-one-out: majority computed WITHOUT the tested expert)
    hc_loo_agree = hc_loo_total = 0
    for pair in controlled_pairs:
        votes = expert_pair_prefs[pair]  # {expert: winner}
        if len(votes) < 3:
            continue  # need 3+ to form a majority after removing one
        for held_out_exp, held_out_winner in votes.items():
            others = [w for e, w in votes.items() if e != held_out_exp]
            if len(others) < 2:
                continue
            c = Counter(others)
            best, n = c.most_common(1)[0]
            if n <= len(others) / 2:
                continue  # no clear majority among remaining experts
            hc_loo_total += 1
            if held_out_winner == best:
                hc_loo_agree += 1

    # AI-Human agreement (AI vs individual expert on same pairs)
    ah_agree = ah_total = 0
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            ah_total += 1
            if ai_pair[pair] == winner:
                ah_agree += 1

    # AI-Committee agreement (AI majority vs expert majority)
    ac_agree = ac_total = 0
    for pair in controlled_pairs:
        if pair not in expert_majority:
            continue
        ac_total += 1
        if ai_pair[pair] == expert_majority[pair]:
            ac_agree += 1

    # --- Layer 4: Stratification by difficulty ---
    difficulty_stats = {"easy": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0]},
                        "medium": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0]},
                        "hard": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0]}}

    for pair in controlled_pairs:
        diff = _classify_difficulty(pair[0], pair[1], papers_by_id)
        if diff is None:
            continue
        ds = difficulty_stats[diff]
        # HH
        voters = list(expert_pair_prefs[pair].values())
        for i in range(len(voters)):
            for j in range(i + 1, len(voters)):
                ds["hh"][1] += 1
                if voters[i] == voters[j]:
                    ds["hh"][0] += 1
        # HC
        if pair in expert_majority:
            for exp, winner in expert_pair_prefs[pair].items():
                ds["hc"][1] += 1
                if winner == expert_majority[pair]:
                    ds["hc"][0] += 1
        # HC LOO
        votes = expert_pair_prefs[pair]
        if len(votes) >= 3:
            for held_out_exp, held_out_winner in votes.items():
                others = [w for e, w in votes.items() if e != held_out_exp]
                if len(others) < 2:
                    continue
                c = Counter(others)
                best, n = c.most_common(1)[0]
                if n <= len(others) / 2:
                    continue
                ds["hc_loo"][1] += 1
                if held_out_winner == best:
                    ds["hc_loo"][0] += 1
        # AH
        for exp, winner in expert_pair_prefs[pair].items():
            ds["ah"][1] += 1
            if ai_pair[pair] == winner:
                ds["ah"][0] += 1
        # AC
        if pair in expert_majority:
            ds["ac"][1] += 1
            if ai_pair[pair] == expert_majority[pair]:
                ds["ac"][0] += 1

    # --- Layer 5: BT rank correlation ---
    # Build human BT from all expert-derived matches
    human_matches = []
    for pair in controlled_pairs:
        # Use majority as the match outcome for human BT
        if pair in expert_majority:
            human_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": expert_majority[pair],
                "completed": True, "failed": False,
            })
    ai_matches_ctrl = [
        {"paper1_id": p[0], "paper2_id": p[1], "winner_id": ai_pair[p],
         "completed": True, "failed": False}
        for p in controlled_pairs
    ]

    ctrl_paper_ids = set()
    for p in controlled_pairs:
        ctrl_paper_ids.add(p[0])
        ctrl_paper_ids.add(p[1])
    ctrl_papers = [papers_by_id[pid] for pid in ctrl_paper_ids if pid in papers_by_id]

    bt_rho = None
    bt_tau = None
    if len(human_matches) >= 10 and len(ai_matches_ctrl) >= 10:
        h_lb = compute_leaderboard(ctrl_papers, human_matches)
        a_lb = compute_leaderboard(ctrl_papers, ai_matches_ctrl)
        h_rank = {e["id"]: e["rank"] for e in h_lb}
        a_rank = {e["id"]: e["rank"] for e in a_lb}
        shared = sorted(set(h_rank.keys()) & set(a_rank.keys()))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([h_rank[pid] for pid in shared],
                                           [a_rank[pid] for pid in shared])
            kt, _ = scipy_stats.kendalltau([h_rank[pid] for pid in shared],
                                            [a_rank[pid] for pid in shared])
            if not np.isnan(sp):
                bt_rho = float(sp)
            if not np.isnan(kt):
                bt_tau = float(kt)

    # --- Layer 6: Cohen's kappa ---
    hh_kappa = _cohens_kappa(hh_agree, hh_total)
    hc_kappa = _cohens_kappa(hc_agree, hc_total)
    hc_loo_kappa = _cohens_kappa(hc_loo_agree, hc_loo_total)
    ah_kappa = _cohens_kappa(ah_agree, ah_total)
    ac_kappa = _cohens_kappa(ac_agree, ac_total)

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    def _format_difficulty(stats):
        result = {}
        for level in ["easy", "medium", "hard"]:
            s = stats[level]
            result[level] = {
                "human_human": {"rate": _rate(s["hh"][0], s["hh"][1]), "pairs": s["hh"][1]},
                "human_committee": {"rate": _rate(s["hc"][0], s["hc"][1]), "pairs": s["hc"][1]},
                "human_committee_loo": {"rate": _rate(s["hc_loo"][0], s["hc_loo"][1]), "pairs": s["hc_loo"][1]},
                "ai_human": {"rate": _rate(s["ah"][0], s["ah"][1]), "pairs": s["ah"][1]},
                "ai_committee": {"rate": _rate(s["ac"][0], s["ac"][1]), "pairs": s["ac"][1]},
            }
        return result

    return {
        "dataset_id": dataset_id,
        "n_papers": len(papers),
        "n_experts": len(experts_with_data),
        "controlled_pairs": len(controlled_pairs),
        "ai_mode": ai_mode_used,
        "inter_rater_rho": safe_round(rho) if rho else None,
        "n_rater_pairs": n_pairs,
        "ceiling": ceiling,
        "pairwise": {
            "human_human": {"agree": hh_agree, "total": hh_total, "rate": _rate(hh_agree, hh_total),
                            "kappa": safe_round(hh_kappa), "ci": _wilson_ci(hh_agree, hh_total)},
            "human_committee": {"agree": hc_agree, "total": hc_total, "rate": _rate(hc_agree, hc_total),
                                "kappa": safe_round(hc_kappa), "ci": _wilson_ci(hc_agree, hc_total)},
            "human_committee_loo": {"agree": hc_loo_agree, "total": hc_loo_total, "rate": _rate(hc_loo_agree, hc_loo_total),
                                    "kappa": safe_round(hc_loo_kappa), "ci": _wilson_ci(hc_loo_agree, hc_loo_total)},
            "ai_human": {"agree": ah_agree, "total": ah_total, "rate": _rate(ah_agree, ah_total),
                         "kappa": safe_round(ah_kappa), "ci": _wilson_ci(ah_agree, ah_total)},
            "ai_committee": {"agree": ac_agree, "total": ac_total, "rate": _rate(ac_agree, ac_total),
                             "kappa": safe_round(ac_kappa), "ci": _wilson_ci(ac_agree, ac_total)},
        },
        "by_difficulty": _format_difficulty(difficulty_stats),
        "bt_correlation": {
            "spearman_rho": safe_round(bt_rho) if bt_rho else None,
            "kendall_tau": safe_round(bt_tau) if bt_tau else None,
            "n_papers": len(ctrl_paper_ids),
        },
    }


@router.get("/human-ai-benchmark")
async def human_ai_benchmark():
    """Comprehensive human vs AI agreement benchmark across all controlled datasets."""
    if _benchmark_cache["data"]:
        return _benchmark_cache["data"]
    result = await _compute_benchmark()
    if result.get("status") == "ok":
        _benchmark_cache["data"] = result
    return result


async def _compute_benchmark():
    """Compute the full benchmark across all datasets with human evaluations."""
    # Discover datasets with evaluations
    ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
    all_ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    per_dataset = []
    pooled = {
        "hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0],
        "rhos": [], "taus": [],
        "inter_rater_rhos": [],
        "ceilings": [],
        "total_pairs": 0,
        "difficulty": {"easy": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0]},
                       "medium": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0]},
                       "hard": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0]}},
    }

    for ds_id in all_ds_ids:
        result = await _compute_dataset_benchmark(ds_id)
        if result is None:
            continue

        result["name"] = ds_names.get(ds_id, ds_id)
        per_dataset.append(result)

        # Accumulate pooled stats
        pw = result["pairwise"]
        for key, pool_key in [("human_human", "hh"), ("human_committee", "hc"),
                               ("human_committee_loo", "hc_loo"),
                               ("ai_human", "ah"), ("ai_committee", "ac")]:
            pooled[pool_key][0] += pw[key]["agree"]
            pooled[pool_key][1] += pw[key]["total"]

        pooled["total_pairs"] += result["controlled_pairs"]

        if result.get("inter_rater_rho") is not None:
            pooled["inter_rater_rhos"].append(result["inter_rater_rho"])
        if result.get("ceiling") and result["ceiling"].get("overall"):
            pooled["ceilings"].append(result["ceiling"]["overall"])
        bt = result.get("bt_correlation", {})
        if bt.get("spearman_rho") is not None:
            pooled["rhos"].append(bt["spearman_rho"])
        if bt.get("kendall_tau") is not None:
            pooled["taus"].append(bt["kendall_tau"])

        # Pool difficulty stats
        for level in ["easy", "medium", "hard"]:
            for metric in ["hh", "hc", "hc_loo", "ah", "ac"]:
                metric_full = {"hh": "human_human", "hc": "human_committee",
                               "hc_loo": "human_committee_loo",
                               "ah": "ai_human", "ac": "ai_committee"}[metric]
                d = result.get("by_difficulty", {}).get(level, {}).get(metric_full, {})
                pooled["difficulty"][level][metric][0] += int(d.get("rate", 0) * d.get("pairs", 0) / 100)
                pooled["difficulty"][level][metric][1] += d.get("pairs", 0)

    if not per_dataset:
        return {"status": "no_data"}

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    def _kappa(a, t):
        return safe_round(_cohens_kappa(a, t))

    def _format_pooled_difficulty():
        result = {}
        for level in ["easy", "medium", "hard"]:
            s = pooled["difficulty"][level]
            result[level] = {
                "human_human": {"rate": _rate(s["hh"][0], s["hh"][1]), "pairs": s["hh"][1]},
                "human_committee": {"rate": _rate(s["hc"][0], s["hc"][1]), "pairs": s["hc"][1]},
                "human_committee_loo": {"rate": _rate(s["hc_loo"][0], s["hc_loo"][1]), "pairs": s["hc_loo"][1]},
                "ai_human": {"rate": _rate(s["ah"][0], s["ah"][1]), "pairs": s["ah"][1]},
                "ai_committee": {"rate": _rate(s["ac"][0], s["ac"][1]), "pairs": s["ac"][1]},
            }
        return result

    summary = {
        "status": "ok",
        "n_datasets": len(per_dataset),
        "total_controlled_pairs": pooled["total_pairs"],
        "pooled": {
            "inter_rater_rho": safe_round(float(np.mean(pooled["inter_rater_rhos"]))) if pooled["inter_rater_rhos"] else None,
            "theoretical_ceiling": safe_round(float(np.mean(pooled["ceilings"])), 1) if pooled["ceilings"] else None,
            "pairwise": {
                "human_human": {"rate": _rate(pooled["hh"][0], pooled["hh"][1]),
                                "kappa": _kappa(pooled["hh"][0], pooled["hh"][1]),
                                "pairs": pooled["hh"][1],
                                "ci": _wilson_ci(pooled["hh"][0], pooled["hh"][1])},
                "human_committee": {"rate": _rate(pooled["hc"][0], pooled["hc"][1]),
                                    "kappa": _kappa(pooled["hc"][0], pooled["hc"][1]),
                                    "pairs": pooled["hc"][1],
                                    "ci": _wilson_ci(pooled["hc"][0], pooled["hc"][1])},
                "human_committee_loo": {"rate": _rate(pooled["hc_loo"][0], pooled["hc_loo"][1]),
                                        "kappa": _kappa(pooled["hc_loo"][0], pooled["hc_loo"][1]),
                                        "pairs": pooled["hc_loo"][1],
                                        "ci": _wilson_ci(pooled["hc_loo"][0], pooled["hc_loo"][1])},
                "ai_human": {"rate": _rate(pooled["ah"][0], pooled["ah"][1]),
                             "kappa": _kappa(pooled["ah"][0], pooled["ah"][1]),
                             "pairs": pooled["ah"][1],
                             "ci": _wilson_ci(pooled["ah"][0], pooled["ah"][1])},
                "ai_committee": {"rate": _rate(pooled["ac"][0], pooled["ac"][1]),
                                 "kappa": _kappa(pooled["ac"][0], pooled["ac"][1]),
                                 "pairs": pooled["ac"][1],
                                 "ci": _wilson_ci(pooled["ac"][0], pooled["ac"][1])},
            },
            "bt_correlation": {
                "spearman_rho": safe_round(float(np.mean(pooled["rhos"]))) if pooled["rhos"] else None,
                "kendall_tau": safe_round(float(np.mean(pooled["taus"]))) if pooled["taus"] else None,
            },
            "by_difficulty": _format_pooled_difficulty(),
        },
        "neurips_reference": {
            "accept_reject_agreement": 60,
            "inter_rater_rho": "0.2-0.3 (estimated)",
            "note": "NeurIPS 2014: two independent committees agreed on accept/reject ~60% of the time. "
                    "This is a BINARY THRESHOLD decision, not pairwise comparison. "
                    "Pairwise agreement is expected to be higher than binary threshold agreement "
                    "because it's a relative judgment (easier) rather than absolute scoring.",
        },
        "per_dataset": per_dataset,
    }

    return summary
