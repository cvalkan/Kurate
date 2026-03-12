"""Shareable badge generation for top-ranked papers."""

import io
import html as html_mod
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
import cairosvg
from typing import Optional

from core.config import db, logger

router = APIRouter(prefix="/api/badge")

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

    tier = _get_tier(paper["rank"])
    if not tier:
        raise HTTPException(404, "Paper is not in the top 3 for this period")

    return {
        "paper": paper,
        "tier": tier,
        "archive_label": archive.get("label", f"Week {week}, {year}"),
        "category": category,
        "category_name": CATEGORIES.get(category, category),
        "paper_count": archive.get("paper_count", len(lb)),
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
    """Generate OG-sized badge image (1200x630) for social sharing."""
    data = await _get_badge_data(category, year, week, paper_id)
    img_bytes = _render_badge_image(data)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{category}/{year}/w{week}/{paper_id}/share", response_class=HTMLResponse)
async def get_badge_share_page(category: str, year: int, week: int, paper_id: str, request: Request):
    """Server-rendered HTML page with OG meta tags for social sharing.
    Crawlers (Twitter, LinkedIn) get the OG tags. Browsers get redirected to the SPA."""
    data = await _get_badge_data(category, year, week, paper_id)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    scheme = request.headers.get("x-forwarded-proto", "https")
    base_url = f"{scheme}://{host}"
    return _render_share_html(data, category, year, f"w{week}", paper_id, base_url)


@router.get("/{category}/{year}/m{month}/{paper_id}/share", response_class=HTMLResponse)
async def get_monthly_badge_share_page(category: str, year: int, month: int, paper_id: str, request: Request):
    """Server-rendered share page for monthly badges."""
    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "month": month, "period_type": "monthly"}, {"_id": 0})
    if not archive:
        raise HTTPException(404, "Archive not found")
    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found")
    tier = _get_tier(paper["rank"])
    if not tier:
        raise HTTPException(404, "Not in top 3")
    data = {"paper": paper, "tier": tier, "archive_label": archive.get("label"),
            "category": category, "category_name": CATEGORIES.get(category, category),
            "paper_count": archive.get("paper_count", len(lb)), "year": year}
    base_url = f"{request.headers.get('x-forwarded-proto', 'https')}://{request.headers.get('x-forwarded-host', request.headers.get('host', ''))}"
    return _render_share_html(data, category, year, f"m{month}", paper_id, base_url)


def _render_share_html(data: dict, category: str, year: int, slug: str, paper_id: str, base_url: str) -> str:
    """Generate HTML with OG meta tags for social crawlers + browser redirect."""
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
    score = p.get("score", "?")
    tier_name = tier["name"]

    # Absolute URLs for social crawlers
    image_url = f"{base_url}/api/badge/{category}/{year}/{slug}/{paper_id}/image.png"
    # Redirect browsers to the archive page with the paper highlighted
    redirect_url = f"/?cat={category}&archive={year}-{slug}"
    canonical_url = f"{base_url}/api/badge/{category}/{year}/{slug}/{paper_id}/share"

    og_title = f"#{rank} {tier_name} in {cat_name} — {archive_label}"
    og_desc = f"{title} by {authors} | Ranked by scientific impact | Kurate.org"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{og_title} | PaperSumo</title>
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="{image_url}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{canonical_url}">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{image_url}">
<meta http-equiv="refresh" content="0;url={redirect_url}">
</head>
<body>
<p>Redirecting to <a href="{redirect_url}">archive page</a>...</p>
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
    rank = paper["rank"]
    tier_name = tier["name"]

    # Load the correct SVG template
    template_map = {"Gold": "badge_gold.svg", "Silver": "badge_silver.svg", "Bronze": "badge_bronze.svg"}
    svg_path = os.path.join(os.path.dirname(__file__), "..", template_map.get(tier_name, "badge_silver.svg"))
    with open(svg_path, "r") as f:
        svg = f.read()

    # Dynamic data
    title_lines = _wordwrap(paper.get("title", ""), 32)
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

    categories = paper.get("categories") or [data.get("category", "")]
    cats_str = _esc(" \u00b7 ".join(categories[:4]))

    archive_label = _esc(data.get("archive_label", ""))
    cat_name = _esc(data.get("category_name", ""))
    paper_count = data.get("paper_count", "?")
    score = paper.get("score", "?")
    win_rate = paper.get("win_rate", "?")

    # Replace placeholder text in the SVG
    # Header
    svg = svg.replace(">Week 11, 2026<", f">{archive_label}<")
    svg = svg.replace(">Robotics Preprints<", f">{cat_name} Preprints<")
    svg = svg.replace(">arXiv (cs.RO)<", f">arXiv ({_esc(data.get('category', ''))})<")

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
    svg = svg.replace(f">Top {rank} of 264<", f">Top {rank} of {paper_count}<")
    # Handle all three rank variants
    for r in [1, 2, 3]:
        svg = svg.replace(f">Top {r} of 264<", f">Top {rank} of {paper_count}<")
    svg = svg.replace(">1472<", f">{score}<")
    svg = svg.replace(">1520<", f">{score}<")
    svg = svg.replace(">1445<", f">{score}<")
    svg = svg.replace(">84.0%<", f">{win_rate}%<")
    svg = svg.replace(">89.2%<", f">{win_rate}%<")
    svg = svg.replace(">79.5%<", f">{win_rate}%<")

    # Render SVG to PNG at OG image size (1200x630)
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=1280, output_height=784)

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
    return {"has_badge": bool(tier), "rank": paper.get("rank"), "tier": tier["name"] if tier else None}

@router.get("/paper/{paper_id}/badges")
async def get_paper_badges(paper_id: str):
    """Get all badges (top 3 appearances) for a specific paper across all archives."""
    archives = await db.leaderboard_archives.find(
        {"leaderboard": {"$elemMatch": {"id": paper_id, "rank": {"$lte": 3}}}},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1, "label": 1,
         "paper_count": 1, "leaderboard": {"$elemMatch": {"id": paper_id}}},
    ).sort([("year", -1), ("week", -1), ("month", -1)]).to_list(50)

    badges = []
    for a in archives:
        lb = a.get("leaderboard", [])
        if not lb:
            continue
        p = lb[0]
        tier = _get_tier(p.get("rank", 999))
        if not tier:
            continue
        slug = f"w{a['week']}" if a.get("week") else f"m{a['month']}"
        badges.append({
            "tier": tier["name"],
            "tier_color": tier["color"],
            "rank": p["rank"],
            "archive_label": a.get("label"),
            "category": a["category"],
            "category_name": CATEGORIES.get(a["category"], a["category"]),
            "badge_url": f"/badge/{a['category']}/{a['year']}/{slug}/{paper_id}",
        })
    return {"badges": badges}


    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found in this archive")

    tier = _get_tier(paper["rank"])
    if not tier:
        raise HTTPException(404, "Paper is not in the top 3 for this period")

    return {
        "title": paper.get("title"),
        "authors": paper.get("authors", []),
        "rank": paper["rank"],
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
    """Generate OG badge image for monthly archive."""
    archive = await db.leaderboard_archives.find_one(
        {"category": category, "year": year, "month": month, "period_type": "monthly"},
        {"_id": 0},
    )
    if not archive:
        raise HTTPException(404, "Archive not found")

    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found")

    tier = _get_tier(paper["rank"])
    if not tier:
        raise HTTPException(404, "Not in top 3")

    data = {
        "paper": paper, "tier": tier,
        "archive_label": archive.get("label"),
        "category": category,
        "category_name": CATEGORIES.get(category, category),
        "paper_count": archive.get("paper_count", len(lb)),
    }
    img_bytes = _render_badge_image(data)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


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
