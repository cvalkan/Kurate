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
    """Get all bookmarks for the current user."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    bookmarks = await db.bookmarks.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return {"bookmarks": bookmarks}


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
