"""
Human vs AI Agreement Benchmark

Computes a comprehensive comparison of inter-human and AI-human agreement rates
across all controlled same-pair datasets.

Layers:
1. Inter-rater pairwise concordance (directly from paper pairs, ties excluded)
2. Theoretical Thurstonian ceiling (rho derived from concordance via Kruskal 1958)
3. Controlled same-pair pairwise agreement (H-H, H-Committee, AI-H, AI-Committee)
4. Stratification by difficulty (cross-tier, adjacent-tier, within-tier)
5. BT rank correlation (Spearman) — both committee and individual human baselines
6. Cohen's kappa (chance-corrected agreement)
"""

import math
import asyncio
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
    COMPARATIVE_GT_DATASETS, STANDALONE_GT_DATASETS,
)
from services.ranking import compute_leaderboard

router = APIRouter(prefix="/api/validation")

_benchmark_cache = {"comp": {"data": None}, "stan": {"data": None}}


async def _load_cached_benchmark(gt_type: str):
    """Try to load benchmark from MongoDB cache."""
    from core.cache import CACHE_VERSION
    doc = await db.benchmark_cache.find_one({"gt_type": gt_type}, {"_id": 0, "data": 1, "version": 1})
    if doc and doc.get("data"):
        if doc.get("version", 0) != CACHE_VERSION:
            await db.benchmark_cache.delete_one({"gt_type": gt_type})
            logger.info(f"Benchmark cache invalidated (version mismatch): {gt_type}")
            return None
        _benchmark_cache[gt_type] = {"data": doc["data"]}
        return doc["data"]
    return None


async def prewarm_benchmark_cache():
    """Pre-warm benchmark cache on startup. Called from server.py."""
    for gt_type in ["comp"]:
        cached = await _load_cached_benchmark(gt_type)
        if cached:
            logger.info(f"Benchmark cache loaded from DB for gt_type={gt_type}")
        else:
            logger.info(f"No cached benchmark for gt_type={gt_type}, computing...")
            try:
                result = await _compute_benchmark(gt_type)
                if result.get("status") == "ok":
                    _benchmark_cache[gt_type] = {"data": result}
                    await db.benchmark_cache.update_one(
                        {"gt_type": gt_type},
                        {"$set": {"gt_type": gt_type, "data": result}},
                        upsert=True,
                    )
                    logger.info(f"Benchmark cache computed and stored for gt_type={gt_type}")
            except Exception as e:
                logger.warning(f"Benchmark pre-warm failed for {gt_type}: {e}")


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


def _inter_rater_pairwise(expert_ratings: dict):
    """Compute inter-rater reliability directly from pairwise concordance.

    For each pair of experts sharing >= 5 common papers:
    1. Enumerate all paper pairs where BOTH experts give different scores (non-tie)
    2. Count concordant pairs (both experts order the same way) vs discordant
    3. Concordance rate = concordant / (concordant + discordant)

    Convert to Thurstonian rho via: rho = sin(pi * (concordance - 0.5))
    (Kruskal 1958: for bivariate normal, P(concordant) = 0.5 + arcsin(rho)/pi)

    Also reports tie statistics: what fraction of paper pairs are excluded
    because at least one expert gave both papers the same score.

    Only uses reviewer pairs that share >= 5 common papers."""
    experts = list(expert_ratings.keys())
    if len(experts) < 2:
        return None, 0, 0, {}

    concordance_rates = []
    coinflip_concordance_rates = []
    total_reviewer_pairs = 0
    total_concordant = 0
    total_discordant = 0
    total_tied = 0

    for i, e1 in enumerate(experts):
        for e2 in experts[i + 1:]:
            common = set(expert_ratings[e1].keys()) & set(expert_ratings[e2].keys())
            if len(common) < 5:
                continue

            pids = sorted(common)
            concordant = 0
            discordant = 0
            tied = 0

            for a_idx in range(len(pids)):
                for b_idx in range(a_idx + 1, len(pids)):
                    pa, pb = pids[a_idx], pids[b_idx]
                    diff1 = expert_ratings[e1][pa] - expert_ratings[e1][pb]
                    diff2 = expert_ratings[e2][pa] - expert_ratings[e2][pb]

                    if diff1 == 0 or diff2 == 0:
                        tied += 1
                        continue

                    if (diff1 > 0 and diff2 > 0) or (diff1 < 0 and diff2 < 0):
                        concordant += 1
                    else:
                        discordant += 1

            total_concordant += concordant
            total_discordant += discordant
            total_tied += tied

            nontie = concordant + discordant
            all_pairs = nontie + tied
            if nontie >= 5:
                concordance_rates.append(concordant / nontie)
                total_reviewer_pairs += 1
            if all_pairs >= 5:
                coinflip_concordance_rates.append((concordant + 0.5 * tied) / all_pairs)

    if not concordance_rates:
        return None, len(experts), 0, {}

    avg_concordance = float(np.mean(concordance_rates))
    avg_cf_concordance = float(np.mean(coinflip_concordance_rates)) if coinflip_concordance_rates else None
    # Convert to Thurstonian rho: rho = sin(pi * (concordance - 0.5))
    rho = math.sin(math.pi * (avg_concordance - 0.5))

    tie_stats = {
        "concordant": total_concordant,
        "discordant": total_discordant,
        "tied_excluded": total_tied,
        "tie_fraction": round(total_tied / max(total_concordant + total_discordant + total_tied, 1), 4),
        "concordance_rate": round(avg_concordance, 4),
        "cf_concordance_rate": round(avg_cf_concordance, 4) if avg_cf_concordance is not None else None,
    }

    return float(rho), len(experts), total_reviewer_pairs, tie_stats


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


async def _compute_dataset_benchmark(dataset_id: str, require_si: bool = False):
    """Compute all benchmark metrics for a single dataset."""
    query = {"dataset_id": dataset_id}
    if require_si:
        query["single_item_score"] = {"$exists": True}
    papers = await db.validation_papers.find(query, PAPER_LIGHT_PROJECTION).to_list(5000)
    if not papers:
        return None

    papers_by_id = {p["id"]: p for p in papers}
    expert_ratings = build_expert_ratings(papers)

    # Need at least 2 experts with overlapping ratings
    experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}
    if len(experts_with_data) < 2:
        return None

    # --- Layer 1: Inter-rater correlation rho (pairwise concordance) ---
    rho, n_experts, n_pairs, tie_stats = _inter_rater_pairwise(experts_with_data)

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

    # --- Load AI matches (thinking mode if available, else plain) ---
    sample_paper = papers[0] if papers else {}
    sample_full = await db.validation_papers.find_one(
        {"id": sample_paper.get("id"), "dataset_id": dataset_id},
        {"_id": 0, "ai_impact_summary_thinking": 1}
    ) if sample_paper.get("id") else None
    has_thinking = bool(sample_full and sample_full.get("ai_impact_summary_thinking"))
    ai_content_mode = "abstract_plus_summary:thinking" if has_thinking else "abstract_plus_summary"
    mode_count = await db.validation_matches.count_documents(
        {"dataset_id": dataset_id, "completed": True, "content_mode": ai_content_mode})
    if mode_count == 0:
        ai_content_mode = "abstract_plus_summary"

    ai_raw = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": ai_content_mode},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)
    ai_mode_used = ai_content_mode

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

    # --- AI-Human concordance (per-expert average) ---
    ai_h_per_expert = defaultdict(lambda: [0, 0])  # {expert: [agree, total]}
    ai_h_per_expert_ties = defaultdict(int)  # {expert: tie_count}
    for pair in controlled_pairs:
        paper_a, paper_b = pair
        for exp, winner in expert_pair_prefs[pair].items():
            ai_h_per_expert[exp][1] += 1
            if ai_pair[pair] == winner:
                ai_h_per_expert[exp][0] += 1
        # Count experts who tie on this controlled pair (for coin-flip concordance)
        for exp, ratings in experts_with_data.items():
            if paper_a in ratings and paper_b in ratings:
                if ratings[paper_a] == ratings[paper_b]:
                    ai_h_per_expert_ties[exp] += 1

    ai_h_conc_rates = [a / t for a, t in ai_h_per_expert.values() if t >= 5]
    ai_h_concordance = float(np.mean(ai_h_conc_rates)) if ai_h_conc_rates else None
    ai_h_rho = math.sin(math.pi * (ai_h_concordance - 0.5)) if ai_h_concordance else None

    # Coin-flip AI-H concordance: (agree + 0.5*ties) / (total + ties) per expert
    ai_h_cf_conc_rates = []
    for exp in ai_h_per_expert:
        a, t = ai_h_per_expert[exp]
        ties = ai_h_per_expert_ties.get(exp, 0)
        total_cf = t + ties
        if total_cf >= 5:
            ai_h_cf_conc_rates.append((a + 0.5 * ties) / total_cf)
    ai_h_cf_concordance = float(np.mean(ai_h_cf_conc_rates)) if ai_h_cf_conc_rates else None

    # --- Tie impact analysis ---
    # Count tie-affected expert comparisons that are currently excluded
    hh_tie_one = 0   # one expert has preference, other ties
    hh_tie_both = 0  # both experts tie on this pair
    ah_tie = 0       # expert ties but AI has a verdict
    hc_tie = 0       # expert ties vs committee that has a majority
    hc_loo_tie = 0   # expert ties vs LOO majority
    for pair in controlled_pairs:
        paper_a, paper_b = pair
        experts_for_pair = []
        for exp, ratings in experts_with_data.items():
            if paper_a in ratings and paper_b in ratings:
                has_pref = ratings[paper_a] != ratings[paper_b]
                experts_for_pair.append((exp, has_pref))

        # H-H tie counts
        for i in range(len(experts_for_pair)):
            for j in range(i + 1, len(experts_for_pair)):
                _, e1_pref = experts_for_pair[i]
                _, e2_pref = experts_for_pair[j]
                if e1_pref and e2_pref:
                    pass  # already in hh_total
                elif not e1_pref and not e2_pref:
                    hh_tie_both += 1
                else:
                    hh_tie_one += 1

        # AI-H tie counts
        for _, has_pref in experts_for_pair:
            if not has_pref:
                ah_tie += 1

        # H-Comm tie: expert ties but committee has a majority
        if pair in expert_majority:
            for _, has_pref in experts_for_pair:
                if not has_pref:
                    hc_tie += 1

        # H-Comm LOO tie: expert ties but LOO majority exists
        votes = expert_pair_prefs.get(pair, {})
        for exp_name, has_pref in experts_for_pair:
            if has_pref:
                continue  # already counted
            # This expert ties; check if remaining experts form a majority
            others = [w for e, w in votes.items()]
            if len(others) >= 2:
                c = Counter(others)
                best, n = c.most_common(1)[0]
                if n > len(others) / 2:
                    hc_loo_tie += 1

    # --- Tie validation: does AI have real signal on pairs where experts tie? ---
    # For each pair where at least one expert ties AND at least one doesn't:
    # Check if AI agrees with the non-tying experts.
    # If > 50%, AI has signal beyond random on "hard for humans" pairs.
    tv_ai_agree = tv_ai_total = 0
    tv_hh_agree = tv_hh_total = 0
    for pair in controlled_pairs:
        paper_a, paper_b = pair
        tying_experts = []
        nontying_experts = []
        for exp, ratings in experts_with_data.items():
            if paper_a in ratings and paper_b in ratings:
                if ratings[paper_a] == ratings[paper_b]:
                    tying_experts.append(exp)
                else:
                    nontying_experts.append(exp)

        # Need at least 1 tying AND 1 non-tying
        if not tying_experts or not nontying_experts:
            continue

        # AI vs each non-tying expert (on pairs where at least one other expert ties)
        for exp in nontying_experts:
            winner = expert_pair_prefs[pair].get(exp)
            if winner:
                tv_ai_total += 1
                if ai_pair[pair] == winner:
                    tv_ai_agree += 1

        # H-H: tying expert (coin-flip) vs non-tying expert
        # Under coin-flip: 50%. But do non-tying experts agree with EACH OTHER on these pairs?
        for i in range(len(nontying_experts)):
            for j in range(i + 1, len(nontying_experts)):
                e1 = expert_pair_prefs[pair].get(nontying_experts[i])
                e2 = expert_pair_prefs[pair].get(nontying_experts[j])
                if e1 and e2:
                    tv_hh_total += 1
                    if e1 == e2:
                        tv_hh_agree += 1

    # --- Tier-based accuracy: AI verdict vs actual ICLR committee decisions ---
    # For pairs where papers have different decision tiers, does AI pick the higher-tier paper?
    tier_ai_agree = tier_ai_total = 0
    tier_hh_agree = tier_hh_total = 0
    for pair in controlled_pairs:
        a, b = pair
        pa = papers_by_id.get(a, {})
        pb = papers_by_id.get(b, {})
        ta = norm_tier(pa.get("decision"))
        tb = norm_tier(pb.get("decision"))
        if ta is None or tb is None:
            continue
        sa = TIER_SCORE.get(ta, -1)
        sb = TIER_SCORE.get(tb, -1)
        if sa == sb:
            continue  # same tier — no GT preference
        tier_winner = a if sa > sb else b
        tier_ai_total += 1
        if ai_pair[pair] == tier_winner:
            tier_ai_agree += 1
        # H-H: how often do individual experts agree with tier decision?
        for exp, winner in expert_pair_prefs[pair].items():
            tier_hh_total += 1
            if winner == tier_winner:
                tier_hh_agree += 1

    # --- Layer 4: Stratification by difficulty ---
    difficulty_stats = {"easy": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0], "n_pairs": 0,
                                 "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_tie": 0, "hc_loo_tie": 0,
                                 "tier_ai": [0, 0], "tier_hh": [0, 0]},
                        "medium": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0], "n_pairs": 0,
                                   "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_tie": 0, "hc_loo_tie": 0,
                                   "tier_ai": [0, 0], "tier_hh": [0, 0]},
                        "hard": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0], "n_pairs": 0,
                                 "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_tie": 0, "hc_loo_tie": 0,
                                 "tier_ai": [0, 0], "tier_hh": [0, 0]}}

    for pair in controlled_pairs:
        diff = _classify_difficulty(pair[0], pair[1], papers_by_id)
        if diff is None:
            continue
        ds = difficulty_stats[diff]
        ds["n_pairs"] += 1

        # Tie counts per difficulty
        paper_a, paper_b = pair
        experts_for_pair_d = []
        for exp, ratings in experts_with_data.items():
            if paper_a in ratings and paper_b in ratings:
                has_pref = ratings[paper_a] != ratings[paper_b]
                experts_for_pair_d.append((exp, has_pref))
        for i in range(len(experts_for_pair_d)):
            for j in range(i + 1, len(experts_for_pair_d)):
                _, e1p = experts_for_pair_d[i]
                _, e2p = experts_for_pair_d[j]
                if e1p and e2p:
                    pass
                elif not e1p and not e2p:
                    ds["hh_tie_both"] += 1
                else:
                    ds["hh_tie_one"] += 1
        for _, has_pref in experts_for_pair_d:
            if not has_pref:
                ds["ah_tie"] += 1

        # HC/HC-LOO tie counts per difficulty
        if pair in expert_majority:
            for _, has_pref in experts_for_pair_d:
                if not has_pref:
                    ds["hc_tie"] += 1
        votes = expert_pair_prefs.get(pair, {})
        for exp_name, has_pref in experts_for_pair_d:
            if has_pref:
                continue
            others = [w for e, w in votes.items()]
            if len(others) >= 2:
                c = Counter(others)
                best, n = c.most_common(1)[0]
                if n > len(others) / 2:
                    ds["hc_loo_tie"] += 1

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
        # Tier accuracy per difficulty
        pa_d, pb_d = papers_by_id.get(pair[0], {}), papers_by_id.get(pair[1], {})
        ta_d, tb_d = norm_tier(pa_d.get("decision")), norm_tier(pb_d.get("decision"))
        if ta_d is not None and tb_d is not None:
            sa_d, sb_d = TIER_SCORE.get(ta_d, -1), TIER_SCORE.get(tb_d, -1)
            if sa_d != sb_d:
                tier_w = pair[0] if sa_d > sb_d else pair[1]
                ds["tier_ai"][1] += 1
                if ai_pair[pair] == tier_w:
                    ds["tier_ai"][0] += 1
                for exp, winner in expert_pair_prefs[pair].items():
                    ds["tier_hh"][1] += 1
                    if winner == tier_w:
                        ds["tier_hh"][0] += 1

    # --- Layer 5: BT rank correlation ---
    # Build human BT from committee (majority) matches
    human_committee_matches = []
    for pair in controlled_pairs:
        if pair in expert_majority:
            human_committee_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": expert_majority[pair],
                "completed": True, "failed": False,
            })
    # Build human BT from individual expert votes (each expert vote = one match)
    human_individual_matches = []
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            human_individual_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": winner,
                "completed": True, "failed": False,
            })
    # AI BT from ALL matches (not just controlled pairs) — avoids easy-subset inflation
    all_ai_bt_matches = [
        {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
         "winner_id": m["winner_id"], "completed": True, "failed": False}
        for m in ai_raw if m.get("winner_id")
    ]
    all_ai_paper_ids = set()
    for m in ai_raw:
        all_ai_paper_ids.add(m["paper1_id"])
        all_ai_paper_ids.add(m["paper2_id"])
    all_ai_papers = [papers_by_id[pid] for pid in all_ai_paper_ids if pid in papers_by_id]

    ctrl_paper_ids = set()
    for p in controlled_pairs:
        ctrl_paper_ids.add(p[0])
        ctrl_paper_ids.add(p[1])

    def _bt_correlate(h_matches, a_matches):
        """Compute Spearman rho and Kendall tau between human and AI BT rankings."""
        if len(h_matches) < 10 or len(a_matches) < 10:
            return None, None
        h_lb = compute_leaderboard(all_ai_papers, h_matches)
        a_lb = compute_leaderboard(all_ai_papers, a_matches)
        h_rank = {e["id"]: e["rank"] for e in h_lb}
        a_rank = {e["id"]: e["rank"] for e in a_lb}
        shared = sorted(set(h_rank.keys()) & set(a_rank.keys()))
        if len(shared) < 5:
            return None, None
        sp, _ = scipy_stats.spearmanr([h_rank[pid] for pid in shared],
                                       [a_rank[pid] for pid in shared])
        kt, _ = scipy_stats.kendalltau([h_rank[pid] for pid in shared],
                                        [a_rank[pid] for pid in shared])
        rho = float(sp) if not np.isnan(sp) else None
        tau = float(kt) if not np.isnan(kt) else None
        return rho, tau

    bt_comm_rho, bt_comm_tau = _bt_correlate(human_committee_matches, all_ai_bt_matches)
    bt_indiv_rho, bt_indiv_tau = _bt_correlate(human_individual_matches, all_ai_bt_matches)

    # Direct ranking: AI BT (all matches) vs h1_avg_rating
    bt_vs_avg_rho = None
    if len(all_ai_bt_matches) >= 10:
        ai_bt_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, all_ai_bt_matches)}
        avg_rating_map = {}
        for pid in all_ai_paper_ids:
            p = papers_by_id.get(pid)
            if p:
                r = p.get("h1_avg_rating")
                if r is None:
                    evals = p.get("evaluations", [])
                    vals = [e["rating_value"] for e in evals if e.get("rating_value")]
                    r = sum(vals) / len(vals) if vals else None
                if r is not None:
                    avg_rating_map[pid] = r
        shared = sorted(set(ai_bt_rank.keys()) & set(avg_rating_map.keys()))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([ai_bt_rank[p] for p in shared],
                                           [-avg_rating_map[p] for p in shared])
            if not np.isnan(sp):
                bt_vs_avg_rho = float(sp)

    # Build tier score map for all papers (used by both AI and per-expert tier correlation)
    tier_score_map = {}
    for pid in all_ai_paper_ids:
        p = papers_by_id.get(pid)
        if p:
            t = norm_tier(p.get("decision"))
            if t and t in TIER_SCORE:
                tier_score_map[pid] = TIER_SCORE[t]

    # AI BT vs ICLR tier decisions (program committee)
    bt_vs_tier_rho = None
    bt_vs_tier_tau = None
    if len(all_ai_bt_matches) >= 10:
        if not ai_bt_rank:
            ai_bt_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, all_ai_bt_matches)}
        shared = sorted(set(ai_bt_rank.keys()) & set(tier_score_map.keys()))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([ai_bt_rank[p] for p in shared],
                                           [-tier_score_map[p] for p in shared])
            kt, _ = scipy_stats.kendalltau([ai_bt_rank[p] for p in shared],
                                            [-tier_score_map[p] for p in shared])
            if not np.isnan(sp):
                bt_vs_tier_rho = float(sp)
            if not np.isnan(kt):
                bt_vs_tier_tau = float(kt)

    # Internal human baselines: individual vs committee, per-expert correlations
    bt_indiv_vs_comm_rho, bt_indiv_vs_comm_tau = _bt_correlate(human_individual_matches, human_committee_matches)

    # Per-expert BT: build BT from each expert's preferences, correlate with committee, AI, individual aggregate
    expert_vs_comm_rhos = []
    expert_vs_comm_taus = []
    expert_vs_ai_rhos = []
    expert_vs_ai_taus = []
    expert_vs_indiv_rhos = []
    expert_vs_indiv_taus = []
    expert_vs_loo_rhos = []
    expert_vs_loo_taus = []
    expert_vs_loo_avg_rhos = []
    expert_vs_loo_avg_taus = []
    expert_vs_loo_indiv_rhos = []
    expert_vs_loo_indiv_taus = []
    expert_vs_tier_rhos = []
    expert_vs_tier_taus = []

    # Pre-compute reference leaderboards once
    comm_rank = {}
    if len(human_committee_matches) >= 10:
        comm_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, human_committee_matches)}
    ai_rank = {}
    if len(all_ai_bt_matches) >= 10:
        ai_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, all_ai_bt_matches)}
    indiv_rank = {}
    if len(human_individual_matches) >= 10:
        indiv_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, human_individual_matches)}

    for exp in experts_with_data:
        exp_matches = []
        for pair in controlled_pairs:
            if exp in expert_pair_prefs.get(pair, {}):
                exp_matches.append({
                    "paper1_id": pair[0], "paper2_id": pair[1],
                    "winner_id": expert_pair_prefs[pair][exp],
                    "completed": True, "failed": False,
                })
        if len(exp_matches) < 10:
            continue
        exp_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, exp_matches)}

        for ref_rank, rho_list, tau_list in [
            (comm_rank, expert_vs_comm_rhos, expert_vs_comm_taus),
            (ai_rank, expert_vs_ai_rhos, expert_vs_ai_taus),
            (indiv_rank, expert_vs_indiv_rhos, expert_vs_indiv_taus),
        ]:
            if not ref_rank:
                continue
            shared = sorted(set(exp_rank.keys()) & set(ref_rank.keys()))
            if len(shared) < 5:
                continue
            sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in shared], [ref_rank[p] for p in shared])
            kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in shared], [ref_rank[p] for p in shared])
            if not np.isnan(sp):
                rho_list.append(float(sp))
            if not np.isnan(kt):
                tau_list.append(float(kt))

        # LOO committee for this expert: build BT from all OTHER experts' preferences (majority vote)
        loo_matches = []
        for pair in controlled_pairs:
            prefs = expert_pair_prefs.get(pair, {})
            others = {e: w for e, w in prefs.items() if e != exp}
            if len(others) < 2:
                continue
            c = Counter(others.values())
            best, n = c.most_common(1)[0]
            if n > len(others) / 2:
                loo_matches.append({
                    "paper1_id": pair[0], "paper2_id": pair[1],
                    "winner_id": best, "completed": True, "failed": False,
                })
        if len(loo_matches) >= 10:
            loo_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, loo_matches)}
            shared = sorted(set(exp_rank.keys()) & set(loo_rank.keys()))
            if len(shared) >= 5:
                sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in shared], [loo_rank[p] for p in shared])
                kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in shared], [loo_rank[p] for p in shared])
                if not np.isnan(sp):
                    expert_vs_loo_rhos.append(float(sp))
                if not np.isnan(kt):
                    expert_vs_loo_taus.append(float(kt))

        # LOO Individual Aggregate BT: each other expert's preference = 1 separate BT match
        loo_indiv_matches = []
        for pair in controlled_pairs:
            prefs = expert_pair_prefs.get(pair, {})
            for other_exp, winner in prefs.items():
                if other_exp != exp:
                    loo_indiv_matches.append({
                        "paper1_id": pair[0], "paper2_id": pair[1],
                        "winner_id": winner, "completed": True, "failed": False,
                    })
        if len(loo_indiv_matches) >= 10:
            loo_indiv_rank = {e["id"]: e["rank"] for e in compute_leaderboard(all_ai_papers, loo_indiv_matches)}
            shared = sorted(set(exp_rank.keys()) & set(loo_indiv_rank.keys()))
            if len(shared) >= 5:
                sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in shared], [loo_indiv_rank[p] for p in shared])
                kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in shared], [loo_indiv_rank[p] for p in shared])
                if not np.isnan(sp):
                    expert_vs_loo_indiv_rhos.append(float(sp))
                if not np.isnan(kt):
                    expert_vs_loo_indiv_taus.append(float(kt))

        # LOO h1_avg: average of all OTHER experts' scores per paper
        loo_avg = {}
        for pid in ctrl_paper_ids:
            other_scores = []
            for other_exp, ratings in experts_with_data.items():
                if other_exp == exp:
                    continue
                if pid in ratings:
                    other_scores.append(ratings[pid])
            if other_scores:
                loo_avg[pid] = float(np.mean(other_scores))
        shared_avg = sorted(set(exp_rank.keys()) & set(loo_avg.keys()))
        if len(shared_avg) >= 5:
            sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in shared_avg],
                                           [-loo_avg[p] for p in shared_avg])
            kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in shared_avg],
                                            [-loo_avg[p] for p in shared_avg])
            if not np.isnan(sp):
                expert_vs_loo_avg_rhos.append(float(sp))
            if not np.isnan(kt):
                expert_vs_loo_avg_taus.append(float(kt))

        # Expert BT vs ICLR tier decisions
        if tier_score_map:
            tier_shared = sorted(set(exp_rank.keys()) & set(tier_score_map.keys()))
            if len(tier_shared) >= 5:
                sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in tier_shared],
                                               [-tier_score_map[p] for p in tier_shared])
                kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in tier_shared],
                                                [-tier_score_map[p] for p in tier_shared])
                if not np.isnan(sp):
                    expert_vs_tier_rhos.append(float(sp))
                if not np.isnan(kt):
                    expert_vs_tier_taus.append(float(kt))

    avg_expert_vs_comm_rho = float(np.mean(expert_vs_comm_rhos)) if expert_vs_comm_rhos else None
    avg_expert_vs_comm_tau = float(np.mean(expert_vs_comm_taus)) if expert_vs_comm_taus else None
    avg_expert_vs_ai_rho = float(np.mean(expert_vs_ai_rhos)) if expert_vs_ai_rhos else None
    avg_expert_vs_ai_tau = float(np.mean(expert_vs_ai_taus)) if expert_vs_ai_taus else None
    avg_expert_vs_indiv_rho = float(np.mean(expert_vs_indiv_rhos)) if expert_vs_indiv_rhos else None
    avg_expert_vs_indiv_tau = float(np.mean(expert_vs_indiv_taus)) if expert_vs_indiv_taus else None
    avg_expert_vs_loo_rho = float(np.mean(expert_vs_loo_rhos)) if expert_vs_loo_rhos else None
    avg_expert_vs_loo_tau = float(np.mean(expert_vs_loo_taus)) if expert_vs_loo_taus else None
    avg_expert_vs_loo_avg_rho = float(np.mean(expert_vs_loo_avg_rhos)) if expert_vs_loo_avg_rhos else None
    avg_expert_vs_loo_avg_tau = float(np.mean(expert_vs_loo_avg_taus)) if expert_vs_loo_avg_taus else None
    avg_expert_vs_loo_indiv_rho = float(np.mean(expert_vs_loo_indiv_rhos)) if expert_vs_loo_indiv_rhos else None
    avg_expert_vs_loo_indiv_tau = float(np.mean(expert_vs_loo_indiv_taus)) if expert_vs_loo_indiv_taus else None
    avg_expert_vs_tier_rho = float(np.mean(expert_vs_tier_rhos)) if expert_vs_tier_rhos else None
    avg_expert_vs_tier_tau = float(np.mean(expert_vs_tier_taus)) if expert_vs_tier_taus else None

    # --- Layer 6: Cohen's kappa ---
    hh_kappa = _cohens_kappa(hh_agree, hh_total)
    hc_kappa = _cohens_kappa(hc_agree, hc_total)
    hc_loo_kappa = _cohens_kappa(hc_loo_agree, hc_loo_total)
    ah_kappa = _cohens_kappa(ah_agree, ah_total)
    ac_kappa = _cohens_kappa(ac_agree, ac_total)

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    def _cf_rate(agree, nontie_total, tie_count):
        total = nontie_total + tie_count
        if total == 0:
            return None
        return round((agree + 0.5 * tie_count) / total * 100, 1)


    def _format_difficulty(stats):
        result = {}
        for level in ["easy", "medium", "hard"]:
            s = stats[level]
            hh_a, hh_t = s["hh"][0], s["hh"][1]
            ah_a, ah_t = s["ah"][0], s["ah"][1]
            hh_t1, hh_t2, ah_ti = s["hh_tie_one"], s["hh_tie_both"], s["ah_tie"]
            hc_loo_a, hc_loo_t = s["hc_loo"][0], s["hc_loo"][1]
            hc_loo_ti = s["hc_loo_tie"]
            # Coin-flip rates
            hh_cf_total = hh_t + hh_t1 + hh_t2
            ah_cf_total = ah_t + ah_ti
            hh_cf = round((hh_a + 0.5 * (hh_t1 + hh_t2)) / max(hh_cf_total, 1) * 100, 1) if hh_cf_total > 0 else None
            ah_cf = round((ah_a + 0.5 * ah_ti) / max(ah_cf_total, 1) * 100, 1) if ah_cf_total > 0 else None
            hc_loo_cf_total = hc_loo_t + hc_loo_ti
            hc_loo_cf = round((hc_loo_a + 0.5 * hc_loo_ti) / max(hc_loo_cf_total, 1) * 100, 1) if hc_loo_cf_total > 0 else None
            result[level] = {
                "human_human": {"rate": _rate(hh_a, hh_t), "pairs": hh_t},
                "human_committee": {"rate": _rate(s["hc"][0], s["hc"][1]), "pairs": s["hc"][1]},
                "human_committee_loo": {"rate": _rate(hc_loo_a, hc_loo_t), "pairs": hc_loo_t},
                "ai_human": {"rate": _rate(ah_a, ah_t), "pairs": ah_t},
                "ai_committee": {"rate": _rate(s["ac"][0], s["ac"][1]), "pairs": s["ac"][1]},
                "n_pairs": s["n_pairs"],
                "hh_cf": hh_cf,
                "ah_cf": ah_cf,
                "hc_loo_cf": hc_loo_cf,
                "hh_cf_n": hh_cf_total,
                "ah_cf_n": ah_cf_total,
                "hc_loo_cf_n": hc_loo_cf_total,
                "tier_ai": {"rate": _rate(s["tier_ai"][0], s["tier_ai"][1]), "pairs": s["tier_ai"][1]},
                "tier_hh": {"rate": _rate(s["tier_hh"][0], s["tier_hh"][1]), "pairs": s["tier_hh"][1]},
                "ah_cf_kappa": safe_round(_cohens_kappa(int(ah_a + 0.5 * ah_ti), ah_cf_total)) if ah_cf_total > 0 else None,
                "hh_tie_one": hh_t1,
                "hh_tie_both": hh_t2,
                "ah_tie": ah_ti,
                "hc_loo_tie": hc_loo_ti,
            }
        return result

    return {
        "dataset_id": dataset_id,
        "n_papers": len(papers),
        "n_experts": len(experts_with_data),
        "controlled_pairs": len(controlled_pairs),
        "ai_mode": ai_mode_used,
        "inter_rater_rho": safe_round(rho) if rho else None,
        "ai_h_concordance": safe_round(ai_h_concordance) if ai_h_concordance else None,
        "ai_h_cf_concordance": safe_round(ai_h_cf_concordance) if ai_h_cf_concordance else None,
        "ai_h_rho": safe_round(ai_h_rho) if ai_h_rho else None,
        "tie_stats": tie_stats,
        "tie_impact": {
            "hh_agree": hh_agree, "hh_total": hh_total,
            "hh_tie_one": hh_tie_one, "hh_tie_both": hh_tie_both,
            "ah_agree": ah_agree, "ah_total": ah_total,
            "ah_tie": ah_tie,
            "hc_agree": hc_agree, "hc_total": hc_total, "hc_tie": hc_tie,
            "hc_loo_agree": hc_loo_agree, "hc_loo_total": hc_loo_total, "hc_loo_tie": hc_loo_tie,
            "ac_agree": ac_agree, "ac_total": ac_total,
        },
        "tie_validation": {
            "ai_agree": tv_ai_agree, "ai_total": tv_ai_total,
            "ai_rate": _rate(tv_ai_agree, tv_ai_total),
            "hh_agree": tv_hh_agree, "hh_total": tv_hh_total,
            "hh_rate": _rate(tv_hh_agree, tv_hh_total),
        },
        "tier_accuracy": {
            "ai_agree": tier_ai_agree, "ai_total": tier_ai_total,
            "ai_rate": _rate(tier_ai_agree, tier_ai_total),
            "hh_agree": tier_hh_agree, "hh_total": tier_hh_total,
            "hh_rate": _rate(tier_hh_agree, tier_hh_total),
        },
        "n_rater_pairs": n_pairs,
        "ceiling": ceiling,
        "pairwise": {
            "human_human": {"agree": hh_agree, "total": hh_total, "rate": _rate(hh_agree, hh_total),
                            "kappa": safe_round(hh_kappa), "ci": _wilson_ci(hh_agree, hh_total),
                            "cf_rate": _cf_rate(hh_agree, hh_total, hh_tie_one + hh_tie_both)},
            "human_committee": {"agree": hc_agree, "total": hc_total, "rate": _rate(hc_agree, hc_total),
                                "kappa": safe_round(hc_kappa), "ci": _wilson_ci(hc_agree, hc_total)},
            "human_committee_loo": {"agree": hc_loo_agree, "total": hc_loo_total, "rate": _rate(hc_loo_agree, hc_loo_total),
                                    "kappa": safe_round(hc_loo_kappa), "ci": _wilson_ci(hc_loo_agree, hc_loo_total),
                                    "cf_rate": _cf_rate(hc_loo_agree, hc_loo_total, hc_loo_tie)},
            "ai_human": {"agree": ah_agree, "total": ah_total, "rate": _rate(ah_agree, ah_total),
                         "kappa": safe_round(ah_kappa), "ci": _wilson_ci(ah_agree, ah_total),
                         "cf_rate": _cf_rate(ah_agree, ah_total, ah_tie)},
            "ai_committee": {"agree": ac_agree, "total": ac_total, "rate": _rate(ac_agree, ac_total),
                             "kappa": safe_round(ac_kappa), "ci": _wilson_ci(ac_agree, ac_total)},
        },
        "by_difficulty": _format_difficulty(difficulty_stats),
        "bt_correlation": {
            "committee": {
                "spearman_rho": safe_round(bt_comm_rho) if bt_comm_rho else None,
                "kendall_tau": safe_round(bt_comm_tau) if bt_comm_tau else None,
            },
            "individual": {
                "spearman_rho": safe_round(bt_indiv_rho) if bt_indiv_rho else None,
                "kendall_tau": safe_round(bt_indiv_tau) if bt_indiv_tau else None,
            },
            "indiv_vs_comm": {
                "spearman_rho": safe_round(bt_indiv_vs_comm_rho) if bt_indiv_vs_comm_rho else None,
                "kendall_tau": safe_round(bt_indiv_vs_comm_tau) if bt_indiv_vs_comm_tau else None,
            },
            "avg_expert_vs_comm": {
                "spearman_rho": safe_round(avg_expert_vs_comm_rho) if avg_expert_vs_comm_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_comm_tau) if avg_expert_vs_comm_tau else None,
            },
            "avg_expert_vs_ai": {
                "spearman_rho": safe_round(avg_expert_vs_ai_rho) if avg_expert_vs_ai_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_ai_tau) if avg_expert_vs_ai_tau else None,
            },
            "avg_expert_vs_indiv": {
                "spearman_rho": safe_round(avg_expert_vs_indiv_rho) if avg_expert_vs_indiv_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_indiv_tau) if avg_expert_vs_indiv_tau else None,
            },
            "avg_expert_vs_loo": {
                "spearman_rho": safe_round(avg_expert_vs_loo_rho) if avg_expert_vs_loo_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_loo_tau) if avg_expert_vs_loo_tau else None,
            },
            "avg_expert_vs_loo_avg": {
                "spearman_rho": safe_round(avg_expert_vs_loo_avg_rho) if avg_expert_vs_loo_avg_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_loo_avg_tau) if avg_expert_vs_loo_avg_tau else None,
            },
            "avg_expert_vs_loo_indiv": {
                "spearman_rho": safe_round(avg_expert_vs_loo_indiv_rho) if avg_expert_vs_loo_indiv_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_loo_indiv_tau) if avg_expert_vs_loo_indiv_tau else None,
            },
            "vs_tier_rho": safe_round(bt_vs_tier_rho) if bt_vs_tier_rho else None,
            "vs_tier_tau": safe_round(bt_vs_tier_tau) if bt_vs_tier_tau else None,
            "avg_expert_vs_tier": {
                "spearman_rho": safe_round(avg_expert_vs_tier_rho) if avg_expert_vs_tier_rho else None,
                "kendall_tau": safe_round(avg_expert_vs_tier_tau) if avg_expert_vs_tier_tau else None,
            },
            "n_papers": len(ctrl_paper_ids),
            "vs_avg_rating_rho": safe_round(bt_vs_avg_rho) if bt_vs_avg_rho else None,
        },
    }


@router.get("/human-ai-benchmark")
async def human_ai_benchmark(gt_type: str = Query("comp")):
    """Comprehensive human vs AI agreement benchmark — served from precomputed cache only."""
    cache = _benchmark_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    return {"status": "no_data", "message": "Human-AI benchmark not precomputed. Run admin precompute-experiments."}


async def _compute_benchmark(gt_type: str = "comp"):
    """Compute the full benchmark across datasets filtered by GT type.
    gt_type='comp': comparative GT (ICLR, PeerRead, eLife Neuro)
    gt_type='stan': standalone GT (eLife bio, MIDL, Qeios, ResearchHub)
    """
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS

    # Discover datasets with evaluations, filtered by GT type
    ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
    all_ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)
                  if r["_id"] in allowed]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    per_dataset = []
    pooled = {
        "hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0],
        "bt_comm_rhos": [], "bt_comm_taus": [],
        "bt_indiv_rhos": [], "bt_indiv_taus": [],
        "bt_ivc_rhos": [], "bt_ivc_taus": [],
        "bt_evc_rhos": [], "bt_evc_taus": [],
        "bt_eva_rhos": [], "bt_eva_taus": [],
        "bt_evi_rhos": [], "bt_evi_taus": [],
        "bt_avg_rating_rhos": [],
        "inter_rater_rhos": [],
        "ai_h_concordances": [],
        "concordance_rates": [],
        "ceilings": [],
        "total_pairs": 0,
        "total_papers": 0,
        "tie_concordant": 0, "tie_discordant": 0, "tie_excluded": 0,
        # Tie impact accumulators
        "ti_hh_tie_one": 0, "ti_hh_tie_both": 0,
        "ti_ah_tie": 0,
        "ti_hc_tie": 0, "ti_hc_loo_tie": 0,
        "difficulty": {"easy": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0], "n_pairs": 0,
                               "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_loo_tie": 0,
                               "tier_ai": [0, 0], "tier_hh": [0, 0]},
                       "medium": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0], "n_pairs": 0,
                                  "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_loo_tie": 0,
                                  "tier_ai": [0, 0], "tier_hh": [0, 0]},
                       "hard": {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0], "n_pairs": 0,
                                "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_loo_tie": 0,
                                "tier_ai": [0, 0], "tier_hh": [0, 0]}},
    }

    # For comp GT, no longer restrict to SI-scored papers
    # (that was for the old PW vs SI comparison pages)
    require_si = False

    # Compute all datasets in parallel
    tasks = [_compute_dataset_benchmark(ds_id, require_si=require_si) for ds_id in all_ds_ids]
    results_list = await asyncio.gather(*tasks)

    for ds_id, result in zip(all_ds_ids, results_list):
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
        pooled["total_papers"] += result["n_papers"]

        if result.get("inter_rater_rho") is not None:
            pooled["inter_rater_rhos"].append(result["inter_rater_rho"])
        if result.get("ai_h_concordance") is not None:
            pooled["ai_h_concordances"].append(result["ai_h_concordance"])
        if result.get("ai_h_cf_concordance") is not None:
            pooled.setdefault("ai_h_cf_concordances", []).append(result["ai_h_cf_concordance"])
        ts = result.get("tie_stats", {})
        if ts:
            pooled["tie_concordant"] += ts.get("concordant", 0)
            pooled["tie_discordant"] += ts.get("discordant", 0)
            pooled["tie_excluded"] += ts.get("tied_excluded", 0)
            if ts.get("concordance_rate") is not None:
                pooled["concordance_rates"].append(ts["concordance_rate"])
            if ts.get("cf_concordance_rate") is not None:
                pooled.setdefault("cf_concordance_rates", []).append(ts["cf_concordance_rate"])
        ti = result.get("tie_impact", {})
        pooled["ti_hh_tie_one"] += ti.get("hh_tie_one", 0)
        pooled["ti_hh_tie_both"] += ti.get("hh_tie_both", 0)
        pooled["ti_ah_tie"] += ti.get("ah_tie", 0)
        pooled["ti_hc_tie"] += ti.get("hc_tie", 0)
        pooled["ti_hc_loo_tie"] += ti.get("hc_loo_tie", 0)
        if result.get("ceiling") and result["ceiling"].get("overall"):
            pooled["ceilings"].append(result["ceiling"]["overall"])
        bt = result.get("bt_correlation", {})
        bt_c = bt.get("committee", {})
        bt_i = bt.get("individual", {})
        if bt_c.get("spearman_rho") is not None:
            pooled["bt_comm_rhos"].append(bt_c["spearman_rho"])
        if bt_c.get("kendall_tau") is not None:
            pooled["bt_comm_taus"].append(bt_c["kendall_tau"])
        if bt_i.get("spearman_rho") is not None:
            pooled["bt_indiv_rhos"].append(bt_i["spearman_rho"])
        if bt_i.get("kendall_tau") is not None:
            pooled["bt_indiv_taus"].append(bt_i["kendall_tau"])
        for src, dst_r, dst_t in [
            ("indiv_vs_comm", "bt_ivc_rhos", "bt_ivc_taus"),
            ("avg_expert_vs_comm", "bt_evc_rhos", "bt_evc_taus"),
            ("avg_expert_vs_ai", "bt_eva_rhos", "bt_eva_taus"),
            ("avg_expert_vs_indiv", "bt_evi_rhos", "bt_evi_taus"),
        ]:
            sub = bt.get(src, {})
            if sub.get("spearman_rho") is not None:
                pooled[dst_r].append(sub["spearman_rho"])
            if sub.get("kendall_tau") is not None:
                pooled[dst_t].append(sub["kendall_tau"])
        if bt.get("vs_avg_rating_rho") is not None:
            pooled["bt_avg_rating_rhos"].append(bt["vs_avg_rating_rho"])
        loo_sub = bt.get("avg_expert_vs_loo", {})
        if loo_sub.get("spearman_rho") is not None:
            pooled.setdefault("bt_loo_rhos", []).append(loo_sub["spearman_rho"])
        if loo_sub.get("kendall_tau") is not None:
            pooled.setdefault("bt_loo_taus", []).append(loo_sub["kendall_tau"])
        loo_avg_sub = bt.get("avg_expert_vs_loo_avg", {})
        if loo_avg_sub.get("spearman_rho") is not None:
            pooled.setdefault("bt_loo_avg_rhos", []).append(loo_avg_sub["spearman_rho"])
        if loo_avg_sub.get("kendall_tau") is not None:
            pooled.setdefault("bt_loo_avg_taus", []).append(loo_avg_sub["kendall_tau"])
        loo_indiv_sub = bt.get("avg_expert_vs_loo_indiv", {})
        if loo_indiv_sub.get("spearman_rho") is not None:
            pooled.setdefault("bt_loo_indiv_rhos", []).append(loo_indiv_sub["spearman_rho"])
        if loo_indiv_sub.get("kendall_tau") is not None:
            pooled.setdefault("bt_loo_indiv_taus", []).append(loo_indiv_sub["kendall_tau"])
        if bt.get("vs_tier_rho") is not None:
            pooled.setdefault("bt_tier_rhos", []).append(bt["vs_tier_rho"])
        if bt.get("vs_tier_tau") is not None:
            pooled.setdefault("bt_tier_taus", []).append(bt["vs_tier_tau"])
        exp_tier_sub = bt.get("avg_expert_vs_tier", {})
        if exp_tier_sub.get("spearman_rho") is not None:
            pooled.setdefault("bt_exp_tier_rhos", []).append(exp_tier_sub["spearman_rho"])
        if exp_tier_sub.get("kendall_tau") is not None:
            pooled.setdefault("bt_exp_tier_taus", []).append(exp_tier_sub["kendall_tau"])
        tv = result.get("tie_validation", {})
        pooled.setdefault("tv_ai_agree", 0)
        pooled.setdefault("tv_ai_total", 0)
        pooled.setdefault("tv_hh_agree", 0)
        pooled.setdefault("tv_hh_total", 0)
        pooled["tv_ai_agree"] += tv.get("ai_agree", 0)
        pooled["tv_ai_total"] += tv.get("ai_total", 0)
        pooled["tv_hh_agree"] += tv.get("hh_agree", 0)
        pooled["tv_hh_total"] += tv.get("hh_total", 0)
        ta = result.get("tier_accuracy", {})
        pooled.setdefault("tier_ai_agree", 0)
        pooled.setdefault("tier_ai_total", 0)
        pooled.setdefault("tier_hh_agree", 0)
        pooled.setdefault("tier_hh_total", 0)
        pooled["tier_ai_agree"] += ta.get("ai_agree", 0)
        pooled["tier_ai_total"] += ta.get("ai_total", 0)
        pooled["tier_hh_agree"] += ta.get("hh_agree", 0)
        pooled["tier_hh_total"] += ta.get("hh_total", 0)

        # Pool difficulty stats
        for level in ["easy", "medium", "hard"]:
            for metric in ["hh", "hc", "hc_loo", "ah", "ac"]:
                metric_full = {"hh": "human_human", "hc": "human_committee",
                               "hc_loo": "human_committee_loo",
                               "ah": "ai_human", "ac": "ai_committee"}[metric]
                d = result.get("by_difficulty", {}).get(level, {}).get(metric_full, {})
                pooled["difficulty"][level][metric][0] += int(d.get("rate", 0) * d.get("pairs", 0) / 100)
                pooled["difficulty"][level][metric][1] += d.get("pairs", 0)
            pooled["difficulty"][level]["n_pairs"] += result.get("by_difficulty", {}).get(level, {}).get("n_pairs", 0)
            dl = result.get("by_difficulty", {}).get(level, {})
            pooled["difficulty"][level]["hh_tie_one"] += dl.get("hh_tie_one", 0)
            pooled["difficulty"][level]["hh_tie_both"] += dl.get("hh_tie_both", 0)
            pooled["difficulty"][level]["ah_tie"] += dl.get("ah_tie", 0)
            pooled["difficulty"][level]["hc_loo_tie"] += dl.get("hc_loo_tie", 0)
            # Tier accuracy per difficulty
            for tm in ["tier_ai", "tier_hh"]:
                td = dl.get(tm, {})
                pooled["difficulty"][level][tm][0] += int(td.get("rate", 0) * td.get("pairs", 0) / 100)
                pooled["difficulty"][level][tm][1] += td.get("pairs", 0)

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
            hh_a, hh_t = s["hh"][0], s["hh"][1]
            ah_a, ah_t = s["ah"][0], s["ah"][1]
            hh_t1, hh_t2, ah_ti = s["hh_tie_one"], s["hh_tie_both"], s["ah_tie"]
            hc_loo_a, hc_loo_t = s["hc_loo"][0], s["hc_loo"][1]
            hc_loo_ti = s["hc_loo_tie"]
            hh_cf_total = hh_t + hh_t1 + hh_t2
            ah_cf_total = ah_t + ah_ti
            hh_cf = round((hh_a + 0.5 * (hh_t1 + hh_t2)) / max(hh_cf_total, 1) * 100, 1) if hh_cf_total > 0 else None
            ah_cf = round((ah_a + 0.5 * ah_ti) / max(ah_cf_total, 1) * 100, 1) if ah_cf_total > 0 else None
            hc_loo_cf_total = hc_loo_t + hc_loo_ti
            hc_loo_cf = round((hc_loo_a + 0.5 * hc_loo_ti) / max(hc_loo_cf_total, 1) * 100, 1) if hc_loo_cf_total > 0 else None
            result[level] = {
                "human_human": {"rate": _rate(hh_a, hh_t), "pairs": hh_t},
                "human_committee": {"rate": _rate(s["hc"][0], s["hc"][1]), "pairs": s["hc"][1]},
                "human_committee_loo": {"rate": _rate(hc_loo_a, hc_loo_t), "pairs": hc_loo_t},
                "ai_human": {"rate": _rate(ah_a, ah_t), "pairs": ah_t},
                "ai_committee": {"rate": _rate(s["ac"][0], s["ac"][1]), "pairs": s["ac"][1]},
                "n_pairs": s["n_pairs"],
                "hh_cf": hh_cf,
                "ah_cf": ah_cf,
                "hc_loo_cf": hc_loo_cf,
                "hh_cf_n": hh_cf_total,
                "ah_cf_n": ah_cf_total,
                "hc_loo_cf_n": hc_loo_cf_total,
                "tier_ai": {"rate": _rate(s["tier_ai"][0], s["tier_ai"][1]), "pairs": s["tier_ai"][1]},
                "tier_hh": {"rate": _rate(s["tier_hh"][0], s["tier_hh"][1]), "pairs": s["tier_hh"][1]},
                "ah_cf_kappa": safe_round(_cohens_kappa(int(ah_a + 0.5 * ah_ti), ah_cf_total)) if ah_cf_total > 0 else None,
                "hh_tie_rate": round((hh_t1 + hh_t2) / max(hh_t + hh_t1 + hh_t2, 1) * 100, 1),
            }
        return result

    # Pooled tie stats
    total_tie_all = pooled["tie_concordant"] + pooled["tie_discordant"] + pooled["tie_excluded"]
    pooled_tie_stats = {
        "concordant": pooled["tie_concordant"],
        "discordant": pooled["tie_discordant"],
        "tied_excluded": pooled["tie_excluded"],
        "tie_fraction": round(pooled["tie_excluded"] / max(total_tie_all, 1), 4),
        "concordance_rate": round(float(np.mean(pooled["concordance_rates"])), 4) if pooled["concordance_rates"] else None,
        "cf_concordance_rate": round(float(np.mean(pooled.get("cf_concordance_rates", []))), 4) if pooled.get("cf_concordance_rates") else None,
    }

    # Pooled AI-human concordance
    ai_h_conc_avg = float(np.mean(pooled["ai_h_concordances"])) if pooled["ai_h_concordances"] else None
    ai_h_cf_conc_avg = float(np.mean(pooled.get("ai_h_cf_concordances", []))) if pooled.get("ai_h_cf_concordances") else None
    ai_h_rho_avg = math.sin(math.pi * (ai_h_conc_avg - 0.5)) if ai_h_conc_avg else None

    # Pooled tie impact analysis — compute coin-flip rates for all metrics
    hh_a, hh_t = pooled["hh"][0], pooled["hh"][1]
    ah_a, ah_t = pooled["ah"][0], pooled["ah"][1]
    hc_a, hc_t = pooled["hc"][0], pooled["hc"][1]
    hc_loo_a, hc_loo_t = pooled["hc_loo"][0], pooled["hc_loo"][1]
    ac_a, ac_t = pooled["ac"][0], pooled["ac"][1]
    hh_t1, hh_t2 = pooled["ti_hh_tie_one"], pooled["ti_hh_tie_both"]
    ah_tie = pooled["ti_ah_tie"]
    hc_tie = pooled["ti_hc_tie"]
    hc_loo_tie = pooled["ti_hc_loo_tie"]

    hh_total_cf = hh_t + hh_t1 + hh_t2
    ah_total_cf = ah_t + ah_tie

    def _cf_rate(agree, nontie_total, tie_count):
        """Coin-flip rate: existing agrees + 50% of tie comparisons."""
        total = nontie_total + tie_count
        if total == 0:
            return None
        return round((agree + 0.5 * tie_count) / total * 100, 1)

    hh_cf_rate = _cf_rate(hh_a, hh_t, hh_t1 + hh_t2)
    ah_cf_rate = _cf_rate(ah_a, ah_t, ah_tie)
    hc_cf_rate = _cf_rate(hc_a, hc_t, hc_tie)
    hc_loo_cf_rate = _cf_rate(hc_loo_a, hc_loo_t, hc_loo_tie)
    # AI-Comm: AI never ties and committee is built from non-tie votes,
    # so the coin-flip doesn't change AI-Comm directly. Keep as-is.
    ac_cf_rate = _rate(ac_a, ac_t) if ac_t > 0 else None
    # kappa for coin-flip AI-H
    ah_cf_agree = ah_a + 0.5 * ah_tie
    ah_cf_kappa = safe_round(_cohens_kappa(int(ah_cf_agree), ah_total_cf)) if ah_total_cf > 0 else None

    def _tie_pct(tie_count, nontie_total):
        total = nontie_total + tie_count
        if total == 0:
            return None
        return round(tie_count / total * 100, 1)

    tie_impact = {
        "coin_flip": {
            "human_human": hh_cf_rate,
            "human_committee": hc_cf_rate,
            "human_committee_loo": hc_loo_cf_rate,
            "ai_human": ah_cf_rate,
            "ai_committee": ac_cf_rate,
            "ai_human_kappa": ah_cf_kappa,
            "total_pairs": hh_total_cf,
        },
        "excluded": {
            "hh_rate": _rate(hh_a, hh_t),
            "ah_rate": _rate(ah_a, ah_t),
        },
        "tie_rates": {
            "hh": _tie_pct(hh_t1 + hh_t2, hh_t),
            "ah": _tie_pct(ah_tie, ah_t),
            "hc_loo": _tie_pct(hc_loo_tie, hc_loo_t),
        },
        "tie_counts": {
            "hh_nontie": hh_t, "hh_one_tie": hh_t1, "hh_both_tie": hh_t2,
            "ah_nontie": ah_t, "ah_tie": ah_tie,
            "hc_tie": hc_tie, "hc_loo_tie": hc_loo_tie,
        },
    }

    summary = {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(per_dataset),
        "total_controlled_pairs": pooled["total_pairs"],
        "total_papers": pooled["total_papers"],
        "avg_matches_per_paper": round(2 * pooled["total_pairs"] / max(pooled["total_papers"], 1), 1),
        "pooled": {
            "inter_rater_rho": safe_round(float(np.mean(pooled["inter_rater_rhos"]))) if pooled["inter_rater_rhos"] else None,
            "ai_h_concordance": safe_round(ai_h_conc_avg) if ai_h_conc_avg else None,
            "ai_h_cf_concordance": safe_round(ai_h_cf_conc_avg) if ai_h_cf_conc_avg else None,
            "ai_h_rho": safe_round(ai_h_rho_avg) if ai_h_rho_avg else None,
            "tie_stats": pooled_tie_stats,
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
                "committee": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_comm_rhos"]))) if pooled["bt_comm_rhos"] else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_comm_taus"]))) if pooled["bt_comm_taus"] else None,
                },
                "individual": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_indiv_rhos"]))) if pooled["bt_indiv_rhos"] else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_indiv_taus"]))) if pooled["bt_indiv_taus"] else None,
                },
                "indiv_vs_comm": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_ivc_rhos"]))) if pooled["bt_ivc_rhos"] else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_ivc_taus"]))) if pooled["bt_ivc_taus"] else None,
                },
                "avg_expert_vs_comm": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_evc_rhos"]))) if pooled["bt_evc_rhos"] else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_evc_taus"]))) if pooled["bt_evc_taus"] else None,
                },
                "avg_expert_vs_ai": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_eva_rhos"]))) if pooled["bt_eva_rhos"] else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_eva_taus"]))) if pooled["bt_eva_taus"] else None,
                },
                "avg_expert_vs_indiv": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_evi_rhos"]))) if pooled["bt_evi_rhos"] else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_evi_taus"]))) if pooled["bt_evi_taus"] else None,
                },
                "avg_expert_vs_loo": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_loo_rhos"]))) if pooled.get("bt_loo_rhos") else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_loo_taus"]))) if pooled.get("bt_loo_taus") else None,
                },
                "avg_expert_vs_loo_avg": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_loo_avg_rhos"]))) if pooled.get("bt_loo_avg_rhos") else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_loo_avg_taus"]))) if pooled.get("bt_loo_avg_taus") else None,
                },
                "avg_expert_vs_loo_indiv": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_loo_indiv_rhos"]))) if pooled.get("bt_loo_indiv_rhos") else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_loo_indiv_taus"]))) if pooled.get("bt_loo_indiv_taus") else None,
                },
                "vs_tier_rho": safe_round(float(np.mean(pooled["bt_tier_rhos"]))) if pooled.get("bt_tier_rhos") else None,
                "vs_tier_tau": safe_round(float(np.mean(pooled["bt_tier_taus"]))) if pooled.get("bt_tier_taus") else None,
                "avg_expert_vs_tier": {
                    "spearman_rho": safe_round(float(np.mean(pooled["bt_exp_tier_rhos"]))) if pooled.get("bt_exp_tier_rhos") else None,
                    "kendall_tau": safe_round(float(np.mean(pooled["bt_exp_tier_taus"]))) if pooled.get("bt_exp_tier_taus") else None,
                },
                "vs_avg_rating_rho": safe_round(float(np.mean(pooled["bt_avg_rating_rhos"]))) if pooled["bt_avg_rating_rhos"] else None,
            },
            "by_difficulty": _format_pooled_difficulty(),
            "tie_impact": tie_impact,
            "tie_validation": {
                "ai_rate": _rate(pooled.get("tv_ai_agree", 0), pooled.get("tv_ai_total", 0)),
                "ai_total": pooled.get("tv_ai_total", 0),
                "hh_rate": _rate(pooled.get("tv_hh_agree", 0), pooled.get("tv_hh_total", 0)),
                "hh_total": pooled.get("tv_hh_total", 0),
            },
            "tier_accuracy": {
                "ai_rate": _rate(pooled.get("tier_ai_agree", 0), pooled.get("tier_ai_total", 0)),
                "ai_total": pooled.get("tier_ai_total", 0),
                "hh_rate": _rate(pooled.get("tier_hh_agree", 0), pooled.get("tier_hh_total", 0)),
                "hh_total": pooled.get("tier_hh_total", 0),
            },
        },
        "per_dataset": per_dataset,
    }

    return summary
