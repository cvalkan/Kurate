from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import os
import time as _time
from collections import defaultdict
from core.config import db, logger
from routers.leaderboard import router as leaderboard_router
from routers.admin import router as admin_router
from routers.auth import router as auth_router
from routers.suggestions import router as suggestions_router
from services.scheduler import start_scheduler

app = FastAPI(title="PaperSumo - Robotics Paper Leaderboard")

# --- Simple in-memory rate limiter ---
_rate_buckets = defaultdict(list)  # ip -> [timestamps]
_RATE_LIMITS = {
    "/api/admin/login": (5, 60),       # 5 per 60s
    "/api/model-correlation": (10, 60), # 10 per 60s
}
_DEFAULT_RATE = (120, 60)  # 120 per 60s for all other endpoints


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Use X-Forwarded-For for real client IP behind proxy/K8s ingress
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    path = request.url.path
    max_requests, window = _RATE_LIMITS.get(path, _DEFAULT_RATE)
    key = f"{ip}:{path}" if path in _RATE_LIMITS else ip

    now = _time.time()
    _rate_buckets[key] = [t for t in _rate_buckets[key] if now - t < window]

    if len(_rate_buckets[key]) >= max_requests:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please slow down."})

    _rate_buckets[key].append(now)

    # Periodic cleanup of stale buckets (every ~1000 requests)
    if len(_rate_buckets) > 5000:
        stale = [k for k, v in _rate_buckets.items() if not v or now - v[-1] > 120]
        for k in stale:
            del _rate_buckets[k]

    return await call_next(request)


app.include_router(leaderboard_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(suggestions_router)

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
        await db.matches.create_index("primary_category")
        await db.matches.create_index("created_at")
        # Compound index for the most common admin query pattern
        await db.matches.create_index([
            ("primary_category", 1), ("completed", 1), ("failed", 1), ("mode", 1)
        ])
        await db.settings.create_index("key", unique=True)
        await db.users.create_index("email", unique=True)
        await db.users.create_index("user_id", unique=True)
        await db.user_sessions.create_index("session_token", unique=True)
        await db.user_sessions.create_index("user_id")
        await db.suggestions.create_index("created_at")
        # Tournament indexes — drop stale ones first to avoid conflicts
        try:
            await db.tournaments.drop_index("id_1")
        except Exception:
            pass
        await db.tournaments.create_index("tournament_id", unique=True)
        await db.tournaments.create_index([("status", 1), ("category", 1)])
        # Admin sessions collection
        await db.admin_sessions.create_index("key", unique=True)
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")

    # Migration: remove papers whose primary category is not in active categories
    try:
        from core.auth import get_settings
        from core.config import CATEGORIES
        _settings = await get_settings()
        valid_cats = set(_settings.get("active_categories", list(CATEGORIES.keys())))
        # Only clean up if we have valid categories
        if valid_cats:
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

    # Initialize tournament registry from CATEGORIES
    try:
        from services.scheduler import init_tournament_registry
        await init_tournament_registry()
    except Exception as e:
        logger.warning(f"Tournament registry init warning: {e}")

    await start_scheduler()

    # Start background cache refresh loop — pre-computes all leaderboard data
    from routers.leaderboard import start_cache_bg
    start_cache_bg()

    logger.info("PaperSumo Leaderboard started")


@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
