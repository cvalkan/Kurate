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

def _get_base_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto", "https")
    return f"{proto}://{host}" if host and "cluster" not in host else SITE_URL


@router.get("/{list_id}/share", response_class=HTMLResponse)
async def get_list_share_page(list_id: str, request: Request):
    """OG meta tags page for social sharing of reading lists."""
    rl = await db.reading_lists.find_one({"list_id": list_id, "public": True}, {"_id": 0})
    if not rl:
        raise HTTPException(404, "Reading list not found")

    base_url = _get_base_url(request)
    name = _esc(rl.get("name", "Reading List"))
    desc = _esc(rl.get("description", ""))
    curator = _esc(rl.get("user_name", ""))
    paper_count = len(rl.get("paper_ids", []))
    image_url = f"{base_url}/api/lists/{list_id}/image.png"
    share_url = f"{base_url}/api/lists/{list_id}/share"
    list_url = f"{base_url}/list/{list_id}"

    og_title = f"{name} — {paper_count} papers"
    og_desc = f"Curated by {curator} on Kurate.org" + (f" — {desc}" if desc else "")

    # Don't redirect bots — let them read the OG tags
    ua = (request.headers.get("user-agent") or "").lower()
    is_bot = any(b in ua for b in ("linkedinbot", "twitterbot", "facebookexternalhit", "slackbot", "telegrambot", "whatsapp", "bot", "crawler", "spider"))
    redirect_script = "" if is_bot else f'<script>window.location.replace("{list_url}");</script>'

    return f"""<!DOCTYPE html>
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
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{image_url}">
</head>
<body>
{redirect_script}
<p>Redirecting to <a href="{list_url}">{name}</a>...</p>
</body>
</html>"""


@router.get("/{list_id}/image.png")
async def get_list_image(list_id: str):
    """Generate OG image (1200x630) showing the reading list's top papers."""
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
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


def _render_list_image(name: str, description: str, curator: str, papers: list, total: int) -> bytes:
    """Render a reading list preview as SVG → PNG."""
    show = papers[:6]
    rows_svg = ""
    y = 180
    for i, p in enumerate(show):
        title = _esc(p.get("title", "")[:60] + ("..." if len(p.get("title", "")) > 60 else ""))
        authors = _esc(", ".join(p.get("authors", [])[:3]) + (" +" + str(len(p["authors"]) - 3) if len(p.get("authors", [])) > 3 else ""))
        score = p.get("score", "—")
        cat = _esc((p.get("categories") or [""])[0])
        bg = '#f8fafc' if i % 2 == 0 else '#ffffff'
        rows_svg += f"""
    <rect x="30" y="{y}" width="580" height="58" rx="4" fill="{bg}"/>
    <text x="50" y="{y+24}" font-family="system-ui, sans-serif" font-size="14" font-weight="600" fill="#1a1a2e">{title}</text>
    <text x="50" y="{y+44}" font-family="system-ui, sans-serif" font-size="11" fill="#6b7280">{authors}</text>
    <text x="590" y="{y+24}" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#4285F4" text-anchor="end">{score}</text>
    <text x="590" y="{y+44}" font-family="system-ui, sans-serif" font-size="10" fill="#9ca3af" text-anchor="end">{cat}</text>"""
        y += 62

    if total > len(show):
        rows_svg += f"""
    <text x="320" y="{y+20}" font-family="system-ui, sans-serif" font-size="12" fill="#9ca3af" text-anchor="middle">+{total - len(show)} more papers</text>"""

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

    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=1200, output_height=735)
