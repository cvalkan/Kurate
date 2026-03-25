from fastapi import APIRouter, Query, Request
from typing import Optional
from datetime import datetime, timezone, timedelta
from collections import Counter
import asyncio
import time
from core.config import db, logger, CATEGORIES
from routers.validation_utils import collect_all
from services.ranking import compute_leaderboard, compute_leaderboard_async, calculate_confidence_interval, wilson_margin_pct, compute_paper_score

router = APIRouter(prefix="/api")

# Pre-computed cache — refreshed in the background, never blocks requests
_cache = {"ts": 0, "categories": {}, "total_papers": 0, "total_matches": 0, "warming_up": True}
_bg_task_started = False
_cache_dirty = asyncio.Event()  # Set by compare/fetch loops when data changes

# Cached match counts — updated on data change, not per-request.
# Eliminates a 50-200ms COLLSCAN on the matches collection for every leaderboard request.
_match_count_cache = {}  # category_or_"__all__" -> {"count": int, "ts": float}
_MATCH_COUNT_TTL = 300  # 5 min TTL (safety net — normally invalidated by data change)


async def _get_match_count(category: str = None) -> int:
    """Return cached match count for a category (or all). Refreshes on miss/stale."""
    key = category or "__all__"
    cached = _match_count_cache.get(key)
    if cached and (time.time() - cached["ts"]) < _MATCH_COUNT_TTL:
        return cached["count"]
    q = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}
    if category:
        q["primary_category"] = category
    count = await db.matches.count_documents(q)
    _match_count_cache[key] = {"count": count, "ts": time.time()}
    return count


def _invalidate_match_counts():
    """Call when matches are added/changed. Clears the cache."""
    _match_count_cache.clear()


def notify_data_changed():
    """Call this when matches or papers are added/changed. Triggers a cache refresh."""
    _cache_dirty.set()
    _invalidate_match_counts()

# Tag query cache — keyed on (frozenset(tags), period, tag_mode, global_stats, show_all)
_tag_cache = {}  # key -> {"ts": float, "result": dict}
_TAG_CACHE_TTL = 20  # Same as main cache TTL
_TAG_CACHE_MAX = 100  # Max cached tag combos


def _apply_period_filter(full_leaderboard, period, added_at_lookup=None):
    """Apply period filter to a pre-ranked leaderboard. Returns (filtered_list, total_in_period)."""
    if period == "all":
        return full_leaderboard, len(full_leaderboard)

    utc_now = datetime.now(timezone.utc)

    if period == "recent" and added_at_lookup:
        # "Most Recent" = papers added to system in last 48h, sorted by published date
        cutoff = utc_now - timedelta(hours=48)
        filtered = [{**e} for e in full_leaderboard
                    if added_at_lookup.get(e["id"], datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        if filtered:
            for i, e in enumerate(filtered):
                e["rank"] = i + 1
            return filtered, len(filtered)
        # Fallback if no recent papers: use latest published day

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



async def _compute_summary_stats_agg():
    """Compute summary stats per category using MongoDB aggregation.
    
    Runs entirely server-side — no summaries loaded into Python memory.
    Replaces the old approach that iterated over all_papers with summaries in RAM.
    """
    # Pipeline: for each paper, extract summary model keys and token tracking,
    # then group by category.
    pipeline = [
        {"$match": {"summaries": {"$exists": True, "$ne": {}}}},
        {"$project": {
            "_id": 0,
            "cat": {"$arrayElemAt": ["$categories", 0]},
            "summary_keys": {"$objectToArray": {"$ifNull": ["$summaries", {}]}},
            "token_keys": {"$objectToArray": {"$ifNull": ["$summary_tokens", {}]}},
        }},
        {"$unwind": "$summary_keys"},
        # Filter out short summaries (< 50 chars) — match the old Python logic
        {"$match": {"summary_keys.v": {"$type": "string"}, "$expr": {"$gte": [{"$strLenCP": "$summary_keys.v"}, 50]}}},
        {"$group": {
            "_id": {"cat": "$cat", "model": "$summary_keys.k"},
            "count": {"$sum": 1},
        }},
    ]

    # Run the per-model-per-category counts
    model_counts = {}  # (cat, model) -> count
    async for doc in db.papers.aggregate(pipeline, allowDiskUse=True):
        cat = doc["_id"]["cat"] or "unknown"
        model = doc["_id"]["model"]
        model_counts[(cat, model)] = doc["count"]

    # Also get per-paper model counts for papers_with_all_3
    pipeline_all3 = [
        {"$match": {"summaries": {"$exists": True, "$ne": {}}}},
        {"$project": {
            "_id": 0,
            "cat": {"$arrayElemAt": ["$categories", 0]},
            "summary_keys": {"$objectToArray": {"$ifNull": ["$summaries", {}]}},
        }},
        # Count valid summaries per paper (>= 50 chars)
        {"$project": {
            "cat": 1,
            "valid_summaries": {
                "$filter": {
                    "input": "$summary_keys",
                    "as": "s",
                    "cond": {"$and": [
                        {"$eq": [{"$type": "$$s.v"}, "string"]},
                        {"$gte": [{"$strLenCP": "$$s.v"}, 50]},
                    ]},
                },
            },
        }},
        {"$project": {
            "cat": 1,
            "n_models": {"$size": "$valid_summaries"},
        }},
        {"$group": {
            "_id": "$cat",
            "papers_with_summaries": {"$sum": 1},
            "papers_with_all_3": {"$sum": {"$cond": [{"$gte": ["$n_models", 3]}, 1, 0]}},
        }},
    ]

    cat_paper_counts = {}  # cat -> {papers_with_summaries, papers_with_all_3}
    async for doc in db.papers.aggregate(pipeline_all3, allowDiskUse=True):
        cat = doc["_id"] or "unknown"
        cat_paper_counts[cat] = {
            "papers_with_summaries": doc["papers_with_summaries"],
            "papers_with_all_3": doc["papers_with_all_3"],
        }

    # Token tracking aggregation (separate — only papers with tracked tokens)
    pipeline_tokens = [
        {"$match": {"summary_tokens": {"$exists": True, "$ne": {}}}},
        {"$project": {
            "_id": 0,
            "cat": {"$arrayElemAt": ["$categories", 0]},
            "token_pairs": {"$objectToArray": "$summary_tokens"},
        }},
        {"$unwind": "$token_pairs"},
        {"$match": {"token_pairs.v": {"$type": "object"}}},
        {"$group": {
            "_id": {"cat": "$cat", "model": "$token_pairs.k"},
            "tracked_input": {"$sum": {"$ifNull": ["$token_pairs.v.input", 0]}},
            "tracked_output": {"$sum": {"$ifNull": ["$token_pairs.v.output", 0]}},
            "tracked_thinking": {"$sum": {"$ifNull": ["$token_pairs.v.thinking", 0]}},
            "tracked_count": {"$sum": 1},
        }},
    ]

    token_stats = {}  # (cat, model) -> {tracked_input, ...}
    async for doc in db.papers.aggregate(pipeline_tokens, allowDiskUse=True):
        cat = doc["_id"]["cat"] or "unknown"
        model = doc["_id"]["model"]
        token_stats[(cat, model)] = {
            "tracked_input": doc["tracked_input"],
            "tracked_output": doc["tracked_output"],
            "tracked_thinking": doc["tracked_thinking"],
            "tracked_count": doc["tracked_count"],
        }

    # Assemble into the same structure the admin endpoint expects
    all_cats = set(c for c, _ in model_counts) | set(cat_paper_counts.keys())
    all_models = set(m for _, m in model_counts)

    result = {"__all__": {"models": {}, "papers_with_summaries": 0, "papers_with_all_3": 0}}
    for cat in all_cats:
        cp = cat_paper_counts.get(cat, {})
        result[cat] = {
            "models": {},
            "papers_with_summaries": cp.get("papers_with_summaries", 0),
            "papers_with_all_3": cp.get("papers_with_all_3", 0),
        }
        result["__all__"]["papers_with_summaries"] += cp.get("papers_with_summaries", 0)
        result["__all__"]["papers_with_all_3"] += cp.get("papers_with_all_3", 0)

    for (cat, model), count in model_counts.items():
        ts = token_stats.get((cat, model), {})
        entry = {
            "summaries": count,
            "tracked_input": ts.get("tracked_input", 0),
            "tracked_output": ts.get("tracked_output", 0),
            "tracked_thinking": ts.get("tracked_thinking", 0),
            "tracked_count": ts.get("tracked_count", 0),
        }
        result[cat]["models"][model] = entry
        # Accumulate into __all__
        if model not in result["__all__"]["models"]:
            result["__all__"]["models"][model] = {"summaries": 0, "tracked_input": 0, "tracked_output": 0, "tracked_thinking": 0, "tracked_count": 0}
        for k in ("summaries", "tracked_input", "tracked_output", "tracked_thinking", "tracked_count"):
            result["__all__"]["models"][model][k] += entry[k]

    return result


async def _refresh_cache():
    """Lightweight metadata refresh — computes only admin stats and small caches.
    
    Phase 3: All leaderboard serving now uses the `rankings` DB collection directly.
    This function only maintains small metadata caches (~20MB total) for admin panel,
    tags, categories, summary stats, progress, and archives.
    """
    global _cache
    _t0 = time.time()

    from core.auth import get_settings
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))

    # --- Counts ---
    total_papers = await db.rankings.count_documents({})
    total_matches = await _get_match_count()

    # --- Failed match counts per category ---
    failed_by_cat = Counter()
    async for m in db.matches.find(
        {"failed": True, "mode": {"$exists": False}},
        {"_id": 0, "primary_category": 1},
    ):
        failed_by_cat[m.get("primary_category", "unknown")] += 1

    # --- PDF/storage stats via aggregation ---
    pdf_by_cat = Counter()
    storage_chars_by_cat = Counter()
    storage_chars_total = 0
    async for doc in db.papers.aggregate([
        {"$match": {"full_text": {"$ne": None}}},
        {"$project": {"cat": {"$arrayElemAt": ["$categories", 0]}, "chars": {"$strLenCP": {"$ifNull": ["$full_text", ""]}}}},
        {"$group": {"_id": "$cat", "count": {"$sum": 1}, "chars": {"$sum": "$chars"}}},
    ]):
        cat = doc["_id"] or "unknown"
        pdf_by_cat[cat] = doc["count"]
        storage_chars_by_cat[cat] = doc["chars"]
        storage_chars_total += doc["chars"]

    # --- Progress per category (from rankings DB) ---
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 10)
    ci_target_general = settings.get("ci_target_general", 15)
    parallel_agents = settings.get("parallel_agents", 5)

    progress_by_cat = {}
    for cat_id in active_cats:
        entries = await db.rankings.find(
            {"category": cat_id},
            {"_id": 0, "paper_id": 1, "wins": 1, "losses": 1, "comparisons": 1, "score": 1}
        ).sort("score", -1).to_list(10000)

        cat_total = len(entries)
        if cat_total == 0:
            progress_by_cat[cat_id] = {"total_papers": 0, "goals_met": True, "category": cat_id}
            continue

        top_k_list = entries[:min(top_k, cat_total)]
        top_k_ids = {e["paper_id"] for e in top_k_list}

        # Goal 1: General CI
        general_converged = general_total = general_additional = 0
        widest_general = 0.0
        general_margins = []
        for e in entries:
            if e["paper_id"] in top_k_ids:
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

        # Goal 3: Cross-matches among top-K (use targeted count queries, not full scan)
        topk_id_list = [e["paper_id"] for e in top_k_list]
        topk_total_pairs = len(topk_id_list) * (len(topk_id_list) - 1) // 2
        topk_matched_pairs = 0
        for i in range(len(topk_id_list)):
            for j in range(i + 1, len(topk_id_list)):
                p1, p2 = topk_id_list[i], topk_id_list[j]
                has_match = await db.matches.count_documents({
                    "completed": True, "failed": {"$ne": True}, "primary_category": cat_id,
                    "mode": {"$exists": False},
                    "$or": [
                        {"paper1_id": p1, "paper2_id": p2},
                        {"paper1_id": p2, "paper2_id": p1},
                    ],
                }) > 0
                if has_match:
                    topk_matched_pairs += 1
        goal3_met = topk_matched_pairs == topk_total_pairs
        matches_for_goal3 = topk_total_pairs - topk_matched_pairs

        total_est = max(matches_for_goal1, matches_for_goal2) + matches_for_goal3
        est_minutes = max(0, round(total_est * (10.0 / max(parallel_agents, 1)) / 60))
        cat_matches_done = sum(e.get("comparisons", 0) for e in entries) // 2

        progress_by_cat[cat_id] = {
            "total_papers": cat_total,
            "total_matches": cat_matches_done,
            "papers_with_pdf": pdf_by_cat.get(cat_id, 0),
            "category": cat_id,
            "goals_met": bool(goal1_met and goal2_met and goal3_met),
            "goal1": {"met": bool(goal1_met), "label": f"General CI \u2264 {ci_target_general}%",
                      "done": int(general_converged), "total": int(general_total), "median_margin": round(median_general, 1)},
            "goal2": {"met": bool(goal2_met), "label": f"Top-{topk_total} CI \u2264 {ci_target}%",
                      "done": int(topk_converged), "total": int(topk_total), "median_margin": round(median_topk, 1)},
            "goal3": {"met": bool(goal3_met), "label": f"Top-{len(topk_id_list)} cross-matches",
                      "done": int(topk_matched_pairs), "total": int(topk_total_pairs)},
            "estimated_matches_remaining": int(total_est),
            "estimated_minutes": int(est_minutes),
        }
        await asyncio.sleep(0)  # Yield between categories

    # --- Summary stats via aggregation ---
    _t_progress = time.time()
    summary_stats = await _compute_summary_stats_agg()
    logger.info(f"Progress + summary stats computed in {time.time() - _t_progress:.1f}s")

    # --- Rating stats via aggregation ---
    rating_stats = {"__all__": {"rated": 0, "with_summaries": 0}}
    async for doc in db.papers.aggregate([
        {"$match": {"summaries": {"$exists": True, "$ne": {}}}},
        {"$project": {
            "cat": {"$arrayElemAt": ["$categories", 0]},
            "has_rating": {"$and": [
                {"$ne": [{"$type": "$ai_rating"}, "missing"]},
                {"$ne": ["$ai_rating", None]},
            ]},
        }},
        {"$group": {
            "_id": "$cat",
            "with_summaries": {"$sum": 1},
            "rated": {"$sum": {"$cond": ["$has_rating", 1, 0]}},
        }},
    ]):
        cat = doc["_id"] or "unknown"
        rating_stats[cat] = {"rated": doc["rated"], "with_summaries": doc["with_summaries"]}
        rating_stats["__all__"]["rated"] += doc["rated"]
        rating_stats["__all__"]["with_summaries"] += doc["with_summaries"]

    # --- Tags via aggregation ---
    _tag_cache.clear()
    tag_counts = Counter()
    async for doc in db.papers.aggregate([
        {"$match": {"summaries": {"$exists": True, "$ne": {}}}},
        {"$unwind": "$categories"},
        {"$group": {"_id": "$categories", "count": {"$sum": 1}}},
    ]):
        tag_counts[doc["_id"]] = doc["count"]

    tag_match_counts = Counter()
    async for doc in db.matches.aggregate([
        {"$match": {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}},
        {"$unwind": "$shared_categories"},
        {"$group": {"_id": "$shared_categories", "count": {"$sum": 1}}},
    ]):
        tag_match_counts[doc["_id"]] = doc["count"]

    tags_list = [
        {"id": tag, "count": count, "matches": tag_match_counts.get(tag, 0)}
        for tag, count in tag_counts.most_common()
    ]

    # --- Categories list ---
    try:
        from core.arxiv_categories import ARXIV_TAXONOMY
    except ImportError:
        ARXIV_TAXONOMY = {}
    categories_list = [
        {"id": cat_id, "name": CATEGORIES.get(cat_id) or ARXIV_TAXONOMY.get(cat_id) or cat_id}
        for cat_id in active_cats
    ]

    # --- Archives ---
    try:
        archive_docs = await db.leaderboard_archives.find(
            {}, {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1,
                 "period_type": 1, "paper_count": 1, "match_count": 1, "label": 1}
        ).sort([("year", -1), ("week", -1)]).to_list(500)
    except Exception:
        archive_docs = []

    # Build new lightweight cache (metadata only — no papers/matches in memory)
    new_cache = {
        "ts": time.time(),
        "total_papers": total_papers,
        "total_matches": total_matches,
        "warming_up": False,
        "_failed_by_cat": dict(failed_by_cat),
        "_pdf_by_cat": dict(pdf_by_cat),
        "_storage": {
            "total_chars": storage_chars_total,
            "total_with_text": sum(pdf_by_cat.values()),
            "chars_by_cat": dict(storage_chars_by_cat),
        },
        "_progress": progress_by_cat,
        "_summary_stats": summary_stats,
        "_rating_stats": rating_stats,
        "_tags": tags_list,
        "_categories": categories_list,
        "_default_category": active_cats[0] if active_cats else "cs.RO",
        "_archives": archive_docs,
    }
    # Preserve any keys set by other code
    for k in _cache:
        if k not in new_cache:
            new_cache[k] = _cache[k]

    _cache = new_cache
    _t1 = time.time()
    from core.memlog import get_mem_mb
    logger.info(f"Metadata cache refresh took {_t1 - _t0:.1f}s ({total_papers} papers, {total_matches} matches, {len(active_cats)} categories) [RSS: {get_mem_mb():.0f}MB]")


async def _bg_cache_loop():
    """Background loop that refreshes cache ONLY when data changes."""
    global _bg_task_started
    _bg_task_started = True
    # Initial warm
    try:
        await _refresh_cache()
        logger.info("Leaderboard cache warmed (background)")
    except Exception as e:
        logger.warning(f"Initial cache warm failed: {e}")

    while True:
        # Wait ONLY for data change — no timeout fallback
        await _cache_dirty.wait()
        _cache_dirty.clear()
        await asyncio.sleep(10)  # Debounce: batch rapid changes (e.g. 5 matches in a row)
        _cache_dirty.clear()

        try:
            await _refresh_cache()
        except Exception as e:
            logger.warning(f"Background cache refresh failed: {e}")


def start_cache_bg():
    """Start the background cache refresh task. Called from startup."""
    global _bg_task_started
    if not _bg_task_started:
        asyncio.create_task(_bg_cache_loop())
        asyncio.create_task(_bg_analysis_cache_loop())
        asyncio.create_task(_bg_archive_loop())


async def _bg_analysis_cache_loop():
    """Background loop that refreshes model-correlation and convergence when data changes.
    
    Debounced at 120s to batch rapid changes (comparison rounds complete every 5-15min).
    GC between categories to prevent memory accumulation.
    Initial delay: 120s to avoid running concurrently with startup tasks.
    """
    await asyncio.sleep(120)  # Wait for ALL startup tasks to complete before first run

    async def _refresh_analysis():
        try:
            import gc
            from core.auth import get_settings
            from core.memlog import log_mem
            settings = await get_settings()
            cats = settings.get("active_categories", [])
            log_mem(f"analysis_refresh start ({len(cats)} categories)")
            for cat in cats:
                try:
                    result = await _compute_model_correlation(cat, None)
                    _set_analysis_cached("model-correlation", cat, "", result)
                except Exception:
                    pass
                try:
                    result = await _compute_convergence(cat, 20)
                    _set_analysis_cached("convergence", cat, "20", result)
                except Exception:
                    pass
                gc.collect()
                await asyncio.sleep(2)  # Cooldown between categories
            log_mem(f"analysis_refresh done ({len(cats)} categories)")
            logger.info(f"Analysis cache refreshed: {len(cats)} categories")
        except Exception as e:
            logger.warning(f"Analysis cache refresh failed: {e}")

    await _refresh_analysis()

    while True:
        await _cache_dirty.wait()
        _cache_dirty.clear()
        await asyncio.sleep(120)  # 120s debounce — batch rapid comparison rounds
        _cache_dirty.clear()
        await _refresh_analysis()



async def _bg_archive_loop():
    """Background loop that checks and creates archive snapshots daily at 00:00 UTC."""
    from core.memlog import log_mem
    await asyncio.sleep(30)  # Wait for cache to warm

    # First iteration: archive snapshots only
    try:
        log_mem("archive_loop initial run start")
        await run_archive_snapshots()
        log_mem("archive_loop initial run done")
    except Exception as e:
        logger.warning(f"Archive snapshot check failed: {e}")

    while True:
        # Sleep until next day at 00:05 UTC
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        sleep_seconds = (tomorrow - now).total_seconds()
        await asyncio.sleep(max(sleep_seconds, 3600))

        try:
            log_mem("archive_loop daily run start")
            await run_archive_snapshots()
            log_mem("archive_loop daily snapshots done")
        except Exception as e:
            logger.warning(f"Archive snapshot check failed: {e}")


async def _get_cached_leaderboard():
    """Returns pre-computed cache instantly. Never blocks — returns empty cache if not yet warmed."""
    return _cache


@router.get("/tags")
async def get_all_tags():
    """Returns all unique category tags across all papers with counts and match coverage."""
    cache = await _get_cached_leaderboard()
    # Serve pre-computed tags from background cache
    if "_tags" in cache:
        return {"tags": cache["_tags"]}
    # Fallback: compute from DB (only on cold cache)
    from collections import Counter
    tag_counts = Counter()
    async for doc in db.rankings.aggregate([
        {"$unwind": "$categories"},
        {"$group": {"_id": "$categories", "count": {"$sum": 1}}},
    ]):
        tag_counts[doc["_id"]] = doc["count"]
    tag_match_counts = Counter()
    async for doc in db.matches.aggregate([
        {"$match": {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}},
        {"$unwind": "$shared_categories"},
        {"$group": {"_id": "$shared_categories", "count": {"$sum": 1}}},
    ]):
        tag_match_counts[doc["_id"]] = doc["count"]
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
    """Filter leaderboard entries by title or author search and re-rank."""
    if not search:
        return data
    search_lower = search.lower()
    filtered = [p for p in data if search_lower in p.get("title", "").lower()
                or any(search_lower in a.lower() for a in (p.get("authors") or []))]
    # Re-rank the filtered results
    return [{**p, "rank": i + 1} for i, p in enumerate(filtered)]


# ─── DB-Backed Leaderboard Serving (Phase 2) ────────────────────────────────

# Projection for rankings queries — exclude MongoDB _id, include all serving fields
_RANK_PROJ = {"_id": 0, "paper_id": 1, "category": 1, "rank": 1, "score": 1,
              "ci": 1, "wilson_margin": 1, "win_rate": 1, "wins": 1, "losses": 1,
              "comparisons": 1, "title": 1, "authors": 1, "arxiv_id": 1, "link": 1,
              "published": 1, "added_at": 1, "ai_rating": 1, "gap_score": 1,
              "community_likes": 1, "categories": 1}


def _encode_cursor(score: int, paper_id: str) -> str:
    """Encode a keyset pagination cursor as a URL-safe base64 token."""
    import base64, json
    payload = json.dumps({"s": score, "p": paper_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple:
    """Decode a keyset cursor → (score, paper_id). Returns (None, None) on invalid input."""
    import base64, json
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload["s"], payload["p"]
    except Exception:
        return None, None


def _rank_doc_to_entry(doc: dict) -> dict:
    """Convert a rankings DB document to a leaderboard entry (matching the old cache format)."""
    return {
        "id": doc["paper_id"],
        "rank": doc.get("rank", 0),
        "title": doc.get("title", ""),
        "authors": doc.get("authors", []),
        "arxiv_id": doc.get("arxiv_id", ""),
        "link": doc.get("link", ""),
        "published": doc.get("published", ""),
        "score": doc.get("score", 1200),
        "ci": doc.get("ci", 0),
        "wilson_margin": doc.get("wilson_margin", 100.0),
        "win_rate": doc.get("win_rate", 0.0),
        "wins": doc.get("wins", 0),
        "losses": doc.get("losses", 0),
        "comparisons": doc.get("comparisons", 0),
        **({"ai_rating": doc["ai_rating"]} if doc.get("ai_rating") else {}),
        **({"gap_score": doc["gap_score"]} if doc.get("gap_score") else {}),
        **({"community_likes": doc["community_likes"]} if doc.get("community_likes") is not None else {}),
    }


def _build_period_filter(period: str) -> dict:
    """Build a MongoDB query filter for time periods (non-recent only).
    For 'recent', use _build_recent_filter() which needs async DB access."""
    if period == "all":
        return {}
    utc_now = datetime.now(timezone.utc)
    if period == "recent":
        # Fallback: static 48h (use _build_recent_filter for rolling window)
        cutoff = (utc_now - timedelta(hours=48)).isoformat()
        return {"added_at": {"$gte": cutoff}}
    elif period == "week":
        cutoff = (utc_now - timedelta(weeks=1)).isoformat()
        return {"published": {"$gte": cutoff}}
    elif period == "month":
        cutoff = (utc_now - timedelta(days=30)).isoformat()
        return {"published": {"$gte": cutoff}}
    return {}


async def _build_recent_filter(scope_query: dict = None) -> dict:
    """Rolling 48h window anchored to the latest addition within scope.
    
    scope_query: optional MongoDB filter to scope the anchor lookup
    (e.g., {"category": "cs.RO"} or {"categories": {"$in": ["cs.AI"]}})
    """
    anchor_query = {"added_at": {"$nin": ["", None]}}
    if scope_query:
        anchor_query.update(scope_query)

    latest = await db.rankings.find_one(
        anchor_query,
        {"_id": 0, "added_at": 1},
        sort=[("added_at", -1)],
    )
    if latest and latest.get("added_at"):
        try:
            anchor_dt = datetime.fromisoformat(latest["added_at"].replace("Z", "+00:00"))
            cutoff = (anchor_dt - timedelta(hours=48)).isoformat()
            return {"added_at": {"$gte": cutoff}}
        except (ValueError, TypeError):
            pass
    # Fallback: static 48h
    return {"added_at": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()}}


async def _get_archives_for_category(category: str, settings: dict) -> list:
    """Load archive list from DB (lightweight metadata only)."""
    archives = await db.leaderboard_archives.find(
        {"category": category},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1,
         "period_type": 1, "paper_count": 1, "match_count": 1, "label": 1}
    ).sort([("year", -1), ("week", -1)]).to_list(200)
    return _filter_archives_by_frequency(archives, category, settings)


async def _db_category_leaderboard(category: str, period: str, limit: int, offset: int, search: str = None, cursor: str = None):
    """Serve primary category leaderboard from DB rankings collection."""
    _t0 = time.time()
    try:
        result = await _db_category_leaderboard_impl(category, period, limit, offset, search, cursor)
        _elapsed = time.time() - _t0
        entries_n = len(result.get("leaderboard", []))
        if _elapsed > 0.2:
            from core.memlog import log_event
            log_event("slow_query", f"category_leaderboard({category}, {period})",
                      {"elapsed_s": round(_elapsed, 3), "entries": entries_n,
                       "search": bool(search), "cursor": bool(cursor)})
        return result
    except Exception as e:
        logger.error(f"Leaderboard query failed for {category}: {e}")
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": category, "tags": None, "tag_mode": None,
            "warming_up": True, "message": "Leaderboard data is temporarily unavailable.",
        }


async def _get_community_correlation(category: str):
    """Compute community correlation for a category (currently only cs.RO)."""
    if category != "cs.RO":
        return None
    liked = []
    async for doc in db.rankings.find(
        {"category": category, "community_likes": {"$exists": True, "$ne": None}},
        {"_id": 0, "score": 1, "community_likes": 1}
    ):
        liked.append((doc["score"], doc["community_likes"]))
    if len(liked) >= 10:
        from scipy import stats as _sp
        import numpy as _np
        scores, likes = zip(*liked)
        rho, pval = _sp.spearmanr(scores, likes)
        return {
            "rho": round(rho, 4) if not _np.isnan(rho) else None,
            "p_value": round(pval, 4) if not _np.isnan(pval) else None,
            "n": len(liked),
        }
    return None


async def _db_category_leaderboard_impl(category: str, period: str, limit: int, offset: int, search: str = None, cursor: str = None):
    import asyncio
    from core.auth import get_settings

    # Phase 1: Fire all independent operations in parallel to minimize event-loop wait
    phase1 = [
        get_settings(),
        db.rankings.count_documents({"category": category}),
        _get_match_count(category),
        _get_community_correlation(category),
    ]
    if period == "recent":
        phase1.append(_build_recent_filter({"category": category}))
        settings, total_in_cat, match_count, community_corr, recent_filter = await asyncio.gather(*phase1)
    else:
        settings, total_in_cat, match_count, community_corr = await asyncio.gather(*phase1)
        recent_filter = None

    if total_in_cat == 0:
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": category, "tags": None, "tag_mode": None,
            "warming_up": True, "message": "Leaderboard data is loading, please wait...",
        }

    query = {"category": category}

    # Period filter (rolling window for "recent")
    if period == "recent":
        query.update(recent_filter)
    else:
        query.update(_build_period_filter(period))

    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"authors": {"$regex": search, "$options": "i"}},
        ]

    # Phase 2: Query-dependent count + archives in parallel
    total_in_period, archives = await asyncio.gather(
        db.rankings.count_documents(query),
        _get_archives_for_category(category, settings),
    )

    sort_field = "rank" if period == "all" and not search else "score"

    # Keyset pagination: O(1) for any page depth (vs O(N) for skip-based)
    if cursor and not search:
        cursor_score, cursor_pid = _decode_cursor(cursor)
        if cursor_score is not None:
            query["$or"] = [
                {"score": {"$lt": cursor_score}},
                {"score": cursor_score, "paper_id": {"$lt": cursor_pid}},
            ]
            offset = 0

    sort_key = [("rank", 1)] if sort_field == "rank" else [("score", -1), ("paper_id", -1)]
    cursor_obj = db.rankings.find(query, _RANK_PROJ).sort(sort_key).skip(offset).limit(limit)
    entries = []
    rank_offset = offset + 1
    last_doc = None
    async for doc in cursor_obj:
        entry = _rank_doc_to_entry(doc)
        if period != "all" or search:
            entry["rank"] = rank_offset
            rank_offset += 1
        entries.append(entry)
        last_doc = doc

    next_cursor = None
    if entries and last_doc and len(entries) == limit:
        next_cursor = _encode_cursor(last_doc.get("score", 0), last_doc.get("paper_id", ""))

    # is_ranking = tournament goals not yet met (still actively comparing)
    from services.scheduler import _get_cat_status
    cat_status = _get_cat_status(category)
    cat_activity = cat_status.get("current_activity", "")
    is_ranking = cat_activity not in ("Idle", "Goals met — idle", "Tournament paused", "System paused", "Comparisons paused")

    return {
        "leaderboard": entries,
        "total_papers": total_in_cat,
        "total_in_period": total_in_period,
        "total_matches": match_count,
        "is_ranking": is_ranking,
        "period": period,
        "category": category,
        "tags": None,
        "tag_mode": None,
        "warming_up": False,
        "community_correlation": community_corr,
        "show_rating_column": settings.get("show_rating_column", True),
        "show_gap_column": settings.get("show_gap_column", True),
        "archives": archives,
        "next_cursor": next_cursor,
    }


async def _db_all_papers_leaderboard(period: str, limit: int, offset: int, search: str = None, cursor: str = None):
    """Serve cross-category 'all papers' leaderboard from DB rankings."""
    _t0 = time.time()
    try:
        result = await _db_all_papers_leaderboard_impl(period, limit, offset, search, cursor)
        _elapsed = time.time() - _t0
        entries_n = len(result.get("leaderboard", []))
        if _elapsed > 0.2:
            from core.memlog import log_event
            log_event("slow_query", f"all_papers_leaderboard({period})",
                      {"elapsed_s": round(_elapsed, 3), "entries": entries_n,
                       "search": bool(search), "cursor": bool(cursor)})
        return result
    except Exception as e:
        logger.error(f"All-papers leaderboard query failed: {e}")
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": None, "tags": None, "tag_mode": None, "show_all": True,
        }


async def _db_all_papers_leaderboard_impl(period: str, limit: int, offset: int, search: str = None, cursor: str = None):
    import asyncio

    # Phase 1: Build filter + fire independent counts in parallel
    phase1 = [
        db.rankings.count_documents({}),
        _get_match_count(),
    ]
    if period == "recent":
        phase1.append(_build_recent_filter())
        total_papers, total_matches, recent_filter = await asyncio.gather(*phase1)
        query = recent_filter
    else:
        total_papers, total_matches = await asyncio.gather(*phase1)
        query = _build_period_filter(period)

    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"authors": {"$regex": search, "$options": "i"}},
        ]

    total_in_period = await db.rankings.count_documents(query)

    # Keyset pagination
    if cursor and not search:
        cursor_score, cursor_pid = _decode_cursor(cursor)
        if cursor_score is not None:
            query["$or"] = [
                {"score": {"$lt": cursor_score}},
                {"score": cursor_score, "paper_id": {"$lt": cursor_pid}},
            ]
            offset = 0

    cursor_obj = db.rankings.find(query, _RANK_PROJ).sort([("score", -1), ("paper_id", -1)]).skip(offset).limit(limit)
    entries = []
    rank_num = offset + 1
    last_doc = None
    async for doc in cursor_obj:
        entry = _rank_doc_to_entry(doc)
        entry["rank"] = rank_num
        entry["primary_category"] = doc.get("category", "unknown")
        rank_num += 1
        entries.append(entry)
        last_doc = doc

    next_cursor = None
    if entries and last_doc and len(entries) == limit:
        next_cursor = _encode_cursor(last_doc.get("score", 0), last_doc.get("paper_id", ""))

    return {
        "leaderboard": entries,
        "total_papers": total_papers,
        "total_in_period": total_in_period,
        "total_matches": total_matches,
        "is_ranking": False,
        "period": period,
        "category": None,
        "tags": None,
        "tag_mode": None,
        "show_all": True,
        "next_cursor": next_cursor,
    }


async def _db_tag_leaderboard(
    tag_list: list, period: str, limit: int, offset: int,
    tag_mode: str = "or", global_stats: bool = False, show_all: bool = False,
    search: str = None, cursor: str = None,
):
    """Serve tag-filtered leaderboard from DB rankings."""
    _t0 = time.time()
    try:
        result = await _db_tag_leaderboard_impl(tag_list, period, limit, offset, tag_mode, global_stats, show_all, search, cursor)
        _elapsed = time.time() - _t0
        entries_n = len(result.get("leaderboard", []))
        if _elapsed > 0.2:
            from core.memlog import log_event
            log_event("slow_query", f"tag_leaderboard({tag_list[:3]}, {period})",
                      {"elapsed_s": round(_elapsed, 3), "entries": entries_n,
                       "tags": tag_list[:5], "show_all": show_all,
                       "search": bool(search), "cursor": bool(cursor)})
        return result
    except Exception as e:
        logger.error(f"Tag leaderboard query failed for {tag_list}: {e}")
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": None, "tags": tag_list, "tag_mode": tag_mode,
        }


async def _db_tag_leaderboard_impl(
    tag_list: list, period: str, limit: int, offset: int,
    tag_mode: str = "or", global_stats: bool = False, show_all: bool = False,
    search: str = None, cursor: str = None,
):
    import asyncio
    # Query rankings directly by categories (no papers collection round-trip)
    tag_set = list(set(tag_list))
    if tag_mode == "and" and len(tag_set) > 1:
        tag_filter = {"categories": {"$all": tag_set}}
    else:
        tag_filter = {"categories": {"$in": tag_set}}

    # Phase 1: Count + recent filter in parallel
    phase1 = [db.rankings.count_documents(tag_filter)]
    if period == "recent":
        phase1.append(_build_recent_filter(tag_filter if not show_all else None))
        matching_count, recent_filter = await asyncio.gather(*phase1)
    else:
        (matching_count,) = await asyncio.gather(*phase1)
        recent_filter = None

    if matching_count == 0 and not show_all:
        return {
            "leaderboard": [], "total_papers": 0, "total_in_period": 0,
            "total_matches": 0, "is_ranking": False, "period": period,
            "category": None, "tags": tag_list, "tag_mode": tag_mode,
        }

    # Build query for the page

    if show_all:
        rank_query = recent_filter if recent_filter else _build_period_filter(period)
    else:
        rank_query = dict(tag_filter)
        rank_query.update(recent_filter if recent_filter else _build_period_filter(period))

    if search:
        rank_query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"authors": {"$regex": search, "$options": "i"}},
        ]

    total_in_period = await db.rankings.count_documents(rank_query)

    # Get matching IDs for tag badge (only needed if show_all — otherwise all results match)
    matching_ids = None
    if show_all:
        matching_ids = set()
        async for r in db.rankings.find(tag_filter, {"_id": 0, "paper_id": 1}):
            matching_ids.add(r["paper_id"])

    # Keyset pagination
    if cursor and not search:
        cursor_score, cursor_pid = _decode_cursor(cursor)
        if cursor_score is not None:
            rank_query["$or"] = [
                {"score": {"$lt": cursor_score}},
                {"score": cursor_score, "paper_id": {"$lt": cursor_pid}},
            ]
            offset = 0

    cursor_obj = db.rankings.find(rank_query, _RANK_PROJ).sort([("score", -1), ("paper_id", -1)]).skip(offset).limit(limit)
    entries = []
    rank_num = offset + 1
    last_doc = None
    async for doc in cursor_obj:
        entry = _rank_doc_to_entry(doc)
        entry["rank"] = rank_num
        entry["primary_category"] = doc.get("category", "unknown")
        entry["matches_tag"] = matching_ids is None or doc["paper_id"] in matching_ids
        rank_num += 1
        entries.append(entry)
        last_doc = doc

    # Local mode: recompute stats from only matches between papers in the filtered set
    if not global_stats and entries:
        paper_id_set = [e["id"] for e in entries]
        local_matches = await collect_all(db.matches.find(
            {"completed": True, "winner_id": {"$exists": True}, "failed": {"$ne": True},
             "paper1_id": {"$in": paper_id_set}, "paper2_id": {"$in": paper_id_set},
             "mode": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))
        if local_matches:
            bt_matches = [
                {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                 "winner_id": m["winner_id"], "completed": True, "failed": False}
                for m in local_matches
            ]
            papers_stub = [{"id": pid, "title": ""} for pid in paper_id_set]
            local_lb = compute_leaderboard(papers_stub, bt_matches)
            local_map = {e["id"]: e for e in local_lb}
            for entry in entries:
                loc = local_map.get(entry["id"])
                if loc:
                    entry["score"] = loc["score"]
                    entry["win_rate"] = loc["win_rate"]
                    entry["wins"] = loc["wins"]
                    entry["losses"] = loc["losses"]
                    entry["comparisons"] = loc["comparisons"]
            entries.sort(key=lambda e: (-e["score"], e["id"]))
            for i, e in enumerate(entries):
                e["rank"] = i + 1

    next_cursor = None
    if entries and last_doc and len(entries) == limit:
        next_cursor = _encode_cursor(last_doc.get("score", 0), last_doc.get("paper_id", ""))

    return {
        "leaderboard": entries,
        "total_papers": matching_count,
        "total_all_papers": total_in_period if show_all else matching_count,
        "total_in_period": total_in_period,
        "total_matches": 0,  # Skip expensive cross-join match count
        "is_ranking": False,
        "period": period,
        "category": None,
        "tags": tag_list,
        "tag_mode": tag_mode,
        "show_all": show_all,
        "global_stats": global_stats,
        "next_cursor": next_cursor,
    }



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
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor (from previous response's next_cursor)"),
):
    # Tag-based filtering
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()][:50]
        if tag_list:
            return await _db_tag_leaderboard(tag_list, period, limit, offset, tag_mode, global_stats, show_all, search, cursor)

    # All papers cross-category
    if show_all:
        return await _db_all_papers_leaderboard(period, limit, offset, search, cursor)

    # Primary category leaderboard — served from DB rankings
    return await _db_category_leaderboard(category, period, limit, offset, search, cursor)


def _filter_archives_by_frequency(archives, category, settings):
    """Filter archive list to show only the type configured by admin (weekly or monthly).
    Excludes the current (ongoing) period and sorts by recency."""
    from datetime import datetime, timezone
    freq_config = settings.get("archive_frequency", {})
    freq = freq_config.get(category, freq_config.get("default", "weekly"))
    target_type = "monthly" if freq == "monthly" else "weekly"

    now = datetime.now(timezone.utc)
    current_year = now.isocalendar()[0]
    current_week = now.isocalendar()[1]
    current_month = now.month

    filtered = []
    for a in archives:
        if a.get("period_type") != target_type:
            continue
        # Exclude current (ongoing) period
        if target_type == "weekly" and a.get("year") == current_year and a.get("week") == current_week:
            continue
        if target_type == "monthly" and a.get("year") == now.year and a.get("month") == current_month:
            continue
        filtered.append(a)

    # Sort by recency: year desc, then week/month desc
    def sort_key(a):
        return (a.get("year", 0), a.get("week") or a.get("month") or 0)
    filtered.sort(key=sort_key, reverse=True)
    return filtered



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

    # Stats from rankings collection (same source as leaderboard — always in sync)
    ranking_doc = await db.rankings.find_one(
        {"paper_id": paper_id},
        {"_id": 0, "wins": 1, "losses": 1, "comparisons": 1,
         "score": 1, "rank": 1, "win_rate": 1, "ci": 1, "wilson_margin": 1}
    )

    if ranking_doc:
        stats = {
            "wins": ranking_doc.get("wins", 0),
            "losses": ranking_doc.get("losses", 0),
            "comparisons": ranking_doc.get("comparisons", 0),
            "confidence": calculate_confidence_interval(
                ranking_doc.get("wins", 0), ranking_doc.get("comparisons", 0)),
        }
    else:
        # Paper not yet in rankings (newly added) — compute from matches
        wins = sum(1 for m in enriched_matches if m["won"] and not m["failed"])
        total = sum(1 for m in enriched_matches if not m["failed"])
        stats = {
            "wins": wins,
            "losses": total - wins,
            "comparisons": total,
            "confidence": calculate_confidence_interval(wins, total),
        }

    return {
        "paper": paper,
        "matches": enriched_matches,
        "stats": stats,
    }


_status_cache = {"data": None, "ts": 0}


@router.get("/status")
async def get_system_status():
    from services.scheduler import get_scheduler_status

    now = time.time()
    if _status_cache["data"] is None or now - _status_cache["ts"] > 10:
        # Query DB directly — no dependency on in-memory cache
        total_papers = await db.rankings.count_documents({})
        total_matches = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}
        )
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
    """Public read-only view of the evaluation and summary prompts.
    Always returns the code-defined prompts as the source of truth."""
    from core.config import DEFAULT_EVALUATION_PROMPT
    from services.llm import IMPACT_ASSESSMENT_PROMPT

    eval_doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
    eval_prompt = {
        "system_prompt": eval_doc.get("system_prompt", "") if eval_doc else DEFAULT_EVALUATION_PROMPT["system_prompt"],
        "user_prompt": eval_doc.get("user_prompt", "") if eval_doc else DEFAULT_EVALUATION_PROMPT["user_prompt"],
    }

    # Always use the code-defined impact assessment prompt (includes ratings)
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
_ANALYSIS_CACHE_TTL = 3600  # 1 hour — data only changes when new matches are added
_ANALYSIS_CACHE_MAX = 500   # ~50MB max; evict oldest when exceeded


def _get_analysis_cached(endpoint: str, category: str, mode: str = ""):
    key = (endpoint, category or "__all__", mode or "")
    entry = _analysis_cache.get(key)
    if entry and time.time() - entry["ts"] < _ANALYSIS_CACHE_TTL:
        return entry["data"]
    return None


def _set_analysis_cached(endpoint: str, category: str, mode: str, data):
    key = (endpoint, category or "__all__", mode or "")
    if len(_analysis_cache) >= _ANALYSIS_CACHE_MAX:
        oldest = min(_analysis_cache, key=lambda k: _analysis_cache[k]["ts"])
        del _analysis_cache[oldest]
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

    # Always query DB (no in-memory cache dependency)
    match_query = {"completed": True, "failed": {"$ne": True}, "model_used": {"$exists": True}}
    if category:
        match_query["primary_category"] = category  # Filter at DB level, not Python
    matches_raw = await collect_all(db.matches.find(
        match_query,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1, "mode": 1},
    ))

    if mode:
        matches_raw = [m for m in matches_raw if m.get("mode") == mode]
    else:
        matches_raw = [m for m in matches_raw if not m.get("mode")]

    matches = matches_raw  # Already filtered by category at DB level
    paper_titles = {}
    rank_query = {"category": category} if category else {}
    async for p in db.rankings.find(rank_query, {"_id": 0, "paper_id": 1, "title": 1}):
        paper_titles[p["paper_id"]] = p["title"]

    if not matches:
        return {"models": [], "correlations": {}, "agreement": {}, "n_common_papers": 0, "category": category, "mode": mode}

    # Merge Opus 4.5 and 4.6 into unified "Claude Opus"
    _OPUS_MERGE = {
        "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
        "anthropic/claude-opus-4-6": "anthropic/claude-opus",
    }
    for m in matches:
        mu = m.get("model_used", {})
        raw_key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        if raw_key in _OPUS_MERGE:
            mu["_merged_key"] = _OPUS_MERGE[raw_key]

    model_keys = set()
    for m in matches:
        mu = m.get("model_used", {})
        key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
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
        key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        for pid in [p1, p2]:
            if pid not in model_paper_stats[key]:
                model_paper_stats[key][pid] = {"wins": 0, "total": 0}
            model_paper_stats[key][pid]["total"] += 1
        if w and w in model_paper_stats[key]:
            model_paper_stats[key][w]["wins"] += 1

    MIN_MATCHES_PER_MODEL = 5  # Minimum matches per model to include a paper (reduces quantization artifacts)

    model_win_rates = {}
    for mk in model_keys:
        model_win_rates[mk] = {}
        for pid in paper_ids:
            s = model_paper_stats[mk].get(pid)
            if s and s["total"] >= MIN_MATCHES_PER_MODEL:
                model_win_rates[mk][pid] = s["wins"] / s["total"]

    # Compute correlations PER MODEL PAIR (not requiring all models to have data)
    correlations = {}
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j:
                continue
            pair_papers = sorted(set(model_win_rates[m1].keys()) & set(model_win_rates[m2].keys()))
            if len(pair_papers) >= 5:
                rates1 = [model_win_rates[m1][pid] for pid in pair_papers]
                rates2 = [model_win_rates[m2][pid] for pid in pair_papers]
                spearman_r, spearman_p = scipy_stats.spearmanr(rates1, rates2)
                pearson_r, pearson_p = scipy_stats.pearsonr(rates1, rates2)
                correlations[f"{m1} vs {m2}"] = {
                    "spearman_r": round(float(spearman_r), 3),
                    "spearman_p": round(float(spearman_p), 4),
                    "pearson_r": round(float(pearson_r), 3),
                    "pearson_p": round(float(pearson_p), 4),
                    "n_papers": len(pair_papers),
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
        key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
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
        total_by_model = sum(
            1 for m in matches
            if (m.get("model_used", {}).get("_merged_key") or f"{m.get('model_used',{}).get('provider','')}/{m.get('model_used',{}).get('model','')}") == mk
        )
        model_summaries[mk] = {
            "total_matches": total_by_model,
            "papers_judged": len(model_paper_stats[mk]),
        }

    # Short name mapping for merged models
    _SHORT_NAMES = {
        "anthropic/claude-opus": "Claude Opus",
        "gemini/gemini-3-pro-preview": "Gemini 3 Pro",
        "openai/gpt-5.2": "GPT-5.2",
    }

    def _short(mk):
        return _SHORT_NAMES.get(mk, mk.split("/")[-1])

    # Scatter data PER MODEL PAIR (each pair gets its own data points)
    scatter_data = {}
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j:
                continue
            pair_key = f"{m1} vs {m2}"
            pair_papers = sorted(set(model_win_rates[m1].keys()) & set(model_win_rates[m2].keys()))
            short1 = _short(m1)
            short2 = _short(m2)
            pair_points = []
            for pid in pair_papers:
                pair_points.append({
                    "title": paper_titles.get(pid, "?")[:40],
                    short1: round(model_win_rates[m1][pid] * 100, 1),
                    short2: round(model_win_rates[m2][pid] * 100, 1),
                })
            scatter_data[pair_key] = pair_points

    # Also compute total common papers (intersection of ALL models) for backward compat
    common_papers = set(paper_ids)
    for mk in model_keys:
        common_papers &= set(model_win_rates[mk].keys())

    # Sort correlations and agreement by the same key order
    sorted_corr_keys = sorted(correlations.keys())
    sorted_correlations = {k: correlations[k] for k in sorted_corr_keys}

    sorted_agree_keys = sorted(agreement.keys())
    sorted_agreement = {k: agreement[k] for k in sorted_agree_keys}

    # ── PW Inter-Model by Scoring Method ──────────────────────────────────
    # For each model, compute rankings using raw win%, regularized WR, BT, TrueSkill
    # Then correlate across model pairs to show which scoring method yields most agreement
    pw_inter_model = []
    try:
        from services.ranking import compute_bt_ranking_scores, compute_trueskill_ranking_scores

        # Group matches by model
        model_matches = {mk: [] for mk in model_keys}
        for m in matches:
            mu = m.get("model_used", {})
            key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
            model_matches[key].append(m)

        # Compute per-model rankings by each method
        model_rankings = {}  # {model_key: {method: {paper_id: score}}}
        for mk in model_keys:
            mk_matches = model_matches[mk]
            if len(mk_matches) < 20:
                continue

            bt_fmt = [
                {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                 "winner_id": m.get("winner_id"), "completed": True, "failed": False}
                for m in mk_matches
            ]
            mk_paper_ids = list(set(
                [m["paper1_id"] for m in mk_matches] + [m["paper2_id"] for m in mk_matches]
            ))

            # Raw win% (already computed)
            raw_wr = {pid: model_win_rates[mk].get(pid) for pid in mk_paper_ids
                      if model_win_rates[mk].get(pid) is not None}

            # Regularized WR (Jeffreys prior)
            reg_wr = {}
            for pid in mk_paper_ids:
                s = model_paper_stats[mk].get(pid)
                if s and s["total"] >= 1:
                    reg_wr[pid] = (s["wins"] + 0.5) / (s["total"] + 1.0)

            # BT
            bt_scores = compute_bt_ranking_scores(bt_fmt, mk_paper_ids)

            # TrueSkill
            ts_scores = compute_trueskill_ranking_scores(bt_fmt, mk_paper_ids)

            model_rankings[mk] = {
                "raw_wr": raw_wr,
                "reg_wr": reg_wr,
                "bt": bt_scores,
                "trueskill": ts_scores,
            }

        # For each model pair, compute Spearman ρ per method
        method_labels = {
            "raw_wr": "Dashboard (raw win%)",
            "reg_wr": "Regularized WR",
            "bt": "Bradley-Terry",
            "trueskill": "TrueSkill",
        }
        method_order = ["raw_wr", "reg_wr", "bt", "trueskill"]

        for i, m1 in enumerate(model_keys):
            for j, m2 in enumerate(model_keys):
                if i >= j:
                    continue
                if m1 not in model_rankings or m2 not in model_rankings:
                    continue
                row = {"pair": f"{_short(m1)} vs {_short(m2)}", "methods": {}}
                for method in method_order:
                    r1 = model_rankings[m1].get(method, {})
                    r2 = model_rankings[m2].get(method, {})
                    common = sorted(set(r1.keys()) & set(r2.keys()))
                    if len(common) >= 10:
                        v1 = [r1[p] for p in common]
                        v2 = [r2[p] for p in common]
                        rho, _ = scipy_stats.spearmanr(v1, v2)
                        if not np.isnan(rho):
                            row["methods"][method] = {
                                "rho": round(float(rho), 3),
                                "n": len(common),
                            }
                if row["methods"]:
                    pw_inter_model.append(row)
    except Exception as e:
        logger.warning(f"PW inter-model by method failed: {e}")

    return {
        "models": [{"key": mk, "short": _short(mk), **model_summaries.get(mk, {})} for mk in model_keys],
        "correlations": sorted_correlations,
        "agreement": sorted_agreement,
        "scatter_data": scatter_data,
        "n_common_papers": len(common_papers),
        "category": category,
        "mode": mode,
        "pw_inter_model": pw_inter_model,
        "method_labels": {
            "raw_wr": "Dashboard (raw win%)",
            "reg_wr": "Regularized WR",
            "bt": "Bradley-Terry",
            "trueskill": "TrueSkill",
        },
    }



@router.get("/scoring-method-correlation")
async def get_scoring_method_correlation(
    category: Optional[str] = Query(None, description="Filter by category (None = all)"),
):
    """Compare Win-Rate, Bradley-Terry, and TrueSkill ranking methods on live tournament data."""
    cached = _get_analysis_cached("scoring-method-correlation", category, "")
    if cached:
        return cached
    result = await _compute_scoring_method_correlation(category)
    _set_analysis_cached("scoring-method-correlation", category, "", result)
    return result


async def _compute_scoring_method_correlation(category):
    import numpy as np
    from scipy import stats as scipy_stats
    from services.ranking import compute_bt_ranking_scores, compute_trueskill_ranking_scores
    t_start = time.perf_counter()

    match_query = {"completed": True, "winner_id": {"$exists": True}, "failed": {"$ne": True}}
    if category:
        match_query["primary_category"] = category
    # Standard mode only (exclude prediction modes)
    match_query["mode"] = {"$exists": False}

    matches_raw = await collect_all(db.matches.find(
        match_query,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))
    if len(matches_raw) < 20:
        return {"status": "insufficient_data", "n_matches": len(matches_raw)}

    bt_matches = [
        {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
         "winner_id": m["winner_id"], "completed": True, "failed": False}
        for m in matches_raw
    ]
    paper_ids = list(set(
        [m["paper1_id"] for m in matches_raw] + [m["paper2_id"] for m in matches_raw]
    ))

    # Compute all three scoring methods
    papers = [{"id": pid, "title": ""} for pid in paper_ids]
    lb = compute_leaderboard(papers, bt_matches)
    wr_scores = {e["id"]: e["score"] for e in lb}

    bt_scores = compute_bt_ranking_scores(bt_matches, paper_ids)
    ts_scores = compute_trueskill_ranking_scores(bt_matches, paper_ids)

    t_compute = time.perf_counter() - t_start

    # Pairwise correlations
    shared = sorted(set(wr_scores.keys()) & set(bt_scores.keys()) & set(ts_scores.keys()))
    methods = {"win_rate": wr_scores, "bt": bt_scores, "trueskill": ts_scores}
    method_labels = {"win_rate": "Normalized Win-Rate", "bt": "Bradley-Terry", "trueskill": "TrueSkill"}
    method_keys = ["win_rate", "bt", "trueskill"]

    correlations = []
    for i in range(len(method_keys)):
        for j in range(i + 1, len(method_keys)):
            m1, m2 = method_keys[i], method_keys[j]
            arr1 = [methods[m1][p] for p in shared]
            arr2 = [methods[m2][p] for p in shared]
            sp_r, sp_p = scipy_stats.spearmanr(arr1, arr2)
            kt_r, kt_p = scipy_stats.kendalltau(arr1, arr2)
            correlations.append({
                "method1": m1, "method2": m2,
                "label": f"{method_labels[m1]} vs {method_labels[m2]}",
                "spearman_rho": round(float(sp_r), 6),
                "spearman_p": float(sp_p),
                "kendall_tau": round(float(kt_r), 6),
                "kendall_p": float(kt_p),
            })

    # Rank agreement at extremes (top/bottom 5%, 10%)
    rank_agreement = []
    for frac in [0.05, 0.10, 0.20]:
        k = max(1, int(len(shared) * frac))
        pct = int(frac * 100)
        for i in range(len(method_keys)):
            for j in range(i + 1, len(method_keys)):
                m1, m2 = method_keys[i], method_keys[j]
                top1 = set(sorted(shared, key=lambda p: methods[m1][p], reverse=True)[:k])
                top2 = set(sorted(shared, key=lambda p: methods[m2][p], reverse=True)[:k])
                bot1 = set(sorted(shared, key=lambda p: methods[m1][p])[:k])
                bot2 = set(sorted(shared, key=lambda p: methods[m2][p])[:k])
                rank_agreement.append({
                    "method1": m1, "method2": m2,
                    "pct": pct,
                    "top_overlap": round(len(top1 & top2) / k * 100, 1),
                    "bottom_overlap": round(len(bot1 & bot2) / k * 100, 1),
                })

    return {
        "status": "ok",
        "n_papers": len(shared),
        "n_matches": len(matches_raw),
        "compute_time_s": round(t_compute, 2),
        "category": category,
        "methods": [{"key": k, "label": method_labels[k]} for k in method_keys],
        "correlations": correlations,
        "rank_agreement": rank_agreement,
    }


@router.get("/si-rating-stats")
async def get_si_rating_stats(
    category: Optional[str] = Query(None, description="Filter by primary category"),
    model: Optional[str] = Query(None, description="Filter by model: claude, gpt, gemini, or None for all"),
):
    """Single-item rating distributions and inter-metric correlations from live leaderboard data."""
    cache_key = f"{model or 'all'}"
    cached = _get_analysis_cached("si-rating-stats", category, cache_key)
    if cached and cached.get("pw_vs_si") is not None:
        return cached
    result = await _compute_si_rating_stats(category, model)
    if result.get("pw_vs_si") is not None:
        _set_analysis_cached("si-rating-stats", category, cache_key, result)
    return result


_SI_MODEL_KEYS = {
    "claude": "claude",
    "gpt": "gpt",
    "gemini": "gemini",
}

def _get_paper_si_rating(paper, model=None):
    """Get SI rating for a paper, optionally filtered by model.
    When model=None, returns the average across all available models."""
    if model:
        by_model = paper.get("ai_ratings_by_model", {})
        if isinstance(by_model, dict) and by_model.get(model):
            return by_model[model]
        # Fallback: ai_rating is generated by Claude
        if model == "claude":
            ai_r = paper.get("ai_rating")
            return ai_r if isinstance(ai_r, dict) else None
        return None
    # No model filter: average across all available per-model ratings
    by_model = paper.get("ai_ratings_by_model", {})
    if isinstance(by_model, dict):
        ratings = [r for r in by_model.values() if isinstance(r, dict) and r.get("score")]
        if ratings:
            FIELDS = ["score", "significance", "rigor", "novelty", "clarity"]
            avg = {}
            for f in FIELDS:
                vals = [r[f] for r in ratings if r.get(f)]
                avg[f] = round(sum(vals) / len(vals), 1) if vals else 0
            return avg
    ai_r = paper.get("ai_rating")
    return ai_r if isinstance(ai_r, dict) else None


async def _compute_si_rating_stats(category, model):
    import numpy as np
    from scipy import stats as scipy_stats
    from collections import Counter

    # Build query: papers with any SI rating data
    query = {"$or": [
        {"ai_rating": {"$exists": True}, "ai_rating.score": {"$gt": 0}},
        {"ai_ratings_by_model": {"$exists": True}},
    ]}
    if category:
        query["categories.0"] = category

    papers = await collect_all(db.papers.find(
        query,
        {"_id": 0, "id": 1, "ai_rating": 1, "ai_ratings_by_model": 1, "categories": 1}
    ))

    # Determine which models have data (avoid double-counting)
    available_models = []
    model_counts = {"claude": 0, "gpt": 0, "gemini": 0}
    for p in papers:
        by_model = p.get("ai_ratings_by_model", {})
        has_by_model_claude = isinstance(by_model, dict) and isinstance(by_model.get("claude"), dict) and by_model["claude"].get("score")
        # Count claude from ai_ratings_by_model first, fall back to ai_rating
        ai_r = p.get("ai_rating")
        if has_by_model_claude:
            model_counts["claude"] += 1
        elif isinstance(ai_r, dict) and ai_r.get("score"):
            model_counts["claude"] += 1
        if isinstance(by_model, dict):
            for mk in ("gpt", "gemini"):
                r = by_model.get(mk)
                if isinstance(r, dict) and r.get("score"):
                    model_counts[mk] += 1
    for mk, count in model_counts.items():
        if count >= 5:
            available_models.append({"id": mk, "count": count})

    # Filter papers by model
    filtered = []
    for p in papers:
        rating = _get_paper_si_rating(p, model)
        if rating and isinstance(rating, dict) and rating.get("score"):
            filtered.append({"id": p["id"], "rating": rating, "categories": p.get("categories", [])})

    if len(filtered) < 5:
        return {
            "status": "insufficient_data",
            "total_papers": len(filtered),
            "model": model,
            "available_models": available_models,
        }

    METRICS = ["score", "significance", "rigor", "novelty", "clarity"]
    SUB_METRICS = ["significance", "rigor", "novelty", "clarity"]

    arrays = {}
    for m in METRICS:
        arrays[m] = [p["rating"].get(m, 0) for p in filtered if p["rating"].get(m)]

    # Compute per-paper average of subscores
    subscore_avgs = []
    for p in filtered:
        subs = [p["rating"].get(m) for m in SUB_METRICS if p["rating"].get(m)]
        if len(subs) >= 2:
            subscore_avgs.append(round(sum(subs) / len(subs), 2))
    arrays["subscore_avg"] = subscore_avgs

    ALL_METRICS = METRICS + ["subscore_avg"]

    bins = [round(1.0 + i * 0.5, 1) for i in range(19)]
    distributions = {}
    for m in ALL_METRICS:
        vals = arrays[m]
        if not vals:
            continue
        hist = Counter()
        raw_hist = Counter()
        for v in vals:
            bucket = round(round(v * 2) / 2, 1)
            bucket = max(1.0, min(10.0, bucket))
            hist[bucket] += 1
            raw_bucket = round(v, 1)
            raw_bucket = max(1.0, min(10.0, raw_bucket))
            raw_hist[raw_bucket] += 1
        raw_bins = [round(1.0 + i * 0.1, 1) for i in range(91)]
        distributions[m] = {
            "histogram": [{"bin": b, "count": hist.get(b, 0)} for b in bins],
            "raw_histogram": [{"bin": b, "count": raw_hist.get(b, 0)} for b in raw_bins],
            "mean": round(float(np.mean(vals)), 2),
            "median": round(float(np.median(vals)), 1),
            "std": round(float(np.std(vals, ddof=1)), 2) if len(vals) > 1 else 0,
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
            "n": len(vals),
        }

    metric_correlations = {}
    for i, m1 in enumerate(METRICS):
        for j, m2 in enumerate(METRICS):
            if j <= i:
                continue
            v1 = arrays[m1]
            v2 = arrays[m2]
            n = min(len(v1), len(v2))
            if n < 5:
                continue
            rho, p_val = scipy_stats.spearmanr(v1[:n], v2[:n])
            if not np.isnan(rho):
                metric_correlations[f"{m1} vs {m2}"] = {
                    "spearman": round(float(rho), 3),
                    "p_value": round(float(p_val), 4) if p_val >= 0.0001 else 0.0,
                    "n": n,
                }

    by_category = []
    if not category:
        cat_groups = {}
        for p in filtered:
            cat = p["categories"][0] if p.get("categories") else "unknown"
            if cat not in cat_groups:
                cat_groups[cat] = []
            cat_groups[cat].append(p["rating"])
        for cat, ratings in sorted(cat_groups.items(), key=lambda x: -np.mean([r.get("score", 0) for r in x[1] if r.get("score")])):
            if len(ratings) < 3:
                continue
            scores = [r.get("score", 0) for r in ratings if r.get("score")]
            if scores:
                by_category.append({
                    "category": cat,
                    "count": len(ratings),
                    "mean_score": round(float(np.mean(scores)), 2),
                    "median_score": round(float(np.median(scores)), 1),
                    "std_score": round(float(np.std(scores, ddof=1)), 2) if len(scores) > 1 else 0,
                })

    # Inter-model SI correlation: rank papers by each model's score, compute Spearman
    inter_model_si = {}
    model_scores = {}
    for mk in ("claude", "gpt", "gemini"):
        scores = {}
        for p in papers:
            r = _get_paper_si_rating(p, mk)
            if r and isinstance(r, dict) and r.get("score"):
                scores[p["id"]] = r["score"]
        if len(scores) >= 10:
            model_scores[mk] = scores

    model_keys = sorted(model_scores.keys())
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if j <= i:
                continue
            common = sorted(set(model_scores[m1].keys()) & set(model_scores[m2].keys()))
            if len(common) < 10:
                continue
            v1 = [model_scores[m1][pid] for pid in common]
            v2 = [model_scores[m2][pid] for pid in common]
            rho, p_val = scipy_stats.spearmanr(v1, v2)
            if not np.isnan(rho):
                inter_model_si[f"{m1} vs {m2}"] = {
                    "spearman": round(float(rho), 3),
                    "n": len(common),
                }

    # Per-model comparison: variance, mean, inter-metric correlation
    model_comparison = {}
    METRICS = ["score", "significance", "rigor", "novelty", "clarity"]
    for mk in ("claude", "gpt", "gemini"):
        mk_ratings = []
        for p in papers:
            r = _get_paper_si_rating(p, mk)
            if r and isinstance(r, dict) and r.get("score"):
                mk_ratings.append(r)
        if len(mk_ratings) < 10:
            continue
        mk_scores = [r["score"] for r in mk_ratings]
        # Average inter-metric correlation (all pairs of sub-scores)
        pair_rhos = []
        for mi in range(len(METRICS)):
            for mj in range(mi + 1, len(METRICS)):
                v1 = [r.get(METRICS[mi], 0) for r in mk_ratings if r.get(METRICS[mi])]
                v2 = [r.get(METRICS[mj], 0) for r in mk_ratings if r.get(METRICS[mj])]
                n = min(len(v1), len(v2))
                if n >= 10:
                    rho, _ = scipy_stats.spearmanr(v1[:n], v2[:n])
                    if not np.isnan(rho):
                        pair_rhos.append(float(rho))
        model_comparison[mk] = {
            "n": len(mk_ratings),
            "mean": round(float(np.mean(mk_scores)), 2),
            "std": round(float(np.std(mk_scores, ddof=1)), 2) if len(mk_scores) > 1 else 0,
            "min": round(min(mk_scores), 1),
            "max": round(max(mk_scores), 1),
            "range_used": round(max(mk_scores) - min(mk_scores), 1),
            "avg_inter_metric_rho": round(float(np.mean(pair_rhos)), 3) if pair_rhos else None,
        }

    # PW vs SI: correlate all 3 pairwise estimators against SI scores (overall + per-model)
    pw_vs_si = None
    try:
        from services.ranking import compute_bt_ranking_scores, compute_trueskill_ranking_scores

        # Fetch all standard-mode matches (including model_used for within-model filtering)
        match_query = {"completed": True, "winner_id": {"$exists": True}, "failed": {"$ne": True}, "mode": {"$exists": False}}
        if category:
            match_query["primary_category"] = category
        matches_raw = await collect_all(db.matches.find(
            match_query, {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}
        ))

        if len(matches_raw) >= 20:
            bt_matches = [
                {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                 "winner_id": m["winner_id"], "completed": True, "failed": False}
                for m in matches_raw
            ]
            pw_paper_ids = list(set(
                [m["paper1_id"] for m in matches_raw] + [m["paper2_id"] for m in matches_raw]
            ))

            # Helper to compute all 4 PW scoring methods from a set of matches
            def _compute_all_methods(bt_fmt, pids):
                papers_stub = [{"id": pid, "title": ""} for pid in pids]
                wr_lb = compute_leaderboard(papers_stub, bt_fmt)
                wr_sc = {e["id"]: e["score"] for e in wr_lb}
                paper_stats = {}
                for m in bt_fmt:
                    for pid in (m["paper1_id"], m["paper2_id"]):
                        if pid not in paper_stats:
                            paper_stats[pid] = {"wins": 0, "total": 0}
                        paper_stats[pid]["total"] += 1
                    w = m.get("winner_id")
                    if w and w in paper_stats:
                        paper_stats[w]["wins"] += 1
                reg_wr_sc = {}
                for pid in pids:
                    s = paper_stats.get(pid)
                    if s and s["total"] >= 1:
                        reg_wr_sc[pid] = (s["wins"] + 0.5) / (s["total"] + 1.0)
                return {
                    "raw_wr": wr_sc,
                    "reg_wr": reg_wr_sc,
                    "bt": compute_bt_ranking_scores(bt_fmt, pids),
                    "trueskill": compute_trueskill_ranking_scores(bt_fmt, pids),
                }

            # Combined PW rankings (all models)
            combined_methods = _compute_all_methods(bt_matches, pw_paper_ids)

            # Build SI score maps per model + averaged
            si_maps = {}  # key -> {paper_id: score}
            for mk in ("claude", "gpt", "gemini"):
                sm = {}
                for p in papers:
                    r = _get_paper_si_rating(p, mk)
                    if r and isinstance(r, dict) and r.get("score"):
                        sm[p["id"]] = r["score"]
                if len(sm) >= 10:
                    si_maps[mk] = sm
            # Averaged SI
            avg_si = {}
            for p in papers:
                r = _get_paper_si_rating(p, None)
                if r and isinstance(r, dict) and r.get("score"):
                    avg_si[p["id"]] = r["score"]
            if len(avg_si) >= 10:
                si_maps["avg"] = avg_si

            def _corr(pw_dict, si_dict):
                common = sorted(set(pw_dict.keys()) & set(si_dict.keys()))
                if len(common) < 10:
                    return None
                pw_vals = [pw_dict[pid] for pid in common]
                si_vals = [si_dict[pid] for pid in common]
                rho, _ = scipy_stats.spearmanr(pw_vals, si_vals)
                kt, _ = scipy_stats.kendalltau(pw_vals, si_vals)
                pr, _ = scipy_stats.pearsonr(pw_vals, si_vals)
                if np.isnan(rho):
                    return None
                return {
                    "spearman_rho": round(float(rho), 4),
                    "kendall_tau": round(float(kt), 4),
                    "pearson_r": round(float(pr), 4),
                    "n": len(common),
                }

            pw_labels = {"raw_wr": "Raw WR", "reg_wr": "Reg WR", "bt": "BT", "trueskill": "TrueSkill"}
            method_order = ["raw_wr", "reg_wr", "bt", "trueskill"]

            # Overall: each combined PW method vs averaged SI
            overall = []
            for mk in method_order:
                if "avg" in si_maps:
                    c = _corr(combined_methods[mk], si_maps["avg"])
                    if c:
                        overall.append({"method": mk, "label": pw_labels[mk], **c})

            # Per-model: each combined PW method vs each model's SI
            per_model = {}
            model_labels_map = {"claude": "Claude Opus", "gpt": "GPT-5.2", "gemini": "Gemini 3 Pro"}
            for si_key in ("claude", "gpt", "gemini"):
                if si_key not in si_maps:
                    continue
                rows = []
                for mk in method_order:
                    c = _corr(combined_methods[mk], si_maps[si_key])
                    if c:
                        rows.append({"method": mk, "label": pw_labels[mk], **c})
                if rows:
                    per_model[si_key] = {"label": model_labels_map[si_key], "rows": rows}

            # ── Within-model PW vs SI (model's own matches only) ───────────
            _OPUS_MERGE = {
                "anthropic/claude-opus-4-5-20251101": "claude",
                "anthropic/claude-opus-4-6": "claude",
                "anthropic/claude-opus": "claude",
            }
            _SI_MODEL_MAP = {
                "openai/gpt-5.2": "gpt",
                "gemini/gemini-3-pro-preview": "gemini",
            }
            _SI_MODEL_MAP.update(_OPUS_MERGE)

            model_match_groups = {"claude": [], "gpt": [], "gemini": []}
            for m in matches_raw:
                mu = m.get("model_used", {})
                raw_key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
                short_key = _SI_MODEL_MAP.get(raw_key)
                if short_key and short_key in model_match_groups:
                    model_match_groups[short_key].append(m)

            within_model = {}
            for mk_si in ("claude", "gpt", "gemini"):
                mk_matches = model_match_groups.get(mk_si, [])
                if len(mk_matches) < 20 or mk_si not in si_maps:
                    continue
                mk_bt = [
                    {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                     "winner_id": m["winner_id"], "completed": True, "failed": False}
                    for m in mk_matches
                ]
                mk_pids = list(set(
                    [m["paper1_id"] for m in mk_matches] + [m["paper2_id"] for m in mk_matches]
                ))
                mk_methods = _compute_all_methods(mk_bt, mk_pids)
                rows = []
                for method_key in method_order:
                    c = _corr(mk_methods[method_key], si_maps[mk_si])
                    if c:
                        rows.append({"method": method_key, "label": pw_labels[method_key], **c})
                if rows:
                    within_model[mk_si] = {
                        "label": model_labels_map[mk_si],
                        "rows": rows,
                        "n_matches": len(mk_matches),
                    }

            # ── Build PW vs Claude SI table (within-model + combined) ─────
            pw_vs_claude_si = []
            if "claude" in si_maps:
                wm_claude = within_model.get("claude", {}).get("rows", [])
                for r in wm_claude:
                    pw_vs_claude_si.append({
                        "comparison": f"Claude-only PW ({r['label']}) vs Claude SI",
                        "type": "within",
                        "method": r["method"],
                        "rho": r["spearman_rho"],
                        "n": r["n"],
                    })
                combined_claude = per_model.get("claude", {}).get("rows", [])
                for r in combined_claude:
                    pw_vs_claude_si.append({
                        "comparison": f"Combined PW ({r['label']}) vs Claude SI",
                        "type": "combined",
                        "method": r["method"],
                        "rho": r["spearman_rho"],
                        "n": r["n"],
                    })

            pw_vs_si = {
                "overall": overall,
                "per_model": per_model,
                "within_model": within_model,
                "pw_vs_claude_si": pw_vs_claude_si,
                "n_matches": len(matches_raw),
            }
    except Exception as e:
        logger.warning(f"PW vs SI correlation failed: {e}")

    return {
        "status": "ok",
        "total_papers": len(filtered),
        "model": model,
        "available_models": available_models,
        "distributions": distributions,
        "metric_correlations": metric_correlations,
        "by_category": by_category,
        "inter_model_si": inter_model_si,
        "model_comparison": model_comparison,
        "bt_vs_si": pw_vs_si.get("overall", [{}])[0] if pw_vs_si and pw_vs_si.get("overall") else None,
        "pw_vs_si": pw_vs_si,
        "pw_vs_claude_si": pw_vs_si.get("pw_vs_claude_si", []) if pw_vs_si else [],
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

    # Always query DB (no in-memory cache dependency)
    paper_query = {"categories.0": category} if category else {}
    papers = []
    async for p in db.rankings.find(
        {"category": category} if category else {},
        {"_id": 0, "paper_id": 1, "title": 1}
    ):
        papers.append({"id": p["paper_id"], "title": p["title"]})

    if len(papers) < 5:
        return {"status": "no_data"}

    pid_set = {p["id"] for p in papers}

    match_query = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}
    if category:
        match_query["primary_category"] = category
    all_matches = await collect_all(db.matches.find(
        match_query,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1, "created_at": 1},
    ))
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

    # Compute max avg matches/paper (over ALL papers, not just active)
    full_counts = defaultdict(int)
    for m in all_matches:
        full_counts[m["paper1_id"]] += 1
        full_counts[m["paper2_id"]] += 1
    max_avg = sum(full_counts[pid] for pid in pid_set) / max(n_papers, 1)

    # Pre-compute cumulative avg-per-paper at every match index (O(n) once)
    # avg = total_participations / ALL_papers (not just active), so sub-1.0 values are possible
    import bisect
    _total_match_sum = 0
    _cum_avg = [0.0] * (total + 1)
    for i, m in enumerate(all_matches):
        if m["paper1_id"] in pid_set:
            _total_match_sum += 1
        if m["paper2_id"] in pid_set:
            _total_match_sum += 1
        _cum_avg[i + 1] = _total_match_sum / n_papers

    # Generate sample indices from avg-per-paper targets
    # Step size adapts to dataset size: 0.25 for small, larger for big datasets
    sample_indices = set()
    avg_targets = []
    # For large datasets (>200 papers), use coarser steps to keep computation <10s
    fine_step = 0.5 if n_papers <= 200 else 1.0 if n_papers <= 500 else 2.0
    coarse_step = 2.0 if n_papers <= 200 else 4.0 if n_papers <= 500 else 8.0
    fine_limit = min(10.0, max_avg)
    t = fine_step
    while t <= fine_limit:
        avg_targets.append(round(t, 2))
        t += fine_step
    t = fine_limit + coarse_step
    while t <= max_avg + coarse_step:
        avg_targets.append(round(t, 1))
        t += coarse_step
    if avg_targets and avg_targets[-1] < max_avg * 0.95:
        avg_targets.append(max_avg)

    for target_avg in avg_targets:
        idx = bisect.bisect_left(_cum_avg, target_avg, 1, total + 1)
        if idx <= total:
            sample_indices.add(idx)
    # Always include the final point
    if total > 0:
        sample_indices.add(total)

    sample_indices = sorted(sample_indices)

    # Start with explicit origin point
    curve = [{
        "matches": 0, "avg_matches_per_paper": 0, "papers_covered": 0,
        "spearman": 0, "kendall": 0, "pearson": 0,
    }]
    for best_n in sample_indices:
        subset = all_matches[:best_n]
        paper_match_count = defaultdict(int)
        for m in subset:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1

        active = [pid for pid in pid_set if paper_match_count[pid] > 0]
        if len(active) < 5:
            continue

        avg_mpp = sum(paper_match_count[pid] for pid in pid_set) / n_papers

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
            "avg_matches_per_paper": round(avg_mpp, 1),
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



@router.get("/sitemap.xml", response_class=None)
async def sitemap():
    """Dynamic XML sitemap including all paper detail pages."""
    from fastapi.responses import Response

    base = "https://kurate.org"
    static_pages = [
        ("", "daily", "1.0"),
        ("/correlation", "daily", "0.8"),
        ("/methodology", "monthly", "0.6"),
        ("/validation", "weekly", "0.7"),
        ("/prompts", "monthly", "0.4"),
    ]

    urls = []
    for path, freq, priority in static_pages:
        urls.append(f"  <url><loc>{base}{path}</loc><changefreq>{freq}</changefreq><priority>{priority}</priority></url>")

    # Add paper pages from rankings DB
    async for r in db.rankings.find({}, {"_id": 0, "paper_id": 1}):
        pid = r.get("paper_id", "")
        if pid:
            urls.append(f"  <url><loc>{base}/paper/{pid}</loc><changefreq>weekly</changefreq><priority>0.5</priority></url>")

    # Add archive pages
    archives = await db.leaderboard_archives.find(
        {}, {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1}
    ).to_list(5000)
    for a in archives:
        slug = f"w{a['week']}" if a.get("week") else f"m{a['month']}"
        urls.append(f"  <url><loc>{base}/leaderboard/{a['category']}/{a['year']}/{slug}</loc><changefreq>never</changefreq><priority>0.6</priority></url>")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"

    return Response(content=xml, media_type="application/xml")


# ─── Weekly Archive System ───────────────────────────────────────────────────

@router.get("/archive/list")
async def list_archives(category: str = Query(None)):
    """List available archived leaderboard snapshots for a category, filtered by configured frequency."""
    query = {}
    if category:
        query["category"] = category
    archives = await db.leaderboard_archives.find(
        query, {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1,
                "period_type": 1, "paper_count": 1, "match_count": 1, "created_at": 1, "label": 1}
    ).sort([("year", -1), ("week", -1), ("month", -1)]).to_list(200)
    if category:
        from core.auth import get_settings
        settings = await get_settings()
        archives = _filter_archives_by_frequency(archives, category, settings)
    return {"archives": archives}


@router.get("/archive/{category}/{year}/w{week}")
async def get_weekly_archive(category: str, year: int, week: int):
    """Get a specific weekly archive snapshot."""
    doc = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "week": week, "period_type": "weekly"},
        {"_id": 0}
    )
    if not doc:
        return {"status": "not_found"}
    return doc


@router.get("/archive/{category}/{year}/m{month}")
async def get_monthly_archive(category: str, year: int, month: int):
    """Get a specific monthly archive snapshot."""
    doc = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "month": month, "period_type": "monthly"},
        {"_id": 0}
    )
    if not doc:
        return {"status": "not_found"}
    return doc

@router.get("/archive/{category}/older")
async def get_older_archive(category: str):
    """Get the 'Older' catch-all archive for papers before the first weekly snapshot."""
    doc = await db.leaderboard_archives.find_one(
        {"category": category, "period_type": "older"},
        {"_id": 0}
    )
    if not doc:
        return {"status": "not_found"}
    return doc




async def create_archive_snapshot(category: str, period_type: str = "weekly"):
    """Create a frozen leaderboard snapshot for the given category.
    Called by the scheduler at the configured interval."""
    utc_now = datetime.now(timezone.utc)
    year = utc_now.isocalendar()[0]
    week = utc_now.isocalendar()[1]
    month = utc_now.month

    # Check if this snapshot already exists
    if period_type == "weekly":
        existing = await db.leaderboard_archives.find_one(
            {"category": category, "year": year, "week": week, "period_type": "weekly"})
    else:
        existing = await db.leaderboard_archives.find_one(
            {"category": category, "year": year, "month": month, "period_type": "monthly"})
    if existing:
        return None  # Already archived

    # Get papers for this period from rankings DB
    period_filter = _build_period_filter("month" if period_type == "monthly" else "week")
    rank_query = {"category": category}
    rank_query.update(period_filter)
    source_entries = await db.rankings.find(rank_query, _RANK_PROJ).sort("score", -1).to_list(10000)
    if not source_entries:
        return None

    # Freeze the leaderboard: store essential fields only
    frozen_entries = []
    for i, r in enumerate(source_entries, 1):
        frozen_entries.append({
            "rank": i,
            "id": r.get("paper_id"),
            "title": r.get("title", ""),
            "authors": r.get("authors", []),
            "score": r.get("score"),
            "wins": r.get("wins"),
            "losses": r.get("losses"),
            "comparisons": r.get("comparisons"),
            "win_rate": r.get("win_rate"),
            "ci": r.get("ci"),
            "wilson_margin": r.get("wilson_margin"),
            "published": r.get("published"),
            "link": r.get("link"),
            "arxiv_id": r.get("arxiv_id"),
            "ai_rating": r.get("ai_rating"),
            "gap_score": r.get("gap_score"),
        })

    if period_type == "weekly":
        label = f"Week {week}, {year}"
    else:
        month_names = ["", "January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        label = f"{month_names[month]} {year}"

    doc = {
        "category": category,
        "period_type": period_type,
        "year": year,
        "week": week if period_type == "weekly" else None,
        "month": month if period_type == "monthly" else None,
        "label": label,
        "paper_count": len(frozen_entries),
        "match_count": sum(e.get("comparisons") or 0 for e in frozen_entries) // 2,
        "leaderboard": frozen_entries,
        "created_at": utc_now.isoformat(),
    }

    await db.leaderboard_archives.insert_one(doc)
    logger.info(f"Archive snapshot created: {category} {label} ({len(frozen_entries)} papers)")

    # Pre-render badge images for top 3 papers
    try:
        from routers.badges import _get_badge_data, _render_badge_image
        from core.image_store import store_image
        slug = f"w{week}" if period_type == "weekly" else f"m{month}"
        period_key_letter = "w" if period_type == "weekly" else "m"
        period_num = week if period_type == "weekly" else month
        for entry in frozen_entries[:3]:
            if entry.get("rank", 99) > 3:
                continue
            try:
                data = await _get_badge_data(category, year, period_num, entry["id"]) if period_type == "weekly" else None
                if not data:
                    continue
                img_bytes = _render_badge_image(data)
                store_key = f"badge:{period_key_letter}:{category}/{year}/{period_num}/{entry['id']}"
                await store_image(store_key, img_bytes)
            except Exception as e:
                logger.warning(f"Pre-render badge failed for {entry['id']}: {e}")
        logger.info(f"Pre-rendered badge images for {category} {label}")
    except Exception as e:
        logger.warning(f"Badge pre-render skipped: {e}")

    return doc


async def run_archive_snapshots():
    """Create both weekly and monthly snapshots as appropriate.
    Weekly: every Monday. Monthly: 1st of month. Both always created for all categories."""
    from core.auth import get_settings
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))

    utc_now = datetime.now(timezone.utc)
    is_monday = utc_now.weekday() == 0
    is_first = utc_now.day == 1

    created = 0
    for cat in active_cats:
        if is_monday:
            result = await create_archive_snapshot(cat, "weekly")
            if result:
                created += 1
        if is_first:
            result = await create_archive_snapshot(cat, "monthly")
            if result:
                created += 1
                created += 1

    if created:
        logger.info(f"Archive snapshots: {created} new snapshots created")
    return created
