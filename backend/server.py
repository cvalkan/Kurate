from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
import os
from core.config import db, logger
from routers.leaderboard import router as leaderboard_router
from routers.admin import router as admin_router
from services.scheduler import start_scheduler

app = FastAPI(title="PaperSumo - Robotics Paper Leaderboard")

app.include_router(leaderboard_router)
app.include_router(admin_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "papersumo-leaderboard"}


@app.on_event("startup")
async def startup():
    try:
        await db.papers.create_index("id", unique=True)
        await db.papers.create_index("arxiv_id", unique=True)
        await db.papers.create_index("published")
        await db.matches.create_index("id", unique=True)
        await db.matches.create_index("paper1_id")
        await db.matches.create_index("paper2_id")
        await db.matches.create_index("created_at")
        await db.settings.create_index("key", unique=True)
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")

    # Migration: remove papers where cs.RO is not the primary category
    try:
        non_ro_papers = []
        async for p in db.papers.find({}, {"_id": 0, "id": 1, "categories": 1}):
            cats = p.get("categories", [])
            if not cats or cats[0] != "cs.RO":
                non_ro_papers.append(p["id"])
        if non_ro_papers:
            await db.matches.delete_many({"$or": [
                {"paper1_id": {"$in": non_ro_papers}},
                {"paper2_id": {"$in": non_ro_papers}},
            ]})
            await db.papers.delete_many({"id": {"$in": non_ro_papers}})
            logger.info(f"Cleaned {len(non_ro_papers)} non-primary cs.RO papers")
    except Exception as e:
        logger.warning(f"Migration warning: {e}")

    await start_scheduler()

    # Pre-warm leaderboard cache so first visitor gets instant response
    try:
        from routers.leaderboard import _get_cached_leaderboard
        await _get_cached_leaderboard()
        logger.info("Leaderboard cache warmed")
    except Exception as e:
        logger.warning(f"Cache warm failed: {e}")

    logger.info("PaperSumo Leaderboard started")


@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
