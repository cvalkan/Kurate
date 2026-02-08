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
        await db.matches.create_index("shared_categories")
        await db.matches.create_index("created_at")
        await db.settings.create_index("key", unique=True)
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")

    # Migration: remove papers whose primary category is not in CATEGORIES
    try:
        from core.config import CATEGORIES
        valid_cats = set(CATEGORIES.keys())
        invalid_papers = []
        async for p in db.papers.find({}, {"_id": 0, "id": 1, "categories": 1}):
            cats = p.get("categories", [])
            if not cats or cats[0] not in valid_cats:
                invalid_papers.append(p["id"])
        if invalid_papers:
            await db.matches.delete_many({"$or": [
                {"paper1_id": {"$in": invalid_papers}},
                {"paper2_id": {"$in": invalid_papers}},
            ]})
            await db.papers.delete_many({"id": {"$in": invalid_papers}})
            logger.info(f"Cleaned {len(invalid_papers)} papers with unsupported primary categories")
    except Exception as e:
        logger.warning(f"Migration warning: {e}")

    # Migration: fix prompt variables if needed
    try:
        from core.config import DEFAULT_EVALUATION_PROMPT
        prompt_doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
        if prompt_doc and "{paper1_abstract}" in prompt_doc.get("user_prompt", ""):
            new_user = prompt_doc["user_prompt"].replace("{paper1_abstract}", "{paper1_content}").replace("{paper2_abstract}", "{paper2_content}")
            await db.settings.update_one({"key": "custom_prompt"}, {"$set": {"user_prompt": new_user}})
            logger.info("Fixed prompt variables")
        elif not prompt_doc:
            await db.settings.update_one(
                {"key": "custom_prompt"},
                {"$set": {"key": "custom_prompt", **DEFAULT_EVALUATION_PROMPT}},
                upsert=True,
            )
            logger.info("Saved default prompt to DB")
    except Exception as e:
        logger.warning(f"Prompt migration warning: {e}")

    # Backfill shared_categories on existing matches (piggyback for cross-category)
    try:
        from services.scheduler import backfill_shared_categories
        await backfill_shared_categories()
    except Exception as e:
        logger.warning(f"shared_categories backfill warning: {e}")

    await start_scheduler()

    # Start background cache refresh loop — pre-computes all leaderboard data
    from routers.leaderboard import start_cache_bg
    start_cache_bg()

    logger.info("PaperSumo Leaderboard started")


@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
