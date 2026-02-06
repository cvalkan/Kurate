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

    await start_scheduler()
    logger.info("PaperSumo Leaderboard started")


@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
