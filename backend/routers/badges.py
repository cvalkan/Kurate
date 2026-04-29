"""Shareable badge generation for top-ranked papers."""

import io
import html as html_mod
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
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
    "cs.IT": "Information Theory", "quant-ph": "Quantum Physics",
    "astro-ph.CO": "Cosmology & Astrophysics", "cond-mat.mtrl-sci": "Materials Science",
    "cs.AI": "Artificial Intelligence", "cs.SI": "Social & Information Networks",
    "cs.FL": "Formal Languages", "q-fin.CP": "Quantitative Finance",
}

TIER_CONFIG = [
    {"rank": 1, "name": "Gold", "color": "#D4A017", "bg": "#FFF8E1"},
    {"rank": 2, "name": "Silver", "color": "#8A8A8A", "bg": "#F5F5F5"},
    {"rank": 3, "name": "Bronze", "color": "#CD7F32", "bg": "#FFF3E0"},
]

FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


# Minimum matches required for medal eligibility
MIN_MATCHES_FOR_MEDAL = 9


def _get_tier(rank: int) -> Optional[dict]:
    """Get badge tier for a given rank. Only top 3 get badges."""
    for t in TIER_CONFIG:
        if rank == t["rank"]:
            return t
    return None


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len - 1] + "\u2026" if len(text) > max_len else text


def _compute_archive_rank(leaderboard: list, paper_id: str) -> int:
    """Compute paper rank from archive leaderboard by sorting on ts_score.
    Every paper should have ts_score (computed from matches or default 1200)."""
    sorted_lb = sorted(
        leaderboard,
        key=lambda p: p.get("ts_score") or 1200,
        reverse=True,
    )
    return next((i + 1 for i, p in enumerate(sorted_lb) if p.get("id") == paper_id), 999)


async def _get_badge_data(category: str, year: int, paper_id: str, week: int = None, month: int = None) -> dict:
    """Fetch archive and extract badge data for a specific paper. Works for both weekly and monthly."""
    if week is not None:
        query = {"category": category, "year": year, "week": week, "period_type": "weekly"}
        fallback_label = f"Week {week}, {year}"
    elif month is not None:
        query = {"category": category, "year": year, "month": month, "period_type": "monthly"}
        fallback_label = f"Month {month}, {year}"
    else:
        raise HTTPException(400, "Must specify week or month")

    archive = await db.leaderboard_archives.find_one(query, {"_id": 0})
    if not archive:
        raise HTTPException(404, "Archive not found")

    lb = archive.get("leaderboard", [])
    paper = next((p for p in lb if p.get("id") == paper_id), None)
    if not paper:
        raise HTTPException(404, "Paper not found in this archive")

    # Compute rank by sorting the FULL archive leaderboard by ts_score (same as list view)
    rank = _compute_archive_rank(lb, paper_id)

    tier = _get_tier(rank)
    if not tier:
        raise HTTPException(404, "Paper is not in the top 3 for this period")

    if not paper.get("comparisons"):
        raise HTTPException(404, "Paper has no tournament matches yet — badge unavailable")

    categories = [category]
    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "categories": 1})
    if paper_doc and paper_doc.get("categories"):
        categories = paper_doc["categories"]

    slug = f"w{week}" if week is not None else f"m{month}"

    return {
        "paper": paper,
        "rank": rank,
        "tier": tier,
        "archive_label": archive.get("label", fallback_label),
        "category": category,
        "category_name": CATEGORIES.get(category, category),
        "paper_count": archive.get("paper_count", len(lb)),
        "categories": categories,
        "year": year,
        "week": week,
        "month": month,
        "slug": slug,
    }


def _badge_response(data: dict, paper_id: str) -> dict:
    """Build the standard badge API response from badge data."""
    p = data["paper"]
    return {
        "title": p.get("title"),
        "authors": p.get("authors", []),
        "rank": data["rank"],
        "score": p.get("ts_score", p.get("score")),
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
        "image_url": f"/api/badge/{data['category']}/{data['year']}/{data['slug']}/{paper_id}/image.png",
    }


@router.get("/{category}/{year}/w{week}/{paper_id}")
async def get_badge(category: str, year: int, week: int, paper_id: str):
    """Get badge data for a top-ranked paper in a weekly archive."""
    data = await _get_badge_data(category, year, paper_id, week=week)
    return _badge_response(data, paper_id)


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
    data = await _get_badge_data(category, year, paper_id, week=week)
    img_bytes = await _render_badge_png(data)
    _set_cached_image(store_key, img_bytes)
    # Also persist for future cold starts
    await store_image(store_key, img_bytes)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{category}/{year}/w{week}/{paper_id}/share", response_class=HTMLResponse)
async def get_badge_share_page(category: str, year: int, week: int, paper_id: str, request: Request):
    """Static HTML page with OG meta tags for social sharing. JS redirect for humans, crawlers see static tags."""
    from core.sharing import get_public_base_url, SHARE_HEADERS, is_bot
    data = await _get_badge_data(category, year, paper_id, week=week)
    base_url = get_public_base_url(request)
    html = _render_share_html(data, category, year, f"w{week}", paper_id, base_url, redirect=not is_bot(request))
    return HTMLResponse(content=html, headers=SHARE_HEADERS)


@router.get("/{category}/{year}/m{month}/{paper_id}/share", response_class=HTMLResponse)
async def get_monthly_badge_share_page(category: str, year: int, month: int, paper_id: str, request: Request):
    """Static HTML page with OG meta tags for monthly badge sharing."""
    from core.sharing import get_public_base_url, SHARE_HEADERS, is_bot
    data = await _get_badge_data(category, year, paper_id, month=month)
    base_url = get_public_base_url(request)
    html = _render_share_html(data, category, year, f"m{month}", paper_id, base_url, redirect=not is_bot(request))
    return HTMLResponse(content=html, headers=SHARE_HEADERS)


def _render_share_html(data: dict, category: str, year: int, slug: str, paper_id: str, base_url: str, redirect: bool = False) -> str:
    """Generate HTML page with OG/Twitter meta tags. Bots get pure static HTML; humans get JS redirect to leaderboard."""
    import html as html_mod
    p = data["paper"]
    tier = data["tier"]
    title = html_mod.escape(p.get("title", ""))
    authors = html_mod.escape(", ".join(p.get("authors", [])[:3]))
    if len(p.get("authors", [])) > 3:
        authors += f" +{len(p['authors']) - 3}"
    cat_name = html_mod.escape(data["category_name"])
    archive_label = html_mod.escape(data["archive_label"])
    rank = data["rank"]
    tier_name = tier["name"]

    image_url = f"{base_url}/api/badge/{category}/{year}/{slug}/{paper_id}/image.png"
    share_url = f"{base_url}/api/badge/{category}/{year}/{slug}/{paper_id}/share"
    leaderboard_url = f"{base_url}/leaderboard/{category}/{year}/{slug}"

    og_title = f"#{rank} {tier_name} in {cat_name} — {archive_label}"
    og_desc = f"{title} by {authors} | Ranked by scientific impact | Kurate.org"

    redirect_tag = f'\n<script>window.location.replace("{leaderboard_url}");</script>' if redirect else ""

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
<meta name="twitter:site" content="@KurateAI">{redirect_tag}
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
    """Render badge using the designer SVG templates, inject dynamic data, convert to PNG.
    Returns SVG string for async rendering via Playwright."""
    import os
    paper = data["paper"]
    tier = data["tier"]
    rank = data["rank"]
    tier_name = tier["name"] if tier else "Silver"
    is_medal = tier is not None

    # Load the correct SVG template (use silver as base for non-medal)
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

    archive_label = _esc(data.get("archive_label") or "")
    cat_name = _esc(data.get("category_name", ""))
    paper_count = data.get("paper_count", "?")
    score = paper.get("score", "?")
    win_rate = paper.get("win_rate", "?")

    # Replace placeholder text in the SVG
    # Header — for universal share pages (no archive), show just the category
    svg = svg.replace(">Week 11, 2026<", f">{archive_label}<" if archive_label else f"><")
    svg = svg.replace(">Robotics Preprints<", f">{cat_name} Preprints<")

    # Tier label + rank in medal circle
    # Each template has a hardcoded rank in the medal: Gold=#1, Silver=#2, Bronze=#3
    # Replace the TEMPLATE'S hardcoded rank with the actual rank
    template_rank_map = {"Gold": 1, "Silver": 2, "Bronze": 3}
    template_rank = template_rank_map.get(tier_name, 2)
    svg = svg.replace(f">#{template_rank}<", f">#{rank}<")

    tier_labels = {"Gold": "GOLD", "Silver": "SILVER", "Bronze": "BRONZE"}
    if is_medal:
        svg = svg.replace(f">{tier_labels.get(tier_name, 'SILVER')}<", f">{tier_name.upper()}<")
    else:
        # No medal — replace tier label with rank text
        for label in tier_labels.values():
            svg = svg.replace(f">{label}<", f">RANKED<")

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

    # Return the prepared SVG string (caller renders via Playwright)
    return svg


async def _render_badge_png(data: dict) -> bytes:
    """Render badge data to PNG using Playwright for pixel-perfect font rendering."""
    from services.svg_renderer import svg_to_png
    svg = _render_badge_image(data)
    return await svg_to_png(svg, output_width=2400, output_height=1260)

# Monthly badges
@router.get("/{category}/{year}/m{month}/{paper_id}")
async def get_monthly_badge(category: str, year: int, month: int, paper_id: str):
    """Get badge data for a top-ranked paper in a monthly archive."""
    data = await _get_badge_data(category, year, paper_id, month=month)
    return _badge_response(data, paper_id)

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


async def _find_paper_badge(paper_id: str) -> dict:
    """Find the paper's archive snapshot data.
    Priority: most recent top-3 appearance (the badge), then most recent appearance.
    Returns None only if the paper has never appeared in any archive."""
    from core.auth import get_settings
    settings = await get_settings()
    archive_config = settings.get("archive_frequency") or {}
    default_freq = archive_config.get("default", "weekly")

    archives = await db.leaderboard_archives.find(
        {"leaderboard.id": paper_id, "period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1,
         "label": 1, "paper_count": 1, "leaderboard": 1},
    ).sort([("year", -1), ("week", -1), ("month", -1)]).to_list(20)

    best_medal = None  # Top-3 appearance (the actual badge)
    latest_any = None  # Most recent appearance regardless of rank

    for a in archives:
        cat_freq = archive_config.get(a["category"], default_freq)
        if a.get("period_type") != cat_freq:
            continue
        lb = a.get("leaderboard", [])
        if not lb:
            continue
        p = next((entry for entry in lb if entry.get("id") == paper_id), None)
        if not p:
            continue
        archive_rank = _compute_archive_rank(lb, paper_id)
        # Medal requires minimum matches — prevents meaningless badges from 1-2 matches
        paper_comparisons = p.get("comparisons") or 0
        tier = _get_tier(archive_rank) if paper_comparisons >= MIN_MATCHES_FOR_MEDAL else None
        slug = f"w{a['week']}" if a.get("week") else f"m{a['month']}"
        entry = {
            "tier": tier,
            "rank": archive_rank,
            "archive_label": a.get("label"),
            "paper_count": a.get("paper_count", len(lb)),
            "category": a["category"],
            "slug": slug,
            "year": a.get("year"),
            "badge_url": f"/badge/{a['category']}/{a['year']}/{slug}/{paper_id}",
            "leaderboard_url": f"/leaderboard/{a['category']}/{a['year']}/{slug}",
            "score": p.get("ts_score", p.get("score")),
            "win_rate": p.get("win_rate"),
            "comparisons": p.get("comparisons"),
        }
        if tier and not best_medal:
            best_medal = entry
        if not latest_any:
            latest_any = entry
        if best_medal:
            break  # Found a medal — no need to search further

    return best_medal or latest_any


@router.get("/paper/{paper_id}/share")
async def get_paper_share_data(paper_id: str):
    """Get shareable badge data for ANY paper — includes best archive badge info if available."""
    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "categories": 1, "ai_rating": 1, "arxiv_id": 1})
    if not paper_doc:
        raise HTTPException(404, "Paper not found")

    primary_cat = paper_doc.get("categories", [None])[0]
    ranking = await db.rankings.find_one(
        {"paper_id": paper_id},
        {"_id": 0, "rank_ts": 1, "rank": 1, "ts_score": 1, "score": 1, "win_rate": 1, "comparisons": 1, "category": 1},
    )

    # Use TS rank (TrueSkill) — the canonical ranking metric
    rank = ranking.get("rank_ts", ranking.get("rank")) if ranking else None
    total = await db.rankings.count_documents({"category": primary_cat}) if primary_cat else 0

    ai_rating = paper_doc.get("ai_rating")
    rating_score = ai_rating.get("score") if isinstance(ai_rating, dict) else ai_rating if isinstance(ai_rating, (int, float)) else None

    # Look up the paper's archive badge (each paper has at most one)
    badge_data = await _find_paper_badge(paper_id)

    # When archive data exists, image uses snapshot, footer shows live rank
    if badge_data:
        has_medal = badge_data["tier"] is not None
        tier_name = badge_data["tier"]["name"] if has_medal else None
        tier_color = badge_data["tier"]["color"] if has_medal else None
        badge = {
            "tier": tier_name,
            "tier_color": tier_color,
            "rank": badge_data["rank"],
            "paper_count": badge_data["paper_count"],
            "score": badge_data["score"],
            "win_rate": round(badge_data["win_rate"]) if badge_data["win_rate"] else None,
            "archive_label": badge_data["archive_label"],
            "category": badge_data["category"],
            "slug": badge_data["slug"],
            "year": badge_data["year"],
            "badge_url": badge_data["badge_url"],
            "leaderboard_url": badge_data["leaderboard_url"],
        }
        return {
            "title": paper_doc.get("title"),
            "authors": paper_doc.get("authors", []),
            "rank": rank,
            "total_in_category": total,
            "score": ranking.get("ts_score") if ranking else None,
            "win_rate": round(ranking.get("win_rate", 0)) if ranking else None,
            "comparisons": ranking.get("comparisons") if ranking else None,
            "rating": rating_score,
            "category": primary_cat,
            "category_name": CATEGORIES.get(primary_cat, primary_cat) if primary_cat else None,
            "arxiv_id": paper_doc.get("arxiv_id"),
            "paper_id": paper_id,
            "has_medal": has_medal,
            "tier": tier_name,
            "display_rank": badge_data["rank"],
            "badge": badge,
            "image_url": f"/api/badge/paper/{paper_id}/share/image.png",
        }

    # No archive data at all — use live data
    return {
        "title": paper_doc.get("title"),
        "authors": paper_doc.get("authors", []),
        "rank": rank,
        "total_in_category": total,
        "score": ranking.get("ts_score") if ranking else None,
        "win_rate": round(ranking.get("win_rate", 0)) if ranking else None,
        "comparisons": ranking.get("comparisons") if ranking else None,
        "rating": rating_score,
        "category": primary_cat,
        "category_name": CATEGORIES.get(primary_cat, primary_cat) if primary_cat else None,
        "arxiv_id": paper_doc.get("arxiv_id"),
        "paper_id": paper_id,
        "has_medal": rank is not None and rank <= 3,
        "tier": _get_tier(rank)["name"] if rank and _get_tier(rank) else None,
        "display_rank": rank,
        "badge": None,
        "image_url": f"/api/badge/paper/{paper_id}/share/image.png",
    }


@router.get("/paper/{paper_id}/share/page", response_class=HTMLResponse)
async def get_paper_share_page(paper_id: str, request: Request):
    """Static HTML page with OG/Twitter meta tags for social media sharing.
    Works for ALL papers — uses archive snapshot data when available, live data otherwise."""
    import html as html_mod
    from core.sharing import get_public_base_url, SHARE_HEADERS, is_bot
    bot = is_bot(request)

    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "categories": 1, "arxiv_id": 1})
    if not paper_doc:
        raise HTTPException(404, "Paper not found")

    primary_cat = paper_doc.get("categories", [None])[0]
    ranking = await db.rankings.find_one(
        {"paper_id": paper_id},
        {"_id": 0, "rank_ts": 1, "rank": 1, "ts_score": 1, "score": 1, "win_rate": 1, "comparisons": 1},
    )
    rank = ranking.get("rank_ts", ranking.get("rank")) if ranking else None
    total = await db.rankings.count_documents({"category": primary_cat}) if primary_cat else 0

    badge_data = await _find_paper_badge(paper_id)
    base_url = get_public_base_url(request)

    # Best available data: archive snapshot if exists, live data otherwise
    display_rank = badge_data["rank"] if badge_data else rank
    display_total = badge_data["paper_count"] if badge_data else total
    tier = badge_data.get("tier") if badge_data else _get_tier(rank) if rank else None
    tier_label = f"{tier['name']} " if tier else ""
    period_label = badge_data["archive_label"] if badge_data else "All Time"

    title = html_mod.escape(paper_doc.get("title", ""))
    authors_list = paper_doc.get("authors", [])
    authors = html_mod.escape(", ".join(authors_list[:3]))
    if len(authors_list) > 3:
        authors += f" +{len(authors_list) - 3}"
    cat_name = html_mod.escape(CATEGORIES.get(primary_cat, primary_cat) if primary_cat else "")

    image_url = f"{base_url}/api/badge/paper/{paper_id}/share/image.png"
    share_url = f"{base_url}/api/badge/paper/{paper_id}/share/page"
    paper_url = f"{base_url}/paper/{paper_id}"

    # Redirect destination: archive leaderboard if exists, else live category leaderboard
    if badge_data and badge_data.get("leaderboard_url"):
        redirect_url = f"{base_url}{badge_data['leaderboard_url']}"
    else:
        redirect_url = f"{base_url}/?cat={primary_cat}&period=all" if primary_cat else base_url

    og_title = f"#{display_rank} {tier_label}in {cat_name} ({period_label})" if display_rank else f"Paper in {cat_name}"
    og_desc = f"{title} by {authors} | Ranked by scientific impact | Kurate.org"

    redirect_tag = f'\n<script>window.location.replace("{redirect_url}");</script>' if not bot else ""

    html_content = f"""<!DOCTYPE html>
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
<meta name="twitter:site" content="@KurateAI">{redirect_tag}
</head>
<body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; color: #333;">
<h1 style="font-size: 20px;">{og_title}</h1>
<p style="color: #666;">{title}</p>
<p style="color: #999; font-size: 14px;">by {authors}</p>
<p style="margin-top: 24px;"><a href="{redirect_url}" style="display: inline-block; padding: 10px 20px; background: #4285F4; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px;">View on Kurate.org</a></p>
</body>
</html>"""
    return HTMLResponse(content=html_content, headers=SHARE_HEADERS)


@router.get("/paper/{paper_id}/share/image.png")
async def get_paper_share_image(paper_id: str):
    """Render a shareable badge image for any paper. Uses the paper's archive badge if it exists."""
    await _install_fonts_if_needed()

    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "categories": 1})
    if not paper_doc:
        raise HTTPException(404, "Paper not found")

    primary_cat = paper_doc.get("categories", [None])[0]
    ranking = await db.rankings.find_one(
        {"paper_id": paper_id},
        {"_id": 0, "rank_ts": 1, "rank": 1, "ts_score": 1, "score": 1, "win_rate": 1, "comparisons": 1},
    )
    if not ranking:
        raise HTTPException(404, "Paper has no ranking")

    live_rank = ranking.get("rank_ts", ranking.get("rank", 999))
    live_total = await db.rankings.count_documents({"category": primary_cat}) if primary_cat else 0

    # Use archive badge data if it exists — ALL numbers from the snapshot
    badge_data = await _find_paper_badge(paper_id)
    if badge_data:
        rank = badge_data["rank"]
        tier = badge_data["tier"]
        archive_label = badge_data["archive_label"]
        paper_count = badge_data["paper_count"]
        score = badge_data["score"]
        win_rate = badge_data["win_rate"]
    else:
        rank = live_rank
        tier = _get_tier(rank)
        archive_label = None
        paper_count = live_total
        score = ranking.get("ts_score", ranking.get("score"))
        win_rate = ranking.get("win_rate")

    data = {
        "paper": {
            "title": paper_doc.get("title"),
            "authors": paper_doc.get("authors", []),
            "rank": rank,
            "score": score,
            "win_rate": win_rate,
            "comparisons": ranking.get("comparisons"),
        },
        "rank": rank,
        "tier": tier,
        "category": primary_cat,
        "category_name": CATEGORIES.get(primary_cat, primary_cat) if primary_cat else "",
        "paper_count": paper_count,
        "archive_label": archive_label,
    }

    img_bytes = await _render_badge_png(data)
    return Response(content=img_bytes, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})



@router.get("/paper/{paper_id}/badges")
async def get_paper_badges(paper_id: str):
    """Get all badges (top 3 appearances) for a specific paper across all archives.
    Only returns badges matching the category's configured archive frequency (weekly or monthly)."""
    from core.auth import get_settings
    settings = await get_settings()
    archive_config = settings.get("archive_frequency") or {}
    default_freq = archive_config.get("default", "weekly")

    archives = await db.leaderboard_archives.find(
        {"leaderboard.id": paper_id,
         "period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1, "period_type": 1, "label": 1,
         "paper_count": 1, "leaderboard": 1},
    ).sort([("year", -1), ("week", -1), ("month", -1)]).to_list(50)

    badges = []
    for a in archives:
        cat_freq = archive_config.get(a["category"], default_freq)
        if a.get("period_type") != cat_freq:
            continue
        lb = a.get("leaderboard", [])
        if not lb:
            continue
        p = next((entry for entry in lb if entry.get("id") == paper_id), None)
        if not p:
            continue

        # Compute rank by sorting full leaderboard by ts_score (consistent with list view)
        rank = _compute_archive_rank(lb, paper_id)

        paper_comparisons = p.get("comparisons") or 0
        tier = _get_tier(rank) if paper_comparisons >= MIN_MATCHES_FOR_MEDAL else None
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
    rank = paper.get("rank", 999)
    tier = _get_tier(rank)
    if not tier:
        raise HTTPException(404, "Not in top 3")
    data = {"paper": paper, "rank": rank, "tier": tier, "archive_label": archive.get("label"),
            "category": category, "category_name": CATEGORIES.get(category, category),
            "paper_count": archive.get("paper_count", len(lb))}
    paper_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "categories": 1})
    data["categories"] = paper_doc["categories"] if paper_doc and paper_doc.get("categories") else [category]
    img_bytes = await _render_badge_png(data)
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
