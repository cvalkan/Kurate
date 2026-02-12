import asyncio
import uuid
import random
import math
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from core.config import db, logger, DEFAULT_SETTINGS, CATEGORIES
from core.auth import get_settings
from services.arxiv import fetch_arxiv_papers
from services.llm import download_and_extract_pdf, compare_papers
from services.ranking import calculate_confidence_interval, wilson_margin_pct

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
                    "min_matches": settings.get("min_matches_per_paper", 5),
                    "ci_target": settings.get("ci_target", 12),
                    "top_k": settings.get("top_k_focus", 10),
                    "max_matches": settings.get("max_matches_per_paper", 150),
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
    paper_count = await db.papers.count_documents({"categories.0": category})
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
        _get_cat_status(cat_id)
    logger.info("Background scheduler started")
    asyncio.create_task(_scheduler_loop())


async def _scheduler_loop():
    global _scheduler_running, _wake_event
    await asyncio.sleep(5)

    while _scheduler_running:
        try:
            settings = await get_settings()
            interval_hours = settings.get("fetch_interval_hours", 24)
            is_paused = settings.get("paused", False)
            min_papers = settings.get("min_papers_for_tournament", 8)

            # Get active tournaments from registry (single source of truth for what to run)
            tournaments = await get_active_tournaments()
            active_cats = list({t["category"] for t in tournaments})

            # Also track ALL known categories for fetch/stats (even paused ones)
            all_tournament_cats = set()
            all_tournaments_raw = await db.tournaments.find({}, {"_id": 0, "category": 1}).to_list(500)
            for t in all_tournaments_raw:
                all_tournament_cats.add(t["category"])
            # Fallback only if no tournaments exist at all (fresh install)
            if not all_tournament_cats:
                all_tournament_cats = set(settings.get("active_categories", list(CATEGORIES.keys())))

            # Fetch papers only for ACTIVE categories (paused categories don't fetch)
            for cat in active_cats:
                cat_status = _get_cat_status(cat)
                last_fetch_key = f"last_fetch_at_{cat}"
                last_fetch = settings.get(last_fetch_key)

                should_fetch = False
                if not last_fetch:
                    should_fetch = True
                else:
                    last_dt = datetime.fromisoformat(last_fetch)
                    if datetime.now(timezone.utc) - last_dt > timedelta(hours=interval_hours):
                        should_fetch = True

                if should_fetch:
                    await run_fetch_cycle(category=cat)
                    now_iso = datetime.now(timezone.utc).isoformat()
                    await db.settings.update_one(
                        {"key": "global"},
                        {"$set": {last_fetch_key: now_iso}},
                        upsert=True,
                    )
                    cat_status["last_fetch_at"] = now_iso

                # Compute next fetch time for this category
                settings_refreshed = await get_settings()
                cat_last = settings_refreshed.get(last_fetch_key)
                if cat_last:
                    last_dt = datetime.fromisoformat(cat_last)
                    cat_status["next_fetch_at"] = (last_dt + timedelta(hours=interval_hours)).isoformat()

            # Update per-category paper/match counts and tournament stats for ALL categories
            for cat in all_tournament_cats:
                cat_status = _get_cat_status(cat)
                cat_paper_count = await db.papers.count_documents({"categories.0": cat})
                cat_status["papers_count"] = cat_paper_count
                cat_match_count = await db.matches.count_documents(
                    {"completed": True, "failed": {"$ne": True}, "primary_category": cat, "mode": {"$exists": False}}
                )
                cat_status["matches_count"] = cat_match_count
                await update_tournament_stats(cat)

            # Mark paused categories in status
            paused_cats = all_tournament_cats - set(active_cats)
            for cat in paused_cats:
                _get_cat_status(cat)["current_activity"] = "Tournament paused"

            if not is_paused and active_cats:
                # Check which active categories need work (skip if below min papers threshold)
                unmet_cats = []
                for cat in active_cats:
                    paper_count = _get_cat_status(cat).get("papers_count", 0)
                    if paper_count < min_papers:
                        _get_cat_status(cat)["current_activity"] = f"Insufficient papers ({paper_count}/{min_papers})"
                        continue
                    if not await _check_goals_met(category=cat):
                        unmet_cats.append(cat)

                if unmet_cats:
                    # Run all unmet categories in parallel
                    tasks = [run_comparison_round(category=cat) for cat in unmet_cats]
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await asyncio.sleep(5)
                    continue
                else:
                    for cat in active_cats:
                        if _get_cat_status(cat).get("papers_count", 0) >= min_papers:
                            _get_cat_status(cat)["current_activity"] = "Goals met — idle"
            elif is_paused:
                for cat in all_tournament_cats:
                    _get_cat_status(cat)["current_activity"] = "System paused"

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

        # Wait up to 30s, but wake immediately if signaled
        _wake_event.clear()
        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


async def _check_goals_met(category: str = "cs.RO") -> bool:
    """Check if all ranking goals are satisfied for a category.
    
    Goal 1: All papers have >= min_matches
    Goal 2: Top-K papers have CI <= ci_target
    Goal 3: All non-capped top-K papers have played against each other at least once
    """
    settings = await get_settings()
    min_matches = settings.get("min_matches_per_paper", 3)
    max_matches = settings.get("max_matches_per_paper", 150)
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 12)

    paper_ids = [p["id"] async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1})]
    if len(paper_ids) < 2:
        return True

    pid_set = set(paper_ids)
    paper_match_count = {pid: 0 for pid in paper_ids}
    paper_wins = {pid: 0 for pid in paper_ids}
    compared_pairs = set()

    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1
            compared_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
            w = m.get("winner_id")
            if w and w in paper_wins:
                paper_wins[w] += 1

    # Goal 1: min matches per paper
    for c in paper_match_count.values():
        if c < min_matches:
            return False

    # Identify top-K by win rate (ALL papers, including capped)
    sorted_papers = sorted(
        paper_match_count.keys(),
        key=lambda pid: paper_wins.get(pid, 0) / max(paper_match_count.get(pid, 0), 1),
        reverse=True,
    )
    top_k_ids = sorted_papers[:min(top_k, len(sorted_papers))]

    # Goal 2: CI convergence for top-K
    for pid in top_k_ids:
        n = paper_match_count[pid]
        if n >= max_matches:
            continue
        w = paper_wins.get(pid, 0)
        margin_pct = wilson_margin_pct(w, n)
        if margin_pct > ci_target:
            return False

    # Goal 3: Cross-matches among non-capped top-K papers
    # Papers at max_matches are exempt — they've played enough
    capped = {pid for pid in top_k_ids if paper_match_count[pid] >= max_matches}
    crossmatch_ids = [pid for pid in top_k_ids if pid not in capped]
    for i in range(len(crossmatch_ids)):
        for j in range(i + 1, len(crossmatch_ids)):
            pair = tuple(sorted([crossmatch_ids[i], crossmatch_ids[j]]))
            if pair not in compared_pairs:
                return False

    return True


async def run_fetch_cycle(category: str = "cs.RO"):
    if category in _fetching_cats:
        return {"status": "already_fetching"}

    _fetching_cats.add(category)
    cat_status = _get_cat_status(category)
    cat_status["is_fetching"] = True
    cat_status["current_activity"] = "Fetching papers..."

    try:
        settings = await get_settings()
        max_papers = settings.get("max_papers_per_fetch", 50)

        raw_papers = await fetch_arxiv_papers(category=category, max_results=max_papers)
        logger.info(f"Fetched {len(raw_papers)} {category} papers from arXiv")

        new_count = 0
        for rp in raw_papers:
            exists = await db.papers.find_one({"arxiv_id": rp["arxiv_id"]}, {"_id": 0, "id": 1})
            if not exists:
                paper_doc = {
                    "id": str(uuid.uuid4()),
                    "arxiv_id": rp["arxiv_id"],
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
                }
                await db.papers.insert_one(paper_doc)
                new_count += 1

        cat_status["current_activity"] = f"Fetched {new_count} new papers"
        logger.info(f"Added {new_count} new {category} papers to DB")

        if new_count > 0:
            await _download_pending_pdfs(category=category)

        return {"status": "ok", "new_papers": new_count, "total_fetched": len(raw_papers)}

    except Exception as e:
        logger.error(f"Fetch cycle failed for {category}: {e}")
        cat_status["current_activity"] = f"Fetch failed: {str(e)[:100]}"
        return {"status": "error", "error": str(e)}
    finally:
        _fetching_cats.discard(category)
        cat_status["is_fetching"] = False


async def _download_pending_pdfs(category: str = None):
    """Download PDFs for papers missing full_text, scoped to a category."""
    query = {"$or": [{"needs_pdf": True}, {"full_text": None}], "pdf_link": {"$ne": None}}
    if category:
        query["categories.0"] = category

    papers_needing_pdf = await db.papers.find(
        query, {"_id": 0, "id": 1, "pdf_link": 1, "title": 1},
    ).to_list(200)

    if not papers_needing_pdf:
        return 0

    cat_status = _get_cat_status(category) if category else None

    downloaded = 0
    for i, paper in enumerate(papers_needing_pdf):
        if cat_status:
            cat_status["current_activity"] = f"Downloading PDF {i+1}/{len(papers_needing_pdf)}: {paper['title'][:40]}..."
        try:
            full_text = await download_and_extract_pdf(paper["pdf_link"])
            if full_text:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"full_text": full_text, "needs_pdf": False}},
                )
                downloaded += 1
            else:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"needs_pdf": False}},
                )
        except Exception as e:
            logger.warning(f"PDF download failed for {paper['id']}: {e}")
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"needs_pdf": False}},
            )
        await asyncio.sleep(1)
    return downloaded


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
            min_matches_per_paper = settings.get("min_matches_per_paper", 5)
            max_matches_per_paper = settings.get("max_matches_per_paper", 150)
            max_new_per_round = settings.get("max_new_matches_per_round", 3)
            ci_target = settings.get("ci_target", 12)
            section_char_limit = settings.get("section_char_limit", 2000)  # Pre-fetch for batch

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

            all_papers = await db.papers.find(
                {"categories.0": category},
                {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                 "authors": 1, "arxiv_id": 1, "link": 1, "published": 1, "pdf_link": 1, "added_at": 1}
            ).to_list(5000)

            if len(all_papers) < 2:
                cat_status["current_activity"] = "Not enough papers"
                return {"status": "not_enough_papers"}

            # Download any missing PDFs for this category
            papers_missing_text = sum(1 for p in all_papers if not p.get("full_text"))
            if papers_missing_text > 0:
                dl_count = await _download_pending_pdfs(category=category)
                if dl_count > 0:
                    all_papers = await db.papers.find(
                        {"categories.0": category},
                        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                         "authors": 1, "arxiv_id": 1, "link": 1, "published": 1, "pdf_link": 1, "added_at": 1}
                    ).to_list(5000)

            # Only load standard matches for this category (exclude experiments)
            all_matches = await db.matches.find(
                {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
            ).to_list(100000)

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
                max_pairs, top_k_focus, min_matches_per_paper,
                max_matches_per_paper, max_new_per_round, ci_target,
            )

            if not pairs:
                cat_status["current_activity"] = "No new pairs needed"
                return {"status": "no_pairs"}

            paper_lookup = {p["id"]: p for p in all_papers}
            completed = 0
            failed = 0
            total_matches = len(all_matches)

            for i in range(0, len(pairs), parallel_agents):
                batch = pairs[i:i + parallel_agents]
                tasks = []
                # Randomly flip pair order to eliminate positional bias
                presented_batch = []
                for p1_id, p2_id in batch:
                    if random.random() < 0.5:
                        presented_batch.append((p2_id, p1_id))
                    else:
                        presented_batch.append((p1_id, p2_id))
                for p1_id, p2_id in presented_batch:
                    tasks.append(compare_papers(paper_lookup[p1_id], paper_lookup[p2_id], prompt_config, char_limit=section_char_limit))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for (p1_id, p2_id), result in zip(presented_batch, results):
                    # Compute shared categories between the two papers (piggyback)
                    p1_cats = set(paper_lookup[p1_id].get("categories", []))
                    p2_cats = set(paper_lookup[p2_id].get("categories", []))
                    shared_cats = sorted(p1_cats & p2_cats)

                    match_doc = {
                        "id": str(uuid.uuid4()),
                        "paper1_id": p1_id,
                        "paper2_id": p2_id,
                        "primary_category": category,
                        "shared_categories": shared_cats,
                        "prompt_hash": current_prompt_hash,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }

                    if isinstance(result, Exception):
                        match_doc["completed"] = False
                        match_doc["failed"] = True
                        match_doc["error"] = str(result)[:200]
                        match_doc["reasoning"] = f"Failed: {str(result)[:100]}"
                        failed += 1
                    else:
                        winner_key = result.get("winner", "paper1")
                        match_doc["winner_id"] = p1_id if winner_key == "paper1" else p2_id
                        match_doc["reasoning"] = result.get("reasoning", "")
                        match_doc["model_used"] = result.get("model_used", {})
                        match_doc["tokens"] = result.get("tokens", {})
                        match_doc["completed"] = True
                        match_doc["failed"] = False
                        completed += 1

                    await db.matches.insert_one(match_doc)

                cat_status["matches_count"] = total_matches + completed + failed
                cat_status["current_activity"] = f"Comparing... {total_matches + completed + failed} total matches"
                await asyncio.sleep(0.5)

            now_iso = datetime.now(timezone.utc).isoformat()
            cat_status["last_process_at"] = now_iso
            cat_status["current_activity"] = f"{total_matches + completed} total matches"
            logger.info(f"[{category}] Comparison round: {completed} ok, {failed} failed")

            # Generate impact summaries only for this category
            await _generate_pending_summaries(category=category)

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

    all_papers = await db.papers.find(
        query,
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "authors": 1, "categories": 1},
    ).to_list(500)

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

        summary = await generate_impact_summary(paper, logs, summary_prompt, char_limit=section_char_limit)
        if summary:
            await db.papers.update_one(
                {"id": pid},
                {"$set": {"impact_summary": summary, "summary_generated_at": datetime.now(timezone.utc).isoformat()}},
            )
            logger.info(f"Summary generated for {pid}")
        else:
            await db.papers.update_one(
                {"id": pid},
                {"$set": {"impact_summary": None, "summary_generated_at": datetime.now(timezone.utc).isoformat()}},
            )

        await asyncio.sleep(1)


def _select_pairs(
    papers: list, stats: dict, compared_pairs: set,
    max_pairs: int, top_k: int, min_matches: int,
    max_matches: int, max_per_round: int, ci_target: float = 12.0,
) -> List[tuple]:
    """
    Smart pair selection with adaptive per-paper round caps.

    Key principles:
    1. Top-K cross-matches: missing pairs among top-K papers get HIGHEST priority
    2. Papers below min_matches get high priority AND higher per-round cap
    3. After min_matches, CI-width drives both priority and round cap
    4. Papers with narrow CIs or extreme win rates get lower caps
    5. Pairs with similar win rates are preferred (most informative)
    6. Top-K papers get boosted priority and caps when CI needs narrowing
    """
    paper_ids = [p["id"] for p in papers]
    n = len(paper_ids)
    if n < 2:
        return []

    # Pre-compute per-paper metrics
    capped = set()
    comparisons = {}
    win_rates = {}
    ci_widths = {}

    for pid in paper_ids:
        s = stats.get(pid, {})
        c = s.get("comparisons", 0)
        w = s.get("wins", 0)
        comparisons[pid] = c
        if c >= max_matches:
            capped.add(pid)
        win_rates[pid] = w / max(c, 1)
        ci_widths[pid] = wilson_margin_pct(w, c)

    active = [pid for pid in paper_ids if pid not in capped]
    if len(active) < 2:
        return []

    # Rank ALL papers by win rate for top-K detection (including capped)
    # This ensures top-K identification is consistent with _check_goals_met
    all_ranked = sorted(paper_ids, key=lambda pid: win_rates[pid], reverse=True)
    top_k_all = all_ranked[:min(top_k, len(all_ranked))]

    # For Phase 0 cross-matching: only non-capped top-K papers
    # Capped papers are exempt (they've hit max_matches)
    top_k_crossmatch = [pid for pid in top_k_all if pid not in capped]

    # For priority/cap calculations: top-K among active papers
    top_k_set = set(top_k_all) & set(active)

    # Also sort active papers for normal pair selection (used in Phase 1+)
    # (priority_sorted is used below instead of ranked)

    # --- Phase 0: Top-K cross-matches (highest priority) ---
    # Find all missing pairs among non-capped top-K papers
    topk_missing_pairs = []
    for i in range(len(top_k_crossmatch)):
        for j in range(i + 1, len(top_k_crossmatch)):
            pair_key = tuple(sorted([top_k_crossmatch[i], top_k_crossmatch[j]]))
            if pair_key not in compared_pairs:
                topk_missing_pairs.append((top_k_crossmatch[i], top_k_crossmatch[j]))

    pairs = []
    round_count = {pid: 0 for pid in active}

    # Inject top-K cross-match pairs first (up to half the budget)
    topk_budget = max(max_pairs // 2, len(topk_missing_pairs))
    for p1, p2 in topk_missing_pairs[:topk_budget]:
        if len(pairs) >= max_pairs:
            break
        pairs.append((p1, p2))
        compared_pairs.add(tuple(sorted([p1, p2])))
        round_count[p1] += 1
        round_count[p2] += 1

    if len(pairs) >= max_pairs:
        return pairs[:max_pairs]

    # --- Phase 1+: Normal priority-based selection ---
    # Per-paper priority score AND adaptive round cap
    paper_priority = {}
    paper_round_cap = {}  # Adaptive per-paper cap

    for pid in active:
        c = comparisons[pid]
        ci = ci_widths[pid]
        wr = win_rates[pid]

        # Phase 1: Deficit — papers below min_matches
        deficit = max(0, min_matches - c) / max(min_matches, 1)
        in_deficit = c < min_matches

        # Phase 2: CI-driven
        ci_urgency = max(0, (ci - ci_target)) / max(ci_target, 1)

        # Exploration bonus for very new papers
        exploration = max(0, 1.0 - c / max(min_matches * 2, 1))

        # Top-K boost
        topk_bonus = 0
        if pid in top_k_set and ci > ci_target:
            topk_bonus = ci_urgency * 2.0

        # Extreme penalty — reduced for top-K papers to ensure they get matched
        extreme_penalty = 0
        is_extreme = False
        if c >= min_matches and (wr > 0.9 or wr < 0.1):
            is_extreme = True
            if pid not in top_k_set:
                extreme_penalty = 0.5 * (1 - min(ci_urgency, 1.0))
            # No penalty for top-K extreme papers — they need differentiation

        priority = (deficit * 10.0
                    + ci_urgency * 5.0
                    + exploration * 1.0
                    + topk_bonus
                    - extreme_penalty)
        paper_priority[pid] = max(priority, 0.01)

        # Adaptive round cap based on urgency
        if in_deficit:
            # Deficit papers: allow up to 2x the base cap to quickly fill minimum
            paper_round_cap[pid] = max_per_round * 2
        elif pid in top_k_set and ci > ci_target:
            # Top-K papers still needing CI narrowing: boosted cap
            paper_round_cap[pid] = max(max_per_round, int(max_per_round * (1 + ci_urgency)))
        elif is_extreme and ci <= ci_target and pid not in top_k_set:
            # Extreme NON-top-K papers with narrow CI: minimal cap
            paper_round_cap[pid] = max(1, max_per_round // 2)
        elif ci <= ci_target and c >= min_matches:
            # Converged papers: reduced cap
            paper_round_cap[pid] = max(1, max_per_round // 2)
        else:
            # Normal: base cap scaled by CI urgency
            paper_round_cap[pid] = max(max_per_round, int(max_per_round * min(1 + ci_urgency * 0.5, 2)))

    # Sort papers by priority (highest first)
    priority_sorted = sorted(active, key=lambda pid: paper_priority[pid], reverse=True)

    # Generate candidate pairs with adaptive caps
    for p1 in priority_sorted:
        cap1 = paper_round_cap.get(p1, max_per_round)
        if round_count[p1] >= cap1 or len(pairs) >= max_pairs:
            continue

        best_opponents = []
        for p2 in priority_sorted:
            cap2 = paper_round_cap.get(p2, max_per_round)
            if p2 == p1 or round_count[p2] >= cap2:
                continue
            pair_key = tuple(sorted([p1, p2]))
            is_novel = pair_key not in compared_pairs

            pair_score = paper_priority[p1] + paper_priority[p2]

            # Win-rate similarity bonus
            wr_diff = abs(win_rates[p1] - win_rates[p2])
            similarity_bonus = max(0, 1.0 - wr_diff * 3.0)
            pair_score += similarity_bonus * 2.0

            if is_novel:
                pair_score += 3.0
            else:
                pair_score *= 0.1

            best_opponents.append((p2, pair_score, is_novel, pair_key))

        best_opponents.sort(key=lambda x: x[1], reverse=True)

        for p2, score, is_novel, pair_key in best_opponents:
            cap1 = paper_round_cap.get(p1, max_per_round)
            cap2 = paper_round_cap.get(p2, max_per_round)
            if round_count[p1] >= cap1 or len(pairs) >= max_pairs:
                break
            if round_count[p2] >= cap2:
                continue
            if not is_novel and any(x[2] for x in best_opponents):
                continue
            pairs.append((p1, p2))
            compared_pairs.add(pair_key)
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
