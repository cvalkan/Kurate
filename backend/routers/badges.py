"""Shareable badge generation for top-ranked papers."""

import io
import html as html_mod
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
import cairosvg
from typing import Optional

from core.config import db, logger

router = APIRouter(prefix="/api/badge")

# Font installation deferred to background (was blocking module import for 10s+)
_FONT_DIR = Path(__file__).parent.parent / "fonts"
_fonts_installed = False

async def _install_fonts_if_needed():
    """Install bundled Inter fonts in background. Non-blocking."""
    global _fonts_installed
    if _fonts_installed:
        return
    try:
        import asyncio
        _SYSTEM_FONT_DIR = Path("/usr/share/fonts/truetype/inter")
        if _FONT_DIR.exists():
            _SYSTEM_FONT_DIR.mkdir(parents=True, exist_ok=True)
            installed = 0
            for f in _FONT_DIR.glob("*.ttf"):
                dest = _SYSTEM_FONT_DIR / f.name
                if not dest.exists() or dest.stat().st_size != f.stat().st_size:
                    shutil.copy2(f, dest)
                    installed += 1
            if installed > 0:
                proc = await asyncio.create_subprocess_exec(
                    "fc-cache", "-f",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
                logger.info(f"Installed {installed} bundled Inter fonts")
        _fonts_installed = True
    except Exception as e:
        logger.warning(f"Failed to install bundled fonts: {e}")
        _fonts_installed = True  # Don't retry

# Fallback: set FONTCONFIG_FILE to ensure fonts are discoverable
import os as _os
_fc_conf = _FONT_DIR / "fonts.conf"
if not _fc_conf.exists() and _FONT_DIR.exists():
    try:
        _fc_conf.write_text(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{_FONT_DIR}</dir>
  <dir>{_SYSTEM_FONT_DIR}</dir>
</fontconfig>
""")
    except Exception:
        pass
if _fc_conf.exists() and not _os.environ.get("FONTCONFIG_FILE"):
    _os.environ["FONTCONFIG_FILE"] = str(_fc_conf)

# In-memory image cache: {cache_key: (bytes, timestamp)}
_image_cache = {}
_IMAGE_CACHE_TTL = 3600  # 1 hour


def _get_cached_image(key: str) -> Optional[bytes]:
    entry = _image_cache.get(key)
    if entry and (time.time() - entry[1]) < _IMAGE_CACHE_TTL:
        return entry[0]
    return None


def _set_cached_image(key: str, data: bytes):
    _image_cache[key] = (data, time.time())
    # Evict old entries if cache grows too large
    if len(_image_cache) > 500:
        cutoff = time.time() - _IMAGE_CACHE_TTL
        to_delete = [k for k, (_, ts) in _image_cache.items() if ts < cutoff]
        for k in to_delete:
            del _image_cache[k]

import os
_cors = os.environ.get("CORS_ORIGINS", "")
SITE_URL = os.environ.get("SITE_URL", "")
if not SITE_URL and _cors and _cors != "*":
    SITE_URL = _cors.split(",")[0].strip()

CATEGORIES = {
    "cs.RO": "Robotics", "cs.DC": "Distributed Computing", "econ.GN": "Economics",
    "physics.comp-ph": "Computational Physics", "q-bio.BM": "Biomolecules",
    "cs.GT": "Game Theory", "physics.chem-ph": "Chemical Physics",
    "chemrxiv.IC": "Inorganic Chemistry", "cs.CR": "Cryptography & Security",
    "cs.IT": "Information Theory",
}

TIER_CONFIG = [
    {"rank": 1, "name": "Gold", "color": "#D4A017", "bg": "#FFF8E1"},
    {"rank": 2, "name": "Silver", "color": "#8A8A8A", "bg": "#F5F5F5"},
    {"rank": 3, "name": "Bronze", "color": "#CD7F32", "bg": "#FFF3E0"},
]

FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def _get_tier(rank: int) -> Optional[dict]:
    """Get badge tier for a given rank. Only top 3 get badges."""
    for t in TIER_CONFIG:
        if rank == t["rank"]:
            return t
    return None


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len - 1] + "\u2026" if len(text) > max_len else text


async def _get_badge_data(category: str, year: int, week: int, paper_id: str) -> dict:
    """Fetch archive and extract badge data for a specific paper."""
    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "week": week, "period_type": "weekly"},
        {"_id": 0},
    )
    if not archive:
        raise HTTPException(404, "Archive not found")

    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found in this archive")

    tier = _get_tier(paper.get("rank_ts", paper.get("rank", 999)))
    if not tier:
        raise HTTPException(404, "Paper is not in the top 3 for this period")

    if not paper.get("comparisons"):
        raise HTTPException(404, "Paper has no tournament matches yet — badge unavailable")

    # Fetch full categories from papers collection (archives don't store them)
    categories = [category]
    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "categories": 1})
    if paper_doc and paper_doc.get("categories"):
        categories = paper_doc["categories"]

    return {
        "paper": paper,
        "tier": tier,
        "archive_label": archive.get("label", f"Week {week}, {year}"),
        "category": category,
        "category_name": CATEGORIES.get(category, category),
        "paper_count": archive.get("paper_count", len(lb)),
        "categories": categories,
        "year": year,
        "week": week,
    }


@router.get("/{category}/{year}/w{week}/{paper_id}")
async def get_badge(category: str, year: int, week: int, paper_id: str):
    """Get badge data for a top-ranked paper in a weekly archive."""
    data = await _get_badge_data(category, year, week, paper_id)
    p = data["paper"]
    return {
        "title": p.get("title"),
        "authors": p.get("authors", []),
        "rank": p["rank"],
        "score": p.get("score"),
        "win_rate": p.get("win_rate"),
        "comparisons": p.get("comparisons"),
        "tier": data["tier"]["name"],
        "tier_color": data["tier"]["color"],
        "archive_label": data["archive_label"],
        "category": data["category"],
        "category_name": data["category_name"],
        "paper_count": data["paper_count"],
        "arxiv_id": p.get("arxiv_id"),
        "paper_id": paper_id,
        "image_url": f"/api/badge/{category}/{year}/w{week}/{paper_id}/image.png",
    }


@router.get("/{category}/{year}/w{week}/{paper_id}/image.png")
async def get_badge_image(category: str, year: int, week: int, paper_id: str):
    """Serve pre-rendered badge image, falling back to on-the-fly rendering."""
    await _install_fonts_if_needed()  # Lazy font install on first image request
    from core.image_store import get_image, store_image
    store_key = f"badge:w:{category}/{year}/{week}/{paper_id}"
    # 1. Check persistent store (pre-rendered)
    stored = await get_image(store_key)
    if stored:
        return Response(content=stored, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    # 2. Check in-memory cache
    cached = _get_cached_image(store_key)
    if cached:
        return Response(content=cached, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    # 3. Render on-the-fly and cache
    data = await _get_badge_data(category, year, week, paper_id)
    img_bytes = _render_badge_image(data)
    _set_cached_image(store_key, img_bytes)
    # Also persist for future cold starts
    await store_image(store_key, img_bytes)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{category}/{year}/w{week}/{paper_id}/share", response_class=HTMLResponse)
async def get_badge_share_page(category: str, year: int, week: int, paper_id: str, request: Request):
    """Static HTML page with OG meta tags for social sharing. JS redirect for humans, crawlers see tags."""
    from core.sharing import get_public_base_url, SHARE_HEADERS
    data = await _get_badge_data(category, year, week, paper_id)
    base_url = get_public_base_url(request)
    html = _render_share_html(data, category, year, f"w{week}", paper_id, base_url)
    return HTMLResponse(content=html, headers=SHARE_HEADERS)


@router.get("/{category}/{year}/m{month}/{paper_id}/share", response_class=HTMLResponse)
async def get_monthly_badge_share_page(category: str, year: int, month: int, paper_id: str, request: Request):
    """Static HTML page with OG meta tags for monthly badge sharing."""
    from core.sharing import get_public_base_url, SHARE_HEADERS
    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "month": month, "period_type": "monthly"}, {"_id": 0})
    if not archive:
        raise HTTPException(404, "Archive not found")
    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found")
    tier = _get_tier(paper.get("rank_ts", paper.get("rank", 999)))
    if not tier:
        raise HTTPException(404, "Not in top 3")
    data = {"paper": paper, "tier": tier, "archive_label": archive.get("label"),
            "category": category, "category_name": CATEGORIES.get(category, category),
            "paper_count": archive.get("paper_count", len(lb)), "year": year}
    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "categories": 1})
    data["categories"] = paper_doc["categories"] if paper_doc and paper_doc.get("categories") else [category]
    base_url = get_public_base_url(request)
    html = _render_share_html(data, category, year, f"m{month}", paper_id, base_url)
    return HTMLResponse(content=html, headers=SHARE_HEADERS)


def _render_share_html(data: dict, category: str, year: int, slug: str, paper_id: str, base_url: str) -> str:
    """Generate a pure static HTML page with OG/Twitter meta tags. Zero JS, zero redirects — crawler-proof."""
    import html as html_mod
    p = data["paper"]
    tier = data["tier"]
    title = html_mod.escape(p.get("title", ""))
    authors = html_mod.escape(", ".join(p.get("authors", [])[:3]))
    if len(p.get("authors", [])) > 3:
        authors += f" +{len(p['authors']) - 3}"
    cat_name = html_mod.escape(data["category_name"])
    archive_label = html_mod.escape(data["archive_label"])
    rank = p["rank"]
    tier_name = tier["name"]

    image_url = f"{base_url}/api/badge/{category}/{year}/{slug}/{paper_id}/image.png"
    share_url = f"{base_url}/api/badge/{category}/{year}/{slug}/{paper_id}/share"
    leaderboard_url = f"{base_url}/leaderboard/{category}/{year}/{slug}"

    og_title = f"#{rank} {tier_name} in {cat_name} — {archive_label}"
    og_desc = f"{title} by {authors} | Ranked by scientific impact | Kurate.org"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{og_title} | Kurate.org</title>
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
<h1 style="font-size: 20px;">{og_title}</h1>
<p style="color: #666;">{title}</p>
<p style="color: #999; font-size: 14px;">by {authors}</p>
<p style="margin-top: 24px;"><a href="{leaderboard_url}" style="display: inline-block; padding: 10px 20px; background: #4285F4; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px;">View Leaderboard on Kurate.org</a></p>
</body>
</html>"""





def _esc(t):
    return html_mod.escape(str(t))


def _wordwrap(text, max_chars):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if len(test) > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _render_badge_image(data: dict) -> bytes:
    """Render badge using the designer SVG templates, inject dynamic data, convert to PNG."""
    import os
    paper = data["paper"]
    tier = data["tier"]
    rank = paper.get("rank_ts", paper.get("rank", 999))
    tier_name = tier["name"]

    # Load the correct SVG template
    template_map = {"Gold": "badge_gold.svg", "Silver": "badge_silver.svg", "Bronze": "badge_bronze.svg"}
    svg_path = os.path.join(os.path.dirname(__file__), "..", template_map.get(tier_name, "badge_silver.svg"))
    with open(svg_path, "r") as f:
        svg = f.read()

    # Dynamic data
    title_lines = _wordwrap(paper.get("title", ""), 52)
    title_line1 = _esc(title_lines[0]) if len(title_lines) > 0 else ""
    title_line2 = ""
    if len(title_lines) > 1:
        t2 = title_lines[1]
        if len(title_lines) > 2:
            t2 = t2[:-3] + "..." if len(t2) > 3 else "..."
        title_line2 = _esc(t2)

    authors = paper.get("authors", [])
    authors_str = _esc(", ".join(authors[:4]) + (f" +{len(authors)-4}" if len(authors) > 4 else ""))

    pub_date = paper.get("published", "")
    pub_str = ""
    if pub_date:
        try:
            from datetime import datetime as _dt
            pub_str = _dt.fromisoformat(pub_date.replace("Z", "+00:00")).strftime("Published %B %-d, %Y on arXiv.org")
        except Exception:
            pub_str = "Published on arXiv.org"

    categories = paper.get("categories") or data.get("categories") or [data.get("category", "")]
    cats_str = _esc("Category: " + ", ".join(categories[:4]))

    archive_label = _esc(data.get("archive_label", ""))
    cat_name = _esc(data.get("category_name", ""))
    paper_count = data.get("paper_count", "?")
    score = paper.get("score", "?")
    win_rate = paper.get("win_rate", "?")

    # Replace placeholder text in the SVG
    # Header
    svg = svg.replace(">Week 11, 2026<", f">{archive_label}<")
    svg = svg.replace(">Robotics Preprints<", f">{cat_name} Preprints<")

    # Tier label + rank
    tier_labels = {"Gold": "GOLD", "Silver": "SILVER", "Bronze": "BRONZE"}
    svg = svg.replace(f">{tier_labels.get(tier_name, 'SILVER')}<", f">{tier_name.upper()}<")
    svg = svg.replace(f">#{rank}<", f">#{rank}<")  # already correct

    # Title (two tspan lines)
    svg = svg.replace(">Data Analogies Enable Efficient<", f">{title_line1}<")
    svg = svg.replace(">Cross-Embodiment Transfer<", f">{title_line2}<")

    # Authors
    svg = svg.replace(">Jonathan Yang, Chelsea Finn, Dorsa Sadigh<", f">{authors_str}<")

    # Publication date
    svg = svg.replace(">Published March 8, 2026 on arXiv.org<", f">{_esc(pub_str)}<")

    # Categories
    svg = svg.replace(">cs.RO \u00b7 cs.AI \u00b7 cs.LG<", f">{cats_str}<")

    # Stats
    for r in [1, 2, 3]:
        svg = svg.replace(f'>Top {r} of 264<', f'>Top {rank} of {paper_count}<')
    svg = svg.replace(">1472<", f">{score}<")
    svg = svg.replace(">1520<", f">{score}<")
    svg = svg.replace(">1445<", f">{score}<")
    svg = svg.replace(">84.0%<", f">{win_rate}%<")
    svg = svg.replace(">89.2%<", f">{win_rate}%<")
    svg = svg.replace(">79.5%<", f">{win_rate}%<")

    # Render SVG to PNG at standard OG size (1200x630 = 1.91:1 ratio)
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=2400, output_height=1260)

# Monthly badges
@router.get("/{category}/{year}/m{month}/{paper_id}")
async def get_monthly_badge(category: str, year: int, month: int, paper_id: str):
    """Get badge data for a top-ranked paper in a monthly archive."""
    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "month": month, "period_type": "monthly"},
        {"_id": 0},
    )
    if not archive:
        raise HTTPException(404, "Archive not found")

    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found in this archive")

    tier = _get_tier(paper.get("rank_ts", paper.get("rank", 999)))
    if not tier:
        raise HTTPException(404, "Paper is not in the top 3 for this period")

    if not paper.get("comparisons"):
        raise HTTPException(404, "Paper has no tournament matches yet — badge unavailable")

    return {
        "title": paper.get("title"),
        "authors": paper.get("authors", []),
        "rank": paper.get("rank_ts", paper.get("rank", 999)),
        "score": paper.get("score"),
        "win_rate": paper.get("win_rate"),
        "comparisons": paper.get("comparisons"),
        "tier": tier["name"],
        "tier_color": tier["color"],
        "archive_label": archive.get("label", f"Month {month}, {year}"),
        "category": category,
        "category_name": CATEGORIES.get(category, category),
        "paper_count": archive.get("paper_count", len(lb)),
        "arxiv_id": paper.get("arxiv_id"),
        "paper_id": paper_id,
        "image_url": f"/api/badge/{category}/{year}/m{month}/{paper_id}/image.png",
    }

@router.get("/{category}/{year}/w{week}/{paper_id}/exists")
async def badge_exists(category: str, year: int, week: int, paper_id: str):
    """Quick check if a paper has a badge (top 3) in an archive."""
    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "week": week, "period_type": "weekly"},
        {"_id": 0, "leaderboard": {"$elemMatch": {"id": paper_id}}},
    )
    if not archive or not archive.get("leaderboard"):
        return {"has_badge": False}
    paper = archive["leaderboard"][0]
    tier = _get_tier(paper.get("rank", 999))
    return {"has_badge": bool(tier), "rank": paper.get("rank_ts", paper.get("rank")), "tier": tier["name"] if tier else None}

@router.get("/paper/{paper_id}/badges")
async def get_paper_badges(paper_id: str):
    """Get all badges (top 3 appearances) for a specific paper across all archives.
    Only returns badges matching the category's configured archive frequency (weekly or monthly)."""
    from core.auth import get_settings
    settings = await get_settings()
    archive_config = settings.get("archive_frequency", {})
    default_freq = archive_config.get("default", "weekly")

    archives = await db.leaderboard_archives.find(
        {"leaderboard": {"$elemMatch": {"id": paper_id, "rank_ts": {"$lte": 3}}},
         "period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1, "label": 1,
         "paper_count": 1, "leaderboard": {"$elemMatch": {"id": paper_id}}},
    ).sort([("year", -1), ("week", -1), ("month", -1)]).to_list(50)

    badges = []
    for a in archives:
        cat_freq = archive_config.get(a["category"], default_freq)
        if a.get("period_type") != cat_freq:
            continue
        lb = a.get("leaderboard", [])
        if not lb:
            continue
        p = lb[0]
        if not p.get("comparisons"):
            continue
        rank = p.get("rank_ts", p.get("rank", 999))
        tier = _get_tier(rank)
        if not tier:
            continue
        slug = f"w{a['week']}" if a.get("week") else f"m{a['month']}"
        badges.append({
            "tier": tier["name"],
            "tier_color": tier["color"],
            "rank": rank,
            "archive_label": a.get("label"),
            "category": a["category"],
            "category_name": CATEGORIES.get(a["category"], a["category"]),
            "badge_url": f"/badge/{a['category']}/{a['year']}/{slug}/{paper_id}",
        })
    return {"badges": badges}


    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found in this archive")

    tier = _get_tier(paper.get("rank_ts", paper.get("rank", 999)))
    if not tier:
        raise HTTPException(404, "Paper is not in the top 3 for this period")

    if not paper.get("comparisons"):
        raise HTTPException(404, "Paper has no tournament matches yet — badge unavailable")

    return {
        "title": paper.get("title"),
        "authors": paper.get("authors", []),
        "rank": paper.get("rank_ts", paper.get("rank", 999)),
        "score": paper.get("score"),
        "win_rate": paper.get("win_rate"),
        "comparisons": paper.get("comparisons"),
        "tier": tier["name"],
        "tier_color": tier["color"],
        "archive_label": archive.get("label", f"Month {month}, {year}"),
        "category": category,
        "category_name": CATEGORIES.get(category, category),
        "paper_count": archive.get("paper_count", len(lb)),
        "arxiv_id": paper.get("arxiv_id"),
        "paper_id": paper_id,
        "image_url": f"/api/badge/{category}/{year}/m{month}/{paper_id}/image.png",
    }


@router.get("/{category}/{year}/m{month}/{paper_id}/image.png")
async def get_monthly_badge_image(category: str, year: int, month: int, paper_id: str):
    """Serve pre-rendered monthly badge image, falling back to on-the-fly rendering."""
    from core.image_store import get_image, store_image
    store_key = f"badge:m:{category}/{year}/{month}/{paper_id}"
    stored = await get_image(store_key)
    if stored:
        return Response(content=stored, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    cached = _get_cached_image(store_key)
    if cached:
        return Response(content=cached, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "month": month, "period_type": "monthly"}, {"_id": 0})
    if not archive:
        raise HTTPException(404, "Archive not found")
    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found")
    tier = _get_tier(paper.get("rank_ts", paper.get("rank", 999)))
    if not tier:
        raise HTTPException(404, "Not in top 3")
    data = {"paper": paper, "tier": tier, "archive_label": archive.get("label"),
            "category": category, "category_name": CATEGORIES.get(category, category),
            "paper_count": archive.get("paper_count", len(lb))}
    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "categories": 1})
    data["categories"] = paper_doc["categories"] if paper_doc and paper_doc.get("categories") else [category]
    img_bytes = _render_badge_image(data)
    _set_cached_image(store_key, img_bytes)
    await store_image(store_key, img_bytes)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{category}/badges")
async def list_badges_for_category(category: str, period_type: str = Query("weekly")):
    """List all badge-eligible papers (top 3) across all archives for a category."""
    query = {"category": category, "period_type": period_type}
    archives = await db.leaderboard_archives.find(
        query, {"_id": 0, "leaderboard": {"$slice": 3}, "label": 1, "year": 1, "week": 1, "month": 1, "paper_count": 1}
    ).sort([("year", -1), ("week", -1), ("month", -1)]).to_list(100)

    badges = []
    for a in archives:
        for p in a.get("leaderboard", [])[:3]:
            tier = _get_tier(p["rank"])
            if tier:
                slug = f"w{a['week']}" if a.get("week") else f"m{a['month']}"
                badges.append({
                    "paper_id": p["id"],
                    "title": p.get("title"),
                    "authors": p.get("authors", []),
                    "rank": p["rank"],
                    "score": p.get("score"),
                    "tier": tier["name"],
                    "tier_color": tier["color"],
                    "archive_label": a.get("label"),
                    "badge_url": f"/badge/{category}/{a['year']}/{slug}/{p['id']}",
                    "image_url": f"/api/badge/{category}/{a['year']}/{slug}/{p['id']}/image.png",
                })
    return {"badges": badges}
