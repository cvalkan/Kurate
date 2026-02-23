from fastapi import APIRouter, Query, Request
from typing import Optional
from datetime import datetime, timezone, timedelta
from collections import Counter
import asyncio
import time
from core.config import db, logger, CATEGORIES
from services.ranking import compute_leaderboard, compute_leaderboard_async, calculate_confidence_interval, wilson_margin_pct

router = APIRouter(prefix="/api")

# Pre-computed cache — refreshed in the background, never blocks requests
_cache = {"ts": 0, "categories": {}, "total_papers": 0, "total_matches": 0, "warming_up": True}
_CACHE_TTL = 60  # Increased from 20s to reduce recomputation frequency
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
    _t0 = time.time()
    all_papers = await db.papers.find(
        {"summaries": {"$exists": True, "$ne": {}}},
        {"_id": 0, "full_text": 0, "abstract": 0}
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

        full = await compute_leaderboard_async(cat_papers, cat_matches)
        # Yield to event loop after CPU-bound leaderboard computation
        await asyncio.sleep(0)

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

        categories_data[cat_id] = {
            "all": full,
            "recent": filter_and_rerank(recent_cutoff),
            "week": filter_and_rerank(utc_now - timedelta(weeks=1)),
            "month": filter_and_rerank(utc_now - timedelta(days=30)),
            "_matches": len(cat_matches),
            "_papers": len(cat_papers),
            "_is_ranking": True,  # Placeholder — updated after progress computation
        }

    # --- Derive "all papers" leaderboard from per-category results (no extra compute_leaderboard call) ---
    paper_cat_lookup = {p["id"]: p.get("categories", ["unknown"])[0] for p in all_papers}
    all_full = []
    for cat_id, cat_data in categories_data.items():
        for entry in cat_data.get("all", []):
            all_full.append({**entry, "primary_category": cat_id})
    # Re-rank by score globally
    all_full.sort(key=lambda e: (e.get("score", 0), e.get("wins", 0)), reverse=True)
    for i, entry in enumerate(all_full):
        entry["rank"] = i + 1

    all_periods = {"all": all_full}
    for period_key in ("recent", "week", "month"):
        filtered, _ = _apply_period_filter(all_full, period_key)
        all_periods[period_key] = filtered

    _cache.update({
        "ts": time.time(),
        "categories": categories_data,
        "total_papers": len(all_papers),
        "total_matches": len(all_matches),
        "warming_up": False,  # Cache is now ready
        "_raw_papers": all_papers,
        "_raw_matches": all_matches,
        "_raw_matches_all": all_matches_raw,
        "_match_index": match_index,
        "_paper_cat_lookup": paper_cat_lookup,
        "_all_papers_leaderboard": all_periods,
    })
    _t1 = time.time()
    logger.info(f"Cache refresh took {_t1 - _t0:.1f}s ({len(all_papers)} papers, {len(all_matches)} matches, {len(categories_data)} categories)")

    # Pre-compute failed match counts per category (for admin panel)
    failed_by_cat = Counter()
    async for m in db.matches.find(
        {"failed": True, "mode": {"$exists": False}},
        {"_id": 0, "primary_category": 1},
    ):
        failed_by_cat[m.get("primary_category", "unknown")] += 1
    _cache["_failed_by_cat"] = dict(failed_by_cat)

    # Pre-compute PDF counts and storage stats per category (for admin panel)
    pdf_by_cat = Counter()
    storage_chars_by_cat = Counter()
    storage_chars_total = 0
    async for p in db.papers.find(
        {"full_text": {"$ne": None}},
        {"_id": 0, "categories": 1, "full_text": 1},
    ):
        cat = p.get("categories", ["unknown"])[0] if p.get("categories") else "unknown"
        pdf_by_cat[cat] += 1
        chars = len(p.get("full_text", ""))
        storage_chars_by_cat[cat] += chars
        storage_chars_total += chars
    _cache["_pdf_by_cat"] = dict(pdf_by_cat)
    _cache["_storage"] = {
        "total_chars": storage_chars_total,
        "total_with_text": sum(pdf_by_cat.values()),
        "chars_by_cat": dict(storage_chars_by_cat),
    }

    # --- Pre-compute progress data per category (avoids DB queries on admin panel) ---
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 10)
    ci_target_general = settings.get("ci_target_general", 15)
    parallel_agents = settings.get("parallel_agents", 5)

    progress_by_cat = {}
    for cat_id in active_cats:
        cat_data = categories_data.get(cat_id, {})
        entries = cat_data.get("all", [])
        total_papers = len(entries)
        if total_papers == 0:
            progress_by_cat[cat_id] = {
                "total_papers": 0, "goals_met": True, "category": cat_id,
            }
            continue

        # Build compared_pairs set from matches
        cat_paper_ids = {e["id"] for e in entries}
        compared_pairs = set()
        for m in all_matches:
            p1, p2 = m["paper1_id"], m["paper2_id"]
            if p1 in cat_paper_ids and p2 in cat_paper_ids:
                compared_pairs.add(tuple(sorted([p1, p2])))

        # Sort by win rate for top-K identification
        sorted_entries = sorted(
            entries,
            key=lambda e: e.get("wins", 0) / max(e.get("comparisons", 0), 1),
            reverse=True,
        )
        top_k_list = sorted_entries[:min(top_k, total_papers)]
        top_k_ids = {e["id"] for e in top_k_list}

        # Goal 1: General CI
        general_converged = general_total = general_additional = 0
        widest_general = 0.0
        general_margins = []
        for e in entries:
            if e["id"] in top_k_ids:
                continue
            general_total += 1
            n, w = e.get("comparisons", 0), e.get("wins", 0)
            margin = wilson_margin_pct(w, n)
            general_margins.append(margin)
            if margin <= ci_target_general:
                general_converged += 1
            else:
                general_additional += max(3, int(n * (margin / ci_target_general) ** 2) - n) if n >= 2 else 30
            widest_general = max(widest_general, margin)

        goal1_met = general_converged == general_total if general_total > 0 else True
        median_general = sorted(general_margins)[len(general_margins) // 2] if general_margins else 0.0
        matches_for_goal1 = 0 if goal1_met else max(0, int(general_additional * 0.6))

        # Goal 2: Top-K CI
        topk_converged = topk_additional = 0
        topk_total = len(top_k_ids)
        widest_topk = 0.0
        topk_margins = []
        for e in top_k_list:
            n, w = e.get("comparisons", 0), e.get("wins", 0)
            margin = wilson_margin_pct(w, n)
            topk_margins.append(margin)
            if margin <= ci_target:
                topk_converged += 1
            else:
                topk_additional += max(3, int(n * (margin / ci_target) ** 2) - n) if n >= 2 else 40
            widest_topk = max(widest_topk, margin)

        goal2_met = topk_converged == topk_total if topk_total > 0 else True
        median_topk = sorted(topk_margins)[len(topk_margins) // 2] if topk_margins else 0.0
        matches_for_goal2 = 0 if goal2_met else max(0, int(topk_additional * 0.6))

        # Goal 3: Cross-matches among top-K
        topk_id_list = [e["id"] for e in top_k_list]
        topk_total_pairs = len(topk_id_list) * (len(topk_id_list) - 1) // 2
        topk_matched_pairs = sum(
            1 for i in range(len(topk_id_list))
            for j in range(i + 1, len(topk_id_list))
            if tuple(sorted([topk_id_list[i], topk_id_list[j]])) in compared_pairs
        )
        goal3_met = topk_matched_pairs == topk_total_pairs
        matches_for_goal3 = topk_total_pairs - topk_matched_pairs

        total_est = max(matches_for_goal1, matches_for_goal2) + matches_for_goal3
        est_minutes = max(0, round(total_est * (10.0 / max(parallel_agents, 1)) / 60))

        cat_matches_done = sum(e.get("comparisons", 0) for e in entries) // 2

        progress_by_cat[cat_id] = {
            "total_papers": total_papers,
            "total_matches": cat_matches_done,
            "papers_with_pdf": pdf_by_cat.get(cat_id, 0),
            "category": cat_id,
            "goals_met": bool(goal1_met and goal2_met and goal3_met),
            "goal1": {
                "met": bool(goal1_met),
                "label": f"General CI \u2264 {ci_target_general}%",
                "done": int(general_converged),
                "total": int(general_total),
                "median_margin": round(median_general, 1),
            },
            "goal2": {
                "met": bool(goal2_met),
                "label": f"Top-{topk_total} CI \u2264 {ci_target}%",
                "done": int(topk_converged),
                "total": int(topk_total),
                "median_margin": round(median_topk, 1),
            },
            "goal3": {
                "met": bool(goal3_met),
                "label": f"Top-{len(topk_id_list)} cross-matches",
                "done": int(topk_matched_pairs),
                "total": int(topk_total_pairs),
            },
            "estimated_matches_remaining": int(total_est),
            "estimated_minutes": int(est_minutes),
        }

    _cache["_progress"] = progress_by_cat
    await asyncio.sleep(0)  # Yield after progress computation

    # --- Pre-compute summary stats (avoids expensive DB scan on /stats) ---
    summary_stats_by_cat = {"__all__": {"models": {}, "papers_with_summaries": 0, "papers_with_all_3": 0}}
    for p in all_papers:
        cat = p.get("categories", ["unknown"])[0] if p.get("categories") else "unknown"
        sums = p.get("summaries", {})
        if not sums:
            continue
        if cat not in summary_stats_by_cat:
            summary_stats_by_cat[cat] = {"models": {}, "papers_with_summaries": 0, "papers_with_all_3": 0}
        summary_stats_by_cat[cat]["papers_with_summaries"] += 1
        summary_stats_by_cat["__all__"]["papers_with_summaries"] += 1
        model_count = 0
        for mk, text in sums.items():
            if not isinstance(text, str) or len(text) < 50:
                continue
            model_count += 1
            for bucket in (cat, "__all__"):
                if mk not in summary_stats_by_cat[bucket]["models"]:
                    summary_stats_by_cat[bucket]["models"][mk] = {"summaries": 0}
                summary_stats_by_cat[bucket]["models"][mk]["summaries"] += 1
        if model_count >= 3:
            summary_stats_by_cat[cat]["papers_with_all_3"] += 1
            summary_stats_by_cat["__all__"]["papers_with_all_3"] += 1

    _cache["_summary_stats"] = summary_stats_by_cat

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
    search: Optional[str] = Query(None, description="Search papers by title (case-insensitive)", max_length=200),
    limit: int = Query(10000, description="Max papers to return", ge=1, le=100000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
):
    # Tag-based filtering: compute on-demand
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()][:50]  # Cap at 50 tags
        if tag_list:
            return await _compute_tag_leaderboard(tag_list, period, limit, offset, tag_mode, global_stats, show_all, search)

    # Show all papers from all categories (tag panel open, no tags selected)
    if show_all:
        return await _compute_all_papers_leaderboard(period, limit, offset, search)

    # Default: use pre-computed primary category cache
    cache = await _get_cached_leaderboard()
    
    # If cache is still warming up, return indicator
    if cache.get("warming_up", True) and not cache["categories"]:
        return {
            "leaderboard": [],
            "total_papers": 0,
            "total_in_period": 0,
            "total_matches": 0,
            "is_ranking": False,
            "period": period,
            "category": category,
            "tags": None,
            "tag_mode": None,
            "warming_up": True,
            "message": "Leaderboard data is loading, please wait...",
        }
    
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
        "warming_up": False,
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

    full = await compute_leaderboard_async(display_papers, display_matches)

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
        # Use leaderboard background cache (refreshed every 20s)
        total_papers = _cache.get("total_papers", 0)
        total_matches = _cache.get("total_matches", 0)
        failed_by_cat = _cache.get("_failed_by_cat", {})
        failed_matches = sum(failed_by_cat.values())
        # Fallback to DB only if cache is completely empty (cold boot)
        if total_papers == 0 and not _cache.get("categories"):
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
    if summary_doc and summary_doc.get("system_prompt"):
        summary_prompt = {
            "system_prompt": summary_doc.get("system_prompt", ""),
            "user_prompt": summary_doc.get("user_prompt", ""),
        }
    else:
        # Use the pre-comparison impact assessment prompt
        from services.llm import IMPACT_ASSESSMENT_PROMPT
        summary_prompt = {
            "system_prompt": IMPACT_ASSESSMENT_PROMPT["system_prompt"],
            "user_prompt": IMPACT_ASSESSMENT_PROMPT["user_prompt"],
        }

    return {
        "evaluation": eval_prompt,
        "summary": summary_prompt,
    }


# Cache for model-correlation and convergence endpoints (keyed by category+mode)
_analysis_cache = {}  # (endpoint, category, mode) -> {"data": ..., "ts": float}
_ANALYSIS_CACHE_TTL = 300  # 5 minutes


def _get_analysis_cached(endpoint: str, category: str, mode: str = ""):
    key = (endpoint, category or "__all__", mode or "")
    entry = _analysis_cache.get(key)
    if entry and time.time() - entry["ts"] < _ANALYSIS_CACHE_TTL:
        return entry["data"]
    return None


def _set_analysis_cached(endpoint: str, category: str, mode: str, data):
    key = (endpoint, category or "__all__", mode or "")
    _analysis_cache[key] = {"data": data, "ts": time.time()}


@router.get("/model-correlation")
async def get_model_correlation(
    category: Optional[str] = Query(None, description="Filter by category (None = all)"),
    mode: Optional[str] = Query(None, description="Match mode: None=standard, 'prediction', 'prediction-fulltext'"),
):
    """Correlation analysis between the 3 LLMs used for rankings."""
    cached = _get_analysis_cached("model-correlation", category, mode)
    if cached:
        return cached
    result = await _compute_model_correlation(category, mode)
    _set_analysis_cached("model-correlation", category, mode, result)
    return result


async def _compute_model_correlation(category, mode):
    import numpy as np
    from scipy import stats as scipy_stats

    # Use leaderboard cache when possible (standard matches, no mode filter)
    use_cache = not mode
    cat_paper_ids = None

    if use_cache and _cache.get("_raw_matches"):
        matches_raw = _cache["_raw_matches"]  # Already filtered: completed=True, failed!=True, no mode
        if category:
            cat_data = _cache.get("categories", {}).get(category, {})
            cat_paper_ids = {e["id"] for e in cat_data.get("all", [])} if cat_data else set()
        matches = [m for m in matches_raw if not cat_paper_ids or (m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids)]
        paper_titles = {p["id"]: p["title"] for p in _cache.get("_raw_papers", [])}
    else:
        if category:
            cat_paper_ids = set()
            async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
                cat_paper_ids.add(p["id"])

        matches_raw = await db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "model_used": {"$exists": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1, "mode": 1},
        ).to_list(100000)

        if mode:
            matches_raw = [m for m in matches_raw if m.get("mode") == mode]
        else:
            matches_raw = [m for m in matches_raw if not m.get("mode")]

        matches = [m for m in matches_raw if not cat_paper_ids or (m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids)]
        paper_titles = {}
        async for p in db.papers.find({}, {"_id": 0, "id": 1, "title": 1}):
            paper_titles[p["id"]] = p["title"]

    if not matches:
        return {"models": [], "correlations": {}, "agreement": {}, "n_common_papers": 0, "category": category, "mode": mode}

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



@router.get("/convergence")
async def get_convergence(
    category: Optional[str] = Query(None),
    steps: int = Query(20),
):
    """Convergence analysis: how ranking stability improves as matches accumulate."""
    cached = _get_analysis_cached("convergence", category, str(steps))
    if cached:
        return cached
    result = await _compute_convergence(category, steps)
    _set_analysis_cached("convergence", category, str(steps), result)
    return result


async def _compute_convergence(category, steps):
    """Convergence analysis: how ranking stability improves as matches accumulate."""
    from scipy import stats as scipy_stats
    from collections import defaultdict
    from core.auth import get_settings

    settings = await get_settings()
    top_k_focus = settings.get("top_k_focus", 10)

    # Use leaderboard cache when available (avoids DB queries)
    if category and _cache.get("categories", {}).get(category):
        cat_data = _cache["categories"][category]
        papers = [{"id": e["id"], "title": e["title"]} for e in cat_data.get("all", [])]
    else:
        paper_query = {"categories.0": category} if category else {}
        papers = await db.papers.find(paper_query, {"_id": 0, "id": 1, "title": 1}).to_list(10000)

    if len(papers) < 5:
        return {"status": "no_data"}

    pid_set = {p["id"] for p in papers}

    # Use _raw_matches_all from cache (has created_at), fall back to DB
    raw_from_cache = _cache.get("_raw_matches_all", [])
    if raw_from_cache:
        all_matches = [m for m in raw_from_cache if not m.get("mode")
                       and m["paper1_id"] in pid_set and m["paper2_id"] in pid_set]
    else:
        match_query = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}
        if category:
            match_query["paper1_id"] = {"$in": list(pid_set)}
        all_matches = await db.matches.find(
            match_query,
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1, "created_at": 1},
        ).to_list(200000)
        all_matches = [m for m in all_matches if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set]

    if len(all_matches) < 20:
        return {"status": "no_data"}

    # Sort chronologically
    all_matches.sort(key=lambda m: m.get("created_at", ""))

    # Ground truth ranking
    paper_dicts = [{"id": p["id"], "title": p.get("title", "")} for p in papers]
    gt_lb = await compute_leaderboard_async(paper_dicts, all_matches)
    gt_rank = {e["id"]: e["rank"] for e in gt_lb}
    gt_score = {e["id"]: e["score"] for e in gt_lb}
    n_papers = len(pid_set)
    top_k_values = [top_k_focus] if top_k_focus < n_papers else [min(10, n_papers - 1)]
    gt_topk = {k: set(e["id"] for e in gt_lb if e["rank"] <= k) for k in top_k_values}

    total = len(all_matches)
    steps = min(max(steps, 5), 40)

    # Compute max avg matches/paper for integer x-axis
    full_counts = defaultdict(int)
    for m in all_matches:
        full_counts[m["paper1_id"]] += 1
        full_counts[m["paper2_id"]] += 1
    active_pids = [pid for pid in pid_set if full_counts[pid] > 0]
    max_avg = sum(full_counts[pid] for pid in active_pids) / max(len(active_pids), 1)

    step_size = max(1, int(max_avg / steps))
    if step_size >= 5:
        step_size = (step_size // 5) * 5
    x_targets = list(range(step_size, int(max_avg) + step_size, step_size))
    if not x_targets or x_targets[-1] < max_avg * 0.95:
        x_targets.append(int(max_avg) + 1)

    curve = []
    for target_avg in x_targets:
        lo, hi = 1, total
        best_n = total
        while lo <= hi:
            mid = (lo + hi) // 2
            counts = defaultdict(int)
            for m in all_matches[:mid]:
                counts[m["paper1_id"]] += 1
                counts[m["paper2_id"]] += 1
            active = [pid for pid in pid_set if counts[pid] > 0]
            if not active:
                lo = mid + 1
                continue
            avg = sum(counts[pid] for pid in active) / len(active)
            if avg < target_avg:
                lo = mid + 1
            else:
                best_n = mid
                hi = mid - 1

        subset = all_matches[:best_n]
        paper_match_count = defaultdict(int)
        for m in subset:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1

        active = [pid for pid in pid_set if paper_match_count[pid] > 0]
        if len(active) < 5:
            continue

        avg_mpp = sum(paper_match_count[pid] for pid in active) / len(active)

        sub_lb = await compute_leaderboard_async(paper_dicts, subset)
        sub_rank = {e["id"]: e["rank"] for e in sub_lb}
        sub_score = {e["id"]: e["score"] for e in sub_lb}

        common = [pid for pid in active if pid in gt_rank and pid in sub_rank]
        if len(common) < 5:
            continue

        sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common], [gt_rank[p] for p in common])
        kt, _ = scipy_stats.kendalltau([sub_rank[p] for p in common], [gt_rank[p] for p in common])
        pr, _ = scipy_stats.pearsonr([sub_score.get(p, 0) for p in common], [gt_score.get(p, 0) for p in common])

        topk = {}
        for k in top_k_values:
            sub_topk = set(e["id"] for e in sub_lb if e["rank"] <= k)
            overlap = len(sub_topk & gt_topk[k])
            topk[f"top_{k}"] = round(overlap / k * 100, 1)

        point = {
            "matches": best_n,
            "avg_matches_per_paper": round(avg_mpp),
            "papers_covered": len(active),
            "spearman": round(sp, 4),
            "kendall": round(kt, 4),
            "pearson": round(pr, 4),
        }
        point.update(topk)
        curve.append(point)

    return {
        "status": "ok",
        "category": category,
        "total_matches": total,
        "total_papers": n_papers,
        "top_k_values": top_k_values,
        "curve": curve,
    }

