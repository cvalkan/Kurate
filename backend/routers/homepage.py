"""Homepage stats endpoint — aggregates live metrics for the landing page."""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from core.config import db, logger, CATEGORIES

router = APIRouter(prefix="/api/homepage", tags=["homepage"])


@router.get("/stats")
async def homepage_stats():
    """Aggregate live metrics for the homepage."""
    try:
        # Get active categories from settings + CATEGORIES config
        settings = await db.settings.find_one({"key": "global"}, {"_id": 0}) or {}
        active_cat_ids = settings.get("active_categories", list(CATEGORIES.keys()))

        from core.arxiv_categories import ARXIV_TAXONOMY
        cats = []
        for cid in active_cat_ids:
            name = CATEGORIES.get(cid) or ARXIV_TAXONOMY.get(cid) or cid
            cats.append({"id": cid, "name": name})

        total_papers = await db.papers.estimated_document_count()
        total_matches = await db.matches.estimated_document_count()

        # Recent papers (last 7 days) — try both timestamp fields
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_papers = await db.papers.count_documents({"created_at": {"$gte": week_ago}})
        if recent_papers == 0:
            recent_papers = await db.papers.count_documents({"added_at": {"$gte": week_ago}})

        # Most active categories — handle both primary_category and categories[0]
        top_cats = []
        async for doc in db.papers.aggregate([
            {"$project": {"cat": {
                "$ifNull": ["$primary_category", {"$arrayElemAt": ["$categories", 0]}]
            }}},
            {"$match": {"cat": {"$ne": None}}},
            {"$group": {"_id": "$cat", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]):
            cat_name = CATEGORIES.get(doc["_id"]) or ARXIV_TAXONOMY.get(doc["_id"]) or doc["_id"]
            top_cats.append({"id": doc["_id"], "name": cat_name, "count": doc["count"]})

        # Latest timestamp — try both fields
        latest = await db.papers.find_one(
            {}, {"_id": 0, "created_at": 1, "added_at": 1}, sort=[("created_at", -1)]
        )
        latest_ts = None
        if latest:
            ts = latest.get("created_at") or latest.get("added_at")
            if ts:
                latest_ts = ts.isoformat() if isinstance(ts, datetime) else str(ts)

        # Top recent papers — handle both scoring fields
        top_papers = []
        async for doc in db.papers.aggregate([
            {"$addFields": {
                "_score": {"$ifNull": ["$ts_score", "$score"]},
                "_cat": {"$ifNull": ["$primary_category", {"$arrayElemAt": ["$categories", 0]}]},
            }},
            {"$match": {"_score": {"$ne": None}}},
            {"$sort": {"_score": -1}},
            {"$limit": 6},
            {"$project": {
                "_id": 0, "id": 1, "title": 1,
                "primary_category": "$_cat",
                "ts_score": "$_score",
                "published": 1,
                "authors": {"$slice": ["$authors", 2]},
            }},
        ]):
            top_papers.append(doc)

        return {
            "total_papers": total_papers,
            "total_categories": len(cats),
            "total_matches": total_matches,
            "recent_papers": recent_papers,
            "top_categories": top_cats,
            "latest_update": latest_ts,
            "categories": cats,
            "top_papers": top_papers,
            "ai_judges": 3,
        }
    except Exception as e:
        logger.error(f"Homepage stats error: {e}")
        return {
            "total_papers": 0, "total_categories": 0, "total_matches": 0,
            "recent_papers": 0, "top_categories": [], "latest_update": None,
            "categories": [], "top_papers": [], "ai_judges": 3,
        }
