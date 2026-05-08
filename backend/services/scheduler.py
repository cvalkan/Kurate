import asyncio
import os
import re
import uuid
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict
from core.config import db, logger, CATEGORIES
from core.auth import get_settings
from services.arxiv import fetch_arxiv_papers, strip_arxiv_version
from services.llm import download_and_extract_pdf, compare_papers, generate_precomparison_impact_summary


from routers.validation_utils import collect_all

_scheduler_running = False
_processing_locks = {}  # Per-category locks
_fetching_cats = set()  # Categories currently being fetched
_wake_event: asyncio.Event = None  # Wake scheduler immediately on resume

# Compare loop diagnostics — exposed via get_scheduler_diagnostics()
_compare_loop_diag = {
    "last_cycle_at": None,
    "last_cycle_unmet": [],
    "last_cycle_results": {},  # cat -> {"status": str, "completed": int, "failed": int}
    "cycles_since_restart": 0,
    "loop_alive": False,
}


def _get_lock(category: str) -> asyncio.Lock:
    if category not in _processing_locks:
        _processing_locks[category] = asyncio.Lock()
    return _processing_locks[category]


# Per-category status for live UI updates
_category_status: Dict[str, dict] = {}

# Track summary generation progress (per-category)
_summary_gen_progress: Dict[str, dict] = {}

# Instant stop flag for summary generation — set by pause toggle,
# checked inside gen_one without waiting for settings cache refresh
_summary_gen_stop = False


# --- Pair-exhaustion tracking ---
# Categories where _select_pairs returned 0 pairs are marked as exhausted.
# They won't be retried until paper/match counts change (new data invalidates exhaustion).
_pair_exhausted_cats: Dict[str, dict] = {}  # {category: {"papers": N, "matches": M}}


def _mark_pair_exhausted(category: str):
    """Mark a category as pair-exhausted (no new pairs possible)."""
    cat_status = _get_cat_status(category)
    _pair_exhausted_cats[category] = {
        "papers": cat_status.get("papers_count", 0),
        "matches": cat_status.get("matches_count", 0),
    }
    logger.info(f"[{category}] Marked pair-exhausted (no pairs available)")


def _is_pair_exhausted(category: str) -> bool:
    """Check if a category is pair-exhausted and nothing has changed since."""
    snap = _pair_exhausted_cats.get(category)
    if not snap:
        return False
    cat_status = _get_cat_status(category)
    if (cat_status.get("papers_count", 0) != snap["papers"] or
            cat_status.get("matches_count", 0) != snap["matches"]):
        del _pair_exhausted_cats[category]
        return False
    return True



def stop_summary_generation():
    """Signal all running summary generation to stop immediately."""
    global _summary_gen_stop
    _summary_gen_stop = True


def get_summary_gen_progress(category: str = None) -> dict:
    """Get the current summary generation progress for a category.
    Detects stale locks (running > 30 min) and auto-clears them."""
    import time
    key = category or "__all__"
    progress = _summary_gen_progress.get(key, {"running": False})
    if progress.get("running"):
        started = progress.get("started_at_ts", 0)
        if started and time.time() - started > 1800:  # 30 min
            logger.warning(f"Summary gen stale lock detected for {key} (started {int(time.time() - started)}s ago). Clearing.")
            progress["running"] = False
            progress["stale_cleared"] = True
    return progress


def _get_cat_status(category: str) -> dict:
    if category not in _category_status:
        _category_status[category] = {
            "last_fetch_at": None,
            "last_process_at": None,
            "is_fetching": False,
            "is_processing": False,
            "papers_count": 0,
            "matches_count": 0,
            "current_activity": "Idle",
            "next_fetch_at": None,
        }
    return _category_status[category]


async def _collect_cursor_docs(cursor, batch_size: int = 500):
    """Collect all documents from a Motor cursor without imposing a hard cap."""
    docs = []
    while True:
        batch = await cursor.to_list(length=batch_size)
        if not batch:
            break
        docs.extend(batch)
        if len(batch) < batch_size:
            break
        await asyncio.sleep(0)
    return docs


def get_scheduler_status(category: str = None) -> dict:
    """Get scheduler status for a specific category or global summary."""
    if category and category in _category_status:
        return _category_status[category]
    # Global summary
    return {
        "is_fetching": any(s.get("is_fetching") for s in _category_status.values()),
        "is_processing": any(s.get("is_processing") for s in _category_status.values()),
        "current_activity": _get_global_activity(),
        "categories": {k: v.get("current_activity", "Idle") for k, v in _category_status.items()},
    }


def get_scheduler_diagnostics() -> dict:
    """Get compare loop diagnostics — exposes cycle tracking for debugging stalls."""
    return dict(_compare_loop_diag)




def wake_scheduler():
    """Wake the scheduler immediately (e.g., after resuming a tournament)."""
    global _wake_event
    if _wake_event:
        _wake_event.set()



def _get_global_activity() -> str:
    active = [f"{k}: {v['current_activity']}" for k, v in _category_status.items()
              if v.get("current_activity") not in ("Idle", "Goals met — idle")]
    return "; ".join(active) if active else "Idle"


def _prompt_hash(prompt_config: dict) -> str:
    """Short hash of prompt text for version tracking."""
    text = (prompt_config.get("system_prompt", "") + prompt_config.get("user_prompt", "")).encode()
    return hashlib.sha256(text).hexdigest()[:8]


async def init_tournament_registry():
    """Ensure a tournament document exists for each primary category. Uses upsert to prevent duplicates."""
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))

    for cat_id in active_cats:
        tid = f"cat={cat_id}|mode=standard"
        paper_count = await db.papers.count_documents({"categories.0": cat_id})
        match_count = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": cat_id, "mode": {"$exists": False}, "revision_superseded": {"$ne": True}}
        )
        await db.tournaments.update_one(
            {"tournament_id": tid},
            {"$setOnInsert": {
                "tournament_id": tid,
                "category": cat_id,
                "mode": "standard",
                "status": "active",
                "goals": {
                    "ci_target": settings.get("ci_target", 10),
                    "ci_target_general": settings.get("ci_target_general", 15),
                    "top_k": settings.get("top_k_focus", 10),
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }, "$set": {
                "stats": {
                    "papers": paper_count,
                    "matches": match_count,
                    "goals_met": False,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

    # Clean up any orphan/duplicate tournaments without a valid tournament_id
    await db.tournaments.delete_many({"tournament_id": {"$exists": False}})
    await db.tournaments.delete_many({"tournament_id": None})

    total = await db.tournaments.count_documents({})
    logger.info(f"Tournament registry: {total} tournaments")



async def update_tournament_stats(category: str, mode: str = "standard"):
    """Update stats on a tournament document."""
    tid = f"cat={category}|mode={mode}"
    paper_count = _get_cat_status(category).get("papers_count", 0)
    match_count = _get_cat_status(category).get("matches_count", 0)
    update_fields = {
        "stats.papers": paper_count,
        "stats.matches": match_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tournaments.update_one(
        {"tournament_id": tid},
        {"$set": update_fields},
    )


async def start_scheduler():
    global _scheduler_running, _wake_event
    if _scheduler_running:
        return
    _scheduler_running = True
    _wake_event = asyncio.Event()
    # Initialize status for all active categories (dynamic from settings)
    try:
        settings = await get_settings()
    except Exception as e:
        logger.error(f"start_scheduler: get_settings failed: {e}")
        settings = {}
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))
    for cat_id in active_cats:
        cat_status = _get_cat_status(cat_id)
        # Hydrate last_fetch_at from settings
        flat_key = f"last_fetch_at_{cat_id.replace('.', '_')}"
        val = settings.get(flat_key)
        if val and isinstance(val, str):
            cat_status["last_fetch_at"] = val
        else:
            parts = cat_id.split(".")
            if len(parts) == 2:
                nested = settings.get(f"last_fetch_at_{parts[0]}")
                if isinstance(nested, dict) and parts[1] in nested:
                    cat_status["last_fetch_at"] = nested[parts[1]]
    logger.info("Background scheduler started")
    asyncio.create_task(_fetch_loop())
    asyncio.create_task(_compare_loop())


async def _fetch_loop():
    """Independent loop for fetching papers + generating summaries. Never blocks comparisons.
    Processes ONE category at a time with a cooldown between categories to avoid
    overwhelming the MongoDB connection pool on remote (Atlas) instances."""
    from core.memlog import log_mem
    await asyncio.sleep(8)  # Let compare loop start first

    while _scheduler_running:
        try:
            await _fetch_loop_inner()
        except Exception as e:
            import traceback
            logger.error(f"Fetch loop CRASHED: {e}")
            log_mem(f"Fetch loop CRASHED: {traceback.format_exc()[-300:]}")
            await asyncio.sleep(60)  # Back off and retry


async def _fetch_loop_inner():
    from core.memlog import log_mem

    while _scheduler_running:
        next_due_seconds = float("inf")
        try:
            settings = await get_settings()

            # Respect global pause
            if settings.get("paused", False):
                await asyncio.sleep(60)
                continue

            interval_hours = settings.get("fetch_interval_hours", 6)
            now = datetime.now(timezone.utc)

            fetch_cats = set(c for c in settings.get("active_categories", list(CATEGORIES.keys())) if c and c.strip())
            for cat in fetch_cats:
                cat_status = _get_cat_status(cat)

                # Check per-tournament fetch_paused flag
                tid = f"cat={cat}|mode=standard"
                t_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "fetch_paused": 1})
                if t_doc and t_doc.get("fetch_paused"):
                    continue

                last_fetch_key = f"last_fetch_at_{cat.replace('.', '_')}"
                last_fetch = settings.get(last_fetch_key)
                if not last_fetch or not isinstance(last_fetch, str):
                    parts = cat.split(".")
                    if len(parts) == 2:
                        nested = settings.get(f"last_fetch_at_{parts[0]}")
                        if isinstance(nested, dict):
                            last_fetch = nested.get(parts[1])

                should_fetch = False
                if not last_fetch:
                    should_fetch = True
                elif now >= datetime.fromisoformat(last_fetch) + timedelta(hours=interval_hours):
                    should_fetch = True
                else:
                    secs_until = (datetime.fromisoformat(last_fetch) + timedelta(hours=interval_hours) - now).total_seconds()
                    next_due_seconds = min(next_due_seconds, secs_until)

                if should_fetch:
                    result = await run_fetch_cycle(category=cat)
                    # Only advance last_fetch_at if the fetch actually succeeded
                    # (not rate-limited or errored). Otherwise we'd skip papers permanently.
                    fetch_failed = bool(result.get("errors"))
                    if not fetch_failed:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        await db.settings.update_one(
                            {"key": "global"},
                            {"$set": {last_fetch_key: now_iso}},
                            upsert=True,
                        )
                        cat_status["last_fetch_at"] = now_iso
                    cat_status["next_fetch_at"] = (datetime.now(timezone.utc) + timedelta(hours=interval_hours)).isoformat()
                    # Cooldown between categories to avoid arXiv rate limiting (429)
                    await asyncio.sleep(5)
                    from core.memlog import force_gc
                    force_gc()
                    # Re-read settings in case pause was toggled during fetch
                    settings = await get_settings()

        except Exception as e:
            logger.error(f"Fetch loop error: {e}")

        # Sleep until next fetch is due (minimum 60s to avoid busy-loop on errors)
        sleep_time = max(60, min(next_due_seconds, interval_hours * 3600)) if next_due_seconds != float("inf") else interval_hours * 3600
        await asyncio.sleep(sleep_time)


async def _compare_loop():
    """Independent loop for running tournament comparisons. Never waits for fetches.
    Auto-restarts on crash with exponential backoff (max 5 min)."""
    global _wake_event
    from core.memlog import log_mem

    restart_count = 0
    while _scheduler_running:
        try:
            log_mem("Compare loop: starting (pre-sleep)")
            await asyncio.sleep(5)
            log_mem("Compare loop: task started")
            _compare_loop_diag["loop_alive"] = True
            await _compare_loop_inner()
            break  # Clean exit (scheduler stopped)
        except Exception as e:
            import traceback
            restart_count += 1
            _compare_loop_diag["loop_alive"] = False
            _compare_loop_diag["last_crash"] = {
                "error": str(e)[:200],
                "traceback": traceback.format_exc()[-500:],
                "at": datetime.now(timezone.utc).isoformat(),
                "restart_count": restart_count,
            }
            backoff = min(300, 10 * (2 ** min(restart_count - 1, 5)))
            log_mem(f"Compare loop CRASHED (restart #{restart_count} in {backoff}s): {traceback.format_exc()[-300:]}")
            logger.error(f"Compare loop CRASHED (restart #{restart_count}): {e}")
            await asyncio.sleep(backoff)



async def _run_startup_backfill(active_cats):
    """Run ai_rating backfill + gap recompute in background after startup.
    Non-blocking: the compare loop continues while this runs."""
    from core.memlog import log_mem, force_gc
    try:
        # Backfill ai_rating from papers → rankings where missing
        async for rank_doc in db.rankings.find(
            {"ai_rating": {"$in": [None, False, 0]}},
            {"_id": 0, "paper_id": 1}
        ):
            paper = await db.papers.find_one(
                {"id": rank_doc["paper_id"]},
                {"_id": 0, "ai_rating": 1}
            )
            if paper and paper.get("ai_rating"):
                r = paper["ai_rating"]
                rating = round(r["score"], 1) if isinstance(r, dict) and r.get("score") else round(r, 1) if isinstance(r, (int, float)) else None
                if rating:
                    await db.rankings.update_one(
                        {"paper_id": rank_doc["paper_id"]},
                        {"$set": {"ai_rating": rating}}
                    )
        # Also check where ai_rating field doesn't exist at all
        async for rank_doc in db.rankings.find(
            {"ai_rating": {"$exists": False}},
            {"_id": 0, "paper_id": 1}
        ):
            paper = await db.papers.find_one(
                {"id": rank_doc["paper_id"]},
                {"_id": 0, "ai_rating": 1}
            )
            if paper and paper.get("ai_rating"):
                r = paper["ai_rating"]
                rating = round(r["score"], 1) if isinstance(r, dict) and r.get("score") else round(r, 1) if isinstance(r, (int, float)) else None
                if rating:
                    await db.rankings.update_one(
                        {"paper_id": rank_doc["paper_id"]},
                        {"$set": {"ai_rating": rating}}
                    )
        # Recompute gap scores for all categories
        for cat in active_cats:
            try:
                await _recompute_gap_scores(cat)
            except Exception:
                pass
            force_gc()
        log_mem(f"Startup backfill complete for {len(active_cats)} categories")
    except Exception as e:
        logger.warning(f"Startup backfill failed: {e}")



async def _compare_loop_inner():
    global _wake_event
    from core.memlog import log_mem, force_gc
    await asyncio.sleep(0)
    _compare_loop_diag["loop_alive"] = True
    _gap_backfill_done = False

    while _scheduler_running:
        unmet_cats = []
        _compare_loop_diag["cycles_since_restart"] += 1
        _compare_loop_diag["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
        _cycle_results = {}  # Build locally, swap atomically at end
        try:
            settings = await get_settings()
            is_paused = settings.get("paused", False)
            min_papers = settings.get("min_papers_for_tournament", 8)

            # Use the same active_categories source as the fetch loop
            active_cats = [c for c in settings.get("active_categories", list(CATEGORIES.keys())) if c and c.strip()]

            # One-time gap backfill on first cycle after startup — runs in background
            # to avoid blocking the server from accepting connections during deploy
            if not _gap_backfill_done and active_cats:
                _gap_backfill_done = True
                asyncio.create_task(_run_startup_backfill(active_cats))

            log_mem(f"Compare loop cycle: paused={is_paused}, active_cats={len(active_cats)}")

            # Track ALL known categories for stats
            all_tournament_cats = set()
            all_tournaments_raw = await db.tournaments.find({}, {"_id": 0, "category": 1}).to_list(500)
            for t in all_tournaments_raw:
                all_tournament_cats.add(t["category"])
            if not all_tournament_cats:
                all_tournament_cats = set(settings.get("active_categories", list(CATEGORIES.keys())))

            if not is_paused and active_cats:
                log_mem(f"Compare loop: entering (paused={is_paused}, active={len(active_cats)} cats, tournaments={len(all_tournament_cats)})")
                # Update per-category paper/match counts and tournament stats
                # Match counts from incremental counters (no DB scan)
                from routers.leaderboard import get_match_counts_snapshot
                _match_snap, _ = get_match_counts_snapshot()
                for cat in all_tournament_cats:
                    try:
                        cat_status = _get_cat_status(cat)
                        cat_paper_count = await db.papers.count_documents({"categories.0": cat})
                        cat_status["papers_count"] = cat_paper_count
                        cat_status["matches_count"] = _match_snap.get(cat, cat_status.get("matches_count", 0))
                        await update_tournament_stats(cat)
                    except Exception:
                        pass  # Skip this category's stats update on timeout

                # Mark paused categories
                paused_cats = all_tournament_cats - set(active_cats)
                for cat in paused_cats:
                    _get_cat_status(cat)["current_activity"] = "Tournament paused"

                unmet_cats = []
                for cat in active_cats:
                    paper_count = _get_cat_status(cat).get("papers_count", 0)
                    if paper_count < min_papers:
                        total = _get_cat_status(cat).get("papers_total", 0)
                        if total > paper_count:
                            _get_cat_status(cat)["current_activity"] = f"Generating summaries ({paper_count}/{total} ready, need {min_papers})"
                        else:
                            _get_cat_status(cat)["current_activity"] = f"Insufficient papers ({paper_count}/{min_papers})"
                        continue
                    tid = f"cat={cat}|mode=standard"
                    t_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "compare_paused": 1})
                    if t_doc and t_doc.get("compare_paused"):
                        _get_cat_status(cat)["current_activity"] = "Comparisons paused"
                        continue
                    try:
                        if not await _check_goals_met(category=cat):
                            if _is_pair_exhausted(cat):
                                _get_cat_status(cat)["current_activity"] = "Pair-exhausted — waiting for new papers"
                            else:
                                unmet_cats.append(cat)
                    except Exception:
                        # If goals check fails (Atlas timeout), assume unmet → try to generate matches
                        unmet_cats.append(cat)

                if unmet_cats:
                    _compare_loop_diag["last_cycle_unmet"] = list(unmet_cats)
                    log_mem(f"Compare loop: {len(unmet_cats)} unmet categories: {unmet_cats}")
                    batch_size = min(max(settings.get("parallel_categories", 2), 1), 10)
                    all_failed = True  # Track if entire cycle produced 0 matches
                    # Memory ceiling: if RSS is high, force GC and reduce batch size
                    MEM_CEILING_MB = settings.get("mem_ceiling_mb", 3000)
                    for i in range(0, len(unmet_cats), batch_size):
                        # Check memory before starting a new batch
                        from core.memlog import get_mem_mb
                        current_mb = get_mem_mb()
                        if current_mb > MEM_CEILING_MB:
                            force_gc()
                            after_gc = get_mem_mb()
                            log_mem(f"Memory ceiling hit ({current_mb:.0f}MB > {MEM_CEILING_MB}MB), GC freed {current_mb - after_gc:.0f}MB")
                            if after_gc > MEM_CEILING_MB:
                                # Still too high — sleep to let OS reclaim, then continue with batch_size=1
                                log_mem(f"Still above ceiling ({after_gc:.0f}MB), backing off 30s")
                                await asyncio.sleep(30)
                                force_gc()
                                batch_size = 1  # Reduce to sequential for rest of cycle

                        batch = unmet_cats[i:i+batch_size]
                        tasks = [run_comparison_round(category=cat, skip_rerank=True) for cat in batch]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        # Record per-category results for diagnostics
                        for cat, res in zip(batch, results):
                            if isinstance(res, Exception):
                                _cycle_results[cat] = {"status": "error", "error": str(res)[:100]}
                            elif isinstance(res, dict):
                                _cycle_results[cat] = res
                                if res.get("completed", 0) > 0:
                                    all_failed = False
                            else:
                                _cycle_results[cat] = {"status": "unknown"}
                        # GC between batches to release match/paper data from completed rounds
                        from core.memlog import force_gc
                        force_gc()
                        # Sequential reranks — one at a time with GC between to prevent memory stacking
                        from services.ranking import rerank_category_light
                        for cat, res in zip(batch, results):
                            if isinstance(res, dict) and res.get("completed", 0) > 0:
                                try:
                                    await rerank_category_light(db, cat)
                                except Exception as e:
                                    logger.warning(f"[{cat}] Rankings rerank failed: {e}")
                                force_gc()
                        # Process any queued repairs from failed incremental updates
                        from services.ranking import process_repair_queue
                        repaired = await process_repair_queue(db)
                        if repaired:
                            logger.info(f"Repair queue: fixed {repaired} papers")
                        # Log queue size for monitoring
                        queue_size = await db.rankings_repair_queue.count_documents({})
                        from core.memlog import log_event
                        log_event("repair_queue", "repair_queue_size", {"size": queue_size, "repaired": repaired})
                        await asyncio.sleep(2)
                    _compare_loop_diag["last_cycle_results"] = _cycle_results
                    if all_failed:
                        # All categories produced 0 matches — likely budget/proxy outage.
                        # Back off to avoid spinning CPU on futile retries.
                        log_mem("Compare loop: all categories failed (0 matches). Backing off 120s.")
                        await asyncio.sleep(120)
                    # After a round completes, loop immediately to check if more work needed
                    continue
                else:
                    _compare_loop_diag["last_cycle_results"] = {"_all_goals_met": True}
                    log_mem(f"Compare loop: all goals met for {len(active_cats)} categories")
                    from core.memlog import log_event
                    await log_event("convergence", detail=f"All goals met for {len(active_cats)} categories", count=len(active_cats))
                    for cat in active_cats:
                        if _get_cat_status(cat).get("papers_count", 0) >= min_papers:
                            _get_cat_status(cat)["current_activity"] = "Goals met — idle"
            elif is_paused:
                _compare_loop_diag["last_cycle_results"] = {"_system_paused": True}
                for cat in all_tournament_cats:
                    _get_cat_status(cat)["current_activity"] = "System paused"

        except Exception as e:
            logger.error(f"Compare loop error: {e}")
            import traceback
            log_mem(f"Compare loop error: {traceback.format_exc()[-200:]}")

        # If there were unmet goals, loop immediately (don't sleep)
        if unmet_cats:
            await asyncio.sleep(2)
            continue

        # Goals met or paused — wait for wake event OR periodic re-check (60s)
        _wake_event.clear()
        try:
            loop_interval = settings.get("compare_loop_interval", 60)
            await asyncio.wait_for(_wake_event.wait(), timeout=loop_interval)
        except asyncio.TimeoutError:
            pass  # Periodic re-check: goals might have changed (new papers, pruning, etc.)



async def _check_goals_met(category: str = "cs.RO") -> bool:
    """Check if ranking has converged for a category.
    
    Two-tier Wilson CI convergence:
    1. General papers: CI margin ≤ ci_target_general (default 15%)
    2. Top-K papers: CI margin ≤ ci_target (default 10%)
    3. Top-K cross-matching: all top-K pairs compared
    
    Returns True when all goals met. Only considers matchable papers
    (those with summaries that can be compared by LLMs).
    
    No caching — goal3 uses 2 batch $in queries (not 45 individual ones),
    making the full check fast enough (~50ms) to run on every scheduler cycle.
    """
    return await _check_goals_met_impl(category)


async def _check_goals_met_impl(category: str = "cs.RO") -> bool:
    """Actual goals check — loads rankings from DB."""
    from core.memlog import log_mem
    from services.ranking import wilson_margin_pct

    settings = await get_settings()
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 10)
    ci_target_general = settings.get("ci_target_general", 15)

    # Read wins/comparisons directly from rankings (no match loading)
    entries = []
    async for doc in db.rankings.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "wins": 1, "comparisons": 1, "score": 1},
    ):
        entries.append(doc)

    if len(entries) < 2:
        # Check if papers exist but haven't been ranked yet (summary phase)
        actual_papers = await db.papers.count_documents({"categories.0": category})
        if actual_papers >= 2:
            return False  # Papers exist but not yet ranked — goals NOT met
        return True

    total_rankings = len(entries)
    # Exclude unmatchable papers (no summary → can never get matches).
    try:
        matchable_ids = await get_matchable_paper_ids(category, settings.get("summary_source", "thinking"))
        if matchable_ids:
            entries = [e for e in entries if e["paper_id"] in matchable_ids]
        log_mem(f"_check_goals({category}): {total_rankings} ranked, {len(matchable_ids)} matchable, {len(entries)} filtered")
    except Exception as e:
        log_mem(f"_check_goals({category}): filter FAILED: {e}")

    if len(entries) < 2:
        # Not enough matchable papers to compare — but don't claim goals met
        # if papers exist that need summaries
        actual_papers = await db.papers.count_documents({"categories.0": category})
        if actual_papers >= 2:
            return False  # Papers exist, waiting for summaries
        return True

    # Sort by score descending to identify top-K
    entries.sort(key=lambda e: e.get("score", 0), reverse=True)
    top_k_list = [e["paper_id"] for e in entries[:min(top_k, len(entries))]]
    top_k_ids = set(top_k_list)

    # Goal 1: General papers CI ≤ ci_target_general
    for e in entries:
        if e["paper_id"] in top_k_ids:
            continue
        margin = wilson_margin_pct(e.get("wins", 0), e.get("comparisons", 0))
        if margin > ci_target_general:
            return False

    # Goal 2: Top-K papers CI ≤ ci_target
    for e in entries[:min(top_k, len(entries))]:
        margin = wilson_margin_pct(e.get("wins", 0), e.get("comparisons", 0))
        if margin > ci_target:
            return False

    # Goal 3: Top-K cross-matching — 2 batch queries instead of 45 individual ones
    if top_k_list:
        top_k_set = set(top_k_list)
        matched_pairs = set()
        async for m in db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category,
             "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
             "paper1_id": {"$in": top_k_list}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ):
            if m["paper2_id"] in top_k_set:
                matched_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
        async for m in db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category,
             "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
             "paper2_id": {"$in": top_k_list}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ):
            if m["paper1_id"] in top_k_set:
                matched_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
        total_pairs = len(top_k_list) * (len(top_k_list) - 1) // 2
        if len(matched_pairs) < total_pairs:
            return False

    return True



async def _handle_revision(paper_id: str, new_arxiv_data: dict, new_version: int, settings: dict) -> str:
    """Handle an arXiv revision under the *standalone-paper-per-version* model.

    Semantics:
      * The existing paper (the previous "latest") is FROZEN: its summaries,
        ranking, and matches are left exactly as they are, and it is flagged
        `is_latest_version=False` so pair-selection and the leaderboard skip it.
      * A fresh paper document is INSERTED for the new version (new UUID, new
        arxiv_id like `2602.12345v2`, shared `arxiv_id_base`, a link back to
        the previous version via `previous_version_paper_id`).
      * A new ranking row is seeded for the new paper (baseline TrueSkill).
      * No matches are deleted, superseded, or moved. The old paper's page
        continues to show its frozen match history; the new paper's tournament
        starts from scratch.
      * `version_history` arrays are NOT written — the standalone-paper model
        makes them redundant. Navigation between versions is via the new
        `sibling_versions` API (see get_sibling_versions).

    Returns:
      "revised" if a new paper was successfully created; "updated" otherwise
      (e.g., PDF download failed — in which case the old paper stays latest).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = await db.papers.find_one({"id": paper_id})
    if not existing:
        return "updated"
    existing.pop("_id", None)

    # Download new PDF (required — we want full content for the new version).
    new_pdf_link = new_arxiv_data.get("pdf_link") or f"https://arxiv.org/pdf/{new_arxiv_data['arxiv_id']}"
    try:
        new_full_text = await download_and_extract_pdf(new_pdf_link)
    except Exception as e:
        logger.warning(f"Revision PDF download failed for {paper_id}: {e}")
        return "updated"
    if not new_full_text:
        logger.warning(f"Revision PDF extraction empty for {paper_id}")
        return "updated"

    base, _ = strip_arxiv_version(new_arxiv_data["arxiv_id"])

    # --- 1. Create the new paper document ---
    new_paper_id = str(uuid.uuid4())
    new_paper = {
        "id": new_paper_id,
        "title": new_arxiv_data.get("title", existing.get("title", "")),
        "authors": new_arxiv_data.get("authors", existing.get("authors", [])),
        "abstract": new_arxiv_data.get("abstract", existing.get("abstract", "")),
        "full_text": new_full_text,
        "categories": new_arxiv_data.get("categories", existing.get("categories", [])),
        "published": new_arxiv_data.get("published", existing.get("published")),
        "link": new_arxiv_data.get("link", f"https://arxiv.org/abs/{new_arxiv_data['arxiv_id']}"),
        "pdf_link": new_pdf_link,
        "arxiv_id": new_arxiv_data["arxiv_id"],
        "arxiv_id_base": base,
        "current_version": new_version,
        "is_latest_version": True,
        "previous_version_paper_id": paper_id,
        "added_at": now_iso,
        "needs_pdf": False,
    }
    try:
        await db.papers.insert_one(new_paper)
    except Exception as e:
        # Duplicate arxiv_id (someone else already ingested this version).
        logger.warning(f"Revision insert skipped for {new_arxiv_data['arxiv_id']}: {e}")
        return "updated"

    # --- 2. Freeze the previous version (paper doc + its ranking row) ---
    await db.papers.update_one(
        {"id": paper_id},
        {"$set": {
            "is_latest_version": False,
            "frozen_at": now_iso,
            "superseded_by_paper_id": new_paper_id,
        }}
    )
    # Denormalize the flag onto the ranking row so leaderboard queries can
    # filter efficiently without a $lookup (critical-path performance).
    await db.rankings.update_one(
        {"paper_id": paper_id},
        {"$set": {"is_latest_version": False, "frozen_at": now_iso}}
    )

    # --- 3. Seed a fresh ranking row for the new paper ---
    # Denormalize paper fields into the ranking row so leaderboard queries
    # (which project from rankings only) can display title/authors/arxiv link
    # without a papers lookup.
    from services.ranking import SCORE_BASE_CONST
    category = (new_paper["categories"] or ["unknown"])[0]
    await db.rankings.insert_one({
        "paper_id": new_paper_id,
        "category": category,
        "wins": 0, "losses": 0, "comparisons": 0, "unique_opponents": 0,
        "score": SCORE_BASE_CONST, "ci": 0, "wilson_margin": 100.0, "win_rate": 0.0,
        "ts_mu": 25.0, "ts_sigma": 25.0 / 3,
        "ts_score": SCORE_BASE_CONST,
        "is_latest_version": True,
        "model_stats": {},
        "model_ts": {},
        # Denormalized paper fields for leaderboard display
        "title": new_paper["title"],
        "authors": new_paper["authors"],
        "arxiv_id": new_paper["arxiv_id"],
        "link": new_paper["link"],
        "published": new_paper["published"],
        "added_at": now_iso,
        "categories": new_paper["categories"],
        "current_version": new_version,
        "updated_at": now_iso,
    })

    # --- 4. Invalidate caches ---
    from routers.leaderboard import notify_data_changed
    notify_data_changed()

    logger.info(f"Revision v{new_version} for base {base}: created new paper {new_paper_id} "
                f"(previous v{existing.get('current_version', 1)} paper {paper_id} frozen)")
    return "revised"



async def run_fetch_cycle(category: str = "cs.RO", force: bool = False):
    from core.memlog import log_mem
    if not category or not category.strip():
        logger.warning("run_fetch_cycle called with empty category, skipping")
        return {"status": "error", "error": "empty category"}
    if category in _fetching_cats:
        return {"status": "already_fetching"}

    log_mem(f"fetch_cycle({category}) start")

    _fetching_cats.add(category)
    cat_status = _get_cat_status(category)
    cat_status["is_fetching"] = True
    result = {"new_papers": 0, "pdfs_downloaded": 0, "summaries_generated": 0, "rankings_inserted": 0, "errors": []}

    try:
        settings = await get_settings()
        max_papers = settings.get("max_papers_per_fetch", 50)

        # Determine date_from: use the publication date of our NEWEST paper in this category.
        # This is robust regardless of arXiv delays, our downtime, or rate limiting —
        # we always fetch everything published after what we already have.
        from datetime import datetime, timedelta, timezone
        newest_paper = await db.papers.find_one(
            {"categories.0": category, "published": {"$exists": True, "$ne": None}},
            {"_id": 0, "published": 1},
            sort=[("published", -1)],
        )
        if newest_paper and newest_paper.get("published"):
            pub = newest_paper["published"][:10]  # "2026-05-04"
            date_from = pub  # Fetch everything from that day onwards (dedup handles overlap)
        else:
            # No papers in this category yet — use 30-day lookback
            date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

        # --- STEP 1: Fetch new papers from source ---
        cat_status["current_activity"] = "Fetching new papers from source..."
        try:
            if category.startswith("chemrxiv."):
                from services.chemrxiv import fetch_chemrxiv_papers
                raw_papers = await fetch_chemrxiv_papers(category=category, max_results=max_papers)
                logger.info(f"[{category}] Step 1: Fetched {len(raw_papers)} papers from ChemRxiv")
                id_field = "chemrxiv_id"
            elif category.startswith("iacr."):
                from services.iacr import fetch_iacr_papers_oai
                # OAI-PMH returns all IACR categories mixed.
                # The date_from constraint limits volume (~15 papers/day total).
                # Fetch the full date range, then filter to target category.
                raw_all = await fetch_iacr_papers_oai(date_from=date_from, max_papers=5000)
                raw_papers = [p for p in raw_all if category in p.get("categories", [])]
                logger.info(f"[{category}] Step 1: Fetched {len(raw_papers)} papers from IACR ePrint (date_from={date_from}, scanned {len(raw_all)} total)")
                id_field = "iacr_id"
            else:
                raw_papers = await fetch_arxiv_papers(
                    category=category, max_results=max_papers, date_from=date_from,
                )
                logger.info(f"[{category}] Step 1: Fetched {len(raw_papers)} papers from arXiv (date_from={date_from})")
                id_field = "arxiv_id"

            new_count = 0
            revisions_detected = 0
            existing_ids = set()
            existing_hashes = set()
            # Version-aware lookup: for each arxiv_id_base, find the paper marked
            # as latest. Multiple papers may share the same base (one per version
            # in the new standalone-paper-per-version model) — we only want the
            # LATEST one, since that's the one we compare against.
            existing_bases = {}  # base → {arxiv_id, current_version, id}
            if id_field == "arxiv_id":
                async for doc in db.papers.find(
                    {
                        "arxiv_id_base": {"$exists": True},
                        # Legacy papers (pre-revision-system) don't have this
                        # field — treat them as latest. Post-refactor papers
                        # will have it explicitly set.
                        "is_latest_version": {"$ne": False},
                    },
                    {"_id": 0, id_field: 1, "arxiv_id_base": 1, "current_version": 1, "id": 1}
                ):
                    if doc.get("arxiv_id_base"):
                        existing_bases[doc["arxiv_id_base"]] = {
                            "arxiv_id": doc.get(id_field),
                            "current_version": doc.get("current_version", 1),
                            "id": doc["id"],
                        }
            # Per-category dedup hashes + id set (faster for normal dedup path)
            async for doc in db.papers.find(
                {"categories.0": category} if not category.startswith("chemrxiv.") else {},
                {"_id": 0, id_field: 1, "dedup_hash": 1}
            ):
                if doc.get(id_field):
                    existing_ids.add(doc[id_field])
                if doc.get("dedup_hash"):
                    existing_hashes.add(doc["dedup_hash"])

            for rp in raw_papers:
                dedup_value = rp.get(id_field) or rp.get("doi") or rp.get("arxiv_id")
                if not dedup_value:
                    continue

                # --- Version-aware dedup for arXiv papers ---
                if id_field == "arxiv_id" and rp.get("arxiv_id"):
                    base, version = strip_arxiv_version(rp["arxiv_id"])
                    existing = existing_bases.get(base)
                    if existing:
                        if version > existing["current_version"]:
                            # New version detected — queue revision
                            try:
                                rev_result = await _handle_revision(
                                    existing["id"], rp, version, settings
                                )
                                if rev_result == "revised":
                                    revisions_detected += 1
                                    logger.info(f"[{category}] Revision v{version} for {base}: tournament reset")
                                elif rev_result == "updated":
                                    revisions_detected += 1
                                    logger.info(f"[{category}] Revision v{version} for {base}: content updated, tournament kept")
                            except Exception as e:
                                logger.warning(f"[{category}] Revision handling failed for {base}: {e}")
                        # Either way, skip normal insertion (paper already exists)
                        continue

                if dedup_value in existing_ids:
                    continue
                title_norm = rp["title"].strip().lower()
                first_author = (rp.get("authors") or [""])[0].strip().lower() if rp.get("authors") else ""
                content_hash = hashlib.sha256(f"{title_norm}|{first_author}".encode()).hexdigest()[:16]
                if content_hash in existing_hashes:
                    continue
                paper_doc = {
                    "id": str(uuid.uuid4()),
                    "title": rp["title"],
                    "authors": rp["authors"],
                    "abstract": rp["abstract"],
                    "categories": rp["categories"],
                    "published": rp["published"],
                    "link": rp["link"],
                    "pdf_link": rp.get("pdf_link"),
                    "full_text": None,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "needs_pdf": True,
                    "dedup_hash": content_hash,
                }
                if rp.get("arxiv_id"):
                    paper_doc["arxiv_id"] = rp["arxiv_id"]
                    base, version = strip_arxiv_version(rp["arxiv_id"])
                    paper_doc["arxiv_id_base"] = base
                    paper_doc["current_version"] = version
                    paper_doc["is_latest_version"] = True
                if rp.get("chemrxiv_id"):
                    paper_doc["chemrxiv_id"] = rp["chemrxiv_id"]
                if rp.get("iacr_id"):
                    paper_doc["iacr_id"] = rp["iacr_id"]
                if rp.get("doi"):
                    paper_doc["doi"] = rp["doi"]
                try:
                    await db.papers.insert_one(paper_doc)
                    existing_hashes.add(content_hash)
                    new_count += 1
                except Exception as ins_err:
                    # Most likely DuplicateKeyError on arxiv_id or arxiv_id_base
                    # (e.g., paper just inserted by a parallel fetcher, or
                    # category-switched version we missed in the base lookup).
                    # Skip this one but don't abort the rest of the batch.
                    err_name = type(ins_err).__name__
                    logger.warning(f"[{category}] Insert skipped for "
                                   f"{paper_doc.get('arxiv_id') or paper_doc.get('chemrxiv_id')}: "
                                   f"{err_name}: {str(ins_err)[:120]}")
                    continue

            result["new_papers"] = new_count
            result["revisions"] = revisions_detected
            logger.info(f"[{category}] Step 1 done: {new_count} new papers, {revisions_detected} revisions")
        except Exception as e:
            err_msg = f"ArXiv/source fetch failed: {str(e)[:200]}"
            logger.warning(f"[{category}] Step 1 FAILED: {err_msg}")
            result["errors"].append(err_msg)
            # Continue to steps 2-4 even if fetch fails

        cat_status["papers_count"] = await db.papers.count_documents({"categories.0": category})

        # --- STEP 2: Download PDFs for papers missing full_text ---
        cat_status["current_activity"] = "Downloading PDFs..."
        try:
            pdfs = await _download_pending_pdfs(category=category, force=force)
            result["pdfs_downloaded"] = pdfs or 0
            logger.info(f"[{category}] Step 2 done: {pdfs or 0} PDFs downloaded")
        except Exception as e:
            err_msg = f"PDF download failed: {str(e)[:200]}"
            logger.warning(f"[{category}] Step 2 FAILED: {err_msg}")
            result["errors"].append(err_msg)

        # --- STEP 3: Generate AI summaries ---
        cat_status["current_activity"] = "Generating summaries..."
        try:
            gen_count = await _generate_paper_summaries(category=category, force=force)
            result["summaries_generated"] = gen_count or 0
            logger.info(f"[{category}] Step 3 done: {gen_count or 0} summaries generated")
        except Exception as e:
            err_msg = f"Summary generation failed: {str(e)[:200]}"
            logger.warning(f"[{category}] Step 3 FAILED: {err_msg}")
            result["errors"].append(err_msg)

        # Explicit GC after heavy operations
        from core.memlog import force_gc
        force_gc()

        cat_status["papers_count"] = await db.papers.count_documents({"categories.0": category})

        # --- STEP 4: Insert rankings for new papers with summaries ---
        cat_status["current_activity"] = "Updating rankings..."
        try:
            from services.ranking import insert_ranking_for_paper
            inserted = 0
            async for p in db.papers.find(
                {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}, "is_latest_version": {"$ne": False}},
                {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                 "link": 1, "published": 1, "added_at": 1, "categories": 1, "ai_rating": 1, "summaries": 1, "is_latest_version": 1}
            ):
                existing = await db.rankings.find_one({"paper_id": p["id"]}, {"_id": 0, "paper_id": 1})
                if not existing:
                    await insert_ranking_for_paper(db, p)
                    inserted += 1
            result["rankings_inserted"] = inserted
            if inserted > 0:
                logger.info(f"[{category}] Step 4 done: {inserted} new rankings inserted")
        except Exception as e:
            err_msg = f"Rankings insert failed: {str(e)[:200]}"
            logger.warning(f"[{category}] Step 4 FAILED: {err_msg}")
            result["errors"].append(err_msg)

        cat_status["current_activity"] = "Idle"

        # Log pipeline event for admin Logs tab
        from core.memlog import log_event
        await log_event("fetch_cycle", category=category,
            detail=f"{category}: new={result['new_papers']}, pdfs={result['pdfs_downloaded']}, summaries={result['summaries_generated']}, rankings={result['rankings_inserted']}",
            count=result['new_papers'],
            pdfs=result['pdfs_downloaded'],
            summaries=result['summaries_generated'],
            rankings=result['rankings_inserted'])

        if result["new_papers"] > 0 or result["summaries_generated"] > 0 or result["rankings_inserted"] > 0:
            from routers.leaderboard import notify_data_changed
            notify_data_changed()
            wake_scheduler()
            # Invalidate admin stats cache (token usage, model breakdown changes with new data)
            from routers.admin import _invalidate_admin_cache
            _invalidate_admin_cache(category)

        # Determine overall status
        if result["errors"]:
            result["status"] = "partial" if (result["new_papers"] > 0 or result["pdfs_downloaded"] > 0 or result["summaries_generated"] > 0) else "error"
            result["error"] = "; ".join(result["errors"])
        else:
            result["status"] = "ok"
        return result

    except Exception as e:
        err_msg = str(e) or f"{type(e).__name__} (no message)"
        logger.error(f"[{category}] Fetch cycle critical failure: {err_msg}")
        cat_status["current_activity"] = f"Fetch failed: {err_msg[:100]}"
        log_mem(f"fetch_cycle({category}) FAILED: {err_msg[:80]}")
        return {"status": "error", "error": str(e)}
    finally:
        _fetching_cats.discard(category)
        cat_status["is_fetching"] = False


async def _download_pending_pdfs(category: str = None, force: bool = False):
    """Download PDFs for papers missing full_text, scoped to a category.
    
    Papers that fail extraction are marked with needs_pdf=False and pdf_failed=True
    so they can be retried later without blocking every cycle.
    When force=True (admin button), retries previously failed papers too.
    """
    if force:
        # Admin manually clicked — retry ALL papers missing full_text (including previously failed and empty extractions)
        # Include papers without pdf_link — we can construct it from arxiv_id
        query = {"$or": [{"full_text": None}, {"full_text": ""}, {"full_text": {"$exists": False}}]}
    else:
        # Automatic cycle — skip previously failed papers
        _no_text = {"$or": [{"full_text": None}, {"full_text": ""}, {"full_text": {"$exists": False}}]}
        query = {"$or": [{"needs_pdf": True}, {**_no_text, "pdf_failed": {"$ne": True}}], "pdf_link": {"$ne": None}}
    if category:
        query["categories.0"] = category

    papers_needing_pdf = await collect_all(db.papers.find(
        query, {"_id": 0, "id": 1, "pdf_link": 1, "title": 1, "doi": 1, "arxiv_id": 1},
    ))

    if not papers_needing_pdf:
        return 0

    if force:
        previously_failed = sum(1 for _ in await collect_all(db.papers.find(
            {"categories.0": category, "pdf_failed": True, "full_text": None} if category else {"pdf_failed": True, "full_text": None},
            {"_id": 0, "id": 1}
        )))
        logger.info(f"[{category}] Step 2: {len(papers_needing_pdf)} papers need PDFs ({previously_failed} retries from previous failures)")
    else:
        logger.info(f"[{category}] Downloading PDFs for {len(papers_needing_pdf)} papers")

    cat_status = _get_cat_status(category) if category else None

    downloaded = 0
    for i, paper in enumerate(papers_needing_pdf):
        if cat_status:
            cat_status["current_activity"] = f"Downloading PDF {i+1}/{len(papers_needing_pdf)}: {paper['title'][:40]}..."
        # Construct pdf_link from arxiv_id if missing
        pdf_link = paper.get("pdf_link")
        if not pdf_link and paper.get("arxiv_id"):
            pdf_link = f"https://arxiv.org/pdf/{paper['arxiv_id']}"
            await db.papers.update_one({"id": paper["id"]}, {"$set": {"pdf_link": pdf_link}})
        if not pdf_link:
            logger.warning(f"[{category}] No pdf_link and no arxiv_id for {paper['id'][:8]} — skipping")
            continue
        try:
            full_text = await download_and_extract_pdf(pdf_link, doi=paper.get("doi"))
            if full_text:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"full_text": full_text, "needs_pdf": False},
                     "$unset": {"pdf_failed": "", "pdf_fail_reason": ""}},
                )
                downloaded += 1
            else:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"needs_pdf": False, "pdf_failed": True,
                              "pdf_fail_reason": "extraction_empty",
                              "pdf_failed_at": datetime.now(timezone.utc).isoformat()}},
                )
        except Exception as e:
            err_str = str(e)[:200]
            reason = "timeout" if "timeout" in err_str.lower() else \
                     "rate_limit" if "429" in err_str else \
                     "not_found" if "404" in err_str else \
                     "connection" if "connect" in err_str.lower() else \
                     "extraction_error"
            logger.warning(f"PDF download failed for {paper['id']} ({reason}): {err_str[:80]}")
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"needs_pdf": False, "pdf_failed": True,
                          "pdf_fail_reason": reason,
                          "pdf_failed_at": datetime.now(timezone.utc).isoformat()}},
            )
        await asyncio.sleep(1)
    return downloaded



# --- Summary model configuration ---
# Only Claude Opus 4.6 Thinking is used for new summaries.
# GPT/Gemini summaries were disabled to reduce costs (~$30-60/day savings).
# Old GPT/Gemini summaries are preserved in the DB for validation experiments.
_SUMMARY_GENERATION_MODELS = [
    {"provider": "anthropic", "model": "claude-opus-4-6",
     "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}},
     "key_suffix": "thinking"},
]

# Models whose summaries can be selected for live tournament comparisons.
_SUMMARY_MODELS = {
    "claude": {"provider": "anthropic", "model": "claude-opus-4-6", "key_suffix": "thinking"},
}
_summary_rr_counter = 0


def _pick_summary_source(setting: str) -> dict:
    """Pick summary model based on admin setting.
    
    Default 'claude' always uses the Claude thinking summary in live tournaments.
    Other settings ('round_robin', 'gpt', 'gemini') are available for experiments.
    """
    global _summary_rr_counter
    if setting in _SUMMARY_MODELS:
        return _SUMMARY_MODELS[setting]
    # round_robin cycles through all models (for experiments only)
    models = list(_SUMMARY_MODELS.values())
    model = models[_summary_rr_counter % len(models)]
    _summary_rr_counter += 1
    return model


def _summary_model_key(model_info: dict) -> str:
    """Build the MongoDB storage key for a summary model.
    
    Includes key_suffix when present (e.g., 'thinking') to distinguish
    summaries generated with different configurations of the same base model.
    """
    base = f"{model_info['provider']}:{model_info['model']}".replace(".", "_")
    suffix = model_info.get("key_suffix")
    if suffix:
        base += f":{suffix}"
    return base


# Legacy key fallbacks — when looking up a summary, try these keys if the primary is missing.
# This lets old papers (generated before the thinking upgrade) still participate in tournaments.
_SUMMARY_KEY_FALLBACKS = {
    "anthropic:claude-opus-4-6:thinking": [
        # No fallbacks — all papers must have Claude Opus 4.6 thinking summary.
    ],
    "anthropic:claude-opus-4-6": [
        "anthropic:claude-opus-4-5-20251101",
        "openai:gpt-5_2",
        "gemini:gemini-3.1-pro-preview",
        "gemini:gemini-3-pro-preview",
        "gemini:gemini-3_1-pro-preview",
    ],
}


async def get_matchable_paper_ids(category: str, summary_source: str = "claude") -> set:
    """Single source of truth: which papers have the required summary key for matching.
    
    Used by: _check_goals_met, progress endpoint, run_comparison_round.
    """
    summary_model = _pick_summary_source(summary_source)
    required_key = _summary_model_key(summary_model)
    fallback_keys = _SUMMARY_KEY_FALLBACKS.get(required_key, [])
    all_keys = [required_key] + fallback_keys
    summary_filter = {"$or": [{f"summaries.{k}": {"$exists": True}} for k in all_keys]}
    summary_filter["categories.0"] = category
    # Exclude frozen older versions (is_latest_version=False). Treat missing
    # field as latest (legacy pre-refactor papers).
    summary_filter["is_latest_version"] = {"$ne": False}
    matchable_ids = set()
    async for doc in db.papers.find(summary_filter, {"_id": 0, "id": 1}):
        matchable_ids.add(doc["id"])
    return matchable_ids


def _get_paper_summary(paper: dict, model_key: str) -> str:
    """Get a paper's summary for the given model key, with fallback to legacy keys."""
    summaries = paper.get("summaries") or {}
    text = summaries.get(model_key, "")
    if isinstance(text, str) and len(text) > 50:
        return text
    for fallback_key in _SUMMARY_KEY_FALLBACKS.get(model_key, []):
        text = summaries.get(fallback_key, "")
        if isinstance(text, str) and len(text) > 50:
            return text
    return ""


async def _generate_paper_summaries(category: str = None, force: bool = False):
    """Generate AI impact summaries for papers missing them.
    
    Uses _SUMMARY_GENERATION_MODELS (Claude Thinking, GPT, Gemini).
    Claude uses extended thinking for higher-quality summaries.
    All three models generate summaries, but only Claude Thinking is
    used in live tournament comparisons.
    
    Memory-optimized: scans with a lightweight projection (no full_text/summaries),
    then loads full paper data only for the few that actually need generation.
    """
    global _summary_gen_stop
    _summary_gen_stop = False  # Clear stop flag on new run
    settings = await get_settings()
    parallel = settings.get("summary_parallel", 10)

    query = {}
    if category:
        query["categories.0"] = category
    # Only papers with full_text (no abstract-only summaries)
    query["full_text"] = {"$ne": None}

    total_papers = await db.papers.count_documents(query)

    cat_status = _get_cat_status(category) if category else None
    sem = asyncio.Semaphore(parallel)
    generated = 0
    failed = 0
    skipped = 0
    scanned = 0

    # Track progress for external visibility
    prog_key = category or "__all__"
    _summary_gen_progress[prog_key] = {
        "running": True, "generated": 0, "failed": 0, "skipped": 0,
        "scanned": 0, "total": total_papers, "started_at": datetime.now(timezone.utc).isoformat(),
        "started_at_ts": __import__('time').time(),
    }

    def _sync_progress():
        """Push current counters to progress tracker for real-time UI updates."""
        prog = _summary_gen_progress.get(prog_key)
        if prog:
            prog.update({"generated": generated, "failed": failed, "skipped": skipped, "scanned": scanned})

    # All model keys we need to check
    [_summary_model_key(m) for m in _SUMMARY_GENERATION_MODELS]

    # Phase 1: Lightweight scan — only load IDs and summary keys (NOT full_text)
    # This avoids loading ~100MB of full_text for papers that already have summaries.
    _light_proj = {"_id": 0, "id": 1, "summaries": 1}
    papers_needing_gen = []  # list of (paper_id, [model_infos_needed])

    paper_cursor = db.papers.find(query, _light_proj)
    async for paper in paper_cursor:
        scanned += 1
        needed_models = []
        for model_info in _SUMMARY_GENERATION_MODELS:
            mk = _summary_model_key(model_info)
            if not _get_paper_summary(paper, mk):
                needed_models.append(model_info)
            else:
                skipped += 1
        if needed_models:
            papers_needing_gen.append((paper["id"], needed_models))
        if scanned % 100 == 0:
            _sync_progress()
            if cat_status:
                cat_status["current_activity"] = f"Scanning for missing summaries... ({scanned}/{total_papers})"

    _sync_progress()
    if cat_status:
        if len(papers_needing_gen) > 0:
            cat_status["current_activity"] = f"Generating summaries for {len(papers_needing_gen)} papers..."
        else:
            cat_status["current_activity"] = "Idle"

    # Phase 2: Load full paper data ONLY for papers that need generation
    async def gen_one(paper_id, model_info):
        nonlocal generated, failed
        if _summary_gen_stop:
            return
        if not force:
            s = await get_settings()
            if s.get("paused", False):
                return

        mk = _summary_model_key(model_info)

        # Skip refused papers permanently (content policy — will never succeed, even with force)
        refused_doc = await db.papers.find_one(
            {"id": paper_id}, {"_id": 0, f"summary_refused.{mk}": 1}
        )
        if (refused_doc or {}).get("summary_refused", {}).get(mk):
            return  # Permanently refused — never retry

        # Skip papers that have failed 3+ times (budget/other — saves credits)
        if not force:
            fail_doc = await db.papers.find_one(
                {"id": paper_id}, {"_id": 0, f"summary_failures.{mk}": 1}
            )
            fail_count = (fail_doc or {}).get("summary_failures", {}).get(mk, 0)
            if fail_count >= 3:
                return  # Failed 3+ times — don't waste credits

        async with sem:
            if _summary_gen_stop:
                return
            if not force:
                s2 = await get_settings()
                if s2.get("paused", False):
                    return
            # Load full paper data on-demand (only when actually generating)
            paper = await db.papers.find_one(
                {"id": paper_id},
                {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "categories": 1, "summaries": 1, "_pipeline_active": 1}
            )
            if not paper:
                return
            # Skip if single-paper pipeline is already processing this paper
            if paper.get("_pipeline_active"):
                return
            # Re-check in case another worker already generated it
            if _get_paper_summary(paper, mk):
                return
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=model_info)
            except Exception as e:
                failed += 1
                _sync_progress()
                err_msg = str(e)
                is_refusal = err_msg.startswith("REFUSED:")

                # For refusals: mark permanently so we never retry this paper+model
                if is_refusal:
                    await db.papers.update_one(
                        {"id": paper_id},
                        {"$set": {f"summary_refused.{mk}": True, f"summary_failures.{mk}": 999}},
                    )
                    logger.warning(f"[{category}] REFUSED: '{paper.get('title', '')[:40]}' ({mk})")
                else:
                    # Increment failure counter for this paper+model
                    await db.papers.update_one(
                        {"id": paper_id},
                        {"$inc": {f"summary_failures.{mk}": 1}},
                    )
                    logger.warning(f"[{category}] Summary gen error for '{paper.get('title', '')[:40]}' ({mk}): {e}")
                return
            if result and result.get("summary"):
                summary_val = result["summary"]
                # Ensure we always store a string
                if not isinstance(summary_val, str):
                    summary_val = str(summary_val)
                if len(summary_val) > 50:
                    update_fields = {
                        f"summaries.{mk}": summary_val,
                        f"summary_dates.{mk}": datetime.now(timezone.utc).isoformat(),
                    }
                    # Store actual token usage if available
                    if result.get("tokens"):
                        update_fields[f"summary_tokens.{mk}"] = result["tokens"]
                    # Parse ratings from Claude Thinking summaries
                    if "thinking" in mk:
                        from services.llm import parse_ratings_from_summary
                        ratings = parse_ratings_from_summary(summary_val)
                        if ratings:
                            update_fields["ai_rating"] = ratings["score"]
                            # Propagate to rankings immediately (keeps leaderboard in sync)
                            await db.rankings.update_one(
                                {"paper_id": paper["id"]},
                                {"$set": {"ai_rating": ratings["score"]}},
                            )
                    # Store per-model ratings for SI inter-model correlation
                    from services.llm import parse_ratings_from_summary as _parse_ratings
                    _model_ratings = _parse_ratings(summary_val)
                    if _model_ratings:
                        _model_short = "claude" if "anthropic" in mk else "gpt" if "openai" in mk else "gemini" if "gemini" in mk else None
                        if _model_short:
                            update_fields[f"ai_ratings_by_model.{_model_short}"] = _model_ratings
                    await db.papers.update_one(
                        {"id": paper["id"]},
                        {"$set": update_fields, "$unset": {f"summary_failures.{mk}": ""}},
                    )
                    # Track successful summary generation
                    from services.llm import track_llm_usage
                    tokens = result.get("tokens", {})
                    await track_llm_usage(
                        model_info.get("provider", ""), model_info.get("model", ""),
                        context="summary", success=True,
                        input_tokens=tokens.get("input", 0),
                        output_tokens=tokens.get("output", 0),
                        thinking_tokens=tokens.get("thinking", 0),
                    )
                    generated += 1
                    _sync_progress()
                    if cat_status and generated % 5 == 0:
                        cat_status["current_activity"] = f"Generating summaries... ({generated} new, {failed} failed)"
                else:
                    failed += 1
                    _sync_progress()
                    logger.warning(f"[{category}] Summary too short (<50 chars) for '{paper.get('title', '')[:40]}' ({mk})")
            else:
                failed += 1
                _sync_progress()
                logger.warning(f"[{category}] Summary gen returned None for '{paper.get('title', '')[:60]}' ({mk}) — full_text len={len(paper.get('full_text','') or '')}")

    # Process papers needing generation in small batches
    batch_size = settings.get("summary_batch_size", 50)
    batch_size = max(10, min(batch_size, parallel * 5))
    for i in range(0, len(papers_needing_gen), batch_size):
        batch = papers_needing_gen[i:i+batch_size]
        tasks = []
        for paper_id, needed_models in batch:
            for model_info in needed_models:
                tasks.append(gen_one(paper_id, model_info))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if total_papers:
        parts = [f"{generated} new", f"{skipped} skipped", f"{scanned} papers scanned"]
        if failed > 0:
            parts.insert(1, f"{failed} errors")
        logger.info(f"[{category}] Summary generation done: {', '.join(parts)}")
        if generated > 0:
            from routers.leaderboard import notify_data_changed
            notify_data_changed()
            wake_scheduler()  # New summaries → papers now eligible for comparison

    # Finalize progress tracker
    prog = _summary_gen_progress.get(prog_key)
    if prog:
        prog.update({"running": False, "generated": generated, "failed": failed, "skipped": skipped, "scanned": scanned,
                      "finished_at": datetime.now(timezone.utc).isoformat()})

    # Clear activity status (was stuck on "Generating summaries..." after completion)
    if cat_status:
        cat_status["current_activity"] = "Idle"

    return generated



async def run_comparison_round(max_pairs_override=None, category: str = "cs.RO", skip_rerank: bool = False):
    from core.memlog import log_mem
    lock = _get_lock(category)
    if lock.locked():
        return {"status": "already_processing"}

    async with lock:
        log_mem(f"comparison_round({category}) start")
        cat_status = _get_cat_status(category)
        cat_status["is_processing"] = True
        cat_status["current_activity"] = "Comparing papers..."

        try:
            settings = await get_settings()
            parallel_agents = min(max(settings.get("parallel_agents", 5), 1), 20)
            top_k_focus = settings.get("top_k_focus", 10)
            max_new_per_round = settings.get("max_new_matches_per_round", 3)
            summary_source = settings.get("summary_source", "claude")

            from core.config import DEFAULT_EVALUATION_PROMPT
            custom_prompt_doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
            if custom_prompt_doc:
                prompt_config = {
                    "system_prompt": custom_prompt_doc.get("system_prompt", DEFAULT_EVALUATION_PROMPT["system_prompt"]),
                    "user_prompt": custom_prompt_doc.get("user_prompt", DEFAULT_EVALUATION_PROMPT["user_prompt"]),
                }
            else:
                prompt_config = DEFAULT_EVALUATION_PROMPT

            current_prompt_hash = _prompt_hash(prompt_config)

            _paper_fields = {
                "_id": 0, "id": 1, "title": 1, "abstract": 1,
                "authors": 1, "arxiv_id": 1, "link": 1, "published": 1,
                "pdf_link": 1, "added_at": 1,
            }
            all_papers = await collect_all(db.papers.find(
                {"categories.0": category}, _paper_fields
            ))

            if len(all_papers) < 2:
                cat_status["current_activity"] = "Not enough papers"
                return {"status": "not_enough_papers"}

            # Filter out papers without the required summary for the current source.
            # Uses a lightweight DB query to check existence (avoids loading ~385MB of summary text).
            summary_model = _pick_summary_source(summary_source)
            required_key = _summary_model_key(summary_model)
            fallback_keys = _SUMMARY_KEY_FALLBACKS.get(required_key, [])
            all_keys = [required_key] + fallback_keys
            summary_filter = {"$or": [{f"summaries.{k}": {"$exists": True}} for k in all_keys]}
            summary_filter["categories.0"] = category
            papers_with_summary = set()
            async for doc in db.papers.find(summary_filter, {"_id": 0, "id": 1}):
                papers_with_summary.add(doc["id"])

            papers_with_summaries = [p for p in all_papers if p["id"] in papers_with_summary]
            papers_without = len(all_papers) - len(papers_with_summaries)
            if papers_without > 0:
                logger.info(f"[{category}] Excluding {papers_without} papers without {required_key} summary from matchmaking")
            all_papers = papers_with_summaries
            if len(all_papers) < 2:
                cat_status["current_activity"] = "Waiting for summaries"
                return {"status": "waiting_for_summaries", "papers_without_summaries": papers_without}

            # Download any missing PDFs for this category
            papers_missing_text = sum(1 for p in all_papers if not p.get("full_text"))
            if papers_missing_text > 0:
                dl_count = await _download_pending_pdfs(category=category)
                if dl_count > 0:
                    # Re-fetch and re-apply the same summary filter
                    refetched = await collect_all(db.papers.find(
                        {"categories.0": category}, _paper_fields
                    ))
                    papers_with_summary_2 = set()
                    async for doc in db.papers.find(summary_filter, {"_id": 0, "id": 1}):
                        papers_with_summary_2.add(doc["id"])
                    all_papers = [p for p in refetched if p["id"] in papers_with_summary_2]

            # Read paper_stats from rankings collection (O(P) lightweight reads)
            # instead of computing from all_matches (which would load 20K+ docs)
            paper_stats = {}
            async for rdoc in db.rankings.find(
                {"category": category},
                {"_id": 0, "paper_id": 1, "wins": 1, "losses": 1, "comparisons": 1, "score": 1},
            ):
                pid = rdoc["paper_id"]
                paper_stats[pid] = {
                    "wins": rdoc.get("wins", 0),
                    "losses": rdoc.get("losses", 0),
                    "comparisons": rdoc.get("comparisons", 0),
                    "score": rdoc.get("score", 1200),
                }
            # Ensure all papers have an entry (new papers may not be in rankings yet)
            for p in all_papers:
                if p["id"] not in paper_stats:
                    paper_stats[p["id"]] = {"wins": 0, "losses": 0, "comparisons": 0, "score": 1200}

            if max_pairs_override:
                max_pairs = min(max_pairs_override, 500)
            else:
                max_pairs_cap = settings.get("max_pairs_per_round", 100)
                max_pairs = min(max_pairs_cap, len(all_papers) * 2)
            pairs = await _select_pairs(
                all_papers, paper_stats, category,
                max_pairs, top_k_focus, max_new_per_round,
                ci_target=settings.get("ci_target", 10),
                ci_target_general=settings.get("ci_target_general", 15),
                calibration_ratio=settings.get("calibration_ratio", 50),
            )

            if not pairs:
                cat_status["current_activity"] = "No new pairs needed"
                _mark_pair_exhausted(category)
                return {"status": "no_pairs"}

            paper_lookup = {p["id"]: p for p in all_papers}
            completed = 0
            failed = 0
            total_matches = cat_status.get("matches_count", 0)

            # Semaphore-based pipeline: results saved as each completes
            sem = asyncio.Semaphore(parallel_agents)
            _paused = False

            async def _run_one(p1_orig, p2_orig):
                nonlocal completed, failed, _paused
                if _paused:
                    return

                # Random flip for positional bias
                if secrets.randbelow(2):
                    p1_id, p2_id = p2_orig, p1_orig
                else:
                    p1_id, p2_id = p1_orig, p2_orig

                p1 = paper_lookup[p1_id]
                p2 = paper_lookup[p2_id]
                summary_model = _pick_summary_source(summary_source)
                smk = _summary_model_key(summary_model)
                p1_with_sum = {**p1, "ai_impact_summary": _get_paper_summary(p1, smk)}
                p2_with_sum = {**p2, "ai_impact_summary": _get_paper_summary(p2, smk)}

                async with sem:
                    # Check pause between acquiring semaphore and running
                    if _paused:
                        return
                    try:
                        llm_timeout = settings.get("llm_request_timeout", 120)
                        result = await asyncio.wait_for(
                            compare_papers(p1_with_sum, p2_with_sum, prompt_config, content_mode="abstract_plus_summary"),
                            timeout=llm_timeout,
                        )
                    except asyncio.TimeoutError:
                        result = TimeoutError(f"LLM comparison timed out after {llm_timeout}s")
                    except Exception as e:
                        result = e

                p1_cats = set(paper_lookup[p1_id].get("categories", []))
                p2_cats = set(paper_lookup[p2_id].get("categories", []))
                shared_cats = sorted(p1_cats & p2_cats)

                match_doc = {
                    "id": str(uuid.uuid4()),
                    "paper1_id": p1_id, "paper2_id": p2_id,
                    "dedup_pair": _make_dedup_pair(p1_id, p2_id),
                    "primary_category": category,
                    "shared_categories": shared_cats,
                    "content_mode": "abstract_plus_summary",
                    "prompt_hash": current_prompt_hash,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

                if isinstance(result, Exception):
                    match_doc.update({"completed": False, "failed": True, "error": str(result)[:200], "reasoning": f"Failed: {str(result)[:100]}"})
                    failed += 1
                else:
                    winner_key = result.get("winner", "paper1")
                    match_doc.update({
                        "winner_id": p1_id if winner_key == "paper1" else p2_id,
                        "reasoning": result.get("reasoning", ""),
                        "model_used": result.get("model_used", {}),
                        "tokens": result.get("tokens", {}),
                        "completed": True, "failed": False,
                    })
                    completed += 1

                await db.matches.insert_one(match_doc)
                # Track LLM usage for this match
                from services.llm import track_llm_usage
                match_tokens = match_doc.get("tokens", {})
                match_model = match_doc.get("model_used", {})
                match_label = f"{p1.get('title','')[:30]} vs {p2.get('title','')[:30]}"
                await track_llm_usage(
                    match_model.get("provider", ""), match_model.get("model", ""),
                    context="match", success=match_doc.get("completed", False),
                    input_tokens=match_tokens.get("input_est", match_tokens.get("input", 0)),
                    output_tokens=match_tokens.get("output_est", match_tokens.get("output", 0)),
                    paper_title=match_label,
                )
                # Bump incremental match counter (avoids full-collection scan in _refresh_cache)
                from routers.leaderboard import bump_match_counter
                bump_match_counter(category, failed=match_doc.get("failed", False))
                # Incrementally update DB-backed rankings for this match
                if match_doc.get("completed") and match_doc.get("winner_id"):
                    from services.ranking import update_rankings_for_match
                    w_id = match_doc["winner_id"]
                    l_id = p2_id if w_id == p1_id else p1_id
                    model_used = match_doc.get("model_used", {})
                    await update_rankings_for_match(db, category, w_id, l_id, model_used=model_used)
                cat_status["matches_count"] = total_matches + completed + failed
                cat_status["current_activity"] = f"Comparing... {total_matches + completed + failed} total matches"

            # Periodically check for pause
            async def _pause_checker():
                nonlocal _paused
                while not _paused:
                    await asyncio.sleep(5)
                    mid_settings = await get_settings()
                    if mid_settings.get("paused", False):
                        _paused = True
                        logger.info(f"[{category}] System paused mid-round, stopping new comparisons")

            pause_task = asyncio.create_task(_pause_checker())
            all_tasks = [_run_one(p1, p2) for p1, p2 in pairs]
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*all_tasks, return_exceptions=True),
                    timeout=300,  # 5 min max per round — prevents indefinite hangs
                )
            except asyncio.TimeoutError:
                logger.warning(f"[{category}] Comparison round timed out after 300s ({completed} completed, {len(pairs)} attempted)")
                results = []
            _paused = True  # Stop pause checker
            pause_task.cancel()

            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[{category}] Comparison task error: {r}")

            now_iso = datetime.now(timezone.utc).isoformat()
            cat_status["last_process_at"] = now_iso
            cat_status["current_activity"] = f"{total_matches + completed} total matches"
            logger.info(f"[{category}] Comparison round: {completed} ok, {failed} failed")
            log_mem(f"comparison_round({category}) done (ok={completed}, fail={failed}, total={total_matches + completed})")

            if completed > 0:
                # Rerank unless caller will handle it (compare loop does sequential reranks)
                if not skip_rerank:
                    try:
                        from services.ranking import rerank_category_light
                        await rerank_category_light(db, category)
                    except Exception as e:
                        logger.warning(f"[{category}] Rankings rerank failed: {e}")
                # Recompute gap scores for this category
                try:
                    await _recompute_gap_scores(category)
                except Exception as e:
                    logger.warning(f"[{category}] Gap recompute failed: {e}")
                # Signal leaderboard cache to refresh
                from routers.leaderboard import notify_data_changed
                notify_data_changed()
                # Invalidate admin progress cache for this category
                from routers.admin import _invalidate_admin_cache
                _invalidate_admin_cache(category)
                # Recompute convergence in background (non-blocking)
                asyncio.create_task(_recompute_convergence_bg(category))
            elif completed == 0 and failed == 0:
                # No matches at all — pairs exhausted for this category
                _mark_pair_exhausted(category)

            return {"status": "ok", "completed": completed, "failed": failed}

        except Exception as e:
            logger.error(f"[{category}] Comparison round failed: {e}")
            cat_status["current_activity"] = f"Processing error: {str(e)[:100]}"
            log_mem(f"comparison_round({category}) FAILED: {str(e)[:80]}")
            return {"status": "error", "error": str(e)}
        finally:
            cat_status["is_processing"] = False
            # P1: Free large data structures to reduce arena fragmentation
            for _var in ("all_papers", "paper_lookup", "paper_stats"):
                try:
                    del locals()[_var]  # noqa
                except (KeyError, NameError):
                    pass
            from core.memlog import force_gc
            force_gc()



async def _recompute_gap_scores(category: str):
    """Recompute gap_score for all papers in a category.
    
    gap = tournament_percentile - rating_percentile
    Uses scipy.rankdata for proper fractional tie handling.
    Only for papers with ai_rating and >= 3 matches.
    Fast: single DB query + in-memory percentile computation + bulk write.
    """
    from scipy.stats import rankdata
    import numpy as np

    entries = []
    async for r in db.rankings.find(
        {"category": category, "comparisons": {"$gte": 3}, "is_latest_version": {"$ne": False}},
        {"_id": 0, "paper_id": 1, "ts_score": 1, "ai_rating": 1},
    ):
        if r.get("ai_rating") is not None and r.get("ai_rating") >= 0 and r.get("ts_score") is not None:
            entries.append(r)

    if len(entries) < 5:
        return

    n = len(entries)
    ts_vals = np.array([e["ts_score"] for e in entries])
    ai_vals = np.array([e["ai_rating"] for e in entries])

    ts_pct = rankdata(ts_vals) / n * 100
    ai_pct = rankdata(ai_vals) / n * 100
    gap_raw = ts_pct - ai_pct

    # Chunked bulk update
    from pymongo import UpdateOne
    BULK_CHUNK = 5000
    ops = []
    for i, entry in enumerate(entries):
        gap = round(float(gap_raw[i]), 1)
        ops.append(UpdateOne(
            {"paper_id": entry["paper_id"], "category": category},
            {"$set": {"gap_score": gap}},
        ))
        if len(ops) >= BULK_CHUNK:
            await db.rankings.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        await db.rankings.bulk_write(ops, ordered=False)
    del ops


# Track last convergence recompute per category (match count at last recompute)
_convergence_last_recomputed: Dict[str, int] = {}
_CONVERGENCE_RECOMPUTE_THRESHOLD = 0.05  # 5% match growth triggers recompute


async def _recompute_convergence_bg(category: str):
    """Recompute convergence curve for a category and store in MongoDB.
    
    Rate-limited: only recomputes when match count has grown by ≥5% since last
    recompute. Convergence curves barely change with 20-100 new matches.
    """
    try:
        # Check if enough new matches to justify recompute
        current_count = await db.matches.count_documents({
            "completed": True, "failed": {"$ne": True},
            "primary_category": category, "mode": {"$exists": False},
            "revision_superseded": {"$ne": True},
        })
        last_count = _convergence_last_recomputed.get(category, 0)
        if last_count > 0 and current_count < last_count * (1 + _CONVERGENCE_RECOMPUTE_THRESHOLD):
            return  # Skip — not enough new matches

        from routers.leaderboard import _compute_convergence
        result = await _compute_convergence(category, 20)
        if result.get("curve"):
            await db.convergence_cache.update_one(
                {"category": category or "__all__"},
                {"$set": result},
                upsert=True,
            )
            _convergence_last_recomputed[category] = current_count
    except Exception as e:
        logger.debug(f"Convergence recompute for {category}: {e}")


def _make_dedup_pair(p1: str, p2: str) -> str:
    """Normalized pair key — always sorted for consistent dedup."""
    a, b = (p1, p2) if p1 < p2 else (p2, p1)
    return f"{a}|{b}"


async def _get_compared_opponents(paper_id: str, category: str, candidates: list) -> set:
    """Query DB for which candidates have already been compared with paper_id.
    
    Uses the dedup_pair index — O(1) per batch regardless of total match count.
    Falls back to full scan if dedup_pair hasn't been backfilled yet.
    """
    if not candidates:
        return set()
    # Build all possible dedup_pair values
    pair_keys = [_make_dedup_pair(paper_id, c) for c in candidates]
    already = set()
    async for m in db.matches.find(
        {"primary_category": category, "dedup_pair": {"$in": pair_keys},
         "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False},
         "revision_superseded": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        # Return the opponent ID (the one that isn't paper_id)
        opp = m["paper2_id"] if m["paper1_id"] == paper_id else m["paper1_id"]
        already.add(opp)
    return already


async def _select_pairs(
    papers: list, stats: dict, category: str,
    max_pairs: int, top_k: int, max_per_round: int, **kwargs,
) -> List[tuple]:
    """
    Goal-directed pair selection with 2-tier CI targets.
    Loads all existing pairs once, then checks in-memory (O(1) per pair).
    """
    from services.ranking import wilson_margin_pct

    paper_ids = [p["id"] for p in papers]
    if len(paper_ids) < 2:
        return []

    ci_target = kwargs.get("ci_target", 10)
    ci_target_general = kwargs.get("ci_target_general", 15)
    calibration_pct = kwargs.get("calibration_ratio", 50)

    # --- Load ALL existing dedup_pairs for this category once (replaces N per-paper queries) ---
    existing_pairs = set()
    async for m in db.matches.find(
        {"primary_category": category, "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}},
        {"_id": 0, "dedup_pair": 1},
    ):
        if m.get("dedup_pair"):
            existing_pairs.add(m["dedup_pair"])

    comparisons = {}
    wins = {}
    margins = {}

    for pid in paper_ids:
        s = stats.get(pid, {})
        c = s.get("comparisons", 0)
        w = s.get("wins", 0)
        comparisons[pid] = c
        wins[pid] = w
        margins[pid] = wilson_margin_pct(w, c)

    # Use stored scores from rankings collection (same source as _check_goals_met)
    SCORE_BASE = 1200
    wr_scores = {}
    for pid in paper_ids:
        wr_scores[pid] = stats.get(pid, {}).get("score", SCORE_BASE)

    elo_vals = sorted(wr_scores.values())
    median_elo = elo_vals[len(elo_vals) // 2]

    all_ranked = sorted(paper_ids, key=lambda pid: wr_scores[pid], reverse=True)
    top_k_ids = set(all_ranked[:min(top_k, len(all_ranked))])
    top_k_list = all_ranked[:min(top_k, len(all_ranked))]

    pairs = []
    round_count = {pid: 0 for pid in paper_ids}
    # Track pairs selected THIS round (to avoid selecting the same pair twice)
    selected_this_round = set()

    def can_pair(p):
        return round_count[p] < max_per_round

    # --- Rule 1: Match neediest papers (widest margin vs their target) ---
    def urgency(pid):
        target = ci_target if pid in top_k_ids else ci_target_general
        if comparisons[pid] == 0:
            return 999
        if margins[pid] > target:
            return margins[pid] - target
        return 0

    needy = sorted(paper_ids, key=lambda pid: urgency(pid), reverse=True)
    needy = [pid for pid in needy if urgency(pid) > 0]
    established = [pid for pid in paper_ids if urgency(pid) == 0]
    pair_idx = 0

    for p1 in needy:
        if len(pairs) >= max_pairs or not can_pair(p1):
            continue

        prefer_established = len(established) > 0 and ((pair_idx * calibration_pct) % 100 < calibration_pct)
        pair_idx += 1

        # Get all already-compared opponents for p1
        all_candidates = [p for p in paper_ids if p != p1 and can_pair(p)]
        # Check already-compared opponents via in-memory set (no DB query)
        already_compared = {c for c in all_candidates if _make_dedup_pair(p1, c) in existing_pairs}
        # Also exclude pairs selected this round
        already_compared |= {opp for pair_key in selected_this_round for opp in [pair_key.split("|")[0], pair_key.split("|")[1]] if _make_dedup_pair(p1, opp) == pair_key}

        best = None

        if prefer_established:
            target = median_elo if comparisons[p1] == 0 else wr_scores[p1]
            best_dist = float('inf')
            for p2 in established:
                if p2 == p1 or not can_pair(p2) or p2 in already_compared:
                    continue
                dist = abs(wr_scores[p2] - target)
                if dist < best_dist:
                    best_dist = dist
                    best = p2

        # If no novel established opponent, pick a novel needy opponent
        if best is None:
            best_score = -1
            for p2 in needy:
                if p2 == p1 or not can_pair(p2) or p2 in already_compared:
                    continue
                score = urgency(p2)
                if score > best_score:
                    best_score = score
                    best = p2

        # Fallback: any paper with novel pair
        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2) and p2 not in already_compared:
                    best = p2
                    break

        # No novel pair found → skip this paper (never generate repeats)
        if best:
            pairs.append((p1, best))
            selected_this_round.add(_make_dedup_pair(p1, best))
            round_count[p1] += 1
            round_count[best] += 1

    if len(pairs) >= max_pairs:
        return pairs[:max_pairs]

    # --- Rule 2: Top-K cross-matches (use same in-memory set) ---
    topk_pair_keys = []
    topk_pair_map = {}
    for i in range(len(top_k_list)):
        for j in range(i + 1, len(top_k_list)):
            pk = _make_dedup_pair(top_k_list[i], top_k_list[j])
            topk_pair_keys.append(pk)
            topk_pair_map[pk] = (top_k_list[i], top_k_list[j])

    for pk in topk_pair_keys:
        if len(pairs) >= max_pairs:
            break
        if pk not in existing_pairs and pk not in selected_this_round:
            p1, p2 = topk_pair_map[pk]
            pairs.append((p1, p2))
            selected_this_round.add(pk)
            round_count[p1] += 1
            round_count[p2] += 1

    return pairs[:max_pairs]


async def backfill_shared_categories():
    """One-time backfill: add shared_categories and primary_category to existing matches."""
    # Backfill primary_category (denormalized for indexed queries)
    missing_primary = await db.matches.count_documents({"primary_category": {"$exists": False}})

    if missing_primary > 0:
        logger.info(f"Backfilling primary_category for {missing_primary} matches...")
        # Build paper -> primary category lookup
        paper_primary = {}
        async for p in db.papers.find({}, {"_id": 0, "id": 1, "categories": 1}):
            cats = p.get("categories", [])
            paper_primary[p["id"]] = cats[0] if cats else "unknown"

        updated_pc = 0
        async for m in db.matches.find(
            {"primary_category": {"$exists": False}},
            {"_id": 1, "paper1_id": 1},
        ):
            p1_cat = paper_primary.get(m.get("paper1_id"), "unknown")
            await db.matches.update_one(
                {"_id": m["_id"]},
                {"$set": {"primary_category": p1_cat}},
            )
            updated_pc += 1
        logger.info(f"Backfilled primary_category for {updated_pc} matches")

    # Backfill shared_categories
    missing_shared = await db.matches.count_documents({"shared_categories": {"$exists": False}})
    if missing_shared == 0 and missing_primary == 0:
        logger.info("shared_categories/primary_category backfill: nothing to do")
        return 0

    if missing_shared > 0:
        logger.info(f"Backfilling shared_categories for {missing_shared} matches...")
        paper_cats = {}
        async for p in db.papers.find({}, {"_id": 0, "id": 1, "categories": 1}):
            paper_cats[p["id"]] = set(p.get("categories", []))

        updated = 0
        async for m in db.matches.find(
            {"shared_categories": {"$exists": False}},
            {"_id": 1, "paper1_id": 1, "paper2_id": 1},
        ):
            p1_cats = paper_cats.get(m.get("paper1_id"), set())
            p2_cats = paper_cats.get(m.get("paper2_id"), set())
            shared = sorted(p1_cats & p2_cats)
            await db.matches.update_one(
                {"_id": m["_id"]},
                {"$set": {"shared_categories": shared}},
            )
            updated += 1
        logger.info(f"Backfilled shared_categories for {updated} matches")

    return missing_primary + missing_shared
