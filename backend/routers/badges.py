"""Shareable badge generation for top-ranked papers."""

import io
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
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


def _render_badge_image(data: dict) -> bytes:
    """Render a rich card badge image using Pillow."""
    W, H = 1200, 630
    paper = data["paper"]
    tier = data["tier"]
    rank = paper["rank"]

    # Colors
    bg_color = (15, 15, 25)  # Dark navy
    card_color = (25, 25, 40)
    text_white = (240, 240, 245)
    text_muted = (140, 140, 160)
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
        font_logo = ImageFont.truetype(FONT_BOLD, 26)
    except Exception:
        font_title = font_large = font_tier = font_body = font_small = font_logo = ImageFont.load_default()

    # Card background with rounded feel (draw a lighter rect)
    card_margin = 40
    draw.rounded_rectangle(
        [card_margin, card_margin, W - card_margin, H - card_margin],
        radius=20, fill=card_color,
    )

    # Left section: Medal circle
    cx, cy = 160, H // 2
    medal_r = 70
    # Medal glow
    for i in range(3):
        r = medal_r + 8 - i * 3
        alpha_color = tuple(min(255, c + 30) for c in tier_rgb)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=None, outline=alpha_color, width=2)
    # Medal circle
    draw.ellipse([cx - medal_r, cy - medal_r, cx + medal_r, cy + medal_r], fill=tier_rgb)
    # Rank number inside medal
    rank_text = f"#{rank}"
    rank_bbox = draw.textbbox((0, 0), rank_text, font=font_large)
    rank_w = rank_bbox[2] - rank_bbox[0]
    rank_h = rank_bbox[3] - rank_bbox[1]
    draw.text((cx - rank_w // 2, cy - rank_h // 2 - 8), rank_text, fill=(255, 255, 255), font=font_large)

    # Right section: Content
    content_x = 270
    content_w = W - content_x - 60

    # Tier name + category
    tier_y = 75
    draw.text((content_x, tier_y), tier["name"].upper(), fill=tier_rgb, font=font_tier)
    cat_text = f"  {data['category_name']}"
    tier_bbox = draw.textbbox((0, 0), tier["name"].upper(), font=font_tier)
    draw.text((content_x + tier_bbox[2] - tier_bbox[0], tier_y), cat_text, fill=text_muted, font=font_tier)

    # Paper title (2 lines max)
    title_y = tier_y + 50
    title = paper.get("title", "")
    # Word wrap
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
    # Show max 2 lines
    for i, line in enumerate(lines[:2]):
        if i == 1 and len(lines) > 2:
            line = line[:len(line)-3] + "..."
        draw.text((content_x, title_y + i * 40), line, fill=text_white, font=font_title)

    # Authors (1 line)
    authors_y = title_y + 40 * min(len(lines), 2) + 15
    authors = paper.get("authors", [])
    authors_str = ", ".join(authors[:3])
    if len(authors) > 3:
        authors_str += f" +{len(authors) - 3}"
    draw.text((content_x, authors_y), _truncate(authors_str, 80), fill=text_muted, font=font_body)

    # Stats row
    stats_y = authors_y + 45
    stats = [
        (f"Score {paper.get('score', '?')}", text_white),
        (f"Win Rate {paper.get('win_rate', '?')}%", text_white),
        (f"{paper.get('comparisons', '?')} matches", text_muted),
        (f"of {data['paper_count']} papers", text_muted),
    ]
    sx = content_x
    for text, color in stats:
        draw.text((sx, stats_y), text, fill=color, font=font_body)
        bbox = draw.textbbox((0, 0), text, font=font_body)
        sx += bbox[2] - bbox[0] + 30

    # Divider line
    div_y = stats_y + 45
    draw.line([(content_x, div_y), (W - 60, div_y)], fill=(50, 50, 70), width=1)

    # Footer: Archive label + Kurate branding
    footer_y = div_y + 15
    draw.text((content_x, footer_y), data["archive_label"], fill=text_muted, font=font_small)

    # Kurate logo text (right side)
    logo_text = "PaperSumo by Kurate.org"
    logo_bbox = draw.textbbox((0, 0), logo_text, font=font_logo)
    draw.text((W - 60 - (logo_bbox[2] - logo_bbox[0]), footer_y - 2), logo_text, fill=accent, font=font_logo)

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
