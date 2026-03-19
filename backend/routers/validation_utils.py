"""
Shared utilities for the validation system.
Eliminates duplication of tier normalization, expert rating extraction,
content mode filtering, and safe math helpers.
"""
import math
import time as _time
from collections import defaultdict, Counter
from typing import Optional


# Projection for paper queries in analysis endpoints — excludes large text fields
PAPER_LIGHT_PROJECTION = {"_id": 0, "full_text": 0, "ai_impact_summary_opus46": 0, "ai_impact_summary_fairness_v1": 0}

from core.config import db


# ─── Ground Truth Type Classification ──────────────────────────────────────────

COMPARATIVE_GT_DATASETS = {
    "iclr-codegen", "iclr-llm", "iclr-protein", "iclr-fairness", "iclr-pdes",
    "iclr-molecules", "iclr-optimization", "iclr-ot", "peerread_acl_2017",
    "neurips-cv",
}

STANDALONE_GT_DATASETS = {
    "elife-cancer", "elife-microbiology", "elife-comp-sys-bio", "elife-neuro-100",
    "midl-medical-imaging", "qeios-social", "qeios-physical",
    "researchhub-50", "researchhub-cancer", "researchhub-genetics",
}



# ─── Tier Normalization ────────────────────────────────────────────────────────

TIER_ORDER = {"oral": 0, "spotlight": 1, "poster": 2, "reject": 3, "withdrawn": 4, "desk rejected": 4}
RANKABLE_TIERS = {"oral", "spotlight", "poster", "reject"}


def norm_tier(decision: str) -> Optional[str]:
    """Normalize a decision string to a canonical tier name, or None."""
    if not decision:
        return None
    dl = decision.lower().strip()
    for t in TIER_ORDER:
        if t in dl:
            return t
    return None


# ─── Expert Ratings ────────────────────────────────────────────────────────────

def build_expert_ratings(papers: list) -> dict:
    """Build {evaluator_name: {paper_id: rating_value}} from paper evaluations."""
    ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                ratings[name][p["id"]] = ev["rating_value"]
    return dict(ratings)


def build_human_pairwise_matches(expert_ratings: dict) -> tuple:
    """Derive pairwise matches from expert ratings. Returns (matches, ties, experts_used)."""
    matches = []
    ties = 0
    experts_used = 0
    for exp, rated_dict in expert_ratings.items():
        rated = list(rated_dict.items())
        if len(rated) < 2:
            continue
        experts_used += 1
        for i in range(len(rated)):
            for j in range(i + 1, len(rated)):
                a, ra = rated[i]
                b, rb = rated[j]
                if ra == rb:
                    ties += 1
                    continue
                matches.append({
                    "paper1_id": a, "paper2_id": b,
                    "winner_id": a if ra > rb else b,
                    "completed": True, "failed": False,
                })
    return matches, ties, experts_used


def build_expert_majority(expert_ratings: dict) -> dict:
    """Build {pair_key: winner_id} from expert majority vote."""
    pair_votes = defaultdict(list)
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                if ratings[a] != ratings[b]:
                    key = tuple(sorted([a, b]))
                    pair_votes[key].append(a if ratings[a] > ratings[b] else b)

    majority = {}
    for pair, votes in pair_votes.items():
        if len(votes) < 2:
            continue
        c = Counter(votes)
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            majority[pair] = best
    return majority


def build_ai_majority(ai_matches: list) -> dict:
    """Build {pair_key: winner_id} using majority vote from multi-judge matches."""
    votes = defaultdict(list)
    for m in ai_matches:
        if m.get("winner_id"):
            votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
    result = {}
    for pair, v in votes.items():
        c = Counter(v)
        result[pair] = c.most_common(1)[0][0]
    return result


async def build_ensemble_matches(dataset_id: str, min_models: int = 3) -> dict:
    """Build majority-vote and unanimity virtual match lists from multi-model data.
    Only uses matches within the SAME content mode (extract) for methodological purity.
    Returns {"majority": [...], "unanimity": [...], "pairs_with_all": int, "models": [...],
             "source_mode": str, "per_model_accuracy": {...}}
    where each match is a dict compatible with compute_leaderboard_async."""

    # Use extract mode (the primary tournament mode with most 3-model coverage)
    _extract_filter = {
        "abstract_only": {"$ne": True},
        "content_mode": {"$nin": ["full_pdf", "ai_summary", "abstract_plus_summary",
                                   "abstract_plus_impact", "deep_dive"],
                          "$not": {"$regex": ":"}},
        "prompt_tag": {"$exists": False},
    }

    all_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         **_extract_filter},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
         "model_used": 1, "created_at": 1},
    ).to_list(200000)

    # Group by pair → model → winner (within the same mode)
    pair_verdicts = defaultdict(dict)
    model_keys_seen = set()
    for m in all_matches:
        if not m.get("winner_id"):
            continue
        pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        mu = m.get("model_used", {})
        mk = f"{mu.get('provider', '')}:{mu.get('model', '')}"
        model_keys_seen.add(mk)
        pair_verdicts[pair][mk] = m["winner_id"]

    all_models = sorted(model_keys_seen)
    full_pairs = {p: v for p, v in pair_verdicts.items()
                  if len(v) >= min(min_models, len(all_models))}

    majority_matches = []
    unanimity_matches = []
    # Use latest created_at from the underlying matches for ordering
    pair_timestamps = defaultdict(str)
    for m in all_matches:
        pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        ts = m.get("created_at", "")
        if ts > pair_timestamps[pair]:
            pair_timestamps[pair] = ts

    for pair, verdicts in sorted(full_pairs.items(), key=lambda x: pair_timestamps.get(x[0], "")):
        winners = list(verdicts.values())
        c = Counter(winners)
        best, count = c.most_common(1)[0]
        base = {"paper1_id": pair[0], "paper2_id": pair[1], "completed": True, "failed": False,
                "created_at": pair_timestamps.get(pair, "")}

        # Majority: 2+ out of 3 agree
        if count > len(winners) / 2:
            majority_matches.append({**base, "winner_id": best})

        # Unanimity: ALL models agree
        if count == len(winners):
            unanimity_matches.append({**base, "winner_id": best})

    return {
        "majority": majority_matches,
        "unanimity": unanimity_matches,
        "pairs_with_all": len(full_pairs),
        "models": all_models,
        "source_mode": "extract",
    }


# ─── Content Mode Filter ──────────────────────────────────────────────────────

def build_content_mode_filter(content_mode: Optional[str] = None, abstract_only: Optional[bool] = None) -> dict:
    """Build a MongoDB match filter for content_mode, with backward compatibility."""
    _extract_filter = {
        "abstract_only": {"$ne": True},
        "content_mode": {"$nin": ["full_pdf", "ai_summary", "abstract_plus_summary", "abstract_plus_impact", "deep_dive"], "$not": {"$regex": ":"}},
        "prompt_tag": {"$exists": False},
    }
    if not content_mode:
        if abstract_only is True:
            return {"abstract_only": True}
        elif abstract_only is False:
            return _extract_filter
        return {}
    if ":" in content_mode:
        return {"content_mode": content_mode}
    if content_mode == "full_pdf":
        return {"content_mode": "full_pdf"}
    elif content_mode == "ai_summary":
        return {"content_mode": "ai_summary"}
    elif content_mode == "abstract_plus_summary":
        return {"content_mode": "abstract_plus_summary"}
    elif content_mode == "abstract_plus_3summaries":
        return {"content_mode": "abstract_plus_3summaries"}
    elif content_mode == "abstract_plus_random_summary":
        return {"content_mode": "abstract_plus_random_summary"}
    elif content_mode == "abstract_plus_impact":
        return {"content_mode": "abstract_plus_impact"}
    elif content_mode == "deep_dive":
        return {"content_mode": "deep_dive"}
    elif content_mode == "abstract":
        return {"abstract_only": True}
    elif content_mode == "extract" or abstract_only is False:
        return _extract_filter
    return {}


# ─── Ground Truth Scores ──────────────────────────────────────────────────────

def build_paper_gt_scores(papers: list) -> dict:
    """Build {paper_id: gt_score} from tier decisions, composite scores, or avg ratings.
    Returns only papers with a usable GT signal. Higher score = better paper."""
    # Use a unified scale where higher = better (consistent with _TIER in iclr_deep_dive.py)
    DECISION_SCORE = {
        "oral": 4, "spotlight": 3, "poster": 2, "withdrawn": 1,
        "desk rejected": 0, "reject": 0,
    }
    gt = {}
    for p in papers:
        pid = p["id"]
        t = norm_tier(p.get("decision"))
        if t and t in DECISION_SCORE:
            gt[pid] = DECISION_SCORE[t]
            continue
        cs = p.get("composite_score")
        if cs is not None:
            gt[pid] = cs
            continue
        evals = p.get("evaluations", [])
        ratings = [e["rating_value"] for e in evals if e.get("rating_value")]
        if ratings:
            gt[pid] = sum(ratings) / len(ratings)
    return gt


def is_cross_tier_pair(p1_id: str, p2_id: str, gt_scores: dict) -> bool:
    """Return True if two papers have different GT scores (non-tie)."""
    g1 = gt_scores.get(p1_id)
    g2 = gt_scores.get(p2_id)
    if g1 is None or g2 is None:
        return False
    return g1 != g2


def filter_cross_tier_matches(matches: list, gt_scores: dict) -> list:
    """Filter a list of matches to only cross-tier (non-tie GT) pairs."""
    return [m for m in matches if is_cross_tier_pair(m["paper1_id"], m["paper2_id"], gt_scores)]



# ─── Safe Math ─────────────────────────────────────────────────────────────────

def safe_round(v, n=4):
    """Round a float safely, handling NaN/Inf/None."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return 0.0
    return round(float(v), n)


def interp(rho, p_val, n, method):
    """Generate a human-readable interpretation of a correlation result."""
    strength = "strong" if abs(rho) >= 0.7 else "moderate" if abs(rho) >= 0.4 else "weak" if abs(rho) >= 0.2 else "negligible"
    direction = "positive" if rho > 0 else "negative"
    sig = "statistically significant" if p_val < 0.05 else "not statistically significant"
    return f"Using {method} ranking ({n} papers): Spearman ρ = {rho:.3f} ({strength} {direction}, {sig}, p = {p_val:.4f})."


# ─── Result Cache ──────────────────────────────────────────────────────────────
# Pure TTL cache — no per-request DB queries. Invalidated explicitly when
# tournaments add matches, or by TTL expiry.

_result_cache = {}
_CACHE_TTL = 3600  # 1 hour — background refresh keeps it warm, explicit invalidation on new matches


async def cache_get(endpoint: str, dataset_id: str, content_mode: str = ""):
    key = (endpoint, dataset_id, content_mode or "")
    entry = _result_cache.get(key)
    if not entry:
        return None
    return entry["data"]


async def cache_set(endpoint: str, dataset_id: str, content_mode: str, data, match_count: int = None):
    _result_cache[(endpoint, dataset_id, content_mode or "")] = {
        "data": data, "ts": _time.time(),
    }


def invalidate_dataset_cache(dataset_id: str):
    """Invalidate all cached results for a dataset. Call after tournament adds matches."""
    to_del = [k for k in _result_cache if k[1] == dataset_id]
    for k in to_del:
        del _result_cache[k]



# ─── Shared Caches (used by analysis and experiment modules) ──────────────────

# Consistency analysis caches
consistency_cache = {"data": None, "ts": 0}
cycle_all_cache = {"data": None, "ts": 0}
CONSISTENCY_TTL = 3600  # 1 hour

# Convergence-all per-dataset cache
convergence_all_cache = {}  # dataset_id -> {"data": ..., "ts": float}
CONV_CACHE_TTL = 3600

# Summarizer experiment caches
ae_cache = {"data": None, "ts": 0}
sumab_results_cache = {"data": None, "ts": 0}
extended_thinking_cache = {"data": None}
multi_aspect_cache = {"data": None}
pairwise_cache = {}  # (dataset_id, content_mode) -> data


def invalidate_all_caches(dataset_id: str):
    """Invalidate all caches for a dataset — call after any experiment adds matches."""
    invalidate_dataset_cache(dataset_id)
    convergence_all_cache.pop(dataset_id, None)
    # Clear experiment caches so they recompute with new data
    consistency_cache["data"] = None
    cycle_all_cache["data"] = None
    sumab_results_cache["data"] = None
    ae_cache["data"] = None
    extended_thinking_cache["data"] = None
    multi_aspect_cache["data"] = None
