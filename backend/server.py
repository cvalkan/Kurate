from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
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
    logger.info("Kurate.org Leaderboard started")


async def _deferred_startup():
    """Heavy startup work that runs in background after health endpoint is available."""
    await asyncio.sleep(0.1)  # Yield to let server start accepting connections

    # Create remaining indexes
    try:
        await db.papers.create_index("arxiv_id", unique=True, sparse=True)
        await db.papers.create_index("chemrxiv_id", unique=True, sparse=True)
        await db.papers.create_index("published")
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
        # Leaderboard archives (weekly/monthly frozen snapshots)
        await db.leaderboard_archives.create_index([("category", 1), ("year", -1), ("week", -1)])
        await db.leaderboard_archives.create_index([("category", 1), ("year", -1), ("month", -1)])
        await db.leaderboard_archives.create_index([("category", 1), ("period_type", 1), ("year", -1)])
        # Summarizer-ab task queue (for auto-resume on restart)
        await db.summarizer_ab_tasks.create_index([("dataset_id", 1), ("summarizer", 1)], unique=True)
        # Author verifications (ORCID claiming)
        await db.author_verifications.create_index("user_id", unique=True)
        await db.author_verifications.create_index("orcid_id")
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
    # Use globals() lookup to avoid NameError during hot-reload (uvicorn --reload
    # can fire the startup event before all module-level functions are defined).
    _bg_tasks = [
        "_prewarm_extraction_cache", "_prewarm_validation_cache",
        "_prewarm_analysis_cache", "_prewarm_all_experiment_caches",
        "_startup_dedup", "_startup_regen_truncated_summaries",
        "_startup_resume_summarizer_ab", "_startup_check_interrupted_tasks",
        "_startup_seed_targeted_matches",
    ]
    _g = globals()
    for _name in _bg_tasks:
        _fn = _g.get(_name)
        if _fn:
            asyncio.create_task(_fn())
        else:
            logger.warning(f"Startup task {_name} not yet defined (hot-reload race)")

    logger.info("Deferred startup complete — all background tasks launched")



async def _prewarm_all_experiment_caches():
    """Single consolidated cache warmer for all validation experiment endpoints.
    
    Strategy (3 layers, each one is a safety net for the next):
      1. Load from precomputed JSON files on disk (instant, covers ~11 experiments + datasets)
      2. Load remaining from MongoDB persistent cache (fast, covers benchmarks + recently computed)
      3. Compute anything still missing from DB (slow, only needed on first deploy or after data changes)
    """
    await asyncio.sleep(3)
    
    # --- Layer 1: Precomputed JSON files (already loaded in startup(), skip) ---

    # --- Layer 2: MongoDB persistent cache for benchmark endpoints ---
    try:
        from routers.human_ai_benchmark import prewarm_benchmark_cache
        await prewarm_benchmark_cache()
    except Exception as e:
        logger.warning(f"Layer 2 (benchmark MongoDB cache) failed: {e}")

    # Also load other MongoDB-cached endpoints
    try:
        from core.cache import get_cached
        from routers.validation_utils import consistency_cache, cycle_all_cache, sumab_results_cache
        from routers.validation_experiments import _judge_comparison_cache, _SINGLE_ITEM_CACHE
        from routers.unified_benchmark import _unified_cache

        mongo_mappings = [
            ("consistency_analysis", consistency_cache),
            ("cycle_analysis_all", cycle_all_cache),
            ("summarizer_ab_results", sumab_results_cache),
            ("judge_comparison_results", _judge_comparison_cache),
            ("single_item_scoring_results", _SINGLE_ITEM_CACHE),
            ("unified_benchmark_comp", None),
            ("unified_benchmark_stan", None),
        ]
        for key, cache in mongo_mappings:
            if cache and cache.get("data"):
                continue  # Already loaded from JSON
            cached = await get_cached(key)
            if cached:
                if cache:
                    cache["data"] = cached
                elif "comp" in key:
                    _unified_cache["comp"] = {"data": cached}
                elif "stan" in key:
                    _unified_cache["stan"] = {"data": cached}
                logger.info(f"Layer 2: Loaded {key} from MongoDB")
    except Exception as e:
        logger.warning(f"Layer 2 (MongoDB cache) failed: {e}")

    # --- Layer 3: Compute anything still missing ---
    try:
        from routers.validation import _compute_consistency_analysis, _compute_cycle_analysis_all
        from routers.validation_experiments import (
            _compute_summarizer_ab_results, _compute_assessor_evaluator,
            _compute_extended_thinking_results, _compute_multi_aspect_results,
            _compute_judge_comparison, _compute_model_correlation_analysis,
            _compute_single_item_results, _SINGLE_ITEM_CACHE,
        )
        from routers.validation_utils import (
            consistency_cache, cycle_all_cache, sumab_results_cache,
            ae_cache, extended_thinking_cache, multi_aspect_cache,
        )
        from routers.validation_experiments import _judge_comparison_cache, _model_correlation_cache
        from core.cache import set_cached
        import time as _t

        all_caches = [
            ("consistency", _compute_consistency_analysis, consistency_cache, "consistency_analysis"),
            ("cycle-all", _compute_cycle_analysis_all, cycle_all_cache, "cycle_analysis_all"),
            ("summarizer-ab", _compute_summarizer_ab_results, sumab_results_cache, "summarizer_ab_results"),
            ("extended-thinking", _compute_extended_thinking_results, extended_thinking_cache, None),
            ("multi-aspect", _compute_multi_aspect_results, multi_aspect_cache, None),
            ("judge-comparison", _compute_judge_comparison, _judge_comparison_cache, "judge_comparison_results"),
            ("assessor-evaluator", _compute_assessor_evaluator, ae_cache, None),
            ("model-correlation", _compute_model_correlation_analysis, _model_correlation_cache, None),
            ("single-item-scoring", _compute_single_item_results, _SINGLE_ITEM_CACHE, "single_item_scoring_results"),
        ]

        missing = [(n, fn, c, mk) for n, fn, c, mk in all_caches if not c.get("data")]
        if not missing:
            logger.info("Layer 3: All experiment caches loaded — nothing to compute")
        else:
            logger.info(f"Layer 3: Computing {len(missing)} missing caches: {[n for n,_,_,_ in missing]}")
            for name, fn, cache, mongo_key in missing:
                try:
                    result = await asyncio.wait_for(fn(), timeout=120)
                    if result.get("status") == "ok":
                        cache["data"] = result
                        cache["ts"] = _t.time()
                        if mongo_key:
                            await set_cached(mongo_key, result)
                        logger.info(f"  {name}: computed + cached")
                    else:
                        logger.info(f"  {name}: status={result.get('status')}")
                    await asyncio.sleep(0.5)
                except asyncio.TimeoutError:
                    logger.warning(f"  {name}: timed out (120s)")
                except Exception as e:
                    logger.warning(f"  {name}: failed — {e}")

        # Also warm unified benchmark if not cached
        from routers.unified_benchmark import _unified_cache, _compute_unified_benchmark
        for gt in ["comp", "stan"]:
            if not _unified_cache.get(gt, {}).get("data"):
                try:
                    result = await asyncio.wait_for(_compute_unified_benchmark(gt), timeout=60)
                    if result.get("status") == "ok":
                        _unified_cache[gt] = {"data": result}
                        await set_cached(f"unified_benchmark_{gt}", result)
                        logger.info(f"  unified-benchmark-{gt}: computed + cached")
                except Exception as e:
                    logger.warning(f"  unified-benchmark-{gt}: failed — {e}")

        logger.info("All experiment caches ready")

        # Also warm admin timeseries (very expensive: 70s+ cold)
        try:
            mongo_key = "admin_timeseries___all__"
            ts_cached = await get_cached(mongo_key)
            if ts_cached:
                from routers.admin import _set_admin_cached
                _set_admin_cached("timeseries", "__all__", ts_cached)
                logger.info("Admin timeseries loaded from MongoDB cache")
            else:
                logger.info("Admin timeseries not cached — will compute on first admin visit")
        except Exception as e:
            logger.warning(f"Admin timeseries prewarm failed: {e}")
    except Exception as e:
        logger.warning(f"Layer 3 (compute missing) failed: {e}")
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


async def _startup_seed_targeted_matches():
    """One-time: import all validation matches and deep-dive data not yet on this database."""
    await asyncio.sleep(10)
    try:
        # --- Match seed (v5) ---
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
        logger.info("Validation cache pre-warmed")

        # Pre-warm result cache for common datasets (background, non-blocking)
        asyncio.create_task(_prewarm_result_cache())
    except Exception as e:
        logger.warning(f"Validation cache prewarm failed: {e}")


async def _prewarm_result_cache():
    """One-time: warm validation result caches for top datasets on startup.
    
    Limited to top 10 datasets by match count to keep startup under 2 minutes.
    Remaining datasets compute lazily on first request.
    """
    await asyncio.sleep(5)
    try:
        from routers.validation import get_pairwise_results, _compute_convergence_and_cache
        pipeline = [
            {"$match": {"completed": True, "failed": {"$ne": True}}},
            {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
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
                await _compute_convergence_and_cache(ds_id, steps=20)
                conv_warmed += 1
            except Exception:
                pass
            await asyncio.sleep(0)
        logger.info(f"Result cache pre-warmed: {warmed} pairwise, {conv_warmed} convergence")
    except Exception as e:
        logger.warning(f"Result cache prewarm failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    from core.config import client
    client.close()
