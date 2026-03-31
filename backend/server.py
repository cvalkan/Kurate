from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import os
import time as _time
import asyncio
from datetime import datetime, timezone
from collections import defaultdict
from core.config import db, logger

SITE_URL = os.environ.get("SITE_URL", "")
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
from routers.claims import router as claims_router
from routers.badges import router as badges_router
from routers.congrats import router as congrats_router
from routers.bookmarks import router as bookmarks_router
from routers.reading_lists import router as reading_lists_router
from routers.human_ai_benchmark import router as benchmark_router
from routers.si_benchmark import router as si_benchmark_router
from routers.unified_benchmark import router as unified_benchmark_router
from services.scheduler import start_scheduler

app = FastAPI(title="Kurate.org - AI Paper Rankings")

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
async def head_method_middleware(request: Request, call_next):
    """Convert HEAD to GET for badge endpoints (social media crawlers use HEAD to check images)."""
    if request.method == "HEAD" and ("/api/badge/" in request.url.path or "/api/lists/" in request.url.path):
        request._method = "GET"
        request.scope["method"] = "GET"
        response = await call_next(request)
        # Return headers only, no body (per HTTP spec for HEAD)
        from starlette.responses import Response as StarletteResponse
        return StarletteResponse(
            content=b"",
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses. Preserve Cache-Control on share endpoints."""
    response = await call_next(request)
    path = request.url.path
    is_share = "/share" in path or "/image.png" in path
    for header, value in SECURITY_HEADERS.items():
        # Don't override Cache-Control on share/image endpoints (they set no-transform for crawlers)
        if header.lower() == "cache-control" and is_share and "cache-control" in response.headers:
            continue
        response.headers[header] = value
    # Add no-transform on share endpoints to discourage Cloudflare modifications
    if is_share:
        response.headers["Cache-Control"] = "public, max-age=300, no-transform"
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
app.include_router(claims_router)
app.include_router(badges_router)
app.include_router(congrats_router)
app.include_router(bookmarks_router)
app.include_router(reading_lists_router)
app.include_router(benchmark_router)
app.include_router(si_benchmark_router)
app.include_router(unified_benchmark_router)

_cors_raw = os.environ.get("CORS_ORIGINS", "https://kurate.org,https://www.kurate.org,https://papersumo.kurate.org")
_cors_allow_all = _cors_raw.strip() == "*"

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[] if _cors_allow_all else _cors_raw.split(","),
    allow_origin_regex=".*" if _cors_allow_all else None,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress responses >500 bytes (JSON payloads shrink 5-7×)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "papersumo-leaderboard"}

@app.get("/api/prewarm-status")
async def prewarm_status():
    s = getattr(app.state, "prewarm_status", {"done": True, "step": ""})
    return s


@app.get("/api/gmail/callback")
async def gmail_callback(code: str, state: str, request: Request):
    """Handle Gmail OAuth callback — exchange code for tokens."""
    import warnings
    state_doc = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0})
    if not state_doc:
        raise HTTPException(400, "Invalid or expired OAuth state")
    await db.gmail_oauth_states.delete_one({"state": state})

    user_id = state_doc["user_id"]
    return_to = state_doc.get("return_to", "/")

    redirect_uri = SITE_URL + "/api/gmail/callback" if SITE_URL else f"{request.headers.get('origin', '')}/api/gmail/callback"
    from routers.congrats import _build_flow
    flow = _build_flow(redirect_uri)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flow.fetch_token(code=code)

    creds = flow.credentials
    await db.gmail_tokens.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    logger.info(f"Gmail authorized for user {user_id}")
    # Redirect back to the badge page
    return RedirectResponse(url=return_to or "/")


@app.on_event("startup")
async def startup():
    app.state.prewarm_status = {"done": False, "step": "Loading caches"}

    # Remove --reload from supervisor config if present.
    # The platform generates the config with --reload (a dev-only feature) which causes
    # restart storms on deploy and doubled RSS during restarts → OOM kills.
    # This patch runs on every boot so it survives config resets.
    try:
        import subprocess
        conf_path = "/etc/supervisor/conf.d/supervisord.conf"
        with open(conf_path) as f:
            conf = f.read()
        if "--reload" in conf:
            with open(conf_path, "w") as f:
                f.write(conf.replace(" --reload", ""))
            subprocess.run(["supervisorctl", "reread"], capture_output=True)
            subprocess.run(["supervisorctl", "update", "backend"], capture_output=True)
            logger.info("Removed --reload from supervisor config (production fix)")
    except Exception as e:
        logger.warning(f"Supervisor config patch failed: {e}")

    # Cap MongoDB WiredTiger cache to prevent OOM kills in 2GB container.
    # Default is 50% of system RAM (~3.5GB) which leaves no room for Python.
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        admin_db = db.client.admin
        await admin_db.command({"setParameter": 1, "wiredTigerEngineRuntimeConfig": "cache_size=512M"})
        logger.info("MongoDB WiredTiger cache capped to 512MB")
    except Exception as e:
        logger.warning(f"Failed to cap MongoDB cache: {e}")

    # FAST PATH: Only create essential indexes, then let server accept connections.
    # All migrations, backfills, and cache warming run in background.
    try:
        await db.papers.create_index("id", unique=True)
        await db.matches.create_index("id", unique=True)
        await db.settings.create_index("key", unique=True)
        await db.users.create_index("email", unique=True)
        await db.users.create_index("user_id", unique=True)
        await db.user_sessions.create_index("session_token", unique=True)
        logger.info("Essential MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")

    # Load precomputed JSON BEFORE accepting connections — prevents race condition
    # where a request arrives before experiment caches are populated
    try:
        from services.precompute import load_precomputed
        loaded = load_precomputed()
        if loaded > 0:
            logger.info(f"Precomputed caches loaded at startup: {loaded}")
    except Exception as e:
        logger.warning(f"Precomputed cache load failed: {e}")

    # Start accepting connections NOW — everything else runs in background
    asyncio.create_task(_deferred_startup())
    from core.memlog import log_mem, ensure_ttl_index
    await ensure_ttl_index(db)
    log_mem("Server started")
    logger.info("Kurate.org Leaderboard started")


async def _deferred_startup():
    """Heavy startup work that runs in background after health endpoint is available."""
    await asyncio.sleep(0.1)  # Yield to let server start accepting connections

    # Create remaining indexes
    try:
        await db.papers.create_index("arxiv_id", unique=True, sparse=True)
        await db.papers.create_index("chemrxiv_id", unique=True, sparse=True)
        await db.papers.create_index("published")
        await db.papers.create_index([("categories", 1), ("summaries", 1)], name="categories_summaries")
        await db.matches.create_index("paper1_id")
        await db.matches.create_index("paper2_id")
        await db.matches.create_index("shared_categories")
        await db.matches.create_index("primary_category")
        await db.matches.create_index("created_at")
        await db.matches.create_index([
            ("primary_category", 1), ("completed", 1), ("failed", 1), ("mode", 1)
        ])
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
        await db.summarizer_comparisons.create_index("dataset_id", name="dataset_id")
        await db.summarizer_comparisons.create_index([("paper1_id", 1), ("paper2_id", 1)], name="paper_pair")
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
        # Leaderboard archives (weekly/monthly frozen snapshots)
        await db.leaderboard_archives.create_index([("category", 1), ("year", -1), ("week", -1)])
        await db.leaderboard_archives.create_index([("category", 1), ("year", -1), ("month", -1)])
        await db.leaderboard_archives.create_index([("category", 1), ("period_type", 1), ("year", -1)])
        # Summarizer-ab task queue (for auto-resume on restart)
        await db.summarizer_ab_tasks.create_index([("dataset_id", 1), ("summarizer", 1)], unique=True)
        # Author verifications (ORCID claiming)
        await db.author_verifications.create_index("user_id", unique=True)
        await db.author_verifications.create_index("orcid_id")
        # Rankings collection (DB-backed leaderboard)
        await db.rankings.create_index("paper_id", unique=True)
        await db.rankings.create_index([("category", 1), ("rank", 1)])
        await db.rankings.create_index([("category", 1), ("score", -1)])
        await db.rankings.create_index([("category", 1), ("published", -1)])
        await db.rankings.create_index([("category", 1), ("added_at", -1)])
        await db.rankings.create_index([("added_at", -1)], name="added_at_-1")  # For unscoped "recent" (all-papers view)
        await db.rankings.create_index([("categories", 1), ("score", -1)], name="categories_score")  # For tag-filtered views
        # Server-side sort indexes (all sortable leaderboard columns)
        await db.rankings.create_index([("category", 1), ("ts_score", -1)], name="category_1_ts_score_-1")
        await db.rankings.create_index([("category", 1), ("comparisons", -1)], name="category_1_comparisons_-1")
        await db.rankings.create_index([("category", 1), ("win_rate", -1)], name="category_1_win_rate_-1")
        await db.rankings.create_index([("category", 1), ("title", 1)], name="category_1_title_1")
        await db.rankings.create_index([("ts_score", -1)], name="ts_score_-1")  # Cross-category TS sort
        await db.rankings.create_index([("comparisons", -1)], name="comparisons_-1")
        await db.rankings.create_index([("title", 1)], name="title_1")
        # Analysis store (pre-aggregated Model Analysis results)
        # Version check: clear stale docs when schema changes
        _ANALYSIS_STORE_VERSION = 5  # Bump: clear stale gpt-5 cache from old production code
        try:
            await db.analysis_store.drop_indexes()
        except Exception:
            pass
        await db.analysis_store.create_index([("_type", 1), ("key", 1)], unique=True)
        version_doc = await db.analysis_store.find_one({"_type": "__version__"})
        if not version_doc or version_doc.get("v") != _ANALYSIS_STORE_VERSION:
            await db.analysis_store.delete_many({"_type": {"$ne": "__version__"}})
            await db.analysis_store.update_one(
                {"_type": "__version__"},
                {"$set": {"_type": "__version__", "key": "__version__", "v": _ANALYSIS_STORE_VERSION}},
                upsert=True,
            )
            logger.info(f"Analysis store cleared (schema version {_ANALYSIS_STORE_VERSION})")
        # Convergence cache
        await db.convergence_cache.create_index("category", unique=True)
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

    # Initialize tournament registry from CATEGORIES
    try:
        from services.scheduler import init_tournament_registry
        await init_tournament_registry()
    except Exception as e:
        logger.warning(f"Tournament registry init warning: {e}")

    # Migration: backfill per-model SI ratings from existing summaries + ai_rating
    # Idempotent: skips papers that already have ratings. No LLM calls — just text parsing.
    try:
        from services.llm import parse_ratings_from_summary
        _MODEL_MAP = {
            "openai:gpt-5_2": "gpt",
            "gemini:gemini-3-pro-preview": "gemini",
            "anthropic:claude-opus-4-6:thinking": "claude",
            "anthropic:claude-opus-4-6": "claude",
            "anthropic:claude-opus-4-5-20251101": "claude",
        }
        # Step 1: Copy ai_rating → ai_ratings_by_model.claude
        r1 = await db.papers.update_many(
            {"ai_rating": {"$exists": True}, "ai_ratings_by_model.claude": {"$exists": False}},
            [{"$set": {"ai_ratings_by_model.claude": "$ai_rating"}}]
        )
        # Step 2: Parse ratings from all model summaries
        _backfill_parsed = 0
        async for p in db.papers.find(
            {"summaries": {"$exists": True, "$ne": {}}},
            {"_id": 0, "id": 1, "summaries": 1, "ai_ratings_by_model": 1}
        ):
            existing = p.get("ai_ratings_by_model", {}) or {}
            update = {}
            for sk, text in p.get("summaries", {}).items():
                ms = _MODEL_MAP.get(sk)
                if not ms or not isinstance(text, str):
                    continue
                if ms in existing and isinstance(existing.get(ms), dict) and existing[ms].get("score"):
                    continue
                rating = parse_ratings_from_summary(text)
                if rating:
                    update[f"ai_ratings_by_model.{ms}"] = rating
                    _backfill_parsed += 1
            if update:
                await db.papers.update_one({"id": p["id"]}, {"$set": update})
        if r1.modified_count or _backfill_parsed:
            logger.info(f"SI rating backfill: {r1.modified_count} claude copied, {_backfill_parsed} parsed from summaries")
    except Exception as e:
        logger.warning(f"SI rating backfill warning: {e}")

    await start_scheduler()

    # Start background cache refresh loop — pre-computes all leaderboard data
    from routers.leaderboard import start_cache_bg
    start_cache_bg()

    # Pre-warm caches and run startup tasks in background.
    # IMPORTANT: Tasks are staggered to prevent concurrent memory spikes that
    # can trigger OOM kills. Heavy tasks (dedup, regen, experiment cache) are
    # sequenced rather than launched all at once.
    # Use globals() lookup to avoid NameError during hot-reload (uvicorn --reload
    # can fire the startup event before all module-level functions are defined).
    asyncio.create_task(_staggered_startup_tasks())

    logger.info("Deferred startup complete — all background tasks launched")


async def _staggered_startup_tasks():
    """Run startup tasks sequentially to prevent concurrent memory spikes.
    
    Previous approach launched all 8 tasks simultaneously, causing memory to
    spike to 2-3x normal levels. Sequential execution keeps peak memory ~40% lower.
    """
    from core.memlog import log_mem, force_gc
    _g = globals()

    log_mem("Staggered startup begin")

    # Phase 1: Fast, lightweight cache prewarms (run in parallel — tiny memory footprint)
    _fast_tasks = ["_prewarm_extraction_cache", "_prewarm_validation_cache", "_prewarm_all_experiment_caches"]
    for _name in _fast_tasks:
        _fn = _g.get(_name)
        if _fn:
            asyncio.create_task(_fn())

    # Phase 2: Memory-heavy startup tasks (run SEQUENTIALLY with GC between each)
    _heavy_tasks = [
        "_startup_dedup",
        "_startup_seed_rankings",
        "_startup_regen_truncated_summaries",
        "_startup_resume_summarizer_ab",
        "_startup_check_interrupted_tasks",
        "_startup_seed_targeted_matches",
    ]
    for _name in _heavy_tasks:
        _fn = _g.get(_name)
        if _fn:
            try:
                await _fn()
            except Exception as e:
                logger.warning(f"Startup task {_name} failed: {e}")
            force_gc()
            log_mem(f"After {_name}")
            await asyncio.sleep(1)



async def _prewarm_all_experiment_caches():
    """Load ALL validation data from precomputed JSON files. No computation.
    
    If data isn't in the JSON files, endpoints return 'no_data'.
    To update: run admin precompute-experiments on preview, deploy the new JSON files.
    """
    await asyncio.sleep(3)
    # JSON files already loaded in startup(). Nothing else to do.
    # The unified-benchmark and human-ai-benchmark caches are populated
    # by load_precomputed() which was called synchronously in startup().
    logger.info("All experiment caches loaded from precomputed JSON (no computation)")
    app.state.prewarm_status = {"done": True, "step": ""}

    await asyncio.sleep(8)  # Wait for leaderboard cache to be ready
    try:
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


async def _startup_dedup():
    """Backfill dedup_hash on existing papers and create unique index.
    
    Once backfilled, dedup happens at insert time (unique index prevents duplicates).
    No more full-table scan on startup — just a one-time migration.
    """
    import hashlib

    # Check if migration already done
    flag = await db.settings.find_one({"key": "dedup_hash_backfill_v1"}, {"_id": 0})
    if flag and flag.get("done"):
        return

    # Backfill dedup_hash for papers that don't have one
    backfilled = 0
    async for p in db.papers.find(
        {"dedup_hash": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "authors": 1},
    ):
        title_norm = p["title"].strip().lower()
        first_author = (p.get("authors") or [""])[0].strip().lower() if p.get("authors") else ""
        h = hashlib.sha256(f"{title_norm}|{first_author}".encode()).hexdigest()[:16]
        await db.papers.update_one({"id": p["id"]}, {"$set": {"dedup_hash": h}})
        backfilled += 1
        if backfilled % 200 == 0:
            await asyncio.sleep(0)

    # Merge any duplicates found by hash collision
    pipeline = [
        {"$group": {"_id": "$dedup_hash", "count": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    merged = 0
    async for group in db.papers.aggregate(pipeline):
        paper_ids = group["ids"]
        # Fetch lightweight metadata to decide which to keep
        papers = []
        for pid in paper_ids:
            mc = await db.matches.count_documents({"$or": [{"paper1_id": pid}, {"paper2_id": pid}]})
            hs = await db.papers.count_documents({"id": pid, "summaries": {"$exists": True, "$ne": {}}}) > 0
            ht = await db.papers.count_documents({"id": pid, "full_text": {"$ne": None}}) > 0
            papers.append({"id": pid, "_mc": mc, "_hs": hs, "_ht": ht})
        papers.sort(key=lambda p: (p["_hs"], p["_ht"], p["_mc"]), reverse=True)
        keeper = papers[0]
        for dup in papers[1:]:
            await db.matches.update_many({"paper1_id": dup["id"]}, {"$set": {"paper1_id": keeper["id"]}})
            await db.matches.update_many({"paper2_id": dup["id"]}, {"$set": {"paper2_id": keeper["id"]}})
            await db.matches.update_many({"winner_id": dup["id"]}, {"$set": {"winner_id": keeper["id"]}})
            if dup["_hs"] and not keeper["_hs"]:
                dup_doc = await db.papers.find_one({"id": dup["id"]}, {"_id": 0, "summaries": 1})
                if dup_doc and dup_doc.get("summaries"):
                    await db.papers.update_one({"id": keeper["id"]}, {"$set": {"summaries": dup_doc["summaries"]}})
            await db.papers.delete_one({"id": dup["id"]})
            merged += 1

    if merged > 0:
        await db.matches.delete_many({"$expr": {"$eq": ["$paper1_id", "$paper2_id"]}})

    # Create unique index (sparse: papers without hash are ignored)
    try:
        await db.papers.create_index("dedup_hash", unique=True, sparse=True, name="dedup_hash_unique")
    except Exception as e:
        logger.warning(f"dedup_hash index creation warning: {e}")

    # Mark migration as done
    await db.settings.update_one(
        {"key": "dedup_hash_backfill_v1"},
        {"$set": {"key": "dedup_hash_backfill_v1", "done": True, "backfilled": backfilled, "merged": merged}},
        upsert=True,
    )
    if backfilled or merged:
        logger.info(f"Dedup hash backfill: {backfilled} hashed, {merged} duplicates merged")



async def _startup_seed_rankings():
    """Seed the DB-backed rankings collection if empty or stale.
    
    Memory-optimized: only reseeds categories that actually have unranked papers,
    rather than all categories. Processes one category at a time with GC between.
    """
    try:
        from services.ranking import seed_rankings
        from core.auth import get_settings
        from core.config import CATEGORIES
        from core.memlog import force_gc

        settings = await get_settings()
        cats = settings.get("active_categories", list(CATEGORIES.keys()))

        # Check if rankings need seeding
        rankings_count = await db.rankings.count_documents({})
        papers_count = await db.papers.count_documents({"summaries": {"$exists": True, "$ne": {}}})

        if rankings_count == 0 and papers_count > 0:
            logger.info(f"Seeding rankings collection from {papers_count} papers...")
            seeded = await seed_rankings(db)
            logger.info(f"Rankings seeded: {seeded} entries across {len(cats)} categories")
        elif rankings_count > 0:
            # Find which specific categories have unranked papers
            cats_needing_seed = []
            for cat in cats:
                # Count papers with summaries for this category
                cat_papers = await db.papers.count_documents(
                    {"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}}
                )
                cat_rankings = await db.rankings.count_documents({"category": cat})
                if cat_papers > cat_rankings:
                    cats_needing_seed.append(cat)
                    logger.info(f"[{cat}] {cat_papers} papers, {cat_rankings} rankings — needs reseeding")

            if cats_needing_seed:
                logger.info(f"Reseeding {len(cats_needing_seed)}/{len(cats)} categories with new papers...")
                total_seeded = 0
                for cat in cats_needing_seed:
                    seeded = await seed_rankings(db, category=cat)
                    total_seeded += (seeded or 0)
                    force_gc()
                logger.info(f"Rankings reseeded: {total_seeded} entries in {len(cats_needing_seed)} categories")
            else:
                # Backfill added_at if empty/null (one-time migration)
                empty_added = await db.rankings.count_documents(
                    {"$or": [{"added_at": ""}, {"added_at": None}, {"added_at": {"$exists": False}}]}
                )
                if empty_added > 0:
                    logger.info(f"Backfilling added_at for {empty_added} rankings...")
                    backfilled = 0
                    async for p in db.papers.find(
                        {"added_at": {"$nin": [None, ""]}},
                        {"_id": 0, "id": 1, "added_at": 1}
                    ):
                        result = await db.rankings.update_one(
                            {"paper_id": p["id"], "$or": [{"added_at": ""}, {"added_at": None}, {"added_at": {"$exists": False}}]},
                            {"$set": {"added_at": p["added_at"]}}
                        )
                        if result.modified_count:
                            backfilled += 1
                    logger.info(f"Backfilled added_at for {backfilled} rankings")
                else:
                    logger.info(f"Rankings collection up to date ({rankings_count} entries)")

    except Exception as e:
        logger.warning(f"Rankings seed failed: {e}")



async def _startup_regen_truncated_summaries():
    """One-time migration: regenerate summaries that were truncated by the old 40k char limit.
    
    Gated by a DB flag so it only runs once. Resumes cleanly after restarts —
    already-regenerated papers no longer match the scan filter.
    """
    try:
        flag = await db.settings.find_one({"key": "regen_truncated_summaries_v1"}, {"_id": 0})
        if flag and flag.get("done"):
            return  # Already completed — skip immediately (no 60s wait)

        await asyncio.sleep(60)  # Wait for caches + scheduler to be fully ready

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
    try:
        # Quick check if there's anything to resume before waiting
        count = await db.summarizer_ab_tasks.count_documents({"status": "running"})
        if count == 0:
            return  # Nothing to resume — skip immediately
        await asyncio.sleep(30)  # Wait for caches + scheduler to be ready
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


async def _startup_seed_targeted_matches():
    """One-time: import all validation matches and deep-dive data not yet on this database."""
    await asyncio.sleep(10)
    try:
        # --- Match seed (v5) — skip immediately if already done ---
        flag = await db.settings.find_one({"key": "experiment_seed_v5b"}, {"_id": 0})
        if not (flag and flag.get("done")):
            from pathlib import Path
            import json as _json, gzip as _gzip
            path = Path("/app/backend/data/experiment_seed/all_matches_v5.json.gz")
            if path.exists():
                with _gzip.open(path, "rt") as f:
                    matches = _json.load(f)
                existing_ids = set()
                ids = [m["id"] for m in matches if m.get("id")]
                for i in range(0, len(ids), 5000):
                    async for doc in db.validation_matches.find({"id": {"$in": ids[i:i+5000]}}, {"_id": 0, "id": 1}):
                        existing_ids.add(doc["id"])
                new = [m for m in matches if m.get("id") and m["id"] not in existing_ids]
                if new:
                    for i in range(0, len(new), 5000):
                        await db.validation_matches.insert_many(new[i:i+5000])
                await db.settings.update_one(
                    {"key": "experiment_seed_v5b"},
                    {"$set": {"key": "experiment_seed_v5b", "done": True, "imported": len(new)}},
                    upsert=True,
                )
                logger.info(f"Match seed v5: {len(new)} new (of {len(matches)}, {len(existing_ids)} existed)")

        # --- Deep-dive seed (v6) ---
        flag6 = await db.settings.find_one({"key": "experiment_seed_v6b"}, {"_id": 0})
        if not (flag6 and flag6.get("done")):
            from pathlib import Path
            import json as _json, gzip as _gzip
            path = Path("/app/backend/data/experiment_seed/deep_dive_data.json.gz")
            if path.exists():
                with _gzip.open(path, "rt") as f:
                    bundle = _json.load(f)
                imported = 0

                # Settings docs (deeper_dive_experiment, progress, etc.)
                for doc in bundle.get("settings", []):
                    key = doc.get("key")
                    if key:
                        existing = await db.settings.find_one({"key": key}, {"_id": 0, "key": 1})
                        if not existing:
                            await db.settings.insert_one(doc)
                            imported += 1

                # Replay collections
                for coll_name, docs in bundle.get("replay_collections", {}).items():
                    existing_count = await db[coll_name].count_documents({})
                    if existing_count == 0 and docs:
                        await db[coll_name].insert_many(docs)
                        imported += len(docs)
                        logger.info(f"  {coll_name}: {len(docs)} docs")

                # Deep dive matches (skip existing)
                dd_matches = bundle.get("deep_dive_matches", [])
                if dd_matches:
                    existing_ids = set()
                    ids = [m["id"] for m in dd_matches if m.get("id")]
                    for i in range(0, len(ids), 5000):
                        async for doc in db.validation_matches.find({"id": {"$in": ids[i:i+5000]}}, {"_id": 0, "id": 1}):
                            existing_ids.add(doc["id"])
                    new_dd = [m for m in dd_matches if m.get("id") and m["id"] not in existing_ids]
                    if new_dd:
                        for i in range(0, len(new_dd), 5000):
                            await db.validation_matches.insert_many(new_dd[i:i+5000])
                    imported += len(new_dd)
                    logger.info(f"  deep_dive matches: {len(new_dd)} new ({len(existing_ids)} existed)")

                await db.settings.update_one(
                    {"key": "experiment_seed_v6b"},
                    {"$set": {"key": "experiment_seed_v6b", "done": True, "imported": imported}},
                    upsert=True,
                )
                logger.info(f"Deep-dive seed v6: {imported} total items imported")

        # --- CSB paper summaries seed (v7) ---
        flag7 = await db.settings.find_one({"key": "experiment_seed_v7b"}, {"_id": 0})
        if not (flag7 and flag7.get("done")):
            path7 = Path("/app/backend/data/experiment_seed/csb_paper_summaries.json.gz")
            if path7.exists():
                with _gzip.open(path7, "rt") as f:
                    csb_papers = _json.load(f)
                updated = 0
                for p in csb_papers:
                    fields = {}
                    for fld in ["ai_impact_summary_opus46", "ai_impact_summary_gpt", "ai_impact_summary_gemini"]:
                        if p.get(fld):
                            fields[fld] = p[fld]
                    if fields:
                        r = await db.validation_papers.update_one({"id": p["id"]}, {"$set": fields})
                        if r.modified_count > 0:
                            updated += 1
                await db.settings.update_one(
                    {"key": "experiment_seed_v7b"},
                    {"$set": {"key": "experiment_seed_v7b", "done": True, "imported": updated}},
                    upsert=True,
                )
                logger.info(f"CSB paper summaries seed v7: {updated} updated (of {len(csb_papers)})")
    except Exception as e:
        logger.warning(f"Seed import failed: {e}")


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
        # Pre-populate the /datasets endpoint cache so the first request is instant
        from routers.validation import list_datasets
        await list_datasets()
        logger.info("Validation cache pre-warmed")
    except Exception as e:
        logger.warning(f"Validation cache prewarm failed: {e}")




@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
