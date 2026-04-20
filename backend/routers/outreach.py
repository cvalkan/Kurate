"""Admin routes for X/Twitter outreach handle discovery."""

import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.config import db, logger
from routers.admin import verify_admin

router = APIRouter(prefix="/api/admin/outreach", tags=["admin-outreach"])


class DiscoverRequest(BaseModel):
    category: Optional[str] = None  # None = all categories
    period: str = "all"  # "recent", "7d", "30d", "all", or "archive:YYYY-WW"
    top_n: int = 10


_discover_status = {"running": False, "category": None, "progress": 0, "total": 0}


@router.post("/discover", dependencies=[Depends(verify_admin)])
async def discover_handles(body: DiscoverRequest):
    """Discover X handles for top-N papers. Runs in background, returns immediately."""
    from services.twitter import discover_handles_batch

    if _discover_status["running"]:
        return {"status": "already_running", "progress": _discover_status["progress"], "total": _discover_status["total"]}

    papers = await _get_papers_for_period(body.category, body.period, body.top_n)
    if not papers:
        return {"status": "no_papers", "message": "No papers found for this selection."}

    _discover_status["running"] = True
    _discover_status["category"] = body.category
    _discover_status["progress"] = 0
    _discover_status["total"] = len(papers)

    async def _run():
        try:
            results = await discover_handles_batch(papers)
            _discover_status["progress"] = len(results)
        except Exception as e:
            logger.error(f"Discovery failed: {e}")
        finally:
            _discover_status["running"] = False

    asyncio.create_task(_run())

    return {
        "status": "started",
        "total_requested": len(papers),
        "message": f"Searching X for {len(papers)} papers in background. Refresh to see results.",
    }


@router.get("/discover-status", dependencies=[Depends(verify_admin)])
async def discover_status():
    """Check discovery progress."""
    return _discover_status


@router.get("/medalists", dependencies=[Depends(verify_admin)])
async def get_medalists(period: str = "current", top_n: int = 3):
    """Get top-N medalists across all categories.
    
    period: "current" (live leaderboard) or "archive:YYYY-WW" (weekly archive)
    Returns: {categories: [{category, name, papers: [{rank, title, authors, ...}]}]}
    """
    from core.config import CATEGORIES

    # Get all active categories
    all_cats = list(CATEGORIES.keys())
    # Also include categories from rankings that might not be in CATEGORIES
    extra_cats = await db.rankings.distinct("category")
    for c in extra_cats:
        if c not in all_cats:
            all_cats.append(c)

    # Category name lookup
    cat_names = dict(CATEGORIES)
    cats_from_api = await db.papers.aggregate([
        {"$unwind": "$categories"},
        {"$group": {"_id": "$categories"}},
    ]).to_list(100)

    result_cats = []

    if period.startswith("archive:"):
        parts = period.split(":")[1].split("-")
        if len(parts) == 2:
            year, week = int(parts[0]), int(parts[1])
            async for archive in db.leaderboard_archives.find(
                {"period_type": "weekly", "year": year, "week": week},
                {"_id": 0, "category": 1, "leaderboard": {"$slice": top_n}, "label": 1},
            ):
                cat = archive["category"]
                papers = []
                for p in archive.get("leaderboard", [])[:top_n]:
                    # Check if we have discovery data
                    disc = await db.x_handle_discoveries.find_one(
                        {"paper_id": p.get("id")}, {"_id": 0, "candidates": 1, "total_tweets": 1}
                    )
                    papers.append({
                        "id": p.get("id"),
                        "rank": p.get("rank"),
                        "title": p.get("title"),
                        "authors": p.get("authors", []),
                        "arxiv_id": p.get("arxiv_id"),
                        "ts_score": p.get("ts_score") or p.get("score"),
                        "ai_rating": p.get("ai_rating"),
                        "link": p.get("link"),
                        "candidates": disc.get("candidates", []) if disc else [],
                        "total_tweets": disc.get("total_tweets", 0) if disc else 0,
                        "discovered": disc is not None,
                    })
                if papers:
                    result_cats.append({
                        "category": cat,
                        "name": cat_names.get(cat, cat),
                        "label": archive.get("label", ""),
                        "papers": papers,
                    })
    else:
        # Current live leaderboard
        for cat in sorted(all_cats):
            papers = []
            async for doc in db.rankings.find(
                {"category": cat},
                {"_id": 0, "paper_id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                 "rank": 1, "ts_score": 1, "ai_rating": 1, "link": 1},
            ).sort("ts_score", -1).limit(top_n):
                pid = doc.get("paper_id")
                disc = await db.x_handle_discoveries.find_one(
                    {"paper_id": pid}, {"_id": 0, "candidates": 1, "total_tweets": 1}
                )
                papers.append({
                    "id": pid,
                    "rank": doc.get("rank"),
                    "title": doc.get("title"),
                    "authors": doc.get("authors", []),
                    "arxiv_id": doc.get("arxiv_id"),
                    "ts_score": doc.get("ts_score"),
                    "ai_rating": doc.get("ai_rating"),
                    "link": doc.get("link"),
                    "candidates": disc.get("candidates", []) if disc else [],
                    "total_tweets": disc.get("total_tweets", 0) if disc else 0,
                    "discovered": disc is not None,
                })
            if papers:
                result_cats.append({
                    "category": cat,
                    "name": cat_names.get(cat, cat),
                    "papers": papers,
                })

    result_cats.sort(key=lambda c: c["category"])

    return {
        "period": period,
        "categories": result_cats,
        "total_papers": sum(len(c["papers"]) for c in result_cats),
        "total_discovered": sum(1 for c in result_cats for p in c["papers"] if p["discovered"]),
    }


@router.post("/discover-medalists", dependencies=[Depends(verify_admin)])
async def discover_medalists(period: str = "current", top_n: int = 3):
    """Discover X handles for all medalists across all categories. Runs in background."""
    from services.twitter import discover_handles_batch

    if _discover_status["running"]:
        return {"status": "already_running", "progress": _discover_status["progress"], "total": _discover_status["total"]}

    # Collect all medalist papers
    medalists_resp = await get_medalists(period=period, top_n=top_n)
    all_papers = []
    for cat_data in medalists_resp["categories"]:
        for p in cat_data["papers"]:
            all_papers.append(p)

    if not all_papers:
        return {"status": "no_papers", "message": "No medalists found."}

    _discover_status["running"] = True
    _discover_status["category"] = "all-medalists"
    _discover_status["progress"] = 0
    _discover_status["total"] = len(all_papers)

    async def _run():
        try:
            results = await discover_handles_batch(all_papers)
            _discover_status["progress"] = len(results)
        except Exception as e:
            logger.error(f"Medalist discovery failed: {e}")
        finally:
            _discover_status["running"] = False

    asyncio.create_task(_run())

    return {
        "status": "started",
        "total_papers": len(all_papers),
        "total_categories": len(medalists_resp["categories"]),
        "message": f"Searching X for {len(all_papers)} medalists across {len(medalists_resp['categories'])} categories.",
    }



@router.get("/discoveries", dependencies=[Depends(verify_admin)])
async def get_discoveries(
    category: Optional[str] = None,
    period: str = "all",
    top_n: int = 10,
    confidence: Optional[str] = None,
):
    """Get cached discovery results for a category/period without triggering new searches."""
    papers = await _get_papers_for_period(category, period, top_n)
    if not papers:
        return {"papers": [], "total": 0}

    paper_ids = [p["id"] for p in papers]
    discoveries = {}
    async for doc in db.x_handle_discoveries.find(
        {"paper_id": {"$in": paper_ids}}, {"_id": 0}
    ):
        discoveries[doc["paper_id"]] = doc

    # Build response: papers with their discovery status
    result_papers = []
    for p in papers:
        pid = p["id"]
        disc = discoveries.get(pid)
        entry = {
            "id": pid,
            "title": p.get("title", ""),
            "authors": p.get("authors", []),
            "arxiv_id": p.get("arxiv_id", ""),
            "rank": p.get("rank"),
            "ts_score": p.get("ts_score"),
            "ai_rating": p.get("ai_rating"),
            "comparisons": p.get("comparisons", 0),
            "discovered": disc is not None,
            "total_tweets": disc.get("total_tweets", 0) if disc else 0,
            "candidates": disc.get("candidates", []) if disc else [],
            "discovered_at": disc.get("discovered_at") if disc else None,
        }
        if confidence and disc:
            entry["candidates"] = [c for c in entry["candidates"] if c["confidence"] == confidence]
        result_papers.append(entry)

    return {
        "papers": result_papers,
        "total": len(result_papers),
        "discovered_count": sum(1 for p in result_papers if p["discovered"]),
    }


@router.get("/handle-stats", dependencies=[Depends(verify_admin)])
async def get_handle_stats():
    """Summary stats for all discovered handles across the platform."""
    pipeline = [
        {"$unwind": "$candidates"},
        {"$group": {
            "_id": "$candidates.confidence",
            "count": {"$sum": 1},
            "unique_handles": {"$addToSet": "$candidates.handle"},
        }},
    ]
    stats = {}
    async for doc in db.x_handle_discoveries.aggregate(pipeline):
        stats[doc["_id"]] = {
            "count": doc["count"],
            "unique": len(doc["unique_handles"]),
        }

    total_papers = await db.x_handle_discoveries.count_documents({})
    papers_with_candidates = await db.x_handle_discoveries.count_documents(
        {"candidates.0": {"$exists": True}}
    )

    return {
        "total_papers_searched": total_papers,
        "papers_with_candidates": papers_with_candidates,
        "by_confidence": stats,
    }


@router.delete("/discovery/{paper_id}", dependencies=[Depends(verify_admin)])
async def delete_discovery(paper_id: str):
    """Delete a cached discovery to force re-search."""
    result = await db.x_handle_discoveries.delete_one({"paper_id": paper_id})
    return {"deleted": result.deleted_count > 0}


async def _get_papers_for_period(category: str, period: str, top_n: int) -> list:
    """Fetch ranked papers for a category/period, matching leaderboard logic."""
    
    if period.startswith("archive:"):
        # Weekly archive: "archive:2026-15"
        parts = period.split(":")[1].split("-")
        if len(parts) == 2:
            year, week = int(parts[0]), int(parts[1])
            archive = await db.leaderboard_archives.find_one(
                {"category": category, "period_type": "weekly", "year": year, "week": week},
                {"_id": 0, "leaderboard": 1},
            )
            if archive and archive.get("leaderboard"):
                return archive["leaderboard"][:top_n]
        return []

    # Live leaderboard
    query = {"category": category} if category else {}
    
    if period == "recent":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        query["added_at"] = {"$gte": cutoff}
    elif period == "7d":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query["added_at"] = {"$gte": cutoff}
    elif period == "30d":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        query["added_at"] = {"$gte": cutoff}

    papers = []
    async for doc in db.rankings.find(
        query,
        {"_id": 0, "paper_id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
         "rank": 1, "ts_score": 1, "ai_rating": 1, "comparisons": 1,
         "category": 1, "added_at": 1, "link": 1},
    ).sort("ts_score", -1).limit(top_n):
        doc["id"] = doc.pop("paper_id")
        papers.append(doc)
    
    return papers
