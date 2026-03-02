from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import os
import time as _time
import asyncio
from collections import defaultdict
from core.config import db, logger
from routers.leaderboard import router as leaderboard_router
from routers.admin import router as admin_router
from routers.auth import router as auth_router
from routers.suggestions import router as suggestions_router
from routers.validation import router as validation_router
from routers.validation_imports import router as validation_imports_router
from routers.validation_experiments import router as validation_experiments_router
from routers.pairwise import router as pairwise_router
from routers.scipost import router as scipost_router
from routers.qeios import router as qeios_router
from routers.summary_bias import router as summary_bias_router
from services.scheduler import start_scheduler

app = FastAPI(title="PaperSumo - Robotics Paper Leaderboard")

# --- Simple in-memory rate limiter ---
_rate_buckets = defaultdict(list)  # ip -> [timestamps]
_RATE_LIMITS = {
    "/api/admin/login": (5, 60),       # 5 per 60s
    "/api/model-correlation": (10, 60), # 10 per 60s
    "/api/validation/convergence-all": (20, 60),  # expensive computation
    "/api/validation/convergence": (20, 60),
    "/api/validation/cross-mode-agreement": (20, 60),
}
_DEFAULT_RATE = (120, 60)  # 120 per 60s for all other endpoints


# --- Security Headers ---
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",  # HSTS - 1 year
    "X-Content-Type-Options": "nosniff",  # Prevent MIME sniffing
    "X-Frame-Options": "DENY",  # Prevent clickjacking
    "X-XSS-Protection": "1; mode=block",  # XSS filter for legacy browsers
    "Referrer-Policy": "strict-origin-when-cross-origin",  # Control referrer info
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",  # Restrict browser features
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https:; frame-ancestors 'none';",
}


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Use X-Forwarded-For for real client IP behind proxy/K8s ingress
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    path = request.url.path

    # Exempt admin endpoints from rate limiting (already auth-protected)
    if path.startswith("/api/admin/"):
        return await call_next(request)

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
app.include_router(validation_router)
app.include_router(validation_imports_router)
app.include_router(validation_experiments_router)
app.include_router(pairwise_router)
app.include_router(scipost_router)
app.include_router(qeios_router)
app.include_router(summary_bias_router)

_cors_raw = os.environ.get("CORS_ORIGINS", "https://kurate.org,https://www.kurate.org,https://papersumo.kurate.org")
_cors_allow_all = _cors_raw.strip() == "*"

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    # When CORS_ORIGINS="*", use allow_origin_regex to echo the request origin
    # (allow_origins=["*"] + allow_credentials=True is invalid per CORS spec)
    allow_origins=[] if _cors_allow_all else _cors_raw.split(","),
    allow_origin_regex=".*" if _cors_allow_all else None,
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
        await db.papers.create_index("arxiv_id", unique=True, sparse=True)
        await db.papers.create_index("chemrxiv_id", unique=True, sparse=True)
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
        # Validation experiment indexes
        await db.validation_papers.create_index("id", unique=True)
        await db.validation_papers.create_index([("dataset_id", 1), ("id", 1)])
        await db.validation_matches.create_index("id", unique=True)
        await db.validation_matches.create_index([("completed", 1), ("failed", 1)])
        await db.validation_matches.create_index([("dataset_id", 1), ("completed", 1), ("failed", 1)])
        # Compound index for content_mode queries (most common query pattern)
        await db.validation_matches.create_index(
            [("dataset_id", 1), ("content_mode", 1), ("completed", 1), ("failed", 1)],
            name="dataset_mode_completed_failed"
        )
        await db.validation_matches.create_index([("dataset_id", 1), ("completed", 1)])
        # Summarizer comparisons indexes
        await db.summarizer_comparisons.create_index("dataset_id")
        await db.summarizer_comparisons.create_index([("paper1_id", 1), ("paper2_id", 1)])
        # Pairwise comparison indexes
        await db.pairwise_comparisons.create_index("id", unique=True)
        await db.pairwise_comparisons.create_index([("reviewer", 1), ("source", 1)])
        await db.pairwise_comparisons.create_index("domain")
        # Summary bias experiment indexes
        await db.summary_bias_summaries.create_index([("paper_id", 1), ("model_key", 1)], unique=True)
        await db.summary_bias_summaries.create_index("category")
        await db.summary_bias_matches.create_index("id", unique=True)
        await db.summary_bias_matches.create_index([("category", 1), ("completed", 1)])
        await db.summary_bias_matches.create_index([("original_match_id", 1), ("judge_key", 1), ("summary_key", 1)])
        # Ranking snapshots for convergence tracking
        await db.ranking_snapshots.create_index([("category", 1), ("round", -1)])
        # Summarizer-ab task queue (for auto-resume on restart)
        await db.summarizer_ab_tasks.create_index([("dataset_id", 1), ("summarizer", 1)], unique=True)
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

    # Migration: update settings for new convergence-based architecture
    try:
        from core.auth import invalidate_settings_cache as _inv_cache
        _settings_doc = await db.settings.find_one({"key": "global"})
        if _settings_doc:
            migration_updates = {}
            # Set new convergence defaults if not present
            if _settings_doc.get("convergence_threshold") is None:
                migration_updates["convergence_threshold"] = 0.95
            if _settings_doc.get("convergence_rounds") is None:
                migration_updates["convergence_rounds"] = 3
            if _settings_doc.get("summary_source") is None:
                migration_updates["summary_source"] = "claude"
            # Migrate from round_robin to claude for live tournaments
            elif _settings_doc.get("summary_source") == "round_robin":
                migration_updates["summary_source"] = "claude"
            if _settings_doc.get("summary_parallel") is None:
                migration_updates["summary_parallel"] = 10
            # Reduce min/max matches per the new architecture
            if _settings_doc.get("min_matches_per_paper", 0) > 5:
                migration_updates["min_matches_per_paper"] = 3
            if _settings_doc.get("max_matches_per_paper") is None or _settings_doc.get("max_matches_per_paper", 999) > 50:
                migration_updates["max_matches_per_paper"] = 20
            if migration_updates:
                await db.settings.update_one({"key": "global"}, {"$set": migration_updates})
                _inv_cache()
                logger.info(f"Migrated settings: {list(migration_updates.keys())}")
    except Exception as e:
        logger.warning(f"Settings migration warning: {e}")

    # Migration: seed initial ranking snapshots from existing match data
    try:
        from services.scheduler import _store_ranking_snapshot
        snapshot_count = await db.ranking_snapshots.count_documents({})
        if snapshot_count == 0:
            from core.auth import get_settings as _gs
            _s = await _gs()
            _active = _s.get("active_categories", list(CATEGORIES.keys()))
            for _cat in _active:
                paper_count = await db.papers.count_documents({"categories.0": _cat})
                match_count = await db.matches.count_documents({
                    "completed": True, "failed": {"$ne": True},
                    "primary_category": _cat, "mode": {"$exists": False}
                })
                if paper_count >= 2 and match_count >= 10:
                    await _store_ranking_snapshot(_cat)
                    logger.info(f"Seeded ranking snapshot for {_cat}")
            logger.info("Ranking snapshot seeding complete")
    except Exception as e:
        logger.warning(f"Ranking snapshot seeding warning: {e}")

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

    # Pre-warm extraction stats cache in background (expensive computation)
    import asyncio
    asyncio.create_task(_prewarm_extraction_cache())
    asyncio.create_task(_prewarm_validation_cache())
    asyncio.create_task(_prewarm_analysis_cache())
    asyncio.create_task(_prewarm_consistency_cache())
    asyncio.create_task(_startup_dedup())
    asyncio.create_task(_startup_regen_truncated_summaries())
    asyncio.create_task(_startup_resume_summarizer_ab())
    asyncio.create_task(_startup_check_interrupted_tasks())

    logger.info("PaperSumo Leaderboard started")



async def _prewarm_analysis_cache():
    """Pre-warm model-correlation and convergence caches for all active categories."""
    await asyncio.sleep(8)  # Wait for leaderboard cache to be ready
    try:
        from routers.leaderboard import _compute_model_correlation, _compute_convergence, _set_analysis_cached
        from core.auth import get_settings
        settings = await get_settings()
        cats = settings.get("active_categories", [])
        for cat in cats:
            try:
                result = await _compute_model_correlation(cat, None)
                _set_analysis_cached("model-correlation", cat, "", result)
            except Exception:
                pass
            try:
                result = await _compute_convergence(cat, 20)
                _set_analysis_cached("convergence", cat, "20", result)
            except Exception:
                pass
        logger.info(f"Analysis cache pre-warmed: {len(cats)} categories")

        # Also prewarm summary bias caches
        from routers.summary_bias import _compute_results, _compute_sb_convergence, _sb_cache
        sb_cats = set()
        async for r in db.summary_bias_matches.aggregate([{"$group": {"_id": "$category"}}]):
            sb_cats.add(r["_id"])
        for cat in sb_cats:
            try:
                result = await _compute_results(cat)
                _sb_cache[("results", cat)] = {"data": result, "ts": __import__("time").time()}
            except Exception:
                pass
            try:
                result = await _compute_sb_convergence(cat, 15)
                _sb_cache[("convergence", cat)] = {"data": result, "ts": __import__("time").time()}
            except Exception:
                pass
        if sb_cats:
            logger.info(f"Summary bias cache pre-warmed: {len(sb_cats)} categories")
    except Exception as e:
        logger.warning(f"Analysis cache prewarm failed: {e}")


async def _prewarm_consistency_cache():
    """Pre-warm consistency analysis and cycle-analysis-all caches (expensive)."""
    await asyncio.sleep(15)  # Wait for other caches
    try:
        from routers.validation import _compute_consistency_analysis, _compute_cycle_analysis_all
        from routers.validation_utils import consistency_cache, cycle_all_cache
        import time as _t
        result = await _compute_consistency_analysis()
        if result.get("status") == "ok":
            consistency_cache["data"] = result
            consistency_cache["ts"] = _t.time()
        result2 = await _compute_cycle_analysis_all()
        if result2.get("status") == "ok":
            cycle_all_cache["data"] = result2
            cycle_all_cache["ts"] = _t.time()
        logger.info("Consistency + cycle-analysis-all caches pre-warmed")
    except Exception as e:
        logger.warning(f"Consistency cache prewarm failed: {e}")
    # Also warm summarizer experiment caches
    try:
        from routers.validation_experiments import _compute_summarizer_ab_results, _compute_assessor_evaluator
        from routers.validation_utils import sumab_results_cache, ae_cache
        r1 = await _compute_summarizer_ab_results()
        if r1.get("status") == "ok":
            sumab_results_cache["data"] = r1
            sumab_results_cache["ts"] = _t.time()
        r2 = await _compute_assessor_evaluator()
        if r2.get("status") == "ok":
            ae_cache["data"] = r2
            ae_cache["ts"] = _t.time()
        logger.info("Summarizer experiment caches pre-warmed")
    except Exception as e:
        logger.warning(f"Summarizer cache prewarm failed: {e}")




async def _startup_dedup():
    """Auto-deduplicate papers on startup (merges duplicates by title+author)."""
    await asyncio.sleep(10)  # Wait for DB + caches to be ready
    try:
        from collections import defaultdict
        all_papers = await db.papers.find(
            {}, {"_id": 0, "id": 1, "title": 1, "authors": 1, "summaries": 1, "full_text": 1}
        ).to_list(5000)
        groups = defaultdict(list)
        for p in all_papers:
            title_norm = p["title"].strip().lower()
            first_author = (p.get("authors") or [""])[0].strip().lower() if p.get("authors") else ""
            groups[(title_norm, first_author)].append(p)

        merged = 0
        for key, papers in groups.items():
            if len(papers) < 2:
                continue
            for p in papers:
                p["_mc"] = await db.matches.count_documents({"$or": [{"paper1_id": p["id"]}, {"paper2_id": p["id"]}]})
                p["_hs"] = bool(p.get("summaries"))
                p["_ht"] = bool(p.get("full_text"))
            papers.sort(key=lambda p: (p["_hs"], p["_ht"], p["_mc"]), reverse=True)
            keeper = papers[0]
            for dup in papers[1:]:
                await db.matches.update_many({"paper1_id": dup["id"]}, {"$set": {"paper1_id": keeper["id"]}})
                await db.matches.update_many({"paper2_id": dup["id"]}, {"$set": {"paper2_id": keeper["id"]}})
                await db.matches.update_many({"winner_id": dup["id"]}, {"$set": {"winner_id": keeper["id"]}})
                if dup.get("summaries") and not keeper.get("summaries"):
                    await db.papers.update_one({"id": keeper["id"]}, {"$set": {"summaries": dup["summaries"]}})
                await db.papers.delete_one({"id": dup["id"]})
                merged += 1
        if merged > 0:
            await db.matches.delete_many({"$expr": {"$eq": ["$paper1_id", "$paper2_id"]}})
            logger.info(f"Startup dedup: merged {merged} duplicate papers")
    except Exception as e:
        logger.warning(f"Startup dedup failed: {e}")


async def _startup_regen_truncated_summaries():
    """One-time migration: regenerate summaries that were truncated by the old 40k char limit.
    
    Gated by a DB flag so it only runs once. Resumes cleanly after restarts —
    already-regenerated papers no longer match the scan filter.
    """
    await asyncio.sleep(60)  # Wait for caches + scheduler to be fully ready
    try:
        flag = await db.settings.find_one({"key": "regen_truncated_summaries_v1"}, {"_id": 0})
        if flag and flag.get("done"):
            return  # Already completed

        from routers.admin import _run_regen, _get_regen_progress, _set_regen_progress

        # Check if a manual trigger already started it
        progress = await _get_regen_progress()
        if progress.get("running"):
            logger.info("Summary regen: already running (manual trigger), skipping startup trigger")
            return

        # Mark as running and launch
        await _set_regen_progress(running=True, done=0, started_total=0, errors=0, finished=False)
        await _run_regen()

        # Mark the one-time migration as done
        progress = await _get_regen_progress()
        await db.settings.update_one(
            {"key": "regen_truncated_summaries_v1"},
            {"$set": {"key": "regen_truncated_summaries_v1", "done": True,
                       "total": progress.get("done", 0), "errors": progress.get("errors", 0)}},
            upsert=True,
        )
        logger.info("Summary regen startup migration complete")
    except Exception as e:
        logger.error(f"Summary regen startup task failed: {e}")


async def _startup_resume_summarizer_ab():
    """Resume incomplete summarizer-ab tasks that were interrupted by a restart."""
    await asyncio.sleep(30)  # Wait for caches + scheduler to be ready
    try:
        from routers.validation_experiments import resume_incomplete_summarizer_ab
        await resume_incomplete_summarizer_ab()
    except Exception as e:
        logger.warning(f"Summarizer-ab resume failed: {e}")


async def _startup_check_interrupted_tasks():
    """Log warnings for any background tasks that were running when the server stopped."""
    await asyncio.sleep(3)
    try:
        from services.task_tracker import TaskTracker
        interrupted = await TaskTracker.warn_interrupted()
        await TaskTracker.cleanup_old(days=30)
        if not interrupted:
            logger.info("No interrupted background tasks found")
    except Exception as e:
        logger.warning(f"Interrupted task check failed: {e}")



async def _prewarm_extraction_cache():
    """Pre-warm the extraction stats cache in background to avoid slow first load."""
    await asyncio.sleep(5)  # Wait for other startup tasks
    try:
        from routers.admin import _compute_extraction_stats_impl, _extraction_cache
        import time as _t
        # Only prewarm if cache is empty
        if not _extraction_cache.get("data"):
            logger.info("Pre-warming extraction stats cache...")
            _extraction_cache["computing"] = True
            try:
                result = await _compute_extraction_stats_impl(category=None)
                _extraction_cache["data"] = result
                _extraction_cache["timestamp"] = _t.time()
                _extraction_cache["warming_up"] = False
                logger.info("Extraction stats cache warmed")
            finally:
                _extraction_cache["computing"] = False
    except Exception as e:
        logger.warning(f"Extraction cache prewarm failed: {e}")


async def _prewarm_validation_cache():
    """Pre-warm validation endpoints by running the aggregation queries on startup."""
    await asyncio.sleep(3)
    try:
        # Auto-seed validation data from bundled files if DB is empty
        count = await db.validation_datasets.count_documents({})
        if count == 0:
            from pathlib import Path
            import json as _json
            seed_dir = Path(__file__).parent / "backend" / "data" / "validation_seed"
            if not seed_dir.exists():
                seed_dir = Path("/app/backend/data/validation_seed")
            if seed_dir.exists():
                logger.info("Auto-seeding validation data from bundled files...")
                for coll_name in ["validation_datasets", "validation_papers", "validation_matches", "pairwise_comparisons"]:
                    path = seed_dir / f"{coll_name}.json"
                    if path.exists():
                        with open(path) as f:
                            docs = _json.load(f)
                        if docs:
                            await db[coll_name].insert_many(docs)
                            logger.info(f"  Seeded {coll_name}: {len(docs)} docs")
                logger.info("Validation data seeded successfully")

        # Run the datasets aggregation to warm MongoDB query cache
        pipeline = [
            {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
        ]
        async for _ in db.validation_papers.aggregate(pipeline):
            pass
        pipeline2 = [
            {"$match": {"completed": True, "failed": {"$ne": True}}},
            {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
        ]
        async for _ in db.validation_matches.aggregate(pipeline2):
            pass
        logger.info("Validation cache pre-warmed")

        # Pre-warm result cache for common datasets (background, non-blocking)
        asyncio.create_task(_prewarm_result_cache())
    except Exception as e:
        logger.warning(f"Validation cache prewarm failed: {e}")


async def _prewarm_result_cache():
    """Background loop that keeps validation result caches warm."""
    await asyncio.sleep(5)
    while True:
        try:
            from routers.validation import get_pairwise_results, get_convergence_all
            from routers.validation_utils import convergence_all_cache
            pipeline = [
                {"$match": {"completed": True, "failed": {"$ne": True}}},
                {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 30},
            ]
            top_datasets = [doc["_id"] async for doc in db.validation_matches.aggregate(pipeline)]

            warmed = conv_warmed = 0
            for ds_id in top_datasets:
                try:
                    await get_pairwise_results(dataset_id=ds_id, content_mode="abstract")
                    warmed += 1
                except Exception:
                    pass
                try:
                    await get_convergence_all(dataset_id=ds_id, steps=20)
                    conv_warmed += 1
                except Exception:
                    pass
            logger.info(f"Result cache pre-warmed: {warmed} pairwise, {conv_warmed} convergence")
        except Exception as e:
            logger.warning(f"Result cache prewarm failed: {e}")
        await asyncio.sleep(300)  # Re-warm every 5 minutes


@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
