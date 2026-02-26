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
    if _time.time() - entry["ts"] > _CACHE_TTL:
        del _result_cache[key]
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
