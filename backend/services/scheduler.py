import asyncio
import uuid
import random
import math
import hashlib
import re as _re_mod
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from core.config import db, logger, DEFAULT_SETTINGS, CATEGORIES
from core.auth import get_settings
from services.arxiv import fetch_arxiv_papers
from services.llm import download_and_extract_pdf, compare_papers, generate_precomparison_impact_summary
from services.ranking import compute_leaderboard, compute_leaderboard_async


from routers.validation_utils import collect_all

def _re_escape(s: str) -> str:
    """Escape a string for use in MongoDB regex."""
    return _re_mod.escape(s)

_scheduler_running = False
_processing_locks = {}  # Per-category locks
_fetching_cats = set()  # Categories currently being fetched
_wake_event: asyncio.Event = None  # Wake scheduler immediately on resume


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


def stop_summary_generation():
    """Signal all running summary generation to stop immediately."""
    global _summary_gen_stop
    _summary_gen_stop = True


def get_summary_gen_progress(category: str = None) -> dict:
    """Get the current summary generation progress for a category."""
    key = category or "__all__"
    return _summary_gen_progress.get(key, {"running": False})


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


async def _iter_cursor_batches(cursor, batch_size: int = 100):
    """Yield cursor results in batches so large categories do not get truncated."""
    while True:
        batch = await cursor.to_list(length=batch_size)
        if not batch:
            break
        yield batch
        if len(batch) < batch_size:
            break
        await asyncio.sleep(0)


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
            {"completed": True, "failed": {"$ne": True}, "primary_category": cat_id, "mode": {"$exists": False}}
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


async def get_active_tournaments() -> list:
    """Return all active tournament documents."""
    tournaments = await db.tournaments.find(
        {"status": "active"}, {"_id": 0}
    ).to_list(500)
    return tournaments


async def update_tournament_stats(category: str, mode: str = "standard"):
    """Update stats on a tournament document."""
    tid = f"cat={category}|mode={mode}"
    paper_count = await db.papers.count_documents({"categories.0": category, "summaries": {"$exists": True, "$ne": {}}})
    match_count = await db.matches.count_documents(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}}
    )
    goals_met = await _check_goals_met(category=category)
    await db.tournaments.update_one(
        {"tournament_id": tid},
        {"$set": {
            "stats.papers": paper_count,
            "stats.matches": match_count,
            "stats.goals_met": goals_met,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


async def start_scheduler():
    global _scheduler_running, _wake_event
    if _scheduler_running:
        return
    _scheduler_running = True
    _wake_event = asyncio.Event()
    # Initialize status for all active categories (dynamic from settings)
    settings = await get_settings()
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
    await asyncio.sleep(8)  # Let compare loop start first

    while _scheduler_running:
        next_due_seconds = float("inf")
        try:
            settings = await get_settings()
            interval_hours = settings.get("fetch_interval_hours", 6)
            now = datetime.now(timezone.utc)

            fetch_cats = set(settings.get("active_categories", list(CATEGORIES.keys())))
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
                    await run_fetch_cycle(category=cat)
                    now_iso = datetime.now(timezone.utc).isoformat()
                    await db.settings.update_one(
                        {"key": "global"},
                        {"$set": {last_fetch_key: now_iso}},
                        upsert=True,
                    )
                    cat_status["last_fetch_at"] = now_iso
                    cat_status["next_fetch_at"] = (datetime.now(timezone.utc) + timedelta(hours=interval_hours)).isoformat()
                    # Cooldown between categories: GC + sleep to release memory before next category
                    import gc
                    gc.collect()
                    await asyncio.sleep(15)
                    # Re-read settings in case pause was toggled during fetch
                    settings = await get_settings()

        except Exception as e:
            logger.error(f"Fetch loop error: {e}")

        # Sleep until next fetch is due (minimum 60s to avoid busy-loop on errors)
        sleep_time = max(60, min(next_due_seconds, interval_hours * 3600)) if next_due_seconds != float("inf") else interval_hours * 3600
        await asyncio.sleep(sleep_time)


async def _compare_loop():
    """Independent loop for running tournament comparisons. Never waits for fetches."""
    global _wake_event
    await asyncio.sleep(5)

    while _scheduler_running:
        try:
            settings = await get_settings()
            is_paused = settings.get("paused", False)
            min_papers = settings.get("min_papers_for_tournament", 8)

            tournaments = await get_active_tournaments()
            active_cats = list({t["category"] for t in tournaments})

            # Track ALL known categories for stats
            all_tournament_cats = set()
            all_tournaments_raw = await db.tournaments.find({}, {"_id": 0, "category": 1}).to_list(500)
            for t in all_tournaments_raw:
                all_tournament_cats.add(t["category"])
            if not all_tournament_cats:
                all_tournament_cats = set(settings.get("active_categories", list(CATEGORIES.keys())))

            if not is_paused and active_cats:
                # Update per-category paper/match counts and tournament stats
                for cat in all_tournament_cats:
                    cat_status = _get_cat_status(cat)
                    cat_paper_count = await db.papers.count_documents({"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}})
                    cat_status["papers_count"] = cat_paper_count
                    cat_match_count = await db.matches.count_documents(
                        {"completed": True, "failed": {"$ne": True}, "primary_category": cat, "mode": {"$exists": False}}
                    )
                    cat_status["matches_count"] = cat_match_count
                    await update_tournament_stats(cat)

                # Mark paused categories
                paused_cats = all_tournament_cats - set(active_cats)
                for cat in paused_cats:
                    _get_cat_status(cat)["current_activity"] = "Tournament paused"

                unmet_cats = []
                for cat in active_cats:
                    paper_count = _get_cat_status(cat).get("papers_count", 0)
                    if paper_count < min_papers:
                        _get_cat_status(cat)["current_activity"] = f"Insufficient papers ({paper_count}/{min_papers})"
                        continue
                    tid = f"cat={cat}|mode=standard"
                    t_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "compare_paused": 1})
                    if t_doc and t_doc.get("compare_paused"):
                        _get_cat_status(cat)["current_activity"] = "Comparisons paused"
                        continue
                    if not await _check_goals_met(category=cat):
                        unmet_cats.append(cat)

                if unmet_cats:
                    batch_size = min(max(settings.get("parallel_categories", 2), 1), 10)
                    for i in range(0, len(unmet_cats), batch_size):
                        batch = unmet_cats[i:i+batch_size]
                        tasks = [run_comparison_round(category=cat) for cat in batch]
                        await asyncio.gather(*tasks, return_exceptions=True)
                        # GC between batches to release match/paper data from completed rounds
                        import gc
                        gc.collect()
                        await asyncio.sleep(2)
                    # After a round completes, loop immediately to check if more work needed
                    continue
                else:
                    for cat in active_cats:
                        if _get_cat_status(cat).get("papers_count", 0) >= min_papers:
                            _get_cat_status(cat)["current_activity"] = "Goals met — idle"
            elif is_paused:
                for cat in all_tournament_cats:
                    _get_cat_status(cat)["current_activity"] = "System paused"

        except Exception as e:
            logger.error(f"Compare loop error: {e}")

        # Sleep until explicitly woken by wake_scheduler() — no polling
        _wake_event.clear()
        await _wake_event.wait()


async def _store_ranking_snapshot(category: str):
    """Store a ranking snapshot after a comparison round.
    
    Each snapshot records the current BT ranking so we can compare
    rankings across rounds to detect convergence.
    """
    papers = await _collect_cursor_docs(
        db.papers.find(
            {"categories.0": category}, {"_id": 0, "id": 1, "title": 1}
        ),
        batch_size=1000,
    )
    if len(papers) < 2:
        return

    all_matches = await collect_all(db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ))

    pid_set = {p["id"] for p in papers}
    filtered = [m for m in all_matches if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set]
    if not filtered:
        return

    lb = await compute_leaderboard_async(papers, filtered)
    rankings = {e["id"]: e["rank"] for e in lb}

    # Get next round number for this category
    last = await db.ranking_snapshots.find_one(
        {"category": category}, sort=[("round", -1)], projection={"_id": 0, "round": 1}
    )
    next_round = (last["round"] + 1) if last else 1

    await db.ranking_snapshots.insert_one({
        "category": category,
        "round": next_round,
        "rankings": rankings,
        "total_matches": len(filtered),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.debug(f"[{category}] Stored ranking snapshot round {next_round}")


async def _check_goals_met(category: str = "cs.RO") -> bool:
    """Check if ranking has converged for a category.
    
    Two-tier Wilson CI convergence:
    1. General papers: CI margin ≤ ci_target_general (default 15%)
    2. Top-K papers: CI margin ≤ ci_target (default 10%)
    3. Top-K cross-matching: all top-K pairs compared
    """
    from services.ranking import wilson_margin_pct

    settings = await get_settings()
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 10)
    ci_target_general = settings.get("ci_target_general", 15)

    papers = await _collect_cursor_docs(
        db.papers.find(
            {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}},
            {"_id": 0, "id": 1}
        ),
        batch_size=1000,
    )
    paper_ids = [p["id"] for p in papers]
    if len(paper_ids) < 2:
        return True

    pid_set = set(paper_ids)
    paper_match_count = {pid: 0 for pid in paper_ids}
    paper_wins = {pid: 0 for pid in paper_ids}
    compared_pairs = set()

    all_matches = await collect_all(db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))

    for m in all_matches:
        if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1
            compared_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
            w = m.get("winner_id")
            if w and w in paper_wins:
                paper_wins[w] += 1

    # Identify top-K
    sorted_papers = sorted(
        paper_ids,
        key=lambda pid: paper_wins.get(pid, 0) / max(paper_match_count.get(pid, 0), 1),
        reverse=True,
    )
    top_k_ids = set(sorted_papers[:min(top_k, len(sorted_papers))])
    top_k_list = sorted_papers[:min(top_k, len(sorted_papers))]

    # Goal 1: General papers CI ≤ ci_target_general
    for pid in paper_ids:
        if pid in top_k_ids:
            continue
        margin = wilson_margin_pct(paper_wins.get(pid, 0), paper_match_count.get(pid, 0))
        if margin > ci_target_general:
            return False

    # Goal 2: Top-K papers CI ≤ ci_target
    for pid in top_k_list:
        margin = wilson_margin_pct(paper_wins.get(pid, 0), paper_match_count.get(pid, 0))
        if margin > ci_target:
            return False

    # Goal 3: Top-K cross-matching
    for i in range(len(top_k_list)):
        for j in range(i + 1, len(top_k_list)):
            pair = tuple(sorted([top_k_list[i], top_k_list[j]]))
            if pair not in compared_pairs:
                return False

    return True


async def run_fetch_cycle(category: str = "cs.RO", force: bool = False):
    if category in _fetching_cats:
        return {"status": "already_fetching"}

    _fetching_cats.add(category)
    cat_status = _get_cat_status(category)
    cat_status["is_fetching"] = True
    cat_status["current_activity"] = "Fetching papers..."

    try:
        settings = await get_settings()
        max_papers = settings.get("max_papers_per_fetch", 50)

        # Route to the correct fetcher based on category prefix
        if category.startswith("chemrxiv."):
            from services.chemrxiv import fetch_chemrxiv_papers
            raw_papers = await fetch_chemrxiv_papers(category=category, max_results=max_papers)
            logger.info(f"Fetched {len(raw_papers)} {category} papers from ChemRxiv")
            id_field = "chemrxiv_id"  # Dedup key for ChemRxiv
        else:
            raw_papers = await fetch_arxiv_papers(category=category, max_results=max_papers)
            logger.info(f"Fetched {len(raw_papers)} {category} papers from arXiv")
            id_field = "arxiv_id"

        new_count = 0
        # Batch dedup: load existing source IDs and dedup hashes for this category
        existing_ids = set()
        existing_hashes = set()
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
            if dedup_value in existing_ids:
                continue
            title_norm = rp["title"].strip().lower()
            first_author = (rp.get("authors") or [""])[0].strip().lower() if rp.get("authors") else ""
            content_hash = hashlib.sha256(f"{title_norm}|{first_author}".encode()).hexdigest()[:16]
            if content_hash in existing_hashes:
                logger.debug(f"[{category}] Skipping duplicate (hash match): {rp['title'][:60]}")
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
            # Store source-specific IDs
            if rp.get("arxiv_id"):
                paper_doc["arxiv_id"] = rp["arxiv_id"]
            if rp.get("chemrxiv_id"):
                paper_doc["chemrxiv_id"] = rp["chemrxiv_id"]
            if rp.get("doi"):
                paper_doc["doi"] = rp["doi"]
            await db.papers.insert_one(paper_doc)
            existing_hashes.add(content_hash)  # Prevent same-batch duplicates
            new_count += 1

        cat_status["current_activity"] = f"Fetched {new_count} new papers, downloading PDFs..."
        logger.info(f"Added {new_count} new {category} papers to DB")

        # Update paper count immediately so admin dashboard reflects new papers
        cat_status["papers_count"] = await db.papers.count_documents({"categories.0": category})

        # Always attempt PDF downloads (catches retries for previously failed downloads)
        await _download_pending_pdfs(category=category)

        # Generate AI summaries for papers with full text
        cat_status["current_activity"] = "Generating summaries..."
        await _generate_paper_summaries(category=category, force=force)

        # Final paper count (with summaries — for compare loop eligibility)
        cat_status["papers_count"] = await db.papers.count_documents({"categories.0": category})

        # Add new papers with summaries to DB-backed rankings
        if new_count > 0:
            try:
                from services.ranking import insert_ranking_for_paper
                async for p in db.papers.find(
                    {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}},
                    {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                     "link": 1, "published": 1, "added_at": 1, "categories": 1, "ai_rating": 1}
                ):
                    existing = await db.rankings.find_one({"paper_id": p["id"]}, {"_id": 0, "paper_id": 1})
                    if not existing:
                        await insert_ranking_for_paper(db, p)
            except Exception as e:
                logger.warning(f"[{category}] Rankings insert failed: {e}")

        cat_status["current_activity"] = "Idle"
        if new_count > 0:
            from routers.leaderboard import notify_data_changed
            notify_data_changed()
            wake_scheduler()  # New papers → compare loop should check for unmet goals
        return {"status": "ok", "new_papers": new_count, "total_fetched": len(raw_papers)}

    except Exception as e:
        logger.error(f"Fetch cycle failed for {category}: {e}")
        cat_status["current_activity"] = f"Fetch failed: {str(e)[:100]}"
        return {"status": "error", "error": str(e)}
    finally:
        _fetching_cats.discard(category)
        cat_status["is_fetching"] = False


async def _download_pending_pdfs(category: str = None):
    """Download PDFs for papers missing full_text, scoped to a category.
    
    Papers that fail extraction are marked with needs_pdf=False and pdf_failed=True
    so they can be retried later without blocking every cycle.
    """
    query = {"$or": [{"needs_pdf": True}, {"full_text": None, "pdf_failed": {"$ne": True}}], "pdf_link": {"$ne": None}}
    if category:
        query["categories.0"] = category

    papers_needing_pdf = await collect_all(db.papers.find(
        query, {"_id": 0, "id": 1, "pdf_link": 1, "title": 1, "doi": 1},
    ))

    if not papers_needing_pdf:
        return 0

    cat_status = _get_cat_status(category) if category else None

    downloaded = 0
    for i, paper in enumerate(papers_needing_pdf):
        if cat_status:
            cat_status["current_activity"] = f"Downloading PDF {i+1}/{len(papers_needing_pdf)}: {paper['title'][:40]}..."
        try:
            full_text = await download_and_extract_pdf(paper["pdf_link"], doi=paper.get("doi"))
            if full_text:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"full_text": full_text, "needs_pdf": False}, "$unset": {"pdf_failed": ""}},
                )
                downloaded += 1
            else:
                # Mark as failed so it's not retried every cycle, but can be force-retried
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"needs_pdf": False, "pdf_failed": True}},
                )
        except Exception as e:
            logger.warning(f"PDF download failed for {paper['id']}: {e}")
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"needs_pdf": False, "pdf_failed": True}},
            )
        await asyncio.sleep(1)
    return downloaded


# --- Summary model configuration ---
# Models used to GENERATE summaries (Claude uses thinking mode for higher quality)
_SUMMARY_GENERATION_MODELS = [
    {"provider": "anthropic", "model": "claude-opus-4-6",
     "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}},
     "key_suffix": "thinking"},
    {"provider": "openai", "model": "gpt-5.2"},
    {"provider": "gemini", "model": "gemini-3-pro-preview"},
]

# Models whose summaries can be selected for live tournament comparisons.
# Only Claude (thinking) is used in live tournaments; GPT/Gemini summaries are
# generated for analysis purposes but NOT fed to judges.
_SUMMARY_MODELS = {
    "claude": {"provider": "anthropic", "model": "claude-opus-4-6", "key_suffix": "thinking"},
    "gemini": {"provider": "gemini", "model": "gemini-3-pro-preview"},
    "gpt": {"provider": "openai", "model": "gpt-5.2"},
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
        "anthropic:claude-opus-4-6",            # non-thinking Opus 4.6
        "anthropic:claude-opus-4-5-20251101",    # legacy Opus 4.5
    ],
    "anthropic:claude-opus-4-6": ["anthropic:claude-opus-4-5-20251101"],
}


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
    paper_cursor = db.papers.find(
        query,
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "categories": 1, "summaries": 1}
    )

    cat_status = _get_cat_status(category) if category else None
    sem = asyncio.Semaphore(parallel)
    generated = 0
    failed = 0
    skipped = 0
    scanned = 0
    batch_size = max(25, min(parallel * 10, 250))

    # Track progress for external visibility
    prog_key = category or "__all__"
    _summary_gen_progress[prog_key] = {
        "running": True, "generated": 0, "failed": 0, "skipped": 0,
        "scanned": 0, "total": total_papers, "started_at": datetime.now(timezone.utc).isoformat(),
    }

    def _sync_progress():
        """Push current counters to progress tracker for real-time UI updates."""
        prog = _summary_gen_progress.get(prog_key)
        if prog:
            prog.update({"generated": generated, "failed": failed, "skipped": skipped, "scanned": scanned})

    async def gen_one(paper, model_info):
        nonlocal generated, failed, skipped
        # Instant stop check — no cache delay
        if _summary_gen_stop:
            return
        # Also check settings for pause
        s = await get_settings()
        if s.get("paused", False):
            return

        mk = _summary_model_key(model_info)
        # Check if already exists (including fallback keys) — don't regenerate
        if _get_paper_summary(paper, mk):
            skipped += 1
            _sync_progress()
            return

        async with sem:
            # Re-check stop flag after acquiring semaphore
            if _summary_gen_stop:
                return
            s2 = await get_settings()
            if s2.get("paused", False):
                return
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=model_info)
            except Exception as e:
                failed += 1
                _sync_progress()
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
                            update_fields["ai_rating"] = ratings
                    # Store per-model ratings for SI inter-model correlation
                    from services.llm import parse_ratings_from_summary as _parse_ratings
                    _model_ratings = _parse_ratings(summary_val)
                    if _model_ratings:
                        # Map model key to short name: anthropic:claude-opus-4-6:thinking -> claude
                        _model_short = "claude" if "anthropic" in mk else "gpt" if "openai" in mk else "gemini" if "gemini" in mk else None
                        if _model_short:
                            update_fields[f"ai_ratings_by_model.{_model_short}"] = _model_ratings
                    await db.papers.update_one(
                        {"id": paper["id"]},
                        {"$set": update_fields},
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

    async for paper_batch in _iter_cursor_batches(paper_cursor, batch_size=batch_size):
        scanned += len(paper_batch)
        if cat_status:
            cat_status["current_activity"] = f"Generating summaries... ({scanned}/{total_papers} scanned, {generated} new)"
        _sync_progress()
        tasks = []
        for paper in paper_batch:
            for model_info in _SUMMARY_GENERATION_MODELS:
                tasks.append(gen_one(paper, model_info))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if total_papers:
        logger.info(f"[{category}] Summary generation complete: {generated} new, {failed} failed, {skipped} skipped across {scanned} papers")
        if generated > 0:
            from routers.leaderboard import notify_data_changed
            notify_data_changed()
            wake_scheduler()  # New summaries → papers now eligible for comparison

    # Finalize progress tracker
    prog = _summary_gen_progress.get(prog_key)
    if prog:
        prog.update({"running": False, "generated": generated, "failed": failed, "skipped": skipped, "scanned": scanned,
                      "finished_at": datetime.now(timezone.utc).isoformat()})

    return generated



async def run_comparison_round(max_pairs_override=None, category: str = "cs.RO"):
    lock = _get_lock(category)
    if lock.locked():
        return {"status": "already_processing"}

    async with lock:
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
                "pdf_link": 1, "added_at": 1, "summaries": 1,
            }
            all_papers = await collect_all(db.papers.find(
                {"categories.0": category}, _paper_fields
            ))

            if len(all_papers) < 2:
                cat_status["current_activity"] = "Not enough papers"
                return {"status": "not_enough_papers"}

            # Filter out papers without the required summary for the current source.
            # This ensures papers aren't compared using only abstracts when a summary
            # is expected. Resolves the issue where papers with only GPT/Gemini summaries
            # would participate in a Claude-only tournament.
            summary_model = _pick_summary_source(summary_source)
            required_key = _summary_model_key(summary_model)
            papers_with_summaries = [
                p for p in all_papers
                if p.get("summaries") and _get_paper_summary(p, required_key)
            ]
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
                    all_papers = [
                        p for p in refetched
                        if p.get("summaries") and _get_paper_summary(p, required_key)
                    ]

            # Only load standard matches for this category (exclude experiments)
            all_matches = await collect_all(db.matches.find(
                {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
            ))

            paper_stats = {}
            for p in all_papers:
                paper_stats[p["id"]] = {"wins": 0, "losses": 0, "comparisons": 0}
            for m in all_matches:
                p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
                if p1 in paper_stats:
                    paper_stats[p1]["comparisons"] += 1
                if p2 in paper_stats:
                    paper_stats[p2]["comparisons"] += 1
                if w and w in paper_stats:
                    paper_stats[w]["wins"] += 1
                loser = p2 if w == p1 else p1
                if loser in paper_stats:
                    paper_stats[loser]["losses"] += 1

            compared_pairs = set()
            for m in all_matches:
                compared_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

            if max_pairs_override:
                max_pairs = min(max_pairs_override, 500)
            else:
                max_pairs = min(100, len(all_papers) * 2)
            pairs = _select_pairs(
                all_papers, paper_stats, compared_pairs,
                max_pairs, top_k_focus, max_new_per_round,
                ci_target=settings.get("ci_target", 10),
                ci_target_general=settings.get("ci_target_general", 15),
                calibration_ratio=settings.get("calibration_ratio", 50),
            )

            if not pairs:
                cat_status["current_activity"] = "No new pairs needed"
                return {"status": "no_pairs"}

            paper_lookup = {p["id"]: p for p in all_papers}
            completed = 0
            failed = 0
            total_matches = len(all_matches)

            # Semaphore-based pipeline: results saved as each completes
            sem = asyncio.Semaphore(parallel_agents)
            _paused = False

            async def _run_one(p1_orig, p2_orig):
                nonlocal completed, failed, _paused
                if _paused:
                    return

                # Random flip for positional bias
                if random.random() < 0.5:
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
                        result = await compare_papers(p1_with_sum, p2_with_sum, prompt_config, content_mode="abstract_plus_summary")
                    except Exception as e:
                        result = e

                p1_cats = set(paper_lookup[p1_id].get("categories", []))
                p2_cats = set(paper_lookup[p2_id].get("categories", []))
                shared_cats = sorted(p1_cats & p2_cats)

                match_doc = {
                    "id": str(uuid.uuid4()),
                    "paper1_id": p1_id, "paper2_id": p2_id,
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
                # Incrementally update DB-backed rankings for this match
                if match_doc.get("completed") and match_doc.get("winner_id"):
                    try:
                        from services.ranking import update_rankings_for_match
                        w_id = match_doc["winner_id"]
                        l_id = p2_id if w_id == p1_id else p1_id
                        await update_rankings_for_match(db, category, w_id, l_id)
                    except Exception:
                        pass  # Non-critical — rerank_category fixes it at round end
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
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
            _paused = True  # Stop pause checker
            pause_task.cancel()

            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[{category}] Comparison task error: {r}")

            now_iso = datetime.now(timezone.utc).isoformat()
            cat_status["last_process_at"] = now_iso
            cat_status["current_activity"] = f"{total_matches + completed} total matches"
            logger.info(f"[{category}] Comparison round: {completed} ok, {failed} failed")

            # Store ranking snapshot for convergence tracking
            if completed > 0:
                await _store_ranking_snapshot(category)
                # Update DB-backed rankings incrementally
                try:
                    from services.ranking import rerank_category
                    await rerank_category(db, category)
                except Exception as e:
                    logger.warning(f"[{category}] Rankings rerank failed: {e}")
                # Signal leaderboard cache to refresh
                from routers.leaderboard import notify_data_changed
                notify_data_changed()

            return {"status": "ok", "completed": completed, "failed": failed}

        except Exception as e:
            logger.error(f"[{category}] Comparison round failed: {e}")
            cat_status["current_activity"] = f"Processing error: {str(e)[:100]}"
            return {"status": "error", "error": str(e)}
        finally:
            cat_status["is_processing"] = False


async def _generate_pending_summaries(category: str = None):
    """Generate impact summaries for papers in a category when the tournament has completed.
    
    Criteria for generating summaries:
    - Tournament for the category must have all goals met (stopped)
    - Paper must have at least 3 matches (enough data for meaningful summary)
    """
    from services.llm import generate_impact_summary

    settings = await get_settings()
    section_char_limit = settings.get("section_char_limit", 2000)

    # Check if tournament goals are met for this category
    if category:
        goals_met = await _check_goals_met(category=category)
        if not goals_met:
            logger.debug(f"Skipping summary generation for {category} - tournament goals not met")
            return
    else:
        # If no category specified, skip - we need a specific category to check goals
        return

    summary_prompt_doc = await db.settings.find_one({"key": "summary_prompt"}, {"_id": 0})
    summary_prompt = summary_prompt_doc if summary_prompt_doc and summary_prompt_doc.get("system_prompt") else None

    # Find papers without summaries in this category
    query = {
        "$or": [{"impact_summary": {"$exists": False}}, {"impact_summary": None}],
        "categories.0": category
    }

    all_papers = await collect_all(db.papers.find(
        query,
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "authors": 1, "categories": 1},
    ))

    if not all_papers:
        return

    # Get match counts for these papers
    paper_ids = [p["id"] for p in all_papers]
    paper_match_count = {pid: 0 for pid in paper_ids}
    paper_wins = {pid: 0 for pid in paper_ids}

    match_query = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}, "primary_category": category}

    async for m in db.matches.find(
        match_query,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        for pid in [m["paper1_id"], m["paper2_id"]]:
            if pid in paper_match_count:
                paper_match_count[pid] += 1
        w = m.get("winner_id")
        if w and w in paper_wins:
            paper_wins[w] += 1

    cat_status = _get_cat_status(category)

    # Sort papers by match count (highest first) to prioritize well-tested papers
    papers_sorted = sorted(all_papers, key=lambda p: paper_match_count.get(p["id"], 0), reverse=True)

    for paper in papers_sorted:
        pid = paper["id"]
        n = paper_match_count.get(pid, 0)

        # Require minimum matches for meaningful summary
        if n < 3:
            continue

        matches = await db.matches.find(
            {"completed": True, "failed": {"$ne": True},
             "$or": [{"paper1_id": pid}, {"paper2_id": pid}]},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "reasoning": 1},
        ).to_list(500)

        opp_ids = set()
        for m in matches:
            opp_ids.add(m["paper2_id"] if m["paper1_id"] == pid else m["paper1_id"])
        opp_titles = {}
        async for o in db.papers.find({"id": {"$in": list(opp_ids)}}, {"_id": 0, "id": 1, "title": 1}):
            opp_titles[o["id"]] = o["title"]

        logs = []
        for m in matches:
            opp_id = m["paper2_id"] if m["paper1_id"] == pid else m["paper1_id"]
            logs.append({
                "won": m.get("winner_id") == pid,
                "opponent_title": opp_titles.get(opp_id, "Unknown"),
                "reasoning": m.get("reasoning", ""),
            })

        if cat_status:
            cat_status["current_activity"] = f"Generating summary: {paper['title'][:40]}..."
        logger.info(f"Generating impact summary for: {paper['title'][:50]}")

        result = await generate_impact_summary(paper, logs, summary_prompt, char_limit=section_char_limit)
        if result and result.get("summary"):
            await db.papers.update_one(
                {"id": pid},
                {"$set": {
                    "impact_summary": result["summary"],
                    "summary_model_used": result.get("model_used", {}),
                    "summary_generated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            logger.info(f"Summary generated for {pid} using {result.get('model_used', {}).get('model', 'unknown')}")
        else:
            await db.papers.update_one(
                {"id": pid},
                {"$set": {"impact_summary": None, "summary_generated_at": datetime.now(timezone.utc).isoformat()}},
            )

        await asyncio.sleep(1)


def _select_pairs(
    papers: list, stats: dict, compared_pairs: set,
    max_pairs: int, top_k: int, max_per_round: int, **kwargs,
) -> List[tuple]:
    """
    Goal-directed pair selection with 2-tier CI targets.
    1. Match neediest papers first (widest margin vs their tier's target)
       - Established opponents selected by Elo proximity (not arbitrary)
       - Needy-vs-needy matches preserved for efficiency (both papers benefit)
    2. Top-K cross-matches after rankings stabilize
    Repeat pairs only after all goals are met.
    """
    from services.ranking import wilson_margin_pct

    paper_ids = [p["id"] for p in papers]
    if len(paper_ids) < 2:
        return []

    ci_target = kwargs.get("ci_target", 10)
    ci_target_general = kwargs.get("ci_target_general", 15)
    calibration_pct = kwargs.get("calibration_ratio", 50)

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

    # Compute BT scores for opponent selection (accounts for opponent strength)
    from services.ranking import calculate_bradley_terry, _bt_to_score
    SCORE_BASE = 1200
    # Build BT from the stats we already have (wins/losses per paper)
    # Construct pseudo-matches from the stats
    bt_raw = {}
    total_w = sum(wins.values())
    if total_w > 0:
        # Use the existing match data already loaded by the caller
        # We have wins[pid] and comparisons[pid], but BT needs full match list
        # Approximate: use regularized win-rate mapped through BT-to-Elo
        for pid in paper_ids:
            w, c = wins[pid], comparisons[pid]
            if c == 0:
                bt_raw[pid] = 1.0
            else:
                bt_raw[pid] = max(1e-6, (w + 0.5) / (c + 1.0))
    else:
        bt_raw = {pid: 1.0 for pid in paper_ids}
    wr_scores = _bt_to_score(bt_raw, SCORE_BASE)

    elo_vals = sorted(wr_scores.values())
    median_elo = elo_vals[len(elo_vals) // 2]

    # Identify top-K papers using Elo (not raw win-rate)
    all_ranked = sorted(paper_ids, key=lambda pid: wr_scores[pid], reverse=True)
    top_k_ids = set(all_ranked[:min(top_k, len(all_ranked))])
    top_k_list = all_ranked[:min(top_k, len(all_ranked))]

    pairs = []
    round_count = {pid: 0 for pid in paper_ids}

    def can_pair(p):
        return round_count[p] < max_per_round

    # --- Rule 1: Match neediest papers (widest margin vs their target) ---
    def urgency(pid):
        target = ci_target if pid in top_k_ids else ci_target_general
        if comparisons[pid] == 0:
            return 999  # No data = most urgent
        if margins[pid] > target:
            return margins[pid] - target  # Distance from target
        return 0  # Converged

    needy = sorted(paper_ids, key=lambda pid: urgency(pid), reverse=True)
    needy = [pid for pid in needy if urgency(pid) > 0]
    established = [pid for pid in paper_ids if urgency(pid) == 0]
    pair_idx = 0

    for p1 in needy:
        if len(pairs) >= max_pairs or not can_pair(p1):
            continue

        # Calibration split: calibration_pct% against established, rest against needy
        # Use modular arithmetic: e.g., 50% → every other match; 30% → 3 out of 10
        prefer_established = len(established) > 0 and ((pair_idx * calibration_pct) % 100 < calibration_pct)
        pair_idx += 1

        best = None
        best_score = -1

        if prefer_established:
            # Pick established opponent closest to target Elo (not arbitrary first-found).
            # New papers (0 matches) target median; papers with data target their current Elo.
            target = median_elo if comparisons[p1] == 0 else wr_scores[p1]
            best_dist = float('inf')
            for p2 in established:
                if p2 == p1 or not can_pair(p2):
                    continue
                pair_key = tuple(sorted([p1, p2]))
                if pair_key in compared_pairs:
                    continue
                dist = abs(wr_scores[p2] - target)
                if dist < best_dist:
                    best_dist = dist
                    best = p2
        
        # If no established opponent found (or it's a needy-pair turn), pick another needy paper
        if best is None:
            for p2 in needy:
                if p2 == p1 or not can_pair(p2):
                    continue
                pair_key = tuple(sorted([p1, p2]))
                novel = pair_key not in compared_pairs
                score = (1000 if novel else 0) + urgency(p2)
                if score > best_score:
                    best_score = score
                    best = p2

        # Fallback: any paper with novel pair
        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2):
                    pair_key = tuple(sorted([p1, p2]))
                    if pair_key not in compared_pairs:
                        best = p2
                        break
        # Last resort: any paper
        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2):
                    best = p2
                    break
        if best:
            pair_key = tuple(sorted([p1, best]))
            pairs.append((p1, best))
            compared_pairs.add(pair_key)
            round_count[p1] += 1
            round_count[best] += 1

    if len(pairs) >= max_pairs:
        return pairs[:max_pairs]

    # --- Rule 2: Top-K cross-matches ---
    for i in range(len(top_k_list)):
        for j in range(i + 1, len(top_k_list)):
            if len(pairs) >= max_pairs:
                break
            pair_key = tuple(sorted([top_k_list[i], top_k_list[j]]))
            if pair_key not in compared_pairs:
                pairs.append((top_k_list[i], top_k_list[j]))
                compared_pairs.add(pair_key)
                round_count[top_k_list[i]] += 1
                round_count[top_k_list[j]] += 1
        if len(pairs) >= max_pairs:
            break

    if len(pairs) >= max_pairs:
        return pairs[:max_pairs]

    # --- Only when all goals likely met: repeat pairs for cross-model agreement ---
    # Re-compare Elo-adjacent papers to validate ranking boundaries.
    if not needy:
        missing_topk = any(
            tuple(sorted([top_k_list[i], top_k_list[j]])) not in compared_pairs
            for i in range(len(top_k_list)) for j in range(i + 1, len(top_k_list))
        )
        if not missing_topk:
            elo_sorted = sorted(paper_ids, key=lambda pid: wr_scores[pid])
            for i in range(len(elo_sorted) - 1):
                if len(pairs) >= max_pairs:
                    break
                p1, p2 = elo_sorted[i], elo_sorted[i + 1]
                if can_pair(p1) and can_pair(p2):
                    pk = tuple(sorted([p1, p2]))
                    if pk in compared_pairs:  # Only repeat existing pairs
                        pairs.append((p1, p2))
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
