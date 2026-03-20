"""
Single-Item Human vs AI Agreement Benchmark

Same methodology as the pairwise benchmark (human_ai_benchmark.py), but applied
to datasets where AI also produces per-paper scores (single_item_score) rather
than forced-choice pairwise verdicts.

Key difference: here BOTH humans and AI produce numerical scores, so AI can also
tie (two papers with the same score). This makes the comparison more symmetric.
"""

import math
import numpy as np
from scipy import stats as scipy_stats
from collections import defaultdict, Counter
from fastapi import APIRouter, Query

from core.config import db, logger
from routers.validation_utils import (
    collect_all, build_expert_ratings, safe_round, norm_tier, TIER_ORDER,
    COMPARATIVE_GT_DATASETS, STANDALONE_GT_DATASETS,
)
from services.ranking import compute_leaderboard_async as compute_leaderboard

router = APIRouter(prefix="/api/validation")

_si_benchmark_cache = {"comp": {"data": None}, "stan": {"data": None}}

TIER_SCORE = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _cohens_kappa(agree, total):
    if total == 0:
        return 0.0
    p_o = agree / total
    p_e = 0.5
    if p_e >= 1.0:
        return 0.0
    return (p_o - p_e) / (1 - p_e)


def _wilson_ci(agree, total, z=1.96):
    if total == 0:
        return [0, 0]
    p = agree / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * (p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5 / denom
    return [round((center - spread) * 100, 1), round((center + spread) * 100, 1)]


def _inter_rater_pairwise(expert_ratings: dict):
    """Same as pairwise benchmark: concordance from paper pairs, ties excluded."""
    experts = list(expert_ratings.keys())
    if len(experts) < 2:
        return None, 0, 0, {}

    concordance_rates = []
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
            concordant = discordant = tied = 0
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
            if nontie >= 5:
                concordance_rates.append(concordant / nontie)
                total_reviewer_pairs += 1

    if not concordance_rates:
        return None, len(experts), 0, {}

    avg_concordance = float(np.mean(concordance_rates))
    rho = math.sin(math.pi * (avg_concordance - 0.5))

    tie_stats = {
        "concordant": total_concordant,
        "discordant": total_discordant,
        "tied_excluded": total_tied,
        "tie_fraction": round(total_tied / max(total_concordant + total_discordant + total_tied, 1), 4),
        "concordance_rate": round(avg_concordance, 4),
    }
    return float(rho), len(experts), total_reviewer_pairs, tie_stats


def _thurstonian_ceiling(rho, score_gaps):
    if rho is None or rho <= 0:
        return {"overall": 50.0, "note": "rho <= 0, ceiling is chance"}
    if not score_gaps:
        return {"overall": 50.0, "note": "no score gaps available"}
    var_q = float(np.var(score_gaps)) if len(score_gaps) > 1 else 1.0
    if var_q == 0:
        var_q = 1.0
    sigma_sq = var_q * (1 / rho - 1)
    if sigma_sq <= 0:
        sigma_sq = 0.01
    ceiling_rates = []
    for dq in score_gaps:
        if dq == 0:
            ceiling_rates.append(0.5)
            continue
        z = abs(dq) / math.sqrt(2 * sigma_sq)
        p_correct = _phi(z)
        ceiling_rates.append(p_correct ** 2 + (1 - p_correct) ** 2)
    return {
        "overall": round(float(np.mean(ceiling_rates)) * 100, 1),
        "rho_used": round(rho, 4),
    }


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


async def _compute_si_dataset_benchmark(dataset_id: str, require_pw: bool = False):
    """Compute benchmark for a single dataset using single-item AI scores."""
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id, "single_item_score": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "evaluations": 1, "decision": 1,
         "h1_avg_rating": 1, "single_item_score": 1}
    ).to_list(5000)

    # Need papers with both human evaluations and AI scores
    papers = [p for p in papers if p.get("evaluations") and p.get("single_item_score") is not None]

    # For fair comparison with PW benchmark, restrict to papers that appear in PW matches
    if require_pw and papers:
        from routers.validation_utils import build_content_mode_filter
        PREFERRED_MODES = ["abstract_plus_summary:opus46", "abstract_plus_summary:thinking", "abstract_plus_summary"]
        pw_paper_ids = set()
        for mode in PREFERRED_MODES:
            mode_filter = build_content_mode_filter(mode)
            pw_raw = await collect_all(db.validation_matches.find(
                {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}, **mode_filter},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1}
            ))
            if len(pw_raw) >= 20:
                for m in pw_raw:
                    pw_paper_ids.add(m["paper1_id"])
                    pw_paper_ids.add(m["paper2_id"])
                break
        if pw_paper_ids:
            papers = [p for p in papers if p["id"] in pw_paper_ids]
    if len(papers) < 10:
        return None

    papers_by_id = {p["id"]: p for p in papers}
    expert_ratings = build_expert_ratings(papers)
    experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}
    if len(experts_with_data) < 2:
        return None

    # AI "ratings" from single-item scores
    ai_ratings = {p["id"]: p["single_item_score"] for p in papers if p.get("single_item_score") is not None}

    # --- Layer 1: Inter-rater concordance (human-human) ---
    rho, n_experts, n_rater_pairs, tie_stats = _inter_rater_pairwise(experts_with_data)

    # --- Build pairwise preferences ---
    # Human expert preferences (non-tie)
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

    # Expert majority vote
    expert_majority = {}
    for pair, votes in expert_pair_prefs.items():
        if len(votes) < 2:
            continue
        c = Counter(votes.values())
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            expert_majority[pair] = best

    # AI pairwise preferences from single-item scores
    ai_pair_prefs = {}
    ai_paper_ids = sorted(ai_ratings.keys())
    for i in range(len(ai_paper_ids)):
        for j in range(i + 1, len(ai_paper_ids)):
            a, b = ai_paper_ids[i], ai_paper_ids[j]
            pair = tuple(sorted([a, b]))
            sa, sb = ai_ratings[a], ai_ratings[b]
            if sa != sb:
                ai_pair_prefs[pair] = a if sa > sb else b
            # else: AI tie — excluded from ai_pair_prefs

    # Controlled set: pairs with both human prefs AND AI prefs (non-tie for both)
    controlled_pairs = set(expert_pair_prefs.keys()) & set(ai_pair_prefs.keys())
    controlled_pairs = {p for p in controlled_pairs if len(expert_pair_prefs[p]) >= 2}

    if len(controlled_pairs) < 10:
        return None

    # Score gaps for Thurstonian ceiling
    avg_human = {}
    all_ratings = defaultdict(list)
    for exp, ratings in experts_with_data.items():
        for pid, val in ratings.items():
            all_ratings[pid].append(val)
    avg_human = {pid: sum(vals) / len(vals) for pid, vals in all_ratings.items() if vals}

    controlled_score_gaps = []
    for pair in controlled_pairs:
        s1 = avg_human.get(pair[0])
        s2 = avg_human.get(pair[1])
        if s1 is not None and s2 is not None:
            controlled_score_gaps.append(s1 - s2)
    ceiling = _thurstonian_ceiling(rho, controlled_score_gaps) if rho and controlled_score_gaps else None

    # --- Pairwise agreement ---
    hh_agree = hh_total = 0
    for pair in controlled_pairs:
        voters = list(expert_pair_prefs[pair].values())
        for i in range(len(voters)):
            for j in range(i + 1, len(voters)):
                hh_total += 1
                if voters[i] == voters[j]:
                    hh_agree += 1

    hc_agree = hc_total = 0
    for pair in controlled_pairs:
        if pair not in expert_majority:
            continue
        for exp, winner in expert_pair_prefs[pair].items():
            hc_total += 1
            if winner == expert_majority[pair]:
                hc_agree += 1

    hc_loo_agree = hc_loo_total = 0
    for pair in controlled_pairs:
        votes = expert_pair_prefs[pair]
        if len(votes) < 3:
            continue
        for held_out_exp, held_out_winner in votes.items():
            others = [w for e, w in votes.items() if e != held_out_exp]
            if len(others) < 2:
                continue
            c = Counter(others)
            best, n = c.most_common(1)[0]
            if n <= len(others) / 2:
                continue
            hc_loo_total += 1
            if held_out_winner == best:
                hc_loo_agree += 1

    ah_agree = ah_total = 0
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            ah_total += 1
            if ai_pair_prefs[pair] == winner:
                ah_agree += 1

    ac_agree = ac_total = 0
    for pair in controlled_pairs:
        if pair not in expert_majority:
            continue
        ac_total += 1
        if ai_pair_prefs[pair] == expert_majority[pair]:
            ac_agree += 1

    # --- AI-Human concordance (per-expert average) ---
    ai_h_per_expert = defaultdict(lambda: [0, 0])
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            ai_h_per_expert[exp][1] += 1
            if ai_pair_prefs[pair] == winner:
                ai_h_per_expert[exp][0] += 1
    ai_h_conc_rates = [a / t for a, t in ai_h_per_expert.values() if t >= 5]
    ai_h_concordance = float(np.mean(ai_h_conc_rates)) if ai_h_conc_rates else None
    ai_h_rho = math.sin(math.pi * (ai_h_concordance - 0.5)) if ai_h_concordance else None

    # --- Tie impact ---
    hh_tie_one = hh_tie_both = ah_tie = hc_loo_tie = 0
    for pair in controlled_pairs:
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
                ah_tie += 1
        votes = expert_pair_prefs.get(pair, {})
        for _, has_pref in experts_for_pair:
            if has_pref:
                continue
            others = [w for e, w in votes.items()]
            if len(others) >= 2:
                c = Counter(others)
                best, n = c.most_common(1)[0]
                if n > len(others) / 2:
                    hc_loo_tie += 1

    # Count AI ties separately (pairs where AI gave same score)
    ai_tie_count = 0
    for i in range(len(ai_paper_ids)):
        for j in range(i + 1, len(ai_paper_ids)):
            a, b = ai_paper_ids[i], ai_paper_ids[j]
            if ai_ratings[a] == ai_ratings[b]:
                ai_tie_count += 1

    # --- Difficulty stratification ---
    difficulty_stats = {level: {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0],
                                "n_pairs": 0, "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_loo_tie": 0}
                        for level in ["easy", "medium", "hard"]}

    for pair in controlled_pairs:
        diff = _classify_difficulty(pair[0], pair[1], papers_by_id)
        if diff is None:
            continue
        ds = difficulty_stats[diff]
        ds["n_pairs"] += 1

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
        votes_d = expert_pair_prefs.get(pair, {})
        for _, has_pref in experts_for_pair_d:
            if has_pref:
                continue
            others = [w for e, w in votes_d.items()]
            if len(others) >= 2:
                c = Counter(others)
                best, n = c.most_common(1)[0]
                if n > len(others) / 2:
                    ds["hc_loo_tie"] += 1

        voters = list(expert_pair_prefs[pair].values())
        for i in range(len(voters)):
            for j in range(i + 1, len(voters)):
                ds["hh"][1] += 1
                if voters[i] == voters[j]:
                    ds["hh"][0] += 1
        if pair in expert_majority:
            for exp, winner in expert_pair_prefs[pair].items():
                ds["hc"][1] += 1
                if winner == expert_majority[pair]:
                    ds["hc"][0] += 1
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
        for exp, winner in expert_pair_prefs[pair].items():
            ds["ah"][1] += 1
            if ai_pair_prefs[pair] == winner:
                ds["ah"][0] += 1
        if pair in expert_majority:
            ds["ac"][1] += 1
            if ai_pair_prefs[pair] == expert_majority[pair]:
                ds["ac"][0] += 1

    # --- BT rank correlation ---
    human_committee_matches = []
    for pair in controlled_pairs:
        if pair in expert_majority:
            human_committee_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": expert_majority[pair],
                "completed": True, "failed": False,
            })
    human_individual_matches = []
    for pair in controlled_pairs:
        for exp, winner in expert_pair_prefs[pair].items():
            human_individual_matches.append({
                "paper1_id": pair[0], "paper2_id": pair[1],
                "winner_id": winner,
                "completed": True, "failed": False,
            })
    ai_matches_ctrl = [
        {"paper1_id": p[0], "paper2_id": p[1], "winner_id": ai_pair_prefs[p],
         "completed": True, "failed": False}
        for p in controlled_pairs
    ]

    ctrl_paper_ids = set()
    for p in controlled_pairs:
        ctrl_paper_ids.add(p[0])
        ctrl_paper_ids.add(p[1])
    ctrl_papers = [papers_by_id[pid] for pid in ctrl_paper_ids if pid in papers_by_id]

    async def _bt_correlate(h_matches, a_matches):
        if len(h_matches) < 10 or len(a_matches) < 10:
            return None, None
        h_lb = await compute_leaderboard(ctrl_papers, h_matches)
        a_lb = await compute_leaderboard(ctrl_papers, a_matches)
        h_rank = {e["id"]: e["rank"] for e in h_lb}
        a_rank = {e["id"]: e["rank"] for e in a_lb}
        shared = sorted(set(h_rank.keys()) & set(a_rank.keys()))
        if len(shared) < 5:
            return None, None
        sp, _ = scipy_stats.spearmanr([h_rank[pid] for pid in shared],
                                       [a_rank[pid] for pid in shared])
        kt, _ = scipy_stats.kendalltau([h_rank[pid] for pid in shared],
                                        [a_rank[pid] for pid in shared])
        rho_v = float(sp) if not np.isnan(sp) else None
        tau_v = float(kt) if not np.isnan(kt) else None
        return rho_v, tau_v

    bt_comm_rho, bt_comm_tau = await _bt_correlate(human_committee_matches, ai_matches_ctrl)
    bt_indiv_rho, bt_indiv_tau = await _bt_correlate(human_individual_matches, ai_matches_ctrl)
    bt_ivc_rho, bt_ivc_tau = await _bt_correlate(human_individual_matches, human_committee_matches)

    # Direct ranking: AI BT vs h1_avg_rating
    bt_vs_avg_rho = None
    ai_lb_rank = {}
    if len(ai_matches_ctrl) >= 10:
        ai_lb_rank = {e["id"]: e["rank"] for e in await compute_leaderboard(ctrl_papers, ai_matches_ctrl)}
    avg_rating_map = {p["id"]: p["h1_avg_rating"] for p in papers
                      if p.get("h1_avg_rating") is not None and p["id"] in ctrl_paper_ids}
    shared_avg = sorted(set(ai_lb_rank.keys()) & set(avg_rating_map.keys()))
    if len(shared_avg) >= 5:
        sp, _ = scipy_stats.spearmanr([ai_lb_rank[p] for p in shared_avg],
                                       [-avg_rating_map[p] for p in shared_avg])
        if not np.isnan(sp):
            bt_vs_avg_rho = float(sp)

    # Per-expert BT correlations
    comm_rank = {}
    if len(human_committee_matches) >= 10:
        comm_rank = {e["id"]: e["rank"] for e in await compute_leaderboard(ctrl_papers, human_committee_matches)}
    indiv_rank_map = {}
    if len(human_individual_matches) >= 10:
        indiv_rank_map = {e["id"]: e["rank"] for e in await compute_leaderboard(ctrl_papers, human_individual_matches)}

    evc_rhos, evi_rhos = [], []
    for exp in experts_with_data:
        exp_matches = [{"paper1_id": pair[0], "paper2_id": pair[1],
                        "winner_id": expert_pair_prefs[pair][exp],
                        "completed": True, "failed": False}
                       for pair in controlled_pairs if exp in expert_pair_prefs.get(pair, {})]
        if len(exp_matches) < 10:
            continue
        exp_rank = {e["id"]: e["rank"] for e in await compute_leaderboard(ctrl_papers, exp_matches)}
        for ref_rank, rho_list in [(comm_rank, evc_rhos), (indiv_rank_map, evi_rhos)]:
            if not ref_rank:
                continue
            shared = sorted(set(exp_rank.keys()) & set(ref_rank.keys()))
            if len(shared) < 5:
                continue
            sp, _ = scipy_stats.spearmanr([exp_rank[p] for p in shared], [ref_rank[p] for p in shared])
            if not np.isnan(sp):
                rho_list.append(float(sp))

    avg_evc_rho = float(np.mean(evc_rhos)) if evc_rhos else None
    avg_evi_rho = float(np.mean(evi_rhos)) if evi_rhos else None

    # --- Format output ---
    hh_kappa = _cohens_kappa(hh_agree, hh_total)
    ah_kappa = _cohens_kappa(ah_agree, ah_total)

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    def _format_difficulty():
        result = {}
        for level in ["easy", "medium", "hard"]:
            s = difficulty_stats[level]
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
                "hh_cf": hh_cf, "ah_cf": ah_cf, "hc_loo_cf": hc_loo_cf,
                "hh_tie_one": hh_t1, "hh_tie_both": hh_t2, "ah_tie": ah_ti, "hc_loo_tie": hc_loo_ti,
            }
        return result

    return {
        "dataset_id": dataset_id,
        "n_papers": len(papers),
        "n_experts": len(experts_with_data),
        "controlled_pairs": len(controlled_pairs),
        "inter_rater_rho": safe_round(rho) if rho else None,
        "ai_h_concordance": safe_round(ai_h_concordance) if ai_h_concordance else None,
        "ai_h_rho": safe_round(ai_h_rho) if ai_h_rho else None,
        "tie_stats": tie_stats,
        "ai_tie_count": ai_tie_count,
        "ai_total_pairs": len(ai_paper_ids) * (len(ai_paper_ids) - 1) // 2,
        "tie_impact": {
            "hh_agree": hh_agree, "hh_total": hh_total,
            "hh_tie_one": hh_tie_one, "hh_tie_both": hh_tie_both,
            "ah_agree": ah_agree, "ah_total": ah_total, "ah_tie": ah_tie,
            "hc_loo_agree": hc_loo_agree, "hc_loo_total": hc_loo_total, "hc_loo_tie": hc_loo_tie,
            "ac_agree": ac_agree, "ac_total": ac_total,
        },
        "ceiling": ceiling,
        "pairwise": {
            "human_human": {"agree": hh_agree, "total": hh_total, "rate": _rate(hh_agree, hh_total),
                            "kappa": safe_round(hh_kappa), "ci": _wilson_ci(hh_agree, hh_total)},
            "human_committee": {"agree": hc_agree, "total": hc_total, "rate": _rate(hc_agree, hc_total)},
            "human_committee_loo": {"agree": hc_loo_agree, "total": hc_loo_total, "rate": _rate(hc_loo_agree, hc_loo_total)},
            "ai_human": {"agree": ah_agree, "total": ah_total, "rate": _rate(ah_agree, ah_total),
                         "kappa": safe_round(ah_kappa), "ci": _wilson_ci(ah_agree, ah_total)},
            "ai_committee": {"agree": ac_agree, "total": ac_total, "rate": _rate(ac_agree, ac_total)},
        },
        "by_difficulty": _format_difficulty(),
        "bt_correlation": {
            "committee": {"spearman_rho": safe_round(bt_comm_rho) if bt_comm_rho else None,
                          "kendall_tau": safe_round(bt_comm_tau) if bt_comm_tau else None},
            "individual": {"spearman_rho": safe_round(bt_indiv_rho) if bt_indiv_rho else None,
                           "kendall_tau": safe_round(bt_indiv_tau) if bt_indiv_tau else None},
            "avg_expert_vs_comm": {"spearman_rho": safe_round(avg_evc_rho) if avg_evc_rho else None},
            "avg_expert_vs_indiv": {"spearman_rho": safe_round(avg_evi_rho) if avg_evi_rho else None},
            "n_papers": len(ctrl_paper_ids),
            "vs_avg_rating_rho": safe_round(bt_vs_avg_rho) if bt_vs_avg_rho else None,
        },
    }


def _cf_rate(agree, nontie_total, tie_count):
    total = nontie_total + tie_count
    if total == 0:
        return None
    return round((agree + 0.5 * tie_count) / total * 100, 1)


@router.get("/si-benchmark")
async def si_benchmark(gt_type: str = Query("stan")):
    """Human vs AI benchmark for single-item scoring datasets. gt_type: comp or stan."""
    cache = _si_benchmark_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    if gt_type == "stan":
        from routers.standalone_benchmark import compute_standalone_benchmark
        result = await compute_standalone_benchmark(ai_source="single_item")
    else:
        result = await _compute_si_benchmark(gt_type)
    if result.get("status") == "ok":
        _si_benchmark_cache[gt_type] = {"data": result}
    return result


async def _compute_si_benchmark(gt_type: str = "stan"):
    """Compute full benchmark across datasets with single-item AI scores, filtered by GT type."""
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS
    ds_with_scores = await db.validation_papers.distinct(
        "dataset_id", {"single_item_score": {"$exists": True}}
    )
    ds_with_scores = [d for d in ds_with_scores if d in allowed]
    if not ds_with_scores:
        return {"status": "no_data"}

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(200)
    ds_names = {d["dataset_id"]: d.get("name", d["dataset_id"]) for d in meta_docs}

    per_dataset = []
    pooled = {
        "hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0],
        "inter_rater_rhos": [], "ai_h_concordances": [], "concordance_rates": [], "ceilings": [],
        "bt_comm_rhos": [], "bt_indiv_rhos": [], "bt_evc_rhos": [], "bt_evi_rhos": [],
        "bt_avg_rating_rhos": [],
        "total_pairs": 0,
        "total_papers": 0,
        "tie_concordant": 0, "tie_discordant": 0, "tie_excluded": 0,
        "ti_hh_tie_one": 0, "ti_hh_tie_both": 0, "ti_ah_tie": 0, "ti_hc_loo_tie": 0,
        "ai_tie_total": 0, "ai_pair_total": 0,
        "difficulty": {level: {"hh": [0, 0], "hc": [0, 0], "hc_loo": [0, 0], "ah": [0, 0], "ac": [0, 0],
                               "n_pairs": 0, "hh_tie_one": 0, "hh_tie_both": 0, "ah_tie": 0, "hc_loo_tie": 0}
                       for level in ["easy", "medium", "hard"]},
    }

    # For comp GT, restrict to papers with PW matches too, for fair PW vs SI comparison
    require_pw = (gt_type == "comp")

    for ds_id in ds_with_scores:
        result = await _compute_si_dataset_benchmark(ds_id, require_pw=require_pw)
        if result is None:
            continue

        result["name"] = ds_names.get(ds_id, ds_id)
        per_dataset.append(result)

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
        ts = result.get("tie_stats", {})
        if ts:
            pooled["tie_concordant"] += ts.get("concordant", 0)
            pooled["tie_discordant"] += ts.get("discordant", 0)
            pooled["tie_excluded"] += ts.get("tied_excluded", 0)
            if ts.get("concordance_rate") is not None:
                pooled["concordance_rates"].append(ts["concordance_rate"])
        if result.get("ceiling") and result["ceiling"].get("overall"):
            pooled["ceilings"].append(result["ceiling"]["overall"])
        pooled["ai_tie_total"] += result.get("ai_tie_count", 0)
        pooled["ai_pair_total"] += result.get("ai_total_pairs", 0)

        ti = result.get("tie_impact", {})
        pooled["ti_hh_tie_one"] += ti.get("hh_tie_one", 0)
        pooled["ti_hh_tie_both"] += ti.get("hh_tie_both", 0)
        pooled["ti_ah_tie"] += ti.get("ah_tie", 0)
        pooled["ti_hc_loo_tie"] += ti.get("hc_loo_tie", 0)

        bt = result.get("bt_correlation", {})
        for src, dst in [("committee", "bt_comm_rhos"), ("individual", "bt_indiv_rhos"),
                         ("avg_expert_vs_comm", "bt_evc_rhos"), ("avg_expert_vs_indiv", "bt_evi_rhos")]:
            v = bt.get(src, {}).get("spearman_rho")
            if v is not None:
                pooled[dst].append(v)
        if bt.get("vs_avg_rating_rho") is not None:
            pooled["bt_avg_rating_rhos"].append(bt["vs_avg_rating_rho"])

        for level in ["easy", "medium", "hard"]:
            dl = result.get("by_difficulty", {}).get(level, {})
            for metric in ["hh", "hc", "hc_loo", "ah", "ac"]:
                metric_full = {"hh": "human_human", "hc": "human_committee",
                               "hc_loo": "human_committee_loo",
                               "ah": "ai_human", "ac": "ai_committee"}[metric]
                d = dl.get(metric_full, {})
                pooled["difficulty"][level][metric][0] += int(d.get("rate", 0) * d.get("pairs", 0) / 100)
                pooled["difficulty"][level][metric][1] += d.get("pairs", 0)
            pooled["difficulty"][level]["n_pairs"] += dl.get("n_pairs", 0)
            for tk in ["hh_tie_one", "hh_tie_both", "ah_tie", "hc_loo_tie"]:
                pooled["difficulty"][level][tk] += dl.get(tk, 0)

    if not per_dataset:
        return {"status": "no_data"}

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    # Pooled tie stats
    total_tie_all = pooled["tie_concordant"] + pooled["tie_discordant"] + pooled["tie_excluded"]
    pooled_tie_stats = {
        "concordant": pooled["tie_concordant"],
        "discordant": pooled["tie_discordant"],
        "tied_excluded": pooled["tie_excluded"],
        "tie_fraction": round(pooled["tie_excluded"] / max(total_tie_all, 1), 4),
        "concordance_rate": round(float(np.mean(pooled["concordance_rates"])), 4) if pooled["concordance_rates"] else None,
    }

    ai_h_conc_avg = float(np.mean(pooled["ai_h_concordances"])) if pooled["ai_h_concordances"] else None
    ai_h_rho_avg = math.sin(math.pi * (ai_h_conc_avg - 0.5)) if ai_h_conc_avg else None

    # Tie impact
    hh_a, hh_t = pooled["hh"][0], pooled["hh"][1]
    ah_a, ah_t = pooled["ah"][0], pooled["ah"][1]
    hc_loo_a, hc_loo_t = pooled["hc_loo"][0], pooled["hc_loo"][1]
    ac_a, ac_t = pooled["ac"][0], pooled["ac"][1]

    hh_t1_p = pooled["ti_hh_tie_one"]
    hh_t2_p = pooled["ti_hh_tie_both"]
    ah_tie_p = pooled["ti_ah_tie"]
    hc_loo_tie_p = pooled["ti_hc_loo_tie"]

    def _tie_pct(tie_count, nontie_total):
        total = nontie_total + tie_count
        if total == 0:
            return None
        return round(tie_count / total * 100, 1)

    tie_impact = {
        "coin_flip": {
            "human_human": _cf_rate(hh_a, hh_t, hh_t1_p + hh_t2_p),
            "human_committee_loo": _cf_rate(hc_loo_a, hc_loo_t, hc_loo_tie_p),
            "ai_human": _cf_rate(ah_a, ah_t, ah_tie_p),
            "ai_committee": _rate(ac_a, ac_t) if ac_t > 0 else None,
            "human_committee": None,
            "ai_human_kappa": safe_round(_cohens_kappa(
                int(ah_a + 0.5 * ah_tie_p),
                ah_t + ah_tie_p
            )) if (ah_t + ah_tie_p) > 0 else None,
            "total_pairs": hh_t + hh_t1_p + hh_t2_p,
        },
        "excluded": {
            "hh_rate": _rate(hh_a, hh_t),
            "ah_rate": _rate(ah_a, ah_t),
        },
        "tie_rates": {
            "hh": _tie_pct(hh_t1_p + hh_t2_p, hh_t),
            "ah": _tie_pct(ah_tie_p, ah_t),
            "hc_loo": _tie_pct(hc_loo_tie_p, hc_loo_t),
        },
        "tie_counts": {
            "hh_nontie": hh_t, "hh_one_tie": hh_t1_p, "hh_both_tie": hh_t2_p,
            "ah_nontie": ah_t, "ah_tie": ah_tie_p,
        },
    }

    # Pooled difficulty
    def _format_pooled_difficulty():
        result = {}
        for level in ["easy", "medium", "hard"]:
            s = pooled["difficulty"][level]
            hh_a_l, hh_t_l = s["hh"][0], s["hh"][1]
            ah_a_l, ah_t_l = s["ah"][0], s["ah"][1]
            hc_loo_a_l, hc_loo_t_l = s["hc_loo"][0], s["hc_loo"][1]
            result[level] = {
                "human_human": {"rate": _rate(hh_a_l, hh_t_l), "pairs": hh_t_l},
                "human_committee": {"rate": _rate(s["hc"][0], s["hc"][1]), "pairs": s["hc"][1]},
                "human_committee_loo": {"rate": _rate(hc_loo_a_l, hc_loo_t_l), "pairs": hc_loo_t_l},
                "ai_human": {"rate": _rate(ah_a_l, ah_t_l), "pairs": ah_t_l},
                "ai_committee": {"rate": _rate(s["ac"][0], s["ac"][1]), "pairs": s["ac"][1]},
                "n_pairs": s["n_pairs"],
                "hh_cf": _cf_rate(hh_a_l, hh_t_l, s["hh_tie_one"] + s["hh_tie_both"]),
                "ah_cf": _cf_rate(ah_a_l, ah_t_l, s["ah_tie"]),
                "hc_loo_cf": _cf_rate(hc_loo_a_l, hc_loo_t_l, s["hc_loo_tie"]),
                "hh_tie_rate": round((s["hh_tie_one"] + s["hh_tie_both"]) / max(hh_t_l + s["hh_tie_one"] + s["hh_tie_both"], 1) * 100, 1),
            }
        return result

    def _avg(lst):
        return safe_round(float(np.mean(lst))) if lst else None

    return {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(per_dataset),
        "total_controlled_pairs": pooled["total_pairs"],
        "total_papers": pooled["total_papers"],
        "avg_matches_per_paper": round(2 * pooled["total_pairs"] / max(pooled["total_papers"], 1), 1),
        "pooled": {
            "inter_rater_rho": _avg(pooled["inter_rater_rhos"]),
            "ai_h_concordance": safe_round(ai_h_conc_avg) if ai_h_conc_avg else None,
            "ai_h_rho": safe_round(ai_h_rho_avg) if ai_h_rho_avg else None,
            "tie_stats": pooled_tie_stats,
            "ai_tie_fraction": round(pooled["ai_tie_total"] / max(pooled["ai_pair_total"], 1), 4),
            "theoretical_ceiling": safe_round(float(np.mean(pooled["ceilings"])), 1) if pooled["ceilings"] else None,
            "pairwise": {
                "human_human": {"rate": _rate(pooled["hh"][0], pooled["hh"][1]),
                                "kappa": safe_round(_cohens_kappa(pooled["hh"][0], pooled["hh"][1])),
                                "pairs": pooled["hh"][1]},
                "human_committee": {"rate": _rate(pooled["hc"][0], pooled["hc"][1]),
                                    "pairs": pooled["hc"][1]},
                "human_committee_loo": {"rate": _rate(pooled["hc_loo"][0], pooled["hc_loo"][1]),
                                        "pairs": pooled["hc_loo"][1]},
                "ai_human": {"rate": _rate(pooled["ah"][0], pooled["ah"][1]),
                             "kappa": safe_round(_cohens_kappa(pooled["ah"][0], pooled["ah"][1])),
                             "pairs": pooled["ah"][1]},
                "ai_committee": {"rate": _rate(pooled["ac"][0], pooled["ac"][1]),
                                 "pairs": pooled["ac"][1]},
            },
            "bt_correlation": {
                "committee": {"spearman_rho": _avg(pooled["bt_comm_rhos"])},
                "individual": {"spearman_rho": _avg(pooled["bt_indiv_rhos"])},
                "avg_expert_vs_comm": {"spearman_rho": _avg(pooled["bt_evc_rhos"])},
                "avg_expert_vs_indiv": {"spearman_rho": _avg(pooled["bt_evi_rhos"])},
                "vs_avg_rating_rho": _avg(pooled["bt_avg_rating_rhos"]),
            },
            "by_difficulty": _format_pooled_difficulty(),
            "tie_impact": tie_impact,
        },
        "per_dataset": per_dataset,
    }
