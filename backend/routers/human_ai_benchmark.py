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
    collect_all, build_expert_ratings, build_expert_majority, build_content_mode_filter,
    safe_round, PAPER_LIGHT_PROJECTION, norm_tier, TIER_ORDER,
    COMPARATIVE_GT_DATASETS, STANDALONE_GT_DATASETS,
)
from services.ranking import compute_leaderboard_async as compute_leaderboard

router = APIRouter(prefix="/api/validation")

_benchmark_cache = {"comp": {"data": None}, "stan": {"data": None}}
_benchmark_unfiltered_cache = {"comp": {"data": None}, "stan": {"data": None}}


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


async def _compute_dataset_benchmark(dataset_id: str, require_si: bool = False, include_within_tier: bool = False):
    """Compute all benchmark metrics for a single dataset."""
    query = {"dataset_id": dataset_id}
    if require_si:
        query["single_item_score"] = {"$exists": True}
    papers = await collect_all(db.validation_papers.find(query, PAPER_LIGHT_PROJECTION))
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

    # When including within-tier, add experiment within-tier matches to the base
    # cross/adjacent set, subsampled to their natural proportion.
    if include_within_tier:
        # Load base matches (no experiment tag) = cross/adjacent only
        base_raw = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))
        # Load experiment matches (within-tier supplements)
        exp_raw = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))

        import random as _rng
        TIER_MAP = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}
        def _is_within(m):
            t1 = norm_tier(papers_by_id.get(m["paper1_id"], {}).get("decision"))
            t2 = norm_tier(papers_by_id.get(m["paper2_id"], {}).get("decision"))
            return t1 is not None and t2 is not None and TIER_MAP.get(t1, -1) == TIER_MAP.get(t2, -2)

        # Combine base + all experiment matches, then ensure natural within-tier proportion
        all_combined = base_raw + exp_raw
        cross_adj = sorted([m for m in all_combined if not _is_within(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))
        within = sorted([m for m in all_combined if _is_within(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))

        # Compute natural within-tier fraction
        all_pids = list(papers_by_id.keys())
        nat_cross_adj, nat_within = 0, 0
        for i in range(len(all_pids)):
            for j in range(i+1, len(all_pids)):
                t1 = norm_tier(papers_by_id[all_pids[i]].get("decision"))
                t2 = norm_tier(papers_by_id[all_pids[j]].get("decision"))
                if t1 and t2:
                    if TIER_MAP.get(t1) == TIER_MAP.get(t2):
                        nat_within += 1
                    else:
                        nat_cross_adj += 1
        nat_total = nat_cross_adj + nat_within
        nat_within_frac = nat_within / nat_total if nat_total > 0 else 0.3

        # Subsample within-tier to natural proportion relative to cross/adj
        target_within = int(len(cross_adj) * nat_within_frac / max(0.01, 1 - nat_within_frac))
        target_within = min(target_within, len(within))
        if target_within < len(within):
            _rng.seed(42 + hash(dataset_id))
            within = _rng.sample(within, target_within)

        ai_raw = cross_adj + within
    else:
        ai_raw = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))
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

    # Extended controlled set for coin-flip row: includes all-expert-tie pairs.
    # Every paper has ≥4 reviews from dataset-level reviewers, so ≥2 is always satisfied.
    # We still build the rated map for the coin-flip loop (to know which experts rated each pair).
    expert_pair_rated = defaultdict(set)  # pair → set of experts who rated both papers
    for exp, ratings in experts_with_data.items():
        rated_ids = list(ratings.keys())
        for i in range(len(rated_ids)):
            for j in range(i + 1, len(rated_ids)):
                pair = tuple(sorted([rated_ids[i], rated_ids[j]]))
                expert_pair_rated[pair].add(exp)
    controlled_pairs_cf = set(expert_pair_rated.keys()) & set(ai_pair.keys())

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
    # Build human BT from committee (majority) matches — CONTROLLED PAIRS ONLY.
    # For fair AI-vs-human comparison, both must use the same pair set.
    human_committee_matches = []
    for pair in controlled_pairs:
        if pair in expert_majority:
            human_committee_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": expert_majority[pair],
                "completed": True, "failed": False,
            })
    # Human BT from individual expert votes — CONTROLLED PAIRS ONLY
    human_individual_matches = []
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            human_individual_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": winner,
                "completed": True, "failed": False,
            })
    # AI BT from ALL thinking-mode matches (includes controlled pairs and any extras)
    all_ai_bt_matches = [
        {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
         "winner_id": m["winner_id"], "completed": True, "failed": False}
        for m in ai_raw if m.get("winner_id")
    ]
    all_bt_paper_ids = set()
    for m in ai_raw:
        all_bt_paper_ids.add(m["paper1_id"])
        all_bt_paper_ids.add(m["paper2_id"])
    all_bt_papers = [papers_by_id[pid] for pid in all_bt_paper_ids if pid in papers_by_id]

    ctrl_paper_ids = set()
    for p in controlled_pairs:
        ctrl_paper_ids.add(p[0])
        ctrl_paper_ids.add(p[1])

    async def _bt_correlate(h_matches, a_matches):
        """Compute Spearman rho and Kendall tau between human and AI BT rankings."""
        if len(h_matches) < 10 or len(a_matches) < 10:
            return None, None
        h_lb = await compute_leaderboard(all_bt_papers, h_matches)
        a_lb = await compute_leaderboard(all_bt_papers, a_matches)
        h_rank = {e["id"]: e["score"] for e in h_lb}
        a_rank = {e["id"]: e["score"] for e in a_lb}
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

    bt_comm_rho, bt_comm_tau = await _bt_correlate(human_committee_matches, all_ai_bt_matches)
    bt_indiv_rho, bt_indiv_tau = await _bt_correlate(human_individual_matches, all_ai_bt_matches)

    # Direct ranking: AI BT (all matches) vs h1_avg_rating
    bt_vs_avg_rho = None
    if len(all_ai_bt_matches) >= 10:
        ai_bt_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, all_ai_bt_matches)}
        avg_rating_map = {}
        for pid in all_bt_paper_ids:
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
                                           [avg_rating_map[p] for p in shared])
            if not np.isnan(sp):
                bt_vs_avg_rho = float(sp)

    # Build tier score map for all papers (used by both AI and per-expert tier correlation)
    tier_score_map = {}
    for pid in all_bt_paper_ids:
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
            ai_bt_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, all_ai_bt_matches)}
        shared = sorted(set(ai_bt_rank.keys()) & set(tier_score_map.keys()))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([ai_bt_rank[p] for p in shared],
                                           [tier_score_map[p] for p in shared])
            kt, _ = scipy_stats.kendalltau([ai_bt_rank[p] for p in shared],
                                            [tier_score_map[p] for p in shared])
            if not np.isnan(sp):
                bt_vs_tier_rho = float(sp)
            if not np.isnan(kt):
                bt_vs_tier_tau = float(kt)

    # Internal human baselines: individual vs committee, per-expert correlations
    bt_indiv_vs_comm_rho, bt_indiv_vs_comm_tau = await _bt_correlate(human_individual_matches, human_committee_matches)

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
        comm_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, human_committee_matches)}
    ai_rank = {}
    if len(all_ai_bt_matches) >= 10:
        ai_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, all_ai_bt_matches)}
    indiv_rank = {}
    if len(human_individual_matches) >= 10:
        indiv_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, human_individual_matches)}

    for exp in experts_with_data:
        # Expert's own BT: from controlled pairs where they had a preference
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
        exp_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, exp_matches)}

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
            loo_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, loo_matches)}
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
            loo_indiv_rank = {e["id"]: e["score"] for e in await compute_leaderboard(all_bt_papers, loo_indiv_matches)}
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
                                           [loo_avg[p] for p in shared_avg])
            kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in shared_avg],
                                            [loo_avg[p] for p in shared_avg])
            if not np.isnan(sp):
                expert_vs_loo_avg_rhos.append(float(sp))
            if not np.isnan(kt):
                expert_vs_loo_avg_taus.append(float(kt))

        # Expert BT vs ICLR tier decisions
        if tier_score_map:
            tier_shared = sorted(set(exp_rank.keys()) & set(tier_score_map.keys()))
            if len(tier_shared) >= 5:
                sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in tier_shared],
                                               [tier_score_map[p] for p in tier_shared])
                kt, _ = scipy_stats.kendalltau([exp_rank[p] for p in tier_shared],
                                                [tier_score_map[p] for p in tier_shared])
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

    # --- Layer 7: Coin-flip extended stats (uses controlled_pairs_cf including all-expert-tie pairs) ---
    cf_hh_agree = cf_hh_total = 0.0
    cf_ah_agree = cf_ah_total = 0.0
    cf_ac_agree = cf_ac_total = 0.0   # AI vs expert majority
    cf_hc_agree = cf_hc_total = 0.0   # Human vs expert majority
    cf_hc_loo_agree = cf_hc_loo_total = 0.0
    cf_tier_ai_agree = cf_tier_ai_total = 0.0  # AI vs committee tier
    cf_tier_hh_agree = cf_tier_hh_total = 0.0  # Human vs committee tier
    cf_tier_same_count = 0  # Count of actual same-tier (committee tie) pairs

    for pair in controlled_pairs_cf:
        prefs = expert_pair_prefs.get(pair, {})  # may be empty for all-tie pairs
        a, b = pair

        # All experts who rated both papers (with or without preference)
        experts_for_pair = []
        for exp in expert_pair_rated.get(pair, set()):
            ratings = experts_with_data[exp]
            has_pref = ratings[a] != ratings[b]
            experts_for_pair.append((exp, has_pref))

        # AI vs Human (cf): preference → check agreement, tie → 0.5
        for exp, has_pref in experts_for_pair:
            cf_ah_total += 1
            if has_pref:
                winner = prefs.get(exp)
                if winner and ai_pair[pair] == winner:
                    cf_ah_agree += 1
            else:
                cf_ah_agree += 0.5

        # Human vs Human (cf): each expert pair
        for i in range(len(experts_for_pair)):
            for j in range(i + 1, len(experts_for_pair)):
                exp1, pref1 = experts_for_pair[i]
                exp2, pref2 = experts_for_pair[j]
                cf_hh_total += 1
                if pref1 and pref2:
                    w1 = prefs.get(exp1)
                    w2 = prefs.get(exp2)
                    if w1 and w2 and w1 == w2:
                        cf_hh_agree += 1
                else:
                    cf_hh_agree += 0.5  # at least one ties → coin flip

        # AI vs Majority (cf)
        cf_ac_total += 1
        if pair in expert_majority:
            if ai_pair[pair] == expert_majority[pair]:
                cf_ac_agree += 1
        else:
            cf_ac_agree += 0.5  # no majority (all tie or split) → coin flip

        # Human vs Majority (cf) — individual expert vs majority
        if pair in expert_majority:
            for exp, has_pref in experts_for_pair:
                cf_hc_total += 1
                if has_pref:
                    if prefs.get(exp) == expert_majority[pair]:
                        cf_hc_agree += 1
                else:
                    cf_hc_agree += 0.5
        else:
            for exp, has_pref in experts_for_pair:
                cf_hc_total += 1
                cf_hc_agree += 0.5

        # Human vs Majority LOO (cf)
        for exp_name, has_pref in experts_for_pair:
            others = {e: prefs[e] for e in prefs if e != exp_name}
            if len(others) >= 2:
                c = Counter(others.values())
                best, n = c.most_common(1)[0]
                if n > len(others) / 2:
                    cf_hc_loo_total += 1
                    if has_pref:
                        if prefs.get(exp_name) == best:
                            cf_hc_loo_agree += 1
                    else:
                        cf_hc_loo_agree += 0.5
                else:
                    # Split among non-tying experts, no clear LOO majority → coin flip
                    cf_hc_loo_total += 1
                    cf_hc_loo_agree += 0.5
            else:
                # Fewer than 2 others with preferences
                other_rated = [e for e, _ in experts_for_pair if e != exp_name]
                if len(other_rated) >= 2:
                    cf_hc_loo_total += 1
                    cf_hc_loo_agree += 0.5

        # AI vs Committee tier (cf) — includes same-tier as coin flip only when within-tier is included
        pa = papers_by_id.get(a, {})
        pb = papers_by_id.get(b, {})
        ta = norm_tier(pa.get("decision"))
        tb = norm_tier(pb.get("decision"))
        if ta is not None and tb is not None:
            sa = TIER_SCORE.get(ta, -1)
            sb = TIER_SCORE.get(tb, -1)
            if sa != sb:
                cf_tier_ai_total += 1
                tier_winner = a if sa > sb else b
                if ai_pair[pair] == tier_winner:
                    cf_tier_ai_agree += 1
                for exp, has_pref in experts_for_pair:
                    cf_tier_hh_total += 1
                    if has_pref:
                        if prefs.get(exp) == tier_winner:
                            cf_tier_hh_agree += 1
                    else:
                        cf_tier_hh_agree += 0.5
            elif include_within_tier:
                # Same tier → committee tie → coin flip (only when within-tier page)
                cf_tier_same_count += 1
                cf_tier_ai_total += 1
                cf_tier_ai_agree += 0.5
                for exp, has_pref in experts_for_pair:
                    cf_tier_hh_total += 1
                    cf_tier_hh_agree += 0.5

    def _cf_rate_ext(agree, total):
        """Coin-flip rate from the extended controlled set."""
        if total == 0:
            return None
        return round(agree / total * 100, 1)


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
        "controlled_pairs_cf": len(controlled_pairs_cf),
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
            "cf_ai_rate": _cf_rate_ext(cf_tier_ai_agree, cf_tier_ai_total),
            "cf_hh_rate": _cf_rate_ext(cf_tier_hh_agree, cf_tier_hh_total),
            "cf_ai_total": int(cf_tier_ai_total),
            "cf_hh_total": int(cf_tier_hh_total),
            "tier_same_count": cf_tier_same_count,
        },
        "n_rater_pairs": n_pairs,
        "ceiling": ceiling,
        "pairwise": {
            "human_human": {"agree": hh_agree, "total": hh_total, "rate": _rate(hh_agree, hh_total),
                            "kappa": safe_round(hh_kappa), "ci": _wilson_ci(hh_agree, hh_total),
                            "cf_rate": _cf_rate_ext(cf_hh_agree, cf_hh_total),
                            "cf_total": int(cf_hh_total)},
            "human_committee": {"agree": hc_agree, "total": hc_total, "rate": _rate(hc_agree, hc_total),
                                "kappa": safe_round(hc_kappa), "ci": _wilson_ci(hc_agree, hc_total),
                                "cf_rate": _cf_rate_ext(cf_hc_agree, cf_hc_total),
                                "cf_total": int(cf_hc_total)},
            "human_committee_loo": {"agree": hc_loo_agree, "total": hc_loo_total, "rate": _rate(hc_loo_agree, hc_loo_total),
                                    "kappa": safe_round(hc_loo_kappa), "ci": _wilson_ci(hc_loo_agree, hc_loo_total),
                                    "cf_rate": _cf_rate_ext(cf_hc_loo_agree, cf_hc_loo_total),
                                    "cf_total": int(cf_hc_loo_total)},
            "ai_human": {"agree": ah_agree, "total": ah_total, "rate": _rate(ah_agree, ah_total),
                         "kappa": safe_round(ah_kappa), "ci": _wilson_ci(ah_agree, ah_total),
                         "cf_rate": _cf_rate_ext(cf_ah_agree, cf_ah_total),
                         "cf_total": int(cf_ah_total)},
            "ai_committee": {"agree": ac_agree, "total": ac_total, "rate": _rate(ac_agree, ac_total),
                             "kappa": safe_round(ac_kappa), "ci": _wilson_ci(ac_agree, ac_total),
                             "cf_rate": _cf_rate_ext(cf_ac_agree, cf_ac_total),
                             "cf_total": int(cf_ac_total)},
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


@router.get("/human-ai-benchmark-unfiltered")
async def human_ai_benchmark_unfiltered(gt_type: str = Query("comp")):
    """Human vs AI benchmark including within-tier matches — served from precomputed cache."""
    cache = _benchmark_unfiltered_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    return {"status": "no_data", "message": "Unfiltered benchmark not precomputed."}


async def _compute_benchmark(gt_type: str = "comp", include_within_tier: bool = False):
    """Compute the full benchmark across datasets filtered by GT type.
    gt_type='comp': comparative GT (ICLR, PeerRead, eLife Neuro)
    gt_type='stan': standalone GT (eLife bio, MIDL, Qeios, ResearchHub)
    include_within_tier: if True, includes experiment-tagged within-tier matches
    """
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS

    # Discover datasets with evaluations, filtered by GT type
    ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
    all_ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)
                  if r["_id"] in allowed]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(1000)
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
    tasks = [_compute_dataset_benchmark(ds_id, require_si=require_si, include_within_tier=include_within_tier) for ds_id in all_ds_ids]
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
        pooled.setdefault("total_pairs_cf", 0)
        pooled["total_pairs_cf"] += result.get("controlled_pairs_cf", result["controlled_pairs"])
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
        # Aggregate cf tier stats
        pooled.setdefault("tier_cf_ai_agree", 0.0)
        pooled.setdefault("tier_cf_ai_total", 0)
        pooled.setdefault("tier_cf_hh_agree", 0.0)
        pooled.setdefault("tier_cf_hh_total", 0)
        if ta.get("cf_ai_rate") is not None and ta.get("cf_ai_total", 0) > 0:
            pooled["tier_cf_ai_agree"] += ta["cf_ai_rate"] * ta["cf_ai_total"] / 100.0
            pooled["tier_cf_ai_total"] += ta["cf_ai_total"]
        if ta.get("cf_hh_rate") is not None and ta.get("cf_hh_total", 0) > 0:
            pooled["tier_cf_hh_agree"] += ta["cf_hh_rate"] * ta["cf_hh_total"] / 100.0
            pooled["tier_cf_hh_total"] += ta["cf_hh_total"]
        pooled.setdefault("tier_same_count", 0)
        pooled["tier_same_count"] += ta.get("tier_same_count", 0)

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

    # Pooled tie impact analysis — compute coin-flip rates from per-dataset extended cf stats
    hh_a, hh_t = pooled["hh"][0], pooled["hh"][1]
    ah_a, ah_t = pooled["ah"][0], pooled["ah"][1]
    hc_loo_t = pooled["hc_loo"][1]
    hh_t1, hh_t2 = pooled["ti_hh_tie_one"], pooled["ti_hh_tie_both"]
    ah_tie = pooled["ti_ah_tie"]
    hc_tie = pooled["ti_hc_tie"]
    hc_loo_tie = pooled["ti_hc_loo_tie"]

    # Aggregate cf stats from per-dataset results (proper extended coin-flip)
    pooled_cf = {"hh": [0.0, 0.0], "ah": [0.0, 0.0], "ac": [0.0, 0.0],
                 "hc": [0.0, 0.0], "hc_loo": [0.0, 0.0],
                 "tier_ai": [0.0, 0.0], "tier_hh": [0.0, 0.0]}
    for result in per_dataset:
        pw = result.get("pairwise", {})
        for key, pool_key in [("human_human", "hh"), ("human_committee", "hc"),
                               ("human_committee_loo", "hc_loo"),
                               ("ai_human", "ah"), ("ai_committee", "ac")]:
            cf_total = pw[key].get("cf_total", 0)
            cf_rate_val = pw[key].get("cf_rate")
            if cf_rate_val is not None and cf_total > 0:
                pooled_cf[pool_key][0] += cf_rate_val * cf_total / 100.0
                pooled_cf[pool_key][1] += cf_total
        ta = result.get("tier_accuracy", {})
        for src, dst in [("cf_ai_total", "tier_ai"), ("cf_hh_total", "tier_hh")]:
            t = ta.get(src, 0)
            r = ta.get(src.replace("total", "rate"))
            if r is not None and t > 0:
                pooled_cf[dst][0] += r * t / 100.0
                pooled_cf[dst][1] += t

    def _pooled_cf_rate(key):
        a, t = pooled_cf[key]
        return round(a / max(t, 1) * 100, 1) if t > 0 else None

    ah_total_cf = ah_t + ah_tie

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
            "human_human": _pooled_cf_rate("hh"),
            "human_committee": _pooled_cf_rate("hc"),
            "human_committee_loo": _pooled_cf_rate("hc_loo"),
            "ai_human": _pooled_cf_rate("ah"),
            "ai_committee": _pooled_cf_rate("ac"),
            "ai_human_kappa": ah_cf_kappa,
            "total_pairs": pooled.get("total_pairs_cf", pooled["total_pairs"]),
        },
        "excluded": {
            "hh_rate": _rate(hh_a, hh_t),
            "ah_rate": _rate(ah_a, ah_t),
        },
        "tie_rates": {
            "hh": _tie_pct(hh_t1 + hh_t2, hh_t),
            "ah": _tie_pct(ah_tie, ah_t),
            "hc_loo": _tie_pct(hc_loo_tie, hc_loo_t),
            "ac": round((pooled_cf["ac"][1] - pooled["ac"][1]) / max(pooled_cf["ac"][1], 1) * 100, 1) if pooled_cf["ac"][1] > 0 else None,
            "hc": round((pooled_cf["hc"][1] - pooled["hc"][1]) / max(pooled_cf["hc"][1], 1) * 100, 1) if pooled_cf["hc"][1] > 0 else None,
            "tier_ai": round((pooled.get("tier_cf_ai_total", 0) - pooled.get("tier_ai_total", 0)) / max(pooled.get("tier_cf_ai_total", 1), 1) * 100, 1) if pooled.get("tier_cf_ai_total", 0) > 0 else None,
            "tier_hh": round((pooled.get("tier_cf_hh_total", 0) - pooled.get("tier_hh_total", 0)) / max(pooled.get("tier_cf_hh_total", 1), 1) * 100, 1) if pooled.get("tier_cf_hh_total", 0) > 0 else None,
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
        "total_controlled_pairs_cf": pooled.get("total_pairs_cf", pooled["total_pairs"]),
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
                "cf_ai_rate": _rate(pooled.get("tier_cf_ai_agree", 0), pooled.get("tier_cf_ai_total", 0)) if pooled.get("tier_cf_ai_total", 0) > 0 else None,
                "cf_ai_total": pooled.get("tier_cf_ai_total", 0),
                "cf_hh_rate": _rate(pooled.get("tier_cf_hh_agree", 0), pooled.get("tier_cf_hh_total", 0)) if pooled.get("tier_cf_hh_total", 0) > 0 else None,
                "cf_hh_total": pooled.get("tier_cf_hh_total", 0),
                "tier_same_count": pooled.get("tier_same_count", 0),
            },
        },
        "per_dataset": per_dataset,
    }

    return summary



@router.get("/dataset-rankings/{dataset_id}")
async def dataset_rankings(dataset_id: str):
    """Return per-paper BT rankings under different aggregation methods for a dataset."""
    import math
    from collections import defaultdict, Counter

    papers = await collect_all(db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "evaluations": 1, "decision": 1, "h1_avg_rating": 1},
    ))
    if not papers:
        return {"status": "no_data"}

    papers_by_id = {p["id"]: p for p in papers}

    # Detect thinking mode
    sample = await db.validation_papers.find_one(
        {"dataset_id": dataset_id, "ai_impact_summary_thinking": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1},
    )
    ai_content_mode = "abstract_plus_summary:thinking" if sample else "abstract_plus_summary"
    mode_count = await db.validation_matches.count_documents(
        {"dataset_id": dataset_id, "completed": True, "content_mode": ai_content_mode})
    if mode_count == 0:
        ai_content_mode = "abstract_plus_summary"

    ai_raw = await collect_all(db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": ai_content_mode},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))

    if len(ai_raw) < 10:
        return {"status": "no_data", "message": "Too few AI matches"}

    # Expert ratings & pairwise preferences
    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name and ev.get("rating_value") is not None:
                expert_ratings[name][p["id"]] = ev["rating_value"]

    experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}

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

    expert_majority = {}
    for pair, votes in expert_pair_prefs.items():
        if len(votes) < 2:
            continue
        ct = Counter(votes.values())
        best, n = ct.most_common(1)[0]
        if n > len(votes) / 2:
            expert_majority[pair] = best

    # AI pair majority
    ai_pair_votes = defaultdict(list)
    for m in ai_raw:
        if m.get("winner_id"):
            ai_pair_votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
    ai_pair = {}
    for pair, votes in ai_pair_votes.items():
        ct = Counter(votes)
        ai_pair[pair] = ct.most_common(1)[0][0]

    controlled_pairs = {p for p in (set(ai_pair.keys()) & set(expert_pair_prefs.keys()))
                        if len(expert_pair_prefs[p]) >= 2}

    # Build match sets
    # 1. AI: all thinking matches
    ai_bt_matches = [
        {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
         "winner_id": m["winner_id"], "completed": True, "failed": False}
        for m in ai_raw if m.get("winner_id")
    ]

    # 2. Human Individual: each expert vote on controlled pairs
    human_indiv_matches = []
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            human_indiv_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": winner, "completed": True, "failed": False,
            })

    # 3. Human Majority: one vote per controlled pair
    human_maj_matches = []
    for pair in controlled_pairs:
        if pair in expert_majority:
            human_maj_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": expert_majority[pair], "completed": True, "failed": False,
            })

    # Compute Elo scores
    SCORE_BASE = 1200
    paper_ids = [p["id"] for p in papers]

    def _compute_elo(matches_list):
        """Compute BT scores normalized to Elo range for a set of matches."""
        from services.ranking import calculate_bradley_terry, _bt_to_score
        bt_matches = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                        "winner_id": m["winner_id"], "completed": True, "failed": False}
                       for m in matches_list if m.get("winner_id")]
        bt_raw = calculate_bradley_terry(bt_matches, paper_ids)
        elo_map = _bt_to_score(bt_raw, SCORE_BASE)
        
        # Also compute win/loss stats
        w_stats = {pid: {"w": 0, "l": 0} for pid in paper_ids}
        for m in matches_list:
            w = m.get("winner_id")
            if not w: continue
            p1, p2 = m["paper1_id"], m["paper2_id"]
            loser = p2 if w == p1 else p1
            if w in w_stats: w_stats[w]["w"] += 1
            if loser in w_stats: w_stats[loser]["l"] += 1
        
        scores = {}
        for pid in paper_ids:
            s = w_stats[pid]
            n = s["w"] + s["l"]
            scores[pid] = {"score": elo_map.get(pid, SCORE_BASE), "wins": s["w"], "losses": s["l"], "matches": n}
        return scores

    ai_elo = _compute_elo(ai_bt_matches)
    h_indiv_elo = _compute_elo(human_indiv_matches)
    h_maj_elo = _compute_elo(human_maj_matches)

    # Tier score map
    TIER_SCORE = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}
    def _norm_tier(d):
        if not d:
            return None
        dl = d.lower().strip()
        for t in TIER_SCORE:
            if t in dl:
                return t
        return None

    # Build result rows sorted by AI score descending
    import hashlib
    def _title_hash(pid):
        return hashlib.md5(papers_by_id.get(pid, {}).get("title", pid).encode()).hexdigest()

    ranked_ids = sorted(paper_ids, key=lambda pid: (ai_elo[pid]["score"], _title_hash(pid)), reverse=True)

    rows = []
    for ai_rank, pid in enumerate(ranked_ids, 1):
        p = papers_by_id[pid]
        dec = p.get("decision", "")
        tier = _norm_tier(dec)
        h1_avg = p.get("h1_avg_rating")
        if h1_avg is None:
            evals = p.get("evaluations", [])
            vals = [e["rating_value"] for e in evals if e.get("rating_value")]
            h1_avg = round(sum(vals) / len(vals), 2) if vals else None

        rows.append({
            "title": p["title"],
            "decision": dec or None,
            "tier": tier,
            "h1_avg_rating": h1_avg,
            "ai_rank": ai_rank,
            "ai_bt": ai_elo[pid]["score"],
            "ai_wl": f"{ai_elo[pid]['wins']}/{ai_elo[pid]['losses']}",
            "h_indiv_bt": h_indiv_elo[pid]["score"],
            "h_indiv_wl": f"{h_indiv_elo[pid]['wins']}/{h_indiv_elo[pid]['losses']}",
            "h_maj_bt": h_maj_elo[pid]["score"],
            "h_maj_wl": f"{h_maj_elo[pid]['wins']}/{h_maj_elo[pid]['losses']}",
        })

    # Add ranks for human methods
    h_indiv_sorted = sorted(rows, key=lambda r: (-r["h_indiv_bt"], r["title"]))
    for i, r in enumerate(h_indiv_sorted):
        r["h_indiv_rank"] = i + 1
    h_maj_sorted = sorted(rows, key=lambda r: (-r["h_maj_bt"], r["title"]))
    for i, r in enumerate(h_maj_sorted):
        r["h_maj_rank"] = i + 1

    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "n_papers": len(papers),
        "n_controlled_pairs": len(controlled_pairs),
        "n_ai_matches": len(ai_bt_matches),
        "ai_content_mode": ai_content_mode,
        "papers": rows,
    }


_ranking_quality_cache = {"comp": {"data": None}, "stan": {"data": None}}
_ranking_quality_unfiltered_cache = {"comp": {"data": None}, "stan": {"data": None}}


@router.get("/ai-ranking-quality")
async def ai_ranking_quality(gt_type: str = Query("comp")):
    """Standalone AI ranking quality — served from precomputed cache."""
    cache = _ranking_quality_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    return {"status": "no_data", "message": "AI ranking quality not precomputed. Run admin precompute-experiments."}


@router.get("/ai-ranking-quality-unfiltered")
async def ai_ranking_quality_unfiltered(gt_type: str = Query("comp")):
    """AI ranking quality including within-tier matches — served from precomputed cache."""
    cache = _ranking_quality_unfiltered_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    return {"status": "no_data", "message": "Unfiltered AI ranking quality not precomputed."}


_gap_analysis_cache = {"comp": {"data": None}}


@router.get("/ai-ranking-gap-analysis")
async def ai_ranking_gap_analysis(gt_type: str = Query("comp")):
    """AI ranking quality at different SI-score gap thresholds — served from precomputed cache."""
    cache = _gap_analysis_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    return {"status": "no_data", "message": "Gap analysis not precomputed."}


async def _compute_gap_analysis(gt_type: str = "comp"):
    """Compute AI ranking quality at multiple SI-gap thresholds.
    Shows how correlation changes when AI matches are filtered by the
    predicted quality gap (SI score difference) between papers."""
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS
    TIER_MAP = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}

    ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
    all_ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)
                  if r["_id"] in allowed]

    # Load all data per dataset
    ds_data = {}
    for ds_id in all_ds_ids:
        papers = await collect_all(db.validation_papers.find(
            {"dataset_id": ds_id}, PAPER_LIGHT_PROJECTION))
        if not papers:
            continue
        papers_by_id = {p["id"]: p for p in papers}

        si_scores = {}
        for p in papers:
            si = p.get("single_item_score") or p.get("single_item_scores", {}).get("overall")
            if si is not None:
                si_scores[p["id"]] = si
        if len(si_scores) < 10:
            continue

        expert_ratings = build_expert_ratings(papers)
        experts_map = {e: r for e, r in expert_ratings.items() if len(r) >= 3}

        expert_pair_prefs = defaultdict(dict)
        for exp, ratings in experts_map.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    if ratings[a] == ratings[b]:
                        continue
                    pair = tuple(sorted([a, b]))
                    expert_pair_prefs[pair][exp] = a if ratings[a] > ratings[b] else b

        expert_majority = {}
        for pair, votes in expert_pair_prefs.items():
            if len(votes) < 2:
                continue
            c = Counter(votes.values())
            best, n = c.most_common(1)[0]
            if n > len(votes) / 2:
                expert_majority[pair] = best

        all_expert_ge2 = {p for p, v in expert_pair_prefs.items() if len(v) >= 2}

        # Load all thinking matches (base + experiment)
        base = await collect_all(db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True},
             "content_mode": "abstract_plus_summary:thinking", "winner_id": {"$ne": None},
             "experiment_tag": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}))
        exp_matches = await collect_all(db.validation_matches.find(
            {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True},
             "content_mode": "abstract_plus_summary:thinking", "winner_id": {"$ne": None},
             "experiment_tag": {"$exists": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}))

        # Apply natural-proportion subsampling (same as summary cards)
        import random as _rng
        def _is_within_gap(m):
            t1 = norm_tier(papers_by_id.get(m["paper1_id"], {}).get("decision"))
            t2 = norm_tier(papers_by_id.get(m["paper2_id"], {}).get("decision"))
            return t1 is not None and t2 is not None and TIER_MAP.get(t1, -1) == TIER_MAP.get(t2, -2)

        # Combine base + all experiment matches, then ensure natural within-tier proportion
        all_gap_combined = base + exp_matches
        cross_adj_gap = sorted([m for m in all_gap_combined if not _is_within_gap(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))
        within_gap = sorted([m for m in all_gap_combined if _is_within_gap(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))

        all_pids = list(papers_by_id.keys())
        nat_ca, nat_w = 0, 0
        for i in range(len(all_pids)):
            for j in range(i + 1, len(all_pids)):
                t1 = norm_tier(papers_by_id[all_pids[i]].get("decision"))
                t2 = norm_tier(papers_by_id[all_pids[j]].get("decision"))
                if t1 and t2:
                    if TIER_MAP.get(t1) == TIER_MAP.get(t2):
                        nat_w += 1
                    else:
                        nat_ca += 1
        nat_frac = nat_w / (nat_ca + nat_w) if (nat_ca + nat_w) > 0 else 0.3
        target_w = int(len(cross_adj_gap) * nat_frac / max(0.01, 1 - nat_frac))
        target_w = min(target_w, len(within_gap))
        if target_w < len(within_gap):
            _rng.seed(42 + hash(ds_id))
            within_gap = _rng.sample(within_gap, target_w)

        all_matches = cross_adj_gap + within_gap
        for m in all_matches:
            s1, s2 = si_scores.get(m["paper1_id"]), si_scores.get(m["paper2_id"])
            m["_si_gap"] = abs(s1 - s2) if s1 is not None and s2 is not None else None

        # Compute BT scores from all matches, then annotate each match with BT gap
        from services.ranking import compute_leaderboard as _sync_lb
        bt_lb = _sync_lb(papers, [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                                    "winner_id": m["winner_id"], "completed": True, "failed": False}
                                   for m in all_matches if m.get("winner_id")])
        bt_scores = {e["id"]: e["score"] for e in bt_lb}
        for m in all_matches:
            b1, b2 = bt_scores.get(m["paper1_id"]), bt_scores.get(m["paper2_id"])
            m["_bt_gap"] = abs(b1 - b2) if b1 is not None and b2 is not None else None

        tier_rank = {p["id"]: -TIER_MAP[norm_tier(p.get("decision"))]
                     for p in papers if norm_tier(p.get("decision")) in TIER_MAP}
        avg_map = {}
        for p in papers:
            r = p.get("h1_avg_rating")
            if r is None:
                evals = p.get("evaluations", [])
                vals = [e["rating_value"] for e in evals if e.get("rating_value")]
                r = sum(vals) / len(vals) if vals else None
            if r is not None:
                avg_map[p["id"]] = r

        ds_data[ds_id] = {
            "papers": papers, "papers_by_id": papers_by_id, "experts_map": experts_map,
            "expert_pair_prefs": expert_pair_prefs, "expert_majority": expert_majority,
            "all_expert_ge2": all_expert_ge2, "all_matches": all_matches,
            "tier_rank": tier_rank, "avg_map": avg_map,
        }

    # Helper: compute metrics for a filtered match subset
    async def _compute_row(ds_data_items, match_filter_fn, controlled):
        rhos = {"indiv": [], "maj": [], "tier": [], "avg": [], "h_ceil": []}
        total_matches = 0
        total_pairs = 0

        for ds_id, c in ds_data_items:
            papers = c["papers"]
            filtered = [m for m in c["all_matches"] if match_filter_fn(m)]
            if len(filtered) < 10:
                continue
            total_matches += len(filtered)

            pv = defaultdict(list)
            for m in filtered:
                pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
                pv[pair].append(m["winner_id"])
            ai_pair = {pair: Counter(v).most_common(1)[0][0] for pair, v in pv.items()}

            if controlled:
                ctrl = set(ai_pair.keys()) & c["all_expert_ge2"]
                total_pairs += len(ctrl)
                if len(ctrl) < 10:
                    continue
                ai_bt = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": ai_pair[p],
                          "completed": True, "failed": False} for p in ctrl]
                h_indiv = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": w,
                            "completed": True, "failed": False}
                           for p in ctrl for _, w in c["expert_pair_prefs"][p].items()]
                h_maj = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": c["expert_majority"][p],
                          "completed": True, "failed": False}
                         for p in ctrl if p in c["expert_majority"]]
                ceiling_pairs = ctrl
            else:
                total_pairs += len(ai_pair)
                ai_bt = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                          "winner_id": m["winner_id"], "completed": True, "failed": False}
                         for m in filtered]
                h_indiv = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": w,
                            "completed": True, "failed": False}
                           for p in c["all_expert_ge2"] for _, w in c["expert_pair_prefs"][p].items()]
                h_maj = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": c["expert_majority"][p],
                          "completed": True, "failed": False}
                         for p in c["all_expert_ge2"] if p in c["expert_majority"]]
                ceiling_pairs = c["all_expert_ge2"]

            ai_rank = {e["id"]: e["score"] for e in await compute_leaderboard(papers, ai_bt)}

            def _rho(a, b):
                s = sorted(set(a) & set(b))
                if len(s) < 5:
                    return None
                sp, _ = scipy_stats.spearmanr([a[p] for p in s], [b[p] for p in s])
                return safe_round(float(sp)) if not np.isnan(sp) else None

            r = _rho(ai_rank, {e["id"]: e["score"] for e in await compute_leaderboard(papers, h_indiv)})
            if r is not None:
                rhos["indiv"].append(r)
            r = _rho(ai_rank, {e["id"]: e["score"] for e in await compute_leaderboard(papers, h_maj)})
            if r is not None:
                rhos["maj"].append(r)
            s = sorted(set(ai_rank) & set(c["tier_rank"]))
            if len(s) >= 5:
                sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in s], [c["tier_rank"][p] for p in s])
                if not np.isnan(sp):
                    rhos["tier"].append(safe_round(abs(float(sp))))
            s = sorted(set(ai_rank) & set(c["avg_map"]))
            if len(s) >= 5:
                sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in s], [c["avg_map"][p] for p in s])
                if not np.isnan(sp):
                    rhos["avg"].append(safe_round(float(sp)))

            for exp in c["experts_map"]:
                em = [{"paper1_id": p[0], "paper2_id": p[1],
                       "winner_id": c["expert_pair_prefs"][p][exp],
                       "completed": True, "failed": False}
                      for p in ceiling_pairs if exp in c["expert_pair_prefs"].get(p, {})]
                if len(em) < 10:
                    continue
                er = {e["id"]: e["score"] for e in await compute_leaderboard(papers, em)}
                lm = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": w,
                       "completed": True, "failed": False}
                      for p in ceiling_pairs for e2, w in c["expert_pair_prefs"][p].items() if e2 != exp]
                if len(lm) < 10:
                    continue
                lr = {e["id"]: e["score"] for e in await compute_leaderboard(papers, lm)}
                r = _rho(er, lr)
                if r is not None:
                    rhos["h_ceil"].append(r)

        row = {"matches": total_matches, "pairs": total_pairs}
        for key in ["indiv", "maj", "tier", "avg", "h_ceil"]:
            vals = rhos[key]
            row[key] = safe_round(float(np.mean(vals))) if vals else None
        row["ai_advantage"] = safe_round(row["indiv"] - row["h_ceil"]) if row["indiv"] and row["h_ceil"] else None
        return row

    ds_items = list(ds_data.items())
    gap_thresholds = [0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0]

    # Table 1: Non-controlled (AI filtered, human GT fixed)
    # For gap=0, use _compute_ranking_quality directly (single code path, no duplication)
    rq = await _compute_ranking_quality(gt_type, include_within_tier=True)
    rq_pb = rq["pooled_bt"] if rq and rq.get("status") == "ok" else {}
    gap0_row = {
        "min_gap": 0,
        "matches": sum(len(c["all_matches"]) for c in ds_data.values()),
        "pairs": sum(len({tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in c["all_matches"]}) for c in ds_data.values()),
        "indiv": rq_pb.get("indiv", {}).get("spearman_rho"),
        "maj": rq_pb.get("maj", {}).get("spearman_rho"),
        "tier": rq_pb.get("tier", {}).get("spearman_rho"),
        "avg": rq_pb.get("avg_rating", {}).get("spearman_rho"),
        "h_ceil": None,
        "ai_advantage": None,
    }
    # Compute h_ceil from _compute_row for gap=0 (since ranking quality doesn't have it)
    gap0_full = await _compute_row(ds_items, lambda m: m.get("_si_gap") is not None and m["_si_gap"] >= 0, controlled=False)
    gap0_row["h_ceil"] = gap0_full.get("h_ceil")
    if gap0_row["indiv"] and gap0_row["h_ceil"]:
        gap0_row["ai_advantage"] = safe_round(gap0_row["indiv"] - gap0_row["h_ceil"])
    non_ctrl_rows = [gap0_row]

    for g in gap_thresholds[1:]:
        row = await _compute_row(ds_items, lambda m, g=g: m.get("_si_gap") is not None and m["_si_gap"] >= g, controlled=False)
        row["min_gap"] = g
        non_ctrl_rows.append(row)

    # Table 2: Controlled — wide gap (same pairs for AI & human)
    ctrl_wide_rows = []
    for g in gap_thresholds:
        row = await _compute_row(ds_items, lambda m, g=g: m.get("_si_gap") is not None and m["_si_gap"] >= g, controlled=True)
        row["min_gap"] = g
        ctrl_wide_rows.append(row)

    # Table 3: Controlled — close-cut oversampling (SI gap ≤ threshold)
    close_thresholds = [99, 3.0, 2.0, 1.5, 1.0, 0.5, 0.25]
    ctrl_close_rows = []
    for g in close_thresholds:
        row = await _compute_row(ds_items, lambda m, g=g: m.get("_si_gap") is not None and m["_si_gap"] <= g, controlled=True)
        row["max_gap"] = g
        ctrl_close_rows.append(row)

    # Table 4: BT Match Weighting — all matches, different weights by SI gap
    import math as _math

    async def _compute_weighted_row(ds_items, weight_fn, gap_field, label, is_uniform=False):
        """Compute ranking rho using proper per-match weighted BT (fractional wins/losses).
        No match duplication — weights are applied directly in the likelihood function."""
        from services.ranking import compute_weighted_bt
        rhos = {"indiv": [], "maj": [], "tier": [], "avg": [], "h_ceil": []}
        total_pairs = 0

        for ds_id, c in ds_items:
            papers = c["papers"]
            if is_uniform:
                all_m = c["all_matches"]
            else:
                all_m = [m for m in c["all_matches"] if m.get(gap_field) is not None]
            if len(all_m) < 10:
                continue

            paper_ids = [p["id"] for p in papers]
            total_pairs += len({tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in all_m})

            # Proper weighted BT: fractional wins/losses
            if is_uniform:
                ai_lb = await compute_leaderboard(papers, [
                    {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                     "winner_id": m["winner_id"], "completed": True, "failed": False}
                    for m in all_m if m.get("winner_id")])
                ai_rank = {e["id"]: e["score"] for e in ai_lb}
            else:
                ai_rank = compute_weighted_bt(all_m, paper_ids,
                                               weight_fn=lambda m: max(0.01, weight_fn(m[gap_field])))

            h_indiv = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": w,
                        "completed": True, "failed": False}
                       for p in c["all_expert_ge2"] for _, w in c["expert_pair_prefs"][p].items()]
            h_maj = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": c["expert_majority"][p],
                      "completed": True, "failed": False}
                     for p in c["all_expert_ge2"] if p in c["expert_majority"]]

            def _rho(a, b):
                s = sorted(set(a) & set(b))
                if len(s) < 5:
                    return None
                sp, _ = scipy_stats.spearmanr([a[p] for p in s], [b[p] for p in s])
                return safe_round(float(sp)) if not np.isnan(sp) else None

            r = _rho(ai_rank, {e["id"]: e["score"] for e in await compute_leaderboard(papers, h_indiv)})
            if r is not None:
                rhos["indiv"].append(r)
            r = _rho(ai_rank, {e["id"]: e["score"] for e in await compute_leaderboard(papers, h_maj)})
            if r is not None:
                rhos["maj"].append(r)
            s = sorted(set(ai_rank) & set(c["tier_rank"]))
            if len(s) >= 5:
                sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in s], [c["tier_rank"][p] for p in s])
                if not np.isnan(sp):
                    rhos["tier"].append(safe_round(abs(float(sp))))
            s = sorted(set(ai_rank) & set(c["avg_map"]))
            if len(s) >= 5:
                sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in s], [c["avg_map"][p] for p in s])
                if not np.isnan(sp):
                    rhos["avg"].append(safe_round(float(sp)))

            for exp in c["experts_map"]:
                em = [{"paper1_id": p[0], "paper2_id": p[1],
                       "winner_id": c["expert_pair_prefs"][p][exp],
                       "completed": True, "failed": False}
                      for p in c["all_expert_ge2"] if exp in c["expert_pair_prefs"].get(p, {})]
                if len(em) < 10:
                    continue
                er = {e["id"]: e["score"] for e in await compute_leaderboard(papers, em)}
                lm = [{"paper1_id": p[0], "paper2_id": p[1], "winner_id": w,
                       "completed": True, "failed": False}
                      for p in c["all_expert_ge2"] for e2, w in c["expert_pair_prefs"][p].items() if e2 != exp]
                if len(lm) < 10:
                    continue
                lr = {e["id"]: e["score"] for e in await compute_leaderboard(papers, lm)}
                r = _rho(er, lr)
                if r is not None:
                    rhos["h_ceil"].append(r)

        row = {"label": label, "pairs": total_pairs}
        for key in ["indiv", "maj", "tier", "avg", "h_ceil"]:
            vals = rhos[key]
            row[key] = safe_round(float(np.mean(vals))) if vals else None
        row["ai_advantage"] = safe_round(row["indiv"] - row["h_ceil"]) if row["indiv"] and row["h_ceil"] else None
        return row

    weight_schemes = [
        ("Uniform (baseline)", lambda g: 1, True),
        ("Close-cut 2x", lambda g: max(1, round(2 / (g + 0.5))), False),
        ("Close-cut 4x", lambda g: max(1, round(4 / (g + 0.5))), False),
        ("Close-cut 8x", lambda g: max(1, round(8 / (g + 0.5))), False),
        ("Wide-gap 2x", lambda g: max(1, round(1 + g)), False),
        ("Wide-gap 4x", lambda g: max(1, round(1 + g * 2)), False),
        ("Wide-gap only (gap>1)", lambda g: max(1, round(g)) if g > 1 else 1, False),
    ]

    weighted_rows = []
    # Uniform baseline: use gap=0 values from _compute_ranking_quality (single code path)
    uni_row = {"label": "Uniform (baseline)", "pairs": gap0_row["pairs"],
               "indiv": gap0_row["indiv"], "maj": gap0_row["maj"], "tier": gap0_row["tier"],
               "avg": gap0_row["avg"], "h_ceil": gap0_full.get("h_ceil"),
               "ai_advantage": gap0_row.get("ai_advantage")}
    weighted_rows.append(uni_row)
    for label, wfn, is_uni in weight_schemes:
        if is_uni:
            continue  # Already added above
        row = await _compute_weighted_row(ds_items, wfn, "_si_gap", label, is_uniform=False)
        weighted_rows.append(row)

    # Table 5: BT Gap Sampling (non-controlled) — like Table 1 but using BT score gap
    # BT gaps are in Elo points (typically 0-800), not 1-10 like SI
    bt_gap_thresholds = [0, 25, 50, 100, 200, 300, 500]
    bt_sampling_rows = []
    # Row 0: reuse ranking quality values (gap=0 = all matches)
    bt_gap0 = {"min_gap": 0, "matches": gap0_row["matches"], "pairs": gap0_row["pairs"],
               "indiv": gap0_row["indiv"], "maj": gap0_row["maj"], "tier": gap0_row["tier"],
               "avg": gap0_row["avg"], "h_ceil": gap0_full.get("h_ceil"), "ai_advantage": gap0_row.get("ai_advantage")}
    bt_sampling_rows.append(bt_gap0)
    for g in bt_gap_thresholds[1:]:
        row = await _compute_row(ds_items, lambda m, g=g: m.get("_bt_gap") is not None and m["_bt_gap"] >= g, controlled=False)
        row["min_gap"] = g
        bt_sampling_rows.append(row)

    # Table 6: BT Gap Weighting
    bt_weight_schemes = [
        ("Uniform (baseline)", lambda g: 1, True),
        ("Close-cut 2x (score)", lambda g: max(1, round(200 / (g + 50))), False),
        ("Close-cut 4x (score)", lambda g: max(1, round(400 / (g + 50))), False),
        ("Close-cut 8x (score)", lambda g: max(1, round(800 / (g + 50))), False),
        ("Wide-gap 2x (score)", lambda g: max(1, round(1 + g / 100)), False),
        ("Wide-gap 4x (score)", lambda g: max(1, round(1 + g / 50)), False),
    ]
    bt_weighted_rows = []
    bt_weighted_rows.append(dict(uni_row))  # Same uniform baseline
    for label, wfn, is_uni in bt_weight_schemes:
        if is_uni:
            continue
        row = await _compute_weighted_row(ds_items, wfn, "_bt_gap", label, is_uniform=False)
        bt_weighted_rows.append(row)

    return {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(ds_data),
        "non_controlled": non_ctrl_rows,
        "controlled_wide": ctrl_wide_rows,
        "controlled_close": ctrl_close_rows,
        "weighted": weighted_rows,
        "bt_sampling": bt_sampling_rows,
        "bt_weighted": bt_weighted_rows,
    }


async def _compute_ranking_quality(gt_type: str = "comp", include_within_tier: bool = False):
    """Compute standalone AI ranking quality: AI BT from all its matches vs human ground truth from all expert data.

    Unlike the controlled Human-vs-AI benchmark (same pairs), this uses each method's
    FULL available data independently — no intersection/filtering.
    """
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS

    ds_pipeline = [{"$group": {"_id": "$dataset_id"}}, {"$sort": {"_id": 1}}]
    all_ds_ids = [r["_id"] async for r in db.validation_papers.aggregate(ds_pipeline)
                  if r["_id"] in allowed]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(1000)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    per_dataset = []
    pooled_rhos = {"indiv": [], "maj": [], "tier": [], "avg_rating": []}
    pooled_top10 = {}
    pooled_overlap_table = {}

    for ds_id in all_ds_ids:
        result = await _compute_standalone_ranking(ds_id, include_within_tier=include_within_tier)
        if result is None:
            continue
        result["name"] = ds_names.get(ds_id, ds_id)
        per_dataset.append(result)

        for key in pooled_rhos:
            val = result.get("bt", {}).get(key, {})
            rho = val.get("spearman_rho") if isinstance(val, dict) else val
            if rho is not None:
                pooled_rhos[key].append(rho)

        # Collect top overlap
        to = result.get("top_overlap", {})
        for k, v in to.items():
            pooled_top10.setdefault(k, {"actual": [], "expected": []})
            if v.get("actual") is not None:
                pooled_top10[k]["actual"].append(v["actual"])
            if v.get("expected") is not None:
                pooled_top10[k]["expected"].append(v["expected"])

        # Collect overlap table
        for row in result.get("overlap_table", []):
            key = (row["gt"], row["pct"])
            pooled_overlap_table.setdefault(key, {"gt_name": row["gt_name"], "pct": row["pct"],
                "top_actual": [], "top_expected": [], "bottom_actual": [], "bottom_expected": []})
            for f in ["top_actual", "top_expected", "bottom_actual", "bottom_expected"]:
                if row.get(f) is not None:
                    pooled_overlap_table[key][f].append(row[f])

    if not per_dataset:
        return {"status": "no_data"}

    pooled_bt = {}
    for key, vals in pooled_rhos.items():
        if vals:
            pooled_bt[key] = {"spearman_rho": safe_round(float(np.mean(vals))), "n_datasets": len(vals)}

    pooled_top10_avg = {}
    for key, vals in pooled_top10.items():
        entry = {}
        if vals.get("actual"):
            entry["actual"] = safe_round(float(np.mean(vals["actual"])))
        if vals.get("expected"):
            entry["expected"] = safe_round(float(np.mean(vals["expected"])))
        if entry:
            pooled_top10_avg[key] = entry

    # Pool overlap table
    pooled_ot_rows = []
    for key in sorted(pooled_overlap_table.keys()):
        entry = pooled_overlap_table[key]
        row = {"gt": key[0], "gt_name": entry["gt_name"], "pct": entry["pct"]}
        for f in ["top_actual", "top_expected", "bottom_actual", "bottom_expected"]:
            vals = entry[f]
            row[f] = safe_round(float(np.mean(vals))) if vals else None
        pooled_ot_rows.append(row)

    # Pool per scoring method
    _SCORING_METHODS = ["win_rate", "bt", "trueskill"]
    by_method_response = {}
    for method in _SCORING_METHODS:
        m_rhos = {"indiv": [], "maj": [], "tier": [], "avg_rating": []}
        m_top10 = {}
        m_ot = {}
        for result in per_dataset:
            md = result.get("by_method", {}).get(method)
            if not md:
                continue
            for rk in m_rhos:
                val = md.get("bt", {}).get(rk, {})
                rho = val.get("spearman_rho") if isinstance(val, dict) else val
                if rho is not None:
                    m_rhos[rk].append(rho)
            for k, v in md.get("top_overlap", {}).items():
                m_top10.setdefault(k, {"actual": [], "expected": []})
                if v.get("actual") is not None:
                    m_top10[k]["actual"].append(v["actual"])
                if v.get("expected") is not None:
                    m_top10[k]["expected"].append(v["expected"])
            for row in md.get("overlap_table", []):
                otkey = (row["gt"], row["pct"])
                m_ot.setdefault(otkey, {"gt_name": row["gt_name"], "pct": row["pct"],
                    "top_actual": [], "top_expected": [], "bottom_actual": [], "bottom_expected": []})
                for f in ["top_actual", "top_expected", "bottom_actual", "bottom_expected"]:
                    if row.get(f) is not None:
                        m_ot[otkey][f].append(row[f])

        m_pooled_bt = {}
        for rk, vals in m_rhos.items():
            if vals:
                m_pooled_bt[rk] = {"spearman_rho": safe_round(float(np.mean(vals))), "n_datasets": len(vals)}
        m_pooled_top10 = {}
        for k, vals in m_top10.items():
            entry = {}
            if vals.get("actual"):
                entry["actual"] = safe_round(float(np.mean(vals["actual"])))
            if vals.get("expected"):
                entry["expected"] = safe_round(float(np.mean(vals["expected"])))
            if entry:
                m_pooled_top10[k] = entry
        m_pooled_ot = []
        for otkey in sorted(m_ot.keys()):
            entry = m_ot[otkey]
            row = {"gt": otkey[0], "gt_name": entry["gt_name"], "pct": entry["pct"]}
            for f in ["top_actual", "top_expected", "bottom_actual", "bottom_expected"]:
                vals = entry[f]
                row[f] = safe_round(float(np.mean(vals))) if vals else None
            m_pooled_ot.append(row)

        by_method_response[method] = {
            "pooled_bt": m_pooled_bt,
            "pooled_top10_overlap": m_pooled_top10,
            "pooled_overlap_table": m_pooled_ot,
        }

    return {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(per_dataset),
        "scoring_methods": _SCORING_METHODS,
        "pooled_bt": pooled_bt,
        "pooled_top10_overlap": pooled_top10_avg,
        "pooled_overlap_table": pooled_ot_rows,
        "per_dataset": per_dataset,
        "by_method": by_method_response,
    }


async def _compute_standalone_ranking(dataset_id: str, include_within_tier: bool = False):
    """Compute AI ranking quality for a single dataset using full independent data."""
    papers = await collect_all(db.validation_papers.find(
        {"dataset_id": dataset_id}, PAPER_LIGHT_PROJECTION,
    ))
    if not papers:
        return None

    papers_by_id = {p["id"]: p for p in papers}
    paper_ids = [p["id"] for p in papers]

    # --- Expert data: ALL pairs with ≥2 non-tying opinions ---
    expert_ratings = build_expert_ratings(papers)
    experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}

    if len(experts_with_data) < 2:
        return None

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

    all_expert_pairs_ge2 = {p for p, v in expert_pair_prefs.items() if len(v) >= 2}

    # Extended expert pairs including all-expert-tie pairs (for accurate pair counts)
    expert_pair_rated_sr = defaultdict(set)
    for exp, ratings in experts_with_data.items():
        rated_ids = list(ratings.keys())
        for i in range(len(rated_ids)):
            for j in range(i + 1, len(rated_ids)):
                pair = tuple(sorted([rated_ids[i], rated_ids[j]]))
                expert_pair_rated_sr[pair].add(exp)
    all_rated_pairs_incl_ties = set(expert_pair_rated_sr.keys())

    expert_majority = {}
    for pair, votes in expert_pair_prefs.items():
        if len(votes) < 2:
            continue
        c = Counter(votes.values())
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            expert_majority[pair] = best

    # Human BT baselines from ALL expert data
    human_indiv_matches = []
    for pair in all_expert_pairs_ge2:
        for exp, winner in expert_pair_prefs[pair].items():
            human_indiv_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": winner, "completed": True, "failed": False,
            })

    human_maj_matches = []
    for pair in all_expert_pairs_ge2:
        if pair in expert_majority:
            human_maj_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": expert_majority[pair], "completed": True, "failed": False,
            })

    # --- AI data: ALL thinking-mode matches ---
    sample = await db.validation_papers.find_one(
        {"dataset_id": dataset_id, "ai_impact_summary_thinking": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1},
    )
    ai_content_mode = "abstract_plus_summary:thinking" if sample else "abstract_plus_summary"
    mode_count = await db.validation_matches.count_documents(
        {"dataset_id": dataset_id, "completed": True, "content_mode": ai_content_mode})
    if mode_count == 0:
        ai_content_mode = "abstract_plus_summary"

    ai_sr_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": ai_content_mode}
    if not include_within_tier:
        ai_sr_filter["experiment_tag"] = {"$exists": False}

    ai_raw = await collect_all(db.validation_matches.find(
        ai_sr_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))

    # Subsample within-tier to natural proportion (same logic as _compute_dataset_benchmark)
    if include_within_tier:
        base_sr = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))
        exp_sr = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))

        import random as _rng
        TIER_MAP = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}
        def _is_within_sr(m):
            t1 = norm_tier(papers_by_id.get(m["paper1_id"], {}).get("decision"))
            t2 = norm_tier(papers_by_id.get(m["paper2_id"], {}).get("decision"))
            return t1 is not None and t2 is not None and TIER_MAP.get(t1, -1) == TIER_MAP.get(t2, -2)

        # Combine base + all experiment matches, then ensure natural within-tier proportion
        all_sr_combined = base_sr + exp_sr
        cross_adj_sr = sorted([m for m in all_sr_combined if not _is_within_sr(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))
        within_sr = sorted([m for m in all_sr_combined if _is_within_sr(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))

        all_pids = list(papers_by_id.keys())
        nat_cross_adj, nat_within = 0, 0
        for i in range(len(all_pids)):
            for j in range(i+1, len(all_pids)):
                t1 = norm_tier(papers_by_id[all_pids[i]].get("decision"))
                t2 = norm_tier(papers_by_id[all_pids[j]].get("decision"))
                if t1 and t2:
                    if TIER_MAP.get(t1) == TIER_MAP.get(t2):
                        nat_within += 1
                    else:
                        nat_cross_adj += 1
        nat_total = nat_cross_adj + nat_within
        nat_within_frac = nat_within / nat_total if nat_total > 0 else 0.3

        target_within = int(len(cross_adj_sr) * nat_within_frac / max(0.01, 1 - nat_within_frac))
        target_within = min(target_within, len(within_sr))
        if target_within < len(within_sr):
            _rng.seed(42 + hash(dataset_id))
            within_sr = _rng.sample(within_sr, target_within)
        ai_raw = cross_adj_sr + within_sr
    else:
        ai_raw = await collect_all(db.validation_matches.find(
            ai_sr_filter,
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))

    ai_bt_matches = [
        {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
         "winner_id": m["winner_id"], "completed": True, "failed": False}
        for m in ai_raw if m.get("winner_id")
    ]

    if len(ai_bt_matches) < 10 or len(human_indiv_matches) < 10:
        return None

    # Paper universe: all papers in the dataset
    all_papers = papers

    # Compute leaderboards
    ai_lb = await compute_leaderboard(all_papers, ai_bt_matches)
    h_indiv_lb = await compute_leaderboard(all_papers, human_indiv_matches)
    h_maj_lb = await compute_leaderboard(all_papers, human_maj_matches) if human_maj_matches else []

    ai_rank = {e["id"]: e["score"] for e in ai_lb}
    h_indiv_rank = {e["id"]: e["score"] for e in h_indiv_lb}
    h_maj_rank = {e["id"]: e["score"] for e in h_maj_lb}

    def _correlate(a_rank, h_rank):
        shared = sorted(set(a_rank.keys()) & set(h_rank.keys()))
        if len(shared) < 5:
            return None, None
        sp, _ = scipy_stats.spearmanr([a_rank[p] for p in shared], [h_rank[p] for p in shared])
        kt, _ = scipy_stats.kendalltau([a_rank[p] for p in shared], [h_rank[p] for p in shared])
        rho = float(sp) if not np.isnan(sp) else None
        tau = float(kt) if not np.isnan(kt) else None
        return rho, tau

    # Ground truth maps (used by _build_method_results as closures)
    tier_score_map = {}
    for p in papers:
        t = norm_tier(p.get("decision"))
        if t and t in TIER_ORDER:
            tier_score_map[p["id"]] = TIER_ORDER[t]

    avg_rating_map = {}
    for p in papers:
        r = p.get("h1_avg_rating")
        if r is None:
            evals = p.get("evaluations", [])
            vals = [e["rating_value"] for e in evals if e.get("rating_value")]
            r = sum(vals) / len(vals) if vals else None
        if r is not None:
            avg_rating_map[p["id"]] = r

    # Count AI pair overlap with expert pairs
    ai_pairs = set()
    for m in ai_raw:
        if m.get("winner_id"):
            ai_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
    overlap = len(ai_pairs & all_expert_pairs_ge2)
    overlap_incl_ties = len(ai_pairs & all_rated_pairs_incl_ties)

    # Top/Bottom K% overlap across GT methods and percentiles
    import random as _rng_top
    def _compute_overlap(ai_rank_map, gt_rank_map, frac, bottom=False):
        shared = sorted(set(ai_rank_map.keys()) & set(gt_rank_map.keys()))
        if len(shared) < 5:
            return None, None
        k = max(1, int(len(shared) * frac))
        ai_sorted = sorted(shared, key=lambda p: ai_rank_map.get(p, 0), reverse=not bottom)
        gt_sorted = sorted(shared, key=lambda p: gt_rank_map.get(p, 0), reverse=not bottom)
        actual = len(set(ai_sorted[:k]) & set(gt_sorted[:k])) / k * 100
        sp, _ = scipy_stats.spearmanr([ai_rank_map[p] for p in shared], [gt_rank_map[p] for p in shared])
        if np.isnan(sp):
            return actual, None
        n = len(shared)
        np.random.seed(42)
        exps = []
        for _ in range(500):
            x = np.random.randn(n)
            noise = np.random.randn(n)
            y = float(sp) * x + np.sqrt(max(0, 1 - float(sp)**2)) * noise
            if bottom:
                x_sel = set(np.argsort(x)[:k])
                y_sel = set(np.argsort(y)[:k])
            else:
                x_sel = set(np.argsort(x)[-k:])
                y_sel = set(np.argsort(y)[-k:])
            exps.append(len(x_sel & y_sel) / k * 100)
        return actual, float(np.mean(exps))

    # Build the full overlap table
    fracs = [0.05, 0.10, 0.20, 0.30, 0.40, 0.50]

    def _build_method_results(ai_r, h_indiv_r, h_maj_r):
        """Compute correlations and overlap tables for one scoring method."""
        m_bt = {}
        rho, tau = _correlate(ai_r, h_indiv_r)
        m_bt["indiv"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}
        rho, tau = _correlate(ai_r, h_maj_r)
        m_bt["maj"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}
        if len(tier_score_map) >= 5:
            rho, tau = _correlate(ai_r, {pid: -s for pid, s in tier_score_map.items()})
            m_bt["tier"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}
        if len(avg_rating_map) >= 5:
            rho, _ = _correlate(ai_r, avg_rating_map)
            m_bt["avg_rating"] = safe_round(rho)

        m_gt_methods = [("indiv", "Aggregate", h_indiv_r), ("maj", "Majority", h_maj_r), ("avg_rating", "Avg Rating", avg_rating_map)]
        m_ot = []
        for gt_key, gt_name, gt_rank in m_gt_methods:
            for frac in fracs:
                pct = int(frac * 100)
                actual_t, expected_t = _compute_overlap(ai_r, gt_rank, frac, bottom=False)
                actual_b, expected_b = _compute_overlap(ai_r, gt_rank, frac, bottom=True)
                m_ot.append({
                    "gt": gt_key, "gt_name": gt_name, "pct": pct,
                    "top_actual": safe_round(actual_t) if actual_t is not None else None,
                    "top_expected": safe_round(expected_t) if expected_t is not None else None,
                    "bottom_actual": safe_round(actual_b) if actual_b is not None else None,
                    "bottom_expected": safe_round(expected_b) if expected_b is not None else None,
                })

        m_to = {}
        for gt_key, gt_name, gt_rank in m_gt_methods:
            for pct_label, frac in [("10", 0.10), ("20", 0.20)]:
                actual, expected = _compute_overlap(ai_r, gt_rank, frac, bottom=False)
                if actual is not None:
                    m_to[f"{gt_key}_top{pct_label}"] = {"actual": safe_round(actual), "expected": safe_round(expected) if expected else None}

        return {"bt": m_bt, "top_overlap": m_to, "overlap_table": m_ot}

    # Default method results (win_rate) — used for backward compat top-level fields
    default_results = _build_method_results(ai_rank, h_indiv_rank, h_maj_rank)

    # Compute alternative scoring methods
    from services.ranking import compute_bt_ranking_scores, compute_trueskill_ranking_scores
    _paper_ids = [p["id"] for p in all_papers]
    by_method = {"win_rate": default_results}
    for method_key, score_fn in [("bt", compute_bt_ranking_scores), ("trueskill", compute_trueskill_ranking_scores)]:
        _ai_r = score_fn(ai_bt_matches, _paper_ids)
        _hi_r = score_fn(human_indiv_matches, _paper_ids)
        _hm_r = score_fn(human_maj_matches, _paper_ids) if human_maj_matches else {}
        by_method[method_key] = _build_method_results(_ai_r, _hi_r, _hm_r)

    return {
        "dataset_id": dataset_id,
        "n_papers": len(papers),
        "n_ai_matches": len(ai_bt_matches),
        "n_ai_pairs": len(ai_pairs),
        "n_expert_pairs": len(all_expert_pairs_ge2),
        "n_expert_pairs_incl_ties": len(all_rated_pairs_incl_ties),
        "pair_overlap": overlap,
        "pair_overlap_incl_ties": overlap_incl_ties,
        "bt": default_results["bt"],
        "top_overlap": default_results["top_overlap"],
        "overlap_table": default_results["overlap_table"],
        "by_method": by_method,
    }
