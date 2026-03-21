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
from services.ranking import compute_leaderboard_async as compute_leaderboard
from routers.validation_utils import (
    collect_all, build_expert_ratings, build_content_mode_filter, safe_round,
    PAPER_LIGHT_PROJECTION, norm_tier,
    COMPARATIVE_GT_DATASETS, STANDALONE_GT_DATASETS,
)
from services.ranking import compute_leaderboard_async as compute_leaderboard

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


async def _compute_rank_corrs(ai_rank, papers, gt, label):
    """Compute BT correlation table for a given AI ranking against multiple human GTs."""
    from routers.validation_utils import norm_tier
    TIER_SCORE_MAP = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1}

    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name and ev.get("rating_value") is not None:
                expert_ratings[name][p["id"]] = ev["rating_value"]

    corrs = {}

    # vs Individual aggregate
    human_individual_matches = []
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                if ratings[a] != ratings[b]:
                    winner = a if ratings[a] > ratings[b] else b
                    human_individual_matches.append({"paper1_id": a, "paper2_id": b, "winner_id": winner, "completed": True, "failed": False})

    if len(human_individual_matches) >= 10:
        h_lb = await compute_leaderboard(papers, human_individual_matches)
        h_rank = {e["id"]: e["score"] for e in h_lb}
        shared = sorted(set(ai_rank) & set(h_rank))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in shared], [h_rank[p] for p in shared])
            kt, _ = scipy_stats.kendalltau([ai_rank[p] for p in shared], [h_rank[p] for p in shared])
            corrs["vs_individual"] = {"rho": safe_round(sp), "tau": safe_round(kt), "desc": f"{label} ranking vs all-expert-votes ranking"}

    # vs Avg Rating
    shared_avg = sorted(set(ai_rank) & set(gt))
    if len(shared_avg) >= 5:
        sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in shared_avg], [gt[p] for p in shared_avg])
        corrs["vs_avg_rating"] = {"rho": safe_round(sp), "tau": None, "desc": f"{label} ranking vs average reviewer scores"}

    # vs Majority
    from collections import Counter as _Counter
    pair_votes = defaultdict(list)
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = sorted([pids[i], pids[j]])
                if ratings[pids[i]] != ratings[pids[j]]:
                    winner = pids[i] if ratings[pids[i]] > ratings[pids[j]] else pids[j]
                    pair_votes[(a, b)].append(winner)
    human_majority_matches = []
    for (a, b), votes in pair_votes.items():
        c = _Counter(votes)
        if len(c) == 1 or c.most_common(1)[0][1] > len(votes) / 2:
            human_majority_matches.append({"paper1_id": a, "paper2_id": b, "winner_id": c.most_common(1)[0][0], "completed": True, "failed": False})

    if len(human_majority_matches) >= 10:
        h_lb = await compute_leaderboard(papers, human_majority_matches)
        h_rank = {e["id"]: e["score"] for e in h_lb}
        shared = sorted(set(ai_rank) & set(h_rank))
        if len(shared) >= 5:
            sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in shared], [h_rank[p] for p in shared])
            kt, _ = scipy_stats.kendalltau([ai_rank[p] for p in shared], [h_rank[p] for p in shared])
            corrs["vs_majority"] = {"rho": safe_round(sp), "tau": safe_round(kt), "desc": f"{label} ranking vs majority-vote ranking"}

    # vs Committee (Tier)
    tier_score_map = {}
    for p in papers:
        t = norm_tier(p.get("decision"))
        if t and t in TIER_SCORE_MAP:
            tier_score_map[p["id"]] = TIER_SCORE_MAP[t]
    if len(tier_score_map) >= 5:
        shared_t = sorted(set(ai_rank) & set(tier_score_map))
        if len(shared_t) >= 5:
            sp, _ = scipy_stats.spearmanr([ai_rank[p] for p in shared_t], [tier_score_map[p] for p in shared_t])
            kt, _ = scipy_stats.kendalltau([ai_rank[p] for p in shared_t], [tier_score_map[p] for p in shared_t])
            corrs["vs_committee"] = {"rho": safe_round(sp), "tau": safe_round(kt), "desc": f"{label} ranking vs committee tier decisions"}

    return corrs if corrs else None


async def _compute_unified_dataset(dataset_id, gt_type):
    """Evaluate PW and SI each on their full data against h1_avg_rating GT."""
    papers = await collect_all(db.validation_papers.find(
        {"dataset_id": dataset_id}, PAPER_LIGHT_PROJECTION
    ))
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

    pw_matches_raw = await collect_all(db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": pw_content_mode},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))

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
            lb = await compute_leaderboard(paper_dicts, pw_bt_matches)
            rank_scores = {e["id"]: e["score"] for e in lb}
            shared = sorted(set(rank_scores.keys()) & set(gt.keys()))
            if len(shared) >= 5:
                sp, _ = scipy_stats.spearmanr([rank_scores[p] for p in shared],
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
                        # Match by title since paper IDs may differ between environments
                        cache_papers = ds_data.get("papers", [])
                        title_to_score = {}
                        for p_data in cache_papers:
                            title = p_data.get("title", "").strip()
                            score = p_data.get("ai_score") or p_data.get("single_item_score")
                            if title and score is not None:
                                title_to_score[title] = score
                        title_to_id = {p.get("title", "").strip(): p["id"] for p in papers if p.get("title")}
                        # Exact match first
                        for title, score in title_to_score.items():
                            pid = title_to_id.get(title)
                            if pid and pid in gt:
                                si_scores[pid] = score
                        # Prefix match for truncated titles in precomputed data
                        if len(si_scores) < len(cache_papers) // 2:
                            matched_pids = set(si_scores.keys())
                            for db_title, pid in title_to_id.items():
                                if pid in matched_pids or pid not in gt:
                                    continue
                                for cache_title, score in title_to_score.items():
                                    if db_title.startswith(cache_title) or cache_title.startswith(db_title):
                                        si_scores[pid] = score
                                        matched_pids.add(pid)
                                        break
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

    # --- SI Subscore Average: mean of (significance, rigor, novelty, clarity) ---
    si_sub_scores = {}
    SUB_KEYS = ["significance", "rigor", "novelty", "clarity"]
    # From DB
    for p in papers:
        details = p.get("single_item_details") or {}
        subs = [details.get(k) for k in SUB_KEYS if details.get(k)]
        if len(subs) >= 2 and p["id"] in gt:
            si_sub_scores[p["id"]] = round(sum(subs) / len(subs), 2)
    # Fallback from precomputed cache
    if not si_sub_scores:
        try:
            from routers.validation_experiments import _SINGLE_ITEM_CACHE
            si_cache = _SINGLE_ITEM_CACHE.get("data", {})
            if si_cache.get("status") == "ok":
                for ds_data in si_cache.get("datasets", []):
                    if ds_data.get("dataset_id") == dataset_id:
                        title_to_id = {p.get("title", "").strip(): p["id"] for p in papers if p.get("title")}
                        for p_data in ds_data.get("papers", []):
                            details = p_data.get("details") or {}
                            subs = [details.get(k) for k in SUB_KEYS if details.get(k)]
                            if len(subs) < 2: continue
                            avg = round(sum(subs) / len(subs), 2)
                            title = p_data.get("title", "").strip()
                            pid = title_to_id.get(title)
                            if not pid:
                                for db_t, db_pid in title_to_id.items():
                                    if db_t.startswith(title) or title.startswith(db_t):
                                        pid = db_pid; break
                            if pid and pid in gt:
                                si_sub_scores[pid] = avg
                        break
        except Exception:
            pass

    si_sub_correct = si_sub_total = 0
    si_sub_diff = {lvl: [0, 0, 0] for lvl in ["easy", "medium", "hard"]}
    si_sub_ids = sorted(set(si_sub_scores.keys()) & set(gt.keys()))
    for i in range(len(si_sub_ids)):
        for j in range(i + 1, len(si_sub_ids)):
            a, b = si_sub_ids[i], si_sub_ids[j]
            if gt[a] == gt[b] or si_sub_scores[a] == si_sub_scores[b]:
                continue
            si_sub_total += 1
            human_winner = a if gt[a] > gt[b] else b
            si_sub_winner = a if si_sub_scores[a] > si_sub_scores[b] else b
            if si_sub_winner == human_winner:
                si_sub_correct += 1
            diff = _classify_difficulty(a, b, papers_by_id)
            if diff:
                si_sub_diff[diff][1] += 1; si_sub_diff[diff][2] += 1
                if si_sub_winner == human_winner:
                    si_sub_diff[diff][0] += 1

    si_sub_rho = None
    if len(si_sub_ids) >= 5:
        sp, _ = scipy_stats.spearmanr([si_sub_scores[p] for p in si_sub_ids], [gt[p] for p in si_sub_ids])
        if not np.isnan(sp):
            si_sub_rho = safe_round(float(sp))

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
    int_pw_correct = int_si_correct = int_si_sub_correct = int_total = 0
    int_gaps = []
    int_diff = {"easy": {"pw": [0, 0], "si": [0, 0], "si_sub": [0, 0]},
                "medium": {"pw": [0, 0], "si": [0, 0], "si_sub": [0, 0]},
                "hard": {"pw": [0, 0], "si": [0, 0], "si_sub": [0, 0]}}
    # Build SI sub verdict on intersection pairs
    si_sub_verdict = {}
    for pair in common_pairs:
        a, b = pair
        if a in si_sub_scores and b in si_sub_scores and si_sub_scores[a] != si_sub_scores[b]:
            si_sub_verdict[pair] = a if si_sub_scores[a] > si_sub_scores[b] else b
    for pair in common_pairs:
        a, b = pair
        if a not in gt or b not in gt or gt[a] == gt[b]:
            continue
        int_total += 1
        human_winner = a if gt[a] > gt[b] else b
        int_gaps.append(abs(gt[a] - gt[b]))
        pw_ok = pw_verdict[pair] == human_winner
        si_ok = si_verdict[pair] == human_winner
        si_sub_ok = pair in si_sub_verdict and si_sub_verdict[pair] == human_winner
        if pw_ok:
            int_pw_correct += 1
        if si_ok:
            int_si_correct += 1
        if si_sub_ok:
            int_si_sub_correct += 1
        diff = _classify_difficulty(a, b, papers_by_id)
        if diff:
            int_diff[diff]["pw"][1] += 1
            int_diff[diff]["si"][1] += 1
            int_diff[diff]["si_sub"][1] += 1
            if pw_ok: int_diff[diff]["pw"][0] += 1
            if si_ok: int_diff[diff]["si"][0] += 1
            if si_sub_ok: int_diff[diff]["si_sub"][0] += 1

    # --- Ranking Correlations: compute from the PW/SI matches loaded for this page ---
    pw_rank_corrs = None
    si_rank_corrs = None

    # PW correlations from pairwise matches
    if len(pw_matches_raw) >= 10:
        pw_match_dicts = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"], "winner_id": m["winner_id"], "completed": True, "failed": False} for m in pw_matches_raw if m.get("winner_id")]
        if len(pw_match_dicts) >= 10:
            pw_lb = await compute_leaderboard(papers, pw_match_dicts)
            pw_rank = {e["id"]: e["score"] for e in pw_lb}
            pw_rank_corrs = await _compute_rank_corrs(pw_rank, papers, gt, "AI")

        # SI correlations: compute from SI score-derived matches
        si_matches_for_bt = []
        si_ids_list = sorted(si_scores.keys())
        for i in range(len(si_ids_list)):
            for j in range(i + 1, len(si_ids_list)):
                a, b = si_ids_list[i], si_ids_list[j]
                if si_scores[a] != si_scores[b]:
                    winner = a if si_scores[a] > si_scores[b] else b
                    si_matches_for_bt.append({"paper1_id": a, "paper2_id": b, "winner_id": winner, "completed": True, "failed": False})

        if len(si_matches_for_bt) >= 10:
            si_lb = await compute_leaderboard(papers, si_matches_for_bt)
            si_rank = {e["id"]: e["score"] for e in si_lb}
            si_rank_corrs = await _compute_rank_corrs(si_rank, papers, gt, "SI")

        # SI Sub-Avg BT correlations
        si_sub_rank_corrs = None
        si_sub_ids_list = sorted(si_sub_scores.keys())
        si_sub_matches_for_bt = []
        for i in range(len(si_sub_ids_list)):
            for j in range(i + 1, len(si_sub_ids_list)):
                a, b = si_sub_ids_list[i], si_sub_ids_list[j]
                if si_sub_scores[a] != si_sub_scores[b]:
                    winner = a if si_sub_scores[a] > si_sub_scores[b] else b
                    si_sub_matches_for_bt.append({"paper1_id": a, "paper2_id": b, "winner_id": winner, "completed": True, "failed": False})
        if len(si_sub_matches_for_bt) >= 10:
            si_sub_lb = await compute_leaderboard(papers, si_sub_matches_for_bt)
            si_sub_rank = {e["id"]: e["score"] for e in si_sub_lb}
            si_sub_rank_corrs = await _compute_rank_corrs(si_sub_rank, papers, gt, "SI Avg")

    return {
        "dataset_id": dataset_id,
        "n_papers": len(gt),
        "pw": {
            "accuracy": _rate(pw_correct, pw_total),
            "correct": pw_correct, "total": pw_total,
            "pairs": len(pw_pairs_seen),
            "ranking_rho": pw_rho,
            "ranking_correlations": pw_rank_corrs,
            "mode": pw_content_mode,
            "by_difficulty": {lvl: {"rate": _rate(v[0], v[1]), "n_pairs": v[2]} for lvl, v in pw_diff.items()},
        },
        "si": {
            "accuracy": _rate(si_correct, si_total),
            "correct": si_correct, "total": si_total,
            "pairs": si_total,
            "n_scored": len(si_scores),
            "ranking_rho": si_rho,
            "ranking_correlations": si_rank_corrs,
            "by_difficulty": {lvl: {"rate": _rate(v[0], v[1]), "n_pairs": v[2]} for lvl, v in si_diff.items()},
        },
        "si_sub": {
            "accuracy": _rate(si_sub_correct, si_sub_total),
            "correct": si_sub_correct, "total": si_sub_total,
            "n_scored": len(si_sub_scores),
            "ranking_rho": si_sub_rho,
            "ranking_correlations": si_sub_rank_corrs,
            "by_difficulty": {lvl: {"rate": _rate(v[0], v[1]), "n_pairs": v[2]} for lvl, v in si_sub_diff.items()},
        },
        "intersection": {
            "pw_accuracy": _rate(int_pw_correct, int_total),
            "si_accuracy": _rate(int_si_correct, int_total),
            "si_sub_accuracy": _rate(int_si_sub_correct, int_total),
            "pairs": int_total,
            "avg_h1_gap": round(float(np.mean(int_gaps)), 2) if int_gaps else 0,
            "by_difficulty": {
                lvl: {
                    "pw_rate": _rate(int_diff[lvl]["pw"][0], int_diff[lvl]["pw"][1]),
                    "si_rate": _rate(int_diff[lvl]["si"][0], int_diff[lvl]["si"][1]),
                    "si_sub_rate": _rate(int_diff[lvl]["si_sub"][0], int_diff[lvl]["si_sub"][1]),
                    "pairs": int_diff[lvl]["pw"][1],
                }
                for lvl in ["easy", "medium", "hard"]
            },
        },
    }


@router.get("/unified-benchmark")
async def unified_benchmark(gt_type: str = Query("comp")):
    """Unified PW vs SI benchmark — served from precomputed cache only."""
    cache = _unified_cache.get(gt_type, {})
    if cache.get("data"):
        return cache["data"]
    return {"status": "no_data", "message": "Unified benchmark not precomputed. Run admin precompute-experiments."}


async def _compute_unified_benchmark(gt_type):
    allowed = COMPARATIVE_GT_DATASETS if gt_type == "comp" else STANDALONE_GT_DATASETS

    ds_ids = [d for d in await db.validation_papers.distinct("dataset_id") if d in allowed]

    meta_docs = await db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1, "name": 1}).to_list(1000)
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

        si_sub = result.get("si_sub", {})
        pooled.setdefault("si_sub_correct", 0)
        pooled.setdefault("si_sub_total", 0)
        pooled.setdefault("si_sub_rhos", [])
        pooled["si_sub_correct"] += si_sub.get("correct", 0)
        pooled["si_sub_total"] += si_sub.get("total", 0)
        if si_sub.get("ranking_rho") is not None:
            pooled["si_sub_rhos"].append(si_sub["ranking_rho"])

        intr = result.get("intersection", {})
        pooled["int_pw_correct"] += int(intr.get("pw_accuracy", 0) * intr.get("pairs", 0) / 100)
        pooled["int_si_correct"] += int(intr.get("si_accuracy", 0) * intr.get("pairs", 0) / 100)
        pooled["int_total"] += intr.get("pairs", 0)
        pooled.setdefault("int_si_sub_correct", 0)
        if intr.get("si_sub_accuracy") is not None:
            pooled["int_si_sub_correct"] += int(intr["si_sub_accuracy"] * intr.get("pairs", 0) / 100)

        # Pool intersection difficulty
        intr_diff = intr.get("by_difficulty", {})
        for lvl in ["easy", "medium", "hard"]:
            ld = intr_diff.get(lvl, {})
            n = ld.get("pairs", 0)
            pooled.setdefault("int_diff", {"easy": {"pw": [0,0], "si": [0,0], "si_sub": [0,0]},
                                           "medium": {"pw": [0,0], "si": [0,0], "si_sub": [0,0]},
                                           "hard": {"pw": [0,0], "si": [0,0], "si_sub": [0,0]}})
            for m in ["pw", "si", "si_sub"]:
                rate = ld.get(f"{m}_rate", ld.get("si_sub_rate" if m == "si_sub" else f"{m}_rate", 0))
                pooled["int_diff"][lvl][m][0] += int(rate * n / 100)
                pooled["int_diff"][lvl][m][1] += n

        if result["pw"]["ranking_rho"] is not None:
            pooled["pw_rhos"].append(result["pw"]["ranking_rho"])
        if result["si"]["ranking_rho"] is not None:
            pooled["si_rhos"].append(result["si"]["ranking_rho"])

        for lvl in ["easy", "medium", "hard"]:
            for method, key in [("pw", "pw_diff"), ("si", "si_diff")]:
                dl = result[method].get("by_difficulty", {}).get(lvl, {})
                pooled[key][lvl][0] += int(dl.get("rate", 0) * dl.get("n_pairs", 0) / 100)
                pooled[key][lvl][1] += dl.get("n_pairs", 0)
                pooled[key][lvl][2] += dl.get("n_pairs", 0)
            # SI Sub-Avg difficulty
            si_sub_dl = result.get("si_sub", {}).get("by_difficulty", {}).get(lvl, {})
            pooled.setdefault("si_sub_diff", {lvl2: [0, 0, 0] for lvl2 in ["easy", "medium", "hard"]})
            pooled["si_sub_diff"][lvl][0] += int(si_sub_dl.get("rate", 0) * si_sub_dl.get("n_pairs", 0) / 100)
            pooled["si_sub_diff"][lvl][1] += si_sub_dl.get("n_pairs", 0)

    if not per_dataset:
        return {"status": "no_data"}

    pw_rho_avg = safe_round(float(np.mean(pooled["pw_rhos"]))) if pooled["pw_rhos"] else None
    si_rho_avg = safe_round(float(np.mean(pooled["si_rhos"]))) if pooled["si_rhos"] else None
    si_sub_rho_avg = safe_round(float(np.mean(pooled.get("si_sub_rhos", [])))) if pooled.get("si_sub_rhos") else None

    return {
        "status": "ok",
        "gt_type": gt_type,
        "n_datasets": len(per_dataset),
        "pooled": {
            "pw_accuracy": _rate(pooled["pw_correct"], pooled["pw_total"]),
            "si_accuracy": _rate(pooled["si_correct"], pooled["si_total"]),
            "si_sub_accuracy": _rate(pooled.get("si_sub_correct", 0), pooled.get("si_sub_total", 0)),
            "pw_pairs": pooled["pw_total"],
            "si_pairs": pooled["si_total"],
            "pw_rho": pw_rho_avg,
            "si_rho": si_rho_avg,
            "si_sub_rho": si_sub_rho_avg,
            "by_difficulty": {
                lvl: {
                    "pw_rate": _rate(pooled.get("int_diff", {}).get(lvl, {}).get("pw", [0,0])[0], pooled.get("int_diff", {}).get(lvl, {}).get("pw", [0,0])[1]),
                    "si_rate": _rate(pooled.get("int_diff", {}).get(lvl, {}).get("si", [0,0])[0], pooled.get("int_diff", {}).get(lvl, {}).get("si", [0,0])[1]),
                    "si_sub_rate": _rate(pooled.get("int_diff", {}).get(lvl, {}).get("si_sub", [0,0])[0], pooled.get("int_diff", {}).get(lvl, {}).get("si_sub", [0,0])[1]),
                    "pw_pairs": pooled.get("int_diff", {}).get(lvl, {}).get("pw", [0,0])[1],
                }
                for lvl in ["easy", "medium", "hard"]
            },
            "intersection": {
                "pw_accuracy": _rate(pooled["int_pw_correct"], pooled["int_total"]),
                "si_accuracy": _rate(pooled["int_si_correct"], pooled["int_total"]),
                "si_sub_accuracy": _rate(pooled.get("int_si_sub_correct", 0), pooled["int_total"]),
                "pairs": pooled["int_total"],
            },
        },
        "per_dataset": per_dataset,
    }
