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



def _draw_trophy(draw, x, y, size, color):
    """Draw a simple trophy icon using geometric shapes."""
    s = size
    # Cup body (trapezoid via polygon)
    draw.polygon([
        (x - s * 0.4, y - s * 0.1),
        (x + s * 0.4, y - s * 0.1),
        (x + s * 0.25, y + s * 0.35),
        (x - s * 0.25, y + s * 0.35),
    ], fill=color)
    # Cup rim
    draw.rectangle([(x - s * 0.45, y - s * 0.2), (x + s * 0.45, y - s * 0.1)], fill=color)
    # Stem
    draw.rectangle([(x - s * 0.06, y + s * 0.35), (x + s * 0.06, y + s * 0.5)], fill=color)
    # Base
    draw.rectangle([(x - s * 0.2, y + s * 0.47), (x + s * 0.2, y + s * 0.55)], fill=color)


def _render_badge_image(data: dict) -> bytes:
    """Render a rich card badge image using Pillow."""
    W, H = 1200, 630
    paper = data["paper"]
    tier = data["tier"]
    rank = paper["rank"]

    # Colors
    bg_color = (15, 15, 25)
    card_color = (25, 25, 40)
    text_white = (240, 240, 245)
    text_muted = (140, 140, 160)
    text_dim = (80, 85, 100)
    tier_hex = tier["color"]
    tier_rgb = tuple(int(tier_hex.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    accent = (100, 120, 255)

    img = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    # Fonts
    try:
        font_title = ImageFont.truetype(FONT_BOLD, 32)
        font_large = ImageFont.truetype(FONT_BOLD, 72)
        font_tier = ImageFont.truetype(FONT_BOLD, 28)
        font_body = ImageFont.truetype(FONT_REGULAR, 22)
        font_small = ImageFont.truetype(FONT_REGULAR, 18)
        font_logo = ImageFont.truetype(FONT_BOLD, 22)
        font_logo_sm = ImageFont.truetype(FONT_REGULAR, 16)
        font_stat_val = ImageFont.truetype(FONT_BOLD, 26)
        font_stat_lbl = ImageFont.truetype(FONT_REGULAR, 14)
    except Exception:
        font_title = font_large = font_tier = font_body = font_small = ImageFont.load_default()
        font_logo = font_logo_sm = font_stat_val = font_stat_lbl = font_small

    # Card background
    card_margin = 40
    draw.rounded_rectangle(
        [card_margin, card_margin, W - card_margin, H - card_margin],
        radius=20, fill=card_color,
    )

    # === TOP ROW: Logo (left) + Category/Period (right) ===
    header_y = 55

    # Trophy icon + PaperSumo brand (top-left)
    _draw_trophy(draw, 85, header_y + 12, 22, accent)
    logo_x = 105
    draw.text((logo_x, header_y - 2), "Paper", fill=text_white, font=font_logo)
    paper_bbox = draw.textbbox((0, 0), "Paper", font=font_logo)
    draw.text((logo_x + paper_bbox[2] - paper_bbox[0], header_y - 2), "Sumo", fill=accent, font=font_logo)
    sumo_bbox = draw.textbbox((0, 0), "Sumo", font=font_logo)
    by_x = logo_x + paper_bbox[2] - paper_bbox[0] + sumo_bbox[2] - sumo_bbox[0] + 8
    draw.text((by_x, header_y + 3), "by Kurate.org", fill=text_dim, font=font_logo_sm)

    # Category + Period (top-right)
    period_text = f"{data['category_name']}  ·  {data['archive_label']}"
    period_bbox = draw.textbbox((0, 0), period_text, font=font_small)
    draw.text((W - 60 - (period_bbox[2] - period_bbox[0]), header_y + 2), period_text, fill=text_muted, font=font_small)

    # Thin separator
    draw.line([(60, header_y + 38), (W - 60, header_y + 38)], fill=(40, 42, 55), width=1)

    # === MAIN SECTION: Medal + Content ===
    main_y = header_y + 55

    # Left: Medal circle
    cx, cy = 160, main_y + 100
    medal_r = 65
    for i in range(3):
        r = medal_r + 7 - i * 3
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=None, outline=tier_rgb, width=2)
    draw.ellipse([cx - medal_r, cy - medal_r, cx + medal_r, cy + medal_r], fill=tier_rgb)
    rank_text = f"#{rank}"
    rank_bbox = draw.textbbox((0, 0), rank_text, font=font_large)
    rank_w = rank_bbox[2] - rank_bbox[0]
    rank_h = rank_bbox[3] - rank_bbox[1]
    draw.text((cx - rank_w // 2, cy - rank_h // 2 - 6), rank_text, fill=(255, 255, 255), font=font_large)

    # Right: Content
    content_x = 270
    content_w = W - content_x - 60

    # Tier label
    draw.text((content_x, main_y), tier["name"].upper(), fill=tier_rgb, font=font_tier)

    # Paper title (2 lines max)
    title_y = main_y + 45
    title = paper.get("title", "")
    words = title.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font_title)
        if bbox[2] - bbox[0] > content_w:
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
        draw.text((content_x, title_y + i * 40), line, fill=text_white, font=font_title)

    # Authors
    authors_y = title_y + 40 * min(len(lines), 2) + 12
    authors = paper.get("authors", [])
    authors_str = ", ".join(authors[:4])
    if len(authors) > 4:
        authors_str += f" +{len(authors) - 4}"
    draw.text((content_x, authors_y), _truncate(authors_str, 85), fill=text_muted, font=font_body)

    # === BOTTOM: Stats row ===
    stats_y = H - 145
    draw.line([(60, stats_y - 15), (W - 60, stats_y - 15)], fill=(40, 42, 55), width=1)

    paper_count = data['paper_count']
    stats = [
        (str(paper.get("score", "?")), "ELO SCORE"),
        (f"{paper.get('win_rate', '?')}%", "WIN RATE"),
        (f"Top {rank} of {paper_count}", "RANKING"),
    ]

    col_w = content_w // len(stats)
    for i, (val, label) in enumerate(stats):
        sx = content_x + i * col_w
        draw.text((sx, stats_y), val, fill=text_white, font=font_stat_val)
        draw.text((sx, stats_y + 35), label, fill=text_dim, font=font_stat_lbl)

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
