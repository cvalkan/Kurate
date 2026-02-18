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
from services.llm import download_and_extract_pdf, compare_papers, generate_precomparison_impact_summary
from services.ranking import compute_leaderboard

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

            # Fetch papers for ALL tournament categories (not just active ones)
            # Fetching is independent of tournament match-running status
            for cat in all_tournament_cats:
                cat_status = _get_cat_status(cat)
                
                # Check per-tournament fetch_paused flag
                tid = f"cat={cat}|mode=standard"
                t_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "fetch_paused": 1})
                if t_doc and t_doc.get("fetch_paused"):
                    cat_status["current_activity"] = "Fetching paused"
                    continue

                last_fetch_key = f"last_fetch_at_{cat.replace('.', '_')}"
                last_fetch = settings.get(last_fetch_key)
                # Handle nested keys from older MongoDB dot-notation storage
                if not last_fetch or not isinstance(last_fetch, str):
                    parts = cat.split(".")
                    if len(parts) == 2:
                        nested = settings.get(f"last_fetch_at_{parts[0]}")
                        if isinstance(nested, dict):
                            last_fetch = nested.get(parts[1])

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
                # Check which active categories need work (skip if below min papers threshold or compare_paused)
                unmet_cats = []
                for cat in active_cats:
                    paper_count = _get_cat_status(cat).get("papers_count", 0)
                    if paper_count < min_papers:
                        _get_cat_status(cat)["current_activity"] = f"Insufficient papers ({paper_count}/{min_papers})"
                        continue
                    # Check per-tournament compare_paused flag
                    tid = f"cat={cat}|mode=standard"
                    t_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "compare_paused": 1})
                    if t_doc and t_doc.get("compare_paused"):
                        _get_cat_status(cat)["current_activity"] = "Comparisons paused"
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


async def _store_ranking_snapshot(category: str):
    """Store a ranking snapshot after a comparison round.
    
    Each snapshot records the current BT ranking so we can compare
    rankings across rounds to detect convergence.
    """
    papers = await db.papers.find(
        {"categories.0": category}, {"_id": 0, "id": 1, "title": 1}
    ).to_list(500)
    if len(papers) < 2:
        return

    all_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ).to_list(100000)

    pid_set = {p["id"] for p in papers}
    filtered = [m for m in all_matches if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set]
    if not filtered:
        return

    lb = compute_leaderboard(papers, filtered)
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

    papers = await db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}).to_list(500)
    paper_ids = [p["id"] for p in papers]
    if len(paper_ids) < 2:
        return True

    pid_set = set(paper_ids)
    paper_match_count = {pid: 0 for pid in paper_ids}
    paper_wins = {pid: 0 for pid in paper_ids}
    compared_pairs = set()

    all_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)

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
        for rp in raw_papers:
            # Dedup by source-specific ID
            dedup_key = id_field
            dedup_value = rp.get(id_field) or rp.get("doi") or rp.get("arxiv_id")
            if not dedup_value:
                continue
            exists = await db.papers.find_one({dedup_key: dedup_value}, {"_id": 0, "id": 1})
            if not exists:
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
                }
                # Store source-specific IDs
                if rp.get("arxiv_id"):
                    paper_doc["arxiv_id"] = rp["arxiv_id"]
                if rp.get("chemrxiv_id"):
                    paper_doc["chemrxiv_id"] = rp["chemrxiv_id"]
                if rp.get("doi"):
                    paper_doc["doi"] = rp["doi"]
                await db.papers.insert_one(paper_doc)
                new_count += 1

        cat_status["current_activity"] = f"Fetched {new_count} new papers, downloading PDFs..."
        logger.info(f"Added {new_count} new {category} papers to DB")

        # Update paper count immediately so admin dashboard reflects new papers
        cat_status["papers_count"] = await db.papers.count_documents({"categories.0": category})

        # Always attempt PDF downloads (catches retries for previously failed downloads)
        await _download_pending_pdfs(category=category)

        # Update count again after PDF downloads
        cat_status["papers_count"] = await db.papers.count_documents({"categories.0": category})

        # Generate AI summaries for papers with full text
        cat_status["current_activity"] = "Generating summaries..."
        await _generate_paper_summaries(category=category, force=force)

        cat_status["current_activity"] = "Idle"
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
        query, {"_id": 0, "id": 1, "pdf_link": 1, "title": 1, "doi": 1},
    ).to_list(200)

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


# Summary model mapping
_SUMMARY_MODELS = {
    "claude": {"provider": "anthropic", "model": "claude-opus-4-5-20251101"},
    "gemini": {"provider": "gemini", "model": "gemini-3-pro-preview"},
    "gpt": {"provider": "openai", "model": "gpt-5.2"},
}
_summary_rr_counter = 0


def _pick_summary_source(setting: str) -> dict:
    """Pick summary model based on admin setting."""
    global _summary_rr_counter
    if setting in _SUMMARY_MODELS:
        return _SUMMARY_MODELS[setting]
    # round_robin
    models = list(_SUMMARY_MODELS.values())
    model = models[_summary_rr_counter % len(models)]
    _summary_rr_counter += 1
    return model


def _summary_model_key(model_info: dict) -> str:
    # Replace dots with underscores — MongoDB interprets dots as nested paths in $set
    return f"{model_info['provider']}:{model_info['model']}".replace(".", "_")


async def _generate_paper_summaries(category: str = None, force: bool = False):
    """Generate AI impact summaries (3 models) for papers missing them."""
    from core.config import TOURNAMENT_MODELS

    settings = await get_settings()
    parallel = settings.get("summary_parallel", 10)

    query = {}
    if category:
        query["categories.0"] = category
    # Only papers with full_text (no abstract-only summaries)
    query["full_text"] = {"$ne": None}

    papers = await db.papers.find(
        query, {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "categories": 1, "summaries": 1}
    ).to_list(500)

    cat_status = _get_cat_status(category) if category else None
    sem = asyncio.Semaphore(parallel)
    generated = 0

    async def gen_one(paper, model_info):
        nonlocal generated
        # Check if system was paused mid-generation (skip for manual/forced operations)
        if not force:
            s = await get_settings()
            if s.get("paused", False):
                return

        mk = _summary_model_key(model_info)
        # Check if already exists and is a valid string > 50 chars
        existing = (paper.get("summaries") or {}).get(mk)
        if existing and isinstance(existing, str) and len(existing) > 50:
            return

        async with sem:
            if not force:
                s2 = await get_settings()
                if s2.get("paused", False):
                    return
            result = await generate_precomparison_impact_summary(paper, model_override=model_info)
            if result and result.get("summary"):
                summary_val = result["summary"]
                # Ensure we always store a string
                if not isinstance(summary_val, str):
                    summary_val = str(summary_val)
                if len(summary_val) > 50:
                    await db.papers.update_one(
                        {"id": paper["id"]},
                        {"$set": {f"summaries.{mk}": summary_val}},
                    )
                    generated += 1
                    if cat_status and generated % 5 == 0:
                        cat_status["current_activity"] = f"Generating summaries... ({generated})"

    tasks = []
    for paper in papers:
        for model_info in TOURNAMENT_MODELS:
            tasks.append(gen_one(paper, model_info))

    if tasks:
        if cat_status:
            cat_status["current_activity"] = f"Generating summaries for {len(papers)} papers..."
        await asyncio.gather(*tasks)
        logger.info(f"[{category}] Generated {generated} new AI summaries")

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
            summary_source = settings.get("summary_source", "round_robin")

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
                "_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                "authors": 1, "arxiv_id": 1, "link": 1, "published": 1,
                "pdf_link": 1, "added_at": 1, "summaries": 1,
            }
            all_papers = await db.papers.find(
                {"categories.0": category}, _paper_fields
            ).to_list(5000)

            if len(all_papers) < 2:
                cat_status["current_activity"] = "Not enough papers"
                return {"status": "not_enough_papers"}

            # Filter out papers without summaries — they shouldn't participate yet
            papers_with_summaries = [p for p in all_papers if p.get("summaries")]
            papers_without = len(all_papers) - len(papers_with_summaries)
            if papers_without > 0:
                logger.info(f"[{category}] Excluding {papers_without} papers without summaries from matchmaking")
            all_papers = papers_with_summaries
            if len(all_papers) < 2:
                cat_status["current_activity"] = "Waiting for summaries"
                return {"status": "waiting_for_summaries", "papers_without_summaries": papers_without}

            # Download any missing PDFs for this category
            papers_missing_text = sum(1 for p in all_papers if not p.get("full_text"))
            if papers_missing_text > 0:
                dl_count = await _download_pending_pdfs(category=category)
                if dl_count > 0:
                    all_papers = await db.papers.find(
                        {"categories.0": category}, _paper_fields
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

            for i in range(0, len(pairs), parallel_agents):
                # Check if system was paused mid-round
                mid_settings = await get_settings()
                if mid_settings.get("paused", False):
                    logger.info(f"[{category}] System paused mid-round, stopping comparisons")
                    break

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
                    # Inject AI summary into paper dict based on admin setting
                    p1 = paper_lookup[p1_id]
                    p2 = paper_lookup[p2_id]
                    summary_model = _pick_summary_source(summary_source)
                    smk = _summary_model_key(summary_model)
                    p1_with_sum = {**p1, "ai_impact_summary": (p1.get("summaries") or {}).get(smk, "")}
                    p2_with_sum = {**p2, "ai_impact_summary": (p2.get("summaries") or {}).get(smk, "")}
                    tasks.append(compare_papers(p1_with_sum, p2_with_sum, prompt_config, content_mode="abstract_plus_summary"))

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
                        "content_mode": "abstract_plus_summary",
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

            # Store ranking snapshot for convergence tracking
            if completed > 0:
                await _store_ranking_snapshot(category)

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
    2. Top-K cross-matches after rankings stabilize
    Repeat pairs only after all goals are met.
    """
    from services.ranking import wilson_margin_pct

    paper_ids = [p["id"] for p in papers]
    if len(paper_ids) < 2:
        return []

    ci_target = kwargs.get("ci_target", 10)
    ci_target_general = kwargs.get("ci_target_general", 15)
    calibration_pct = kwargs.get("calibration_ratio", 50)  # % of matches against established papers

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

    # Identify top-K papers
    all_ranked = sorted(paper_ids, key=lambda pid: wins.get(pid, 0) / max(comparisons.get(pid, 0), 1), reverse=True)
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
    needy_set = set(needy)
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
            # Pick an established (converged) opponent — anchors new paper to existing rankings
            for p2 in established:
                if p2 == p1 or not can_pair(p2):
                    continue
                pair_key = tuple(sorted([p1, p2]))
                novel = pair_key not in compared_pairs
                if novel:
                    best = p2
                    break
        
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
    if not needy:
        missing_topk = any(
            tuple(sorted([top_k_list[i], top_k_list[j]])) not in compared_pairs
            for i in range(len(top_k_list)) for j in range(i + 1, len(top_k_list))
        )
        if not missing_topk:
            all_sorted = sorted(paper_ids, key=lambda pid: comparisons[pid])
            for p1 in all_sorted:
                if len(pairs) >= max_pairs or not can_pair(p1):
                    continue
                for p2 in all_sorted:
                    if p2 == p1 or not can_pair(p2):
                        continue
                    if tuple(sorted([p1, p2])) in compared_pairs:
                        pairs.append((p1, p2))
                        round_count[p1] += 1
                        round_count[p2] += 1
                        break

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
