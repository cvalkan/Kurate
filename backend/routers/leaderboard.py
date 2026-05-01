from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
from collections import Counter
import asyncio
import time
from core.config import db, logger, CATEGORIES
from routers.validation_utils import collect_all
from services.ranking import compute_leaderboard, compute_leaderboard_async, calculate_confidence_interval, wilson_margin_pct

router = APIRouter(prefix="/api")

# Pre-computed cache — refreshed in the background, never blocks requests
_cache = {"ts": 0, "categories": {}, "total_papers": 0, "total_matches": 0, "warming_up": True}
_bg_task_started = False
_cache_dirty = asyncio.Event()  # Set by compare/fetch loops when data changes

# Cached match counts — updated on data change, not per-request.
# Eliminates a 50-200ms COLLSCAN on the matches collection for every leaderboard request.
_analysis_prewarm_done = False  # Set to True by server.py after prewarm completes
_match_count_cache = {}  # category_or_"__all__" -> {"count": int, "ts": float}
_MATCH_COUNT_TTL = 300  # 5 min TTL (safety net — normally invalidated by data change)

# --- Incremental match counters (avoid full-collection aggregation in _refresh_cache) ---
# Seeded from DB at startup, incremented by run_comparison_round.
# Used by _refresh_cache instead of scanning the matches collection.
_incr_match_counts = {}   # {category: count} — successful matches only
_incr_failed_counts = {}  # {category: count} — failed matches only
_incr_seeded = False      # True after initial seed from DB


async def _seed_match_counters():
    """One-time seed from DB. Called at startup."""
    global _incr_seeded
    async for doc in db.matches.aggregate([
        {"$match": {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}},
        {"$group": {"_id": "$primary_category", "count": {"$sum": 1}}},
    ]):
        _incr_match_counts[doc["_id"]] = doc["count"]

    async for doc in db.matches.aggregate([
        {"$match": {"failed": True, "mode": {"$exists": False}}},
        {"$group": {"_id": "$primary_category", "count": {"$sum": 1}}},
    ]):
        _incr_failed_counts[doc["_id"]] = doc["count"]

    _incr_seeded = True
    logger.info(f"Match counters seeded: {sum(_incr_match_counts.values())} ok, {sum(_incr_failed_counts.values())} failed across {len(_incr_match_counts)} categories")


def bump_match_counter(category: str, failed: bool = False):
    """Called after each match completes. O(1), no DB access."""
    if failed:
        _incr_failed_counts[category] = _incr_failed_counts.get(category, 0) + 1
    else:
        _incr_match_counts[category] = _incr_match_counts.get(category, 0) + 1


def get_match_counts_snapshot() -> tuple:
    """Return (match_counts_by_cat, failed_by_cat) from incremental counters.
    Falls back to empty dicts if not yet seeded (startup race)."""
    return dict(_incr_match_counts), dict(_incr_failed_counts)


async def _get_match_count(category: str = None) -> int:
    """Return cached match count for a category (or all). Refreshes on miss/stale."""
    key = category or "__all__"
    cached = _match_count_cache.get(key)
    if cached and (time.time() - cached["ts"]) < _MATCH_COUNT_TTL:
        return cached["count"]
    q = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}
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
    # Trigger background recompute of All Categories model analysis
    try:
        from services.model_analysis import mark_live_analysis_dirty
        mark_live_analysis_dirty()
    except Exception:
        pass

# Tag query cache — keyed on (frozenset(tags), period, tag_mode, global_stats, show_all)
_tag_cache = {}  # key -> {"ts": float, "result": dict}
_TAG_CACHE_TTL = 20  # Same as main cache TTL
_TAG_CACHE_MAX = 100  # Max cached tag combos




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
    set(m for _, m in model_counts)

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

    # --- Counts (from incremental counters — no matches collection scan) ---
    total_papers = await db.rankings.count_documents({})
    match_counts_by_cat, failed_by_cat = get_match_counts_snapshot()
    total_matches = sum(match_counts_by_cat.values())

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

    progress_by_cat = {}

    # --- Summary stats via aggregation ---
    summary_stats = await _compute_summary_stats_agg()

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
        {"$match": {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}},
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
    logger.info(f"Metadata cache refresh took {_t1 - _t0:.1f}s ({total_papers} papers, {total_matches} matches) [RSS: {get_mem_mb():.0f}MB]")


async def _bg_cache_loop():
    """Background loop that refreshes cache ONLY when data changes."""
    global _bg_task_started
    _bg_task_started = True
    # Delay initial cache warm to let health checks respond first
    await asyncio.sleep(5)
    # Seed incremental match counters from DB (one-time)
    try:
        await _seed_match_counters()
    except Exception as e:
        logger.warning(f"Match counter seed failed: {e}")
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
        await asyncio.sleep(30)  # Debounce: remaining cache data (tags, PDF stats) is slow-changing
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
        asyncio.create_task(_bg_archive_loop())
        asyncio.create_task(_bg_memory_heartbeat())



async def _bg_memory_heartbeat():
    """Log memory every 5 minutes for production visibility."""
    from core.memlog import log_mem
    await asyncio.sleep(60)  # Wait for startup to settle
    while True:
        log_mem("heartbeat")
        await asyncio.sleep(300)  # Every 5 min



async def _bg_archive_loop():
    """Background loop that checks and creates archive snapshots daily at 00:00 UTC.
    On startup, runs with catch_up=True to fill any gaps from missed Monday windows."""
    from core.memlog import log_mem
    await asyncio.sleep(30)  # Wait for cache to warm

    # First iteration: catch-up mode — create current week/month if missing
    try:
        from core.auth import get_settings
        settings = await get_settings()
        if not settings.get("paused", False):
            log_mem("archive_loop initial catch-up start")
            await run_archive_snapshots(catch_up=True)
            log_mem("archive_loop initial catch-up done")
        else:
            log_mem("archive_loop skipped catch-up (system paused)")
    except Exception as e:
        logger.warning(f"Archive snapshot catch-up failed: {e}")

    while True:
        # Sleep until next day at 00:05 UTC
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        sleep_seconds = (tomorrow - now).total_seconds()
        await asyncio.sleep(max(sleep_seconds, 3600))

        try:
            from core.auth import get_settings
            settings = await get_settings()
            if settings.get("paused", False):
                log_mem("archive_loop skipped (system paused)")
                continue
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
        {"$match": {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}},
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



# ─── DB-Backed Leaderboard Serving (Phase 2) ────────────────────────────────

# Projection for rankings queries — exclude MongoDB _id, include all serving fields
_RANK_PROJ = {"_id": 0, "paper_id": 1, "category": 1, "rank": 1, "rank_wr": 1, "rank_ts": 1, "rank_os": 1,
              "score": 1, "ts_score": 1, "ts_mu": 1, "ts_sigma": 1,
              "os_score": 1, "os_sigma": 1,
              "ci": 1, "wilson_margin": 1, "win_rate": 1, "wins": 1, "losses": 1,
              "comparisons": 1, "title": 1, "authors": 1, "arxiv_id": 1, "link": 1,
              "published": 1, "added_at": 1, "ai_rating": 1, "gap_score": 1, "gap_score_ts": 1,
              "categories": 1, "current_version": 1, "is_latest_version": 1}


def _encode_cursor(score: int, paper_id: str) -> str:
    """Encode a keyset pagination cursor as a URL-safe base64 token."""
    import base64
    import json
    payload = json.dumps({"s": score, "p": paper_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple:
    """Decode a keyset cursor → (score, paper_id). Returns (None, None) on invalid input."""
    import base64
    import json
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload["s"], payload["p"]
    except Exception:
        return None, None


def _rank_doc_to_entry(doc: dict) -> dict:
    """Convert a rankings DB document to a leaderboard entry (matching the old cache format).
    Uses rank_ts (TrueSkill rank) as the primary rank — the canonical ranking metric."""
    entry = {
        "id": doc["paper_id"],
        "rank": doc.get("rank_ts", doc.get("rank", 0)),
        "rank_wr": doc.get("rank_wr", doc.get("rank", 0)),
        "rank_ts": doc.get("rank_ts", doc.get("rank", 0)),
        "title": doc.get("title", ""),
        "authors": doc.get("authors", []),
        "arxiv_id": doc.get("arxiv_id", ""),
        "link": doc.get("link", ""),
        "published": doc.get("published", ""),
        "score": doc.get("score", 1200),
        "ts_score": doc.get("ts_score", 1200),
        "ts_sigma": doc.get("ts_sigma"),
        "ci": doc.get("ci", 0),
        "wilson_margin": doc.get("wilson_margin", 100.0),
        "win_rate": doc.get("win_rate", 0.0),
        "wins": doc.get("wins", 0),
        "losses": doc.get("losses", 0),
        "comparisons": doc.get("comparisons", 0),
        **({"ai_rating": doc["ai_rating"]} if doc.get("ai_rating") else {}),
        **({"gap_score": doc["gap_score"]} if doc.get("gap_score") is not None else {}),
        **({"gap_score_ts": doc["gap_score_ts"]} if doc.get("gap_score_ts") is not None else {}),
        **({"os_score": doc["os_score"]} if doc.get("os_score") is not None else {}),
        **({"os_sigma": doc["os_sigma"]} if doc.get("os_sigma") is not None else {}),
        **({"rank_os": doc["rank_os"]} if doc.get("rank_os") is not None else {}),
    }
    # Propagate the arXiv version for the leaderboard `vN` badge (only shown
    # when > 1). Ranking rows don't always carry current_version directly —
    # it's denormalized from the paper doc at seed time; missing value means
    # v1.
    if doc.get("current_version") and doc["current_version"] > 1:
        entry["current_version"] = doc["current_version"]
    return entry



# Mapping from frontend sort keys to MongoDB field names + default direction
_SORT_FIELD_MAP = {
    "rank": ("rank", 1),
    "score": ("ts_score", -1),  # WR no longer selectable — redirect to TS
    "win_rate": ("win_rate", -1),
    "comparisons": ("comparisons", -1),
    "wilson_margin": ("wilson_margin", 1),
    "published": ("published", -1),
    "title": ("title", 1),
    "ts_score": ("ts_score", -1),
    "ts_sigma": ("ts_sigma", 1),  # Lower sigma = more confident = default ascending
    "ai_rating": ("ai_rating", -1),
    "gap_score": ("gap_score", -1),
    "gap_score_ts": ("gap_score_ts", -1),
    "os_score": ("os_score", -1),
    "os_sigma": ("os_sigma", 1),
}


def _resolve_sort(sort_by: str = None, sort_dir: str = None, default_field: str = "ts_score"):
    """Resolve frontend sort params to MongoDB sort spec.
    
    Returns (mongo_sort_list, is_default_sort).
    is_default_sort=True means ts_score desc (the default ranking) — allows keyset cursor.
    """
    if not sort_by or sort_by == "rank":
        # Default sort: TrueSkill score descending with paper_id tiebreaker
        # sort_dir flips it: "asc" = rank 1,2,3 (ts_score desc), "desc" = reversed
        if sort_dir == "desc":
            return [("ts_score", 1), ("paper_id", 1)], False
        return [("ts_score", -1), ("paper_id", -1)], True

    field, default_dir = _SORT_FIELD_MAP.get(sort_by, (sort_by, -1))
    direction = 1 if sort_dir == "asc" else (-1 if sort_dir == "desc" else default_dir)
    # Add paper_id as tiebreaker for stable pagination
    return [(field, direction), ("paper_id", -1 if direction == -1 else 1)], False


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


async def _db_category_leaderboard(category: str, period: str, limit: int, offset: int, search: str = None, cursor: str = None, sort_by: str = None, sort_dir: str = None):
    """Serve primary category leaderboard from DB rankings collection."""
    _t0 = time.time()
    try:
        result = await _db_category_leaderboard_impl(category, period, limit, offset, search, cursor, sort_by, sort_dir)
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
    """Community correlation — removed (AlphaXiv experiment obsolete)."""
    return None


async def _db_category_leaderboard_impl(category: str, period: str, limit: int, offset: int, search: str = None, cursor: str = None, sort_by: str = None, sort_dir: str = None):
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
    # Exclude frozen older paper versions — denormalized flag on ranking rows.
    # Missing field == latest (legacy rankings pre-refactor).
    query["is_latest_version"] = {"$ne": False}

    # Period filter (rolling window for "recent")
    if period == "recent":
        query.update(recent_filter)
    else:
        query.update(_build_period_filter(period))

    if search:
        import re as _re
        _s = _re.escape(search)
        query["$or"] = [
            {"title": {"$regex": _s, "$options": "i"}},
            {"authors": {"$regex": _s, "$options": "i"}},
        ]

    # Phase 2: Query-dependent count + archives in parallel
    total_in_period, archives = await asyncio.gather(
        db.rankings.count_documents(query),
        _get_archives_for_category(category, settings),
    )

    mongo_sort, is_default_sort = _resolve_sort(sort_by, sort_dir)

    # Keyset pagination: O(1) for any page depth — only works with default ts_score sort
    if cursor and not search and is_default_sort:
        cursor_score, cursor_pid = _decode_cursor(cursor)
        if cursor_score is not None:
            query["$or"] = [
                {"ts_score": {"$lt": cursor_score}},
                {"ts_score": cursor_score, "paper_id": {"$lt": cursor_pid}},
            ]
            offset = 0

    cursor_obj = db.rankings.find(query, _RANK_PROJ).sort(mongo_sort).skip(offset).limit(limit)
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
        next_cursor = _encode_cursor(last_doc.get("ts_score", 0), last_doc.get("paper_id", ""))

    # is_ranking = actively running pairwise comparisons right now
    from services.scheduler import _get_cat_status
    cat_status = _get_cat_status(category)
    cat_activity = cat_status.get("current_activity", "")
    is_ranking = cat_activity.startswith("Comparing") and cat_status.get("is_processing", False)

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


async def _db_all_papers_leaderboard(period: str, limit: int, offset: int, search: str = None, cursor: str = None, sort_by: str = None, sort_dir: str = None):
    """Serve cross-category 'all papers' leaderboard from DB rankings."""
    _t0 = time.time()
    try:
        result = await _db_all_papers_leaderboard_impl(period, limit, offset, search, cursor, sort_by, sort_dir)
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


async def _db_all_papers_leaderboard_impl(period: str, limit: int, offset: int, search: str = None, cursor: str = None, sort_by: str = None, sort_dir: str = None):
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
    # Exclude frozen older paper versions
    query["is_latest_version"] = {"$ne": False}

    if search:
        import re as _re
        _s = _re.escape(search)
        query["$or"] = [
            {"title": {"$regex": _s, "$options": "i"}},
            {"authors": {"$regex": _s, "$options": "i"}},
        ]

    total_in_period = await db.rankings.count_documents(query)

    mongo_sort, is_default_sort = _resolve_sort(sort_by, sort_dir)

    # Keyset pagination (only with default ts_score sort)
    if cursor and not search and is_default_sort:
        cursor_score, cursor_pid = _decode_cursor(cursor)
        if cursor_score is not None:
            query["$or"] = [
                {"ts_score": {"$lt": cursor_score}},
                {"ts_score": cursor_score, "paper_id": {"$lt": cursor_pid}},
            ]
            offset = 0

    cursor_obj = db.rankings.find(query, _RANK_PROJ).sort(mongo_sort).skip(offset).limit(limit)
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
        next_cursor = _encode_cursor(last_doc.get("ts_score", 0), last_doc.get("paper_id", ""))

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
    search: str = None, cursor: str = None, sort_by: str = None, sort_dir: str = None,
):
    """Serve tag-filtered leaderboard from DB rankings."""
    _t0 = time.time()
    try:
        result = await _db_tag_leaderboard_impl(tag_list, period, limit, offset, tag_mode, global_stats, show_all, search, cursor, sort_by, sort_dir)
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
    search: str = None, cursor: str = None, sort_by: str = None, sort_dir: str = None,
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
    # Exclude frozen older paper versions
    rank_query["is_latest_version"] = {"$ne": False}

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

    mongo_sort, is_default_sort = _resolve_sort(sort_by, sort_dir)

    # Keyset pagination (only with default ts_score sort)
    if cursor and not search and is_default_sort:
        cursor_score, cursor_pid = _decode_cursor(cursor)
        if cursor_score is not None:
            rank_query["$or"] = [
                {"ts_score": {"$lt": cursor_score}},
                {"ts_score": cursor_score, "paper_id": {"$lt": cursor_pid}},
            ]
            offset = 0

    cursor_obj = db.rankings.find(rank_query, _RANK_PROJ).sort(mongo_sort).skip(offset).limit(limit)
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
            wr_matches = [
                {"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                 "winner_id": m["winner_id"], "completed": True, "failed": False}
                for m in local_matches
            ]
            papers_stub = [{"id": pid, "title": ""} for pid in paper_id_set]
            local_lb = compute_leaderboard(papers_stub, wr_matches)
            local_map = {e["id"]: e for e in local_lb}
            for entry in entries:
                loc = local_map.get(entry["id"])
                if loc:
                    entry["score"] = loc["score"]
                    entry["win_rate"] = loc["win_rate"]
                    entry["wins"] = loc["wins"]
                    entry["losses"] = loc["losses"]
                    entry["comparisons"] = loc["comparisons"]
            # Only re-sort by local score when using default sort;
            # preserve the user's explicit sort otherwise.
            if is_default_sort:
                entries.sort(key=lambda e: (-e["score"], e["id"]))
            for i, e in enumerate(entries):
                e["rank"] = i + 1

    next_cursor = None
    if entries and last_doc and len(entries) == limit:
        next_cursor = _encode_cursor(last_doc.get("ts_score", 0), last_doc.get("paper_id", ""))

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
    limit: int = Query(200, description="Max papers to return", ge=1, le=10000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor (from previous response's next_cursor)"),
    sort_by: Optional[str] = Query(None, description="Sort field: score, win_rate, comparisons, published, wilson_margin, ts_score, ai_rating, gap_score, title"),
    sort_dir: Optional[str] = Query(None, description="Sort direction: asc or desc"),
):
    # Tag-based filtering
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()][:50]
        if tag_list:
            return await _db_tag_leaderboard(tag_list, period, limit, offset, tag_mode, global_stats, show_all, search, cursor, sort_by, sort_dir)

    # All papers cross-category
    if show_all:
        return await _db_all_papers_leaderboard(period, limit, offset, search, cursor, sort_by, sort_dir)

    # Primary category leaderboard — served from DB rankings
    return await _db_category_leaderboard(category, period, limit, offset, search, cursor, sort_by, sort_dir)


def _filter_archives_by_frequency(archives, category, settings):
    """Filter archive list to show only the type configured by admin (weekly or monthly).
    Sorts by recency."""
    freq_config = settings.get("archive_frequency") or {}
    freq = freq_config.get(category, freq_config.get("default", "weekly"))
    target_type = "monthly" if freq == "monthly" else "weekly"

    filtered = []
    for a in archives:
        if a.get("period_type") != target_type:
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
        {"_id": 0, "revision_superseded": 1, "paper1_id": 1, "paper2_id": 1,
         "winner_id": 1, "reasoning": 1, "model_used": 1, "created_at": 1,
         "failed": 1, "id": 1},
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

    # Enrich matches with paper titles. Split out `revision_superseded` matches
    # from legacy in-place revision data (pre-standalone-paper-per-version
    # refactor). These are kept in `archived_matches` for backward compat; new
    # revisions don't produce superseded matches anymore.
    enriched_matches = []
    archived_matches = []
    for m in matches:
        opponent_id = m["paper2_id"] if m["paper1_id"] == paper_id else m["paper1_id"]
        opp = opponent_lookup.get(opponent_id, {})
        won = m.get("winner_id") == paper_id
        entry = {
            "id": m["id"],
            "opponent_id": opponent_id,
            "opponent_title": opp.get("title", "Unknown"),
            "opponent_arxiv_id": opp.get("arxiv_id", ""),
            "won": won,
            "reasoning": m.get("reasoning", ""),
            "model_used": m.get("model_used", {}),
            "created_at": m.get("created_at", ""),
            "failed": m.get("failed", False),
        }
        if m.get("revision_superseded"):
            archived_matches.append(entry)
        else:
            enriched_matches.append(entry)

    # Stats from rankings collection (same source as leaderboard — always in sync)
    ranking_doc = await db.rankings.find_one(
        {"paper_id": paper_id},
        {"_id": 0, "wins": 1, "losses": 1, "comparisons": 1,
         "score": 1, "rank": 1, "rank_ts": 1, "win_rate": 1, "ci": 1, "wilson_margin": 1,
         "ts_score": 1, "ts_sigma": 1, "os_score": 1, "os_sigma": 1, "revision_badge": 1}
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

    # Merge ranking scores into paper for frontend display
    if ranking_doc:
        for field in ["ts_score", "ts_sigma", "os_score", "os_sigma"]:
            if ranking_doc.get(field) is not None:
                paper[field] = ranking_doc[field]

    # Sibling versions: find all standalone papers sharing the same arxiv_id_base
    # (new standalone-paper-per-version model). Only returned when there are ≥2
    # versions — drives the version toggle on the paper page.
    if paper.get("arxiv_id_base"):
        siblings = []
        async for sib in db.papers.find(
            {"arxiv_id_base": paper["arxiv_id_base"]},
            {"_id": 0, "id": 1, "arxiv_id": 1, "current_version": 1,
             "is_latest_version": 1, "added_at": 1, "frozen_at": 1}
        ).sort("current_version", 1):
            siblings.append({
                "paper_id": sib["id"],
                "arxiv_id": sib.get("arxiv_id"),
                "version": sib.get("current_version", 1),
                "is_latest": sib.get("is_latest_version", True),
                "added_at": sib.get("added_at"),
                "frozen_at": sib.get("frozen_at"),
            })
        if len(siblings) >= 2:
            paper["sibling_versions"] = siblings

    # Get category OS score range for CI bar
    primary_cat = paper.get("categories", [None])[0]
    if primary_cat:
        for score_field, min_key, max_key in [
            ("os_score", "category_os_min", "category_os_max"),
            ("ts_score", "category_ts_min", "category_ts_max"),
        ]:
            pipeline = [
                {"$match": {"category": primary_cat, score_field: {"$exists": True, "$ne": None}}},
                {"$group": {"_id": None, "min_val": {"$min": f"${score_field}"}, "max_val": {"$max": f"${score_field}"}}},
            ]
            async for agg in db.rankings.aggregate(pipeline):
                paper[min_key] = agg.get("min_val")
                paper[max_key] = agg.get("max_val")

    # Get current rank and total papers in category
    # Use TS rank (TrueSkill) — the canonical ranking metric
    if ranking_doc and primary_cat:
        from routers.badges import CATEGORIES as _CAT_NAMES
        rank_ts = ranking_doc.get("rank_ts") or ranking_doc.get("rank")
        if rank_ts:
            paper["current_rank"] = rank_ts
        total_in_cat = await db.rankings.count_documents({"category": primary_cat})
        paper["total_in_category"] = total_in_cat
        paper["category_name"] = _CAT_NAMES.get(primary_cat, primary_cat)

    response = {
        "paper": paper,
        "matches": enriched_matches,
        "stats": stats,
    }
    if archived_matches:
        response["archived_matches"] = archived_matches

    return response


_status_cache = {"data": None, "ts": 0}


@router.get("/status")
async def get_system_status():
    from services.scheduler import get_scheduler_status

    now = time.time()
    if _status_cache["data"] is None or now - _status_cache["ts"] > 10:
        # Query DB directly — no dependency on in-memory cache
        total_papers = await db.rankings.count_documents({})
        total_matches = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}
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


# Cache for convergence endpoints (keyed by category+mode). Model analysis uses analysis_store.




# Sequential lock for model-analysis computation — prevents concurrent heavy computations
_analysis_compute_lock = asyncio.Lock()

@router.get("/model-analysis")
async def get_model_analysis(
    category: Optional[str] = Query(None, description="Filter by category (None = all)"),
):
    """Live model analysis with optional cached OpenSkill.
    WR/TS/SI data computed fresh from rankings (~200ms).
    OpenSkill columns merged from cache if available."""
    cat_key = category or "__all__"

    # Always compute live + merge OS (cached together as one complete result)
    from services.model_analysis import compute_live_analysis
    live = await compute_live_analysis(category)

    return live

@router.get("/convergence")
async def get_convergence(
    category: Optional[str] = Query(None),
    steps: int = Query(20),
):
    """Convergence analysis. Reads from pre-computed MongoDB document (<10ms).
    Recomputed in background after comparison rounds — never blocks user requests."""
    cat_key = category or "__all__"
    doc = await db.convergence_cache.find_one(
        {"category": cat_key}, {"_id": 0}
    )
    if doc and doc.get("curve"):
        return doc
    # No cached data yet — trigger background computation, return immediately
    asyncio.create_task(_compute_and_store_convergence(category, steps))
    return {"status": "computing", "category": cat_key, "curve": [],
            "message": "Convergence chart is being computed. Reload in a few seconds."}


async def _compute_and_store_convergence(category, steps):
    """Background task: compute convergence and store in MongoDB."""
    try:
        cat_key = category or "__all__"
        result = await _compute_convergence(category, steps)
        if result.get("curve"):
            await db.convergence_cache.update_one(
                {"category": cat_key},
                {"$set": result},
                upsert=True,
            )
    except Exception as e:
        logger.warning(f"Convergence computation failed for {category}: {e}")


async def _compute_convergence(category, steps):
    """Convergence analysis: how ranking stability improves as matches accumulate."""
    from scipy import stats as scipy_stats
    from collections import defaultdict
    from core.auth import get_settings

    settings = await get_settings()
    top_k_focus = settings.get("top_k_focus", 10)

    # Always query DB (no in-memory cache dependency)
    papers = []
    async for p in db.rankings.find(
        {"category": category} if category else {},
        {"_id": 0, "paper_id": 1, "title": 1}
    ):
        papers.append({"id": p["paper_id"], "title": p["title"]})

    if len(papers) < 5:
        return {"status": "no_data"}

    pid_set = {p["id"] for p in papers}

    match_query = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}
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
    # Uniform 0.5 step for all categories
    sample_indices = set()
    avg_targets = []
    step = 0.5
    t = step
    while t <= max_avg + step:
        avg_targets.append(round(t, 1))
        t += step
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
        "category": category or "__all__",
        "total_matches": total,
        "total_papers": n_papers,
        "top_k_values": top_k_values,
        "curve": curve,
    }



@router.get("/sitemap.xml", response_class=None)
async def sitemap_index():
    """Sitemap index pointing to sub-sitemaps for pages, papers, and archives."""
    from fastapi.responses import Response
    base = "https://kurate.org"
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += f'  <sitemap><loc>{base}/api/sitemap-pages.xml</loc></sitemap>\n'
    xml += f'  <sitemap><loc>{base}/api/sitemap-papers.xml</loc></sitemap>\n'
    xml += f'  <sitemap><loc>{base}/api/sitemap-archives.xml</loc></sitemap>\n'
    xml += '</sitemapindex>'
    return Response(content=xml, media_type="application/xml")


@router.get("/sitemap-pages.xml", response_class=None)
async def sitemap_pages():
    """Static pages + category leaderboards."""
    from fastapi.responses import Response
    from core.auth import get_settings
    from core.config import CATEGORIES

    base = "https://kurate.org"
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))

    urls = []
    for path, freq, pri in [
        ("", "daily", "1.0"), ("/correlation", "daily", "0.8"),
        ("/methodology", "monthly", "0.6"), ("/validation", "weekly", "0.7"),
        ("/prompts", "monthly", "0.4"), ("/privacy", "yearly", "0.3"), ("/impressum", "yearly", "0.3"),
    ]:
        urls.append(f'  <url><loc>{base}{path}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>')
    for cat in active_cats:
        urls.append(f'  <url><loc>{base}/?cat={cat}</loc><changefreq>daily</changefreq><priority>0.9</priority></url>')

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls) + "\n</urlset>"
    return Response(content=xml, media_type="application/xml")


@router.get("/sitemap-papers.xml", response_class=None)
async def sitemap_papers():
    """All paper detail pages."""
    from fastapi.responses import Response
    base = "https://kurate.org"
    urls = []
    async for r in db.rankings.find({}, {"_id": 0, "paper_id": 1}):
        pid = r.get("paper_id", "")
        if pid:
            urls.append(f'  <url><loc>{base}/paper/{pid}</loc><changefreq>weekly</changefreq><priority>0.5</priority></url>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls) + "\n</urlset>"
    return Response(content=xml, media_type="application/xml")


@router.get("/sitemap-archives.xml", response_class=None)
async def sitemap_archives():
    """All archive leaderboard pages."""
    from fastapi.responses import Response
    base = "https://kurate.org"
    urls = []
    archives = await db.leaderboard_archives.find(
        {}, {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1}
    ).to_list(5000)
    for a in archives:
        slug = f"w{a['week']}" if a.get("week") else f"m{a['month']}"
        urls.append(f'  <url><loc>{base}/leaderboard/{a["category"]}/{a["year"]}/{slug}</loc><changefreq>never</changefreq><priority>0.6</priority></url>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls) + "\n</urlset>"
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
    Called by the scheduler at the configured interval.

    Archives the PREVIOUS completed period — not the current one — so that
    all papers for that period have had time to be fetched, summarized, and
    ranked before the snapshot is frozen.
    """
    utc_now = datetime.now(timezone.utc)

    if period_type == "weekly":
        # Archive PREVIOUS week (the one that just ended)
        from datetime import date
        prev_week_date = utc_now - timedelta(days=7)
        year = prev_week_date.isocalendar()[0]
        week = prev_week_date.isocalendar()[1]
    else:
        # Archive PREVIOUS month
        first_of_this_month = utc_now.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        year = last_of_prev_month.year
        month = last_of_prev_month.month

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
    # Use calendar boundaries (not rolling window) to prevent cross-period overlap
    if period_type == "monthly":
        from calendar import monthrange
        month_start = f"{year}-{month:02d}-01T00:00:00+00:00"
        _, last_day = monthrange(year, month)
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        month_end = f"{next_year}-{next_month:02d}-01T00:00:00+00:00"
        period_filter = {"published": {"$gte": month_start, "$lt": month_end}}
    else:
        # Weekly: use ISO week boundaries
        from datetime import date
        week_start_date = date.fromisocalendar(year, week, 1)
        week_end_date = week_start_date + timedelta(days=7)
        period_filter = {"published": {
            "$gte": f"{week_start_date.isoformat()}T00:00:00+00:00",
            "$lt": f"{week_end_date.isoformat()}T00:00:00+00:00",
        }}

    rank_query = {"category": category, "is_latest_version": {"$ne": False}}
    rank_query.update(period_filter)
    source_entries = await db.rankings.find(rank_query, _RANK_PROJ).sort("ts_score", -1).to_list(10000)
    if not source_entries:
        return None

    # Freeze the leaderboard: entries sorted by score descending.
    # Rank = array position (1-indexed). No rank field stored — derived from position.
    frozen_entries = []
    for r in source_entries:
        entry = {
            "id": r.get("paper_id"),
            "title": r.get("title", ""),
            "authors": r.get("authors", []),
            "score": r.get("ts_score") or r.get("score"),
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
        }
        frozen_entries.append(entry)

    if period_type == "weekly":
        label = f"Week {week}, {year}"
    else:
        month_names = ["", "January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        label = f"{month_names[month]} {year}"

    doc = {
        "category": category,
        "period_type": period_type,
        "scoring_method": "ts",
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

    from core.memlog import log_event
    await log_event("archive_created", category=category,
        detail=f"{label} — {len(frozen_entries)} papers",
        count=len(frozen_entries), label=label, period_type=period_type)

    # Pre-render badge images for top 3 papers
    try:
        from routers.badges import _get_badge_data, _render_badge_image
        from core.image_store import store_image
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


async def run_archive_snapshots(catch_up: bool = False):
    """Create both weekly and monthly snapshots as appropriate.
    Weekly: every Monday. Monthly: 1st of month. Both always created for all categories.

    When catch_up=True (used on startup), always attempt to create the current
    week and current month archives regardless of day-of-week.  This makes the
    archiver resilient to server restarts — if the Monday window was missed,
    the next startup will fill the gap.  create_archive_snapshot is idempotent
    so duplicate calls are harmless.
    """
    from core.auth import get_settings
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))

    utc_now = datetime.now(timezone.utc)
    should_weekly = catch_up or utc_now.weekday() == 0  # Monday or catch-up
    should_monthly = catch_up or utc_now.day == 1        # 1st or catch-up

    created = 0
    for cat in active_cats:
        if should_weekly:
            result = await create_archive_snapshot(cat, "weekly")
            if result:
                created += 1
        if should_monthly:
            result = await create_archive_snapshot(cat, "monthly")
            if result:
                created += 1

    if created:
        logger.info(f"Archive snapshots: {created} new snapshots created (catch_up={catch_up})")
    return created


# ─── Live Tournament Positional Bias Analysis ────────────────────────────────
# These endpoints analyze ONLY db.matches (live tournament), never db.validation_matches.

from scipy import stats as scipy_stats
from collections import defaultdict


@router.get("/positional-bias")
async def positional_bias(since: str = None):
    """Compute positional bias from the live tournament matches collection.

    In the scheduler, papers are randomly flipped before being sent to the LLM,
    and stored as paper1_id (shown first) and paper2_id (shown second).
    So winner_id == paper1_id means the model picked the first-position paper.
    
    Optional `since` param (ISO date) to exclude old matches.
    """
    match_filter = {
        "completed": True, "failed": {"$ne": True}, "winner_id": {"$exists": True},
        "mode": {"$exists": False},
    }
    if since:
        match_filter["created_at"] = {"$gte": since}
    matches = await collect_all(
        db.matches.find(
            match_filter,
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
        )
    )

    if not matches:
        return {"models": [], "total": 0, "message": "No completed matches yet"}

    by_model = defaultdict(lambda: {"pos1": 0, "pos2": 0, "total": 0})
    overall = {"pos1": 0, "pos2": 0, "total": 0}

    for m in matches:
        model_name = m.get("model_used", {}).get("model")
        if not model_name:
            continue
        winner = m.get("winner_id")
        p1 = m.get("paper1_id")
        if not winner or not p1:
            continue

        picked_first = (winner == p1)
        bucket = by_model[model_name]
        if picked_first:
            bucket["pos1"] += 1
            overall["pos1"] += 1
        else:
            bucket["pos2"] += 1
            overall["pos2"] += 1
        bucket["total"] += 1
        overall["total"] += 1

    results = []
    for model_name, stats in sorted(by_model.items(), key=lambda x: -x[1]["total"]):
        n = stats["total"]
        if n == 0:
            continue
        pos1_rate = stats["pos1"] / n
        p_value = float(scipy_stats.binomtest(stats["pos1"], n, 0.5).pvalue)
        results.append({
            "model": model_name,
            "pos1_wins": stats["pos1"],
            "pos2_wins": stats["pos2"],
            "total": n,
            "pos1_rate": round(pos1_rate * 100, 2),
            "pos2_rate": round((1 - pos1_rate) * 100, 2),
            "bias_direction": "first" if pos1_rate > 0.5 else "second",
            "bias_magnitude": round(abs(pos1_rate - 0.5) * 100, 2),
            "p_value": round(p_value, 6),
            "significant": p_value < 0.05,
        })

    n_all = overall["total"]
    pos1_rate_all = overall["pos1"] / n_all if n_all else 0
    p_all = float(scipy_stats.binomtest(overall["pos1"], n_all, 0.5).pvalue) if n_all else 1.0

    return {
        "models": results,
        "overall": {
            "pos1_wins": overall["pos1"],
            "pos2_wins": overall["pos2"],
            "total": n_all,
            "pos1_rate": round(pos1_rate_all * 100, 2),
            "p_value": round(p_all, 6),
            "significant": p_all < 0.05,
        },
        "note": "Position 1 = paper presented first in the prompt. The scheduler randomly flips presentation order for each match. A 50/50 split indicates no positional bias. P-values from exact binomial test (H0: p=0.5).",
    }


@router.get("/positional-bias-diagnostic")
async def positional_bias_diagnostic(group: str = "month"):
    """Detailed positional bias breakdown by period, model, and mode."""
    from datetime import date as _date

    stats = defaultdict(lambda: defaultdict(lambda: {"pos1": 0, "pos2": 0, "total": 0}))

    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "winner_id": {"$exists": True}},
        {"_id": 0, "paper1_id": 1, "winner_id": 1, "model_used": 1, "created_at": 1, "mode": 1,
         "content_mode": 1},
    ):
        created = str(m.get("created_at", ""))[:10]
        if group == "week" and len(created) >= 10:
            try:
                d = _date.fromisoformat(created)
                period = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
            except (ValueError, TypeError):
                period = created[:7]
        else:
            period = created[:7]
        model = m.get("model_used", {}).get("model", "unknown") if isinstance(m.get("model_used"), dict) else str(m.get("model_used", "unknown"))
        mode = m.get("mode") or m.get("content_mode") or "standard"
        is_pos1 = m["winner_id"] == m["paper1_id"]

        stats[period][f"{model}|{mode}"]["pos1" if is_pos1 else "pos2"] += 1
        stats[period][f"{model}|{mode}"]["total"] += 1

    result = []
    for period in sorted(stats.keys()):
        for model_mode, s in sorted(stats[period].items()):
            model, mode = model_mode.split("|", 1)
            t = s["total"]
            if t < 10:
                continue
            result.append({
                "period": period,
                "model": model,
                "mode": mode,
                "total": t,
                "pos1": s["pos1"],
                "pos1_pct": round(s["pos1"] / t * 100, 1),
            })

    return {"breakdown": result}


@router.get("/match-mode-stats")
async def match_mode_stats():
    """Breakdown of live tournament matches by content_mode, mode, and model."""
    pipeline = [
        {"$match": {"completed": True, "failed": {"$ne": True}, "winner_id": {"$exists": True}}},
        {"$group": {
            "_id": {
                "content_mode": {"$ifNull": ["$content_mode", "NO_CONTENT_MODE"]},
                "mode": {"$ifNull": ["$mode", "NO_MODE"]},
                "model": {"$ifNull": [
                    {"$cond": [{"$eq": [{"$type": "$model_used"}, "object"]}, "$model_used.model", "$model_used"]},
                    "unknown"
                ]},
            },
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    results = await db.matches.aggregate(pipeline).to_list(100)

    rows = [{"content_mode": r["_id"]["content_mode"], "mode": r["_id"]["mode"],
             "model": r["_id"]["model"], "count": r["count"]} for r in results]

    return {"rows": rows, "total_matches": sum(r["count"] for r in rows)}
