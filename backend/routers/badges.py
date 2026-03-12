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




def _esc(text: str) -> str:
    """Escape text for SVG XML."""
    return html_mod.escape(str(text))


def _svg_medal(cx, cy, r, tier_name, rank):
    """Generate SVG elements for a 3D medal coin."""
    colors = {
        "Gold": {"rim": "#a07a0a", "face": "#d4af37", "inner": "#ebc850", "hl": "#ffeb96", "sh": "#825f05"},
        "Silver": {"rim": "#78788a", "face": "#b4b9c3", "inner": "#c8cdd7", "hl": "#ebeef5", "sh": "#5f5f69"},
        "Bronze": {"rim": "#8c5514", "face": "#cd7f32", "inner": "#e19b50", "hl": "#f5c38c", "sh": "#6e410a"},
    }
    c = colors.get(tier_name, colors["Silver"])
    return f"""
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="{c['rim']}"/>
    <circle cx="{cx}" cy="{cy}" r="{r - 4}" fill="{c['face']}"/>
    <circle cx="{cx}" cy="{cy}" r="{r - 11}" fill="{c['inner']}"/>
    <circle cx="{cx}" cy="{cy}" r="{r - 4}" fill="none" stroke="{c['sh']}" stroke-width="1"/>
    <circle cx="{cx}" cy="{cy}" r="{r - 11}" fill="none" stroke="{c['rim']}" stroke-width="1"/>
    <path d="M {cx - r + 20} {cy - r + 24} A {r - 16} {r - 16} 0 0 1 {cx + r - 28} {cy - r + 18}" fill="none" stroke="{c['hl']}" stroke-width="3" stroke-linecap="round"/>
    <text x="{cx}" y="{cy + 2}" font-family="Liberation Sans" font-weight="bold" font-size="56" fill="{c['sh']}" text-anchor="middle" dominant-baseline="central" dx="1" dy="1">#{rank}</text>
    <text x="{cx}" y="{cy}" font-family="Liberation Sans" font-weight="bold" font-size="56" fill="white" text-anchor="middle" dominant-baseline="central">#{rank}</text>
    """


def _svg_wordwrap(text, max_chars):
    """Split text into lines of max_chars, breaking on words."""
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
    """Render badge as SVG then convert to pixel-perfect PNG via CairoSVG."""
    W, H = 1200, 630
    paper = data["paper"]
    tier = data["tier"]
    rank = paper["rank"]
    tier_name = tier["name"]
    tier_hex = tier["color"]

    tier_bg = {"Gold": "#fffbeb", "Silver": "#f9fafb", "Bronze": "#fff7ed"}.get(tier_name, "#f9fafb")
    accent = "#465adc"
    dark = "#1a1a2e"
    muted = "#82829a"

    # --- Layout ---
    M = 30; P = 50
    CW = W - 2*M - 2*P

    hdr_y = 78
    content_y = 100  # tighter: was 115
    medal_r = 48
    medal_cx = M + P + medal_r
    medal_cy = content_y + medal_r + 18
    tx = medal_cx + medal_r + 25

    medal_svg = _svg_medal(medal_cx, medal_cy, medal_r, tier_name, rank)

    # Title
    title_lines = _svg_wordwrap(paper.get("title", ""), 36)
    tier_lbl_y = content_y + 14
    title_y0 = tier_lbl_y + 32
    title_svg = ""
    for i, line in enumerate(title_lines[:2]):
        d = _esc(line)
        if i == 1 and len(title_lines) > 2:
            d = _esc(line[:-3] + "...") if len(line) > 3 else "..."
        title_svg += f'<text x="{tx}" y="{title_y0 + i * 44}" font-family="Liberation Sans" font-weight="bold" font-size="36" fill="{dark}">{d}</text>\n'

    # Authors
    authors = paper.get("authors", [])
    a_str = ", ".join(authors[:4])
    if len(authors) > 4:
        a_str += f" +{len(authors) - 4}"
    auth_y = title_y0 + min(len(title_lines), 2) * 44 + 8

    # Categories + publication date (new row after authors)
    categories = paper.get("categories") or [data.get("category", "")]
    pub_date = paper.get("published", "")
    if pub_date:
        try:
            from datetime import datetime as _dt
            pub_dt = _dt.fromisoformat(pub_date.replace("Z", "+00:00"))
            pub_str = pub_dt.strftime("%b %d, %Y")
        except Exception:
            pub_str = ""
    else:
        pub_str = ""
    cats_str = " · ".join(categories[:3])
    if pub_str:
        cats_str += f"  ·  {pub_str}"
    meta_y = auth_y + 30

    # Stats: tight after metadata
    stats_h = 80
    sy = max(meta_y + 35, 390)
    bw = (CW - 24) // 3
    paper_count = data["paper_count"]
    stats = [
        (f"Top {rank} of {paper_count}", "Papers"),
        (str(paper.get("score", "?")), "Elo Score"),
        (f"{paper.get('win_rate', '?')}%", "Win Rate"),
    ]
    stats_svg = ""
    for i, (val, label) in enumerate(stats):
        bx = M + P + i * (bw + 12)
        stats_svg += f"""
        <rect x="{bx}" y="{sy}" width="{bw}" height="{stats_h}" rx="10" fill="white"/>
        <text x="{bx + bw // 2}" y="{sy + 35}" font-family="Liberation Sans" font-weight="bold" font-size="32" fill="{dark}" text-anchor="middle">{_esc(val)}</text>
        <text x="{bx + bw // 2}" y="{sy + 60}" font-family="Liberation Sans" font-size="17" fill="{muted}" text-anchor="middle">{_esc(label)}</text>
        """

    footer_y = sy + stats_h + 30  # tight below stats

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect width="{W}" height="{H}" fill="#f5f5f8"/>
  <rect x="{M-2}" y="{M-2}" width="{W-2*M+4}" height="{H-2*M+4}" rx="16" fill="{tier_hex}"/>
  <rect x="{M}" y="{M}" width="{W-2*M}" height="{H-2*M}" rx="14" fill="{tier_bg}"/>

  <text x="{M+P}" y="{hdr_y}" font-family="Liberation Sans" font-weight="bold" font-size="24" fill="{dark}">
    {_esc(data['archive_label'])}  \u00b7  {_esc(data['category_name'])} Preprints  \u00b7  arXiv
  </text>
  <text x="{W-M-P-235}" y="{hdr_y-2}" font-family="Liberation Sans" font-weight="bold" font-size="46" fill="{accent}">Ku</text>
  <text x="{W-M-P-170}" y="{hdr_y-2}" font-family="Liberation Sans" font-weight="bold" font-size="46" fill="{dark}">rate</text>
  <text x="{W-M-P-68}" y="{hdr_y-2}" font-family="Liberation Sans" font-size="46" fill="{accent}">.org</text>

  <line x1="{M+P}" y1="{hdr_y+12}" x2="{W-M-P}" y2="{hdr_y+12}" stroke="#d4d4dc" stroke-width="1"/>

  {medal_svg}

  <text x="{tx}" y="{tier_lbl_y}" font-family="Liberation Sans" font-weight="bold" font-size="20" fill="{tier_hex}">{tier_name.upper()}</text>
  {title_svg}
  <text x="{tx}" y="{auth_y}" font-family="Liberation Sans" font-size="23" fill="{muted}">{_esc(a_str[:70])}</text>
  <text x="{tx}" y="{meta_y}" font-family="Liberation Sans" font-size="19" fill="{muted}">{_esc(cats_str)}</text>

  <line x1="{M+P}" y1="{sy-10}" x2="{W-M-P}" y2="{sy-10}" stroke="#d4d4dc" stroke-width="1"/>

  {stats_svg}

  <text x="{M+P}" y="{footer_y}" font-family="Liberation Sans" font-size="22" fill="{muted}">
    Ranked by scientific impact (novelty, rigor, significance, clarity) via AI pairwise tournament
  </text>
</svg>"""

    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=W, output_height=H)



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
