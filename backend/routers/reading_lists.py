"""Shareable reading lists — curated paper collections with public URLs."""

from datetime import datetime, timezone
import uuid
import html as html_mod
import os
from fastapi.responses import Response, HTMLResponse
import cairosvg
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger

router = APIRouter(prefix="/api/lists")

SITE_URL = os.environ.get("SITE_URL", "")


def _esc(t):
    return html_mod.escape(str(t))


def _build_enriched_paper_map():
    """Build paper map from leaderboard cache with computed scores."""
    from routers.leaderboard import _cache as lb_cache
    paper_map = {}
    # First, load raw papers for metadata (authors, categories, etc.)
    for p in lb_cache.get("_raw_papers", []):
        paper_map[p["id"]] = dict(p)
    # Then overlay computed scores from per-category leaderboard entries
    for cat_data in lb_cache.get("categories", {}).values():
        for entry in cat_data.get("all", []):
            pid = entry.get("id")
            if pid in paper_map:
                paper_map[pid].update({
                    "score": entry.get("score"),
                    "win_rate": entry.get("win_rate"),
                    "wins": entry.get("wins"),
                    "losses": entry.get("losses"),
                    "comparisons": entry.get("comparisons"),
                    "wilson_margin": entry.get("wilson_margin"),
                    "ci": entry.get("ci"),
                    "sp_score": entry.get("sp_score"),
                })
            else:
                paper_map[pid] = dict(entry)
    return paper_map


async def _get_current_user(request: Request) -> Optional[dict]:
    from routers.auth import _get_current_user as _auth_get_user
    return await _auth_get_user(request)


async def _prerender_list_image(list_id: str, name: str, curator: str, paper_ids: list):
    """Pre-render and store the OG image for a reading list."""
    try:
        from core.image_store import store_image
        paper_map = _build_enriched_paper_map()
        papers = [paper_map[pid] for pid in paper_ids[:8] if pid in paper_map]
        img_bytes = _render_list_image(
            name=name, description="", curator=curator,
            papers=papers, total=len(paper_ids),
        )
        await store_image(f"list:{list_id}", img_bytes)
    except Exception as e:
        logger.warning(f"Pre-render list image failed for {list_id}: {e}")


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
    await _prerender_list_image(list_id, body.name.strip(), user.get("name", ""), body.paper_ids[:200])
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
    await _prerender_list_image(list_id, body.name.strip(), user.get("name", ""), paper_ids)
    return {"status": "created", "list": doc}


@router.get("/public/{list_id}")
async def get_public_list(list_id: str, request: Request):
    """Get a reading list with enriched paper data. Public lists visible to all; private lists visible to owner."""
    rl = await db.reading_lists.find_one({"list_id": list_id}, {"_id": 0})
    if not rl:
        raise HTTPException(404, "Reading list not found")
    # Private lists: only the owner can view
    if not rl.get("public"):
        user = await _get_current_user(request)
        if not user or user["user_id"] != rl.get("user_id"):
            raise HTTPException(404, "Reading list not found")

    # Enrich with paper data from leaderboard cache (with computed scores)
    paper_map = _build_enriched_paper_map()

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
    # Re-render OG image with new papers
    updated = await db.reading_lists.find_one({"list_id": list_id}, {"_id": 0, "name": 1, "user_name": 1, "paper_ids": 1})
    if updated:
        await _prerender_list_image(list_id, updated.get("name", ""), updated.get("user_name", ""), updated.get("paper_ids", []))
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
        "public": True,
        "forked_from": list_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.reading_lists.insert_one(doc)
    doc.pop("_id", None)
    return {"status": "forked", "list": doc}


@router.post("/{list_id}/import-bookmarks")
async def import_as_bookmarks(list_id: str, request: Request):
    """Import all papers from a reading list as bookmarks."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    rl = await db.reading_lists.find_one({"list_id": list_id}, {"_id": 0})
    if not rl:
        raise HTTPException(404, "Reading list not found")

    existing = set()
    async for b in db.bookmarks.find({"user_id": user["user_id"]}, {"paper_id": 1}):
        existing.add(b["paper_id"])

    added = 0
    for pid in rl.get("paper_ids", []):
        if pid in existing:
            continue
        paper = await db.papers.find_one({"id": pid}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "categories": 1, "arxiv_id": 1, "published": 1})
        if not paper:
            continue
        await db.bookmarks.insert_one({
            "user_id": user["user_id"], "paper_id": pid,
            "paper_title": paper.get("title", ""), "paper_authors": paper.get("authors", []),
            "paper_categories": paper.get("categories", []), "paper_arxiv_id": paper.get("arxiv_id"),
            "paper_published": paper.get("published"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        existing.add(pid)
        added += 1
    return {"status": "imported", "added": added}


@router.post("/{list_id}/import-to-list")
async def import_to_existing_list(list_id: str, target_list_id: str, request: Request):
    """Import papers from one list into another existing list."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    source = await db.reading_lists.find_one({"list_id": list_id}, {"_id": 0, "paper_ids": 1})
    if not source:
        raise HTTPException(404, "Source list not found")
    target = await db.reading_lists.find_one({"list_id": target_list_id, "user_id": user["user_id"]}, {"_id": 0, "paper_ids": 1})
    if not target:
        raise HTTPException(404, "Target list not found")
    existing = set(target.get("paper_ids", []))
    new_ids = [pid for pid in source.get("paper_ids", []) if pid not in existing]
    if not new_ids:
        return {"status": "no_change", "added": 0}
    await db.reading_lists.update_one(
        {"list_id": target_list_id},
        {"$push": {"paper_ids": {"$each": new_ids}}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "added", "added": len(new_ids)}


# --- Social sharing ---

@router.get("/{list_id}/share", response_class=HTMLResponse)
async def get_list_share_page(list_id: str, request: Request):
    """Static HTML page with OG meta tags for reading list sharing. No redirect — crawler-first."""
    from core.sharing import get_public_base_url, SHARE_HEADERS
    rl = await db.reading_lists.find_one({"list_id": list_id, "public": True}, {"_id": 0})
    if not rl:
        raise HTTPException(404, "Reading list not found")

    base_url = get_public_base_url(request)
    name = _esc(rl.get("name", "Reading List"))
    desc = _esc(rl.get("description", ""))
    curator = _esc(rl.get("user_name", ""))
    paper_count = len(rl.get("paper_ids", []))
    image_url = f"{base_url}/api/lists/{list_id}/image.png"
    share_url = f"{base_url}/api/lists/{list_id}/share"
    list_url = f"{base_url}/list/{list_id}"

    og_title = f"{name} — {paper_count} papers"
    og_desc = f"Curated by {curator} on Kurate.org" + (f" — {desc}" if desc else "")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name} | Kurate.org</title>
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="{image_url}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{share_url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Kurate.org">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{image_url}">
<meta name="twitter:site" content="@KurateAI">
</head>
<body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; color: #333;">
<h1 style="font-size: 20px;">{name}</h1>
<p style="color: #666; font-size: 14px;">Curated by {curator} &middot; {paper_count} papers</p>
<p><a href="{list_url}" style="color: #4285F4;">View this reading list on Kurate.org &rarr;</a></p>
<script>window.location.replace("{list_url}");</script>
</body>
</html>"""
    return HTMLResponse(content=html, headers=SHARE_HEADERS)


@router.get("/{list_id}/image.png")
async def get_list_image(list_id: str):
    """Serve pre-rendered list image, falling back to on-the-fly rendering."""
    from core.image_store import get_image, store_image
    from routers.badges import _get_cached_image, _set_cached_image
    store_key = f"list:{list_id}"

    # 1. Check persistent store
    stored = await get_image(store_key)
    if stored:
        return Response(content=stored, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    # 2. Check in-memory cache
    cached = _get_cached_image(store_key)
    if cached:
        return Response(content=cached, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    # 3. Render on-the-fly
    rl = await db.reading_lists.find_one({"list_id": list_id, "public": True}, {"_id": 0})
    if not rl:
        raise HTTPException(404, "Reading list not found")

    paper_map = _build_enriched_paper_map()
    papers = []
    for pid in rl.get("paper_ids", [])[:8]:
        p = paper_map.get(pid)
        if p:
            papers.append(p)

    img_bytes = _render_list_image(
        name=rl.get("name", "Reading List"),
        description=rl.get("description", ""),
        curator=rl.get("user_name", ""),
        papers=papers,
        total=len(rl.get("paper_ids", [])),
    )
    _set_cached_image(store_key, img_bytes)
    await store_image(store_key, img_bytes)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


def _render_list_image(name: str, description: str, curator: str, papers: list, total: int) -> bytes:
    """Render a reading list preview as SVG → PNG."""
    show = papers[:3]  # Show max 3 papers to avoid overflow
    rows_svg = ""
    y = 180
    for i, p in enumerate(show):
        title = _esc(p.get("title", "")[:55] + ("..." if len(p.get("title", "")) > 55 else ""))
        authors = _esc(", ".join(p.get("authors", [])[:3]) + (" +" + str(len(p["authors"]) - 3) if len(p.get("authors", [])) > 3 else ""))
        score = p.get("score", "—")
        cat = _esc((p.get("categories") or [""])[0])
        bg = '#f8fafc' if i % 2 == 0 else '#ffffff'
        rows_svg += f"""
    <rect x="30" y="{y}" width="580" height="52" rx="4" fill="{bg}"/>
    <text x="50" y="{y+22}" font-family="system-ui, sans-serif" font-size="13" font-weight="600" fill="#1a1a2e">{title}</text>
    <text x="50" y="{y+40}" font-family="system-ui, sans-serif" font-size="10" fill="#6b7280">{authors}</text>
    <text x="590" y="{y+22}" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#4285F4" text-anchor="end">{score}</text>
    <text x="590" y="{y+40}" font-family="system-ui, sans-serif" font-size="10" fill="#9ca3af" text-anchor="end">{cat}</text>"""
        y += 56

    if total > len(show):
        rows_svg += f"""
    <text x="320" y="{y+16}" font-family="system-ui, sans-serif" font-size="11" fill="#9ca3af" text-anchor="middle">+{total - len(show)} more paper{"s" if total - len(show) != 1 else ""}</text>"""

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 392" width="640" height="392">
  <rect width="640" height="392" fill="#ffffff"/>
  <rect width="640" height="64" fill="#f0f4f8"/>
  <line x1="0" y1="64" x2="640" y2="64" stroke="#dde3ea" stroke-width="1"/>

  <!-- Kurate.org logo -->
  <text x="30" y="42" font-family="system-ui, sans-serif" font-size="16" font-weight="600" fill="#6b7280">Reading List</text>
  <text x="480" y="45" font-family="system-ui, sans-serif" font-size="24" letter-spacing="-0.3"><tspan font-weight="800" fill="#4285F4">Ku</tspan><tspan font-weight="800" fill="#1a1a1a">rate</tspan><tspan font-weight="400" fill="#4285F4" font-size="21">.org</tspan></text>

  <!-- Title & metadata -->
  <text x="30" y="100" font-family="system-ui, sans-serif" font-size="22" font-weight="700" fill="#1a1a2e">{_esc(name[:50])}</text>
  <text x="30" y="125" font-family="system-ui, sans-serif" font-size="12" fill="#6b7280">Curated by {_esc(curator)} · {total} papers</text>
  {f'<text x="30" y="145" font-family="system-ui, sans-serif" font-size="11" fill="#9ca3af">{_esc(description[:80])}</text>' if description else ''}

  <!-- Header row -->
  <rect x="30" y="160" width="580" height="18" fill="#f0f4f8" rx="2"/>
  <text x="50" y="173" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="#6b7280">Paper</text>
  <text x="590" y="173" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="#6b7280" text-anchor="end">Score</text>

  {rows_svg}
</svg>"""

    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=2400, output_height=1470)
