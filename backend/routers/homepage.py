"""Homepage API endpoints.

Serves pre-shaped data for the new homepage components (HeroPanel, RecentRankings, etc.).
Reads from the live MongoDB collections — no upstream proxy.

Performance optimizations (targeting 30k+ papers on Atlas):
- 60s TTL in-memory cache for /categories, /metrics, /recent
- Match count from leaderboard's O(1) incremental counters
- /papers skips total count (homepage only shows top 10)
- Explicit projection reduces network transfer
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
import time as _time
from core.config import db, logger, CATEGORIES

router = APIRouter(prefix="/api/homepage")

# ── In-memory cache (60s TTL) ──
_cache = {}  # key -> {"ts": float, "data": any}
_CACHE_TTL = 60


def _cached(key: str):
    entry = _cache.get(key)
    if entry and (_time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cache(key: str, data):
    _cache[key] = {"ts": _time.time(), "data": data}


def _field_for(code: str, group: str) -> str:
    c = code.lower()
    g = (group or "").lower()
    if c.startswith("cs.ai") or c.startswith("cs.lg") or c.startswith("cs.cl"):
        return "ai"
    if c.startswith("cs.ro"):
        return "robotics"
    if c.startswith("cs.cr"):
        return "security"
    if c.startswith("cs."):
        return "cs"
    if c.startswith("quant-ph") or "physics" in g or c.startswith("astro") or c.startswith("cond-mat"):
        return "quantum"
    if c.startswith("math.") or "mathematics" in g or c.startswith("stat"):
        return "math"
    if c.startswith("q-bio") or "biology" in g or "life" in g:
        return "biology"
    if c.startswith("econ") or "economic" in g:
        return "econ"
    return "cs"


def _humanise(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return ""
    delta = datetime.now(timezone.utc) - dt
    h = int(delta.total_seconds() // 3600)
    if h < 1:
        return "just now"
    if h < 24:
        return f"{h}h ago"
    d = h // 24
    if d < 30:
        return f"{d}d ago"
    return f"{d // 30}mo ago"


def _format_month(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%b %Y")
    except Exception:
        return ""


async def _active_categories() -> list[dict]:
    from core.auth import get_settings
    from core.arxiv_categories import ARXIV_TAXONOMY, get_group
    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))
    cats = []
    for cat_id in active:
        name = CATEGORIES.get(cat_id) or ARXIV_TAXONOMY.get(cat_id) or cat_id
        group = get_group(cat_id)
        cats.append({
            "code": cat_id,
            "name": name,
            "field": _field_for(cat_id, group),
            "broad": group,
        })
    return cats


@router.get("/categories")
async def homepage_categories():
    """Categories for chips + dropdown. Cached 60s."""
    cached = _cached("categories")
    if cached is not None:
        return cached

    from core.auth import get_settings
    settings = await get_settings()
    featured = settings.get("featured_categories", [])
    cats = await _active_categories()

    counts = {}
    latest_by_cat = {}
    async for doc in db.rankings.aggregate([
        {"$group": {"_id": "$category", "count": {"$sum": 1}, "latest": {"$max": "$published"}}},
    ]):
        counts[doc["_id"]] = doc["count"]
        latest_by_cat[doc["_id"]] = doc.get("latest") or ""

    for c in cats:
        code = c["code"]
        c["paper_count"] = counts.get(code, 0)
        c["latest_update"] = _humanise(latest_by_cat.get(code, ""))
        c["featured"] = code in featured

    _set_cache("categories", cats)
    return cats


@router.get("/metrics")
async def homepage_metrics():
    """Stats strip. Cached 60s. Match count from O(1) in-memory counters."""
    cached = _cached("metrics")
    if cached is not None:
        return cached

    import asyncio

    async def _paper_count():
        return await db.rankings.estimated_document_count()

    async def _latest_update():
        doc = await db.rankings.find_one(
            {"added_at": {"$nin": ["", None]}},
            {"_id": 0, "added_at": 1},
            sort=[("added_at", -1)],
        )
        return _humanise(doc.get("added_at", "")) if doc else ""

    async def _cat_count():
        cats = await _active_categories()
        return len(cats)

    papers, cat_count, latest = await asyncio.gather(
        _paper_count(), _cat_count(), _latest_update(),
    )

    # estimated_document_count is O(1) — reads collection metadata
    total_matches = await db.matches.estimated_document_count()

    result = {
        "papers_ranked": papers,
        "active_categories": cat_count,
        "total_comparisons": total_matches,
        "ai_judges": 3,
        "latest_update": latest,
    }
    _set_cache("metrics", result)
    return result


# Projection — only fields the frontend needs (reduces Atlas → app network transfer)
_PAPER_PROJ = {
    "_id": 0, "paper_id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
    "link": 1, "category": 1, "categories": 1, "ts_score": 1,
    "ai_rating": 1, "gap_score": 1, "wins": 1, "losses": 1,
    "comparisons": 1, "published": 1, "win_rate": 1,
}


@router.get("/papers")
async def homepage_papers(
    category: Optional[str] = "all",
    period: Optional[str] = "all",
    rank_type: Optional[str] = "score",
    q: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=200),
):
    """Filtered, sorted papers. No count_documents — homepage only shows top N."""
    from core.arxiv_categories import get_group

    query = {"is_latest_version": {"$ne": False}}
    if category and category != "all":
        query["category"] = category

    if period and period != "all":
        if period == "recent":
            # Match the leaderboard: rolling 48h window from latest added_at within scope
            anchor_query = {"added_at": {"$nin": ["", None]}}
            if category and category != "all":
                anchor_query["category"] = category
            latest = await db.rankings.find_one(
                anchor_query,
                {"_id": 0, "added_at": 1},
                sort=[("added_at", -1)],
            )
            if latest and latest.get("added_at"):
                try:
                    anchor = datetime.fromisoformat(str(latest["added_at"]).replace("Z", "+00:00"))
                    cutoff = (anchor - timedelta(hours=48)).isoformat()
                except (ValueError, TypeError):
                    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            else:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            query["added_at"] = {"$gte": cutoff}
        else:
            days_map = {"week": 7, "month": 30}
            days = days_map.get(period, 0)
            if days > 0:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                query["published"] = {"$gte": cutoff.isoformat()}

    if q and q.strip():
        import re as _re
        escaped = _re.escape(q.strip())
        query["$or"] = [
            {"title": {"$regex": escaped, "$options": "i"}},
            {"authors": {"$regex": escaped, "$options": "i"}},
            {"arxiv_id": {"$regex": escaped, "$options": "i"}},
            {"category": {"$regex": escaped, "$options": "i"}},
        ]

    sort_field = "ts_score"
    if rank_type == "ai_rating":
        sort_field = "ai_rating"
    elif rank_type == "gap_score":
        sort_field = "gap_score"

    # Secondary sort by ts_score to break ties (e.g., when all gap_scores are 0)
    sort_order = [(sort_field, -1)]
    if sort_field != "ts_score":
        sort_order.append(("ts_score", -1))

    cursor = db.rankings.find(query, _PAPER_PROJ).sort(sort_order).limit(limit)

    results = []
    rank = 1
    async for doc in cursor:
        cat = doc.get("category", "")
        group = get_group(cat)
        field = _field_for(cat, group)

        results.append({
            "id": doc.get("paper_id"),
            "rank": rank,
            "title": (doc.get("title") or "").strip(),
            "authors": doc.get("authors", []),
            "arxiv_id": doc.get("arxiv_id", ""),
            "link": doc.get("link", ""),
            "category_code": cat or "",
            "categories": doc.get("categories", [cat] if cat else []),
            "field": field,
            "score": doc.get("ts_score", 0),
            "ai_rating": doc.get("ai_rating") or 0,
            "gap_score": doc.get("gap_score") or 0,
            "wins": doc.get("wins", 0),
            "losses": doc.get("losses", 0),
            "comparisons": doc.get("comparisons", 0),
            "published_at": doc.get("published"),
            "year": str(doc.get("published", ""))[:4] if doc.get("published") else "",
            "signal_badge": f"{int(doc.get('win_rate', 0))}% win rate",
        })
        rank += 1

    return {"total": len(results), "results": results}


@router.get("/recent")
async def homepage_recent():
    """Recent rankings cards. Cached 60s."""
    cached = _cached("recent")
    if cached is not None:
        return cached

    cats = await _active_categories()

    counts = {}
    oldest_by_cat = {}
    async for doc in db.rankings.aggregate([
        {"$group": {"_id": "$category", "count": {"$sum": 1}, "oldest": {"$min": "$published"}}},
    ]):
        counts[doc["_id"]] = doc["count"]
        oldest_by_cat[doc["_id"]] = doc.get("oldest") or ""

    latest_added = await db.rankings.find_one(
        {"added_at": {"$nin": ["", None]}},
        {"_id": 0, "added_at": 1},
        sort=[("added_at", -1)],
    )
    if latest_added and latest_added.get("added_at"):
        try:
            anchor_dt = datetime.fromisoformat(str(latest_added["added_at"]).replace("Z", "+00:00"))
            recent_cutoff = (anchor_dt - timedelta(hours=48)).isoformat()
        except (ValueError, TypeError):
            recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    else:
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    newly_ranked_count = await db.rankings.count_documents({"added_at": {"$gte": recent_cutoff}})

    latest_added_str = latest_added.get("added_at", "") if latest_added else ""

    cards = [{
        "key": "newly_ranked",
        "kind": "feed",
        "title": "Newly Ranked Papers",
        "category_code": None,
        "field": "cs",
        "description": "Latest papers added to the live Kurate ranking pipeline.",
        "count": newly_ranked_count,
        "time_label": f"Last updated {_humanise(latest_added_str)}",
    }]

    sorted_cats = sorted(cats, key=lambda c: counts.get(c["code"], 0), reverse=True)[:7]
    for c in sorted_cats:
        code = c["code"]
        if counts.get(code, 0) == 0:
            continue
        oldest_str = _format_month(oldest_by_cat.get(code, ""))
        cards.append({
            "key": code,
            "kind": "category",
            "title": f"{c['name']} Papers",
            "category_code": code,
            "field": c["field"],
            "description": c["broad"],
            "count": counts.get(code, 0),
            "time_label": f"Since {oldest_str}" if oldest_str else "",
        })

    result = {"cards": cards}
    _set_cache("recent", result)
    return result
