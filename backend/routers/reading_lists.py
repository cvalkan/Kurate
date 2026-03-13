"""Shareable reading lists — curated paper collections with public URLs."""

from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger

router = APIRouter(prefix="/api/lists")


async def _get_current_user(request: Request) -> Optional[dict]:
    from routers.auth import _get_current_user as _auth_get_user
    return await _auth_get_user(request)


class CreateListRequest(BaseModel):
    name: str
    description: str = ""
    paper_ids: list[str] = []


class UpdateListRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    public: Optional[bool] = None


class AddPapersRequest(BaseModel):
    paper_ids: list[str]


class CreateFromBookmarksRequest(BaseModel):
    name: str
    description: str = ""
    paper_ids: list[str] = []  # subset of bookmarks; empty = all bookmarks


@router.get("")
async def get_my_lists(request: Request):
    """Get all reading lists for the current user."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    lists = await db.reading_lists.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return {"lists": lists}


@router.post("")
async def create_list(body: CreateListRequest, request: Request):
    """Create a new reading list."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    # Limit per user
    count = await db.reading_lists.count_documents({"user_id": user["user_id"]})
    if count >= 50:
        raise HTTPException(400, "Maximum 50 reading lists per user")

    list_id = uuid.uuid4().hex[:12]
    doc = {
        "list_id": list_id,
        "user_id": user["user_id"],
        "user_name": user.get("name", ""),
        "name": body.name.strip(),
        "description": body.description.strip(),
        "paper_ids": body.paper_ids[:200],
        "public": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.reading_lists.insert_one(doc)
    doc.pop("_id", None)
    return {"status": "created", "list": doc}


@router.post("/from-bookmarks")
async def create_from_bookmarks(body: CreateFromBookmarksRequest, request: Request):
    """Create a reading list from bookmarked papers."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not body.name.strip():
        raise HTTPException(400, "Name is required")

    if body.paper_ids:
        paper_ids = body.paper_ids[:200]
    else:
        # Use all bookmarks
        bookmarks = await db.bookmarks.find(
            {"user_id": user["user_id"]}, {"_id": 0, "paper_id": 1}
        ).sort("created_at", -1).to_list(200)
        paper_ids = [b["paper_id"] for b in bookmarks]

    if not paper_ids:
        raise HTTPException(400, "No papers to add")

    list_id = uuid.uuid4().hex[:12]
    doc = {
        "list_id": list_id,
        "user_id": user["user_id"],
        "user_name": user.get("name", ""),
        "name": body.name.strip(),
        "description": body.description.strip(),
        "paper_ids": paper_ids,
        "public": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.reading_lists.insert_one(doc)
    doc.pop("_id", None)
    return {"status": "created", "list": doc}


@router.get("/public/{list_id}")
async def get_public_list(list_id: str):
    """Get a public reading list with enriched paper data (no auth required)."""
    rl = await db.reading_lists.find_one(
        {"list_id": list_id, "public": True}, {"_id": 0}
    )
    if not rl:
        raise HTTPException(404, "Reading list not found")

    # Enrich with paper data from leaderboard cache
    from routers.leaderboard import _cache as lb_cache
    all_papers = lb_cache.get("_raw_papers", [])
    paper_map = {p["id"]: p for p in all_papers}

    papers = []
    for pid in rl.get("paper_ids", []):
        p = paper_map.get(pid)
        if p:
            papers.append({
                "id": p["id"], "title": p.get("title", ""), "authors": p.get("authors", []),
                "categories": p.get("categories", []), "primary_category": (p.get("categories") or [""])[0],
                "arxiv_id": p.get("arxiv_id"), "published": p.get("published"), "link": p.get("link"),
                "score": p.get("score"), "win_rate": p.get("win_rate"), "wins": p.get("wins"),
                "losses": p.get("losses"), "comparisons": p.get("comparisons"),
                "wilson_margin": p.get("wilson_margin"), "ci": p.get("ci"),
                "ai_rating": p.get("ai_rating", {}).get("score") if isinstance(p.get("ai_rating"), dict) else p.get("ai_rating"),
                "sp_score": p.get("sp_score"),
            })

    return {
        "list": {
            "list_id": rl["list_id"],
            "name": rl["name"],
            "description": rl.get("description", ""),
            "user_name": rl.get("user_name", ""),
            "paper_count": len(papers),
            "created_at": rl.get("created_at"),
            "updated_at": rl.get("updated_at"),
        },
        "papers": papers,
    }


@router.put("/{list_id}")
async def update_list(list_id: str, body: UpdateListRequest, request: Request):
    """Update a reading list's metadata."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    rl = await db.reading_lists.find_one(
        {"list_id": list_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not rl:
        raise HTTPException(404, "Reading list not found")

    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.description is not None:
        updates["description"] = body.description.strip()
    if body.public is not None:
        updates["public"] = body.public

    await db.reading_lists.update_one({"list_id": list_id}, {"$set": updates})
    return {"status": "updated"}


@router.post("/{list_id}/papers")
async def add_papers(list_id: str, body: AddPapersRequest, request: Request):
    """Add papers to a reading list."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    rl = await db.reading_lists.find_one(
        {"list_id": list_id, "user_id": user["user_id"]}, {"_id": 0, "paper_ids": 1}
    )
    if not rl:
        raise HTTPException(404, "Reading list not found")

    existing = set(rl.get("paper_ids", []))
    new_ids = [pid for pid in body.paper_ids if pid not in existing]
    if not new_ids:
        return {"status": "no_change", "added": 0}

    await db.reading_lists.update_one(
        {"list_id": list_id},
        {"$push": {"paper_ids": {"$each": new_ids}},
         "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "added", "added": len(new_ids)}


@router.delete("/{list_id}/papers/{paper_id}")
async def remove_paper(list_id: str, paper_id: str, request: Request):
    """Remove a paper from a reading list."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    result = await db.reading_lists.update_one(
        {"list_id": list_id, "user_id": user["user_id"]},
        {"$pull": {"paper_ids": paper_id},
         "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Paper or list not found")
    return {"status": "removed"}


@router.delete("/{list_id}")
async def delete_list(list_id: str, request: Request):
    """Delete a reading list."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    result = await db.reading_lists.delete_one(
        {"list_id": list_id, "user_id": user["user_id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Reading list not found")
    return {"status": "deleted"}


@router.post("/{list_id}/fork")
async def fork_list(list_id: str, request: Request):
    """Copy a public reading list to your own account."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    original = await db.reading_lists.find_one(
        {"list_id": list_id, "public": True}, {"_id": 0}
    )
    if not original:
        raise HTTPException(404, "Reading list not found")

    new_id = uuid.uuid4().hex[:12]
    doc = {
        "list_id": new_id,
        "user_id": user["user_id"],
        "user_name": user.get("name", ""),
        "name": f"{original['name']} (copy)",
        "description": original.get("description", ""),
        "paper_ids": original.get("paper_ids", []),
        "public": False,
        "forked_from": list_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.reading_lists.insert_one(doc)
    doc.pop("_id", None)
    return {"status": "forked", "list": doc}
