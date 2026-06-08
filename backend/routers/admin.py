from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import asyncio
import hmac
import uuid
import httpx
import random
import time as _time
import secrets as _secrets
from core.config import db, logger, DEFAULT_SETTINGS, DEFAULT_EVALUATION_PROMPT, CATEGORIES
from core.auth import verify_admin, get_settings
from core.dates import mongo_day_expr
from services.scheduler import run_fetch_cycle, run_comparison_round, _get_cat_status, wake_scheduler
from services.arxiv import fetch_arxiv_papers
import routers.leaderboard as _lb_mod

def _get_lb_cache():
    """Get the current leaderboard cache. Uses module reference to always get the latest."""
    return _lb_mod._cache

from routers.validation_utils import collect_all

router = APIRouter(prefix="/api/admin")





class AdminLogin(BaseModel):
    password: str


class SettingsUpdate(BaseModel):
    fetch_interval_hours: Optional[int] = None
    max_papers_per_fetch: Optional[int] = None
    max_initial_backlog: Optional[int] = None
    new_category_lookback_days: Optional[int] = None
    parallel_agents: Optional[int] = None
    parallel_categories: Optional[int] = None
    ranking_method: Optional[str] = None  # reg_wr, trueskill
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
    top_k_focus: Optional[int] = None
    sigma_target_general: Optional[float] = None
    sigma_target_topk: Optional[float] = None
    min_comparisons_converged: Optional[int] = None
    min_papers_for_tournament: Optional[int] = None
    compare_loop_interval: Optional[int] = None
    llm_request_timeout: Optional[int] = None
    max_pairs_per_round: Optional[int] = None
    summary_batch_size: Optional[int] = None
    summary_parallel: Optional[int] = None


class PromptUpdate(BaseModel):
    system_prompt: str
    user_prompt: str


# Admin session tokens - stored in MongoDB for persistence across restarts/pods
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
        # Map internal status to task status
        internal_status = result.get("status", "error") if isinstance(result, dict) else "error"
        if internal_status == "error":
            final_status = "failed"
        elif internal_status == "partial":
            final_status = "completed"  # partial success is still "completed" for polling
        else:
            final_status = "completed"
        _fetch_tasks[category] = {
            "status": final_status,
            "started_at": _fetch_tasks[category]["started_at"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "error": result.get("error") if final_status == "failed" else None,
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
        pass


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



class AddPaperRequest(BaseModel):
    arxiv_url: str  # e.g. "https://arxiv.org/abs/2401.12345" or just "2401.12345" or "2401.12345v3"
    category: str   # target category, e.g. "cs.RO"


@router.post("/add-paper", dependencies=[Depends(verify_admin)])
async def add_paper_by_arxiv(body: AddPaperRequest):
    """Add a specific arXiv paper to a category's pipeline (fetch → PDF → summary → ranking → tournament).
    
    The paper is treated as any other — no extra privileges in the tournament.
    If the paper already exists, it returns its current status.
    """
    import re as _re
    from services.arxiv import strip_arxiv_version

    # Parse arxiv ID from URL or raw ID
    raw = body.arxiv_url.strip()
    # Handle full URLs: https://arxiv.org/abs/2401.12345v2, https://arxiv.org/pdf/2401.12345
    m = _re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', raw)
    if not m:
        raise HTTPException(400, f"Could not parse arXiv ID from: {raw}")
    arxiv_id = m.group(1)
    base, version = strip_arxiv_version(arxiv_id)

    # Check if paper already exists
    existing = await db.papers.find_one(
        {"$or": [{"arxiv_id": arxiv_id}, {"arxiv_id_base": base}]},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "full_text": {"$type": "string"},
         "summaries": 1, "categories": 1}
    )
    if existing:
        has_text = bool(existing.get("full_text"))
        has_summary = bool(existing.get("summaries"))
        has_ranking = bool(await db.rankings.find_one({"paper_id": existing["id"]}, {"_id": 0, "paper_id": 1}))
        return {
            "status": "already_exists",
            "paper_id": existing["id"],
            "title": existing.get("title"),
            "arxiv_id": existing.get("arxiv_id"),
            "has_full_text": has_text,
            "has_summary": has_summary,
            "has_ranking": has_ranking,
            "message": "Paper already in database. Use 'Fetch & generate summaries' to complete any missing steps."
        }

    # Fetch metadata from arXiv API
    import xml.etree.ElementTree as ET
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://export.arxiv.org/api/query?id_list={base}",
            timeout=15,
        )
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None or entry.find("atom:title", ns) is None:
        raise HTTPException(404, f"Paper {arxiv_id} not found on arXiv")

    title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
    abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
    published = entry.find("atom:published", ns).text
    authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)][:8]
    categories = [c.get("term") for c in entry.findall("atom:category", ns)]
    pdf_link = None
    for link in entry.findall("atom:link", ns):
        if link.get("title") == "pdf":
            pdf_link = link.get("href")

    # Ensure target category is in the categories list
    if body.category not in categories:
        categories.insert(0, body.category)

    # Fetch the actual versioned arxiv_id from the response
    entry_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
    actual_base, actual_version = strip_arxiv_version(entry_id)

    paper_doc = {
        "id": str(uuid.uuid4()),
        "title": title,
        "authors": authors,
        "abstract": abstract[:2000],
        "categories": categories,
        "published": published,
        "link": f"https://arxiv.org/abs/{entry_id}",
        "pdf_link": pdf_link,
        "full_text": None,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "needs_pdf": True,
        "arxiv_id": entry_id,
        "arxiv_id_base": actual_base,
        "current_version": actual_version,
        "is_latest_version": True,
    }

    import hashlib
    title_norm = title.strip().lower()
    first_author = (authors[0] if authors else "").strip().lower()
    paper_doc["dedup_hash"] = hashlib.sha256(f"{title_norm}|{first_author}".encode()).hexdigest()[:16]

    try:
        await db.papers.insert_one(paper_doc)
    except Exception as e:
        raise HTTPException(409, f"Failed to insert paper (possible duplicate): {e}")

    # Kick off the pipeline for this category (PDF download → summary → ranking)
    asyncio.create_task(_run_single_paper_pipeline(paper_doc["id"], body.category))

    return {
        "status": "added",
        "paper_id": paper_doc["id"],
        "title": title,
        "arxiv_id": entry_id,
        "category": body.category,
        "message": "Paper added. PDF download, summary generation, and ranking insertion running in background."
    }


async def _run_single_paper_pipeline(paper_id: str, category: str):
    """Background task: download PDF → generate summary → insert ranking for a single paper."""
    from services.llm import download_and_extract_pdf, generate_precomparison_impact_summary
    from services.ranking import insert_ranking_for_paper

    try:
        paper = await db.papers.find_one({"id": paper_id}, {"_id": 0})
        if not paper:
            logger.error(f"[add-paper] Paper {paper_id} not found")
            return

        # Mark paper as being processed by single-paper pipeline — prevents
        # the scheduler's _generate_paper_summaries from racing with us
        await db.papers.update_one({"id": paper_id}, {"$set": {"_pipeline_active": True}})

        # Step 1: Download PDF
        if paper.get("pdf_link") and not paper.get("full_text"):
            try:
                full_text = await download_and_extract_pdf(paper["pdf_link"], doi=paper.get("doi"))
                if full_text:
                    await db.papers.update_one(
                        {"id": paper_id},
                        {"$set": {"full_text": full_text, "needs_pdf": False}}
                    )
                    paper["full_text"] = full_text
                    logger.info(f"[add-paper] PDF downloaded for '{paper['title'][:40]}'")
                else:
                    await db.papers.update_one({"id": paper_id}, {"$set": {"needs_pdf": False, "pdf_failed": True}})
                    logger.warning(f"[add-paper] PDF extraction failed for '{paper['title'][:40]}'")
            except Exception as e:
                logger.warning(f"[add-paper] PDF download error: {e}")
                await db.papers.update_one({"id": paper_id}, {"$set": {"needs_pdf": False, "pdf_failed": True}})

        # Step 2: Generate summaries (all 3 models)
        if paper.get("full_text"):
            from services.scheduler import _SUMMARY_GENERATION_MODELS, _summary_model_key
            for model_info in _SUMMARY_GENERATION_MODELS:
                mk = _summary_model_key(model_info)
                # Re-read paper to check for summaries added by previous iteration
                paper_check = await db.papers.find_one({"id": paper_id}, {"_id": 0, "summaries": 1})
                existing_summary = (paper_check.get("summaries") or {}).get(mk) if paper_check else None
                if existing_summary:
                    continue
                try:
                    result = await generate_precomparison_impact_summary(paper, model_override=model_info)
                    if result and result.get("summary"):
                        summary_val = result["summary"]
                        update_fields = {
                            f"summaries.{mk}": summary_val,
                            f"summary_dates.{mk}": datetime.now(timezone.utc).isoformat(),
                        }
                        if result.get("tokens"):
                            update_fields[f"summary_tokens.{mk}"] = result["tokens"]
                        # Parse ratings from summary (same as scheduler)
                        from services.llm import parse_ratings_from_summary
                        if "thinking" in mk:
                            ratings = parse_ratings_from_summary(summary_val)
                            if ratings:
                                update_fields["ai_rating"] = ratings["score"]
                        model_ratings = parse_ratings_from_summary(summary_val)
                        if model_ratings:
                            model_short = "claude" if "anthropic" in mk else "gpt" if "openai" in mk else "gemini" if "gemini" in mk else None
                            if model_short:
                                update_fields[f"ai_ratings_by_model.{model_short}"] = model_ratings
                        await db.papers.update_one(
                            {"id": paper_id},
                            {"$set": update_fields, "$addToSet": {"summary_keys": mk}}
                        )
                        logger.info(f"[add-paper] Summary generated ({mk}) for '{paper['title'][:40]}'")
                except Exception as e:
                    logger.warning(f"[add-paper] Summary gen failed ({mk}): {e}")

        # Step 3: Insert ranking — always attempt, even if some summaries failed.
        # Requires the Claude thinking summary (the only one used in tournaments).
        REQUIRED_SUMMARY = "anthropic:claude-opus-4-6:thinking"
        try:
            paper_fresh = await db.papers.find_one(
                {"id": paper_id},
                {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                 "link": 1, "published": 1, "added_at": 1, "categories": 1,
                 "ai_rating": 1, "summaries": 1}
            )
            has_claude = bool(paper_fresh and (paper_fresh.get("summaries") or {}).get(REQUIRED_SUMMARY))
            if has_claude:
                existing_rank = await db.rankings.find_one({"paper_id": paper_id}, {"_id": 0})
                if not existing_rank:
                    await insert_ranking_for_paper(db, paper_fresh)
                    logger.info(f"[add-paper] Ranking inserted for '{paper_fresh['title'][:40]}'")

                    from routers.leaderboard import notify_data_changed
                    from services.scheduler import wake_scheduler
                    notify_data_changed()
                    wake_scheduler()
            else:
                logger.warning(f"[add-paper] Claude thinking summary missing for '{paper.get('title', '')[:40]}' — ranking not inserted")
        except Exception as e:
            logger.error(f"[add-paper] Ranking insertion failed: {e}")

        logger.info(f"[add-paper] Pipeline complete for '{paper.get('title', '')[:40]}'")

    except Exception as e:
        logger.error(f"[add-paper] Pipeline failed for {paper_id}: {e}")
    finally:
        await db.papers.update_one({"id": paper_id}, {"$unset": {"_pipeline_active": ""}})



@router.get("/unranked-papers", dependencies=[Depends(verify_admin)])
async def get_unranked_papers(category: str = "cs.RO"):
    """Diagnostic: find papers with summaries that aren't on the leaderboard."""
    from services.scheduler import get_matchable_paper_ids, _SUMMARY_GENERATION_MODELS, _summary_model_key, _SUMMARY_KEY_FALLBACKS

    ranked_ids = set()
    async for r in db.rankings.find({"category": category}, {"_id": 0, "paper_id": 1}):
        ranked_ids.add(r["paper_id"])

    # Find matchable IDs (papers with the required Claude Thinking summary)
    settings = await get_settings()
    matchable_ids = await get_matchable_paper_ids(category, settings.get("summary_source", "thinking"))

    # Ranked but NOT matchable (missing the required summary key)
    ranked_not_matchable = []
    if matchable_ids and len(ranked_ids) > len(matchable_ids):
        non_matchable_ids = ranked_ids - matchable_ids
        model_keys = [_summary_model_key(m) for m in _SUMMARY_GENERATION_MODELS]
        async for p in db.papers.find(
            {"id": {"$in": list(non_matchable_ids)}},
            {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "summaries": 1}
        ):
            existing_keys = list((p.get("summaries") or {}).keys())
            missing_keys = [mk for mk in model_keys if mk not in existing_keys]
            ranked_not_matchable.append({
                "id": p["id"],
                "title": p["title"],
                "arxiv_id": p.get("arxiv_id"),
                "has_summary_keys": existing_keys,
                "missing_summary_keys": missing_keys,
            })

    unranked = []
    async for p in db.papers.find(
        {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "added_at": 1, "full_text": 1}
    ):
        if p["id"] not in ranked_ids:
            unranked.append({
                "id": p["id"],
                "title": p["title"],
                "arxiv_id": p.get("arxiv_id"),
                "added_at": p.get("added_at"),
                "has_full_text": bool(p.get("full_text")),
            })

    # Also find papers with full_text but no summaries
    no_summaries = []
    async for p in db.papers.find(
        {"categories.0": category, "full_text": {"$ne": None},
         "$or": [{"summaries": {"$exists": False}}, {"summaries": {}}, {"summaries": None}]},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "added_at": 1}
    ):
        no_summaries.append({
            "id": p["id"],
            "title": p["title"],
            "arxiv_id": p.get("arxiv_id"),
            "added_at": p.get("added_at"),
        })

    return {
        "category": category,
        "ranked_count": len(ranked_ids),
        "matchable_count": len(matchable_ids) if matchable_ids else len(ranked_ids),
        "ranked_not_matchable": ranked_not_matchable,
        "ranked_not_matchable_count": len(ranked_not_matchable),
        "unranked_with_summaries": unranked,
        "unranked_with_summaries_count": len(unranked),
        "has_text_no_summaries": no_summaries,
        "has_text_no_summaries_count": len(no_summaries),
    }



@router.post("/toggle-pause", dependencies=[Depends(verify_admin)])
async def toggle_pause():
    settings = await get_settings()
    new_state = not settings.get("paused", False)
    await db.settings.update_one({"key": "global"}, {"$set": {"paused": new_state}}, upsert=True)
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
    elif category.startswith("iacr."):
        try:
            from services.iacr import fetch_iacr_papers_oai
            date_from = last_fetch[:10] if last_fetch else None
            if not date_from:
                from datetime import timedelta
                date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
            raw_all = await fetch_iacr_papers_oai(date_from=date_from, max_papers=5000)
            papers = [p for p in raw_all if category in p.get("categories", [])]
            if papers:
                iacr_ids = [p["iacr_id"] for p in papers if p.get("iacr_id")]
                existing = await db.papers.find({"iacr_id": {"$in": iacr_ids}}, {"_id": 0, "iacr_id": 1}).to_list(5000)
                existing_ids = {e["iacr_id"] for e in existing}
                new_count = sum(1 for p in papers if p.get("iacr_id") and p["iacr_id"] not in existing_ids)
            else:
                new_count = 0
            return {"available": new_count, "source": "iacr_oai", "category": category, "last_fetch": last_fetch}
        except Exception as e:
            logger.warning(f"Failed to query IACR for {category}: {e}")
            return {"available": 0, "source": "iacr_error", "category": category, "last_fetch": last_fetch, "error": str(e)[:100]}
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
    # No caching — always serve real-time data from indexed collections
    lb_cache = _get_lb_cache()

    # All counts in parallel
    import asyncio
    cat_scheduler = _get_cat_status(category)

    total_papers, sched_papers_total, total_matches, ranked_count, cat_matches_sorted = await asyncio.gather(
        db.rankings.count_documents({"category": category}),
        db.papers.count_documents({"categories.0": category}),
        db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category}
        ),
        db.rankings.count_documents({"category": category, "comparisons": {"$gt": 0}}),
        db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category},
            {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "reasoning": 1, "created_at": 1, "model_used": 1}
        ).sort("created_at", -1).limit(10).to_list(10),
    )

    sched_papers = cat_scheduler.get("papers_count", 0)
    if not total_papers:
        total_papers = sched_papers
    failed_matches = lb_cache.get("_failed_by_cat", {}).get(category, 0)
    unranked = total_papers - ranked_count

    # Paper titles from rankings DB, fallback to papers collection
    paper_ids_needed = set()
    for m in cat_matches_sorted:
        paper_ids_needed.update([m["paper1_id"], m["paper2_id"], m.get("winner_id", "")])
    paper_ids_needed.discard("")
    paper_titles = {}
    async for r in db.rankings.find({"paper_id": {"$in": list(paper_ids_needed)}}, {"_id": 0, "paper_id": 1, "title": 1}):
        if r.get("title"):
            paper_titles[r["paper_id"]] = r["title"]
    # Fallback for any missing titles
    missing = paper_ids_needed - set(paper_titles.keys())
    if missing:
        async for p in db.papers.find({"id": {"$in": list(missing)}}, {"_id": 0, "id": 1, "title": 1}):
            paper_titles[p["id"]] = p.get("title", "Untitled")

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
    return result


@router.get("/progress", dependencies=[Depends(verify_admin)])
async def get_progress_estimate(category: str = "cs.RO"):
    """Triple-goal progress — always computed fresh from rankings DB (single source of truth)."""
    settings = await get_settings()
    global_paused = settings.get("paused", False)

    # Live tournament pause status (single fast query)
    tid = f"cat={category}|mode=standard"
    tournament_doc = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "status": 1, "fetch_paused": 1, "compare_paused": 1})
    tournament_paused = tournament_doc.get("status") == "paused" if tournament_doc else False
    fetch_paused = bool(tournament_doc.get("fetch_paused")) if tournament_doc else False
    compare_paused = bool(tournament_doc.get("compare_paused")) if tournament_doc else False
    is_paused = global_paused or tournament_paused

    # Compute progress from rankings DB — single source of truth
    # Uses indexed rankings collection (pre-computed wins/comparisons), fast enough without caching
    top_k = settings.get("top_k_focus", 10)
    sigma_target_general = settings.get("sigma_target_general", 2.5)
    sigma_target_topk = settings.get("sigma_target_topk", 2.0)
    min_comps = settings.get("min_comparisons_converged", 50)
    parallel_agents = settings.get("parallel_agents", 5)

    TS_SCALE = 10.0  # for ±Elo display

    entries = []
    async for doc in db.rankings.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "ts_sigma": 1, "comparisons": 1, "score": 1, "unique_opponents": 1, "wins": 1},
    ):
        entries.append(doc)

    # Filter to matchable papers only (shared function — single source of truth)
    try:
        from services.scheduler import get_matchable_paper_ids
        matchable_ids = await get_matchable_paper_ids(category, settings.get("summary_source", "thinking"))
        if matchable_ids:
            entries = [e for e in entries if e["paper_id"] in matchable_ids]
    except Exception:
        pass  # If filter fails, use all entries

    total_papers = len(entries)
    if total_papers == 0:
        # Check if papers exist but haven't been ranked yet (summary phase)
        actual_papers = await db.papers.count_documents({"categories.0": category})
        # Count papers with PDFs and summaries to show progress
        papers_with_pdf = 0
        papers_with_summaries = 0
        if actual_papers > 0:
            try:
                papers_with_pdf = await db.papers.count_documents(
                    {"categories.0": category, "full_text": {"$ne": None}}
                )
                papers_with_summaries = await db.papers.count_documents(
                    {"categories.0": category, "summaries": {"$exists": True, "$ne": {}}}
                )
            except Exception:
                pass
        result = {
            "total_papers": actual_papers,
            "total_in_db": actual_papers,
            "papers_with_pdf": papers_with_pdf,
            "goals_met": actual_papers == 0,  # Only truly met if no papers exist at all
            "phase": "summaries" if actual_papers > 0 else None,
            "summary_coverage": {
                "with_summaries": papers_with_summaries,
                "total": actual_papers,
            } if actual_papers > 0 else None,
            "paused": is_paused,
            "global_paused": global_paused, "tournament_paused": bool(tournament_paused),
            "fetch_paused": fetch_paused, "compare_paused": compare_paused,
            "category": category,
        }
        return result

    entries.sort(key=lambda e: e.get("score", 0), reverse=True)
    top_k_list = [e["paper_id"] for e in entries[:min(top_k, total_papers)]]
    top_k_ids = set(top_k_list)

    # Goal 1: All non-top-K papers sigma ≤ sigma_target_general (+ undefeated check)
    general_converged = 0
    general_total = 0
    general_additional = 0
    widest_general_sigma = 0.0
    general_sigmas = []
    for e in entries:
        if e["paper_id"] in top_k_ids:
            continue
        general_total += 1
        sigma = e.get("ts_sigma", 25.0 / 3)
        general_sigmas.append(sigma)
        n = e.get("comparisons", 0)
        w = e.get("wins", 0)
        # Converged if: (sigma met OR floor reached) AND not undefeated-below-floor
        is_undefeated = n > 0 and (w == n or w == 0) and n < min_comps
        if (sigma <= sigma_target_general or n >= min_comps) and not is_undefeated:
            general_converged += 1
        else:
            if n >= 2:
                # Estimate: sigma ≈ k/sqrt(n), so n_needed = (k/target)^2
                k = sigma * (n ** 0.5)
                n_needed = (k / sigma_target_general) ** 2
                general_additional += max(3, int(n_needed) - n)
            else:
                general_additional += 30
        if sigma > widest_general_sigma:
            widest_general_sigma = sigma

    goal1_met = general_converged == general_total if general_total > 0 else True
    median_general_sigma = sorted(general_sigmas)[len(general_sigmas) // 2] if general_sigmas else 0.0
    matches_for_goal1 = 0 if goal1_met else max(0, int(general_additional * 0.6))

    # Goal 2: All top-K papers sigma ≤ sigma_target_topk (+ undefeated check)
    topk_converged = 0
    topk_total = len(top_k_ids)
    topk_additional = 0
    widest_topk_sigma = 0.0
    topk_sigmas = []
    entry_map = {e["paper_id"]: e for e in entries}
    for pid in top_k_list:
        e = entry_map.get(pid, {})
        sigma = e.get("ts_sigma", 25.0 / 3)
        n = e.get("comparisons", 0)
        w = e.get("wins", 0)
        topk_sigmas.append(sigma)
        is_undefeated = n > 0 and (w == n or w == 0) and n < min_comps
        if (sigma <= sigma_target_topk or n >= min_comps) and not is_undefeated:
            topk_converged += 1
        else:
            if n >= 2:
                k = sigma * (n ** 0.5)
                n_needed = (k / sigma_target_topk) ** 2
                topk_additional += max(3, int(n_needed) - n)
            else:
                topk_additional += 40
        if sigma > widest_topk_sigma:
            widest_topk_sigma = sigma

    goal2_met = topk_converged == topk_total if topk_total > 0 else True
    median_topk_sigma = sorted(topk_sigmas)[len(topk_sigmas) // 2] if topk_sigmas else 0.0
    matches_for_goal2 = 0 if goal2_met else max(0, int(topk_additional * 0.6))

    # Goal 3: Cross-matches among top-K papers
    # Fetch ALL matches involving any top-K paper (simple $in), then check pairs in Python
    topk_total_pairs = len(top_k_list) * (len(top_k_list) - 1) // 2
    topk_matched_pairs = 0
    if top_k_list:
        top_k_set = set(top_k_list)
        matched_pairs_set = set()
        async for m in db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category,
             "paper1_id": {"$in": top_k_list}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ):
            if m["paper2_id"] in top_k_set:
                matched_pairs_set.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
        # Also check reverse direction
        async for m in db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category,
             "paper2_id": {"$in": top_k_list}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ):
            if m["paper1_id"] in top_k_set:
                matched_pairs_set.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
        topk_matched_pairs = len(matched_pairs_set)
    matches_for_goal3 = topk_total_pairs - topk_matched_pairs
    goal3_met = bool(topk_matched_pairs == topk_total_pairs)

    total_est = max(matches_for_goal1, matches_for_goal2) + matches_for_goal3
    seconds_per_match = 10.0 / max(parallel_agents, 1)
    est_minutes = max(0, round(total_est * seconds_per_match / 60))

    # Query matches directly from DB for real-time accuracy (no stale in-memory counter)
    # Parallelize expensive count queries
    import asyncio
    cat_matches_done, cat_papers_with_pdf, cat_total_in_db, cat_papers_with_summaries = await asyncio.gather(
        db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": category}
        ),
        db.papers.count_documents({"categories.0": category, "full_text": {"$ne": None}}),
        db.papers.count_documents({"categories.0": category}),
        db.papers.count_documents({"categories.0": category, "summaries": {"$exists": True, "$ne": {}}}),
    )

    # Detect pair exhaustion: papers that need more matches but have played all matchable opponents.
    # Uses materialized `unique_opponents` field on rankings (O(1) per paper, no aggregation).
    max_possible_pairs = total_papers * (total_papers - 1) // 2
    pair_exhausted = False
    exhausted_papers = 0
    matchable_count = len(entries)
    if not (goal1_met and goal2_met) and matchable_count > 1:
        for e in entries:
            pid = e["paper_id"]
            target = sigma_target_topk if pid in top_k_ids else sigma_target_general
            sigma = e.get("ts_sigma", 25.0 / 3)
            comps = e.get("comparisons", 0)
            actual_opps = e.get("unique_opponents", 0)
            if sigma > target and comps < min_comps and actual_opps >= matchable_count - 1:
                exhausted_papers += 1
        if exhausted_papers > 0:
            pair_exhausted = True

    # Compute unique pairs played from materialized unique_opponents.
    # Cap each paper's count at matchable_count-1 to avoid inflation from orphan opponents.
    unique_pairs_played = sum(min(e.get("unique_opponents", 0), matchable_count - 1) for e in entries) // 2
    all_pairs_exhausted = unique_pairs_played >= max_possible_pairs if max_possible_pairs > 0 else False

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
        "pair_exhausted": pair_exhausted,
        "all_pairs_exhausted": all_pairs_exhausted,
        "exhausted_papers": exhausted_papers,
        "max_possible_pairs": max_possible_pairs,
        "unique_pairs_played": unique_pairs_played,
        "goal1": {
            "met": bool(goal1_met),
            "label": f"General \u00B1{int(sigma_target_general * 2 * TS_SCALE)} pts",
            "done": int(general_converged),
            "total": int(general_total),
            "median_margin": round(median_general_sigma * 2 * TS_SCALE, 0),
        },
        "goal2": {
            "met": bool(goal2_met),
            "label": f"Top-{topk_total} \u00B1{int(sigma_target_topk * 2 * TS_SCALE)} pts",
            "done": int(topk_converged),
            "total": int(topk_total),
            "median_margin": round(median_topk_sigma * 2 * TS_SCALE, 0),
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
            "with_summaries": cat_papers_with_summaries,
        },
    }

    # Add live diagnostics: last match time and failed count (direct DB query, not cached)
    try:
        last_match = await db.matches.find_one(
            {"primary_category": category, "completed": True, "failed": {"$ne": True}},
            {"_id": 0, "created_at": 1},
            sort=[("created_at", -1)],
        )
        result["last_match_at"] = last_match.get("created_at") if last_match else None
        failed_count = await db.matches.count_documents(
            {"primary_category": category, "failed": True}
        )
        result["failed_matches_total"] = failed_count
    except Exception:
        pass

    return result


@router.get("/scheduler-diagnostics", dependencies=[Depends(verify_admin)])
async def scheduler_diagnostics():
    """Real-time scheduler diagnostics — shows compare loop health and per-category round results."""
    from services.scheduler import get_scheduler_diagnostics
    diag = get_scheduler_diagnostics()
    return diag



@router.get("/restart-history", dependencies=[Depends(verify_admin)])
async def restart_history(limit: int = 50):
    """Show recent server shutdown/restart signals for diagnosing periodic restarts.
    Reads from system_logs where event is shutdown_signal or server_shutdown or reload_reexec."""
    events = []
    async for doc in db.system_logs.find(
        {"event": {"$in": ["shutdown_signal", "server_shutdown", "reload_reexec"]}},
        {"_id": 0},
    ).sort("ts", -1).limit(limit):
        if "ts" in doc and hasattr(doc["ts"], "isoformat"):
            doc["ts"] = doc["ts"].isoformat()
        events.append(doc)
    return {"events": events, "count": len(events)}


@router.get("/diagnose-pairs", dependencies=[Depends(verify_admin)])
async def diagnose_pair_selection(category: str = "cs.SI"):
    """Diagnose why _select_pairs returns empty for a category.
    
    Shows per-paper: rankings comparisons vs actual DB matches vs actual unique opponents.
    Identifies the gap between what rankings thinks and what the matches DB has.
    """
    from services.scheduler import get_matchable_paper_ids, _get_compared_opponents, _make_dedup_pair
    settings = await get_settings()
    sigma_target_general = settings.get("sigma_target_general", 2.5)
    sigma_target_topk = settings.get("sigma_target_topk", 2.0)
    top_k = settings.get("top_k_focus", 10)

    # Get rankings entries
    entries = []
    async for doc in db.rankings.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "ts_sigma": 1, "comparisons": 1, "score": 1},
    ):
        entries.append(doc)

    # Filter matchable
    matchable_ids = await get_matchable_paper_ids(category, settings.get("summary_source", "thinking"))
    if matchable_ids:
        entries = [e for e in entries if e["paper_id"] in matchable_ids]

    matchable_count = len(entries)
    entries.sort(key=lambda e: e.get("score", 0), reverse=True)
    top_k_ids = set(e["paper_id"] for e in entries[:top_k])
    paper_ids = [e["paper_id"] for e in entries]

    # For each needy paper, check actual opponents from matches DB
    needy_diagnosis = []
    for e in entries:
        pid = e["paper_id"]
        target = sigma_target_topk if pid in top_k_ids else sigma_target_general
        sigma = e.get("ts_sigma", 25.0 / 3)
        if sigma <= target:
            continue
        # Count actual unique opponents from matches DB
        candidates = [p for p in paper_ids if p != pid]
        already_compared = await _get_compared_opponents(pid, category, candidates)
        novel_count = len(candidates) - len(already_compared)

        needy_diagnosis.append({
            "paper_id": pid[:30],
            "rankings_comparisons": e.get("comparisons", 0),
            "db_unique_opponents": len(already_compared),
            "novel_opponents_available": novel_count,
            "sigma": round(sigma, 3),
            "target": target,
            "is_top_k": pid in top_k_ids,
        })

    # Count total matches in DB vs sum of rankings comparisons
    total_db_matches = await db.matches.count_documents(
        {"primary_category": category, "completed": True, "failed": {"$ne": True}}
    )
    sum_rankings_comps = sum(e.get("comparisons", 0) for e in entries)

    return {
        "category": category,
        "matchable_papers": matchable_count,
        "threshold": matchable_count - 1,
        "total_db_matches": total_db_matches,
        "sum_rankings_comparisons": sum_rankings_comps,
        "rankings_implied_matches": sum_rankings_comps // 2,
        "ghost_matches": total_db_matches - sum_rankings_comps // 2,
        "needy_papers": len(needy_diagnosis),
        "needy_with_zero_novel": sum(1 for d in needy_diagnosis if d["novel_opponents_available"] == 0),
        "diagnosis": sorted(needy_diagnosis, key=lambda d: d["novel_opponents_available"]),
    }




@router.get("/llm-usage", dependencies=[Depends(verify_admin)])
async def get_llm_usage_aggregate(days: int = 7):
    """Aggregate LLM usage from the llm_usage collection, grouped by day and context."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$group": {
            "_id": {
                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
                "context": "$context",
                "success": "$success",
            },
            "calls": {"$sum": 1},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "thinking_tokens": {"$sum": "$thinking_tokens"},
        }},
        {"$sort": {"_id.date": -1}},
    ]
    results = []
    async for doc in db.llm_usage.aggregate(pipeline):
        results.append({
            "date": doc["_id"]["date"],
            "context": doc["_id"]["context"],
            "success": doc["_id"]["success"],
            "calls": doc["calls"],
            "input_tokens": doc["input_tokens"],
            "output_tokens": doc["output_tokens"],
            "thinking_tokens": doc["thinking_tokens"],
        })
    return {"usage": results, "days": days}


@router.get("/disqualified-papers", dependencies=[Depends(verify_admin)])
async def get_disqualified_papers():
    """List papers with summary issues: refused, blocked (3+ failures), incomplete, or unprocessed."""

    # 1. Refused: papers where Claude explicitly declined (content policy)
    refused = []
    async for doc in db.papers.find(
        {"summary_refused": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "categories": 1, "summary_refused": 1, "summaries": 1},
    ).limit(100):
        refused_models = list((doc.get("summary_refused") or {}).keys())
        refused.append({
            "id": doc.get("id"),
            "title": doc.get("title"),
            "arxiv_id": doc.get("arxiv_id"),
            "category": (doc.get("categories") or [""])[0],
            "refused_models": refused_models,
            "has_summaries": list((doc.get("summaries") or {}).keys()),
        })

    # 2. Blocked: papers with summary_failures >= 3 (but not refused)
    disqualified = []
    async for doc in db.papers.find(
        {"summary_failures": {"$exists": True}, "summary_refused": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "categories": 1, "summary_failures": 1, "summaries": 1},
    ).limit(100):
        failures = doc.get("summary_failures", {})
        blocked_models = {m: c for m, c in failures.items() if c >= 3}
        if blocked_models:
            disqualified.append({
                "id": doc.get("id"),
                "title": doc.get("title"),
                "arxiv_id": doc.get("arxiv_id"),
                "category": (doc.get("categories") or [""])[0],
                "blocked_models": blocked_models,
                "has_summaries": list((doc.get("summaries") or {}).keys()),
            })

    # 2. Incomplete: papers missing Claude summary specifically (most common failure)
    # Uses a targeted query instead of scanning all 10K papers
    incomplete = []
    async for doc in db.papers.find(
        {
            "summaries": {"$exists": True, "$ne": {}},
            "is_latest_version": {"$ne": False},
            "summaries.anthropic:claude-opus-4-6:thinking": {"$exists": False},
        },
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "categories": 1, "summary_failures": 1},
    ).limit(100):
        incomplete.append({
            "id": doc.get("id"),
            "title": doc.get("title"),
            "arxiv_id": doc.get("arxiv_id"),
            "category": (doc.get("categories") or [""])[0],
            "missing_models": ["claude-opus-4-6:thinking"],
            "failure_counts": doc.get("summary_failures", {}),
        })

    # 3. Unprocessed: no summaries at all (recent papers awaiting pipeline)
    no_summaries = []
    async for doc in db.papers.find(
        {"$or": [{"summaries": {"$exists": False}}, {"summaries": {}}], "is_latest_version": {"$ne": False}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "categories": 1, "added_at": 1},
    ).sort("added_at", -1).limit(50):
        no_summaries.append({
            "id": doc.get("id"),
            "title": doc.get("title"),
            "arxiv_id": doc.get("arxiv_id"),
            "category": (doc.get("categories") or [""])[0],
            "added_at": doc.get("added_at"),
        })

    return {
        "refused": refused,
        "refused_count": len(refused),
        "disqualified": disqualified,
        "disqualified_count": len(disqualified),
        "incomplete": incomplete,
        "incomplete_count": len(incomplete),
        "no_summaries": no_summaries,
        "no_summaries_count": len(no_summaries),
    }


@router.post("/reset-summary-failures", dependencies=[Depends(verify_admin)])
async def reset_summary_failures(paper_id: str = None):
    """Reset summary failure counters. If paper_id given, reset that paper only. Otherwise reset all."""
    if paper_id:
        result = await db.papers.update_one({"id": paper_id}, {"$unset": {"summary_failures": ""}})
        return {"status": "ok", "reset": result.modified_count}
    else:
        result = await db.papers.update_many(
            {"summary_failures": {"$exists": True}},
            {"$unset": {"summary_failures": ""}},
        )
        return {"status": "ok", "reset": result.modified_count}




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


MODEL_PRICING = {
    "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
    "anthropic/claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "anthropic/claude-opus-4-6": {"input": 5.00, "output": 25.00},
    "gemini/gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
}



# ── Timeseries: incremental daily_stats with bounded chunk backfill ──

_EMPTY_DAY = {"papers": 0, "matches": 0, "input_tokens": 0, "output_tokens": 0,
              "cost": 0.0, "summaries": 0, "summary_cost": 0.0}

_SUMMARY_PRICING = {
    "anthropic": "anthropic/claude-opus-4-6",
    "openai": "openai/gpt-5.2",
    "gemini": "gemini/gemini-3-pro-preview",
}


def _make_day(date: str, category: str) -> dict:
    return {"date": date, "category": category, **_EMPTY_DAY}


def _price_match(inp: int, out: int, provider: str, model: str) -> float:
    mk = f"{provider}/{model}"
    p = MODEL_PRICING.get(mk, {"input": 2.0, "output": 10.0})
    return (inp / 1_000_000) * p["input"] + (out / 1_000_000) * p["output"]


_ts_backfill_running = False


def _build_series_from_daily_stats(total_by_date, cat_by_key, cats, model_totals):
    """Pure function: build the response series from daily_stats dicts."""
    from datetime import date as _date, timedelta as _td, datetime as _dt, timezone as _tz

    if not total_by_date:
        return {"series": [], "categories": cats, "computed_at": _dt.now(_tz.utc).isoformat(),
                "totals": {"papers": 0, "matches": 0, "tokens": 0, "input_tokens": 0,
                           "output_tokens": 0, "cost": 0, "match_cost": 0, "summary_cost": 0},
                "models": {}}

    start = _date.fromisoformat(min(total_by_date))
    end = _date.fromisoformat(max(total_by_date))
    dates = []
    cur = start
    while cur <= end:
        dates.append(cur.isoformat())
        cur += _td(days=1)

    series = []
    cum = {"papers": defaultdict(int), "matches": defaultdict(int),
           "tokens": defaultdict(int), "cost": defaultdict(float),
           "match_cost": defaultdict(float), "summary_cost": defaultdict(float)}

    for day in dates:
        t = total_by_date.get(day, _EMPTY_DAY)
        dtok = t.get("input_tokens", 0) + t.get("output_tokens", 0)
        d_mc = t.get("cost", 0.0)
        d_sc = t.get("summary_cost", 0.0)
        dcost = d_mc + d_sc
        cum["papers"]["_"] += t.get("papers", 0)
        cum["matches"]["_"] += t.get("matches", 0)
        cum["tokens"]["_"] += dtok
        cum["cost"]["_"] += dcost
        cum["match_cost"]["_"] += d_mc
        cum["summary_cost"]["_"] += d_sc

        e = {"date": day,
             "papers_daily": t.get("papers", 0), "papers_cumulative": cum["papers"]["_"],
             "matches_daily": t.get("matches", 0), "matches_cumulative": cum["matches"]["_"],
             "tokens_daily": dtok, "tokens_cumulative": cum["tokens"]["_"],
             "cost_daily": round(dcost, 4), "cost_cumulative": round(cum["cost"]["_"], 4),
             "match_cost_cumulative": round(cum["match_cost"]["_"], 4),
             "summary_cost_cumulative": round(cum["summary_cost"]["_"], 4),
             "input_tokens_daily": t.get("input_tokens", 0),
             "output_tokens_daily": t.get("output_tokens", 0)}

        for cat in cats:
            cd = cat_by_key.get((day, cat), _EMPTY_DAY)
            ct = cd.get("input_tokens", 0) + cd.get("output_tokens", 0)
            cc = cd.get("cost", 0.0) + cd.get("summary_cost", 0.0)
            cum["papers"][cat] += cd.get("papers", 0)
            cum["matches"][cat] += cd.get("matches", 0)
            cum["tokens"][cat] += ct
            cum["cost"][cat] += cc
            e[f"papers_daily_{cat}"] = cd.get("papers", 0)
            e[f"papers_cumulative_{cat}"] = cum["papers"][cat]
            e[f"matches_daily_{cat}"] = cd.get("matches", 0)
            e[f"matches_cumulative_{cat}"] = cum["matches"][cat]
            e[f"tokens_daily_{cat}"] = ct
            e[f"tokens_cumulative_{cat}"] = cum["tokens"][cat]
            e[f"cost_daily_{cat}"] = round(cc, 4)
            e[f"cost_cumulative_{cat}"] = round(cum["cost"][cat], 4)
        series.append(e)

    # Model costs
    for mk, ms in model_totals.items():
        p = MODEL_PRICING.get(mk, {"input": 2.0, "output": 10.0})
        ci = (ms["input_tokens"] / 1_000_000) * p["input"]
        co = (ms["output_tokens"] / 1_000_000) * p["output"]
        ms["cost_input"] = round(ci, 4)
        ms["cost_output"] = round(co, 4)
        ms["cost_total"] = round(ci + co, 4)

    total_summary_cost = sum(d.get("summary_cost", 0.0) for d in total_by_date.values())
    total_match_cost = cum["cost"]["_"] - total_summary_cost

    return {
        "series": series,
        "categories": cats,
        "computed_at": _dt.now(_tz.utc).isoformat(),
        "totals": {
            "papers": cum["papers"]["_"],
            "matches": cum["matches"]["_"],
            "tokens": cum["tokens"]["_"],
            "input_tokens": sum(s.get("input_tokens", 0) for s in model_totals.values()),
            "output_tokens": sum(s.get("output_tokens", 0) for s in model_totals.values()),
            "cost": round(cum["cost"]["_"], 4),
            "match_cost": round(total_match_cost, 4),
            "summary_cost": round(total_summary_cost, 4),
        },
        "models": model_totals,
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
    if not new_paused:
        wake_scheduler()
    return {"compare_paused": new_paused}



# --- Category Management ---

@router.get("/arxiv-categories", dependencies=[Depends(verify_admin)])
async def get_arxiv_categories():
    """Return full arXiv taxonomy for searchable category picker."""
    from core.arxiv_categories import ARXIV_TAXONOMY, get_group
    settings = await get_settings()
    active_list = settings.get("active_categories", list(CATEGORIES.keys()))
    active_set = set(active_list)
    featured_list = settings.get("featured_categories", active_list[:5])
    featured_set = set(featured_list)

    cats = []
    for cat_id, name in sorted(ARXIV_TAXONOMY.items()):
        cats.append({
            "id": cat_id,
            "name": name,
            "group": get_group(cat_id),
            "active": cat_id in active_set,
            "featured": cat_id in featured_set,
        })
    return {
        "categories": cats,
        "active": active_list,
        "featured": featured_list,
        "new_categories": settings.get("new_categories", []),
    }


class CategoryAction(BaseModel):
    category_id: str


@router.post("/categories/toggle-new", dependencies=[Depends(verify_admin)])
async def toggle_new_category(body: CategoryAction):
    """Toggle the 'new' flag for a category (shown on homepage)."""
    settings = await get_settings()
    new_cats = settings.get("new_categories", [])
    cat_id = body.category_id.strip()
    if cat_id in new_cats:
        new_cats.remove(cat_id)
    else:
        new_cats.append(cat_id)
    await db.settings.update_one(
        {"key": "global"}, {"$set": {"new_categories": new_cats}}, upsert=True
    )
    return {"new_categories": new_cats}



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

    # Pause the tournament (don't delete data)
    tid = f"cat={cat_id}|mode=standard"
    await db.tournaments.update_one(
        {"tournament_id": tid},
        {"$set": {"status": "paused", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )

    logger.info(f"Admin removed category: {cat_id}")
    return {"status": "ok", "active_categories": active}


@router.post("/categories/reorder", dependencies=[Depends(verify_admin)])
async def reorder_categories(body: dict):
    """Save a new display order for active categories."""
    new_order = body.get("category_ids", [])
    if not new_order or not isinstance(new_order, list):
        raise HTTPException(400, "category_ids must be a non-empty list")

    settings = await get_settings()
    active = set(settings.get("active_categories", []))

    # Validate: new_order must contain exactly the same IDs as current active
    if set(new_order) != active:
        raise HTTPException(400, "category_ids must contain exactly the current active categories")

    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"active_categories": new_order}},
    )
    return {"status": "ok", "active_categories": new_order}


@router.post("/categories/set-featured", dependencies=[Depends(verify_admin)])
async def set_featured_categories(body: dict):
    """Save the ordered list of featured categories (homepage tabs)."""
    featured = body.get("featured", [])
    if not isinstance(featured, list):
        raise HTTPException(400, "featured must be a list of category IDs")

    settings = await get_settings()
    active_set = set(settings.get("active_categories", []))

    # All featured must be active
    for cat_id in featured:
        if cat_id not in active_set:
            raise HTTPException(400, f"{cat_id} is not an active category")

    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"featured_categories": featured}},
        upsert=True,
    )
    return {"status": "ok", "featured": featured}


@router.post("/categories/toggle-featured", dependencies=[Depends(verify_admin)])
async def toggle_featured_category(body: CategoryAction):
    """Toggle a category's featured status. Adds to end if featuring, removes if unfeaturing."""
    cat_id = body.category_id.strip()
    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))
    if cat_id not in active:
        raise HTTPException(400, f"{cat_id} is not an active category")

    featured = settings.get("featured_categories", active[:5])
    if cat_id in featured:
        featured = [c for c in featured if c != cat_id]
    else:
        featured.append(cat_id)

    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"featured_categories": featured}},
        upsert=True,
    )
    return {"status": "ok", "featured": featured}


@router.post("/categories/reorder-featured", dependencies=[Depends(verify_admin)])
async def reorder_featured_categories(body: dict):
    """Save a new display order for featured categories only."""
    new_order = body.get("featured", [])
    if not isinstance(new_order, list):
        raise HTTPException(400, "featured must be a list")

    settings = await get_settings()
    current_featured = set(settings.get("featured_categories", settings.get("active_categories", [])[:5]))

    if set(new_order) != current_featured:
        raise HTTPException(400, "Must contain exactly the current featured categories")

    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"featured_categories": new_order}},
        upsert=True,
    )
    return {"status": "ok", "featured": new_order}


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




@router.post("/rebuild-archives", dependencies=[Depends(verify_admin)])
async def rebuild_archives():
    """Delete all archives and regenerate with correct calendar boundaries + medalist exclusion.
    Archives are derived data from rankings — no data loss risk."""
    from calendar import monthrange
    from datetime import date

    # Step 1: Delete all existing archives
    deleted = await db.leaderboard_archives.delete_many({})
    
    cats = await db.rankings.distinct("category")
    
    # Get archive_frequency setting per category
    from core.auth import get_settings
    settings_doc = await get_settings() or {}
    freq_config = settings_doc.get("archive_frequency") or {}
    default_freq = freq_config.get("default", "weekly")
    
    # Split categories by their archive type
    # If no config exists, create both weekly AND monthly for all categories
    if freq_config:
        weekly_cats = [c for c in cats if freq_config.get(c, default_freq) == "weekly"]
        monthly_cats = [c for c in cats if freq_config.get(c, default_freq) == "monthly"]
    else:
        weekly_cats = list(cats)
        monthly_cats = list(cats)
    
    # Collect all (year, week) and (year, month) from published dates
    weeks_seen = set()
    months_seen = set()
    async for r in db.rankings.find(
        {"is_latest_version": {"$ne": False}},
        {"_id": 0, "published": 1}
    ):
        pub = (r.get("published") or "")[:10]
        if not pub:
            continue
        try:
            d = date.fromisoformat(pub)
            weeks_seen.add((d.isocalendar()[0], d.isocalendar()[1]))
            months_seen.add((d.year, d.month))
        except (ValueError, TypeError):
            continue

    _RANK_FIELDS = {"_id": 0, "paper_id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                    "score": 1, "ts_score": 1, "ai_rating": 1, "wins": 1, "losses": 1,
                    "comparisons": 1, "win_rate": 1, "ci": 1, "published": 1, "link": 1,
                    "gap_score": 1, "ts_sigma": 1,
                    "os_score": 1, "os_sigma": 1, "rank_ts": 1, "rank_os": 1}
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    def _freeze(entries):
        return [
            {**{k: e.get(k) for k in ["title", "authors", "score", "ts_score", "ai_rating",
                "wins", "losses", "comparisons", "win_rate", "ci", "published", "link",
                "arxiv_id", "gap_score", "ts_sigma",
                "os_score", "os_sigma", "rank_ts", "rank_os"]},
             "rank": i, "id": e.get("paper_id")}
            for i, e in enumerate(entries, 1)
        ]

    weekly_created = 0
    monthly_created = 0

    # Step 2: Weekly archives — only for categories configured as weekly
    for year, week in sorted(weeks_seen):
        week_start = date.fromisocalendar(year, week, 1)
        week_end = week_start + timedelta(days=7)
        for cat in weekly_cats:
            entries = await db.rankings.find(
                {"category": cat, "is_latest_version": {"$ne": False},
                 "published": {"$gte": f"{week_start.isoformat()}T00:00:00",
                              "$lt": f"{week_end.isoformat()}T00:00:00"}},
                _RANK_FIELDS,
            ).sort("ts_score", -1).to_list(10000)
            if not entries:
                continue
            frozen = _freeze(entries)
            await db.leaderboard_archives.insert_one({
                "category": cat, "period_type": "weekly",
                "year": year, "week": week, "month": None,
                "label": f"Week {week}, {year}",
                "paper_count": len(frozen),
                "match_count": sum(e.get("comparisons") or 0 for e in frozen) // 2,
                "leaderboard": frozen,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            weekly_created += 1

    # Step 3: Monthly archives — only for categories configured as monthly
    for cat in monthly_cats:
        for year, month in sorted(months_seen):
            month_start = f"{year}-{month:02d}-01T00:00:00"
            next_m = month + 1 if month < 12 else 1
            next_y = year if month < 12 else year + 1
            month_end = f"{next_y}-{next_m:02d}-01T00:00:00"

            entries = await db.rankings.find(
                {"category": cat, "is_latest_version": {"$ne": False},
                 "published": {"$gte": month_start, "$lt": month_end}},
                _RANK_FIELDS,
            ).sort("ts_score", -1).to_list(10000)
            if not entries:
                continue

            frozen = _freeze(entries)
            await db.leaderboard_archives.insert_one({
                "category": cat, "period_type": "monthly",
                "year": year, "week": None, "month": month,
                "label": f"{month_names[month]} {year}",
                "paper_count": len(frozen),
                "match_count": sum(e.get("comparisons") or 0 for e in frozen) // 2,
                "leaderboard": frozen,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            monthly_created += 1

    return {
        "status": "ok",
        "deleted": deleted.deleted_count,
        "weekly_created": weekly_created,
        "monthly_created": monthly_created,
    }

@router.post("/rerank-all", dependencies=[Depends(verify_admin)])
async def rerank_all_endpoint():
    """Trigger an immediate rerank of all categories.
    Re-sorts ranks from pre-computed WR + TrueSkill scores. No match loading."""
    from services.ranking import rerank_category_light
    from core.auth import get_settings
    settings = await get_settings()
    cats = settings.get("active_categories", list(CATEGORIES.keys()))
    results = {}
    for cat in cats:
        try:
            await rerank_category_light(db, cat)
            results[cat] = "ok"
        except Exception as e:
            results[cat] = f"error: {e}"
    from routers.leaderboard import notify_data_changed
    notify_data_changed()
    return {"status": "ok", "categories": results}


@router.post("/backfill-trueskill", dependencies=[Depends(verify_admin)])
async def backfill_trueskill_endpoint(category: str = None):
    """One-time: replay historical matches through TrueSkill + compute per-model stats.
    Run per-category to avoid OOM: /api/admin/backfill-trueskill?category=cs.RO"""
    from services.ranking import backfill_trueskill, backfill_model_stats, backfill_si_ratings, rerank_category_light
    from core.auth import get_settings
    await backfill_trueskill(db, category=category)
    await backfill_model_stats(db, category=category)
    await backfill_si_ratings(db, category=category)
    # Re-sort ranks after backfill
    settings = await get_settings()
    cats = [category] if category else settings.get("active_categories", list(CATEGORIES.keys()))
    for cat in cats:
        await rerank_category_light(db, cat)
    from routers.leaderboard import notify_data_changed
    notify_data_changed()
    return {"status": "ok", "categories": cats}


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


@router.post("/normalize-ai-ratings", dependencies=[Depends(verify_admin)])
async def normalize_ai_ratings():
    """Fix ai_rating on papers and rankings:
    1. Convert any dict-typed ai_rating to a numeric score
    2. Parse ai_rating from existing Claude thinking summaries where it's missing
    3. Copy ai_rating from papers to their ranking docs
    """
    from pymongo import UpdateOne
    from services.llm import parse_ratings_from_summary
    total = 0

    # Phase 1: dict → float conversion
    for coll in (db.rankings, db.papers):
        ops = []
        async for doc in coll.find(
            {"ai_rating": {"$type": "object"}},
            {"_id": 1, "ai_rating": 1},
        ):
            score = doc["ai_rating"].get("score") if isinstance(doc["ai_rating"], dict) else None
            if score is not None:
                ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"ai_rating": round(score, 1)}}))
        if ops:
            result = await coll.bulk_write(ops, ordered=False)
            total += result.modified_count

    # Phase 2: parse from existing summaries where ai_rating is missing
    parsed = 0
    CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
    async for paper in db.papers.find(
        {"ai_rating": {"$in": [None]}, "summaries": {"$exists": True}},
        {"_id": 0, "id": 1, "summaries": 1},
    ):
        summaries = paper.get("summaries", {})
        for mk in sorted(summaries.keys(), key=lambda k: (0 if "thinking" in k else 1)):
            ratings = parse_ratings_from_summary(summaries[mk])
            if ratings:
                update = {"ai_rating": ratings["score"]}
                model_short = "claude" if "anthropic" in mk else "gpt" if "openai" in mk else "gemini" if "gemini" in mk else None
                if model_short:
                    update[f"ai_ratings_by_model.{model_short}"] = ratings
                await db.papers.update_one({"id": paper["id"]}, {"$set": update})
                await db.rankings.update_one({"paper_id": paper["id"]}, {"$set": {"ai_rating": ratings["score"]}})
                parsed += 1
                break

    # Also catch papers where ai_rating field doesn't exist at all
    async for paper in db.papers.find(
        {"ai_rating": {"$exists": False}, "summaries": {"$exists": True}},
        {"_id": 0, "id": 1, "summaries": 1},
    ):
        summaries = paper.get("summaries", {})
        for mk in sorted(summaries.keys(), key=lambda k: (0 if "thinking" in k else 1)):
            ratings = parse_ratings_from_summary(summaries[mk])
            if ratings:
                update = {"ai_rating": ratings["score"]}
                model_short = "claude" if "anthropic" in mk else "gpt" if "openai" in mk else "gemini" if "gemini" in mk else None
                if model_short:
                    update[f"ai_ratings_by_model.{model_short}"] = ratings
                await db.papers.update_one({"id": paper["id"]}, {"$set": update})
                await db.rankings.update_one({"paper_id": paper["id"]}, {"$set": {"ai_rating": ratings["score"]}})
                parsed += 1
                break

    # Phase 3: fix papers where ai_rating was set by Gemini/GPT instead of Claude.
    # Re-parse from Claude thinking summary and correct if different.
    corrected = 0
    async for paper in db.papers.find(
        {f"summaries.{CLAUDE_KEY}": {"$exists": True}, "ai_rating": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "ai_rating": 1, f"summaries.{CLAUDE_KEY}": 1},
    ):
        claude_text = paper.get("summaries", {}).get(CLAUDE_KEY, "")
        ratings = parse_ratings_from_summary(claude_text)
        if ratings and abs(paper["ai_rating"] - ratings["score"]) > 0.01:
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"ai_rating": ratings["score"], "ai_ratings_by_model.claude": ratings}}
            )
            await db.rankings.update_one(
                {"paper_id": paper["id"]},
                {"$set": {"ai_rating": ratings["score"]}}
            )
            corrected += 1

    # Phase 4: sync paper.ai_rating → ranking.ai_rating for ALL papers
    # Catches cases where the paper doc was fixed but the ranking doc wasn't updated.
    synced = 0
    from pymongo import UpdateOne
    ops = []
    async for paper in db.papers.find(
        {"ai_rating": {"$exists": True, "$ne": None, "$type": ["double", "int"]}},
        {"_id": 0, "id": 1, "ai_rating": 1},
    ):
        ops.append(UpdateOne(
            {"paper_id": paper["id"], "ai_rating": {"$ne": round(paper["ai_rating"], 1)}},
            {"$set": {"ai_rating": round(paper["ai_rating"], 1)}},
        ))
        if len(ops) >= 500:
            result = await db.rankings.bulk_write(ops, ordered=False)
            synced += result.modified_count
            ops = []
    if ops:
        result = await db.rankings.bulk_write(ops, ordered=False)
        synced += result.modified_count

    return {"status": "ok", "dict_to_float": total, "parsed_from_summary": parsed, "corrected_wrong_model": corrected, "synced_to_rankings": synced}




@router.get("/llm-errors", dependencies=[Depends(verify_admin)])
async def get_llm_errors(hours: int = 24, limit: int = 100, provider: str = None):
    """Recent LLM errors persisted by services/llm.py for production debugging."""
    from datetime import timedelta
    query = {"ts": {"$gte": datetime.now(timezone.utc) - timedelta(hours=hours)}}
    if provider:
        query["provider"] = provider
    logs = await db.llm_error_logs.find(query, {"_id": 0}).sort("ts", -1).to_list(length=limit)
    return {"logs": logs, "count": len(logs)}


@router.get("/system-logs", dependencies=[Depends(verify_admin)])
async def get_system_logs(
    level: str = None, label: str = None, event: str = None, hours: int = 24, limit: int = 2000,
):
    """Query persisted system logs (memory tracking, events). Stored 7 days.
    
    Returns all non-mem logs raw (repair_queue, fetch_cycle, events — low volume).
    For mem logs: downsamples to 1 point per minute (max RSS per bucket) to keep
    chart resolution high without sending 100K+ entries to the browser.
    Filters: level=mem|event, label=substring, event=badge_share_view|badge_image_render|...
    """
    from datetime import datetime, timezone, timedelta
    query = {"ts": {"$gte": datetime.now(timezone.utc) - timedelta(hours=hours)}}
    if level:
        query["level"] = level
    if label:
        import re as _re
        query["label"] = {"$regex": _re.escape(label), "$options": "i"}
    if event:
        query["event"] = {"$in": event.split(",")} if "," in event else event

    # Fetch non-mem logs raw (low volume: repair_queue, fetch_cycle, events)
    non_mem_query = {**query, "level": {"$ne": "mem"}} if not level else query
    non_mem_logs = []
    if not level or level != "mem":
        non_mem_logs = await db.system_logs.find(
            non_mem_query, {"_id": 0}
        ).sort("ts", -1).to_list(length=min(limit, 5000))

    # Fetch mem logs with server-side downsampling: 1 point per minute (max RSS per bucket)
    mem_logs = []
    if not level or level == "mem":
        mem_query = {**query, "level": "mem"}
        # Use aggregation to downsample: group by minute, take max RSS
        bucket_seconds = 60  # 1 minute buckets
        pipeline = [
            {"$match": mem_query},
            {"$addFields": {
                "bucket": {"$subtract": [
                    {"$toLong": "$ts"},
                    {"$mod": [{"$toLong": "$ts"}, bucket_seconds * 1000]}
                ]}
            }},
            {"$sort": {"rss_mb": -1}},
            {"$group": {
                "_id": {"bucket": "$bucket", "pod_role": {"$ifNull": ["$pod_role", "unknown"]}},
                "ts": {"$first": "$ts"},
                "rss_mb": {"$max": "$rss_mb"},
                "label": {"$first": "$label"},
                "pod_role": {"$first": {"$ifNull": ["$pod_role", "unknown"]}},
            }},
            {"$sort": {"_id.bucket": 1}},
            {"$limit": hours * 60 * 3},
        ]
        try:
            async for doc in db.system_logs.aggregate(pipeline):
                mem_logs.append({
                    "ts": doc["ts"],
                    "level": "mem",
                    "rss_mb": round(doc["rss_mb"]) if doc.get("rss_mb") else None,
                    "label": doc.get("label", ""),
                    "pod_role": doc.get("pod_role", "unknown"),
                })
        except Exception:
            # Fallback: raw query with limit if aggregation fails
            raw = await db.system_logs.find(
                mem_query, {"_id": 0}
            ).sort("ts", -1).to_list(length=min(limit, 5000))
            mem_logs = raw

    logs = non_mem_logs + mem_logs

    # Always include restart markers at full resolution (bypass downsampling).
    # "Server started" entries have low RSS and get dropped by the max-RSS grouping.
    restart_query = {
        "ts": {"$gte": datetime.now(timezone.utc) - timedelta(hours=hours)},
        "level": "mem",
        "label": "Server started",
    }
    restart_logs = await db.system_logs.find(
        restart_query, {"_id": 0}
    ).sort("ts", -1).to_list(length=hours * 10)  # ~10 restarts/hour max (generous)
    # Add any restarts not already in mem_logs (dedup by timestamp)
    existing_ts = {log.get("ts") for log in mem_logs if log.get("label") == "Server started"}
    for rl in restart_logs:
        if rl.get("ts") not in existing_ts:
            logs.append({
                "ts": rl["ts"],
                "level": "mem",
                "rss_mb": round(rl["rss_mb"]) if rl.get("rss_mb") else None,
                "label": "Server started",
            })

    # Convert datetime to ISO string
    for log in logs:
        if "ts" in log and hasattr(log["ts"], "isoformat"):
            log["ts"] = log["ts"].isoformat()
        if "rss_mb" in log and log["rss_mb"] is not None:
            log["rss_mb"] = round(log["rss_mb"])
        log.pop("_id", None)
    return {"logs": logs, "count": len(logs)}



@router.get("/arxiv-api-check", dependencies=[Depends(verify_admin)])
async def arxiv_api_check():
    """Test if the arXiv REST API is reachable from this server (not rate-limited)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": "cat:cs.RO", "max_results": "1"},
            )
            has_entry = "<entry>" in resp.text
            return {
                "status": "ok" if resp.status_code == 200 and has_entry else "blocked",
                "http_code": resp.status_code,
                "has_results": has_entry,
                "response_time_ms": round(resp.elapsed.total_seconds() * 1000),
            }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}


@router.get("/arxiv-health", dependencies=[Depends(verify_admin)])
async def arxiv_health():
    """arXiv ingestion health per active category."""
    settings = await get_settings()
    active = [c for c in (settings.get("active_categories") or list(CATEGORIES.keys())) if c and c.strip()]
    now = datetime.now(timezone.utc)

    rows = []
    for cat in sorted(active):
        ck = cat.replace(".", "_")
        last_fetch = settings.get(f"last_fetch_at_{ck}")
        if not isinstance(last_fetch, str):
            last_fetch = None
        last_fail = await db.system_logs.find_one(
            {"event": "fetch_cycle", "category": cat, "success": False},
            sort=[("ts", -1)], projection={"_id": 0, "ts": 1, "detail": 1, "reason": 1})
        last_success = await db.system_logs.find_one(
            {"event": "fetch_cycle", "category": cat, "success": True},
            sort=[("ts", -1)], projection={"_id": 0, "ts": 1})
        # Status: compare last success vs last failure
        if not last_fetch:
            status = "never"
        elif last_fail and (not last_success or last_fail.get("ts", "") > last_success.get("ts", "")):
            status = "error"
        else:
            status = "healthy"
        lf_ts = last_fail.get("ts") if last_fail else None
        rows.append({
            "category": cat,
            "status": status,
            "last_fetch_at": last_fetch,
            "last_error": last_fail.get("detail") if last_fail else None,
            "last_error_reason": last_fail.get("reason") if last_fail else None,
            "last_error_at": lf_ts.isoformat() if hasattr(lf_ts, "isoformat") else lf_ts,
        })
    return {
        "now": now.isoformat(),
        "categories": rows,
        "healthy": sum(1 for r in rows if r["status"] == "healthy"),
        "error": sum(1 for r in rows if r["status"] == "error"),
        "never": sum(1 for r in rows if r["status"] == "never"),
    }



@router.get("/category-status", dependencies=[Depends(verify_admin)])
async def category_status():
    """Category status dashboard: fetch health, paper/match counts, tournament state."""
    from services.scheduler import _fetching_cats, _get_cat_status
    settings = await get_settings()
    active = sorted(c for c in (settings.get("active_categories") or []) if c and c.strip())
    interval = settings.get("fetch_interval_hours", 6)
    now = datetime.now(timezone.utc)

    # Batch-load tournament docs for all categories
    t_docs = {}
    async for t in db.tournaments.find(
        {"category": {"$in": active}},
        {"_id": 0, "category": 1, "status": 1, "fetch_paused": 1, "compare_paused": 1},
    ):
        t_docs[t["category"]] = t

    # Batch-load last fetch_cycle log per category
    last_logs = {}
    async for doc in db.system_logs.aggregate([
        {"$match": {"event": "fetch_cycle", "category": {"$in": active}}},
        {"$sort": {"ts": -1}},
        {"$group": {
            "_id": "$category",
            "ts": {"$first": "$ts"},
            "success": {"$first": "$success"},
            "count": {"$first": "$count"},
            "detail": {"$first": "$detail"},
            "reason": {"$first": "$reason"},
        }},
    ]):
        last_logs[doc["_id"]] = doc

    # Batch-load paper + match counts
    paper_counts = {}
    async for doc in db.rankings.aggregate([
        {"$match": {"category": {"$in": active}}},
        {"$group": {"_id": "$category", "papers": {"$sum": 1}}},
    ]):
        paper_counts[doc["_id"]] = doc["papers"]

    match_counts = {}
    async for doc in db.matches.aggregate([
        {"$match": {"primary_category": {"$in": active}, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": "$primary_category", "matches": {"$sum": 1}}},
    ]):
        match_counts[doc["_id"]] = doc["matches"]

    rows = []
    for cat in active:
        ck = cat.replace(".", "_")
        last_fetch = settings.get(f"last_fetch_at_{ck}")
        if not isinstance(last_fetch, str):
            last_fetch = None

        t = t_docs.get(cat, {})
        fetch_paused = bool(t.get("fetch_paused"))
        tournament_paused = t.get("status") == "paused"

        is_fetching = cat in _fetching_cats
        last_log = last_logs.get(cat)
        last_failed = last_log and last_log.get("success") is False

        if is_fetching:
            status = "fetching"
        elif fetch_paused:
            status = "fetch_paused"
        elif tournament_paused:
            status = "tournament_paused"
        elif not last_fetch:
            status = "never"
        elif last_failed:
            status = "fetch_failed"
        elif last_fetch and now >= datetime.fromisoformat(last_fetch) + timedelta(hours=interval):
            status = "overdue"
        else:
            status = "up_to_date"

        next_due = None
        if last_fetch:
            due_at = datetime.fromisoformat(last_fetch) + timedelta(hours=interval)
            next_due = due_at.isoformat()

        last_action = None
        last_action_at = None
        if last_log:
            log_ts = last_log.get("ts", "")
            new_count = last_log.get("count") or 0
            if last_log.get("success") is False:
                reason = last_log.get("reason", "error")
                last_action = f"Failed: {reason}"
            elif new_count > 0:
                last_action = f"+{new_count} papers"
            else:
                last_action = "No new papers"
            last_action_at = log_ts.isoformat() if hasattr(log_ts, "isoformat") else str(log_ts)

        rows.append({
            "category": cat,
            "status": status,
            "papers": paper_counts.get(cat, 0),
            "matches": match_counts.get(cat, 0),
            "last_fetch_at": last_fetch,
            "next_due": next_due,
            "last_action": last_action,
            "last_action_at": last_action_at,
            "fetch_paused": fetch_paused,
            "tournament_paused": tournament_paused,
        })

    summary = {}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    return {"now": now.isoformat(), "interval_hours": interval, "categories": rows, "summary": summary}


@router.post("/fix-oai-dates", dependencies=[Depends(verify_admin)])
async def fix_oai_dates(dry_run: bool = True, phase: int = 0, category: str = ""):
    """OAI-PMH migration: repair 2026 dates (phase=1) + remove pre-2026 ghosts (phase=2)
    + recompute TrueSkill (phase=3). phase=0 runs all. Pass ?dry_run=false to apply.
    For phase=3, pass ?category=cs.AI to run one category at a time."""
    from scripts.fix_oai_dates import run_migration
    return await run_migration(dry_run=dry_run, phase=phase, category=category)


@router.post("/cleanup-stale-tournaments", dependencies=[Depends(verify_admin)])
async def cleanup_stale_tournaments(dry_run: bool = True):
    """Remove tournament docs for categories no longer in active_categories."""
    from core.auth import get_settings
    settings = await get_settings()
    active = set(settings.get("active_categories", []))
    all_tournaments = await db.tournaments.find(
        {}, {"_id": 1, "category": 1, "tournament_id": 1, "status": 1}
    ).to_list(500)
    stale = [t for t in all_tournaments if t.get("category") not in active]
    if dry_run:
        return {"dry_run": True, "stale_count": len(stale),
                "stale": [{"category": t["category"], "status": t.get("status")} for t in stale]}
    ids = [t["_id"] for t in stale]
    result = await db.tournaments.delete_many({"_id": {"$in": ids}})
    return {"deleted": result.deleted_count,
            "categories": [t["category"] for t in stale]}



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
async def create_all_snapshots(year: int = None, month: int = None, week: int = None):
    """Create archive snapshots for all active categories.
    - No params: creates for the previous period (default behavior)
    - year+month: creates monthly archives for that specific month
    - year+week: creates weekly archives for that specific week
    Respects archive_frequency settings. Idempotent (skips existing)."""
    from routers.leaderboard import create_archive_snapshot
    settings = await get_settings()
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))
    archive_config = settings.get("archive_frequency") or {}
    default_freq = archive_config.get("default", "weekly")
    created = 0

    if year and (month or week):
        # Specific period requested — create for ALL active categories regardless of frequency setting.
        # Historical rebuilds shouldn't be filtered by CURRENT frequency config
        # (a category's frequency may have changed since that period).
        period_type = "monthly" if month else "weekly"
        for cat in active_cats:
            result = await create_archive_snapshot(cat, period_type, year=year, week=week, month=month)
            if result:
                created += 1
        return {"status": "ok", "created": created, "period_type": period_type, "year": year, "week": week, "month": month}
    else:
        # Default: previous period
        for cat in active_cats:
            freq = archive_config.get(cat, default_freq)
            result = await create_archive_snapshot(cat, freq)
            if result:
                created += 1
        return {"status": "ok", "created": created, "categories": len(active_cats)}



@router.post("/ensure-indexes", dependencies=[Depends(verify_admin)])
async def ensure_indexes():
    """Force creation of all required indexes. Safe to call multiple times."""
    results = []
    try:
        await db.papers.create_index("arxiv_id_base", name="arxiv_id_base", sparse=True)
        results.append("papers.arxiv_id_base: OK")
    except Exception as e:
        results.append(f"papers.arxiv_id_base: {e}")
    try:
        await db.papers.create_index("categories.0", name="primary_category")
        results.append("papers.categories.0: OK")
    except Exception as e:
        results.append(f"papers.categories.0: {e}")
    try:
        await db.matches.create_index([("primary_category", 1), ("completed", 1), ("created_at", -1)], name="cat_completed_recent")
        results.append("matches.cat_completed_recent: OK")
    except Exception as e:
        results.append(f"matches.cat_completed_recent: {e}")
    try:
        await db.rankings.create_index([("category", 1), ("os_score", -1)], name="category_1_os_score_-1")
        results.append("rankings.category_os_score: OK")
    except Exception as e:
        results.append(f"rankings.category_os_score: {e}")
    return {"results": results}




@router.post("/archive/dedupe", dependencies=[Depends(verify_admin)])
async def dedupe_archives():
    """Remove duplicate leaderboard snapshots (same category/period_type/year/week/
    month), keeping the most complete copy, and (re)enforce the unique index that
    prevents recurrence. Safe and idempotent — returns how many were removed."""
    from routers.leaderboard import ensure_archive_integrity
    before = await db.leaderboard_archives.count_documents({})
    await ensure_archive_integrity()
    after = await db.leaderboard_archives.count_documents({})
    return {"status": "ok", "removed": before - after, "remaining": after}


@router.delete("/archive/week/{year}/{week}", dependencies=[Depends(verify_admin)])
async def delete_weekly_archive(year: int, week: int, force: bool = False):
    """Delete all weekly archive snapshots for a specific ISO week.
    Blocks deletion if archives use a different scoring method than current (prevents accidental history rewrite).
    Use force=true to override."""
    if not force:
        settings = await get_settings()
        current_scoring = settings.get("scoring_method", "ts")
        sample = await db.leaderboard_archives.find_one(
            {"period_type": "weekly", "year": year, "week": week},
            {"_id": 0, "scoring_method": 1})
        if sample and sample.get("scoring_method") and sample["scoring_method"] != current_scoring:
            raise HTTPException(400,
                f"These archives use scoring method '{sample['scoring_method']}' but current is '{current_scoring}'. "
                f"Rebuilding would rewrite history with a different method. Use force=true to override.")

    result = await db.leaderboard_archives.delete_many(
        {"period_type": "weekly", "year": year, "week": week}
    )
    logger.info(f"Deleted {result.deleted_count} weekly archives for {year}-W{week}")
    return {"status": "ok", "deleted": result.deleted_count, "period": f"{year}-W{week}"}


@router.delete("/archive/month/{year}/{month}", dependencies=[Depends(verify_admin)])
async def delete_monthly_archive(year: int, month: int, force: bool = False):
    """Delete all monthly archive snapshots for a specific month.
    Blocks deletion if archives use a different scoring method than current.
    Use force=true to override."""
    if not force:
        settings = await get_settings()
        current_scoring = settings.get("scoring_method", "ts")
        sample = await db.leaderboard_archives.find_one(
            {"period_type": "monthly", "year": year, "month": month},
            {"_id": 0, "scoring_method": 1})
        if sample and sample.get("scoring_method") and sample["scoring_method"] != current_scoring:
            raise HTTPException(400,
                f"These archives use scoring method '{sample['scoring_method']}' but current is '{current_scoring}'. "
                f"Rebuilding would rewrite history with a different method. Use force=true to override.")

    result = await db.leaderboard_archives.delete_many(
        {"period_type": "monthly", "year": year, "month": month}
    )
    logger.info(f"Deleted {result.deleted_count} monthly archives for {year}-{month:02d}")
    return {"status": "ok", "deleted": result.deleted_count, "period": f"{year}-{month:02d}"}


@router.post("/archive/rerank-all", dependencies=[Depends(verify_admin)])
async def rerank_all_archives():
    """Migrate all archives to the new format:
    - Sort leaderboard array by score descending (rank = array position)
    - Set entry.score = ts_score (the authoritative score)
    - Remove only truly stale fields (rank, ranking_score, rank_ts, rank_os)
    - Keep ci, wilson_margin, gap_score, ts_sigma etc for display
    - Add scoring_method: 'ts' to archive document
    """
    fixed = 0
    async for doc in db.leaderboard_archives.find({}, {"_id": 1, "leaderboard": 1, "scoring_method": 1}):
        lb = doc.get("leaderboard", [])
        if not lb:
            continue

        # Sort by ts_score desc (or score as fallback) — this makes array position = rank
        sorted_lb = sorted(lb, key=lambda p: p.get("ts_score") or p.get("score") or 0, reverse=True)

        # Normalize each entry: set score = ts_score, remove ONLY redundant rank fields
        for entry in sorted_lb:
            entry["score"] = entry.get("ts_score") or entry.get("score") or 0
            for stale_field in ["rank", "ranking_score", "rank_ts", "rank_os"]:
                entry.pop(stale_field, None)

        await db.leaderboard_archives.update_one(
            {"_id": doc["_id"]},
            {"$set": {"leaderboard": sorted_lb, "scoring_method": "ts"}},
        )
        fixed += 1

    logger.info(f"Migrated {fixed} archives to position-based ranking")


@router.post("/archive/repair-fields", dependencies=[Depends(verify_admin)])
async def repair_archive_fields():
    """Re-populate missing fields (ts_sigma, gap_score, ci, wilson_margin, os_score, os_sigma)
    from the live rankings collection. Fixes data lost during migration."""
    repaired = 0
    async for doc in db.leaderboard_archives.find({}, {"_id": 1, "leaderboard": 1}):
        lb = doc.get("leaderboard", [])
        if not lb:
            continue
        changed = False
        paper_ids = [p.get("id") for p in lb if p.get("id")]
        # Batch fetch rankings for all papers in this archive
        rankings = {}
        async for r in db.rankings.find(
            {"paper_id": {"$in": paper_ids}},
            {"_id": 0, "paper_id": 1, "ts_sigma": 1, "gap_score": 1,
             "ci": 1, "wilson_margin": 1, "os_score": 1, "os_sigma": 1}
        ):
            rankings[r["paper_id"]] = r

        for entry in lb:
            pid = entry.get("id")
            r = rankings.get(pid, {})
            # Only fill in fields that are missing from the archive entry
            for field in ["ts_sigma", "gap_score", "ci", "wilson_margin", "os_score", "os_sigma"]:
                if field not in entry and r.get(field) is not None:
                    entry[field] = r[field]
                    changed = True

        if changed:
            await db.leaderboard_archives.update_one(
                {"_id": doc["_id"]},
                {"$set": {"leaderboard": lb}},
            )
            repaired += 1

    logger.info(f"Repaired fields on {repaired} archives")
    return {"status": "ok", "repaired": repaired}

    return {"status": "ok", "migrated": fixed}




@router.post("/archive/set-frequency", dependencies=[Depends(verify_admin)])
async def set_archive_frequency(request: Request):
    """Set which archive type to DISPLAY per category (weekly or monthly).
    Both types are always computed and stored — this only controls the dropdown."""
    body = await request.json()
    settings = await get_settings()
    archive_config = settings.get("archive_frequency") or {}

    if "default" in body:
        archive_config["default"] = body["default"]
    if "category" in body and "frequency" in body:
        archive_config[body["category"]] = body["frequency"]

    await db.settings.update_one({"key": "global"}, {"$set": {"archive_frequency": archive_config}})
    return {"status": "ok", "archive_frequency": archive_config}

    await db.settings.update_one({"key": "global"}, {"$set": {"archive_frequency": archive_config}})
    return {"status": "ok", "archive_frequency": archive_config}


@router.get("/archive/frequency", dependencies=[Depends(verify_admin)])
async def get_archive_frequency():
    """Get current archive frequency settings."""
    settings = await get_settings()
    return settings.get("archive_frequency") or {"default": "weekly"}


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
        {"completed": True, "failed": {"$ne": True}},
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
        """Compute ranked list for cat_papers using only matches created before cutoff."""
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
            _wr_vals = _np.array([e["score"] for e in entries_with_both])
            _si_vals = _np.array([e["ai_rating"] for e in entries_with_both])
            _wr_pct = _sp_stats.rankdata(_wr_vals) / len(entries_with_both) * 100
            _si_pct = _sp_stats.rankdata(_si_vals) / len(entries_with_both) * 100
            _gap_raw = _wr_pct - _si_pct
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
        {p["id"] for p in all_cat_papers}
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



@router.post("/prune-duplicate-matches")
async def prune_duplicate_matches(request: Request, category: str = Query("cs.CR"), scope: str = Query("recent")):
    """Remove duplicate matches (keep 1 per pair). 
    scope=recent: only recent papers (48h window). scope=all: entire category."""
    from core.config import db
    from datetime import datetime, timedelta

    if scope == "all":
        # Full category dedup — no paper filter
        pipeline = [
            {"$match": {
                "completed": True, "failed": {"$ne": True},
                "primary_category": category,
            }},
            {"$sort": {"created_at": 1}},
            {"$group": {
                "_id": {"pair": {"$cond": {
                    "if": {"$lt": ["$paper1_id", "$paper2_id"]},
                    "then": {"a": "$paper1_id", "b": "$paper2_id"},
                    "else": {"a": "$paper2_id", "b": "$paper1_id"},
                }}},
                "match_ids": {"$push": "$id"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
        ]

        to_delete = []
        async for doc in db.matches.aggregate(pipeline):
            to_delete.extend(doc["match_ids"][1:])

        total_deleted = 0
        if to_delete:
            import asyncio
            for i in range(0, len(to_delete), 500):
                batch = to_delete[i:i + 500]
                result = await db.matches.delete_many({"id": {"$in": batch}})
                total_deleted += result.deleted_count
                await asyncio.sleep(0)

        if total_deleted > 0:
            from services.ranking import rerank_category, backfill_model_stats
            from core.memlog import force_gc
            await rerank_category(db, category)
            await backfill_model_stats(db, category=category)
            force_gc()

        logger.info(f"[prune-all] {category}: removed {total_deleted} duplicate matches (full category)")
        return {"status": "ok", "category": category, "scope": "all", "total_deleted": total_deleted}

    # Original recent-only logic
    latest = await db.rankings.find_one(
        {"category": category, "added_at": {"$nin": ["", None]}},
        {"_id": 0, "added_at": 1},
        sort=[("added_at", -1)],
    )
    if not latest or not latest.get("added_at"):
        return {"status": "error", "message": f"No papers with added_at found in {category}"}

    anchor_dt = datetime.fromisoformat(latest["added_at"].replace("Z", "+00:00"))
    cutoff = (anchor_dt - timedelta(hours=48)).isoformat()

    recent_paper_ids = set()
    async for doc in db.rankings.find(
        {"category": category, "added_at": {"$gte": cutoff}},
        {"_id": 0, "paper_id": 1},
    ):
        recent_paper_ids.add(doc["paper_id"])

    if not recent_paper_ids:
        return {"status": "error", "message": "No recent papers found"}

    logger.info(f"[prune] cs.CR recent papers: {len(recent_paper_ids)} (added after {cutoff[:19]})")

    # Find duplicate matches involving at least one recent paper
    pipeline = [
        {"$match": {
            "completed": True, "failed": {"$ne": True},
            "primary_category": category,
            "$or": [
                {"paper1_id": {"$in": list(recent_paper_ids)}},
                {"paper2_id": {"$in": list(recent_paper_ids)}},
            ],
        }},
        {"$sort": {"created_at": 1}},
        {"$group": {
            "_id": {
                "pair": {"$cond": {
                    "if": {"$lt": ["$paper1_id", "$paper2_id"]},
                    "then": {"a": "$paper1_id", "b": "$paper2_id"},
                    "else": {"a": "$paper2_id", "b": "$paper1_id"},
                }},
            },
            "match_ids": {"$push": "$id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]

    to_delete = []
    async for doc in db.matches.aggregate(pipeline):
        ids_to_remove = doc["match_ids"][1:]
        to_delete.extend(ids_to_remove)

    total_deleted = 0
    if to_delete:
        import asyncio
        batch_size = 500
        for i in range(0, len(to_delete), batch_size):
            batch = to_delete[i:i + batch_size]
            result = await db.matches.delete_many({"id": {"$in": batch}})
            total_deleted += result.deleted_count
            await asyncio.sleep(0)

        logger.info(f"[prune] [{category}] Pruned {total_deleted} duplicate matches from {len(recent_paper_ids)} recent papers")

        # Rerank cs.CR
        from services.ranking import rerank_category
        from core.memlog import force_gc
        try:
            await rerank_category(db, category)
            logger.info(f"[prune] [{category}] Reranked after pruning")
        except Exception as e:
            logger.warning(f"[prune] [{category}] Rerank failed: {e}")
        force_gc()

    logger.info(f"[prune] Complete: {total_deleted} duplicate matches removed from {category} recent ({len(recent_paper_ids)} papers)")
    return {
        "status": "ok",
        "total_deleted": total_deleted,
        "category": category,
        "recent_papers": len(recent_paper_ids),
        "cutoff": cutoff[:19],
    }



@router.post("/recompute-model-analysis", dependencies=[Depends(verify_admin)])
async def recompute_model_analysis():
    """Trigger model analysis precomputation immediately."""
    from services.precompute_analysis import precompute_model_analysis
    asyncio.create_task(precompute_model_analysis())
    return {"status": "started", "message": "Precomputation running in background"}


@router.post("/clear-experiment-cache")
async def clear_experiment_cache(request: Request, name: str = Query(None)):
    """Reload a specific experiment cache from precomputed JSON (or all).
    This restores the precomputed result rather than forcing a live recomputation."""
    from services.precompute import _load_experiments
    from routers.human_ai_benchmark import (
        _benchmark_fixed_cache, _benchmark_unfiltered_cache,
        _ranking_quality_cache, _ranking_quality_unfiltered_cache,
        _gap_analysis_cache,
    )
    caches = {
        "human-ai-benchmark-fixed": _benchmark_fixed_cache,
        "human-ai-benchmark-unfiltered": _benchmark_unfiltered_cache,
        "ai-ranking-quality": _ranking_quality_cache,
        "ai-ranking-quality-unfiltered": _ranking_quality_unfiltered_cache,
        "ai-ranking-gap-analysis": _gap_analysis_cache,
    }
    if name and name in caches:
        caches[name].clear()
    elif not name:
        for c in caches.values():
            c.clear()
    else:
        return {"status": "error", "message": f"Unknown cache: {name}", "available": list(caches.keys())}

    # Reload all experiment caches from precomputed JSON
    reloaded = _load_experiments()
    cleared = name if name else list(caches.keys())
    return {"status": "ok", "cleared": cleared, "reloaded_from_json": reloaded}


_openskill_compute_lock = asyncio.Lock()

@router.post("/refresh-openskill", dependencies=[Depends(verify_admin)])
async def refresh_openskill(request: Request, category: str = Query(None)):
    """Recompute OpenSkill cache for a category (or __all__). Queued sequentially."""
    cat_key = category or "__all__"
    from services.model_analysis import compute_openskill_cache

    if _openskill_compute_lock.locked():
        return {"status": "queued", "category": cat_key, "message": "Another OpenSkill computation is running. This will start after it finishes."}

    async def _compute():
        async with _openskill_compute_lock:
            try:
                logger.info(f"Computing OpenSkill cache for {cat_key}...")
                result = await compute_openskill_cache(category)
                if result.get("status") == "ok":
                    await db.analysis_store.update_one(
                        {"_type": "openskill-cache", "key": cat_key},
                        {"$set": {**result, "_type": "openskill-cache", "key": cat_key}},
                        upsert=True,
                    )
                    logger.info(f"OpenSkill cache updated for {cat_key} ({result.get('compute_time_s', '?')}s)")
            except Exception as e:
                logger.error(f"OpenSkill cache compute failed for {cat_key}: {e}")

    asyncio.create_task(_compute())
    return {"status": "started", "category": cat_key}


@router.post("/clear-analysis-cache", dependencies=[Depends(verify_admin)])
async def clear_analysis_cache(request: Request, type: str = Query(None), key: str = Query(None)):
    """Clear cached analysis results from analysis_store (MongoDB).
    Pass ?type=model-analysis&key=cs.RO to clear one category, or ?type=model-analysis for all of that type."""
    from core.config import db
    if type and key:
        result = await db.analysis_store.delete_many({"_type": type, "key": key})
        logger.info(f"Admin cleared analysis cache: type={type}, key={key}, deleted={result.deleted_count}")
        return {"status": "ok", "type": type, "key": key, "deleted": result.deleted_count}
    elif type:
        result = await db.analysis_store.delete_many({"_type": type})
        logger.warning(f"Admin cleared ALL analysis cache for type={type}, deleted={result.deleted_count}")
        return {"status": "ok", "type": type, "deleted": result.deleted_count}
    else:
        result = await db.analysis_store.delete_many({})
        logger.warning(f"Admin cleared ENTIRE analysis_store, deleted={result.deleted_count}")
        return {"status": "ok", "type": "all", "deleted": result.deleted_count}


@router.post("/cap-paper-matches", dependencies=[Depends(verify_admin)])
async def cap_paper_matches(request: Request, category: str = Query(...), cap: int = Query(...), dry_run: bool = Query(False)):
    """Cap per-paper match count. For papers exceeding the cap, keeps the oldest
    matches and deletes the newest. Then reranks and backfills model_stats.
    Use dry_run=true to preview without deleting."""
    from core.config import db
    from collections import defaultdict

    paper_matches = defaultdict(list)
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True},
         "primary_category": category},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "created_at": 1},
    ):
        paper_matches[m["paper1_id"]].append((m["id"], m.get("created_at", "")))
        paper_matches[m["paper2_id"]].append((m["id"], m.get("created_at", "")))

    to_delete = set()
    affected_papers = 0
    for pid, matches in paper_matches.items():
        if len(matches) <= cap:
            continue
        affected_papers += 1
        sorted_m = sorted(matches, key=lambda x: x[1])
        for mid, _ in sorted_m[cap:]:
            to_delete.add(mid)

    # Count collateral: papers under cap that would lose matches
    collateral = 0
    worst_collateral = []
    for pid, matches in paper_matches.items():
        if len(matches) <= cap:
            lost = sum(1 for mid, _ in matches if mid in to_delete)
            if lost > 0:
                collateral += 1
                worst_collateral.append({"before": len(matches), "lost": lost, "after": len(matches) - lost})
    worst_collateral.sort(key=lambda x: -x["lost"])

    if dry_run:
        return {
            "status": "dry_run", "category": category, "cap": cap,
            "affected_papers": affected_papers,
            "matches_to_delete": len(to_delete),
            "collateral_papers": collateral,
            "worst_collateral": worst_collateral[:5],
        }

    total_deleted = 0
    if to_delete:
        import asyncio
        id_list = list(to_delete)
        for i in range(0, len(id_list), 500):
            batch = id_list[i:i + 500]
            result = await db.matches.delete_many({"id": {"$in": batch}})
            total_deleted += result.deleted_count
            await asyncio.sleep(0)

    if total_deleted > 0:
        from services.ranking import rerank_category, backfill_model_stats
        from core.memlog import force_gc
        await rerank_category(db, category)
        await backfill_model_stats(db, category=category)
        force_gc()
        logger.info(f"[cap] {category}: capped at {cap}, deleted {total_deleted} matches from {affected_papers} papers, reranked + backfilled")

    return {
        "status": "ok", "category": category, "cap": cap,
        "affected_papers": affected_papers, "deleted": total_deleted,
        "collateral_papers": collateral,
    }


@router.post("/prune-storm-matches", dependencies=[Depends(verify_admin)])
async def prune_storm_matches(request: Request, category: str = Query(...), dry_run: bool = Query(False)):
    """Remove storm-day matches for over-matched papers.

    1. Finds storm dates: days where any paper received >20 matches
    2. For papers above median match count, deletes their matches from storm dates
    3. Papers at/below median are untouched
    4. Reranks and backfills model_stats
    """
    from core.config import db
    from collections import defaultdict, Counter

    # Load all matches with dates
    paper_matches = defaultdict(list)  # pid -> [(match_id, date_str, created_at)]
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True},
         "primary_category": category},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "created_at": 1},
    ):
        ts = m.get("created_at", "")
        date = ts[:10] if ts else ""
        paper_matches[m["paper1_id"]].append((m["id"], date, ts))
        paper_matches[m["paper2_id"]].append((m["id"], date, ts))

    # Find storm dates: days where ANY paper got >20 matches
    paper_date_counts = defaultdict(Counter)  # pid -> {date: count}
    for pid, matches in paper_matches.items():
        for mid, date, ts in matches:
            paper_date_counts[pid][date] += 1

    storm_dates = set()
    for pid, date_counts in paper_date_counts.items():
        for date, count in date_counts.items():
            if count > 20:
                storm_dates.add(date)

    if not storm_dates:
        return {"status": "ok", "message": "No storm dates found", "category": category}

    # Find median match count
    match_counts = sorted(len(m) for m in paper_matches.values())
    median = match_counts[len(match_counts) // 2]

    # For papers above median, collect storm-date match IDs for deletion
    to_delete = set()
    affected_papers = 0
    for pid, matches in paper_matches.items():
        if len(matches) <= median:
            continue
        storm_matches = [mid for mid, date, ts in matches if date in storm_dates]
        if storm_matches:
            affected_papers += 1
            to_delete.update(storm_matches)

    # Count collateral
    collateral = 0
    worst_collateral = []
    for pid, matches in paper_matches.items():
        if len(matches) <= median:
            lost = sum(1 for mid, date, ts in matches if mid in to_delete)
            if lost > 0:
                collateral += 1
                worst_collateral.append({"before": len(matches), "lost": lost, "after": len(matches) - lost})
    worst_collateral.sort(key=lambda x: -x["lost"])

    if dry_run:
        return {
            "status": "dry_run", "category": category,
            "storm_dates": sorted(storm_dates),
            "median_matches": median,
            "affected_papers": affected_papers,
            "matches_to_delete": len(to_delete),
            "collateral_papers": collateral,
            "worst_collateral": worst_collateral[:5],
        }

    total_deleted = 0
    if to_delete:
        import asyncio
        id_list = list(to_delete)
        for i in range(0, len(id_list), 500):
            batch = id_list[i:i + 500]
            result = await db.matches.delete_many({"id": {"$in": batch}})
            total_deleted += result.deleted_count
            await asyncio.sleep(0)

    if total_deleted > 0:
        from services.ranking import rerank_category, backfill_model_stats
        from core.memlog import force_gc
        await rerank_category(db, category)
        await backfill_model_stats(db, category=category)
        force_gc()
        logger.info(f"[storm-prune] {category}: removed {total_deleted} storm matches from {affected_papers} papers, storm dates: {sorted(storm_dates)}")

    return {
        "status": "ok", "category": category,
        "storm_dates": sorted(storm_dates),
        "median_matches": median,
        "affected_papers": affected_papers,
        "deleted": total_deleted,
        "collateral_papers": collateral,
    }


@router.post("/run-backfill/{name}", dependencies=[Depends(verify_admin)])
async def run_backfill(name: str):
    """Run a named backfill script. Admin only."""
    import asyncio
    if name == "model_openskill":
        from scripts.backfill_model_openskill import main as backfill_fn
        asyncio.create_task(_run_backfill_bg("model_openskill", backfill_fn))
        return {"status": "started", "backfill": "model_openskill"}
    elif name == "archive_scores":
        from scripts.backfill_archive_scores import main as backfill_fn
        asyncio.create_task(_run_backfill_bg("archive_scores", backfill_fn))
        return {"status": "started", "backfill": "archive_scores"}
    elif name == "si_ratings":
        from scripts.backfill_model_openskill import backfill_si_ratings
        asyncio.create_task(_run_backfill_bg("si_ratings", backfill_si_ratings))
        return {"status": "started", "backfill": "si_ratings"}
    else:
        return {"status": "error", "message": f"Unknown backfill: {name}. Available: model_openskill, archive_scores"}

_backfill_status = {}

async def _run_backfill_bg(name, fn):
    import time
    _backfill_status[name] = {"status": "running", "started_at": time.time()}
    try:
        await fn()
        _backfill_status[name] = {"status": "completed", "elapsed": round(time.time() - _backfill_status[name]["started_at"], 1)}
        logger.info(f"Backfill {name} completed in {_backfill_status[name]['elapsed']}s")
    except Exception as e:
        _backfill_status[name] = {"status": "failed", "error": str(e)[:200]}
        logger.error(f"Backfill {name} failed: {e}")

@router.get("/backfill-status/{name}", dependencies=[Depends(verify_admin)])
async def get_backfill_status(name: str):
    return _backfill_status.get(name, {"status": "not_started"})


@router.post("/run-audit", dependencies=[Depends(verify_admin)])
async def run_data_audit():
    """Run comprehensive data integrity audit in background."""
    from services.data_audit import run_audit

    async def _run():
        _backfill_status["audit"] = {"status": "running", "started_at": _time.time()}
        try:
            results = await run_audit()
            total_failed = sum(r["failed"] for r in results.values())
            _backfill_status["audit"] = {
                "status": "passed" if total_failed == 0 else "failed",
                "total_failed": total_failed,
                "results": results,
                "elapsed": round(_time.time() - _backfill_status["audit"]["started_at"], 1),
            }
        except Exception as e:
            _backfill_status["audit"] = {"status": "error", "error": str(e)[:500]}

    asyncio.create_task(_run())
    return {"status": "started", "check_status": "/api/admin/backfill-status/audit"}



# ─── Revision Feed (debugging) ─────────────────────────────────────────────

@router.get("/revision-feed")
async def get_revision_feed(admin=Depends(verify_admin), limit: int = Query(50, le=200)):
    """Return papers grouped by arxiv_id_base where more than one version exists.

    Lists "paper families" — arXiv base IDs with 2+ standalone paper documents
    (the new standalone-paper-per-version model). Also surfaces legacy
    in-place revised papers (those with a non-empty `version_history` array)
    for reverse compatibility.
    """
    families = []

    # Families from the NEW standalone-paper-per-version model —
    # arxiv_id_base with 2+ papers.
    async for group in db.papers.aggregate([
        {"$match": {"arxiv_id_base": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": "$arxiv_id_base",
            "n": {"$sum": 1},
            "versions": {"$push": {
                "id": "$id",
                "arxiv_id": "$arxiv_id",
                "version": "$current_version",
                "is_latest_version": "$is_latest_version",
                "title": "$title",
                "frozen_at": "$frozen_at",
                "added_at": "$added_at",
                "categories": "$categories",
            }},
        }},
        {"$match": {"n": {"$gt": 1}}},
        {"$sort": {"_id": 1}},
        {"$limit": limit},
    ]):
        versions = sorted(group["versions"], key=lambda v: v.get("version") or 1)
        latest = next((v for v in versions if v.get("is_latest_version") is not False), versions[-1])
        ranking = await db.rankings.find_one(
            {"paper_id": latest["id"]},
            {"_id": 0, "rank_ts": 1, "ts_score": 1, "comparisons": 1, "win_rate": 1}
        ) or {}
        match_count = await db.matches.count_documents({
            "$or": [{"paper1_id": latest["id"]}, {"paper2_id": latest["id"]}],
            "completed": True, "failed": {"$ne": True},
        })
        families.append({
            "source": "standalone_versions",
            "arxiv_id_base": group["_id"],
            "title": latest.get("title", ""),
            "category": (latest.get("categories") or ["?"])[0],
            "latest_paper_id": latest["id"],
            "latest_arxiv_id": latest.get("arxiv_id"),
            "latest_version": latest.get("version"),
            "total_versions": len(versions),
            "active_matches": match_count,
            "current_ranking": {
                "rank_ts": ranking.get("rank_ts"),
                "ts_score": ranking.get("ts_score"),
                "comparisons": ranking.get("comparisons"),
                "win_rate": ranking.get("win_rate"),
            },
            "versions": [
                {
                    "paper_id": v["id"],
                    "arxiv_id": v.get("arxiv_id"),
                    "version": v.get("version"),
                    "is_latest": v.get("is_latest_version") is not False,
                    "frozen_at": v.get("frozen_at"),
                    "added_at": v.get("added_at"),
                }
                for v in versions
            ],
        })

    # Legacy in-place revised papers (pre-refactor) — surfaced so admins can
    # audit them, but they never receive new standalone sibling docs.
    legacy = []
    async for doc in db.papers.find(
        {"version_history": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "arxiv_id_base": 1,
         "current_version": 1, "version_history": 1, "revised_at": 1, "categories": 1}
    ).sort("revised_at", -1).limit(limit):
        legacy.append({
            "source": "legacy_in_place",
            "id": doc["id"],
            "arxiv_id_base": doc.get("arxiv_id_base"),
            "title": doc.get("title", ""),
            "current_arxiv_id": doc.get("arxiv_id"),
            "current_version": doc.get("current_version"),
            "category": (doc.get("categories") or ["?"])[0],
            "revised_at": doc.get("revised_at"),
            "archived_versions_count": len(doc.get("version_history", [])),
        })

    total_standalone_families = 0
    async for group in db.papers.aggregate([
        {"$match": {"arxiv_id_base": {"$exists": True}}},
        {"$group": {"_id": "$arxiv_id_base", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$count": "total"},
    ]):
        total_standalone_families = group.get("total", 0)

    total_legacy = await db.papers.count_documents({"version_history": {"$exists": True, "$ne": []}})
    total_frozen = await db.papers.count_documents({"is_latest_version": False})

    return {
        "total_standalone_families": total_standalone_families,
        "total_legacy_in_place": total_legacy,
        "total_frozen_papers": total_frozen,
        "families": families,
        "legacy_in_place": legacy,
    }


# =====================================================================
# Positional-Bias Controlled A/B Test (GPT-5.2 infra vs model hypothesis)
# =====================================================================
#
# Goal: distinguish whether GPT-5.2's ~35% pos1 rate on the live tournament
# (W14+) is caused by (a) the LLM proxy degrading under scheduler queue
# pressure, or (b) genuine GPT-5.2 second-paper preference.
#
# Design: sample N already-judged pairs from recent production matches.
# For each pair, call compare_papers twice with model_override=GPT-5.2 —
# once as (A, B), once as (B, A). Use low concurrency so no queueing.
# Report:
#   - pos1_rate: fraction of the 2N calls where winner was shown first
#   - consistency_rate: fraction of pairs where the same paper wins in
#     both orderings (position-invariant)
#   - directional_flip_rate: fraction of pairs where the first-position
#     paper wins BOTH orderings (pure positional bias)
#
# If pos1_rate ≈ 48-50% and consistency_rate is high → live tournament's
# 35% is infra-induced (queue pressure on the proxy).
# If pos1_rate ≈ 35% and directional_flip_rate is high → genuine GPT-5.2
# positional bias.

from threading import Lock as _ThLock

_POSITIONAL_AB_JOBS: dict = {}
_POSITIONAL_AB_LOCK = _ThLock()


class PositionalABRequest(BaseModel):
    n_pairs: int = 500
    model_provider: str = "openai"
    model_name: str = "gpt-5.2"
    concurrency: int = 5
    since: str = "2026-04-01"  # sample production matches after this date


@router.post("/positional-ab-test/start", dependencies=[Depends(verify_admin)])
async def start_positional_ab_test(body: PositionalABRequest):
    """Kick off a background controlled A/B test. Returns job_id for polling."""
    if body.n_pairs < 10 or body.n_pairs > 2000:
        raise HTTPException(400, "n_pairs must be 10..2000")
    if body.concurrency < 1 or body.concurrency > 20:
        raise HTTPException(400, "concurrency must be 1..20")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with _POSITIONAL_AB_LOCK:
        _POSITIONAL_AB_JOBS[job_id] = {
            "job_id": job_id,
            "state": "starting",
            "n_pairs_requested": body.n_pairs,
            "model": f"{body.model_provider}:{body.model_name}",
            "concurrency": body.concurrency,
            "since": body.since,
            "started_at": now,
            "pairs_completed": 0,
            "calls_completed": 0,
            "calls_failed": 0,
            "per_pair": [],
            "summary": None,
        }

    asyncio.create_task(_run_positional_ab(job_id, body))
    return {"job_id": job_id, "state": "starting"}


@router.get("/positional-ab-test/status")
async def status_positional_ab_test(job_id: str):
    """Poll A/B test progress. Returns summary when done."""
    with _POSITIONAL_AB_LOCK:
        job = _POSITIONAL_AB_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    # Shallow copy, omit per_pair detail unless finished
    out = {k: v for k, v in job.items() if k != "per_pair"}
    if job["state"] == "done":
        out["per_pair_sample"] = job["per_pair"][:20]
    return out


@router.get("/positional-ab-test/list")
async def list_positional_ab_tests():
    """List recent A/B runs (in-memory only, cleared on restart)."""
    with _POSITIONAL_AB_LOCK:
        jobs = [
            {k: v for k, v in j.items() if k not in ("per_pair",)}
            for j in _POSITIONAL_AB_JOBS.values()
        ]
    return {"jobs": sorted(jobs, key=lambda x: x.get("started_at", ""), reverse=True)}


async def _run_positional_ab(job_id: str, body: PositionalABRequest):
    """Background worker: sample pairs, run dual-order comparisons."""
    from services.llm import compare_papers

    def _update(**patch):
        with _POSITIONAL_AB_LOCK:
            _POSITIONAL_AB_JOBS[job_id].update(patch)

    try:
        _update(state="sampling")

        # 1) Sample N completed matches for this model, after `since`.
        model_full = f"{body.model_provider}:{body.model_name}"
        match_filter = {
            "completed": True,
            "failed": {"$ne": True},
            "winner_id": {"$exists": True},
            "model_used.model": body.model_name,
            "content_mode": "abstract_plus_summary",
            "created_at": {"$gte": body.since},
        }
        pipeline = [
            {"$match": match_filter},
            {"$sample": {"size": body.n_pairs}},
            {"$project": {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}},
        ]
        sampled = await db.matches.aggregate(pipeline).to_list(length=body.n_pairs)
        if not sampled:
            _update(state="error", error="no matches sampled")
            return

        # 2) Load paper docs with Claude thinking summaries.
        needed_ids = list({m["paper1_id"] for m in sampled} | {m["paper2_id"] for m in sampled})
        papers = await collect_all(db.papers.find(
            {"id": {"$in": needed_ids}},
            {"_id": 0, "id": 1, "title": 1, "abstract": 1, "summaries": 1},
        ))
        paper_lookup = {p["id"]: p for p in papers}

        SUM_KEY = "anthropic:claude-opus-4-6:thinking"

        def _prep(paper_id):
            p = paper_lookup.get(paper_id)
            if not p:
                return None
            summary = (p.get("summaries") or {}).get(SUM_KEY, "")
            if not summary or len(summary) < 50:
                return None
            return {
                "id": p["id"],
                "title": p.get("title", ""),
                "abstract": p.get("abstract", ""),
                "ai_impact_summary": summary,
            }

        # Keep only pairs where both papers have valid Claude summaries
        usable_pairs = []
        for m in sampled:
            a = _prep(m["paper1_id"])
            b = _prep(m["paper2_id"])
            if a and b:
                usable_pairs.append((a, b, m["winner_id"]))

        _update(state="running", n_pairs_usable=len(usable_pairs))
        if not usable_pairs:
            _update(state="error", error="no usable pairs (missing Claude summaries)")
            return

        model_override = {"provider": body.model_provider, "model": body.model_name}
        sem = asyncio.Semaphore(body.concurrency)

        pair_results = []

        async def _judge_once(p_first, p_second):
            """Run compare_papers with p_first as position 1. Return winner paper_id or None."""
            async with sem:
                try:
                    res = await asyncio.wait_for(
                        compare_papers(
                            p_first, p_second,
                            content_mode="abstract_plus_summary",
                            model_override=model_override,
                        ),
                        timeout=90,
                    )
                    return p_first["id"] if res.get("winner") == "paper1" else p_second["id"]
                except Exception as e:
                    logger.warning(f"positional_ab judge failed: {e}")
                    return None

        async def _run_pair(pair_idx, a, b, prod_winner):
            # Order AB: a in pos1, b in pos2
            win_ab = await _judge_once(a, b)
            # Order BA: b in pos1, a in pos2
            win_ba = await _judge_once(b, a)

            # Collect per-pair outcome
            pair_out = {
                "idx": pair_idx,
                "paper_a_id": a["id"],
                "paper_b_id": b["id"],
                "prod_winner_id": prod_winner,
                "ab_winner_id": win_ab,
                "ba_winner_id": win_ba,
                "ab_pos1_win": (win_ab == a["id"]) if win_ab else None,
                "ba_pos1_win": (win_ba == b["id"]) if win_ba else None,
                "consistent": (win_ab == win_ba) if (win_ab and win_ba) else None,
            }
            with _POSITIONAL_AB_LOCK:
                job = _POSITIONAL_AB_JOBS[job_id]
                job["per_pair"].append(pair_out)
                job["pairs_completed"] += 1
                for w in (win_ab, win_ba):
                    if w is None:
                        job["calls_failed"] += 1
                    else:
                        job["calls_completed"] += 1

        await asyncio.gather(*[
            _run_pair(i, a, b, w) for i, (a, b, w) in enumerate(usable_pairs)
        ])

        # 3) Aggregate
        with _POSITIONAL_AB_LOCK:
            per_pair = list(_POSITIONAL_AB_JOBS[job_id]["per_pair"])

        pos1_wins = 0
        pos1_total = 0
        consistent = 0
        consistent_total = 0
        directional_first_bias = 0  # pos1 wins in BOTH orderings = position-driven toward first
        directional_second_bias = 0  # pos2 wins in BOTH orderings = position-driven toward second

        for p in per_pair:
            for k in ("ab_pos1_win", "ba_pos1_win"):
                v = p.get(k)
                if v is None:
                    continue
                pos1_total += 1
                if v:
                    pos1_wins += 1

            c = p.get("consistent")
            if c is not None:
                consistent_total += 1
                if c:
                    consistent += 1
                else:
                    # Inconsistent: same pair voted differently by order.
                    # Classify direction of inconsistency.
                    ab_pos1 = p.get("ab_pos1_win")
                    ba_pos1 = p.get("ba_pos1_win")
                    if ab_pos1 and ba_pos1:
                        directional_first_bias += 1
                    elif (ab_pos1 is False) and (ba_pos1 is False):
                        directional_second_bias += 1

        summary = {
            "n_pairs_usable": len(usable_pairs),
            "calls_total": pos1_total,
            "pos1_rate_pct": round(pos1_wins / pos1_total * 100, 2) if pos1_total else None,
            "consistency_rate_pct": round(consistent / consistent_total * 100, 2) if consistent_total else None,
            "inconsistent_pairs": consistent_total - consistent,
            "inconsistent_toward_first_pct": round(directional_first_bias / consistent_total * 100, 2) if consistent_total else None,
            "inconsistent_toward_second_pct": round(directional_second_bias / consistent_total * 100, 2) if consistent_total else None,
            "production_baseline_pos1_rate_note": "GPT-5.2 on live tournament W14+ is ~35%",
        }

        _update(state="done", finished_at=datetime.now(timezone.utc).isoformat(), summary=summary)
    except Exception as e:
        logger.exception("positional_ab run failed")
        _update(state="error", error=str(e)[:500])
