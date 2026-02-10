from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
from collections import Counter
import asyncio
import time
from core.config import db, logger, CATEGORIES
from services.ranking import compute_leaderboard, calculate_confidence_interval

router = APIRouter(prefix="/api")

# Pre-computed cache — refreshed in the background, never blocks requests
_cache = {"ts": 0, "categories": {}, "total_papers": 0, "total_matches": 0}
_CACHE_TTL = 20
_cache_lock = asyncio.Lock()
_bg_task_started = False

# Tag query cache — keyed on (frozenset(tags), period, tag_mode, global_stats, show_all)
_tag_cache = {}  # key -> {"ts": float, "result": dict}
_TAG_CACHE_TTL = 20  # Same as main cache TTL
_TAG_CACHE_MAX = 100  # Max cached tag combos


def _apply_period_filter(full_leaderboard, period):
    """Apply period filter to a pre-ranked leaderboard. Returns (filtered_list, total_in_period)."""
    if period == "all":
        return full_leaderboard, len(full_leaderboard)

    utc_now = datetime.now(timezone.utc)
    paper_dates = {}
    for entry in full_leaderboard:
        try:
            paper_dates[entry["id"]] = datetime.fromisoformat(entry.get("published", "").replace("Z", "+00:00"))
        except (ValueError, KeyError):
            pass

    if period == "recent":
        max_date = max(paper_dates.values()) if paper_dates else utc_now
        cutoff = datetime(max_date.year, max_date.month, max_date.day, tzinfo=timezone.utc)
    elif period == "week":
        cutoff = utc_now - timedelta(weeks=1)
    elif period == "month":
        cutoff = utc_now - timedelta(days=30)
    else:
        return full_leaderboard, len(full_leaderboard)

    filtered = [{**e} for e in full_leaderboard if e["id"] in paper_dates and paper_dates[e["id"]] >= cutoff]
    for i, e in enumerate(filtered):
        e["rank"] = i + 1
    return filtered, len(filtered)


async def _refresh_cache():
    """Heavy computation — runs in background, never on the request path."""
    all_papers = await db.papers.find(
        {}, {"_id": 0, "full_text": 0, "abstract": 0}
    ).to_list(5000)

    all_matches_raw = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1, "mode": 1, "shared_categories": 1, "primary_category": 1, "model_used": 1, "tokens": 1, "created_at": 1, "id": 1, "reasoning": 1},
    ).to_list(200000)

    # Exclude experiment matches from public leaderboard
    all_matches = [m for m in all_matches_raw if not m.get("mode")]

    utc_now = datetime.now(timezone.utc)
    categories_data = {}

    # Group papers by primary category
    papers_by_cat = {}
    for p in all_papers:
        cat = p.get("categories", ["unknown"])[0] if p.get("categories") else "unknown"
        papers_by_cat.setdefault(cat, []).append(p)

    # Pre-index: build paper_id → list of match indices for O(1) lookup
    match_index = {}  # paper_id -> [match_idx, ...]
    for idx, m in enumerate(all_matches):
        for pid in (m["paper1_id"], m["paper2_id"]):
            if pid not in match_index:
                match_index[pid] = []
            match_index[pid].append(idx)

    # Load settings once
    from core.auth import get_settings
    settings = await get_settings()

    # Use dynamic active categories from settings
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))

    for cat_id in active_cats:
        cat_papers = papers_by_cat.get(cat_id, [])
        if not cat_papers:
            categories_data[cat_id] = {
                "all": [], "recent": [], "week": [], "month": [],
                "_matches": 0, "_papers": 0, "_is_ranking": False,
            }
            continue

        cat_paper_ids = {p["id"] for p in cat_papers}

        # Use pre-built index: collect matches where BOTH papers are in this category
        cat_match_idxs = set()
        for pid in cat_paper_ids:
            for midx in match_index.get(pid, []):
                cat_match_idxs.add(midx)
        cat_matches = [all_matches[i] for i in cat_match_idxs
                       if all_matches[i]["paper1_id"] in cat_paper_ids
                       and all_matches[i]["paper2_id"] in cat_paper_ids]

        full = compute_leaderboard(cat_papers, cat_matches)

        paper_dates = {}
        for entry in full:
            try:
                paper_dates[entry["id"]] = datetime.fromisoformat(entry.get("published", "").replace("Z", "+00:00"))
            except (ValueError, KeyError):
                pass

        max_date = max(paper_dates.values()) if paper_dates else utc_now
        recent_cutoff = datetime(max_date.year, max_date.month, max_date.day, tzinfo=timezone.utc)

        def filter_and_rerank(cutoff, entries=full):
            filtered = [{**e} for e in entries if e["id"] in paper_dates and paper_dates[e["id"]] >= cutoff]
            for i, e in enumerate(filtered):
                e["rank"] = i + 1
            return filtered

        # Use tournament registry for is_ranking status (single source of truth)
        tournament = await db.tournaments.find_one(
            {"category": cat_id, "mode": "standard"}, {"_id": 0, "stats": 1}
        )
        is_ranking = not (tournament and tournament.get("stats", {}).get("goals_met", False))

        categories_data[cat_id] = {
            "all": full,
            "recent": filter_and_rerank(recent_cutoff),
            "week": filter_and_rerank(utc_now - timedelta(weeks=1)),
            "month": filter_and_rerank(utc_now - timedelta(days=30)),
            "_matches": len(cat_matches),
            "_papers": len(cat_papers),
            "_is_ranking": is_ranking,
        }

    # --- Pre-compute "all papers" leaderboard (used by show_all=true) ---
    all_full = compute_leaderboard(all_papers, all_matches)
    paper_cat_lookup = {p["id"]: p.get("categories", ["unknown"])[0] for p in all_papers}
    for entry in all_full:
        entry["primary_category"] = paper_cat_lookup.get(entry["id"], "unknown")

    all_periods = {"all": all_full}
    for period_key in ("recent", "week", "month"):
        filtered, _ = _apply_period_filter(all_full, period_key)
        all_periods[period_key] = filtered

    _cache.update({
        "ts": time.time(),
        "categories": categories_data,
        "total_papers": len(all_papers),
        "total_matches": len(all_matches),
        "_raw_papers": all_papers,
        "_raw_matches": all_matches,
        "_raw_matches_all": all_matches_raw,
        "_match_index": match_index,
        "_paper_cat_lookup": paper_cat_lookup,
        "_all_papers_leaderboard": all_periods,
    })

    # Pre-compute failed match counts per category (for admin panel)
    failed_by_cat = Counter()
    async for m in db.matches.find(
        {"failed": True, "mode": {"$exists": False}},
        {"_id": 0, "primary_category": 1},
    ):
        failed_by_cat[m.get("primary_category", "unknown")] += 1
    _cache["_failed_by_cat"] = dict(failed_by_cat)

    # Invalidate tag cache on data refresh
    _tag_cache.clear()

    # Pre-compute tags data
    tag_counts = Counter()
    for p in all_papers:
        for cat in p.get("categories", []):
            tag_counts[cat] += 1
    tag_match_counts = Counter()
    for m in all_matches:
        for cat in m.get("shared_categories", []):
            tag_match_counts[cat] += 1
    _cache["_tags"] = [
        {"id": tag, "count": count, "matches": tag_match_counts.get(tag, 0)}
        for tag, count in tag_counts.most_common()
    ]

    # Pre-compute categories list
    try:
        from core.arxiv_categories import ARXIV_TAXONOMY
    except ImportError:
        ARXIV_TAXONOMY = {}
    _cache["_categories"] = [
        {"id": cat_id, "name": CATEGORIES.get(cat_id) or ARXIV_TAXONOMY.get(cat_id) or cat_id}
        for cat_id in active_cats
    ]
    _cache["_default_category"] = active_cats[0] if active_cats else "cs.RO"


async def _bg_cache_loop():
    """Background loop that keeps the cache fresh."""
    global _bg_task_started
    _bg_task_started = True
    # Initial warm
    try:
        await _refresh_cache()
        logger.info("Leaderboard cache warmed (background)")
    except Exception as e:
        logger.warning(f"Initial cache warm failed: {e}")

    while True:
        await asyncio.sleep(_CACHE_TTL)
        try:
            await _refresh_cache()
        except Exception as e:
            logger.warning(f"Background cache refresh failed: {e}")


def start_cache_bg():
    """Start the background cache refresh task. Called from startup."""
    global _bg_task_started
    if not _bg_task_started:
        asyncio.create_task(_bg_cache_loop())


async def _get_cached_leaderboard():
    """Returns pre-computed cache instantly. Falls back to sync refresh if cache is empty."""
    if _cache["categories"]:
        return _cache
    await _refresh_cache()
    return _cache


@router.get("/tags")
async def get_all_tags():
    """Returns all unique category tags across all papers with counts and match coverage."""
    cache = await _get_cached_leaderboard()
    # Serve pre-computed tags from background cache
    if "_tags" in cache:
        return {"tags": cache["_tags"]}
    # Fallback: compute from raw data (only on cold cache)
    from collections import Counter
    raw_papers = cache.get("_raw_papers", [])
    raw_matches = cache.get("_raw_matches", [])
    tag_counts = Counter()
    for p in raw_papers:
        for cat in p.get("categories", []):
            tag_counts[cat] += 1
    tag_match_counts = Counter()
    for m in raw_matches:
        for cat in m.get("shared_categories", []):
            tag_match_counts[cat] += 1
    tags = [
        {"id": tag, "count": count, "matches": tag_match_counts.get(tag, 0)}
        for tag, count in tag_counts.most_common()
    ]
    return {"tags": tags}


@router.get("/categories")
async def get_categories():
    """Always read from settings (5s TTL, invalidated on changes) — not the 20s leaderboard cache."""
    from core.auth import get_settings
    try:
        from core.arxiv_categories import ARXIV_TAXONOMY
    except ImportError:
        ARXIV_TAXONOMY = {}
    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))
    cats = []
    for cat_id in active:
        name = CATEGORIES.get(cat_id) or ARXIV_TAXONOMY.get(cat_id) or cat_id
        cats.append({"id": cat_id, "name": name})
    return {
        "categories": cats,
        "default": active[0] if active else "cs.RO",
    }


def _apply_search(data: list, search: str) -> list:
    """Filter leaderboard entries by title search and re-rank."""
    if not search:
        return data
    search_lower = search.lower()
    filtered = [p for p in data if search_lower in p.get("title", "").lower()]
    # Re-rank the filtered results
    return [{**p, "rank": i + 1} for i, p in enumerate(filtered)]


@router.get("/leaderboard")
async def get_leaderboard(
    category: Optional[str] = Query("cs.RO", description="arXiv primary category"),
    period: Optional[str] = Query("all", description="Filter: recent, week, month, all"),
    tags: Optional[str] = Query(None, description="Comma-separated category tags to filter by (overrides category)"),
    tag_mode: Optional[str] = Query("or", description="How to combine tags: 'or' (any) or 'and' (all)"),
    global_stats: bool = Query(False, description="Include global stats (all matches) for each paper"),
    show_all: bool = Query(False, description="Show all papers with matches_tag flag (tag mode only)"),
    search: Optional[str] = Query(None, description="Search papers by title (case-insensitive)"),
    limit: int = Query(500, description="Max papers to return"),
    offset: int = Query(0, description="Offset for pagination"),
):
    # Tag-based filtering: compute on-demand
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            return await _compute_tag_leaderboard(tag_list, period, limit, offset, tag_mode, global_stats, show_all, search)

    # Show all papers from all categories (tag panel open, no tags selected)
    if show_all:
        return await _compute_all_papers_leaderboard(period, limit, offset, search)

    # Default: use pre-computed primary category cache
    cache = await _get_cached_leaderboard()
    cat_data = cache["categories"].get(category, {})
    data = cat_data.get(period, cat_data.get("all", []))

    # Apply search filter
    data = _apply_search(data, search)

    return {
        "leaderboard": data[offset:offset + limit],
        "total_papers": cat_data.get("_papers", 0),
        "total_in_period": len(data),
        "total_matches": cat_data.get("_matches", 0),
        "is_ranking": cat_data.get("_is_ranking", False),
        "period": period,
        "category": category,
        "tags": None,
        "tag_mode": None,
    }


async def _compute_all_papers_leaderboard(period: str, limit: int, offset: int, search: str = None):
    """Return all papers from all categories — served from pre-computed cache."""
    cache = await _get_cached_leaderboard()
    all_lb = cache.get("_all_papers_leaderboard")

    if not all_lb:
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": None, "tags": None, "tag_mode": None, "show_all": True,
        }

    data = all_lb.get(period, all_lb.get("all", []))
    data = _apply_search(data, search)

    return {
        "leaderboard": data[offset:offset + limit],
        "total_papers": cache.get("total_papers", 0),
        "total_in_period": len(data),
        "total_matches": cache.get("total_matches", 0),
        "is_ranking": False,
        "period": period,
        "category": None,
        "tags": None,
        "tag_mode": None,
        "show_all": True,
    }



async def _compute_tag_leaderboard(
    tag_list: list, period: str, limit: int, offset: int,
    tag_mode: str = "or", global_stats: bool = False, show_all: bool = False,
    search: str = None,
):
    """Compute leaderboard for tag queries — cached per tag combination."""
    # Build a cache key from the query parameters (excluding pagination and search)
    cache_key = (frozenset(tag_list), period, tag_mode, global_stats, show_all)

    now = time.time()
    cached = _tag_cache.get(cache_key)
    if cached and now - cached["ts"] < _TAG_CACHE_TTL:
        # Serve from cache, apply search + pagination
        full_data = _apply_search(cached["result"]["_full_data"], search)
        full_result = cached["result"]
        return {
            **{k: v for k, v in full_result.items() if k != "_full_data"},
            "leaderboard": full_data[offset:offset + limit],
            "total_in_period": len(full_data),
        }

    cache = await _get_cached_leaderboard()
    raw_papers = cache.get("_raw_papers", [])
    raw_matches = cache.get("_raw_matches", [])
    match_index = cache.get("_match_index", {})
    paper_cat_lookup = cache.get("_paper_cat_lookup", {})

    if not raw_papers:
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": None, "tags": tag_list, "tag_mode": tag_mode,
        }

    # Identify which papers match the selected tags
    tag_set = set(tag_list)
    if tag_mode == "and" and len(tag_list) > 1:
        matching_papers = [p for p in raw_papers if tag_set.issubset(set(p.get("categories", [])))]
    else:
        matching_papers = [p for p in raw_papers if tag_set.intersection(set(p.get("categories", [])))]

    matching_ids = {p["id"] for p in matching_papers}

    if not matching_papers and not show_all:
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": None, "tags": tag_list, "tag_mode": tag_mode,
        }

    # Decide which papers to include in the output
    display_papers = raw_papers if show_all else matching_papers
    display_ids = {p["id"] for p in display_papers}

    # Use pre-built match index for fast match lookup
    display_match_idxs = set()
    for pid in display_ids:
        for midx in match_index.get(pid, []):
            display_match_idxs.add(midx)
    display_matches = [raw_matches[i] for i in display_match_idxs
                       if raw_matches[i]["paper1_id"] in display_ids
                       and raw_matches[i]["paper2_id"] in display_ids]

    full = compute_leaderboard(display_papers, display_matches)

    # Add primary_category and matches_tag flag
    for entry in full:
        entry["matches_tag"] = entry["id"] in matching_ids
        entry["primary_category"] = paper_cat_lookup.get(entry["id"], "unknown")

    # If global_stats requested, use pre-computed "All Papers" BT scores
    if global_stats:
        all_lb = cache.get("_all_papers_leaderboard", {}).get("all", [])
        global_lookup = {e["id"]: e for e in all_lb}
        for entry in full:
            g = global_lookup.get(entry["id"])
            if g:
                entry["global_score"] = g["score"]
                entry["global_wins"] = g["wins"]
                entry["global_losses"] = g["losses"]
                entry["global_comparisons"] = g["comparisons"]
                entry["global_win_rate"] = g["win_rate"]
            else:
                entry["global_score"] = 1200
                entry["global_wins"] = 0
                entry["global_losses"] = 0
                entry["global_comparisons"] = 0
                entry["global_win_rate"] = 0

    # Period filtering
    data, total_in_period = _apply_period_filter(full, period)

    # Count matches only between matching papers (for the "local" match count)
    tag_match_idxs = set()
    for pid in matching_ids:
        for midx in match_index.get(pid, []):
            tag_match_idxs.add(midx)
    tag_only_match_count = sum(
        1 for i in tag_match_idxs
        if raw_matches[i]["paper1_id"] in matching_ids
        and raw_matches[i]["paper2_id"] in matching_ids
    )

    result = {
        "total_papers": len(matching_papers),
        "total_all_papers": len(display_papers) if show_all else len(matching_papers),
        "total_in_period": total_in_period,
        "total_matches": tag_only_match_count,
        "total_all_matches": len(display_matches) if show_all else tag_only_match_count,
        "is_ranking": False,
        "period": period,
        "category": None,
        "tags": tag_list,
        "tag_mode": tag_mode,
        "show_all": show_all,
        "global_stats": global_stats,
        "_full_data": data,  # Full list for pagination
    }

    # Store in cache (evict oldest if full)
    if len(_tag_cache) >= _TAG_CACHE_MAX:
        oldest_key = min(_tag_cache, key=lambda k: _tag_cache[k]["ts"])
        del _tag_cache[oldest_key]
    _tag_cache[cache_key] = {"ts": now, "result": result}

    # Apply search filter (after caching unfiltered data)
    searched_data = _apply_search(data, search)

    return {
        **{k: v for k, v in result.items() if k != "_full_data"},
        "leaderboard": searched_data[offset:offset + limit],
        "total_in_period": len(searched_data),
    }


@router.get("/papers/{paper_id}")
async def get_paper_detail(paper_id: str):
    paper = await db.papers.find_one({"id": paper_id}, {"_id": 0, "full_text": 0})
    if not paper:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get all standard matches for this paper (exclude experiments)
    matches = await db.matches.find(
        {
            "completed": True,
            "mode": {"$exists": False},
            "$or": [{"paper1_id": paper_id}, {"paper2_id": paper_id}],
        },
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)

    # Get opponent paper titles
    opponent_ids = set()
    for m in matches:
        if m["paper1_id"] == paper_id:
            opponent_ids.add(m["paper2_id"])
        else:
            opponent_ids.add(m["paper1_id"])

    opponents = await db.papers.find(
        {"id": {"$in": list(opponent_ids)}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "link": 1},
    ).to_list(500)
    opponent_lookup = {o["id"]: o for o in opponents}

    # Enrich matches with paper titles
    enriched_matches = []
    for m in matches:
        opponent_id = m["paper2_id"] if m["paper1_id"] == paper_id else m["paper1_id"]
        opp = opponent_lookup.get(opponent_id, {})
        won = m.get("winner_id") == paper_id
        enriched_matches.append({
            "id": m["id"],
            "opponent_id": opponent_id,
            "opponent_title": opp.get("title", "Unknown"),
            "opponent_arxiv_id": opp.get("arxiv_id", ""),
            "won": won,
            "reasoning": m.get("reasoning", ""),
            "model_used": m.get("model_used", {}),
            "created_at": m.get("created_at", ""),
            "failed": m.get("failed", False),
        })

    # Compute stats
    wins = sum(1 for m in enriched_matches if m["won"] and not m["failed"])
    total = sum(1 for m in enriched_matches if not m["failed"])
    ci = calculate_confidence_interval(wins, total)

    return {
        "paper": paper,
        "matches": enriched_matches,
        "stats": {
            "wins": wins,
            "losses": total - wins,
            "comparisons": total,
            "confidence": ci,
        },
    }


_status_cache = {"data": None, "ts": 0}


@router.get("/status")
async def get_system_status():
    from services.scheduler import get_scheduler_status

    now = time.time()
    if _status_cache["data"] is None or now - _status_cache["ts"] > 10:
        total_papers = await db.papers.count_documents({})
        total_matches = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}})
        failed_matches = await db.matches.count_documents({"failed": True})
        _status_cache["data"] = {
            "total_papers": total_papers,
            "total_matches": total_matches,
            "failed_matches": failed_matches,
        }
        _status_cache["ts"] = now

    cached = _status_cache["data"]
    return {
        **cached,
        "scheduler": get_scheduler_status(),
    }


@router.get("/prompts")
async def get_public_prompts():
    """Public read-only view of the evaluation and summary prompts."""
    from core.config import DEFAULT_EVALUATION_PROMPT

    eval_doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
    eval_prompt = {
        "system_prompt": eval_doc.get("system_prompt", "") if eval_doc else DEFAULT_EVALUATION_PROMPT["system_prompt"],
        "user_prompt": eval_doc.get("user_prompt", "") if eval_doc else DEFAULT_EVALUATION_PROMPT["user_prompt"],
    }

    summary_doc = await db.settings.find_one({"key": "summary_prompt"}, {"_id": 0})
    summary_prompt = None
    if summary_doc and summary_doc.get("system_prompt"):
        summary_prompt = {
            "system_prompt": summary_doc.get("system_prompt", ""),
            "user_prompt": summary_doc.get("user_prompt", ""),
        }

    return {
        "evaluation": eval_prompt,
        "summary": summary_prompt,
    }


@router.get("/model-correlation")
async def get_model_correlation(
    category: Optional[str] = Query(None, description="Filter by category (None = all)"),
    mode: Optional[str] = Query(None, description="Match mode: None=standard, 'prediction', 'prediction-fulltext'"),
):
    """Correlation analysis between the 3 LLMs used for rankings."""
    import numpy as np
    from scipy import stats as scipy_stats

    cat_paper_ids = None
    if category:
        cat_paper_ids = set()
        async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
            cat_paper_ids.add(p["id"])

    matches_raw = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "model_used": {"$exists": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1, "mode": 1},
    ).to_list(100000)

    # Filter by mode
    if mode:
        matches_raw = [m for m in matches_raw if m.get("mode") == mode]
    else:
        # Default: standard matches only (exclude experiments)
        matches_raw = [m for m in matches_raw if not m.get("mode")]

    if cat_paper_ids is not None:
        matches = [m for m in matches_raw if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids]
    else:
        matches = matches_raw

    if not matches:
        return {"models": [], "correlations": {}, "agreement": {}, "n_common_papers": 0, "category": category, "mode": mode}

    paper_titles = {}
    async for p in db.papers.find({}, {"_id": 0, "id": 1, "title": 1}):
        paper_titles[p["id"]] = p["title"]

    model_keys = set()
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        model_keys.add(key)
    model_keys = sorted(model_keys)

    paper_ids = set()
    for m in matches:
        paper_ids.add(m["paper1_id"])
        paper_ids.add(m["paper2_id"])
    paper_ids = sorted(paper_ids)

    model_paper_stats = {mk: {} for mk in model_keys}
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        for pid in [p1, p2]:
            if pid not in model_paper_stats[key]:
                model_paper_stats[key][pid] = {"wins": 0, "total": 0}
            model_paper_stats[key][pid]["total"] += 1
        if w and w in model_paper_stats[key]:
            model_paper_stats[key][w]["wins"] += 1

    model_win_rates = {}
    common_papers = set(paper_ids)
    for mk in model_keys:
        model_win_rates[mk] = {}
        papers_with_data = set()
        for pid in paper_ids:
            s = model_paper_stats[mk].get(pid)
            if s and s["total"] >= 3:
                model_win_rates[mk][pid] = s["wins"] / s["total"]
                papers_with_data.add(pid)
        common_papers &= papers_with_data
    common_papers = sorted(common_papers)

    correlations = {}
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j:
                continue
            rates1 = [model_win_rates[m1].get(pid, 0.5) for pid in common_papers]
            rates2 = [model_win_rates[m2].get(pid, 0.5) for pid in common_papers]
            if len(rates1) >= 5:
                spearman_r, spearman_p = scipy_stats.spearmanr(rates1, rates2)
                pearson_r, pearson_p = scipy_stats.pearsonr(rates1, rates2)
                correlations[f"{m1} vs {m2}"] = {
                    "spearman_r": round(float(spearman_r), 3),
                    "spearman_p": round(float(spearman_p), 4),
                    "pearson_r": round(float(pearson_r), 3),
                    "pearson_p": round(float(pearson_p), 4),
                    "n_papers": len(common_papers),
                }

    # Agreement rate: for pairs judged by multiple models,
    # use majority vote per model (handles re-matches correctly)
    from collections import Counter

    # Compute overall win rate per paper for difficulty classification
    paper_wins_all = Counter()
    paper_total_all = Counter()
    for m in matches:
        paper_total_all[m["paper1_id"]] += 1
        paper_total_all[m["paper2_id"]] += 1
        w = m.get("winner_id")
        if w:
            paper_wins_all[w] += 1
    paper_wr = {pid: paper_wins_all[pid] / max(paper_total_all[pid], 1) for pid in paper_ids}

    pair_model_votes = {}  # {(p1,p2): {model: [winner_id, ...]}}
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pair not in pair_model_votes:
            pair_model_votes[pair] = {}
        if key not in pair_model_votes[pair]:
            pair_model_votes[pair][key] = []
        pair_model_votes[pair][key].append(m.get("winner_id"))

    # Resolve each model's verdict per pair via majority vote
    pair_verdicts = {}
    for pair, model_votes in pair_model_votes.items():
        pair_verdicts[pair] = {}
        for model_key, votes in model_votes.items():
            most_common = Counter(votes).most_common(1)[0][0]
            pair_verdicts[pair][model_key] = most_common

    CLEAR_CUT_THRESHOLD = 0.10  # 10pp win rate difference

    agreement_counts = {}
    agreement_by_difficulty = {}  # {pair_key: {clear: {agree, disagree}, contested: {agree, disagree}}}
    for pair, verdicts in pair_verdicts.items():
        models_involved = sorted(verdicts.keys())
        p1, p2 = pair
        wr_diff = abs(paper_wr.get(p1, 0.5) - paper_wr.get(p2, 0.5))
        is_clear = wr_diff >= CLEAR_CUT_THRESHOLD

        for i in range(len(models_involved)):
            for j in range(i + 1, len(models_involved)):
                m1, m2 = models_involved[i], models_involved[j]
                pair_key = f"{m1} vs {m2}"
                if pair_key not in agreement_counts:
                    agreement_counts[pair_key] = {"agree": 0, "disagree": 0}
                if pair_key not in agreement_by_difficulty:
                    agreement_by_difficulty[pair_key] = {
                        "clear": {"agree": 0, "disagree": 0},
                        "contested": {"agree": 0, "disagree": 0},
                    }
                agreed = verdicts[m1] == verdicts[m2]
                bucket = "clear" if is_clear else "contested"
                if agreed:
                    agreement_counts[pair_key]["agree"] += 1
                    agreement_by_difficulty[pair_key][bucket]["agree"] += 1
                else:
                    agreement_counts[pair_key]["disagree"] += 1
                    agreement_by_difficulty[pair_key][bucket]["disagree"] += 1

    agreement = {}
    for pair_key, counts in agreement_counts.items():
        total = counts["agree"] + counts["disagree"]
        if total > 0:
            diff = agreement_by_difficulty.get(pair_key, {})
            clear = diff.get("clear", {"agree": 0, "disagree": 0})
            contested = diff.get("contested", {"agree": 0, "disagree": 0})
            clear_total = clear["agree"] + clear["disagree"]
            contested_total = contested["agree"] + contested["disagree"]
            agreement[pair_key] = {
                "agree": counts["agree"],
                "disagree": counts["disagree"],
                "total": total,
                "rate": round(counts["agree"] / total * 100, 1),
                "clear_cut": {
                    "agree": clear["agree"],
                    "total": clear_total,
                    "rate": round(clear["agree"] / max(clear_total, 1) * 100, 1) if clear_total > 0 else None,
                },
                "contested": {
                    "agree": contested["agree"],
                    "total": contested_total,
                    "rate": round(contested["agree"] / max(contested_total, 1) * 100, 1) if contested_total > 0 else None,
                },
            }

    model_summaries = {}
    for mk in model_keys:
        total_by_model = sum(1 for m in matches if f"{m.get('model_used',{}).get('provider','')}/{m.get('model_used',{}).get('model','')}" == mk)
        model_summaries[mk] = {
            "total_matches": total_by_model,
            "papers_judged": len(model_paper_stats[mk]),
        }

    scatter_data = []
    for pid in common_papers:
        entry = {"id": pid, "title": paper_titles.get(pid, "Unknown")[:50]}
        for mk in model_keys:
            short_name = mk.split("/")[-1]
            entry[short_name] = round(model_win_rates[mk].get(pid, 0.5) * 100, 1)
        scatter_data.append(entry)

    # Sort correlations and agreement by the same key order
    sorted_corr_keys = sorted(correlations.keys())
    sorted_correlations = {k: correlations[k] for k in sorted_corr_keys}

    sorted_agree_keys = sorted(agreement.keys())
    sorted_agreement = {k: agreement[k] for k in sorted_agree_keys}

    return {
        "models": [{"key": mk, "short": mk.split("/")[-1], **model_summaries.get(mk, {})} for mk in model_keys],
        "correlations": sorted_correlations,
        "agreement": sorted_agreement,
        "scatter_data": scatter_data,
        "n_common_papers": len(common_papers),
        "category": category,
        "mode": mode,
    }
