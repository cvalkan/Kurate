"""Admin routes for X/Twitter outreach handle discovery."""

import asyncio
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


@router.post("/discover", dependencies=[Depends(verify_admin)])
async def discover_handles(body: DiscoverRequest):
    """Discover X handles for top-N papers in a category/period.
    
    Skips papers already discovered. Returns cached + new results.
    """
    from services.twitter import discover_handles_batch

    # Get leaderboard papers
    papers = await _get_papers_for_period(body.category, body.period, body.top_n)
    if not papers:
        return {"status": "no_papers", "papers": [], "message": "No papers found for this selection."}

    # Run discovery (skips already-discovered papers)
    results = await discover_handles_batch(papers)

    return {
        "status": "ok",
        "total_requested": len(papers),
        "total_discovered": len(results),
        "new_discovered": sum(1 for r in results if r.get("discovered_at", "").startswith("20")),
        "results": results,
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
        # Most recent papers (last 3 days)
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        query["added_at"] = {"$gte": cutoff}
    elif period == "7d":
        from datetime import datetime as dt, timedelta, timezone
        cutoff = (dt.now(timezone.utc) - timedelta(days=7)).isoformat()
        query["added_at"] = {"$gte": cutoff}
    elif period == "30d":
        from datetime import datetime as dt, timedelta, timezone
        cutoff = (dt.now(timezone.utc) - timedelta(days=30)).isoformat()
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
