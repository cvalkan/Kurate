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
_bg_task_started = False
_cache_dirty = asyncio.Event()  # Set by compare/fetch loops when data changes


def notify_data_changed():
    """Call this when matches or papers are added/changed. Triggers a cache refresh."""
    _cache_dirty.set()

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


async def _refresh_cache():
    """Heavy computation — builds a new cache dict, then swaps atomically.
    The old cache continues serving requests during the entire computation."""
    global _cache
    _t0 = time.time()

    # Run heavy MongoDB loads with yields between each to let requests through
    async def _load_data():
        papers = await db.papers.find(
            {"summaries": {"$exists": True, "$ne": {}}},
            {"_id": 0, "full_text": 0, "abstract": 0}
        ).to_list(5000)
        await asyncio.sleep(0)  # Yield after papers load
        matches = await db.matches.find(
            {"completed": True, "failed": {"$ne": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1, "mode": 1, "shared_categories": 1, "primary_category": 1, "model_used": 1, "tokens": 1, "created_at": 1, "id": 1},
        ).to_list(200000)
        await asyncio.sleep(0)  # Yield after matches load
        likes = {}
        async for doc in db.alphaxiv_likes.find({}, {"_id": 0, "id": 1, "likes": 1}):
            if doc.get("likes") is not None:
                likes[doc["id"]] = doc["likes"]
        return papers, matches, likes

    all_papers, all_matches_raw, alphaxiv_likes = await _load_data()
    await asyncio.sleep(0)  # Yield before processing

    # Build added_at lookup for "Most Recent" filter
    _added_at_lookup = {}
    for p in all_papers:
        added = p.get("added_at")
        if added and len(added) >= 10:
            try:
                _added_at_lookup[p["id"]] = datetime.fromisoformat(added.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

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

    # --- Load AI ratings (single-item scores from summary generation) ---
    ai_ratings = {}
    for p in all_papers:
        rating = p.get("ai_rating")
        if rating and isinstance(rating, dict) and rating.get("score"):
            ai_ratings[p["id"]] = round(rating["score"], 1)

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

        # Inject AlphaXiv community likes and AI ratings into leaderboard entries
        for entry in full:
            likes = alphaxiv_likes.get(entry["id"])
            if likes is not None:
                entry["community_likes"] = likes
            ai_r = ai_ratings.get(entry["id"])
            if ai_r is not None:
                entry["ai_rating"] = ai_r

        # Compute SP score (BT percentile - AI percentile) for papers with both signals
        entries_with_both = [e for e in full if e.get("ai_rating") and e.get("comparisons", 0) >= 3]
        if len(entries_with_both) >= 2:
            from scipy import stats as _sp_stats
            import numpy as _np
            _bt_vals = _np.array([e["score"] for e in entries_with_both])
            _si_vals = _np.array([e["ai_rating"] for e in entries_with_both])
            _bt_pct = _sp_stats.rankdata(_bt_vals) / len(entries_with_both) * 100
            _si_pct = _sp_stats.rankdata(_si_vals) / len(entries_with_both) * 100
            _sp_raw = _bt_pct - _si_pct
            for i, entry in enumerate(entries_with_both):
                entry["sp_score"] = round(float(_sp_raw[i]), 1)

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

        # "Recent" = papers added to the system in last 48h, sorted by published date
        added_cutoff = utc_now - timedelta(hours=48)
        recent_by_added = [{**e} for e in full if _added_at_lookup.get(e["id"], datetime.min.replace(tzinfo=timezone.utc)) >= added_cutoff]
        for i, e in enumerate(recent_by_added):
            e["rank"] = i + 1

        categories_data[cat_id] = {
            "all": full,
            "recent": recent_by_added if recent_by_added else filter_and_rerank(recent_cutoff),
            "week": filter_and_rerank(utc_now - timedelta(weeks=1)),
            "month": filter_and_rerank(utc_now - timedelta(days=30)),
            "_matches": len(cat_matches),
            "_papers": len(cat_papers),
            "_is_ranking": True,
        }

        # Compute community correlation if enough data
        liked_entries = [(e["score"], e["community_likes"]) for e in full if "community_likes" in e]
        if len(liked_entries) >= 10:
            import scipy.stats
            scores, likes = zip(*liked_entries)
            rho, pval = scipy.stats.spearmanr(scores, likes)
            categories_data[cat_id]["_community_correlation"] = {
                "rho": round(rho, 4) if not (rho != rho) else None,
                "p_value": round(pval, 4) if not (pval != pval) else None,
                "n": len(liked_entries),
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
        filtered, _ = _apply_period_filter(all_full, period_key, added_at_lookup=_added_at_lookup)
        all_periods[period_key] = filtered

    # Build new cache dict (old cache continues serving during this entire function)
    new_cache = {
        "ts": time.time(),
        "categories": categories_data,
        "total_papers": len(all_papers),
        "total_matches": len(all_matches),
        "warming_up": False,
        "_raw_papers": all_papers,
        "_raw_matches": all_matches,
        "_added_at_lookup": _added_at_lookup,
        "_raw_matches_all": all_matches_raw,
        "_match_index": match_index,
        "_paper_cat_lookup": paper_cat_lookup,
        "_all_papers_leaderboard": all_periods,
    }
    # Preserve keys that other code sets on the cache (archives, failed counts, etc.)
    for k in _cache:
        if k not in new_cache:
            new_cache[k] = _cache[k]
    # Atomic swap — requests see either the old cache or the new one, never a mix
    _cache = new_cache
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
    # Use aggregation to count chars server-side — avoids loading full_text over the network
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

    # Update _is_ranking from freshly computed progress (not stale DB)
    for cat_id, prog in progress_by_cat.items():
        if cat_id in categories_data:
            categories_data[cat_id]["_is_ranking"] = not prog.get("goals_met", False)

    await asyncio.sleep(0)  # Yield after progress computation

    # --- Pre-compute summary stats (avoids expensive DB scan on /stats) ---
    summary_stats_by_cat = {"__all__": {"models": {}, "papers_with_summaries": 0, "papers_with_all_3": 0}}
    for p in all_papers:
        cat = p.get("categories", ["unknown"])[0] if p.get("categories") else "unknown"
        sums = p.get("summaries", {})
        sum_tokens = p.get("summary_tokens", {})
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
                    summary_stats_by_cat[bucket]["models"][mk] = {"summaries": 0, "tracked_input": 0, "tracked_output": 0, "tracked_thinking": 0, "tracked_count": 0}
                summary_stats_by_cat[bucket]["models"][mk]["summaries"] += 1
                # Aggregate actual tracked tokens if available
                tk = sum_tokens.get(mk)
                if tk and isinstance(tk, dict):
                    summary_stats_by_cat[bucket]["models"][mk]["tracked_input"] += tk.get("input", 0)
                    summary_stats_by_cat[bucket]["models"][mk]["tracked_output"] += tk.get("output", 0)
                    summary_stats_by_cat[bucket]["models"][mk]["tracked_thinking"] += tk.get("thinking", 0)
                    summary_stats_by_cat[bucket]["models"][mk]["tracked_count"] += 1
        if model_count >= 3:
            summary_stats_by_cat[cat]["papers_with_all_3"] += 1
            summary_stats_by_cat["__all__"]["papers_with_all_3"] += 1

    _cache["_summary_stats"] = summary_stats_by_cat

    # --- Pre-compute per-category rating stats (for instant admin panel display) ---
    rating_stats = {"__all__": {"rated": 0, "with_summaries": 0}}
    for p in all_papers:
        cat = p.get("categories", ["unknown"])[0] if p.get("categories") else "unknown"
        if cat not in rating_stats:
            rating_stats[cat] = {"rated": 0, "with_summaries": 0}
        has_summary = bool(p.get("summaries"))
        has_rating = bool(p.get("ai_rating") and isinstance(p.get("ai_rating"), dict) and p["ai_rating"].get("score"))
        if has_summary:
            rating_stats[cat]["with_summaries"] += 1
            rating_stats["__all__"]["with_summaries"] += 1
        if has_rating:
            rating_stats[cat]["rated"] += 1
            rating_stats["__all__"]["rated"] += 1
    _cache["_rating_stats"] = rating_stats

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

    # Pre-load archive list (lightweight metadata only)
    try:
        archive_docs = await db.leaderboard_archives.find(
            {}, {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1,
                 "period_type": 1, "paper_count": 1, "match_count": 1, "label": 1}
        ).sort([("year", -1), ("week", -1)]).to_list(500)
        _cache["_archives"] = archive_docs
    except Exception:
        _cache["_archives"] = []


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
    """Background loop that refreshes model-correlation and convergence when data changes."""
    await asyncio.sleep(15)  # Wait for leaderboard cache to be ready first

    # Compute once immediately on startup
    async def _refresh_analysis():
        try:
            from core.auth import get_settings
            settings = await get_settings()
            cats = settings.get("active_categories", [])
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
                await asyncio.sleep(0)
            logger.info(f"Analysis cache refreshed: {len(cats)} categories")
        except Exception as e:
            logger.warning(f"Analysis cache refresh failed: {e}")

    await _refresh_analysis()

    while True:
        # Wait ONLY for data change — no timeout fallback
        await _cache_dirty.wait()
        _cache_dirty.clear()
        await asyncio.sleep(15)  # Debounce — let a full match round complete
        _cache_dirty.clear()
        await _refresh_analysis()



async def _bg_archive_loop():
    """Background loop that checks and creates archive snapshots daily at 00:00 UTC."""
    await asyncio.sleep(30)  # Wait for cache to warm
    while True:
        try:
            await run_archive_snapshots()
        except Exception as e:
            logger.warning(f"Archive snapshot check failed: {e}")
        # Sleep until next day at 00:05 UTC
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        sleep_seconds = (tomorrow - now).total_seconds()
        await asyncio.sleep(max(sleep_seconds, 3600))  # At least 1 hour between checks


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
    """Filter leaderboard entries by title or author search and re-rank."""
    if not search:
        return data
    search_lower = search.lower()
    filtered = [p for p in data if search_lower in p.get("title", "").lower()
                or any(search_lower in a.lower() for a in (p.get("authors") or []))]
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

    from core.auth import get_settings
    settings = await get_settings()

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
        "community_correlation": cat_data.get("_community_correlation"),
        "show_rating_column": settings.get("show_rating_column", True),
        "show_gap_column": settings.get("show_gap_column", True),
        "archives": _filter_archives_by_frequency(
            [a for a in cache.get("_archives", []) if a.get("category") == category],
            category, settings),
    }


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
    data, total_in_period = _apply_period_filter(full, period, added_at_lookup=cache.get("_added_at_lookup"))

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
    _SHORT_NAMES = {"anthropic/claude-opus": "Claude Opus"}

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
                    "id": pid,
                    "title": paper_titles.get(pid, "Unknown")[:50],
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

    return {
        "models": [{"key": mk, "short": _short(mk), **model_summaries.get(mk, {})} for mk in model_keys],
        "correlations": sorted_correlations,
        "agreement": sorted_agreement,
        "scatter_data": scatter_data,
        "n_common_papers": len(common_papers),
        "category": category,
        "mode": mode,
    }



@router.get("/si-rating-stats")
async def get_si_rating_stats(
    category: Optional[str] = Query(None, description="Filter by primary category"),
    model: Optional[str] = Query(None, description="Filter by model: claude, gpt, gemini, or None for all"),
):
    """Single-item rating distributions and inter-metric correlations from live leaderboard data."""
    cache_key = f"{model or 'all'}"
    cached = _get_analysis_cached("si-rating-stats", category, cache_key)
    if cached and cached.get("bt_vs_si") is not None:
        return cached
    result = await _compute_si_rating_stats(category, model)
    if result.get("bt_vs_si") is not None:
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

    papers = await db.papers.find(
        query,
        {"_id": 0, "id": 1, "ai_rating": 1, "ai_ratings_by_model": 1, "categories": 1}
    ).to_list(10000)

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

    arrays = {}
    for m in METRICS:
        arrays[m] = [p["rating"].get(m, 0) for p in filtered if p["rating"].get(m)]

    bins = [round(1.0 + i * 0.5, 1) for i in range(19)]
    distributions = {}
    for m in METRICS:
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

    # BT Pairwise Ranking vs Claude Opus 4.6 Thinking Single-Item Score Correlation
    bt_vs_si = None
    try:
        # Collect BT scores from leaderboard cache or compute from DB
        bt_ranks = {}
        cache = _cache
        if cache.get("categories"):
            if category and cache["categories"].get(category):
                for entry in cache["categories"][category].get("all", []):
                    bt_ranks[entry["id"]] = entry.get("score", 0)
            else:
                for cat_data in cache["categories"].values():
                    for entry in cat_data.get("all", []):
                        if entry["id"] not in bt_ranks:
                            bt_ranks[entry["id"]] = entry.get("score", 0)

        if not bt_ranks:
            from services.ranking import compute_leaderboard
            match_query = {"completed": True, "failed": {"$ne": True}}
            if category:
                match_query["$or"] = [{"shared_categories": category}, {"primary_category": category}]
            raw_matches = await db.matches.find(
                match_query,
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1}
            ).to_list(200000)
            paper_query = {"summaries": {"$exists": True, "$ne": {}}}
            if category:
                paper_query["categories.0"] = category
            bt_papers = await db.papers.find(paper_query, {"_id": 0, "id": 1}).to_list(5000)
            if bt_papers and raw_matches:
                lb = compute_leaderboard(bt_papers, raw_matches)
                bt_ranks = {e["id"]: e.get("score", 0) for e in lb}

        # Use ONLY Claude SI scores (from ai_rating or ai_ratings_by_model.claude)
        si_map = {}
        for p in papers:
            claude_score = None
            by_model = p.get("ai_ratings_by_model", {})
            if isinstance(by_model, dict) and isinstance(by_model.get("claude"), dict):
                claude_score = by_model["claude"].get("score")
            if not claude_score:
                ai_r = p.get("ai_rating")
                if isinstance(ai_r, dict):
                    claude_score = ai_r.get("score")
            if claude_score and p["id"] in bt_ranks:
                si_map[p["id"]] = claude_score

        if len(si_map) >= 10:
            shared = sorted(si_map.keys())
            bt_vals = [bt_ranks[pid] for pid in shared]
            si_vals = [si_map[pid] for pid in shared]
            rho, p_val = scipy_stats.spearmanr(bt_vals, si_vals)
            kt, kt_p = scipy_stats.kendalltau(bt_vals, si_vals)
            pr, pr_p = scipy_stats.pearsonr(bt_vals, si_vals)
            if not np.isnan(rho):
                bt_vs_si = {
                    "spearman_rho": round(float(rho), 4),
                    "kendall_tau": round(float(kt), 4),
                    "pearson_r": round(float(pr), 4),
                    "n": len(shared),
                }
    except Exception as e:
        logger.warning(f"BT vs SI correlation failed: {e}")

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
        "bt_vs_si": bt_vs_si,
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
    # For large datasets (>200 papers), use coarser steps to keep computation <30s
    fine_step = 0.25 if n_papers <= 500 else 0.5 if n_papers <= 1000 else 1.0
    coarse_step = 1.0 if n_papers <= 500 else 2.0 if n_papers <= 1000 else 4.0
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

    # Add paper pages from cache
    papers = _cache.get("_raw_papers", [])
    for p in papers:
        pid = p.get("id", "")
        if pid:
            urls.append(f"  <url><loc>{base}/paper/{pid}</loc><changefreq>weekly</changefreq><priority>0.5</priority></url>")

    # Add archive pages
    archives = await db.leaderboard_archives.find(
        {}, {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1}
    ).to_list(1000)
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

    # Get the appropriate leaderboard period from cache
    cat_data = _cache.get("categories", {}).get(category, {})
    period_key = "month" if period_type == "monthly" else "week"
    source_lb = cat_data.get(period_key, [])
    if not source_lb:
        return None

    # Freeze the leaderboard: store essential fields only
    frozen_entries = []
    for entry in source_lb:
        frozen_entries.append({
            "rank": entry.get("rank"),
            "id": entry.get("id"),
            "title": entry.get("title", ""),
            "authors": entry.get("authors", []),
            "score": entry.get("score"),
            "wins": entry.get("wins"),
            "losses": entry.get("losses"),
            "comparisons": entry.get("comparisons"),
            "win_rate": entry.get("win_rate"),
            "ci": entry.get("ci"),
            "wilson_margin": entry.get("wilson_margin"),
            "published": entry.get("published"),
            "link": entry.get("link"),
            "arxiv_id": entry.get("arxiv_id"),
            "ai_rating": entry.get("ai_rating"),
            "sp_score": entry.get("sp_score"),
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
