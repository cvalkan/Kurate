from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from collections import defaultdict
from datetime import datetime, timezone
import asyncio
import hmac
import math
import uuid
import random
import time as _time
import secrets as _secrets
from core.config import db, logger, DEFAULT_SETTINGS, DEFAULT_EVALUATION_PROMPT, CATEGORIES
from core.auth import verify_admin, get_settings, invalidate_settings_cache
from services.scheduler import run_fetch_cycle, run_comparison_round, get_scheduler_status, _get_cat_status, wake_scheduler
from services.arxiv import fetch_arxiv_papers
import routers.leaderboard as _lb_mod

def _get_lb_cache():
    """Get the current leaderboard cache. Uses module reference to always get the latest."""
    return _lb_mod._cache

from routers.validation_utils import collect_all

router = APIRouter(prefix="/api/admin")

# Per-category cache for admin endpoints (avoids hammering DB on rapid category switching)
_admin_cache = {}  # {(endpoint, category): {"data": ..., "ts": float}}
_ADMIN_CACHE_TTL = 300  # 5 min — timeseries is expensive (70s+ cold), data changes slowly
_ADMIN_CACHE_MAX = 50  # Max cached entries


def _get_admin_cached(key: str, category: str):
    entry = _admin_cache.get((key, category))
    if entry and _time.time() - entry["ts"] < _ADMIN_CACHE_TTL:
        return entry["data"]
    return None


def _set_admin_cached(key: str, category: str, data):
    if len(_admin_cache) >= _ADMIN_CACHE_MAX:
        oldest_key = min(_admin_cache, key=lambda k: _admin_cache[k]["ts"])
        del _admin_cache[oldest_key]
    _admin_cache[(key, category)] = {"data": data, "ts": _time.time()}


def _invalidate_admin_cache(category: str = None):
    """Invalidate admin cache for a category (or all if None)."""
    if category:
        keys_to_remove = [k for k in _admin_cache if k[1] == category]
    else:
        keys_to_remove = list(_admin_cache.keys())
    for k in keys_to_remove:
        _admin_cache.pop(k, None)


class AdminLogin(BaseModel):
    password: str


class SettingsUpdate(BaseModel):
    fetch_interval_hours: Optional[int] = None
    max_papers_per_fetch: Optional[int] = None
    parallel_agents: Optional[int] = None
    parallel_categories: Optional[int] = None
    ranking_method: Optional[str] = None  # reg_wr, bt, trueskill
    max_new_matches_per_round: Optional[int] = None
    ci_target: Optional[int] = None
    ci_target_general: Optional[int] = None
    calibration_ratio: Optional[int] = None
    summary_source: Optional[str] = None
    paused: Optional[bool] = None
    admin_password: Optional[str] = None
    show_rating_column: Optional[bool] = None
    show_gap_column: Optional[bool] = None
    congrats_per_week: Optional[int] = None


class PromptUpdate(BaseModel):
    system_prompt: str
    user_prompt: str


# Admin session tokens - stored in MongoDB for persistence across restarts/pods
async def _get_admin_sessions():
    """Get all valid admin session tokens from DB."""
    doc = await db.admin_sessions.find_one({"key": "sessions"})
    if not doc:
        return set()
    return set(doc.get("tokens", []))


async def _add_admin_session(token: str):
    """Add a new admin session token to DB."""
    await db.admin_sessions.update_one(
        {"key": "sessions"},
        {"$addToSet": {"tokens": token}},
        upsert=True,
    )


async def _is_valid_session(token: str) -> bool:
    """Check if a token exists in the admin sessions."""
    doc = await db.admin_sessions.find_one({"key": "sessions", "tokens": token})
    return doc is not None


@router.post("/login")
async def admin_login(body: AdminLogin, request: Request):
    settings = await get_settings()
    if not hmac.compare_digest(body.password, settings.get("admin_password", DEFAULT_SETTINGS["admin_password"])):
        raise HTTPException(status_code=403, detail="Invalid password")
    token = f"adm_{_secrets.token_urlsafe(32)}"
    await _add_admin_session(token)
    return {"success": True, "token": token}


@router.get("/settings", dependencies=[Depends(verify_admin)])
async def get_admin_settings():
    settings = await get_settings()
    settings.pop("_id", None)
    settings.pop("admin_password", None)
    return {"settings": settings}


@router.put("/settings", dependencies=[Depends(verify_admin)])
async def update_settings(update: SettingsUpdate):
    update_dict = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")

    await db.settings.update_one(
        {"key": "global"},
        {"$set": update_dict},
        upsert=True,
    )
    invalidate_settings_cache()
    _invalidate_admin_cache()  # Settings change affects progress calculations
    logger.info(f"Admin updated settings: {list(update_dict.keys())}")
    return {"success": True, "updated": list(update_dict.keys())}


class FetchRequest(BaseModel):
    category: str = "cs.RO"


# In-memory tracker for background fetch tasks
_fetch_tasks: dict = {}  # {category: {"status": "running"|"completed"|"failed", "started_at": str, "result": dict|None, "error": str|None}}


async def _run_fetch_in_background(category: str):
    """Wrapper that runs fetch cycle and records result."""
    try:
        result = await run_fetch_cycle(category=category, force=True)
        _fetch_tasks[category] = {
            "status": "completed",
            "started_at": _fetch_tasks[category]["started_at"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Background fetch failed for {category}: {e}")
        _fetch_tasks[category] = {
            "status": "failed",
            "started_at": _fetch_tasks[category]["started_at"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": None,
            "error": str(e),
        }
    finally:
        _invalidate_admin_cache(category)


@router.post("/fetch", dependencies=[Depends(verify_admin)])
async def trigger_fetch(body: FetchRequest = FetchRequest()):
    # Check if a fetch is already running for this category
    existing = _fetch_tasks.get(body.category)
    if existing and existing["status"] == "running":
        return {"status": "already_running", "started_at": existing["started_at"]}

    # Mark as running and launch background task
    _fetch_tasks[body.category] = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }
    asyncio.create_task(_run_fetch_in_background(body.category))
    wake_scheduler()
    return {"status": "accepted", "message": f"Fetch & generate task started for {body.category}"}


@router.get("/fetch-status/{category}", dependencies=[Depends(verify_admin)])
async def get_fetch_status(category: str):
    """Poll this endpoint to check the status of a background fetch task."""
    task = _fetch_tasks.get(category)
    if not task:
        return {"status": "no_task", "message": "No fetch task has been run for this category."}
    return task


@router.post("/toggle-pause", dependencies=[Depends(verify_admin)])
async def toggle_pause():
    settings = await get_settings()
    new_state = not settings.get("paused", False)
    await db.settings.update_one({"key": "global"}, {"$set": {"paused": new_state}}, upsert=True)
    invalidate_settings_cache()
    _invalidate_admin_cache()  # Global pause affects all categories
    if new_state:
        # Immediately stop any running summary generation
        from services.scheduler import stop_summary_generation
        stop_summary_generation()
    else:
        wake_scheduler()  # Wake immediately on unpause
    return {"paused": new_state}


class ManualCompareRequest(BaseModel):
    num_matches: int = 50
    category: str = "cs.RO"


@router.post("/compare", dependencies=[Depends(verify_admin)])
async def trigger_comparison(body: ManualCompareRequest = ManualCompareRequest()):
    num = min(max(body.num_matches, 1), 500)
    asyncio.create_task(run_comparison_round(max_pairs_override=num, category=body.category))
    return {"status": "started", "num_matches": num, "category": body.category}


def _resolve_last_fetch(settings: dict, category: str):
    """Resolve last_fetch_at for a category, handling both flat and nested MongoDB keys."""
    # Try flat key (newer format: last_fetch_at_cs_RO)
    flat_key = f"last_fetch_at_{category.replace('.', '_')}"
    val = settings.get(flat_key)
    if val and isinstance(val, str):
        return val
    # Try nested key (older MongoDB dot-notation created: last_fetch_at_cs → {RO: value})
    parts = category.split(".")
    if len(parts) == 2:
        nested = settings.get(f"last_fetch_at_{parts[0]}")
        if isinstance(nested, dict):
            val = nested.get(parts[1])
            if val and isinstance(val, str):
                return val
    # Fallback to global
    return settings.get("last_fetch_at")


@router.get("/check-new-papers", dependencies=[Depends(verify_admin)])
async def check_new_papers(category: str = "cs.RO"):
    """Count how many new papers are available since last fetch by querying the source."""
    settings = await get_settings()
    last_fetch = _resolve_last_fetch(settings, category)

    if category.startswith("chemrxiv."):
        from services.chemrxiv import SEED_FILE
        import json
        if SEED_FILE.exists():
            with open(SEED_FILE) as f:
                seeds = json.load(f)
            seeds = [s for s in seeds if category in s.get("categories", [])]
            existing = await db.papers.count_documents({"categories.0": category})
            return {"available": max(0, len(seeds) - existing), "source": "chemrxiv_seed", "category": category, "last_fetch": last_fetch}
        return {"available": 0, "source": "chemrxiv_seed", "category": category, "last_fetch": last_fetch}
    else:
        # For arXiv: query the API to get an accurate count of new papers
        try:
            date_from = last_fetch[:10] if last_fetch else None
            papers = await fetch_arxiv_papers(category=category, max_results=200, date_from=date_from)
            primary = [p for p in papers if p.get("categories", [None])[0] == category]
            if primary:
                arxiv_ids = [p["arxiv_id"] for p in primary]
                existing = await db.papers.find({"arxiv_id": {"$in": arxiv_ids}}, {"_id": 0, "arxiv_id": 1}).to_list(500)
                existing_ids = {e["arxiv_id"] for e in existing}
                new_count = sum(1 for p in primary if p["arxiv_id"] not in existing_ids)
            else:
                new_count = 0
            return {"available": new_count, "source": "arxiv_query", "category": category, "last_fetch": last_fetch}
        except Exception as e:
            logger.warning(f"Failed to query arXiv for {category}: {e}")
            # Fallback to estimate
            if last_fetch:
                hours_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last_fetch)).total_seconds() / 3600
                est = int(hours_since * 2)
            else:
                est = 0
            return {"available": est, "source": "arxiv_estimate", "category": category, "last_fetch": last_fetch}


class GenerateSummariesRequest(BaseModel):
    category: str = None  # None = all categories


@router.post("/generate-summaries", dependencies=[Depends(verify_admin)])
async def trigger_summary_generation(body: GenerateSummariesRequest = GenerateSummariesRequest()):
    """Manually trigger AI impact summary generation for papers in completed tournaments.
    
    Summaries are only generated for categories where the tournament has met all goals.
    """
    from services.scheduler import _generate_pending_summaries, _check_goals_met
    
    if not body.category:
        return {
            "status": "error",
            "error": "Category is required. Summaries are generated per-category when tournament goals are met."
        }
    
    # Check if tournament goals are met
    goals_met = await _check_goals_met(category=body.category)
    
    if not goals_met:
        # Count papers and return info
        query = {"$or": [{"impact_summary": {"$exists": False}}, {"impact_summary": None}], "categories.0": body.category}
        pending_count = await db.papers.count_documents(query)
        return {
            "status": "waiting",
            "category": body.category,
            "papers_pending": pending_count,
            "note": "Tournament goals not yet met. Summaries will be generated automatically when the tournament completes."
        }
    
    # Goals met - count papers needing summaries
    query = {"$or": [{"impact_summary": {"$exists": False}}, {"impact_summary": None}], "categories.0": body.category}
    pending_count = await db.papers.count_documents(query)
    
    if pending_count == 0:
        return {
            "status": "complete",
            "category": body.category,
            "papers_pending": 0,
            "note": "All papers in this category already have summaries."
        }
    
    # Run in background
    asyncio.create_task(_generate_pending_summaries(category=body.category))
    
    return {
        "status": "started",
        "category": body.category,
        "papers_pending": pending_count,
        "note": "Tournament goals met. Generating summaries using round-robin across GPT-5.2, Claude Opus, and Gemini Pro."
    }


@router.get("/summary-stats", dependencies=[Depends(verify_admin)])
async def get_summary_stats(category: str = None):
    """Get statistics about AI impact summary generation (both legacy and pre-generated)."""
    query_base = {}
    if category:
        query_base["categories.0"] = category

    # Legacy summaries
    legacy_with = await db.papers.count_documents({**query_base, "impact_summary": {"$exists": True, "$ne": None}})

    # Pre-generated summaries (new architecture)
    pregen_with = await db.papers.count_documents({**query_base, "summaries": {"$exists": True, "$ne": None}})
    total = await db.papers.count_documents(query_base)
    without_pregen = total - pregen_with

    return {
        "with_summary": legacy_with,
        "with_pregen_summaries": pregen_with,
        "without_pregen_summaries": without_pregen,
        "total": total,
        "pregen_coverage_rate": round(pregen_with / max(total, 1) * 100, 1),
        "legacy_coverage_rate": round(legacy_with / max(total, 1) * 100, 1),
        "category": category,
    }


class BackfillSummariesRequest(BaseModel):
    category: str = None  # None = all categories


@router.post("/backfill-summaries", dependencies=[Depends(verify_admin)])
async def trigger_backfill_summaries(body: BackfillSummariesRequest = BackfillSummariesRequest()):
    """Backfill pre-generated AI summaries (3 models) for existing papers.
    
    This generates summaries from Claude, Gemini, and GPT for papers that don't have them yet.
    Runs in background with force=True (ignores pause state). Papers must have full_text available.
    """
    from services.scheduler import _generate_paper_summaries, get_summary_gen_progress

    # Check if already running
    progress = get_summary_gen_progress(body.category)
    if progress.get("running"):
        return {"status": "already_running", "progress": progress}

    query = {"full_text": {"$ne": None}}
    if body.category:
        query["categories.0"] = body.category

    # Count papers needing summaries
    all_papers = await collect_all(db.papers.find(
        query, {"_id": 0, "id": 1, "summaries": 1}
    ))

    from services.scheduler import _summary_model_key, _SUMMARY_GENERATION_MODELS
    model_keys = [_summary_model_key(m) for m in _SUMMARY_GENERATION_MODELS]

    needs_work = 0
    for p in all_papers:
        from services.scheduler import _get_paper_summary
        missing = [mk for mk in model_keys if not _get_paper_summary(p, mk)]
        if missing:
            needs_work += 1

    if needs_work == 0:
        return {
            "status": "complete",
            "category": body.category,
            "papers_with_text": len(all_papers),
            "papers_needing_summaries": 0,
            "note": "All papers already have pre-generated summaries from all 3 models.",
        }

    # Run in background with force=True to ignore pause state
    asyncio.create_task(_generate_paper_summaries(category=body.category, force=True))

    return {
        "status": "started",
        "category": body.category,
        "papers_with_text": len(all_papers),
        "papers_needing_summaries": needs_work,
        "total_summaries_to_generate": needs_work * 3,
        "note": f"Generating 3 AI summaries per paper for {needs_work} papers in background (force mode).",
    }


@router.get("/summary-gen-progress", dependencies=[Depends(verify_admin)])
async def get_summary_generation_progress(category: str = "cs.RO"):
    """Get real-time progress of ongoing summary generation."""
    from services.scheduler import get_summary_gen_progress

    progress = get_summary_gen_progress(category)

    # Also get current DB counts for context
    total_papers = await db.papers.count_documents({"categories.0": category})
    with_text = await db.papers.count_documents({"categories.0": category, "full_text": {"$ne": None}})
    with_summaries = await db.papers.count_documents({"categories.0": category, "summaries": {"$exists": True, "$ne": {}}})

    return {
        **progress,
        "category": category,
        "db_total_papers": total_papers,
        "db_papers_with_text": with_text,
        "db_papers_with_summaries": with_summaries,
        "db_papers_needing_summaries": with_text - with_summaries,
    }


@router.get("/status", dependencies=[Depends(verify_admin)])
async def get_admin_status(category: str = "cs.RO"):
    cached = _get_admin_cached("status", category)
    if cached:
        return cached

    lb_cache = _get_lb_cache()

    # All counts — from DB rankings + scheduler
    cat_scheduler = _get_cat_status(category)
    total_papers = await db.rankings.count_documents({"category": category})
    sched_papers = cat_scheduler.get("papers_count", 0)
    sched_papers_total = cat_scheduler.get("papers_total", 0)
    if not total_papers:
        total_papers = sched_papers
    total_matches = await db.matches.count_documents(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}}
    )
    sched_matches = cat_scheduler.get("matches_count", 0)
    total_matches = max(total_matches, sched_matches)
    failed_matches = lb_cache.get("_failed_by_cat", {}).get(category, 0)

    # Unranked from rankings DB
    ranked_count = await db.rankings.count_documents({"category": category, "comparisons": {"$gt": 0}})
    unranked = total_papers - ranked_count

    # Recent matches from DB
    cat_matches_sorted = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "reasoning": 1, "created_at": 1, "model_used": 1}
    ).sort("created_at", -1).limit(10).to_list(10)

    # Paper titles from rankings DB
    paper_ids_needed = set()
    for m in cat_matches_sorted:
        paper_ids_needed.update([m["paper1_id"], m["paper2_id"], m.get("winner_id", "")])
    paper_ids_needed.discard("")
    paper_titles = {}
    async for r in db.rankings.find({"paper_id": {"$in": list(paper_ids_needed)}}, {"_id": 0, "paper_id": 1, "title": 1}):
        paper_titles[r["paper_id"]] = r["title"]

    enriched_recent = []
    for m in cat_matches_sorted:
        winner_id = m.get("winner_id", "")
        loser_id = m["paper2_id"] if winner_id == m["paper1_id"] else m["paper1_id"]
        enriched_recent.append({
            "id": m.get("id", ""),
            "paper1_title": paper_titles.get(m["paper1_id"], "Unknown"),
            "paper2_title": paper_titles.get(m["paper2_id"], "Unknown"),
            "winner_title": paper_titles.get(winner_id, "Unknown"),
            "loser_title": paper_titles.get(loser_id, "Unknown"),
            "reasoning": m.get("reasoning", ""),
            "model_used": m.get("model_used", {}),
            "created_at": m.get("created_at", ""),
        })

    # Resolve last_fetch_at from settings if scheduler doesn't have it
    sched_last_fetch = cat_scheduler.get("last_fetch_at")
    if not sched_last_fetch:
        settings = await get_settings()
        sched_last_fetch = _resolve_last_fetch(settings, category)
        cat_scheduler["last_fetch_at"] = sched_last_fetch

    result = {
        "total_papers": total_papers,
        "papers_total_fetched": sched_papers_total,
        "total_matches": total_matches,
        "failed_matches": failed_matches,
        "unranked_papers": unranked,
        "category": category,
        "scheduler": cat_scheduler,
        "recent_matches": enriched_recent,
    }
    _set_admin_cached("status", category, result)
    return result


@router.get("/progress", dependencies=[Depends(verify_admin)])
async def get_progress_estimate(category: str = "cs.RO"):
    """Triple-goal progress — served from pre-computed leaderboard cache."""
    # Check if summary generation is running — skip cache if so for real-time updates
    from services.scheduler import get_summary_gen_progress
    summary_gen = get_summary_gen_progress(category)
    is_gen_running = summary_gen.get("running", False)

    if not is_gen_running:
        cached = _get_admin_cached("progress", category)
        if cached:
            return cached

    settings = await get_settings()
    global_paused = settings.get("paused", False)

    # Live tournament pause status (single fast query)
    tid = f"cat={category}|mode=standard"
    tournament_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "status": 1, "fetch_paused": 1, "compare_paused": 1})
    tournament_paused = tournament_doc.get("status") == "paused" if tournament_doc else False
    fetch_paused = bool(tournament_doc.get("fetch_paused")) if tournament_doc else False
    compare_paused = bool(tournament_doc.get("compare_paused")) if tournament_doc else False
    is_paused = global_paused or tournament_paused

    # Use pre-computed progress from leaderboard background cache
    lb_cache = _get_lb_cache()
    precomputed = lb_cache.get("_progress", {}).get(category)
    if precomputed:
        realtime_summaries = precomputed.get("total_papers", 0)  # from rankings count
        # If summary gen is running, get fresh count from DB
        if is_gen_running:
            realtime_summaries = await db.papers.count_documents(
                {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}}
            )
        result = {
            **precomputed,
            "paused": is_paused,
            "global_paused": global_paused,
            "tournament_paused": bool(tournament_paused),
            "fetch_paused": fetch_paused,
            "compare_paused": compare_paused,
            "summary_coverage": {
                "with_summaries": realtime_summaries,
            },
            "summary_gen_progress": summary_gen if is_gen_running else None,
        }
        if not is_gen_running:
            _set_admin_cached("progress", category, result)
        return result

    # Fallback: compute from DB (only during cold start before leaderboard cache is ready)
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 10)
    ci_target_general = settings.get("ci_target_general", 15)
    parallel_agents = settings.get("parallel_agents", 5)
    parallel_categories = settings.get("parallel_categories", 2)

    direct_papers = await collect_all(db.papers.find(
        {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}},
        {"_id": 0, "id": 1}
    ))
    all_paper_ids = [p["id"] for p in direct_papers]

    raw_matches = await collect_all(db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ))

    total_papers = len(all_paper_ids)
    if total_papers == 0:
        result = {
            "total_papers": 0, "goals_met": True, "paused": is_paused,
            "global_paused": global_paused, "tournament_paused": bool(tournament_paused),
            "fetch_paused": fetch_paused, "compare_paused": compare_paused,
            "category": category,
        }
        _set_admin_cached("progress", category, result)
        return result

    pid_set = set(all_paper_ids)
    paper_match_count = {pid: 0 for pid in all_paper_ids}
    paper_wins = {pid: 0 for pid in all_paper_ids}
    compared_pairs = set()

    for m in raw_matches:
        p1, p2 = m["paper1_id"], m["paper2_id"]
        if p1 in pid_set and p2 in pid_set:
            paper_match_count[p1] += 1
            paper_match_count[p2] += 1
            compared_pairs.add(tuple(sorted([p1, p2])))
            w = m.get("winner_id")
            if w and w in paper_wins:
                paper_wins[w] += 1

    # Identify top-K papers
    from services.ranking import wilson_margin_pct
    sorted_papers = sorted(
        all_paper_ids,
        key=lambda pid: paper_wins.get(pid, 0) / max(paper_match_count.get(pid, 0), 1),
        reverse=True,
    )
    top_k_ids = set(sorted_papers[:min(top_k, total_papers)])
    top_k_list = sorted_papers[:min(top_k, total_papers)]

    # Goal 1: All non-top-K papers CI ≤ ci_target_general
    general_converged = 0
    general_total = 0
    general_additional = 0
    widest_general = 0.0
    general_margins = []
    for pid in all_paper_ids:
        if pid in top_k_ids:
            continue
        general_total += 1
        n = paper_match_count.get(pid, 0)
        w = paper_wins.get(pid, 0)
        margin = wilson_margin_pct(w, n)
        general_margins.append(margin)
        if margin <= ci_target_general:
            general_converged += 1
        else:
            if n >= 2:
                n_needed = n * (margin / ci_target_general) ** 2
                general_additional += max(3, int(n_needed) - n)
            else:
                general_additional += 30
        if margin > widest_general:
            widest_general = margin

    goal1_met = general_converged == general_total if general_total > 0 else True
    median_general = sorted(general_margins)[len(general_margins) // 2] if general_margins else 0.0
    matches_for_goal1 = 0 if goal1_met else max(0, int(general_additional * 0.6))

    # Goal 2: All top-K papers CI ≤ ci_target (tighter)
    topk_converged = 0
    topk_total = len(top_k_ids)
    topk_additional = 0
    widest_topk = 0.0
    topk_margins = []
    for pid in top_k_list:
        n = paper_match_count.get(pid, 0)
        w = paper_wins.get(pid, 0)
        margin = wilson_margin_pct(w, n)
        topk_margins.append(margin)
        if margin <= ci_target:
            topk_converged += 1
        else:
            if n >= 2:
                n_needed = n * (margin / ci_target) ** 2
                topk_additional += max(3, int(n_needed) - n)
            else:
                topk_additional += 40
        if margin > widest_topk:
            widest_topk = margin

    goal2_met = topk_converged == topk_total if topk_total > 0 else True
    median_topk = sorted(topk_margins)[len(topk_margins) // 2] if topk_margins else 0.0
    matches_for_goal2 = 0 if goal2_met else max(0, int(topk_additional * 0.6))

    # Goal 3: Cross-matches among top-K papers
    topk_total_pairs = len(top_k_list) * (len(top_k_list) - 1) // 2
    topk_matched_pairs = 0
    for i in range(len(top_k_list)):
        for j in range(i + 1, len(top_k_list)):
            pair = tuple(sorted([top_k_list[i], top_k_list[j]]))
            if pair in compared_pairs:
                topk_matched_pairs += 1
    matches_for_goal3 = topk_total_pairs - topk_matched_pairs
    goal3_met = bool(topk_matched_pairs == topk_total_pairs)

    total_est = max(matches_for_goal1, matches_for_goal2) + matches_for_goal3
    seconds_per_match = 10.0 / max(parallel_agents, 1)
    est_minutes = max(0, round(total_est * seconds_per_match / 60))

    cat_matches_done = sum(paper_match_count.values()) // 2
    cat_papers_with_pdf = await db.papers.count_documents({"categories.0": category, "full_text": {"$ne": None}})
    cat_total_in_db = await db.papers.count_documents({"categories.0": category})

    result = {
        "total_papers": total_papers,
        "total_in_db": cat_total_in_db,
        "total_matches": cat_matches_done,
        "papers_with_pdf": cat_papers_with_pdf,
        "paused": is_paused,
        "global_paused": global_paused,
        "tournament_paused": bool(tournament_paused),
        "fetch_paused": fetch_paused,
        "compare_paused": compare_paused,
        "category": category,
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
            "label": f"Top-{len(top_k_list)} cross-matches",
            "done": int(topk_matched_pairs),
            "total": int(topk_total_pairs),
        },
        "estimated_matches_remaining": int(total_est),
        "estimated_minutes": int(est_minutes),
        "summary_coverage": {
            "with_summaries": total_papers,
        },
    }
    _set_admin_cached("progress", category, result)
    return result


def _elo_ci(wins, comparisons):
    if comparisons < 2:
        return 999
    p = max(0.02, min(0.98, (wins + 0.5) / (comparisons + 1.0)))
    se_logit = 1.0 / math.sqrt((comparisons + 1.0) * p * (1 - p))
    se_elo = (400 / math.log(10)) * se_logit
    return 1.96 * se_elo


@router.get("/stats", dependencies=[Depends(verify_admin)])
async def get_usage_stats(category: str = None):
    """Token usage by model with cost estimation, optionally filtered by category."""
    cache_cat = category or "__all__"
    cached = _get_admin_cached("stats", cache_cat)
    if cached:
        return cached

    lb_cache = _get_lb_cache()

    # Compute model stats from DB matches
    match_query = {"completed": True, "failed": {"$ne": True}, "model_used": {"$exists": True}, "mode": {"$exists": False}}
    if category:
        match_query["primary_category"] = category
    model_stats = {}
    async for m in db.matches.find(match_query, {"_id": 0, "model_used": 1, "tokens": 1}):
        mu = m.get("model_used", {})
        if not mu:
            continue
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        if key not in model_stats:
            model_stats[key] = {"matches": 0, "input_tokens": 0, "output_tokens": 0}
        model_stats[key]["matches"] += 1
        tokens = m.get("tokens", {})
        model_stats[key]["input_tokens"] += tokens.get("input_est", 0)
        model_stats[key]["output_tokens"] += tokens.get("output_est", 0)

    # Calculate cost per model
    total_cost = 0.0
    for key, stats in model_stats.items():
        pricing = MODEL_PRICING.get(key, {"input": 2.0, "output": 10.0})
        cost_in = (stats["input_tokens"] / 1_000_000) * pricing["input"]
        cost_out = (stats["output_tokens"] / 1_000_000) * pricing["output"]
        stats["cost_input"] = round(cost_in, 4)
        stats["cost_output"] = round(cost_out, 4)
        stats["cost_total"] = round(cost_in + cost_out, 4)
        total_cost += cost_in + cost_out

    total_input = sum(s["input_tokens"] for s in model_stats.values())
    total_output = sum(s["output_tokens"] for s in model_stats.values())

    # Storage from pre-computed background cache
    storage_cache = lb_cache.get("_storage", {})
    if category:
        total_chars = storage_cache.get("chars_by_cat", {}).get(category, 0)
        papers_with_text = lb_cache.get("_pdf_by_cat", {}).get(category, 0)
        total_papers = await db.rankings.count_documents({"category": category})
    else:
        total_chars = storage_cache.get("total_chars", 0)
        papers_with_text = storage_cache.get("total_with_text", 0)
        total_papers = await db.rankings.count_documents({})

    # --- Summary generation stats from pre-computed cache ---
    precomputed_summary = lb_cache.get("_summary_stats", {}).get(cache_cat, {})
    summary_stats = {}
    papers_with_summaries = precomputed_summary.get("papers_with_summaries", 0)
    papers_with_all_3 = precomputed_summary.get("papers_with_all_3", 0)
    summary_total_input = 0
    summary_total_output = 0
    summary_total_thinking = 0
    summary_total_cost = 0.0

    for mk, info in precomputed_summary.get("models", {}).items():
        count = info["summaries"]
        tracked_count = info.get("tracked_count", 0)
        tracked_input = info.get("tracked_input", 0)
        tracked_output = info.get("tracked_output", 0)
        tracked_thinking = info.get("tracked_thinking", 0)

        # Use actual tracked tokens if available, extrapolate for untracked summaries
        if tracked_count > 0:
            avg_input = tracked_input / tracked_count
            avg_output = tracked_output / tracked_count
            avg_thinking = tracked_thinking / tracked_count
            input_tokens = int(avg_input * count)
            output_tokens = int(avg_output * count)
            thinking_tokens = int(avg_thinking * count)
        else:
            # Fallback: estimate from output text length (~1700 output tokens avg, ~400 input for abstract-only)
            input_tokens = count * 750
            output_tokens = count * 1700
            # Estimate thinking tokens for Claude Thinking models
            thinking_tokens = count * 4000 if "thinking" in mk else 0

        # Determine provider for pricing
        provider = mk.split(":")[0] if ":" in mk else mk
        if "openai" in provider:
            pricing_key = "openai/gpt-5.2"
        elif "anthropic" in provider:
            pricing_key = f"anthropic/{mk.split(chr(58))[1]}" if ":" in mk else "anthropic/claude-opus-4-6"
        elif "gemini" in provider:
            pricing_key = "gemini/gemini-3-pro-preview"
        else:
            pricing_key = None

        cost = 0.0
        if pricing_key:
            pricing = MODEL_PRICING.get(pricing_key, {"input": 2.0, "output": 10.0})
            cost_in = (input_tokens / 1_000_000) * pricing["input"]
            cost_out = ((output_tokens + thinking_tokens) / 1_000_000) * pricing["output"]
            cost = cost_in + cost_out

        summary_stats[mk] = {
            "summaries": count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "tracked_count": tracked_count,
            "cost_total": round(cost, 4),
        }
        summary_total_input += input_tokens
        summary_total_output += output_tokens
        summary_total_thinking += thinking_tokens
        summary_total_cost += cost

    result = {
        "models": model_stats,
        "totals": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_matches": sum(s["matches"] for s in model_stats.values()),
            "total_cost": round(total_cost, 4),
        },
        "storage": {
            "papers_with_text": papers_with_text,
            "total_papers": total_papers,
            "total_chars": total_chars,
            "size_mb": round(total_chars / (1024 * 1024), 2),
        },
        "summaries": {
            "models": summary_stats,
            "papers_with_summaries": papers_with_summaries,
            "papers_with_all_3": papers_with_all_3,
            "total_papers": total_papers,
            "totals": {
                "input_tokens": summary_total_input,
                "output_tokens": summary_total_output,
                "total_tokens": summary_total_input + summary_total_output,
                "total_summaries": sum(s["summaries"] for s in summary_stats.values()),
                "total_cost": round(summary_total_cost, 4),
            },
        },
    }
    _set_admin_cached("stats", cache_cat, result)
    return result


@router.get("/prompt", dependencies=[Depends(verify_admin)])
async def get_evaluation_prompt():
    doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
    if doc:
        return {
            "system_prompt": doc.get("system_prompt", ""),
            "user_prompt": doc.get("user_prompt", ""),
        }
    # No prompt saved yet — save the default and return it
    await db.settings.update_one(
        {"key": "custom_prompt"},
        {"$set": {"key": "custom_prompt", **DEFAULT_EVALUATION_PROMPT}},
        upsert=True,
    )
    return DEFAULT_EVALUATION_PROMPT


@router.put("/prompt", dependencies=[Depends(verify_admin)])
async def update_evaluation_prompt(update: PromptUpdate):
    await db.settings.update_one(
        {"key": "custom_prompt"},
        {"$set": {
            "key": "custom_prompt",
            "system_prompt": update.system_prompt,
            "user_prompt": update.user_prompt,
        }},
        upsert=True,
    )
    return {"success": True}


from services.llm import IMPACT_ASSESSMENT_PROMPT as _IAP

DEFAULT_SUMMARY_PROMPT = {
    "system_prompt": _IAP["system_prompt"],
    "user_prompt": _IAP["user_prompt"],
}


@router.get("/summary-prompt", dependencies=[Depends(verify_admin)])
async def get_summary_prompt():
    doc = await db.settings.find_one({"key": "summary_prompt"}, {"_id": 0})
    if doc:
        return {
            "system_prompt": doc.get("system_prompt", ""),
            "user_prompt": doc.get("user_prompt", ""),
        }
    await db.settings.update_one(
        {"key": "summary_prompt"},
        {"$set": {"key": "summary_prompt", **DEFAULT_SUMMARY_PROMPT}},
        upsert=True,
    )
    return DEFAULT_SUMMARY_PROMPT


@router.put("/summary-prompt", dependencies=[Depends(verify_admin)])
async def update_summary_prompt(update: PromptUpdate):
    await db.settings.update_one(
        {"key": "summary_prompt"},
        {"$set": {
            "key": "summary_prompt",
            "system_prompt": update.system_prompt,
            "user_prompt": update.user_prompt,
        }},
        upsert=True,
    )
    return {"success": True}


# --- Prediction Experiment (Gap Score) ---

DEFAULT_PREDICTION_PROMPT = {
    "system_prompt": """You are predicting scientific consensus. Your task is NOT to evaluate the papers yourself, but to anticipate which paper the broader scientific community would consider more impactful.

Think about what most researchers in the field would say. Consider:
1. Which paper addresses a more widely recognized problem?
2. Which methodology would appeal to the mainstream research community?
3. Which results would generate more citations and follow-up work?
4. Which paper aligns better with current funding priorities and trends?

You MUST respond with valid JSON only:
{"winner": "paper1" or "paper2", "reasoning": "Explain why the scientific crowd would favor this paper (max 200 words)"}""",
    "user_prompt": """Predict which paper the scientific community would consider more impactful:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper would most researchers pick as more impactful? Respond with JSON only.""",
}


@router.get("/prediction-prompt", dependencies=[Depends(verify_admin)])
async def get_prediction_prompt():
    doc = await db.settings.find_one({"key": "prediction_prompt"}, {"_id": 0})
    if doc and doc.get("system_prompt"):
        return {
            "system_prompt": doc.get("system_prompt", ""),
            "user_prompt": doc.get("user_prompt", ""),
        }
    await db.settings.update_one(
        {"key": "prediction_prompt"},
        {"$set": {"key": "prediction_prompt", **DEFAULT_PREDICTION_PROMPT}},
        upsert=True,
    )
    return DEFAULT_PREDICTION_PROMPT


@router.put("/prediction-prompt", dependencies=[Depends(verify_admin)])
async def update_prediction_prompt(update: PromptUpdate):
    await db.settings.update_one(
        {"key": "prediction_prompt"},
        {"$set": {
            "key": "prediction_prompt",
            "system_prompt": update.system_prompt,
            "user_prompt": update.user_prompt,
        }},
        upsert=True,
    )
    return {"success": True}


class PredictionRunRequest(BaseModel):
    num_matches: int = 50
    category: str = "cs.RO"
    use_full_text: bool = False


@router.post("/run-prediction", dependencies=[Depends(verify_admin)])
async def run_prediction_tournament(body: PredictionRunRequest = PredictionRunRequest()):
    """Run prediction tournament with crowd-prediction prompt."""
    mode = "prediction-fulltext" if body.use_full_text else "prediction"
    asyncio.create_task(_run_prediction_round(body.category, min(max(body.num_matches, 1), 500), abstract_only=not body.use_full_text, mode=mode))
    return {"status": "started", "category": body.category, "num_matches": body.num_matches, "mode": mode}


async def _run_prediction_round(category: str, max_pairs: int, abstract_only: bool = True, mode: str = "prediction"):
    """Run a prediction comparison round."""
    from services.llm import compare_papers

    # Load prediction prompt
    prompt_doc = await db.settings.find_one({"key": "prediction_prompt"}, {"_id": 0})
    if not prompt_doc or not prompt_doc.get("system_prompt"):
        prompt_config = DEFAULT_PREDICTION_PROMPT
    else:
        prompt_config = {
            "system_prompt": prompt_doc["system_prompt"],
            "user_prompt": prompt_doc["user_prompt"],
        }

    # Load papers
    fields = {"_id": 0, "id": 1, "title": 1, "abstract": 1, "authors": 1, "arxiv_id": 1, "published": 1}
    if not abstract_only:
        fields["full_text"] = 1
    all_papers = await collect_all(db.papers.find(
        {"categories.0": category}, fields,
    ))

    if len(all_papers) < 2:
        logger.warning(f"Prediction: not enough papers for {category}")
        return

    # Get existing matches for this mode to avoid duplicates
    existing = await collect_all(db.matches.find(
        {"mode": mode, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ))

    cat_paper_ids = {p["id"] for p in all_papers}
    compared = set()
    for m in existing:
        if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids:
            compared.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Generate random pairs (simple uniform sampling)
    paper_ids = [p["id"] for p in all_papers]
    pairs = []
    attempts = 0
    while len(pairs) < max_pairs and attempts < max_pairs * 10:
        p1, p2 = random.sample(paper_ids, 2)
        key = tuple(sorted([p1, p2]))
        if key not in compared:
            pairs.append((p1, p2))
            compared.add(key)
        attempts += 1

    if not pairs:
        logger.info(f"Prediction: no new pairs for {category}")
        return

    paper_lookup = {p["id"]: p for p in all_papers}
    settings = await get_settings()
    parallel = min(max(settings.get("parallel_agents", 5), 1), 20)
    section_char_limit = settings.get("section_char_limit", 2000)  # Pre-fetch for batch
    completed = 0

    for i in range(0, len(pairs), parallel):
        batch = pairs[i:i + parallel]
        tasks = []
        presented = []
        for p1_id, p2_id in batch:
            if random.random() < 0.5:
                presented.append((p2_id, p1_id))
            else:
                presented.append((p1_id, p2_id))
        for p1_id, p2_id in presented:
            tasks.append(compare_papers(paper_lookup[p1_id], paper_lookup[p2_id], prompt_config, abstract_only=abstract_only, char_limit=section_char_limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (p1_id, p2_id), result in zip(presented, results):
            match_doc = {
                "id": str(uuid.uuid4()),
                "paper1_id": p1_id,
                "paper2_id": p2_id,
                "mode": mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if isinstance(result, Exception):
                match_doc["completed"] = False
                match_doc["failed"] = True
                match_doc["error"] = str(result)[:200]
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
        await asyncio.sleep(0.5)

    logger.info(f"Prediction round for {category}: {completed}/{len(pairs)} completed")


@router.get("/experiment-comparison", dependencies=[Depends(verify_admin)])
async def get_experiment_comparison(category: str = "cs.RO"):
    """Compare standard vs prediction rankings for the Gap Score experiment."""
    from services.ranking import compute_leaderboard_async

    # Load papers
    all_papers = await collect_all(db.papers.find(
        {"categories.0": category},
        {"_id": 0, "full_text": 0},
    ))

    if not all_papers:
        return {"papers": [], "category": category, "standard_matches": 0, "prediction_matches": 0}

    cat_paper_ids = {p["id"] for p in all_papers}

    # Load standard matches (no mode field or mode=standard)
    all_matches_raw = await collect_all(db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "mode": 1, "completed": 1, "failed": 1},
    ))

    standard_matches = [m for m in all_matches_raw
                        if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids
                        and not m.get("mode")]

    prediction_matches = [m for m in all_matches_raw
                          if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids
                          and m.get("mode") == "prediction"]

    prediction_ft_matches = [m for m in all_matches_raw
                             if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids
                             and m.get("mode") == "prediction-fulltext"]

    # Compute rankings for each mode (in thread pool to avoid blocking event loop)
    std_ranking, pred_ranking, pred_ft_ranking = await asyncio.gather(
        compute_leaderboard_async(all_papers, standard_matches),
        compute_leaderboard_async(all_papers, prediction_matches),
        compute_leaderboard_async(all_papers, prediction_ft_matches),
    )

    # Build lookup
    std_lookup = {p["id"]: p for p in std_ranking}
    pred_lookup = {p["id"]: p for p in pred_ranking}
    pred_ft_lookup = {p["id"]: p for p in pred_ft_ranking}

    # Merge into comparison table
    comparison = []
    for paper in all_papers:
        pid = paper["id"]
        std = std_lookup.get(pid, {})
        pred = pred_lookup.get(pid, {})
        pred_ft = pred_ft_lookup.get(pid, {})
        std_rank = std.get("rank", 999)
        pred_rank = pred.get("rank", 999)
        pred_ft_rank = pred_ft.get("rank", 999)
        comparison.append({
            "id": pid,
            "title": paper["title"],
            "authors": paper.get("authors", [])[:3],
            "arxiv_id": paper.get("arxiv_id", ""),
            "standard_rank": std_rank,
            "standard_score": std.get("score", 1200),
            "standard_win_rate": std.get("win_rate", 0),
            "standard_matches": std.get("comparisons", 0),
            "prediction_rank": pred_rank,
            "prediction_score": pred.get("score", 1200),
            "prediction_win_rate": pred.get("win_rate", 0),
            "prediction_matches": pred.get("comparisons", 0),
            "rank_delta": pred_rank - std_rank,
            "pred_ft_rank": pred_ft_rank,
            "pred_ft_score": pred_ft.get("score", 1200),
            "pred_ft_win_rate": pred_ft.get("win_rate", 0),
            "pred_ft_matches": pred_ft.get("comparisons", 0),
            "rank_delta_ft": pred_ft_rank - std_rank,
        })

    return {
        "papers": comparison,
        "category": category,
        "standard_matches": len(standard_matches),
        "prediction_matches": len(prediction_matches),
        "prediction_ft_matches": len(prediction_ft_matches),
    }


MODEL_PRICING = {
    "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
    "anthropic/claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "anthropic/claude-opus-4-6": {"input": 5.00, "output": 25.00},
    "gemini/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
}


_timeseries_refresh_lock = False
_timeseries_last_refresh = 0


@router.get("/timeseries", dependencies=[Depends(verify_admin)])
async def get_timeseries(category: Optional[str] = None):
    """Return daily time-series data for papers, matches, tokens, costs."""
    global _timeseries_refresh_lock, _timeseries_last_refresh
    cache_key = category or "__all__"
    cached = _get_admin_cached("timeseries", cache_key)
    if cached:
        return cached

    # Cold start: load from MongoDB to respond fast
    from core.cache import get_cached, set_cached
    mongo_key = f"admin_timeseries_{cache_key}"
    db_cached = await get_cached(mongo_key)
    if db_cached:
        _set_admin_cached("timeseries", cache_key, db_cached)
        # Background refresh at most once per hour, and only if not already running
        if not _timeseries_refresh_lock and _time.time() - _timeseries_last_refresh > 3600:
            _timeseries_refresh_lock = True
            async def _bg_refresh():
                global _timeseries_refresh_lock, _timeseries_last_refresh
                try:
                    await asyncio.sleep(2)  # Brief delay to not compete with the response
                    result = await _compute_timeseries(category)
                    _set_admin_cached("timeseries", cache_key, result)
                    await set_cached(mongo_key, result)
                    _timeseries_last_refresh = _time.time()
                finally:
                    _timeseries_refresh_lock = False
            asyncio.create_task(_bg_refresh())
        return db_cached

    # No cache at all: compute synchronously (only happens on very first deploy)
    result = await _compute_timeseries(category)
    _set_admin_cached("timeseries", cache_key, result)
    await set_cached(mongo_key, result)
    _timeseries_last_refresh = _time.time()
    return result


async def _compute_timeseries(category: Optional[str] = None):
    """Heavy timeseries computation — separated for caching."""
    # --- Papers by day ---
    paper_query = {}
    if category:
        paper_query["categories.0"] = category
    papers_daily = defaultdict(lambda: defaultdict(int))
    total_papers_count = 0
    async for p in db.papers.find(paper_query, {"_id": 0, "added_at": 1, "published": 1, "categories": 1}):
        total_papers_count += 1
        # Prefer added_at, fall back to published date
        added = p.get("added_at") or p.get("published") or ""
        if not added or len(added) < 10:
            continue
        day = added[:10]  # "YYYY-MM-DD"
        cats = p.get("categories") or []
        cat = cats[0] if cats else "unknown"
        papers_daily[day][cat] += 1
        papers_daily[day]["_total"] += 1

    # --- Matches by day + model stats ---
    match_query = {"completed": True, "failed": {"$ne": True}}
    if category:
        match_query["primary_category"] = category
    matches_daily = defaultdict(lambda: defaultdict(lambda: {
        "count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0
    }))
    # System-wide model breakdown (not per-category, always total)
    model_stats = {}

    async for m in db.matches.find(
        match_query,
        {"_id": 0, "created_at": 1, "primary_category": 1, "tokens": 1, "model_used": 1, "mode": 1},
    ):
        if m.get("mode"):
            continue  # Exclude experiment matches
        created = m.get("created_at") or ""
        if not created or len(created) < 10:
            continue
        day = created[:10]
        cat = m.get("primary_category") or "unknown"
        tokens = m.get("tokens") or {}
        inp = tokens.get("input_est", 0) or 0
        out = tokens.get("output_est", 0) or 0
        mu = m.get("model_used") or {}
        provider = mu.get("provider", "unknown")
        model = mu.get("model", "unknown")
        model_key = f"{provider}/{model}" if provider != "unknown" or model != "unknown" else "unknown"
        pricing = MODEL_PRICING.get(model_key, {"input": 2.0, "output": 10.0})
        cost = (inp / 1_000_000) * pricing["input"] + (out / 1_000_000) * pricing["output"]

        for key in [cat, "_total"]:
            bucket = matches_daily[day][key]
            bucket["count"] += 1
            bucket["input_tokens"] += inp
            bucket["output_tokens"] += out
            bucket["cost"] += cost

        # Accumulate per-model stats (system-wide, always unfiltered by category)
        if model_key != "unknown":
            if model_key not in model_stats:
                model_stats[model_key] = {"matches": 0, "input_tokens": 0, "output_tokens": 0}
            model_stats[model_key]["matches"] += 1
            model_stats[model_key]["input_tokens"] += inp
            model_stats[model_key]["output_tokens"] += out

    # --- Summary generation costs (estimated from paper summaries) ---
    summary_daily = defaultdict(lambda: defaultdict(lambda: {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}))
    async for p in db.papers.find(
        {"summaries": {"$exists": True, "$ne": None}},
        {"_id": 0, "summaries": 1, "full_text": 1, "abstract": 1, "added_at": 1, "categories": 1},
    ):
        sums = p.get("summaries") or {}
        if not sums:
            continue
        day = (p.get("added_at") or "")[:10]
        if not day:
            continue
        cat = (p.get("categories") or ["unknown"])[0]
        ft_len = len(p.get("full_text", "") or "")
        abs_len = len(p.get("abstract", "") or "")
        input_chars_per_call = min(ft_len, 40000) + min(abs_len, 1500) + 500

        for mk, text in sums.items():
            if not isinstance(text, str) or len(text) < 50:
                continue
            provider = mk.split(":")[0]
            model_name = mk.split(":")[-1].replace("_", ".")
            if "openai" in provider:
                pricing_key = "openai/gpt-5.2"
            elif "anthropic" in provider:
                pricing_key = f"anthropic/{mk.split(chr(58))[1]}" if ":" in mk else "anthropic/claude-opus-4-6"
            elif "gemini" in provider:
                pricing_key = "gemini/gemini-3-pro-preview"
            else:
                pricing_key = None

            inp_tok = input_chars_per_call // 4
            out_tok = len(text) // 4
            cost = 0.0
            if pricing_key:
                pr = MODEL_PRICING.get(pricing_key, {"input": 2.0, "output": 10.0})
                cost = (inp_tok / 1_000_000) * pr["input"] + (out_tok / 1_000_000) * pr["output"]

            for key in [cat, "_total"]:
                bucket = summary_daily[day][key]
                bucket["count"] += 1
                bucket["input_tokens"] += inp_tok
                bucket["output_tokens"] += out_tok
                bucket["cost"] += cost

    # Merge summary dates into all_dates and fill gaps with zeros
    raw_dates = sorted(set(list(papers_daily.keys()) + list(matches_daily.keys()) + list(summary_daily.keys())))
    settings_for_cats = await get_settings()
    all_cats = sorted(settings_for_cats.get("active_categories", list(CATEGORIES.keys())))

    # Generate continuous date range (no gaps)
    if raw_dates:
        from datetime import date as _date, timedelta as _td
        start = _date.fromisoformat(raw_dates[0])
        end = _date.fromisoformat(raw_dates[-1])
        all_dates = []
        cur = start
        while cur <= end:
            all_dates.append(cur.isoformat())
            cur += _td(days=1)
    else:
        all_dates = []

    # Build daily series
    series = []
    cum_papers = defaultdict(int)
    cum_matches = defaultdict(int)
    cum_tokens = defaultdict(int)
    cum_cost = defaultdict(float)

    for day in all_dates:
        entry = {"date": day}

        # Papers
        p_total = papers_daily[day].get("_total", 0)
        cum_papers["_total"] += p_total
        entry["papers_daily"] = p_total
        entry["papers_cumulative"] = cum_papers["_total"]

        # Per-category papers
        for cat in all_cats:
            p_cat = papers_daily[day].get(cat, 0)
            cum_papers[cat] += p_cat
            entry[f"papers_daily_{cat}"] = p_cat
            entry[f"papers_cumulative_{cat}"] = cum_papers[cat]

        # Matches + Summaries combined in tokens/cost
        m_data = matches_daily[day].get("_total", {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        s_data = summary_daily[day].get("_total", {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        cum_matches["_total"] += m_data["count"]
        day_tokens = m_data["input_tokens"] + m_data["output_tokens"] + s_data["input_tokens"] + s_data["output_tokens"]
        day_cost = m_data["cost"] + s_data["cost"]
        cum_tokens["_total"] += day_tokens
        cum_cost["_total"] += day_cost
        entry["matches_daily"] = m_data["count"]
        entry["matches_cumulative"] = cum_matches["_total"]
        entry["tokens_daily"] = day_tokens
        entry["tokens_cumulative"] = cum_tokens["_total"]
        entry["cost_daily"] = round(day_cost, 4)
        entry["cost_cumulative"] = round(cum_cost["_total"], 4)
        entry["input_tokens_daily"] = m_data["input_tokens"] + s_data["input_tokens"]
        entry["output_tokens_daily"] = m_data["output_tokens"] + s_data["output_tokens"]

        # Per-category matches + summaries
        for cat in all_cats:
            mc = matches_daily[day].get(cat, {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
            sc = summary_daily[day].get(cat, {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
            cum_matches[cat] += mc["count"]
            cat_day_tok = mc["input_tokens"] + mc["output_tokens"] + sc["input_tokens"] + sc["output_tokens"]
            cat_day_cost = mc["cost"] + sc["cost"]
            cum_tokens[cat] += cat_day_tok
            cum_cost[cat] += cat_day_cost
            entry[f"matches_daily_{cat}"] = mc["count"]
            entry[f"matches_cumulative_{cat}"] = cum_matches[cat]
            entry[f"tokens_daily_{cat}"] = cat_day_tok
            entry[f"tokens_cumulative_{cat}"] = cum_tokens[cat]
            entry[f"cost_daily_{cat}"] = round(cat_day_cost, 4)
            entry[f"cost_cumulative_{cat}"] = round(cum_cost[cat], 4)

        series.append(entry)

    # Compute per-model costs
    total_model_cost = 0.0
    for key, stats in model_stats.items():
        pricing = MODEL_PRICING.get(key, {"input": 2.0, "output": 10.0})
        cost_in = (stats["input_tokens"] / 1_000_000) * pricing["input"]
        cost_out = (stats["output_tokens"] / 1_000_000) * pricing["output"]
        stats["cost_input"] = round(cost_in, 4)
        stats["cost_output"] = round(cost_out, 4)
        stats["cost_total"] = round(cost_in + cost_out, 4)
        total_model_cost += cost_in + cost_out

    # Compute total summary tokens/cost for the totals
    total_summary_tokens = sum(
        summary_daily[day]["_total"]["input_tokens"] + summary_daily[day]["_total"]["output_tokens"]
        for day in summary_daily
    )
    total_summary_cost = sum(summary_daily[day]["_total"]["cost"] for day in summary_daily)

    return {
        "series": series,
        "categories": all_cats,
        "totals": {
            "papers": max(cum_papers["_total"], total_papers_count),
            "matches": cum_matches["_total"],
            "tokens": cum_tokens["_total"],
            "input_tokens": sum(s.get("input_tokens", 0) for s in model_stats.values()),
            "output_tokens": sum(s.get("output_tokens", 0) for s in model_stats.values()),
            "cost": round(cum_cost["_total"], 4),
            "match_cost": round(cum_cost["_total"] - total_summary_cost, 4),
            "summary_cost": round(total_summary_cost, 4),
        },
        "models": model_stats,
    }


@router.get("/tournaments", dependencies=[Depends(verify_admin)])
async def get_tournaments():
    tournaments = await db.tournaments.find({}, {"_id": 0}).sort("category", 1).to_list(500)
    return {"tournaments": tournaments}


@router.post("/tournaments/{tournament_id}/status", dependencies=[Depends(verify_admin)])
async def update_tournament_status(tournament_id: str, request: Request):
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("active", "paused"):
        raise HTTPException(400, "Status must be 'active' or 'paused'")

    result = await db.tournaments.update_one(
        {"tournament_id": tournament_id},
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Tournament not found")

    # On resume: immediately start fetching papers + tournament
    if new_status == "active":
        # Get the category from the tournament
        tournament = await db.tournaments.find_one(
            {"tournament_id": tournament_id}, {"_id": 0, "category": 1}
        )
        if tournament:
            cat = tournament["category"]
            paper_count = await db.papers.count_documents({"categories.0": cat})
            # If few/no papers, kick off an immediate fetch
            if paper_count < 10:
                import asyncio
                asyncio.create_task(run_fetch_cycle(category=cat))
                logger.info(f"Resume triggered immediate paper fetch for {cat} ({paper_count} papers)")
        wake_scheduler()  # Wake immediately so comparisons start

    # Invalidate cache for the affected category
    _invalidate_admin_cache()

@router.post("/tournaments/{tournament_id}/toggle-fetch", dependencies=[Depends(verify_admin)])
async def toggle_tournament_fetch(tournament_id: str):
    """Toggle fetch (paper ingestion) pause for a tournament."""
    doc = await db.tournaments.find_one({"tournament_id": tournament_id}, {"_id": 0, "tournament_id": 1, "fetch_paused": 1})
    if doc is None:
        raise HTTPException(404, "Tournament not found")
    new_paused = not doc.get("fetch_paused", False)
    await db.tournaments.update_one(
        {"tournament_id": tournament_id},
        {"$set": {"fetch_paused": new_paused, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    _invalidate_admin_cache()
    return {"fetch_paused": new_paused}


@router.post("/tournaments/{tournament_id}/toggle-compare", dependencies=[Depends(verify_admin)])
async def toggle_tournament_compare(tournament_id: str):
    """Toggle comparison (matchmaking) pause for a tournament."""
    doc = await db.tournaments.find_one({"tournament_id": tournament_id}, {"_id": 0, "tournament_id": 1, "compare_paused": 1})
    if doc is None:
        raise HTTPException(404, "Tournament not found")
    new_paused = not doc.get("compare_paused", False)
    new_status = "paused" if new_paused else "active"
    await db.tournaments.update_one(
        {"tournament_id": tournament_id},
        {"$set": {"compare_paused": new_paused, "status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    _invalidate_admin_cache()
    if not new_paused:
        wake_scheduler()
    return {"compare_paused": new_paused}



# --- Category Management ---

@router.get("/arxiv-categories", dependencies=[Depends(verify_admin)])
async def get_arxiv_categories():
    """Return full arXiv taxonomy for searchable category picker."""
    from core.arxiv_categories import ARXIV_TAXONOMY, get_group
    settings = await get_settings()
    active = set(settings.get("active_categories", list(CATEGORIES.keys())))

    cats = []
    for cat_id, name in sorted(ARXIV_TAXONOMY.items()):
        cats.append({
            "id": cat_id,
            "name": name,
            "group": get_group(cat_id),
            "active": cat_id in active,
        })
    return {"categories": cats, "active": sorted(active)}


class CategoryAction(BaseModel):
    category_id: str


@router.post("/categories/add", dependencies=[Depends(verify_admin)])
async def add_category(body: CategoryAction):
    """Add a new tournament category. New categories start as paused."""
    from core.arxiv_categories import ARXIV_TAXONOMY
    cat_id = body.category_id.strip()
    if cat_id not in ARXIV_TAXONOMY:
        raise HTTPException(400, f"Unknown arXiv category: {cat_id}")

    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))
    if cat_id in active:
        raise HTTPException(400, f"{cat_id} is already active")

    active.append(cat_id)
    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"active_categories": active}},
        upsert=True,
    )
    invalidate_settings_cache()

    # Initialize tournament for the new category
    from services.scheduler import init_tournament_registry
    await init_tournament_registry()

    # Set new category tournament to paused (admin must explicitly resume)
    tid = f"cat={cat_id}|mode=standard"
    await db.tournaments.update_one(
        {"tournament_id": tid},
        {"$set": {"status": "paused", "compare_paused": True, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )

    logger.info(f"Admin added category: {cat_id} (preset to paused)")
    _invalidate_admin_cache()
    return {"status": "ok", "active_categories": active, "tournament_status": "paused"}


@router.post("/categories/remove", dependencies=[Depends(verify_admin)])
async def remove_category(body: CategoryAction):
    """Remove a tournament category (keeps data, just stops tournaments)."""
    cat_id = body.category_id.strip()
    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))

    if cat_id not in active:
        raise HTTPException(400, f"{cat_id} is not active")
    if len(active) <= 1:
        raise HTTPException(400, "Cannot remove the last category")

    active = [c for c in active if c != cat_id]
    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"active_categories": active}},
        upsert=True,
    )
    invalidate_settings_cache()

    # Pause the tournament (don't delete data)
    tid = f"cat={cat_id}|mode=standard"
    await db.tournaments.update_one(
        {"tournament_id": tid},
        {"$set": {"status": "paused", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )

    logger.info(f"Admin removed category: {cat_id}")
    _invalidate_admin_cache()
    return {"status": "ok", "active_categories": active}


@router.get("/category-estimate/{cat_id}", dependencies=[Depends(verify_admin)])
async def estimate_category(cat_id: str):
    """Estimate weekly paper volume and tournament cost for a category."""
    from core.arxiv_categories import ARXIV_TAXONOMY
    from services.arxiv import fetch_arxiv_papers

    if cat_id not in ARXIV_TAXONOMY:
        raise HTTPException(400, f"Unknown arXiv category: {cat_id}")

    # Fetch a small sample to estimate volume
    try:
        sample = await fetch_arxiv_papers(category=cat_id, max_results=100)
        total_fetched = len(sample)
    except Exception as e:
        logger.warning(f"Failed to estimate {cat_id}: {e}")
        total_fetched = 0

    # Estimate weekly papers from the sample date range
    weekly_papers = 0
    if total_fetched >= 2:
        dates = []
        for p in sample:
            try:
                d = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
                dates.append(d)
            except (ValueError, KeyError):
                pass
        if len(dates) >= 2:
            dates.sort()
            span_days = max((dates[-1] - dates[0]).days, 1)
            weekly_papers = round(len(dates) / span_days * 7)
    if weekly_papers == 0 and total_fetched > 0:
        weekly_papers = total_fetched  # conservative fallback

    # Cost estimate based on historical matches-per-paper ratio
    settings = await get_settings()
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 10)

    # Check if we already have papers for this category
    existing_papers = await db.papers.count_documents({"categories.0": cat_id})
    existing_matches = await db.matches.count_documents(
        {"completed": True, "failed": {"$ne": True}, "primary_category": cat_id, "mode": {"$exists": False}}
    )

    # Calculate matches-per-paper ratio from historical data across ALL categories
    # This captures the real cost including CI convergence, top-K focus, and re-matches
    total_hist_papers = 0
    total_hist_matches = 0
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))
    for ac in active_cats:
        hp = await db.papers.count_documents({"categories.0": ac})
        hm = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": ac, "mode": {"$exists": False}}
        )
        total_hist_papers += hp
        total_hist_matches += hm

    # Use historical ratio if available, otherwise estimate from settings
    if total_hist_papers >= 20 and total_hist_matches >= 100:
        matches_per_paper = total_hist_matches / total_hist_papers
    else:
        # Theoretical estimate when no history: min_matches * ~4 (empirical multiplier
        # accounting for CI convergence rounds, top-K focus, and re-matching)
        matches_per_paper = 30  # Conservative estimate for new categories

    matches_needed = round(weekly_papers * matches_per_paper)

    # Cost per match: average across 3 models (~$0.015 per comparison)
    avg_cost_per_match = 0.015
    weekly_cost = round(matches_needed * avg_cost_per_match, 2)

    return {
        "category_id": cat_id,
        "name": ARXIV_TAXONOMY.get(cat_id, cat_id),
        "estimated_weekly_papers": weekly_papers,
        "estimated_weekly_matches": matches_needed,
        "estimated_weekly_cost": weekly_cost,
        "existing_papers": existing_papers,
        "existing_matches": existing_matches,
        "sample_size": total_fetched,
        "settings_used": {
            "top_k_focus": top_k,
            "ci_target": ci_target,
            "matches_per_paper_ratio": round(matches_per_paper, 1),
        },
    }



# --- Extraction Statistics ---

# Simple cache for extraction stats (expensive to compute)
_extraction_cache = {"data": None, "timestamp": 0, "computing": False, "warming_up": True}
_EXTRACTION_CACHE_TTL = 3600  # 1 hour


async def _compute_extraction_stats_bg(category: str = None):
    """Background task to compute extraction stats without blocking."""
    if _extraction_cache["computing"]:
        return  # Already computing
    _extraction_cache["computing"] = True
    try:
        result = await _compute_extraction_stats_impl(category)
        if not category:
            _extraction_cache["data"] = result
            _extraction_cache["timestamp"] = _time.time()
            _extraction_cache["warming_up"] = False
    except Exception as e:
        logger.error(f"Background extraction stats computation failed: {e}")
    finally:
        _extraction_cache["computing"] = False


async def _compute_extraction_stats_impl(category: str = None):
    """
    Core implementation for computing extraction statistics.
    """
    from services.llm import extract_key_sections
    
    # Get section char limit from settings
    settings_doc = await db.settings.find_one({"key": "global"}) or {}
    char_limit = settings_doc.get("section_char_limit", DEFAULT_SETTINGS.get("section_char_limit", 2000))
    
    # Count papers efficiently
    query = {"full_text": {"$exists": True, "$nin": [None, ""]}}
    if category:
        query["categories.0"] = category
    
    total_with_text = await db.papers.count_documents(query)
    
    no_text_query = {"$or": [{"full_text": {"$exists": False}}, {"full_text": None}, {"full_text": ""}]}
    if category:
        no_text_query["categories.0"] = category
    papers_without_text = await db.papers.count_documents(no_text_query)
    
    if total_with_text == 0:
        return {
            "total_papers": papers_without_text,
            "papers_with_text": 0,
            "papers_without_text": papers_without_text,
            "by_category": {},
            "overall": {s: {"found": 0, "total": 0, "rate": 0, "header_rate": 0, "fallback_rate": 0, "avg_chars": 0} for s in ["introduction", "methodology", "results", "conclusion"]},
            "all_sections_found": 0,
            "all_sections_rate": 0,
            "all_headers_found": 0,
            "all_headers_rate": 0,
            "section_char_limit": char_limit,
            "sample_size": 0,
            "is_sampled": False,
            "warming_up": False,
        }
    
    # Use sampling for reasonable performance (100 papers max)
    MAX_PAPERS_TO_PROCESS = 100
    use_sampling = total_with_text > MAX_PAPERS_TO_PROCESS
    
    if use_sampling:
        pipeline = [{"$match": query}, {"$sample": {"size": MAX_PAPERS_TO_PROCESS}}, {"$project": {"_id": 0, "id": 1, "title": 1, "full_text": 1, "categories": 1}}]
        papers = await db.papers.aggregate(pipeline).to_list(MAX_PAPERS_TO_PROCESS)
    else:
        papers = await db.papers.find(query, {"_id": 0, "id": 1, "title": 1, "full_text": 1, "categories": 1}).to_list(MAX_PAPERS_TO_PROCESS)
    
    # Aggregate stats
    by_category = {}
    overall = {
        "introduction": {"found": 0, "total": 0, "avg_chars": 0, "total_chars": 0},
        "methodology": {"found": 0, "total": 0, "avg_chars": 0, "total_chars": 0},
        "results": {"found": 0, "total": 0, "avg_chars": 0, "total_chars": 0},
        "conclusion": {"found": 0, "total": 0, "avg_chars": 0, "total_chars": 0},
    }
    all_sections_found = 0
    no_sections_found = 0
    total_chars = 0
    total_extracted_chars = 0
    sample_papers = []
    
    header_detection = {
        "introduction": {"found": 0, "fallback": 0},
        "methodology": {"found": 0, "fallback": 0},
        "results": {"found": 0, "fallback": 0},
        "conclusion": {"found": 0, "fallback": 0},
    }
    
    for paper in papers:
        cat = paper.get("categories", ["unknown"])[0]
        full_text = paper.get("full_text", "")
        
        if cat not in by_category:
            by_category[cat] = {
                "total": 0,
                "introduction": {"found": 0, "header": 0, "fallback": 0, "total_chars": 0},
                "methodology": {"found": 0, "header": 0, "fallback": 0, "total_chars": 0},
                "results": {"found": 0, "header": 0, "fallback": 0, "total_chars": 0},
                "conclusion": {"found": 0, "header": 0, "fallback": 0, "total_chars": 0},
                "all_sections": 0,
                "all_headers": 0,
                "no_sections": 0,
                "avg_full_text_chars": 0,
                "total_full_text_chars": 0,
            }
        
        cat_stats = by_category[cat]
        cat_stats["total"] += 1
        
        if not full_text:
            continue
            
        cat_stats["total_full_text_chars"] += len(full_text)
        total_chars += len(full_text)
        
        sections = extract_key_sections(full_text, cat, char_limit)
        meta = sections.pop("_meta", {})
        found_via_header = meta.get("found_via_header", {})
        used_fallback = meta.get("used_fallback", {})
        
        sections_found_count = 0
        headers_found_count = 0
        paper_extracted_chars = 0
        
        for section_name in ["introduction", "methodology", "results", "conclusion"]:
            section_text = sections.get(section_name, "")
            has_content = len(section_text) > 0
            chars = len(section_text)
            via_header = found_via_header.get(section_name, False)
            via_fallback = used_fallback.get(section_name, False)
            
            overall[section_name]["total"] += 1
            cat_stats[section_name]["total_chars"] += chars
            paper_extracted_chars += chars
            
            if has_content:
                overall[section_name]["found"] += 1
                overall[section_name]["total_chars"] += chars
                cat_stats[section_name]["found"] += 1
                sections_found_count += 1
                
                if via_header:
                    header_detection[section_name]["found"] += 1
                    cat_stats[section_name]["header"] += 1
                    headers_found_count += 1
                elif via_fallback:
                    header_detection[section_name]["fallback"] += 1
                    cat_stats[section_name]["fallback"] += 1
        
        total_extracted_chars += paper_extracted_chars
        
        if sections_found_count == 4:
            all_sections_found += 1
            cat_stats["all_sections"] += 1
        if headers_found_count == 4:
            cat_stats["all_headers"] += 1
        if sections_found_count == 0:
            no_sections_found += 1
            cat_stats["no_sections"] += 1
        
        # Collect sample papers for the UI table (limit to 100)
        if len(sample_papers) < 100:
            sample_papers.append({
                "id": paper["id"],
                "title": paper.get("title", "")[:60],
                "category": cat,
                "full_text_chars": len(full_text),
                "sections_found": sections_found_count,
                "extracted_chars": paper_extracted_chars,
                "intro_chars": len(sections.get("introduction", "")),
                "method_chars": len(sections.get("methodology", "")),
                "results_chars": len(sections.get("results", "")),
                "conclusion_chars": len(sections.get("conclusion", "")),
            })
    
    # Calculate rates
    processed_count = len(papers)
    
    for section_name in ["introduction", "methodology", "results", "conclusion"]:
        if overall[section_name]["total"] > 0:
            overall[section_name]["rate"] = round(overall[section_name]["found"] / overall[section_name]["total"] * 100, 1)
            overall[section_name]["avg_chars"] = round(overall[section_name]["total_chars"] / max(overall[section_name]["found"], 1))
        total = overall[section_name]["total"]
        header_count = header_detection[section_name]["found"]
        fallback_count = header_detection[section_name]["fallback"]
        overall[section_name]["header_found"] = header_count
        overall[section_name]["header_rate"] = round(header_count / max(total, 1) * 100, 1)
        overall[section_name]["fallback_used"] = fallback_count
        overall[section_name]["fallback_rate"] = round(fallback_count / max(total, 1) * 100, 1)
    
    for cat, stats in by_category.items():
        if stats["total"] > 0:
            stats["avg_full_text_chars"] = round(stats["total_full_text_chars"] / stats["total"])
            stats["all_headers_rate"] = round(stats.get("all_headers", 0) / stats["total"] * 100, 1)
            for section_name in ["introduction", "methodology", "results", "conclusion"]:
                stats[section_name]["rate"] = round(stats[section_name]["found"] / stats["total"] * 100, 1)
                stats[section_name]["header_rate"] = round(stats[section_name].get("header", 0) / stats["total"] * 100, 1)
                stats[section_name]["avg_chars"] = round(stats[section_name]["total_chars"] / max(stats[section_name]["found"], 1))
    
    return {
        "total_papers": total_with_text + papers_without_text,
        "papers_with_text": total_with_text,
        "papers_without_text": papers_without_text,
        "text_coverage_rate": round(total_with_text / max(total_with_text + papers_without_text, 1) * 100, 1),
        "by_category": by_category,
        "overall": overall,
        "all_sections_found": all_sections_found,
        "all_sections_rate": round(all_sections_found / max(processed_count, 1) * 100, 1),
        "all_headers_found": sum(stats.get("all_headers", 0) for stats in by_category.values()),
        "all_headers_rate": round(sum(stats.get("all_headers", 0) for stats in by_category.values()) / max(processed_count, 1) * 100, 1),
        "no_sections_found": no_sections_found,
        "no_sections_rate": round(no_sections_found / max(processed_count, 1) * 100, 1),
        "avg_full_text_chars": round(total_chars / max(processed_count, 1)),
        "avg_extracted_chars": round(total_extracted_chars / max(processed_count, 1)),
        "extraction_ratio": round(total_extracted_chars / max(total_chars, 1) * 100, 2),
        "section_char_limit": char_limit,
        "header_detection": header_detection,
        "is_sampled": use_sampling,
        "sample_size": processed_count,
        "sample_papers": sample_papers[:50],
        "warming_up": False,
    }


@router.get("/extraction-stats", dependencies=[Depends(verify_admin)])
async def get_extraction_stats(category: str = None, refresh: bool = False):
    """
    Get detailed statistics about PDF text extraction across all papers.
    Returns warming_up status if cache is not ready yet.
    """
    now = _time.time()
    
    # Return cached data if available and fresh
    if not category and not refresh and _extraction_cache["data"] and (now - _extraction_cache["timestamp"]) < _EXTRACTION_CACHE_TTL:
        return _extraction_cache["data"]
    
    # If currently computing, return warming_up status immediately (non-blocking)
    if _extraction_cache["computing"]:
        if _extraction_cache["data"]:
            return {**_extraction_cache["data"], "warming_up": True, "message": "Refreshing cache..."}
        return {
            "warming_up": True,
            "message": "Computing extraction statistics, please wait...",
            "total_papers": 0,
            "papers_with_text": 0,
            "papers_without_text": 0,
        }
    
    # If no cache and this is NOT a refresh request, trigger background and return warming_up
    if not _extraction_cache["data"] and not refresh:
        asyncio.create_task(_compute_extraction_stats_bg(category))
        return {
            "warming_up": True,
            "message": "Computing extraction statistics, please wait...",
            "total_papers": 0,
            "papers_with_text": 0,
            "papers_without_text": 0,
        }
    
    # Compute synchronously (for refresh=True or startup prewarm)
    _extraction_cache["computing"] = True
    try:
        result = await _compute_extraction_stats_impl(category)
        if not category:
            _extraction_cache["data"] = result
            _extraction_cache["timestamp"] = now
            _extraction_cache["warming_up"] = False
        return result
    finally:
        _extraction_cache["computing"] = False


@router.post("/reconcile-rankings", dependencies=[Depends(verify_admin)])
async def reconcile_rankings_endpoint(category: str = None):
    """Manually trigger a full rankings reconciliation (recompute from matches and compare)."""
    from services.ranking import reconcile_rankings
    results = await reconcile_rankings(db, category=category)
    return {"status": "ok", "results": results}


@router.post("/rerank-all", dependencies=[Depends(verify_admin)])
async def rerank_all_endpoint():
    """Trigger an immediate rerank of all categories using the current ranking method.
    Called after switching ranking_method in settings."""
    from services.ranking import rerank_category_light
    from core.auth import get_settings
    settings = await get_settings()
    method = settings.get("ranking_method", "reg_wr")
    cats = settings.get("active_categories", list(CATEGORIES.keys()))
    results = {}
    for cat in cats:
        try:
            await rerank_category_light(db, cat)
            results[cat] = "ok"
        except Exception as e:
            results[cat] = f"error: {e}"
    # Invalidate leaderboard cache
    from routers.leaderboard import notify_data_changed
    notify_data_changed()
    return {"status": "ok", "method": method, "categories": results}


@router.get("/repair-queue", dependencies=[Depends(verify_admin)])
async def get_repair_queue():
    """Check the rankings repair queue size."""
    count = await db.rankings_repair_queue.count_documents({})
    items = []
    async for item in db.rankings_repair_queue.find({}, {"_id": 0}).limit(20):
        items.append(item)
    return {"count": count, "items": items}

@router.post("/process-repair-queue", dependencies=[Depends(verify_admin)])
async def process_repair_queue_endpoint():
    """Manually process the rankings repair queue."""
    from services.ranking import process_repair_queue
    repaired = await process_repair_queue(db)
    return {"status": "ok", "repaired": repaired}



@router.get("/system-logs", dependencies=[Depends(verify_admin)])
async def get_system_logs(
    level: str = None, label: str = None, hours: int = 24, limit: int = 2000,
):
    """Query persisted system logs (memory tracking, events). Stored 7 days.
    
    For time ranges > 24h, downsamples mem logs to one entry per time bucket
    (max RSS per bucket) to ensure the full range is visible on charts.
    """
    from datetime import datetime, timezone, timedelta
    query = {"ts": {"$gte": datetime.now(timezone.utc) - timedelta(hours=hours)}}
    if level:
        query["level"] = level
    if label:
        query["label"] = {"$regex": label, "$options": "i"}

    # For longer ranges, use aggregation to downsample mem logs
    if hours > 24 and not level:
        # Fetch mem logs downsampled + all non-mem logs
        bucket_minutes = 30 if hours <= 72 else 60  # 30min for 3d, 60min for 7d

        # Downsample mem logs via aggregation
        pipeline = [
            {"$match": {**query, "level": "mem", "rss_mb": {"$exists": True}}},
            {"$sort": {"ts": 1}},
            {"$group": {
                "_id": {
                    "$dateTrunc": {"date": "$ts", "unit": "minute", "binSize": bucket_minutes}
                },
                "ts": {"$last": "$ts"},
                "rss_mb": {"$max": "$rss_mb"},
                "label": {"$last": "$label"},
                "level": {"$first": "$level"},
            }},
            {"$sort": {"ts": 1}},
            {"$limit": 500},
        ]
        mem_logs = await db.system_logs.aggregate(pipeline).to_list(500)

        # Non-mem logs (repair_queue, slow_query) — just get recent
        non_mem_query = {**query, "level": {"$ne": "mem"}}
        non_mem_logs = await db.system_logs.find(
            non_mem_query, {"_id": 0}
        ).sort("ts", -1).limit(500).to_list(500)

        logs = mem_logs + non_mem_logs
    else:
        logs = await db.system_logs.find(
            query, {"_id": 0}
        ).sort("ts", -1).limit(min(limit, 5000)).to_list(min(limit, 5000))

    # Convert datetime to ISO string for JSON serialization
    for log in logs:
        if "ts" in log:
            log["ts"] = log["ts"].isoformat()
        log.pop("_id", None)
    return {"logs": logs, "count": len(logs)}



@router.post("/dedup-papers", dependencies=[Depends(verify_admin)])
async def deduplicate_papers():
    """Find and merge duplicate papers (same title + first author).
    Keeps the paper with more matches, reassigns matches from the duplicate."""
    all_papers = await collect_all(db.papers.find(
        {}, {"_id": 0, "id": 1, "title": 1, "authors": 1}
    ))

    # Group by normalized title + first author
    groups = defaultdict(list)
    for p in all_papers:
        title_norm = p["title"].strip().lower()
        first_author = (p.get("authors") or [""])[0].strip().lower() if p.get("authors") else ""
        key = (title_norm, first_author)
        groups[key].append(p)

    merged = 0
    removed_ids = []
    for key, papers in groups.items():
        if len(papers) < 2:
            continue

        # Count matches and check existence of summaries/full_text for each duplicate
        for p in papers:
            p["_match_count"] = await db.matches.count_documents(
                {"$or": [{"paper1_id": p["id"]}, {"paper2_id": p["id"]}]}
            )
            p["_has_summaries"] = await db.papers.count_documents({"id": p["id"], "summaries": {"$exists": True, "$ne": {}}}) > 0
            p["_has_text"] = await db.papers.count_documents({"id": p["id"], "full_text": {"$ne": None}}) > 0

        # Sort: prefer summaries > full_text > more matches
        papers.sort(key=lambda p: (p["_has_summaries"], p["_has_text"], p["_match_count"]), reverse=True)
        keeper = papers[0]
        duplicates = papers[1:]

        for dup in duplicates:
            dup_id = dup["id"]
            keeper_id = keeper["id"]
            logger.info(f"Merging duplicate: '{key[0][:50]}' — keeping {keeper_id[:8]} ({keeper['_match_count']} matches), removing {dup_id[:8]} ({dup['_match_count']} matches)")

            # Reassign matches: paper1_id
            await db.matches.update_many(
                {"paper1_id": dup_id},
                {"$set": {"paper1_id": keeper_id}},
            )
            # Reassign matches: paper2_id
            await db.matches.update_many(
                {"paper2_id": dup_id},
                {"$set": {"paper2_id": keeper_id}},
            )
            # Reassign winner_id
            await db.matches.update_many(
                {"winner_id": dup_id},
                {"$set": {"winner_id": keeper_id}},
            )

            # If keeper is missing summaries but dup has them, copy them over
            if dup.get("summaries") and not keeper.get("summaries"):
                await db.papers.update_one(
                    {"id": keeper_id},
                    {"$set": {"summaries": dup["summaries"]}},
                )

            # Delete the duplicate paper
            await db.papers.delete_one({"id": dup_id})
            removed_ids.append(dup_id)
            merged += 1

    # Clean up self-matches (where paper1_id == paper2_id after reassignment)
    self_match_result = await db.matches.delete_many(
        {"$expr": {"$eq": ["$paper1_id", "$paper2_id"]}}
    )
    self_matches_deleted = self_match_result.deleted_count

    # Invalidate caches after cleanup
    _invalidate_admin_cache()
    lb_cache = _get_lb_cache()
    lb_cache.clear()
    lb_cache.update({"ts": 0, "total_papers": 0, "total_matches": 0, "warming_up": True})
    from routers.leaderboard import notify_data_changed
    notify_data_changed()
    # Also reseed rankings after dedup
    try:
        from services.ranking import seed_rankings
        await seed_rankings(db)
    except Exception:
        pass

    return {
        "status": "ok",
        "merged": merged,
        "removed_paper_ids": removed_ids,
        "self_matches_deleted": self_matches_deleted,
    }



# --- Temporary: Regenerate truncated summaries ---
# Progress is persisted in DB (settings.regen_progress) to survive server restarts.

_REGEN_PROGRESS_KEY = "regen_progress"


async def _get_regen_progress() -> dict:
    doc = await db.settings.find_one({"key": _REGEN_PROGRESS_KEY}, {"_id": 0})
    return doc or {"running": False, "done": 0, "started_total": 0, "errors": 0, "cost_est": 0.0, "finished": False}


async def _set_regen_progress(**fields):
    await db.settings.update_one(
        {"key": _REGEN_PROGRESS_KEY},
        {"$set": {**fields, "key": _REGEN_PROGRESS_KEY}},
        upsert=True,
    )


def _find_truncated_summaries_sync(papers_cursor) -> list:
    """Shared logic: find papers whose summaries mention truncation (excluding false positives)."""
    import re as _re
    FALSE_POS = _re.compile(r'truncated (normal|distribution|gaussian|Gaussian|power|series)', _re.IGNORECASE)
    results = []
    for p in papers_cursor:
        ft = p.get("full_text") or ""
        if not ft:
            continue
        keys_to_regen = []
        for key, summary in p.get("summaries", {}).items():
            text = summary if isinstance(summary, str) else summary.get("text", "") if isinstance(summary, dict) else str(summary)
            if "truncat" in text.lower():
                cleaned = FALSE_POS.sub("", text)
                if "truncat" not in cleaned.lower():
                    continue
                keys_to_regen.append(key)
        if keys_to_regen:
            results.append({"paper": p, "keys": keys_to_regen})
    return results


async def _scan_truncated_papers() -> list:
    """Async scan: find all papers with truncation complaints in summaries."""
    import re as _re
    FALSE_POS = _re.compile(r'truncated (normal|distribution|gaussian|Gaussian|power|series)', _re.IGNORECASE)
    results = []
    async for p in db.papers.find(
        {"summaries": {"$exists": True, "$ne": {}}, "full_text": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "title": 1, "summaries": 1, "full_text": 1, "abstract": 1, "categories": 1},
    ):
        ft = p.get("full_text") or ""
        if not ft:
            continue
        keys_to_regen = []
        for key, summary in p.get("summaries", {}).items():
            text = summary if isinstance(summary, str) else summary.get("text", "") if isinstance(summary, dict) else str(summary)
            if "truncat" in text.lower():
                cleaned = FALSE_POS.sub("", text)
                if "truncat" not in cleaned.lower():
                    continue
                keys_to_regen.append(key)
        if keys_to_regen:
            results.append({"paper": p, "keys": keys_to_regen})
    return results


@router.get("/regen-summaries/status", dependencies=[Depends(verify_admin)])
async def regen_summaries_status():
    """Check progress of the summary regeneration task."""
    return await _get_regen_progress()


@router.post("/regen-summaries", dependencies=[Depends(verify_admin)])
async def regen_summaries(request: Request):
    """One-time task: regenerate all AI impact summaries that mention truncation.
    
    Runs as a background task. Each summary is regenerated with the same model
    that produced the original, using the full (untruncated) paper text.
    Progress survives server restarts.
    """
    progress = await _get_regen_progress()
    if progress.get("running"):
        raise HTTPException(409, "Regeneration already in progress")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    dry_run = body.get("dry_run", False)

    papers = await _scan_truncated_papers()
    total_summaries = sum(len(item["keys"]) for item in papers)

    # Cost estimate
    pricing = {"openai": 1.75, "anthropic": 5.00, "gemini": 2.00}
    est_cost = 0.0
    for item in papers:
        ft_len = len(item["paper"].get("full_text", ""))
        for key in item["keys"]:
            provider = key.split(":")[0] if ":" in key else "anthropic"
            price = pricing.get(provider, 2.0)
            input_tokens = (ft_len + 2000) / 4
            est_cost += (input_tokens / 1_000_000) * price + (800 / 1_000_000) * 17.0

    if dry_run:
        return {"dry_run": True, "papers": len(papers), "summaries": total_summaries, "estimated_cost": round(est_cost, 2)}

    await _set_regen_progress(running=True, done=0, started_total=total_summaries, errors=0, cost_est=round(est_cost, 2), finished=False)
    asyncio.create_task(_run_regen())
    return {"status": "started", "papers": len(papers), "summaries": total_summaries, "estimated_cost": round(est_cost, 2)}


async def _run_regen():
    """Background task: regenerate summaries with truncation complaints.
    
    Rescans the DB each time so it naturally resumes after a restart
    (already-regenerated papers no longer contain 'truncat').
    """
    from services.llm import generate_precomparison_impact_summary
    from core.config import TOURNAMENT_MODELS

    MODEL_MAP = {}
    for m in TOURNAMENT_MODELS:
        MODEL_MAP[m["provider"]] = m

    try:
        papers = await _scan_truncated_papers()
        total = sum(len(item["keys"]) for item in papers)
        if total == 0:
            await _set_regen_progress(running=False, finished=True, done=0, started_total=0)
            logger.info("Regen: no truncated summaries remaining")
            return

        await _set_regen_progress(running=True, started_total=total, done=0, errors=0)
        done = 0
        errors = 0

        for item in papers:
            paper = item["paper"]
            for key in item["keys"]:
                provider = key.split(":")[0] if ":" in key else "anthropic"
                model_info = MODEL_MAP.get(provider, TOURNAMENT_MODELS[0])

                try:
                    result = await generate_precomparison_impact_summary(paper, model_override=model_info)
                    if result and result.get("summary"):
                        await db.papers.update_one(
                            {"id": paper["id"]},
                            {"$set": {
                                f"summaries.{key}": result["summary"],
                                f"summary_dates.{key}": datetime.now(timezone.utc).isoformat(),
                            }},
                        )
                        logger.info(f"Regen OK: {paper['title'][:50]} [{key}]")
                    else:
                        errors += 1
                        logger.warning(f"Regen empty: {paper['title'][:50]} [{key}]")
                except Exception as e:
                    errors += 1
                    logger.error(f"Regen failed: {paper['title'][:50]} [{key}]: {e}")

                done += 1
                if done % 5 == 0:
                    await _set_regen_progress(done=done, errors=errors)
    except Exception as e:
        logger.error(f"Regen task crashed: {e}")
    finally:
        await _set_regen_progress(running=False, finished=True, done=done, errors=errors)
        logger.info(f"Summary regeneration complete: {done}/{total} done, {errors} errors")



@router.get("/background-tasks", dependencies=[Depends(verify_admin)])
async def get_background_tasks():
    """View recent background task history (experiments, tournaments, etc.)."""
    from services.task_tracker import TaskTracker
    tasks = await TaskTracker.recent(limit=50)
    return {"tasks": tasks}



@router.post("/precompute-experiments", dependencies=[Depends(verify_admin)])
async def precompute_experiments():
    """Compute all experiment results and save to a JSON file for production deployment.
    
    Run this in preview before deploying. Production loads the file on startup instead
    of recomputing from the database (which takes 2-5 minutes and risks OOM).
    """
    from services.precompute import compute_and_export_all
    result = await compute_and_export_all()
    return {"status": "ok", **result}


# --- Generate AI Ratings from existing summaries ---
# --- Archive Management ---
# --- Archive Management ---

@router.post("/archive/snapshot", dependencies=[Depends(verify_admin)])
async def create_snapshot(request: Request):
    """Manually create an archive snapshot for a category."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    category = body.get("category")
    period_type = body.get("period_type", "weekly")
    if not category:
        raise HTTPException(400, "category required")
    from routers.leaderboard import create_archive_snapshot
    result = await create_archive_snapshot(category, period_type)
    if result:
        return {"status": "created", "label": result["label"], "papers": result["paper_count"]}
    return {"status": "already_exists"}


@router.post("/archive/snapshot-all", dependencies=[Depends(verify_admin)])
async def create_all_snapshots():
    """Create archive snapshots for ALL active categories (ignoring day-of-week check)."""
    from routers.leaderboard import create_archive_snapshot
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))
    archive_config = settings.get("archive_frequency", {})
    default_freq = archive_config.get("default", "weekly")
    created = 0
    for cat in active_cats:
        freq = archive_config.get(cat, default_freq)
        result = await create_archive_snapshot(cat, freq)
        if result:
            created += 1
    return {"status": "ok", "created": created, "categories": len(active_cats)}


@router.post("/archive/set-frequency", dependencies=[Depends(verify_admin)])
async def set_archive_frequency(request: Request):
    """Set which archive type to DISPLAY per category (weekly or monthly).
    Both types are always computed and stored — this only controls the dropdown."""
    body = await request.json()
    settings = await get_settings()
    archive_config = settings.get("archive_frequency", {})

    if "default" in body:
        archive_config["default"] = body["default"]
    if "category" in body and "frequency" in body:
        archive_config[body["category"]] = body["frequency"]

    await db.settings.update_one({"key": "global"}, {"$set": {"archive_frequency": archive_config}})
    invalidate_settings_cache()
    return {"status": "ok", "archive_frequency": archive_config}

    await db.settings.update_one({"key": "global"}, {"$set": {"archive_frequency": archive_config}})
    invalidate_settings_cache()
    return {"status": "ok", "archive_frequency": archive_config}


@router.get("/archive/frequency", dependencies=[Depends(verify_admin)])
async def get_archive_frequency():
    """Get current archive frequency settings."""
    settings = await get_settings()
    return settings.get("archive_frequency", {"default": "weekly"})


@router.post("/archive/backfill", dependencies=[Depends(verify_admin)])
async def backfill_archives():
    """Create weekly AND monthly archive snapshots for all active categories.
    
    Design:
    - Both weekly and monthly archives always created for every category
    - Each archive = papers published in that time window, ranked by ALL their matches to date
    - Idempotent: skips archives that already exist
    - Skips categories with no tournament matches
    - Creates "Older" catch-all for papers published before the first archive window
    """
    from services.ranking import compute_leaderboard_async
    from datetime import timedelta

    FROZEN_FIELDS = ["rank", "id", "title", "authors", "score", "wins", "losses",
                     "comparisons", "win_rate", "ci", "wilson_margin", "published", "link", "arxiv_id",
                     "ai_rating", "gap_score"]
    MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    def freeze(lb_entries):
        return [{k: e.get(k) for k in FROZEN_FIELDS} for e in lb_entries]

    def match_count(frozen):
        return sum((e.get("comparisons") or 0) for e in frozen) // 2

    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))
    utc_now = datetime.now(timezone.utc)

    # Drop existing archives so we regenerate with full field set (ai_rating, gap_score)
    await db.leaderboard_archives.delete_many({})

    # --- Load all data once ---
    all_papers = await collect_all(db.papers.find(
        {}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "published": 1, "link": 1,
             "arxiv_id": 1, "categories": 1, "ai_rating": 1}
    ))

    # Build ai_ratings lookup
    ai_ratings = {}
    for p in all_papers:
        rating = p.get("ai_rating")
        if rating and isinstance(rating, dict) and rating.get("score"):
            ai_ratings[p["id"]] = round(rating["score"], 1)

    all_matches = await collect_all(db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1, "created_at": 1}
    ))

    # Parse match dates for time-scoped snapshots
    for m in all_matches:
        ca = m.get("created_at", "")
        if isinstance(ca, str) and ca:
            try:
                m["_ts"] = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            except Exception:
                m["_ts"] = None
        elif isinstance(ca, datetime):
            m["_ts"] = ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
        else:
            m["_ts"] = None

    # Build lookup maps
    paper_by_id = {p["id"]: p for p in all_papers}
    paper_dates = {}
    for p in all_papers:
        try:
            paper_dates[p["id"]] = datetime.fromisoformat(p.get("published", "").replace("Z", "+00:00"))
        except:
            pass

    paper_cat = {}
    for p in all_papers:
        paper_cat[p["id"]] = (p.get("categories") or [""])[0] if p.get("categories") else ""

    # Skip categories with no matches
    cats_with_matches = set()
    for m in all_matches:
        cats_with_matches.add(paper_cat.get(m["paper1_id"], ""))
        cats_with_matches.add(paper_cat.get(m["paper2_id"], ""))
    active_cats = [c for c in active_cats if c in cats_with_matches]

    if not paper_dates:
        return {"status": "no_data"}

    # --- Helper: compute archive for a set of paper IDs, scoped to matches before cutoff ---
    async def compute_archive(cat_papers, cat_pids, cutoff):
        """Run BT on cat_papers using only matches created before cutoff. Return ranked list filtered to cat_pids."""
        # Find matches involving these papers, created before the cutoff
        cat_matches = [m for m in all_matches
                       if (m["paper1_id"] in cat_pids or m["paper2_id"] in cat_pids)
                       and (m.get("_ts") is None or m["_ts"] <= cutoff)]
        if not cat_matches:
            # No matches: return papers with default scores
            result = [{"rank": i + 1, **{k: p.get(k) for k in FROZEN_FIELDS if k != "rank"}} for i, p in enumerate(cat_papers)]
            return result

        # Include opponent papers for BT
        opp_ids = set()
        for m in cat_matches:
            opp_ids.add(m["paper1_id"])
            opp_ids.add(m["paper2_id"])
        opp_ids -= cat_pids
        opp_papers = [paper_by_id[pid] for pid in opp_ids if pid in paper_by_id]

        lb = await compute_leaderboard_async(cat_papers + opp_papers, cat_matches)
        lb = [e for e in lb if e["id"] in cat_pids]
        for i, e in enumerate(lb):
            e["rank"] = i + 1

        # Inject ai_rating and compute gap_score
        for e in lb:
            ai_r = ai_ratings.get(e["id"])
            if ai_r is not None:
                e["ai_rating"] = ai_r

        entries_with_both = [e for e in lb if e.get("ai_rating") and e.get("comparisons", 0) >= 3]
        if len(entries_with_both) >= 2:
            from scipy import stats as _sp_stats
            import numpy as _np
            _bt_vals = _np.array([e["score"] for e in entries_with_both])
            _si_vals = _np.array([e["ai_rating"] for e in entries_with_both])
            _bt_pct = _sp_stats.rankdata(_bt_vals) / len(entries_with_both) * 100
            _si_pct = _sp_stats.rankdata(_si_vals) / len(entries_with_both) * 100
            _gap_raw = _bt_pct - _si_pct
            for i, entry in enumerate(entries_with_both):
                entry["gap_score"] = round(float(_gap_raw[i]), 1)

        return lb

    created = 0

    # --- Determine time range ---
    earliest_paper = min(paper_dates.values())
    # First Monday on or after the earliest paper
    days_to_monday = (7 - earliest_paper.weekday()) % 7
    first_monday = (earliest_paper + timedelta(days=days_to_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    # If earliest paper IS on Monday, first_monday = that Monday (not +7)

    # --- WEEKLY archives ---
    monday = first_monday
    while monday <= utc_now + timedelta(days=7):
        year, week = monday.isocalendar()[0], monday.isocalendar()[1]
        week_start = monday - timedelta(days=7)

        for cat in active_cats:
            if await db.leaderboard_archives.find_one({"category": cat, "year": year, "week": week, "period_type": "weekly"}):
                continue

            cat_papers = [p for p in all_papers
                          if paper_cat.get(p["id"]) == cat
                          and p["id"] in paper_dates
                          and week_start <= paper_dates[p["id"]] < monday]
            if not cat_papers:
                continue

            cat_pids = {p["id"] for p in cat_papers}
            # Cutoff: end of the labeled week (papers get a full week of matches)
            match_cutoff = monday + timedelta(days=7)
            lb = await compute_archive(cat_papers, cat_pids, match_cutoff)

            await db.leaderboard_archives.insert_one({
                "category": cat, "period_type": "weekly",
                "year": year, "week": week, "month": None,
                "label": f"Week {week}, {year}",
                "paper_count": len(lb), "match_count": match_count(lb),
                "leaderboard": freeze(lb), "created_at": monday.isoformat(),
            })
            created += 1

        monday += timedelta(weeks=1)
        await asyncio.sleep(0)

    # --- MONTHLY archives ---
    cur_year, cur_month = earliest_paper.year, earliest_paper.month
    while (cur_year, cur_month) <= (utc_now.year, utc_now.month):
        month_start = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        month_end = datetime(cur_year + (1 if cur_month == 12 else 0), (cur_month % 12) + 1, 1, tzinfo=timezone.utc)

        for cat in active_cats:
            if await db.leaderboard_archives.find_one({"category": cat, "year": cur_year, "month": cur_month, "period_type": "monthly"}):
                continue

            cat_papers = [p for p in all_papers
                          if paper_cat.get(p["id"]) == cat
                          and p["id"] in paper_dates
                          and month_start <= paper_dates[p["id"]] < month_end]
            if not cat_papers:
                continue

            cat_pids = {p["id"] for p in cat_papers}
            # Cutoff: one week after month ends (papers get time to accumulate matches)
            match_cutoff = month_end + timedelta(days=7)
            lb = await compute_archive(cat_papers, cat_pids, match_cutoff)

            await db.leaderboard_archives.insert_one({
                "category": cat, "period_type": "monthly",
                "year": cur_year, "week": None, "month": cur_month,
                "label": f"{MONTH_NAMES[cur_month]} {cur_year}",
                "paper_count": len(lb), "match_count": match_count(lb),
                "leaderboard": freeze(lb), "created_at": month_end.isoformat(),
            })
            created += 1

        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1
        await asyncio.sleep(0)

    # --- "OLDER" catch-all: papers published before the first weekly/monthly archive ---
    for cat in active_cats:
        all_cat_papers = [p for p in all_papers if paper_cat.get(p["id"]) == cat and p["id"] in paper_dates]
        all_cat_pids = {p["id"] for p in all_cat_papers}
        if not all_cat_papers:
            continue

        for ptype in ["weekly", "monthly"]:
            if await db.leaderboard_archives.find_one({"category": cat, "period_type": ptype, "label": "Older"}):
                continue

            # Find the earliest non-Older archive for this type
            if ptype == "weekly":
                earliest = await db.leaderboard_archives.find_one(
                    {"category": cat, "period_type": "weekly", "label": {"$ne": "Older"}},
                    sort=[("year", 1), ("week", 1)])
                if not earliest:
                    # No weekly archives at all — all papers are "Older"
                    cutoff = utc_now
                else:
                    ea_monday = datetime.fromisocalendar(earliest["year"], earliest["week"], 1).replace(tzinfo=timezone.utc)
                    cutoff = ea_monday - timedelta(days=7)
            else:
                earliest = await db.leaderboard_archives.find_one(
                    {"category": cat, "period_type": "monthly", "label": {"$ne": "Older"}},
                    sort=[("year", 1), ("month", 1)])
                if not earliest:
                    cutoff = utc_now
                else:
                    cutoff = datetime(earliest["year"], earliest["month"], 1, tzinfo=timezone.utc)

            older_papers = [p for p in all_cat_papers if paper_dates[p["id"]] < cutoff]
            if not older_papers:
                continue

            older_pids = {p["id"] for p in older_papers}
            lb = await compute_archive(older_papers, older_pids, cutoff)

            await db.leaderboard_archives.insert_one({
                "category": cat, "period_type": ptype,
                "year": 0, "week": 0 if ptype == "weekly" else None,
                "month": 0 if ptype == "monthly" else None,
                "label": "Older",
                "paper_count": len(lb), "match_count": match_count(lb),
                "leaderboard": freeze(lb), "created_at": cutoff.isoformat(),
            })
            created += 1

    logger.info(f"Archive backfill complete: {created} snapshots created")
    return {"status": "ok", "created": created}
