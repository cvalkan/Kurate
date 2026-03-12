"""Shareable badge generation for top-ranked papers."""

import io
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
from PIL import Image, ImageDraw, ImageFont
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
    og_desc = f"{title} by {authors} | Score {score} | PaperSumo by Kurate.org"

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



def _render_badge_image(data: dict) -> bytes:
    """Render the 'Obsidian Slab' badge image (1200x630) using Pillow."""
    W, H = 1200, 630
    paper = data["paper"]
    tier = data["tier"]
    rank = paper["rank"]

    # --- Color palette ---
    bg = (15, 23, 42)         # Deep midnight navy
    text_primary = (255, 255, 255)
    text_secondary = (148, 163, 184)  # Slate-400
    text_tertiary = (71, 85, 105)     # Slate-600
    tier_hex = tier["color"]
    tier_rgb = tuple(int(tier_hex.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))

    # Tier-specific dark accent for sidebar
    tier_accents = {
        "Gold":   (69, 26, 3),    # #451a03
        "Silver": (30, 41, 59),   # #1e293b
        "Bronze": (67, 20, 7),    # #431407
    }
    sidebar_bg = tier_accents.get(tier["name"], (30, 30, 50))

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # --- Fonts ---
    try:
        f_rank = ImageFont.truetype(FONT_BOLD, 160)
        f_tier = ImageFont.truetype(FONT_BOLD, 32)
        f_title = ImageFont.truetype(FONT_BOLD, 40)
        f_authors = ImageFont.truetype(FONT_REGULAR, 26)
        f_stat_val = ImageFont.truetype(FONT_BOLD, 38)
        f_stat_lbl = ImageFont.truetype(FONT_REGULAR, 16)
        f_brand = ImageFont.truetype(FONT_BOLD, 22)
        f_label = ImageFont.truetype(FONT_REGULAR, 20)
    except Exception:
        f_rank = f_tier = f_title = f_authors = f_stat_val = f_stat_lbl = f_brand = f_label = ImageFont.load_default()

    # --- Sidebar (left 280px) ---
    sidebar_w = 280
    draw.rectangle([(0, 0), (sidebar_w, H)], fill=sidebar_bg)
    # Bright accent line on the right edge of sidebar
    draw.rectangle([(sidebar_w - 4, 0), (sidebar_w, H)], fill=tier_rgb)

    # Rank number (centered in sidebar)
    rank_text = f"#{rank}"
    rank_bbox = draw.textbbox((0, 0), rank_text, font=f_rank)
    rank_w = rank_bbox[2] - rank_bbox[0]
    rank_h = rank_bbox[3] - rank_bbox[1]
    draw.text(
        (sidebar_w // 2 - rank_w // 2, H // 2 - rank_h // 2 - 40),
        rank_text, fill=tier_rgb, font=f_rank,
    )

    # Tier label below rank
    tier_text = tier["name"].upper()
    tier_bbox = draw.textbbox((0, 0), tier_text, font=f_tier)
    tier_w = tier_bbox[2] - tier_bbox[0]
    draw.text(
        (sidebar_w // 2 - tier_w // 2, H // 2 + rank_h // 2 - 20),
        tier_text, fill=tier_rgb, font=f_tier,
    )

    # --- Main content area (right 75%) ---
    cx = sidebar_w + 60  # Content X start
    cw = W - cx - 50     # Content width

    # Category + Archive label (top)
    label_y = 50
    label_text = f"{data['category_name']}  ·  {data['archive_label']}"
    draw.text((cx, label_y), label_text, fill=text_secondary, font=f_label)

    # Paper title (max 2 lines, word-wrapped)
    title_y = label_y + 45
    title = paper.get("title", "")
    words = title.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=f_title)
        if bbox[2] - bbox[0] > cw:
            if current_line:
                lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)
    for i, line in enumerate(lines[:2]):
        if i == 1 and len(lines) > 2:
            line = line[:-3] + "..." if len(line) > 3 else "..."
        draw.text((cx, title_y + i * 52), line, fill=text_primary, font=f_title)

    # Authors
    authors_y = title_y + 52 * min(len(lines), 2) + 20
    authors = paper.get("authors", [])
    authors_str = ", ".join(authors[:4])
    if len(authors) > 4:
        authors_str += f"  +{len(authors) - 4}"
    draw.text((cx, authors_y), _truncate(authors_str, 75), fill=text_secondary, font=f_authors)

    # --- Stats grid (bottom section) ---
    stats_y = 430
    # Horizontal divider
    draw.line([(cx, stats_y - 20), (W - 50, stats_y - 20)], fill=text_tertiary, width=1)

    stats = [
        (str(paper.get("score", "?")), "ELO SCORE"),
        (f"{paper.get('win_rate', '?')}%", "WIN RATE"),
        (str(paper.get("comparisons", "?")), "MATCHES"),
        (f"of {data['paper_count']}", "PAPERS"),
    ]
    col_w = cw // 4
    for i, (val, label) in enumerate(stats):
        sx = cx + i * col_w
        draw.text((sx, stats_y), val, fill=text_primary, font=f_stat_val)
        draw.text((sx, stats_y + 48), label, fill=text_tertiary, font=f_stat_lbl)

    # --- Branding (bottom right) ---
    brand_text = "PaperSumo by Kurate.org"
    brand_bbox = draw.textbbox((0, 0), brand_text, font=f_brand)
    brand_w = brand_bbox[2] - brand_bbox[0]
    draw.text((W - 50 - brand_w, H - 50), brand_text, fill=text_secondary, font=f_brand)

    # Export
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


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
