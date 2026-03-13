"""Paper bookmarks — save papers for later, foundation for reading lists."""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger

router = APIRouter(prefix="/api/bookmarks")


async def _get_current_user(request: Request) -> Optional[dict]:
    from routers.auth import _get_current_user as _auth_get_user
    return await _auth_get_user(request)


class BookmarkRequest(BaseModel):
    paper_id: str


@router.get("")
async def get_bookmarks(request: Request):
    """Get bookmarked papers with current leaderboard scores."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    bookmarks = await db.bookmarks.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    if not bookmarks:
        return {"bookmarks": [], "papers": []}

    # Fetch current paper data with scores from cache
    from routers.leaderboard import _cache as lb_cache
    all_papers = lb_cache.get("_raw_papers", [])
    paper_map = {p["id"]: p for p in all_papers}
    bookmark_dates = {b["paper_id"]: b.get("created_at") for b in bookmarks}

    papers = []
    for b in bookmarks:
        p = paper_map.get(b["paper_id"])
        if p:
            paper = {k: v for k, v in p.items() if k != "_id"}
            paper["bookmarked_at"] = bookmark_dates.get(b["paper_id"])
            papers.append(paper)
        else:
            # Paper not in cache — use denormalized bookmark data
            papers.append({
                "id": b["paper_id"],
                "title": b.get("paper_title", ""),
                "authors": b.get("paper_authors", []),
                "categories": b.get("paper_categories", []),
                "arxiv_id": b.get("paper_arxiv_id"),
                "published": b.get("paper_published"),
                "bookmarked_at": b.get("created_at"),
            })

    return {"bookmarks": bookmarks, "papers": papers}


@router.get("/ids")
async def get_bookmark_ids(request: Request):
    """Get just the paper IDs the user has bookmarked (lightweight, for UI icons)."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    bookmarks = await db.bookmarks.find(
        {"user_id": user["user_id"]}, {"_id": 0, "paper_id": 1}
    ).to_list(500)
    return {"paper_ids": [b["paper_id"] for b in bookmarks]}


@router.post("")
async def add_bookmark(body: BookmarkRequest, request: Request):
    """Bookmark a paper."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    # Check paper exists
    paper = await db.papers.find_one(
        {"id": body.paper_id}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "categories": 1, "arxiv_id": 1, "published": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")
    # Check not already bookmarked
    existing = await db.bookmarks.find_one(
        {"user_id": user["user_id"], "paper_id": body.paper_id}
    )
    if existing:
        return {"status": "already_bookmarked"}
    await db.bookmarks.insert_one({
        "user_id": user["user_id"],
        "paper_id": body.paper_id,
        "paper_title": paper.get("title", ""),
        "paper_authors": paper.get("authors", []),
        "paper_categories": paper.get("categories", []),
        "paper_arxiv_id": paper.get("arxiv_id"),
        "paper_published": paper.get("published"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "bookmarked"}


@router.delete("/{paper_id}")
async def remove_bookmark(paper_id: str, request: Request):
    """Remove a bookmark."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    result = await db.bookmarks.delete_one(
        {"user_id": user["user_id"], "paper_id": paper_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Bookmark not found")
    return {"status": "removed"}
