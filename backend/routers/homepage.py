"""Homepage API endpoints.

Serves pre-shaped data for the new homepage components (HeroPanel, RecentRankings, etc.).
Reads from the live MongoDB collections — no upstream proxy.
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
from core.config import db, logger, CATEGORIES

router = APIRouter(prefix="/api/homepage")


def _field_for(code: str, group: str) -> str:
    """Map a category code to a broad field key used for accent colours."""
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
    """Convert an ISO timestamp to a human-friendly relative string."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return "—"
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


async def _active_categories() -> list[dict]:
    """Return active categories with metadata from settings."""
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
    """Categories shaped for the homepage chip bar and filter dropdowns."""
    from core.auth import get_settings
    settings = await get_settings()
    featured = settings.get("featured_categories", [])
    cats = await _active_categories()

    # Aggregate paper counts and latest update per category from rankings
    counts = {}
    latest_by_cat = {}
    pipeline = [
        {"$group": {
            "_id": "$category",
            "count": {"$sum": 1},
            "latest": {"$max": "$published"},
        }},
    ]
    async for doc in db.rankings.aggregate(pipeline):
        cat = doc["_id"]
        counts[cat] = doc["count"]
        latest_by_cat[cat] = doc.get("latest") or ""

    for c in cats:
        code = c["code"]
        c["paper_count"] = counts.get(code, 0)
        c["latest_update"] = _humanise(latest_by_cat.get(code, ""))
        c["featured"] = code in featured

    return cats


@router.get("/metrics")
async def homepage_metrics():
    """Aggregate metrics for the homepage stats strip."""
    import asyncio

    async def _paper_count():
        return await db.rankings.count_documents({})

    async def _match_count():
        return await db.matches.count_documents({
            "completed": True, "failed": {"$ne": True},
            "revision_superseded": {"$ne": True},
        })

    async def _cat_count():
        cats = await _active_categories()
        return len(cats)

    async def _latest_update():
        doc = await db.rankings.find_one(
            {}, {"_id": 0, "published": 1},
            sort=[("published", -1)],
        )
        return _humanise(doc.get("published", "")) if doc else "—"

    papers, matches, cat_count, latest = await asyncio.gather(
        _paper_count(), _match_count(), _cat_count(), _latest_update(),
    )

    return {
        "papers_ranked": papers,
        "active_categories": cat_count,
        "total_comparisons": matches,
        "ai_judges": 3,
        "latest_update": latest,
    }


@router.get("/papers")
async def homepage_papers(
    category: Optional[str] = "all",
    period: Optional[str] = "all",
    rank_type: Optional[str] = "score",
    q: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=200),
):
    """Filtered, sorted papers for the homepage HeroPanel table."""
    from core.arxiv_categories import get_group
    import re as _re

    query = {"is_latest_version": {"$ne": False}}
    if category and category != "all":
        query["category"] = category

    # Time-period filter
    if period and period != "all":
        days_map = {"new": 3, "7d": 7, "30d": 30}
        days = days_map.get(period, 0)
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query["published"] = {"$gte": cutoff.isoformat()}

    # Search filter
    if q and q.strip():
        escaped = _re.escape(q.strip())
        query["$or"] = [
            {"title": {"$regex": escaped, "$options": "i"}},
            {"authors": {"$regex": escaped, "$options": "i"}},
            {"arxiv_id": {"$regex": escaped, "$options": "i"}},
            {"category": {"$regex": escaped, "$options": "i"}},
        ]

    # Sort
    sort_field = "ts_score"
    if rank_type == "rating":
        sort_field = "ai_rating"
    elif rank_type == "gap":
        sort_field = "gap_score"
    sort_order = [("$natural" if sort_field == "ts_score" else sort_field, -1)]
    if sort_field == "ts_score":
        sort_order = [("ts_score", -1)]

    total = await db.rankings.count_documents(query)
    cursor = db.rankings.find(query, {"_id": 0}).sort(sort_order).limit(limit)

    results = []
    rank = 1
    async for doc in cursor:
        cat = doc.get("category", "")
        group = get_group(cat)
        field = _field_for(cat, group)
        score_val = doc.get("ts_score", 0)
        rating_val = doc.get("ai_rating", 0)
        gap_val = doc.get("gap_score", 0)

        results.append({
            "id": doc.get("paper_id"),
            "rank": rank,
            "title": (doc.get("title") or "").strip(),
            "authors": doc.get("authors", []),
            "arxiv_id": doc.get("arxiv_id", ""),
            "link": doc.get("link", ""),
            "category_code": cat or "—",
            "categories": doc.get("categories", [cat] if cat else []),
            "field": field,
            "score": score_val,
            "rating": rating_val or 0,
            "gap": gap_val or 0,
            "wins": doc.get("wins", 0),
            "losses": doc.get("losses", 0),
            "comparisons": doc.get("comparisons", 0),
            "published_at": doc.get("published"),
            "year": str(doc.get("published", ""))[:4] if doc.get("published") else "",
            "signal_badge": f"{int(doc.get('win_rate', 0))}% win rate",
        })
        rank += 1

    return {"total": total, "results": results}


@router.get("/recent")
async def homepage_recent():
    """Recent rankings: category cards + latest papers for the RecentRankings section."""
    cats = await _active_categories()
    cat_lookup = {c["code"]: c for c in cats}

    # Aggregate counts and latest update per category
    counts = {}
    latest_by_cat = {}
    pipeline = [
        {"$group": {
            "_id": "$category",
            "count": {"$sum": 1},
            "latest": {"$max": "$published"},
        }},
    ]
    async for doc in db.rankings.aggregate(pipeline):
        cat = doc["_id"]
        counts[cat] = doc["count"]
        latest_by_cat[cat] = doc.get("latest") or ""

    # Build cards: "Newly Ranked" card first, then top categories by count
    total_papers = sum(counts.values())
    latest_overall = max(latest_by_cat.values(), default="") if latest_by_cat else ""

    cards = [{
        "key": "newly_ranked",
        "kind": "feed",
        "title": "Newly Ranked Papers",
        "category_code": None,
        "field": "cs",
        "description": "Latest papers added to the live Kurate ranking pipeline.",
        "count": total_papers,
        "latest_update": _humanise(latest_overall),
    }]

    # Sort categories by paper count, take top 7
    sorted_cats = sorted(cats, key=lambda c: counts.get(c["code"], 0), reverse=True)[:7]
    for c in sorted_cats:
        code = c["code"]
        if counts.get(code, 0) == 0:
            continue
        cards.append({
            "key": code,
            "kind": "category",
            "title": f"{c['name']} Papers",
            "category_code": code,
            "field": c["field"],
            "description": c["broad"],
            "count": counts.get(code, 0),
            "latest_update": _humanise(latest_by_cat.get(code, "")),
        })

    return {"cards": cards}
