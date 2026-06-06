from fastapi import FastAPI, APIRouter, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Any

from seed import build_papers, CATEGORIES, latest_update_string


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Kurate API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# In-memory store keeps responses snappy; Mongo persists a snapshot.
PAPERS: list[dict[str, Any]] = []


def _category_field(code: str) -> str:
    for c in CATEGORIES:
        if c["code"] == code:
            return c["field"]
    return "cs"


def _filter_papers(
    papers: list[dict[str, Any]],
    *,
    category: Optional[str] = None,
    year: Optional[str] = None,
    period: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict[str, Any]]:
    out = papers
    if category and category != "all":
        out = [p for p in out if p["category_code"] == category]
    if year and year != "all":
        out = [p for p in out if str(p["year"]) == str(year)]
    if period and period != "all":
        now = datetime.now(timezone.utc)
        if period == "7d":
            cutoff = now.timestamp() - 7 * 86400
        elif period == "30d":
            cutoff = now.timestamp() - 30 * 86400
        elif period == "new":
            cutoff = now.timestamp() - 3 * 86400
        else:
            cutoff = 0
        out = [p for p in out if datetime.fromisoformat(p["added_at"]).timestamp() >= cutoff]
    if q:
        ql = q.lower().strip()
        if ql:
            out = [
                p for p in out
                if ql in p["title"].lower()
                or ql in p["category_code"].lower()
                or ql in p["category_name"].lower()
                or any(ql in a.lower() for a in p["authors"])
            ]
    return out


def _sort_papers(papers: list[dict[str, Any]], rank_type: str) -> list[dict[str, Any]]:
    if rank_type == "recent":
        return sorted(papers, key=lambda p: p["added_at"], reverse=True)
    if rank_type == "rating":
        return sorted(papers, key=lambda p: p["rating"], reverse=True)
    if rank_type == "gap":
        return sorted(papers, key=lambda p: p["gap"], reverse=True)
    if rank_type == "newly_ranked":
        return sorted(papers, key=lambda p: (p["added_at"], p["score"]), reverse=True)
    # default: score
    return sorted(papers, key=lambda p: p["score"], reverse=True)


@api_router.get("/")
async def root():
    return {"service": "kurate", "status": "ok"}


@api_router.get("/categories")
async def get_categories():
    counts: dict[str, int] = {}
    for p in PAPERS:
        counts[p["category_code"]] = counts.get(p["category_code"], 0) + 1
    result = []
    for c in CATEGORIES:
        result.append({
            **c,
            "paper_count": counts.get(c["code"], 0),
            "latest_update": latest_update_string(
                [p for p in PAPERS if p["category_code"] == c["code"]] or PAPERS
            ),
        })
    return result


@api_router.get("/years")
async def get_years():
    years = sorted({p["year"] for p in PAPERS}, reverse=True)
    return [{"value": str(y), "label": str(y)} for y in years]


@api_router.get("/papers")
async def get_papers(
    category: Optional[str] = "all",
    year: Optional[str] = "all",
    period: Optional[str] = "all",
    rank_type: Optional[str] = "top",
    q: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=100),
):
    filtered = _filter_papers(PAPERS, category=category, year=year, period=period, q=q)
    ranked = _sort_papers(filtered, rank_type or "top")
    return {
        "total": len(ranked),
        "results": [
            {**p, "rank": i + 1}
            for i, p in enumerate(ranked[:limit])
        ],
    }


@api_router.get("/metrics")
async def get_metrics():
    if not PAPERS:
        return {}
    counts: dict[str, int] = {}
    for p in PAPERS:
        counts[p["category_code"]] = counts.get(p["category_code"], 0) + 1
    most_active = max(counts.items(), key=lambda kv: kv[1])
    total_comparisons = sum(int(p["score"] * 25) + p["rating"] for p in PAPERS)
    return {
        "papers_ranked": len(PAPERS),
        "active_categories": len(CATEGORIES),
        "total_comparisons": total_comparisons,
        "ai_judges": 3,
        "most_active_category": most_active[0],
        "latest_update": latest_update_string(PAPERS),
    }


@api_router.get("/recent")
async def get_recent():
    """Recent Rankings panel cards — one card per category plus 'Newly Ranked'."""
    recent_papers = sorted(PAPERS, key=lambda p: p["added_at"], reverse=True)[:8]
    cards: list[dict[str, Any]] = [{
        "key": "newly_ranked",
        "kind": "feed",
        "title": "Newly Ranked Papers",
        "category_code": None,
        "field": "cs",
        "description": "Latest papers added to the live Kurate ranking pipeline.",
        "count": len(PAPERS),
        "latest_update": latest_update_string(PAPERS),
    }]
    # Top 7 categories by paper count
    cat_counts = sorted(
        ({**c, "count": sum(1 for p in PAPERS if p["category_code"] == c["code"])} for c in CATEGORIES),
        key=lambda c: c["count"], reverse=True,
    )[:7]
    for c in cat_counts:
        cards.append({
            "key": c["code"],
            "kind": "category",
            "title": f"{c['name']} Papers",
            "category_code": c["code"],
            "field": c["field"],
            "description": c["description"],
            "count": c["count"],
            "latest_update": latest_update_string(
                [p for p in PAPERS if p["category_code"] == c["code"]] or PAPERS
            ),
        })
    return {"cards": cards, "recent_papers": recent_papers}


@api_router.get("/activity")
async def get_activity():
    """Latest Platform Activity items."""
    items = []
    recent = sorted(PAPERS, key=lambda p: p["added_at"], reverse=True)[:6]
    for p in recent:
        items.append({
            "id": p["id"],
            "kind": "paper_ranked",
            "title": p["title"],
            "category_code": p["category_code"],
            "field": p["field"],
            "timestamp": p["added_at"],
            "status": f"Ranked at score {p['score']}",
        })
    # Field-level activity
    cat_counts = sorted(
        ({**c, "count": sum(1 for p in PAPERS if p["category_code"] == c["code"])} for c in CATEGORIES),
        key=lambda c: c["count"], reverse=True,
    )[:2]
    for c in cat_counts:
        items.append({
            "id": c["code"],
            "kind": "category_update",
            "title": f"{c['name']} leaderboard refreshed",
            "category_code": c["code"],
            "field": c["field"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": f"{c['count']} papers ranked",
        })
    return items


app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def seed_on_startup():
    global PAPERS
    PAPERS = build_papers()
    try:
        await db.papers.delete_many({})
        if PAPERS:
            await db.papers.insert_many([{**p} for p in PAPERS])
        logger.info("Seeded %d papers into MongoDB.", len(PAPERS))
    except Exception as e:
        logger.warning("Mongo seed failed (continuing with in-memory data): %s", e)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
