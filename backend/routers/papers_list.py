"""
Server-side paginated paper list — the keystone of the heatmap scaling plan.

The frontend used to fetch the full corpus and filter/sort/page client-side. This
endpoint owns those operations on the server so the wire transfer scales with
`limit` instead of corpus size.

Data sources:
  * `dataset=precomputed`  → the 206 ICLR papers from the prompt-stability JSON
  * `dataset=synthetic`    → N synthetic papers (same generator as /api/scaling-test/papers)
                              cached in-memory keyed by (n, seed, reasoning)

When the production `papers` collection eventually carries extended ratings, the
data-source layer below can be swapped for Mongo aggregations without touching
the filter/sort/page semantics.
"""
from fastapi import APIRouter, Query, Request
from typing import Optional
from datetime import datetime, timezone, timedelta
import json
import random
import time

from routers.scaling_test import _gen_paper

router = APIRouter(prefix="/api/papers-list", tags=["papers_list"])

# --- Metric definitions (must match frontend METRICS) -----------------------
_CORE_METRICS = ["score", "significance", "rigor", "novelty", "clarity"]
_EXT_METRICS = [
    "difficulty", "surprisingness", "reproducibility",
    "translational_potential", "evidence_strength", "generalisability",
]
_ALL_METRICS = _CORE_METRICS + _EXT_METRICS
_SORT_KEYS = {*_ALL_METRICS, "title", "category", "published"}

# --- Data sources -----------------------------------------------------------
_PRECOMPUTED_CACHE: Optional[list] = None


def _load_precomputed() -> list:
    """Load the 206 prompt-stability papers from disk (cached)."""
    global _PRECOMPUTED_CACHE
    if _PRECOMPUTED_CACHE is not None:
        return _PRECOMPUTED_CACHE
    path = "/app/backend/data/precomputed/prompt_stability_results.json"
    try:
        with open(path) as f:
            d = json.load(f)
        _PRECOMPUTED_CACHE = d.get("exp3", {}).get("papers", []) or []
    except FileNotFoundError:
        _PRECOMPUTED_CACHE = []
    return _PRECOMPUTED_CACHE


_SYNTHETIC_CACHE: dict = {}


def _load_synthetic(n: int, seed: int, reasoning: bool) -> list:
    """Generate N synthetic papers, cached by (n, seed, reasoning)."""
    key = (n, seed, reasoning)
    if key in _SYNTHETIC_CACHE:
        return _SYNTHETIC_CACHE[key]
    # Only retain one synthetic dataset at a time to avoid memory blow on 100k+
    _SYNTHETIC_CACHE.clear()
    rng = random.Random(seed)
    papers = [_gen_paper(rng, include_reasoning=reasoning) for _ in range(n)]
    _SYNTHETIC_CACHE[key] = papers
    return papers


# --- Filter / sort / histogram ----------------------------------------------
def _matches_categories(p: dict, cat_set: set, mode: str, logic: str) -> bool:
    primary = p.get("category")
    all_cats = p.get("categories") or ([primary] if primary else [])
    cats_seen = set(all_cats)

    def check(c: str) -> bool:
        if mode == "primary":
            return c == primary
        if mode == "cross-listed":
            return c in cats_seen and c != primary
        return c in cats_seen  # "any"

    if logic == "and":
        return all(check(c) for c in cat_set)
    return any(check(c) for c in cat_set)


def _apply_filter(papers: list, params: dict) -> list:
    out = papers

    q = (params.get("search") or "").strip().lower()
    if q:
        out = [
            p for p in out
            if (p.get("title") or "").lower().find(q) >= 0
            or any(q in (a or "").lower() for a in (p.get("authors") or []))
        ]

    dr = params.get("date_range") or "all"
    if dr != "all":
        days = {"newly": 1, "7d": 7, "30d": 30}.get(dr)
        if days:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            out = [p for p in out if (p.get("published") or "") >= cutoff_iso]

    cats_raw = params.get("cats") or ""
    cats = [c for c in cats_raw.split(",") if c]
    if cats:
        cat_set = set(cats)
        mode = params.get("cat_mode") or "any"
        logic = params.get("cat_logic") or "or"
        out = [p for p in out if _matches_categories(p, cat_set, mode, logic)]

    include_nulls = params.get("include_nulls", True)
    thresholds = params.get("thresholds") or {}
    for metric, (thr, op) in thresholds.items():
        # No-op thresholds
        if op == "gte" and thr <= 0:
            continue
        if op == "lte" and (thr >= 10 or thr <= 0):
            continue
        filtered = []
        for p in out:
            v = (p.get("ratings") or {}).get(metric)
            if v is None:
                if include_nulls:
                    filtered.append(p)
                continue
            if op == "gte" and v >= thr:
                filtered.append(p)
            elif op == "lte" and v <= thr:
                filtered.append(p)
        out = filtered

    return out


def _apply_sort(papers: list, sort_key: str, sort_dir: str) -> list:
    reverse = sort_dir == "desc"
    if sort_key == "title":
        return sorted(papers, key=lambda p: (p.get("title") or "").lower(), reverse=reverse)
    if sort_key == "category":
        return sorted(papers, key=lambda p: p.get("category") or "", reverse=reverse)
    if sort_key == "published":
        return sorted(papers, key=lambda p: p.get("published") or "", reverse=reverse)
    if sort_key in _ALL_METRICS:
        # Nulls always sink regardless of direction. Stable tiebreaker on paper_id.
        def keyfn(p: dict):
            v = (p.get("ratings") or {}).get(sort_key)
            is_null = v is None
            return (is_null, -(v or 0) if (reverse and not is_null) else (v if not is_null else 0), p.get("paper_id") or "")
        return sorted(papers, key=keyfn)
    return papers


def _compute_histograms(papers: list, bins: int = 10) -> dict:
    out = {}
    for m in _ALL_METRICS:
        counts = [0] * bins
        values = []
        for p in papers:
            v = (p.get("ratings") or {}).get(m)
            if v is None:
                continue
            values.append(v)
            idx = min(bins - 1, max(0, int(((v - 1) / 9) * bins)))
            counts[idx] += 1
        n = len(values)
        out[m] = {
            "counts": counts,
            "n": n,
            "mean": (sum(values) / n) if n else None,
            "max": max(counts) if counts else 1,
        }
    return out


# --- Endpoint ----------------------------------------------------------------
@router.get("")
async def papers_list(
    request: Request,
    # Data source
    dataset: str = Query("precomputed", description="precomputed | synthetic"),
    n: int = Query(1000, ge=1, le=200_000),
    seed: int = Query(42),
    reasoning: bool = Query(True),
    # Filter
    search: str = "",
    date_range: str = "all",
    cats: str = "",
    cat_mode: str = "any",
    cat_logic: str = "or",
    include_nulls: bool = True,
    # Sort
    sort_key: str = "score",
    sort_dir: str = "desc",
    # Page
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=200),
    include_histograms: bool = True,
    include_categories: bool = False,
):
    """Server-side paginated paper list.

    Per-metric thresholds are passed via query params `min_<metric>` and `op_<metric>`,
    e.g. `?min_reproducibility=7&op_reproducibility=gte`. They're read off the raw
    request rather than declared explicitly so the metric set can evolve without
    code changes here.
    """
    t0 = time.time()

    # Parse per-metric thresholds from the request's query params
    thresholds: dict = {}
    qp = request.query_params
    for m in _ALL_METRICS:
        thr_raw = qp.get(f"min_{m}")
        if thr_raw is None:
            continue
        try:
            thr_val = float(thr_raw)
        except (TypeError, ValueError):
            continue
        op = qp.get(f"op_{m}") or "gte"
        if op not in ("gte", "lte"):
            op = "gte"
        thresholds[m] = (thr_val, op)

    if sort_key not in _SORT_KEYS:
        sort_key = "score"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    # Load source
    if dataset == "synthetic":
        all_papers = _load_synthetic(n, seed, reasoning)
    else:
        all_papers = _load_precomputed()

    t_load = time.time()

    # Build the params dict the filter expects
    params = {
        "search": search,
        "date_range": date_range,
        "cats": cats,
        "cat_mode": cat_mode,
        "cat_logic": cat_logic,
        "include_nulls": include_nulls,
        "thresholds": thresholds,
    }

    filtered = _apply_filter(all_papers, params)
    t_filter = time.time()

    sorted_papers = _apply_sort(filtered, sort_key, sort_dir)
    t_sort = time.time()

    total = len(sorted_papers)
    page = sorted_papers[offset:offset + limit]
    next_cursor = str(offset + limit) if offset + limit < total else None

    histograms = _compute_histograms(filtered) if include_histograms else None

    all_categories = None
    if include_categories:
        cat_set = set()
        for p in all_papers:
            if p.get("category"):
                cat_set.add(p["category"])
            for c in (p.get("categories") or []):
                cat_set.add(c)
        all_categories = sorted(cat_set)

    t_end = time.time()

    return {
        "rows": page,
        "next_cursor": next_cursor,
        "offset": offset,
        "limit": limit,
        "total": total,
        "histograms": histograms,
        "all_categories": all_categories,
        "dataset": dataset,
        "dataset_size": len(all_papers),
        "timing_ms": {
            "load": int((t_load - t0) * 1000),
            "filter": int((t_filter - t_load) * 1000),
            "sort": int((t_sort - t_filter) * 1000),
            "histogram": int((t_end - t_sort) * 1000),
            "total": int((t_end - t0) * 1000),
        },
    }
