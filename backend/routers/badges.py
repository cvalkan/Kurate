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



def _draw_medal(draw, cx, cy, radius, tier_name, rank, font):
    """Draw a sleek 3D medal coin with proper gold/silver/bronze coloring."""
    r = radius
    # Tier-specific color palettes for realistic metal look
    palettes = {
        "Gold": {
            "rim": (160, 120, 10), "face": (212, 175, 55), "inner": (235, 200, 80),
            "highlight": (255, 235, 150), "shadow": (130, 95, 5),
        },
        "Silver": {
            "rim": (120, 120, 130), "face": (180, 185, 195), "inner": (200, 205, 215),
            "highlight": (235, 238, 245), "shadow": (95, 95, 105),
        },
        "Bronze": {
            "rim": (140, 85, 20), "face": (205, 127, 50), "inner": (225, 155, 80),
            "highlight": (245, 195, 140), "shadow": (110, 65, 10),
        },
    }
    p = palettes.get(tier_name, palettes["Silver"])

    # Outer rim
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=p["rim"])
    # Main face
    inner_r = r - 5
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=p["face"])
    # Raised inner disc
    disc_r = r - 12
    draw.ellipse([cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r], fill=p["inner"])
    # Rim groove (between rim and face)
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=None, outline=p["shadow"], width=1)
    draw.ellipse([cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r], fill=None, outline=p["rim"], width=1)
    # Top highlight arc (simulate light source top-left)
    hl_r = r - 16
    draw.arc([cx - hl_r - 4, cy - hl_r - 4, cx + hl_r - 8, cy + hl_r - 8], start=200, end=340, fill=p["highlight"], width=3)
    # Rank text with shadow
    rank_text = f"#{rank}"
    bbox = draw.textbbox((0, 0), rank_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw // 2 + 1, cy - th // 2 - 3), rank_text, fill=p["shadow"], font=font)
    draw.text((cx - tw // 2, cy - th // 2 - 4), rank_text, fill=(255, 255, 255), font=font)


def _draw_kurate_wordmark(draw, x, y, font_bold, font_regular, color_dark, color_accent):
    """Draw the Kurate.org wordmark. 'Ku' and '.org' in accent, 'rate' in dark."""
    # All same font size (font_bold for everything)
    draw.text((x, y), "Ku", fill=color_accent, font=font_bold)
    ku_bbox = draw.textbbox((0, 0), "Ku", font=font_bold)
    kw = ku_bbox[2] - ku_bbox[0]
    draw.text((x + kw - 1, y), "rate", fill=color_dark, font=font_bold)
    rate_bbox = draw.textbbox((0, 0), "rate", font=font_bold)
    rw = rate_bbox[2] - rate_bbox[0]
    draw.text((x + kw + rw - 1, y), ".org", fill=color_accent, font=font_regular)


def _render_badge_image(data: dict) -> bytes:
    """Render a light card badge image (1200x630) for social sharing."""
    W, H = 1200, 630
    paper = data["paper"]
    tier = data["tier"]
    rank = paper["rank"]

    tier_hex = tier["color"]
    tier_rgb = tuple(int(tier_hex.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    tier_bg = {
        "Gold": (255, 251, 235), "Silver": (249, 250, 251), "Bronze": (255, 247, 237),
    }.get(tier["name"], (249, 250, 251))

    bg = (245, 245, 248)
    card_bg = tier_bg
    text_dark = (26, 26, 46)
    text_muted = (130, 130, 150)
    accent = (70, 90, 220)
    divider = (210, 210, 220)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        f_header = ImageFont.truetype(FONT_BOLD, 26)
        f_header_sm = ImageFont.truetype(FONT_REGULAR, 20)
        f_tier = ImageFont.truetype(FONT_BOLD, 20)
        f_title = ImageFont.truetype(FONT_BOLD, 38)
        f_rank = ImageFont.truetype(FONT_BOLD, 58)
        f_authors = ImageFont.truetype(FONT_REGULAR, 24)
        f_stat_val = ImageFont.truetype(FONT_BOLD, 36)
        f_stat_lbl = ImageFont.truetype(FONT_REGULAR, 18)
        f_footer = ImageFont.truetype(FONT_REGULAR, 20)
        f_brand = ImageFont.truetype(FONT_BOLD, 50)
        f_brand_reg = ImageFont.truetype(FONT_REGULAR, 50)
        f_brand_sm = ImageFont.truetype(FONT_REGULAR, 30)
    except Exception:
        f_header = f_header_sm = f_tier = f_title = f_rank = f_authors = ImageFont.load_default()
        f_stat_val = f_stat_lbl = f_footer = f_brand = f_brand_sm = f_header

    # Card with tier-colored border
    m = 28
    draw.rounded_rectangle([m - 2, m - 2, W - m + 2, H - m + 2], radius=18, fill=tier_rgb)
    draw.rounded_rectangle([m, m, W - m, H - m], radius=16, fill=card_bg)

    pad = 45

    # === TOP ROW: Period + Category (left) · Kurate wordmark (right) ===
    top_y = m + 22
    cat_name = data["category_name"]
    header_text = f"{data['archive_label']}  ·  {cat_name} Preprints  ·  arXiv"
    draw.text((m + pad, top_y), header_text, fill=text_dark, font=f_header)

    # Kurate.org wordmark (right, large)
    _draw_kurate_wordmark(draw, W - m - pad - 380, top_y - 8, f_brand, f_brand_reg, text_dark, accent)

    # === MEDAL + TITLE + AUTHORS ===
    section_y = top_y + 50
    medal_r = 50
    cx = m + pad + medal_r + 5
    cy = section_y + medal_r + 15
    _draw_medal(draw, cx, cy, medal_r, tier["name"], rank, f_rank)

    content_x = cx + medal_r + 28
    content_w = W - m - pad - content_x

    # Tier label
    draw.text((content_x, section_y), tier["name"].upper(), fill=tier_rgb, font=f_tier)

    # Title (max 2 lines)
    title_y = section_y + 30
    title = paper.get("title", "")
    words = title.split()
    lines, cur = [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=f_title)
        if bbox[2] - bbox[0] > content_w:
            if cur:
                lines.append(cur)
            cur = word
        else:
            cur = test
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines[:2]):
        if i == 1 and len(lines) > 2:
            line = line[:-3] + "..." if len(line) > 3 else "..."
        draw.text((content_x, title_y + i * 48), line, fill=text_dark, font=f_title)

    # Authors
    authors_y = title_y + 48 * min(len(lines), 2) + 10
    authors = paper.get("authors", [])
    authors_str = ", ".join(authors[:4])
    if len(authors) > 4:
        authors_str += f" +{len(authors) - 4}"
    draw.text((content_x, authors_y), _truncate(authors_str, 70), fill=text_muted, font=f_authors)

    # === STATS ROW (3 boxes) ===
    stats_y = H - m - 155
    draw.line([(m + pad, stats_y - 12), (W - m - pad, stats_y - 12)], fill=divider, width=1)

    paper_count = data["paper_count"]
    stats = [
        (f"Top {rank} of {paper_count}", "Papers"),
        (str(paper.get("score", "?")), "Elo Score"),
        (f"{paper.get('win_rate', '?')}%", "Win Rate"),
    ]

    total_w = W - 2 * m - 2 * pad
    box_w = (total_w - 20) // 3
    for i, (val, label) in enumerate(stats):
        bx = m + pad + i * (box_w + 10)
        draw.rounded_rectangle([(bx, stats_y), (bx + box_w, stats_y + 85)], radius=10, fill=(255, 255, 255))
        vbbox = draw.textbbox((0, 0), val, font=f_stat_val)
        vw = vbbox[2] - vbbox[0]
        draw.text((bx + box_w // 2 - vw // 2, stats_y + 10), val, fill=text_dark, font=f_stat_val)
        lbbox = draw.textbbox((0, 0), label, font=f_stat_lbl)
        lw = lbbox[2] - lbbox[0]
        draw.text((bx + box_w // 2 - lw // 2, stats_y + 55), label, fill=text_muted, font=f_stat_lbl)

    # === FOOTER ===
    footer_y = H - m - 48
    draw.text((m + pad, footer_y),
        "Ranked by novelty, rigor, significance & clarity via AI pairwise tournament",
        fill=text_muted, font=f_footer)

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
