"""
Simplified Human vs AI Benchmark — "Fixed" variant.

Clean reimplementation with minimal filters:
- ALL reviewers included (no minimum papers-rated threshold)
- >=1 non-tie expert preference per pair for controlled set
- Rankable tiers only (Oral/Spotlight/Poster/Reject — excl. withdrawn/desk-rejected)
- ICLR datasets only (no PeerRead)
- Pair-pooled aggregation (not expert-averaged)
- Deterministic within-tier subsampling (hashlib-based seed)
"""

import hashlib
import math
import random as _rng
from collections import defaultdict, Counter

import numpy as np
from scipy import stats as scipy_stats

from routers.human_ai_benchmark import (
    collect_all, build_expert_ratings, norm_tier, TIER_SCORE,
    _wilson_ci,
)


def _rate(a, t):
    return round(a / t * 100, 1) if t else 0.0


def _cf_rate_ext(agree, total):
    return round(agree / total * 100, 1) if total else None


def safe_round(v, n=4):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(v, n)


def _simple_bt_scores(pair_winners, paper_ids):
    """Simple Bradley-Terry scores from pairwise winners. Returns {paper_id: score}."""
    wins = Counter()
    comparisons = Counter()
    for pair, winner in pair_winners:
        a, b = pair
        comparisons[a] += 1
        comparisons[b] += 1
        wins[winner] += 1
    # Regularized win-rate score (same as leaderboard)
    scores = {}
    for pid in paper_ids:
        w = wins.get(pid, 0)
        c = comparisons.get(pid, 0)
        if c == 0:
            scores[pid] = 0.0
        else:
            p = max(0.02, min(0.98, (w + 0.5) / (c + 1.0)))
            scores[pid] = 400.0 * math.log10(p / (1 - p))
    return scores

RANKABLE_TIERS = {"oral", "spotlight", "poster", "reject"}

ICLR_DATASETS = [
    "iclr-codegen", "iclr-fairness", "iclr-llm", "iclr-molecules",
    "iclr-optimization", "iclr-ot", "iclr-pdes", "iclr-protein",
]


async def compute_fixed_benchmark(db):
    """Compute the simplified fixed benchmark across all ICLR datasets."""
    per_dataset = []

    for ds_id in ICLR_DATASETS:
        result = await _compute_dataset(db, ds_id)
        if result:
            per_dataset.append(result)

    if not per_dataset:
        return {"status": "no_data"}

    # Pool across datasets
    pooled = _pool_datasets(per_dataset)

    return {
        "status": "ok",
        "n_datasets": len(per_dataset),
        "total_papers": sum(d["n_papers"] for d in per_dataset),
        "total_controlled_pairs": sum(d["controlled_pairs"] for d in per_dataset),
        "total_controlled_pairs_cf": sum(d["controlled_pairs_cf"] for d in per_dataset),
        "pooled": pooled,
        "per_dataset": per_dataset,
    }


async def _compute_dataset(db, dataset_id: str):
    """Compute benchmark for a single dataset with simplified filters."""

    # --- Load papers ---
    papers = await collect_all(db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "decision": 1, "evaluations": 1,
         "ai_impact_summary_thinking": 1},
    ))
    if len(papers) < 4:
        return None

    papers_by_id = {p["id"]: p for p in papers}

    # --- Build expert ratings: ALL reviewers, no minimum ---
    expert_ratings = build_expert_ratings(papers)
    # No filter: include every reviewer who rated at least 1 paper

    # --- Expert pairwise preferences ---
    # For every pair where at least one expert has a preference
    expert_pair_prefs = defaultdict(dict)  # {pair: {expert: winner_id}}
    expert_pair_rated = defaultdict(set)    # {pair: {expert, ...}} — includes ties

    for exp, ratings in expert_ratings.items():
        rated_ids = list(ratings.keys())
        for i in range(len(rated_ids)):
            for j in range(i + 1, len(rated_ids)):
                a, b = rated_ids[i], rated_ids[j]
                pair = tuple(sorted([a, b]))
                expert_pair_rated[pair].add(exp)
                if ratings[a] != ratings[b]:
                    expert_pair_prefs[pair][exp] = a if ratings[a] > ratings[b] else b

    # --- Load AI matches (with within-tier) ---
    has_thinking = any(p.get("ai_impact_summary_thinking") for p in papers)
    ai_mode = "abstract_plus_summary:thinking" if has_thinking else "abstract_plus_summary"
    if await db.validation_matches.count_documents(
        {"dataset_id": dataset_id, "completed": True, "content_mode": ai_mode}) == 0:
        ai_mode = "abstract_plus_summary"

    base_raw = await collect_all(db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": ai_mode, "experiment_tag": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))
    exp_raw = await collect_all(db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": ai_mode, "experiment_tag": {"$exists": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))

    # Split cross-tier vs within-tier, subsample within-tier to natural proportion
    def _is_within(m):
        t1 = norm_tier(papers_by_id.get(m["paper1_id"], {}).get("decision"))
        t2 = norm_tier(papers_by_id.get(m["paper2_id"], {}).get("decision"))
        return (t1 is not None and t2 is not None and
                TIER_SCORE.get(t1, -1) == TIER_SCORE.get(t2, -2))

    combined = base_raw + exp_raw
    cross = [m for m in combined if not _is_within(m)]
    within = [m for m in combined if _is_within(m)]

    # Natural within-tier fraction
    all_pids = list(papers_by_id.keys())
    nat_cross, nat_within = 0, 0
    for i in range(len(all_pids)):
        for j in range(i + 1, len(all_pids)):
            t1 = norm_tier(papers_by_id[all_pids[i]].get("decision"))
            t2 = norm_tier(papers_by_id[all_pids[j]].get("decision"))
            if t1 and t2:
                if TIER_SCORE.get(t1) == TIER_SCORE.get(t2):
                    nat_within += 1
                else:
                    nat_cross += 1
    nat_total = nat_cross + nat_within
    nat_frac = nat_within / nat_total if nat_total > 0 else 0.3
    target_within = int(len(cross) * nat_frac / max(0.01, 1 - nat_frac))
    target_within = min(target_within, len(within))
    if target_within < len(within):
        seed = 42 + int(hashlib.sha256(dataset_id.encode()).hexdigest()[:8], 16)
        _rng.seed(seed)
        within = _rng.sample(within, target_within)
    ai_raw = cross + within

    # --- AI majority vote per pair ---
    ai_pair_votes = defaultdict(list)
    for m in ai_raw:
        if m.get("winner_id"):
            pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            ai_pair_votes[pair].append(m["winner_id"])

    ai_pair = {}
    for pair, votes in ai_pair_votes.items():
        c = Counter(votes)
        ai_pair[pair] = c.most_common(1)[0][0]

    # --- Expert majority (>=1 non-tie vote = majority) ---
    expert_majority = {}
    for pair, votes in expert_pair_prefs.items():
        c = Counter(votes.values())
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            expert_majority[pair] = best

    # --- Controlled pair sets ---
    # controlled = pairs with >=1 non-tie expert AND AI verdict
    controlled_pairs = set(expert_pair_prefs.keys()) & set(ai_pair.keys())
    # controlled_cf = pairs where experts rated both papers (incl. all-tie) AND AI verdict
    controlled_pairs_cf = set(expert_pair_rated.keys()) & set(ai_pair.keys())

    if not controlled_pairs:
        return None

    # =====================================================================
    # METRICS (all pair-pooled, clean logic)
    # =====================================================================

    # --- 1. AI vs Human (individual expert level) ---
    ah_agree, ah_total, ah_ties = 0, 0, 0
    # CF version
    cf_ah_agree, cf_ah_total = 0.0, 0

    for pair in controlled_pairs_cf:
        a, b = pair
        for exp in expert_pair_rated[pair]:
            cf_ah_total += 1
            if pair in expert_pair_prefs and exp in expert_pair_prefs[pair]:
                # Expert has preference
                ah_total += 1
                if ai_pair[pair] == expert_pair_prefs[pair][exp]:
                    ah_agree += 1
                    cf_ah_agree += 1
            else:
                # Expert tied → coin flip
                ah_ties += 1
                cf_ah_agree += 0.5

    # --- 2. Human vs Human (pairwise, >=2 experts with preferences) ---
    hh_agree, hh_total = 0, 0
    cf_hh_agree, cf_hh_total = 0.0, 0

    for pair in controlled_pairs_cf:
        prefs = expert_pair_prefs.get(pair, {})
        rated = expert_pair_rated.get(pair, set())
        experts_list = list(rated)
        for i in range(len(experts_list)):
            for j in range(i + 1, len(experts_list)):
                e1, e2 = experts_list[i], experts_list[j]
                p1 = prefs.get(e1)  # winner_id or None (tie)
                p2 = prefs.get(e2)
                cf_hh_total += 1
                if p1 is not None and p2 is not None:
                    hh_total += 1
                    if p1 == p2:
                        hh_agree += 1
                        cf_hh_agree += 1
                elif p1 is None and p2 is None:
                    # Both tied → coin flip
                    cf_hh_agree += 0.5
                else:
                    # One tied, one has preference → coin flip
                    cf_hh_agree += 0.5

    # --- 3. AI vs Majority (simple majority of non-tied experts) ---
    ac_agree, ac_total = 0, 0
    cf_ac_agree, cf_ac_total = 0.0, 0

    for pair in controlled_pairs_cf:
        cf_ac_total += 1
        if pair in expert_majority:
            ac_total += 1
            if ai_pair[pair] == expert_majority[pair]:
                ac_agree += 1
                cf_ac_agree += 1
        else:
            # No majority (split or all-tie) → coin flip
            cf_ac_agree += 0.5

    # --- 4. Human vs Majority (LOO) ---
    hc_loo_agree, hc_loo_total = 0, 0
    cf_hc_loo_agree, cf_hc_loo_total = 0.0, 0

    for pair in controlled_pairs_cf:
        prefs = expert_pair_prefs.get(pair, {})
        rated = expert_pair_rated.get(pair, set())
        for exp in rated:
            others_prefs = {e: v for e, v in prefs.items() if e != exp}
            if len(others_prefs) >= 2:
                c = Counter(others_prefs.values())
                best, n = c.most_common(1)[0]
                if n > len(others_prefs) / 2:
                    # Clear LOO majority
                    exp_pref = prefs.get(exp)
                    cf_hc_loo_total += 1
                    if exp_pref is not None:
                        hc_loo_total += 1
                        if exp_pref == best:
                            hc_loo_agree += 1
                            cf_hc_loo_agree += 1
                    else:
                        cf_hc_loo_agree += 0.5

    # --- 4b. Human vs Majority (non-LOO, for completeness) ---
    hc_agree, hc_total = 0, 0
    cf_hc_agree, cf_hc_total = 0.0, 0

    for pair in controlled_pairs_cf:
        prefs = expert_pair_prefs.get(pair, {})
        rated = expert_pair_rated.get(pair, set())
        if pair in expert_majority:
            maj = expert_majority[pair]
            for exp in rated:
                cf_hc_total += 1
                exp_pref = prefs.get(exp)
                if exp_pref is not None:
                    hc_total += 1
                    if exp_pref == maj:
                        hc_agree += 1
                        cf_hc_agree += 1
                else:
                    cf_hc_agree += 0.5
        else:
            for exp in rated:
                cf_hc_total += 1
                cf_hc_agree += 0.5

    # --- 5. AI vs Committee (tier accuracy, rankable only) ---
    tier_ai_agree, tier_ai_total = 0, 0
    tier_hh_agree, tier_hh_total = 0, 0
    cf_tier_ai_agree, cf_tier_ai_total = 0.0, 0
    cf_tier_hh_agree, cf_tier_hh_total = 0.0, 0
    cf_tier_same_count = 0

    for pair in controlled_pairs_cf:
        a, b = pair
        ta = norm_tier(papers_by_id.get(a, {}).get("decision"))
        tb = norm_tier(papers_by_id.get(b, {}).get("decision"))

        # Only rankable tiers
        if ta not in RANKABLE_TIERS or tb not in RANKABLE_TIERS:
            # Non-rankable → coin flip in CF
            cf_tier_ai_total += 1
            cf_tier_ai_agree += 0.5
            cf_tier_same_count += 1
            prefs = expert_pair_prefs.get(pair, {})
            for exp in expert_pair_rated.get(pair, set()):
                cf_tier_hh_total += 1
                cf_tier_hh_agree += 0.5
            continue

        sa = TIER_SCORE.get(ta, -1)
        sb = TIER_SCORE.get(tb, -1)

        if sa != sb:
            tier_winner = a if sa > sb else b
            # AI
            tier_ai_total += 1
            cf_tier_ai_total += 1
            if ai_pair[pair] == tier_winner:
                tier_ai_agree += 1
                cf_tier_ai_agree += 1
            # Human experts
            prefs = expert_pair_prefs.get(pair, {})
            for exp in expert_pair_rated.get(pair, set()):
                cf_tier_hh_total += 1
                if exp in prefs:
                    tier_hh_total += 1
                    if prefs[exp] == tier_winner:
                        tier_hh_agree += 1
                        cf_tier_hh_agree += 1
                else:
                    cf_tier_hh_agree += 0.5
        else:
            # Same tier → coin flip
            cf_tier_same_count += 1
            cf_tier_ai_total += 1
            cf_tier_ai_agree += 0.5
            for exp in expert_pair_rated.get(pair, set()):
                cf_tier_hh_total += 1
                cf_tier_hh_agree += 0.5

    # --- 6. Ranking correlation (BT scores: all comparisons) ---
    bt_results = {}

    try:
        all_pids_in_controlled = list({pid for pair in controlled_pairs for pid in pair})

        # AI BT scores (from AI majority votes)
        ai_bt = _simple_bt_scores(
            [(pair, ai_pair[pair]) for pair in controlled_pairs],
            all_pids_in_controlled
        )

        # Human majority BT scores
        maj_pairs = [(pair, expert_majority[pair]) for pair in controlled_pairs if pair in expert_majority]
        h_maj_bt = _simple_bt_scores(maj_pairs, all_pids_in_controlled) if len(maj_pairs) >= 10 else {}

        # Human individual aggregate BT (each expert vote = separate match)
        indiv_pairs = []
        for pair in controlled_pairs:
            prefs = expert_pair_prefs.get(pair, {})
            for exp, winner in prefs.items():
                indiv_pairs.append((pair, winner))
        h_indiv_bt = _simple_bt_scores(indiv_pairs, all_pids_in_controlled) if len(indiv_pairs) >= 10 else {}

        # Average reviewer score per paper
        avg_rating = {}
        for pid in all_pids_in_controlled:
            scores = []
            for exp, ratings in expert_ratings.items():
                if pid in ratings:
                    scores.append(ratings[pid])
            if scores:
                avg_rating[pid] = sum(scores) / len(scores)

        # Tier score per paper (for AI vs Committee correlation)
        tier_scores = {}
        for pid in all_pids_in_controlled:
            t = norm_tier(papers_by_id.get(pid, {}).get("decision"))
            if t in RANKABLE_TIERS:
                tier_scores[pid] = TIER_SCORE.get(t, 0)

        def _corr(scores_a, scores_b, pids=None):
            """Compute Spearman and Kendall between two score dicts."""
            if pids is None:
                pids = sorted(set(scores_a.keys()) & set(scores_b.keys()))
            else:
                pids = [p for p in pids if p in scores_a and p in scores_b]
            if len(pids) < 5:
                return None, None
            a = [scores_a[p] for p in pids]
            b = [scores_b[p] for p in pids]
            rho = scipy_stats.spearmanr(a, b).statistic
            tau = scipy_stats.kendalltau(a, b).statistic
            rho = None if (isinstance(rho, float) and math.isnan(rho)) else rho
            tau = None if (isinstance(tau, float) and math.isnan(tau)) else tau
            return rho, tau

        # AI VS HUMAN comparisons
        # AI vs Individual aggregate
        rho, tau = _corr(ai_bt, h_indiv_bt)
        bt_results["individual"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}

        # AI vs Avg Rating
        rho, tau = _corr(ai_bt, avg_rating)
        bt_results["vs_avg_rating"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}
        bt_results["vs_avg_rating_rho"] = safe_round(rho)

        # AI vs Majority
        rho, tau = _corr(ai_bt, h_maj_bt)
        bt_results["committee"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}

        # AI vs Committee (ICLR PC tier)
        rho, tau = _corr(ai_bt, tier_scores)
        bt_results["vs_tier_rho"] = safe_round(rho)
        bt_results["vs_tier_tau"] = safe_round(tau)

        # Indiv vs Comm (consistency check)
        rho, tau = _corr(h_indiv_bt, h_maj_bt)
        bt_results["indiv_vs_comm"] = {"spearman_rho": safe_round(rho), "kendall_tau": safe_round(tau)}

        # HUMAN INTERNAL comparisons (LOO-based, averaged across experts)
        loo_vs_indiv_rhos = []
        loo_vs_avg_rhos = []
        loo_vs_maj_rhos = []
        loo_vs_tier_rhos = []
        loo_vs_indiv_agg_rhos = []   # LOO individual-aggregate

        for exp, ratings in expert_ratings.items():
            if len(ratings) < 5:
                continue
            # Expert's own pairwise preferences → BT
            exp_pairs = [(pair, expert_pair_prefs[pair][exp])
                         for pair in controlled_pairs
                         if pair in expert_pair_prefs and exp in expert_pair_prefs[pair]]
            if len(exp_pairs) < 5:
                continue
            exp_bt = _simple_bt_scores(exp_pairs, all_pids_in_controlled)

            # LOO majority (exclude this expert)
            loo_maj_pairs = []
            for pair in controlled_pairs:
                prefs = expert_pair_prefs.get(pair, {})
                others = {e: v for e, v in prefs.items() if e != exp}
                if len(others) >= 2:
                    c = Counter(others.values())
                    best, n = c.most_common(1)[0]
                    if n > len(others) / 2:
                        loo_maj_pairs.append((pair, best))
            loo_maj_bt = _simple_bt_scores(loo_maj_pairs, all_pids_in_controlled) if len(loo_maj_pairs) >= 5 else {}

            # LOO individual aggregate (all others' votes)
            loo_indiv_pairs = []
            for pair in controlled_pairs:
                prefs = expert_pair_prefs.get(pair, {})
                for e, v in prefs.items():
                    if e != exp:
                        loo_indiv_pairs.append((pair, v))
            loo_indiv_bt = _simple_bt_scores(loo_indiv_pairs, all_pids_in_controlled) if len(loo_indiv_pairs) >= 5 else {}

            # LOO avg rating
            loo_avg = {}
            for pid in all_pids_in_controlled:
                scores = [ratings[pid] for e, ratings in expert_ratings.items() if e != exp and pid in ratings]
                if scores:
                    loo_avg[pid] = sum(scores) / len(scores)

            # Correlations
            r, _ = _corr(exp_bt, h_indiv_bt)
            if r is not None:
                loo_vs_indiv_agg_rhos.append(r)

            r, _ = _corr(exp_bt, loo_avg)
            if r is not None:
                loo_vs_avg_rhos.append(r)

            r, _ = _corr(exp_bt, loo_maj_bt)
            if r is not None:
                loo_vs_maj_rhos.append(r)

            r, _ = _corr(exp_bt, tier_scores)
            if r is not None:
                loo_vs_tier_rhos.append(r)

            r, _ = _corr(exp_bt, loo_indiv_bt)
            if r is not None:
                loo_vs_indiv_rhos.append(r)

        bt_results["avg_expert_vs_ai"] = {"spearman_rho": safe_round(float(np.mean([r for r in loo_vs_indiv_rhos]))) if loo_vs_indiv_rhos else None}
        bt_results["avg_expert_vs_comm"] = {"spearman_rho": safe_round(float(np.mean(loo_vs_maj_rhos))) if loo_vs_maj_rhos else None}
        bt_results["avg_expert_vs_indiv"] = {"spearman_rho": safe_round(float(np.mean(loo_vs_indiv_agg_rhos))) if loo_vs_indiv_agg_rhos else None}
        bt_results["avg_expert_vs_loo"] = {"spearman_rho": safe_round(float(np.mean(loo_vs_maj_rhos))) if loo_vs_maj_rhos else None}
        bt_results["avg_expert_vs_loo_avg"] = {"spearman_rho": safe_round(float(np.mean(loo_vs_avg_rhos))) if loo_vs_avg_rhos else None}
        bt_results["avg_expert_vs_loo_indiv"] = {"spearman_rho": safe_round(float(np.mean(loo_vs_indiv_rhos))) if loo_vs_indiv_rhos else None}
        bt_results["avg_expert_vs_tier"] = {"spearman_rho": safe_round(float(np.mean(loo_vs_tier_rhos))) if loo_vs_tier_rhos else None}

    except Exception:
        pass

    # --- Tie rates ---
    tie_rates = {
        "ah": round((1 - ah_total / cf_ah_total) * 100, 1) if cf_ah_total else 0,
        "hh": round((1 - hh_total / cf_hh_total) * 100, 1) if cf_hh_total else 0,
        "ac": round((1 - ac_total / cf_ac_total) * 100, 1) if cf_ac_total else 0,
        "hc": round((1 - hc_total / cf_hc_total) * 100, 1) if cf_hc_total else 0,
        "hc_loo": round((1 - hc_loo_total / cf_hc_loo_total) * 100, 1) if cf_hc_loo_total else 0,
        "tier_ai": round((1 - tier_ai_total / cf_tier_ai_total) * 100, 1) if cf_tier_ai_total else 0,
        "tier_hh": round((1 - tier_hh_total / cf_tier_hh_total) * 100, 1) if cf_tier_hh_total else 0,
    }

    # --- Kappa ---
    def _kappa(agree, total):
        if total == 0:
            return None
        po = agree / total
        pe = 0.5
        if pe == 1:
            return 1.0
        return round((po - pe) / (1 - pe), 4)

    return {
        "dataset_id": dataset_id,
        "name": papers[0].get("title", dataset_id).split(":")[0] if False else _dataset_name(dataset_id),
        "n_papers": len(papers),
        "n_experts": len(expert_ratings),
        "controlled_pairs": ac_total,  # pairs with clear expert majority (= "ties excluded" denominator)
        "controlled_pairs_cf": len(controlled_pairs_cf),
        "pairwise": {
            "ai_human": {"agree": ah_agree, "total": ah_total, "rate": _rate(ah_agree, ah_total),
                         "kappa": _kappa(ah_agree, ah_total), "ci": _wilson_ci(ah_agree, ah_total),
                         "cf_rate": _cf_rate_ext(cf_ah_agree, cf_ah_total), "cf_total": int(cf_ah_total)},
            "human_human": {"agree": hh_agree, "total": hh_total, "rate": _rate(hh_agree, hh_total),
                            "kappa": _kappa(hh_agree, hh_total), "ci": _wilson_ci(hh_agree, hh_total),
                            "cf_rate": _cf_rate_ext(cf_hh_agree, cf_hh_total), "cf_total": int(cf_hh_total)},
            "ai_committee": {"agree": ac_agree, "total": ac_total, "rate": _rate(ac_agree, ac_total),
                             "kappa": _kappa(ac_agree, ac_total), "ci": _wilson_ci(ac_agree, ac_total),
                             "cf_rate": _cf_rate_ext(cf_ac_agree, cf_ac_total), "cf_total": int(cf_ac_total),
                             "pairs": ac_total},
            "human_committee": {"agree": hc_agree, "total": hc_total, "rate": _rate(hc_agree, hc_total),
                                "kappa": _kappa(hc_agree, hc_total), "ci": _wilson_ci(hc_agree, hc_total),
                                "cf_rate": _cf_rate_ext(cf_hc_agree, cf_hc_total), "cf_total": int(cf_hc_total)},
            "human_committee_loo": {"agree": hc_loo_agree, "total": hc_loo_total, "rate": _rate(hc_loo_agree, hc_loo_total),
                                    "kappa": _kappa(hc_loo_agree, hc_loo_total), "ci": _wilson_ci(hc_loo_agree, hc_loo_total),
                                    "cf_rate": _cf_rate_ext(cf_hc_loo_agree, cf_hc_loo_total), "cf_total": int(cf_hc_loo_total)},
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
        "tie_impact": {
            "tie_rates": tie_rates,
            "ah_agree": ah_agree, "ah_total": ah_total, "ah_tie": ah_ties,
            "hh_agree": hh_agree, "hh_total": hh_total,
            "ac_agree": ac_agree, "ac_total": ac_total,
            "hc_agree": hc_agree, "hc_total": hc_total,
            "hc_loo_agree": hc_loo_agree, "hc_loo_total": hc_loo_total,
            "coin_flip": {
                "ai_human": {"rate": _cf_rate_ext(cf_ah_agree, cf_ah_total), "total": int(cf_ah_total)},
                "human_human": {"rate": _cf_rate_ext(cf_hh_agree, cf_hh_total), "total": int(cf_hh_total)},
                "ai_committee": {"rate": _cf_rate_ext(cf_ac_agree, cf_ac_total), "total": int(cf_ac_total)},
                "human_committee": {"rate": _cf_rate_ext(cf_hc_agree, cf_hc_total), "total": int(cf_hc_total)},
                "human_committee_loo": {"rate": _cf_rate_ext(cf_hc_loo_agree, cf_hc_loo_total), "total": int(cf_hc_loo_total)},
                "ai_tier": {"rate": _cf_rate_ext(cf_tier_ai_agree, cf_tier_ai_total), "total": int(cf_tier_ai_total)},
                "ai_human_kappa": _kappa(int(cf_ah_agree), int(cf_ah_total)),
                "total_pairs": len(controlled_pairs_cf),
            },
        },
        "bt_correlation": bt_results,
    }


def _dataset_name(ds_id):
    names = {
        "iclr-codegen": "ICLR Code Generation",
        "iclr-fairness": "ICLR Fairness",
        "iclr-llm": "ICLR LLMs",
        "iclr-molecules": "ICLR Molecules",
        "iclr-optimization": "ICLR Optimization",
        "iclr-ot": "ICLR Optimal Transport",
        "iclr-pdes": "ICLR PDEs & Dynamical Systems",
        "iclr-protein": "ICLR Protein Science",
    }
    return names.get(ds_id, ds_id)


def _pool_datasets(per_dataset):
    """Pool metrics across datasets (sum raw counts, then compute rates)."""

    # Sum raw pairwise counts
    pw_keys = ["ai_human", "human_human", "ai_committee", "human_committee", "human_committee_loo"]
    pooled_pw = {}
    for key in pw_keys:
        total_agree = sum(d["pairwise"][key]["agree"] for d in per_dataset if key in d["pairwise"])
        total_total = sum(d["pairwise"][key]["total"] for d in per_dataset if key in d["pairwise"])
        total_cf_total = sum(d["pairwise"][key].get("cf_total", 0) for d in per_dataset if key in d["pairwise"])
        cf_agree_sum = sum(
            d["pairwise"][key]["cf_rate"] * d["pairwise"][key].get("cf_total", 0) / 100
            for d in per_dataset if key in d["pairwise"] and d["pairwise"][key].get("cf_rate") is not None
        )
        pooled_pw[key] = {
            "agree": total_agree, "total": total_total,
            "rate": _rate(total_agree, total_total),
            "kappa": safe_round((total_agree / total_total - 0.5) / 0.5) if total_total else None,
            "ci": _wilson_ci(total_agree, total_total),
            "cf_rate": round(cf_agree_sum / total_cf_total * 100, 1) if total_cf_total else None,
            "cf_total": total_cf_total,
        }
        if key == "ai_committee":
            pooled_pw[key]["pairs"] = total_total

    # Pool tier accuracy
    ta_ai_agree = sum(d["tier_accuracy"]["ai_agree"] for d in per_dataset)
    ta_ai_total = sum(d["tier_accuracy"]["ai_total"] for d in per_dataset)
    ta_hh_agree = sum(d["tier_accuracy"]["hh_agree"] for d in per_dataset)
    ta_hh_total = sum(d["tier_accuracy"]["hh_total"] for d in per_dataset)
    cf_ta_ai_total = sum(d["tier_accuracy"]["cf_ai_total"] for d in per_dataset)
    cf_ta_hh_total = sum(d["tier_accuracy"]["cf_hh_total"] for d in per_dataset)
    cf_ta_ai_agree = sum(
        d["tier_accuracy"]["cf_ai_rate"] * d["tier_accuracy"]["cf_ai_total"] / 100
        for d in per_dataset if d["tier_accuracy"]["cf_ai_rate"] is not None
    )
    cf_ta_hh_agree = sum(
        d["tier_accuracy"]["cf_hh_rate"] * d["tier_accuracy"]["cf_hh_total"] / 100
        for d in per_dataset if d["tier_accuracy"]["cf_hh_rate"] is not None
    )

    pooled_tier = {
        "ai_agree": ta_ai_agree, "ai_total": ta_ai_total,
        "ai_rate": _rate(ta_ai_agree, ta_ai_total),
        "hh_agree": ta_hh_agree, "hh_total": ta_hh_total,
        "hh_rate": _rate(ta_hh_agree, ta_hh_total),
        "cf_ai_rate": round(cf_ta_ai_agree / cf_ta_ai_total * 100, 1) if cf_ta_ai_total else None,
        "cf_hh_rate": round(cf_ta_hh_agree / cf_ta_hh_total * 100, 1) if cf_ta_hh_total else None,
        "cf_ai_total": cf_ta_ai_total,
        "cf_hh_total": cf_ta_hh_total,
        "tier_same_count": sum(d["tier_accuracy"]["tier_same_count"] for d in per_dataset),
    }

    # Pool tie rates (weighted by CF pair count)
    total_cf = sum(d["controlled_pairs_cf"] for d in per_dataset)
    pooled_tie_rates = {}
    for tr_key in ["ah", "hh", "ac", "hc", "hc_loo", "tier_ai", "tier_hh"]:
        numerator = sum(d["tie_impact"]["tie_rates"].get(tr_key, 0) * d["controlled_pairs_cf"] for d in per_dataset)
        pooled_tie_rates[tr_key] = round(numerator / total_cf, 1) if total_cf else 0

    # Pool coin_flip (match old format: plain float rates, not dicts)
    cf_keys = ["ai_human", "human_human", "ai_committee", "human_committee", "human_committee_loo"]
    pooled_cf = {}
    for ck in cf_keys:
        total_cf_pairs = sum(d["tie_impact"]["coin_flip"].get(ck, {}).get("total", 0) for d in per_dataset)
        total_cf_agree = sum(
            d["tie_impact"]["coin_flip"].get(ck, {}).get("rate", 0) * d["tie_impact"]["coin_flip"].get(ck, {}).get("total", 0) / 100
            for d in per_dataset if d["tie_impact"]["coin_flip"].get(ck, {}).get("rate") is not None
        )
        pooled_cf[ck] = round(total_cf_agree / total_cf_pairs * 100, 1) if total_cf_pairs else None
    # Kappa and total_pairs
    ah_cf_total_p = sum(d["tie_impact"]["coin_flip"].get("ai_human", {}).get("total", 0) for d in per_dataset)
    ah_cf_agree_p = (pooled_cf.get("ai_human", 0) or 0) * ah_cf_total_p / 100 if ah_cf_total_p else 0
    pooled_cf["ai_human_kappa"] = round((ah_cf_agree_p / ah_cf_total_p - 0.5) / 0.5, 4) if ah_cf_total_p else None
    pooled_cf["total_pairs"] = sum(d["controlled_pairs_cf"] for d in per_dataset)

    # Pool tie_impact raw counts
    pooled_ti_raw = {}
    for key in ["ah_agree", "ah_total", "ah_tie", "hh_agree", "hh_total",
                "ac_agree", "ac_total", "hc_agree", "hc_total", "hc_loo_agree", "hc_loo_total"]:
        pooled_ti_raw[key] = sum(d["tie_impact"].get(key, 0) for d in per_dataset)

    # Pool BT correlations (average across datasets that have them)
    bt_pooled = {}
    for bt_key in ["committee", "individual", "indiv_vs_comm", "vs_avg_rating",
                    "avg_expert_vs_ai", "avg_expert_vs_comm", "avg_expert_vs_indiv",
                    "avg_expert_vs_loo", "avg_expert_vs_loo_avg", "avg_expert_vs_loo_indiv",
                    "avg_expert_vs_tier"]:
        rhos = [d["bt_correlation"].get(bt_key, {}).get("spearman_rho")
                for d in per_dataset if d["bt_correlation"].get(bt_key, {}).get("spearman_rho") is not None]
        taus = [d["bt_correlation"].get(bt_key, {}).get("kendall_tau")
                for d in per_dataset if d["bt_correlation"].get(bt_key, {}).get("kendall_tau") is not None]
        bt_pooled[bt_key] = {
            "spearman_rho": safe_round(float(np.mean(rhos))) if rhos else None,
            "kendall_tau": safe_round(float(np.mean(taus))) if taus else None,
        }
    # Scalar correlations
    for scalar_key in ["vs_tier_rho", "vs_tier_tau", "vs_avg_rating_rho"]:
        vals = [d["bt_correlation"].get(scalar_key) for d in per_dataset if d["bt_correlation"].get(scalar_key) is not None]
        bt_pooled[scalar_key] = safe_round(float(np.mean(vals))) if vals else None

    # Concordance values for header cards
    ah_agree_total = pooled_pw["ai_human"]["agree"]
    ah_total_total = pooled_pw["ai_human"]["total"]
    ah_cf_total = pooled_pw["ai_human"]["cf_total"]
    ah_cf_agree = (pooled_pw["ai_human"]["cf_rate"] or 0) * ah_cf_total / 100 if ah_cf_total else 0
    ai_h_concordance = safe_round(ah_agree_total / ah_total_total) if ah_total_total else None
    ai_h_cf_concordance = safe_round(ah_cf_agree / ah_cf_total) if ah_cf_total else None

    return {
        "pairwise": pooled_pw,
        "tier_accuracy": pooled_tier,
        "ai_h_concordance": ai_h_concordance,
        "ai_h_cf_concordance": ai_h_cf_concordance,
        "tie_impact": {
            "tie_rates": pooled_tie_rates,
            "coin_flip": pooled_cf,
            **pooled_ti_raw,
        },
        "bt_correlation": bt_pooled,
    }
