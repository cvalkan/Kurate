from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import os
import sys
import signal
import time as _time
import asyncio
from datetime import datetime, timezone
from collections import defaultdict
from core.config import db, logger

# --- Restart diagnostics: track uptime and shutdown reason ---
_server_start_time = _time.monotonic()
_shutdown_reason = "unknown"
_pod_id = f"pod-{os.getpid()}"  # Will be updated with leader election ID once scheduler starts


def _sync_log_shutdown(sig_name: str):
    """Write shutdown event to MongoDB SYNCHRONOUSLY using pymongo.
    Must complete before the process dies — no async, no event loop dependency."""
    uptime_s = _time.monotonic() - _server_start_time
    uptime_min = uptime_s / 60
    try:
        from pymongo import MongoClient
        from core.memlog import _pod_role
        sync_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        sc = MongoClient(sync_url, serverSelectionTimeoutMS=2000)
        sc[os.environ.get("DB_NAME", "papersumo")].system_logs.insert_one({
            "ts": datetime.now(timezone.utc),
            "level": "event",
            "event": "shutdown_signal",
            "label": f"Received {sig_name}",
            "signal": sig_name,
            "uptime_seconds": round(uptime_s),
            "uptime_minutes": round(uptime_min, 1),
            "pod_id": _pod_id,
            "pod_role": _pod_role,
            "argv": sys.argv,
            "pid": os.getpid(),
        })
        sc.close()
    except Exception:
        pass


def _sigterm_handler(signum, frame):
    """Synchronous SIGTERM handler — runs immediately when signal is received,
    BEFORE supervisor or any other layer can kill the process."""
    global _shutdown_reason
    sig_name = signal.Signals(signum).name
    _shutdown_reason = sig_name
    uptime_s = _time.monotonic() - _server_start_time
    logger.warning(f"[SHUTDOWN] Received {sig_name} after {uptime_s/60:.1f}min uptime. pod={_pod_id}")
    _sync_log_shutdown(sig_name)
    # Re-raise to let uvicorn handle graceful shutdown
    raise SystemExit(0)


# Install IMMEDIATELY at import time — before uvicorn, before asyncio.
# This ensures we catch SIGTERM even if the event loop hasn't started yet.
signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


def _install_signal_handlers():
    """Re-install signal handlers via asyncio loop.add_signal_handler.
    asyncio handlers take precedence over signal.signal() ones.
    Called after uvicorn starts so we can also trigger graceful ASGI shutdown."""
    global _server_start_time
    _server_start_time = _time.monotonic()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[STARTUP] No running event loop — asyncio signal handlers not installed")
        return

    def _make_exit_handler(sig_enum):
        def _handler():
            global _shutdown_reason
            sig_name = sig_enum.name
            _shutdown_reason = sig_name
            logger.warning(f"[SHUTDOWN] Received {sig_name} (async handler). pod={_pod_id}")
            _sync_log_shutdown(sig_name)
            from uvicorn import Server
            Server.should_exit = True
        return _handler

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _make_exit_handler(sig))
            logger.info(f"[STARTUP] Signal handler installed for {sig.name}")
        except Exception as e:
            logger.warning(f"[STARTUP] Failed to install {sig.name} handler: {e}")

SITE_URL = os.environ.get("SITE_URL", "")
from routers.leaderboard import router as leaderboard_router
from routers.admin import router as admin_router
from routers.outreach import router as outreach_router
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
from routers.email_outreach import router as email_outreach_router
from routers.email_outreach import unsubscribe_router
from routers.db_explorer import router as db_explorer_router
from routers.defi import router as defi_router
from routers.bookmarks import router as bookmarks_router
from routers.reading_lists import router as reading_lists_router
from routers.sync import router as sync_router
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

@app.get("/api/logo-compare", response_class=HTMLResponse)
async def logo_compare():
    import pathlib
    p = pathlib.Path(__file__).parent / "logo_compare.html"
    if p.exists():
        return HTMLResponse(content=p.read_text())
    return HTMLResponse(content="<h1>Not found</h1>")


app.include_router(leaderboard_router)
app.include_router(admin_router)
app.include_router(outreach_router)
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
app.include_router(email_outreach_router)
app.include_router(unsubscribe_router)
app.include_router(db_explorer_router)
app.include_router(defi_router)
app.include_router(bookmarks_router)
app.include_router(sync_router)
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
    # (allow_origins=["*"] + allow_credentials=True is invalid per CORS spec,
    #  but allow_origin_regex echoes the actual origin, which is valid)
    allow_origins=[] if _cors_allow_all else _cors_raw.split(","),
    allow_origin_regex=".*" if _cors_allow_all else None,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress responses >500 bytes (JSON payloads shrink 5-7×)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.get("/api/health")
@app.get("/health")
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
    # Restore PKCE code_verifier if it was stored during auth URL generation
    if state_doc.get("code_verifier"):
        flow.code_verifier = state_doc["code_verifier"]
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


# --- SEO: Server-side meta tags for paper pages ---
# Crawlers (Googlebot, etc.) get paper-specific meta tags.


@app.on_event("startup")
async def startup():
    app.state.prewarm_status = {"done": False, "step": "Loading caches"}

    # --- Startup diagnostics: log how we were launched ---
    logger.info(f"[STARTUP] PID={os.getpid()}, argv={sys.argv}")
    _has_reload = "--reload" in sys.argv
    if _has_reload:
        logger.warning("[STARTUP] ⚠ Running with --reload! This causes periodic restarts via file watcher.")

    # Install signal handlers NOW — after uvicorn has set up its own,
    # so we can chain to them for proper graceful shutdown.
    _install_signal_handlers()

    # Remove --reload from supervisor config if present.
    # The platform generates the config with --reload (a dev-only feature) which causes
    # restart storms on deploy and doubled RSS during restarts → OOM kills.
    # Strategy: (1) try to patch config file, (2) if that fails, re-exec without --reload.
    try:
        import subprocess
        _patched = False
        # Production uses /app/etc/..., preview uses /etc/...
        for conf_path in ["/app/etc/supervisor/conf.d/supervisord.conf", "/etc/supervisor/conf.d/supervisord.conf"]:
            try:
                with open(conf_path) as f:
                    conf = f.read()
            except FileNotFoundError:
                continue
            if "--reload" in conf:
                try:
                    with open(conf_path, "w") as f:
                        f.write(conf.replace(" --reload", ""))
                    subprocess.run(["supervisorctl", "reread"], capture_output=True, timeout=5)
                    logger.info(f"Patched out --reload from {conf_path} — exiting for clean restart")
                    _patched = True
                    sys.exit(0)  # Let supervisor restart us WITHOUT --reload
                except PermissionError:
                    logger.warning(f"Config file {conf_path} is read-only, cannot patch out --reload")
                except SystemExit:
                    raise
            break  # Found config, no need to check other paths

        # Fallback: if config couldn't be patched but we detect --reload in argv,
        # re-exec ourselves without it. This prevents uvicorn's file watcher from
        # causing periodic restarts.
        if not _patched and _has_reload:
            clean_argv = [a for a in sys.argv if a != "--reload"]
            logger.warning(f"[STARTUP] Re-execing without --reload: {clean_argv}")
            # Persist diagnostic to MongoDB before re-exec
            try:
                from pymongo import MongoClient
                sync_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
                sc = MongoClient(sync_url, serverSelectionTimeoutMS=2000)
                sc[os.environ.get("DB_NAME", "papersumo")].system_logs.insert_one({
                    "ts": datetime.now(timezone.utc),
                    "level": "event",
                    "event": "reload_reexec",
                    "label": "Re-execing to remove --reload",
                    "original_argv": sys.argv,
                    "clean_argv": clean_argv,
                    "pid": os.getpid(),
                })
                sc.close()
            except Exception:
                pass
            os.execv(sys.executable, [sys.executable] + clean_argv)
    except SystemExit:
        raise  # Don't catch sys.exit
    except Exception as e:
        logger.warning(f"Supervisor config patch failed: {e}")

    # Cap MongoDB WiredTiger cache to prevent OOM kills in 2GB container.
    # Default is 50% of system RAM (~3.5GB) which leaves no room for Python.
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        admin_db = db.client.admin
        await admin_db.command({"setParameter": 1, "wiredTigerEngineRuntimeConfig": "cache_size=384M"})
        logger.info("MongoDB WiredTiger cache capped to 384MB")
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
    
    # Start scheduler loops immediately (don't depend on _deferred_startup completing)
    try:
        await start_scheduler()
        log_mem("Scheduler started")
    except Exception as e:
        logger.error(f"start_scheduler failed: {e}")
    
    # Set pod_id for memory/event logging after scheduler assigns leader ID
    try:
        from services.scheduler import _leader_id, _is_leader
        global _pod_id
        _pod_id = _leader_id
        from core.memlog import set_pod_id, set_pod_role
        set_pod_id(_leader_id)
        set_pod_role("leader" if _is_leader else "follower")
        logger.info(f"[STARTUP] pod_id={_leader_id}, role={'leader' if _is_leader else 'follower'}")
    except Exception as e:
        logger.warning(f"[STARTUP] Failed to set pod_id: {e}")

    logger.info("Kurate.org Leaderboard started")

    # Log startup event with build fingerprint to distinguish deploys from restarts
    # This runs AFTER role assignment so pod_role is available
    try:
        import hashlib, glob
        _build_files = sorted(glob.glob("/app/backend/**/*.py", recursive=True))[:50]
        _build_hash = hashlib.md5("".join(open(f).read()[:200] for f in _build_files if os.path.isfile(f)).encode()).hexdigest()[:12]
        _prev_hash = await db.system_logs.find_one(
            {"event": "server_started", "build_hash": {"$exists": True}},
            sort=[("ts", -1)], projection={"_id": 0, "build_hash": 1},
        )
        _is_deploy = not _prev_hash or _prev_hash.get("build_hash") != _build_hash
        from core.memlog import _pod_role
        await db.system_logs.insert_one({
            "ts": datetime.now(timezone.utc),
            "level": "event",
            "event": "server_started",
            "label": "Deploy" if _is_deploy else "Restart",
            "build_hash": _build_hash,
            "is_deploy": _is_deploy,
            "pod_id": _pod_id,
            "pod_role": _pod_role,
            "pid": os.getpid(),
        })
        logger.info(f"[STARTUP] {'DEPLOY (new code)' if _is_deploy else 'RESTART (same code)'} build={_build_hash} role={_pod_role}")
    except Exception as e:
        logger.warning(f"[STARTUP] Build fingerprint failed: {e}")

    log_mem("Server started")



async def _retry_missing_summaries():
    """Retry pre-comparison summary generation for papers missing the required summary.

    Queries the papers collection (NOT rankings) for all papers in active
    categories that lack the required summary key. Delegates to
    _generate_paper_summaries — the same function the fetch cycle uses for
    pre-comparison summaries used by the comparison pipeline.

    Runs once on startup after a short delay. The scheduler's regular fetch
    cycle handles ongoing generation for new papers.
    """
    await asyncio.sleep(60)  # Wait for scheduler and settings to be ready
    from core.memlog import log_mem
    from services.scheduler import (
        _pick_summary_source, _summary_model_key, _SUMMARY_KEY_FALLBACKS,
        _generate_paper_summaries,
    )

    try:
        settings = await db.settings.find_one({"key": "global"}) or {}
        active_cats = settings.get("active_categories", [])
        summary_model = _pick_summary_source(settings.get("summary_source", "thinking"))
        required_key = _summary_model_key(summary_model)
        fallback_keys = _SUMMARY_KEY_FALLBACKS.get(required_key, [])
        all_keys = [required_key] + fallback_keys

        # Find papers in active categories missing the required summary
        total_missing = 0
        cats_with_missing = []
        for cat in active_cats:
            summary_filter = {"$or": [{f"summaries.{k}": {"$exists": True}} for k in all_keys]}
            summary_filter["categories.0"] = cat
            total_with = await db.papers.count_documents(summary_filter)
            total_all = await db.papers.count_documents({"categories.0": cat})
            missing = total_all - total_with
            if missing > 0:
                total_missing += missing
                cats_with_missing.append(cat)
                logger.info(f"[retry-summaries] {cat}: {missing} of {total_all} papers missing {required_key} summary")

        if total_missing == 0:
            log_mem("[retry-summaries] All papers have required summaries")
            return

        log_mem(f"[retry-summaries] {total_missing} papers need summaries, generating...")

        # Use the pre-comparison summary generation pipeline
        for cat in cats_with_missing:
            try:
                await _generate_paper_summaries(category=cat)
            except Exception as e:
                logger.warning(f"[retry-summaries] {cat} failed: {e}")

        log_mem("[retry-summaries] Done")
        from core.memlog import force_gc
        force_gc("[retry-summaries] cleanup")
    except Exception as e:
        import traceback
        logger.error(f"[retry-summaries] CRASHED: {e}")
        from core.memlog import log_mem as _lm
        _lm(f"[retry-summaries] CRASHED: {traceback.format_exc()[-200:]}")



async def _deferred_startup():
    """Heavy startup work that runs in background after health endpoint is available."""
    await asyncio.sleep(0.1)  # Yield to let server start accepting connections
    from core.memlog import log_mem, force_gc

    log_mem("_deferred_startup: begin")

    # Ensure Playwright Chromium is installed (needed for badge rendering)
    try:
        import subprocess, os as _os, glob as _glob
        pw_path = _os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")
        if not _glob.glob(f"{pw_path}/chromium*"):
            logger.info("Installing Playwright Chromium browsers...")
            result = subprocess.run(
                ["python3", "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=120,
                env={**_os.environ, "PLAYWRIGHT_BROWSERS_PATH": pw_path},
            )
            if result.returncode == 0:
                logger.info(f"Playwright Chromium installed at {pw_path}")
            else:
                logger.warning(f"Playwright install failed: {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"Playwright install skipped: {e}")

    # Create remaining indexes
    try:
        await db.papers.create_index("arxiv_id", unique=True, sparse=True)
        await db.papers.create_index("chemrxiv_id", unique=True, sparse=True)
        await db.papers.create_index("published")
        await db.papers.create_index([("categories", 1), ("summaries", 1)], name="categories_summaries")
        await db.papers.create_index("categories.0", name="primary_category")
        await db.papers.create_index("arxiv_id_base", name="arxiv_id_base", sparse=True)
        await db.matches.create_index("paper1_id")
        await db.matches.create_index("paper2_id")
        await db.matches.create_index("shared_categories")
        await db.matches.create_index("primary_category")
        await db.matches.create_index([("primary_category", 1), ("completed", 1), ("created_at", -1)], name="cat_completed_recent")
        await db.matches.create_index([("primary_category", 1), ("completed", 1), ("failed", 1), ("mode", 1)], name="cat_completed_mode")
        await db.matches.create_index("created_at")
        await db.matches.create_index([
            ("primary_category", 1), ("completed", 1), ("failed", 1), ("mode", 1)
        ])
        # Pair dedup index — used by _select_pairs for O(1) repeat-match checks
        await db.matches.create_index([
            ("primary_category", 1), ("dedup_pair", 1)
        ], name="pair_dedup_idx")
        # Ranking filter index — leaderboard queries now filter on
        # is_latest_version to exclude frozen older paper versions.
        try:
            await db.rankings.create_index(
                [("category", 1), ("is_latest_version", 1), ("ts_score", -1)],
                name="rank_cat_latest_ts_idx",
            )
        except Exception as _idx_err:
            logger.warning(f"rank_cat_latest_ts_idx create skipped: {_idx_err}")
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
        # Unique constraint to prevent duplicate archives from multi-pod race conditions
        try:
            await db.leaderboard_archives.create_index(
                [("category", 1), ("period_type", 1), ("scoring_method", 1), ("year", 1), ("week", 1), ("month", 1)],
                unique=True, name="archive_unique"
            )
        except Exception:
            pass  # Index may already exist or conflict with duplicates — dedup handles it
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
        await db.rankings.create_index([("category", 1), ("os_score", -1)], name="category_1_os_score_-1")
        await db.rankings.create_index([("category", 1), ("comparisons", -1)], name="category_1_comparisons_-1")
        await db.rankings.create_index([("category", 1), ("win_rate", -1)], name="category_1_win_rate_-1")
        await db.rankings.create_index([("category", 1), ("title", 1)], name="category_1_title_1")
        await db.rankings.create_index([("ts_score", -1)], name="ts_score_-1")  # Cross-category TS sort
        await db.rankings.create_index([("comparisons", -1)], name="comparisons_-1")
        await db.rankings.create_index([("title", 1)], name="title_1")
        await db.rankings.create_index([("category", 1), ("ts_sigma", 1)], name="category_1_ts_sigma_1")
        await db.rankings.create_index([("category", 1), ("wilson_margin", 1)], name="category_1_wilson_margin_1")
        await db.rankings.create_index([("ts_sigma", 1)], name="ts_sigma_1")
        await db.rankings.create_index([("wilson_margin", 1)], name="wilson_margin_1")
        # Analysis store index (pre-aggregated Model Analysis results)
        # Create index if missing (don't drop — that kills concurrent prewarm tasks)
        try:
            existing = [idx["name"] async for idx in db.analysis_store.list_indexes()]
            if "_type_1_key_1" not in existing:
                # Clean up null-key duplicates that prevent unique index creation on Atlas
                try:
                    async for doc in db.analysis_store.aggregate([
                        {"$match": {"key": None}},
                        {"$group": {"_id": "$_type", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
                        {"$match": {"count": {"$gt": 1}}},
                    ]):
                        to_delete = doc["ids"][1:]
                        if to_delete:
                            await db.analysis_store.delete_many({"_id": {"$in": to_delete}})
                except Exception:
                    pass
                await db.analysis_store.create_index([("_type", 1), ("key", 1)], unique=True)
        except Exception:
            pass
        # Version check removed — analysis cache is ONLY cleared via admin button.
        # No startup, deploy, or restart will ever clear cached model analysis.
        # Convergence cache
        await db.convergence_cache.create_index("category", unique=True)
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")

    log_mem("_deferred_startup: after indexes")

    # Warmup: prime MongoDB query plan cache for paper detail endpoint
    try:
        sample = await db.rankings.find_one({}, {"_id": 0, "paper_id": 1, "category": 1})
        if sample:
            pid, cat = sample["paper_id"], sample["category"]
            await asyncio.gather(
                db.papers.find_one({"id": pid}, {"_id": 0, "title": 1}),
                db.matches.find({"completed": True, "$or": [{"paper1_id": pid}, {"paper2_id": pid}]}, {"_id": 0, "paper1_id": 1}).to_list(1),
                db.rankings.aggregate([{"$match": {"category": cat, "ts_score": {"$exists": True}}}, {"$group": {"_id": None, "min": {"$min": "$ts_score"}, "max": {"$max": "$ts_score"}}}]).to_list(1),
                db.rankings.count_documents({"category": cat}),
            )
            logger.info(f"Query plan warmup complete (cat={cat})")
    except Exception:
        pass

    force_gc()

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

    log_mem("_deferred_startup: after category cleanup")
    force_gc()

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

    # Migration: backfill ts_score for ranking docs missing it, then rerank
    try:
        from services.ranking import SCORE_BASE_CONST, TS_SCALE
        missing_ts = await db.rankings.count_documents(
            {"$or": [{"ts_score": {"$exists": False}}, {"ts_score": None}]}
        )
        if missing_ts > 0:
            # Compute ts_score from ts_mu/ts_sigma (conservative estimate = mu - 3*sigma)
            # If ts_mu is also missing, use defaults (mu=25, sigma=25/3 → score=1200)
            DEFAULT_MU = 25.0
            DEFAULT_SIGMA = DEFAULT_MU / 3
            await db.rankings.update_many(
                {"$or": [{"ts_score": {"$exists": False}}, {"ts_score": None}]},
                [{"$set": {
                    "ts_mu": {"$ifNull": ["$ts_mu", DEFAULT_MU]},
                    "ts_sigma": {"$ifNull": ["$ts_sigma", DEFAULT_SIGMA]},
                    "ts_score": {"$round": [{"$add": [
                        {"$multiply": [
                            {"$subtract": [
                                {"$ifNull": ["$ts_mu", DEFAULT_MU]},
                                {"$multiply": [3, {"$ifNull": ["$ts_sigma", DEFAULT_SIGMA]}]}
                            ]},
                            TS_SCALE
                        ]},
                        SCORE_BASE_CONST
                    ]}, 0]},
                }}],
            )
            logger.info(f"Backfilled ts_score for {missing_ts} ranking docs from ts_mu/ts_sigma")
            # Trigger full rerank to compute proper ranks
            from services.ranking import rerank_category_light
            for cat in await db.rankings.distinct("category"):
                try:
                    await rerank_category_light(db, cat)
                except Exception as re:
                    logger.warning(f"Rerank {cat} after backfill failed: {re}")
    except Exception as e:
        logger.warning(f"ts_score backfill warning: {e}")

    # Migration: ensure ts_mu/ts_sigma exist on all rankings (some have ts_score but missing raw params)
    try:
        DEFAULT_MU = 25.0
        DEFAULT_SIGMA = DEFAULT_MU / 3
        missing_mu = await db.rankings.count_documents(
            {"$or": [{"ts_mu": {"$exists": False}}, {"ts_mu": None}]}
        )
        if missing_mu > 0:
            await db.rankings.update_many(
                {"$or": [{"ts_mu": {"$exists": False}}, {"ts_mu": None}]},
                {"$set": {"ts_mu": DEFAULT_MU, "ts_sigma": DEFAULT_SIGMA}},
            )
            logger.info(f"Backfilled ts_mu/ts_sigma defaults for {missing_mu} ranking docs")
    except Exception as e:
        logger.warning(f"ts_mu/ts_sigma backfill warning: {e}")

    # Migration: backfill ai_rating into existing archive entries that are missing it.
    # ai_rating is static (derived from paper content) so copying current values is safe.
    # For gap_score, use the admin backfill endpoint (scripts/backfill_archive_scores.py)
    # which replays matches chronologically for historically accurate values.
    try:
        rating_map = {}  # paper_id -> ai_rating
        async for r in db.rankings.find(
            {"ai_rating": {"$exists": True, "$ne": None}},
            {"_id": 0, "paper_id": 1, "ai_rating": 1}
        ):
            rating_map[r["paper_id"]] = r["ai_rating"]

        if rating_map:
            patched_archives = 0
            async for archive in db.leaderboard_archives.find({}, {"_id": 1, "leaderboard": 1}):
                lb = archive.get("leaderboard", [])
                changed = False
                for entry in lb:
                    pid = entry.get("id")
                    if pid and pid in rating_map and not entry.get("ai_rating"):
                        entry["ai_rating"] = rating_map[pid]
                        changed = True
                if changed:
                    await db.leaderboard_archives.update_one(
                        {"_id": archive["_id"]},
                        {"$set": {"leaderboard": lb}}
                    )
                    patched_archives += 1
            if patched_archives:
                logger.info(f"Backfilled ai_rating into {patched_archives} archives")
    except Exception as e:
        logger.warning(f"Archive ai_rating backfill warning: {e}")


    # Migration: update settings for new convergence-based architecture
    try:
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
            # Remove max_matches_per_paper cap — convergence is controlled by CI targets
            if _settings_doc.get("max_matches_per_paper") is not None:
                await db.settings.update_one({"key": "global"}, {"$unset": {"max_matches_per_paper": ""}})
                logger.info("Removed max_matches_per_paper cap")
            if migration_updates:
                await db.settings.update_one({"key": "global"}, {"$set": migration_updates})
                logger.info(f"Migrated settings: {list(migration_updates.keys())}")
    except Exception as e:
        logger.warning(f"Settings migration warning: {e}")

    # Initialize tournament registry from CATEGORIES
    try:
        from services.scheduler import init_tournament_registry
        await init_tournament_registry()
    except Exception as e:
        logger.warning(f"Tournament registry init warning: {e}")

    # NOTE: SI rating backfill removed Apr 9, 2026.
    # Was a one-time migration that loaded ALL paper summaries (~90 MB) on every startup.
    # All papers now have ai_ratings_by_model populated during summary generation.

    log_mem("_deferred_startup: after migrations")
    force_gc()

    # Import within-tier experiment matches if missing from this DB.
    # These were generated on preview and are needed for the fixed benchmark to
    # produce correct results (~6,800 pairs) on live recomputation.
    try:
        from pathlib import Path
        exp_file = Path(__file__).parent / "data" / "precomputed" / "within_tier_experiment_matches.json"
        if exp_file.exists():
            existing = await db.validation_matches.count_documents({
                "experiment_tag": {"$exists": True},
                "content_mode": "abstract_plus_summary:thinking",
            })
            if existing == 0:
                import json as _json
                with open(exp_file) as f:
                    exp_matches = _json.load(f)
                if exp_matches:
                    await db.validation_matches.insert_many(exp_matches, ordered=False)
                    logger.info(f"Imported {len(exp_matches)} within-tier experiment matches")
            else:
                logger.info(f"Within-tier experiment matches already present ({existing})")
    except Exception as e:
        logger.warning(f"Experiment match import warning: {e}")

    log_mem("_deferred_startup: complete")

    # Phase 8: Scoring simplification migration (one-time)
    # Overwrites score=ts_score, ci=wilson_margin, removes rank_wr/rank_os
    try:
        migration_done = await db.settings.find_one({"key": "migration_scoring_simplification"})
        if not migration_done:
            _mig_count = await db.rankings.count_documents({"rank_wr": {"$exists": True}})
            if _mig_count > 0:
                # 1. Overwrite score with ts_score
                await db.rankings.update_many(
                    {"ts_score": {"$exists": True}},
                    [{"$set": {"score": "$ts_score"}}],
                )
                # 2. Overwrite ci with wilson_margin
                await db.rankings.update_many(
                    {"wilson_margin": {"$exists": True}},
                    [{"$set": {"ci": "$wilson_margin"}}],
                )
                # 3. Remove dead fields
                await db.rankings.update_many({}, {"$unset": {"rank_wr": "", "rank_os": ""}})
                logger.info(f"Scoring simplification migration: updated {_mig_count} ranking docs")
            await db.settings.update_one(
                {"key": "migration_scoring_simplification"},
                {"$set": {"key": "migration_scoring_simplification", "done_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
    except Exception as e:
        logger.warning(f"Scoring simplification migration warning: {e}")

    # Migration: backfill archive CI from Wilson % to sigma-derived ±Elo
    try:
        _ci_mig = await db.settings.find_one({"key": "migration_archive_ci_sigma_v2"})
        if not _ci_mig:
            patched = 0
            async for archive in db.leaderboard_archives.find({}, {"_id": 1, "leaderboard": 1}):
                lb = archive.get("leaderboard", [])
                changed = False
                for entry in lb:
                    ts_sigma = entry.get("ts_sigma")
                    if ts_sigma is not None:
                        new_ci = round(ts_sigma * 2 * 10, 0)
                        if entry.get("ci") != new_ci:
                            entry["ci"] = new_ci
                            changed = True
                if changed:
                    await db.leaderboard_archives.update_one(
                        {"_id": archive["_id"]},
                        {"$set": {"leaderboard": lb}},
                    )
                    patched += 1
            if patched:
                logger.info(f"Archive CI backfill: patched {patched} archives (Wilson→sigma ±Elo)")
            await db.settings.update_one(
                {"key": "migration_archive_ci_sigma_v2"},
                {"$set": {"key": "migration_archive_ci_sigma_v2", "done_at": datetime.now(timezone.utc).isoformat(), "patched": patched}},
                upsert=True,
            )
    except Exception as e:
        logger.warning(f"Archive CI backfill warning: {e}")

    # Determine pod role for gating leader-only tasks
    from services.scheduler import _is_leader as _pod_is_leader

    # Start background cache refresh loop — needed by ALL pods for serving HTTP
    from routers.leaderboard import start_cache_bg
    start_cache_bg(is_leader=_pod_is_leader)

    # Start background All Categories model analysis refresh (keeps correlation page fast)
    # Both pods need this for serving the validation/model-analysis pages
    from services.model_analysis import _bg_refresh_all_categories
    asyncio.create_task(_bg_refresh_all_categories())

    if _pod_is_leader:
        # --- LEADER-ONLY tasks: summaries, dedup, backfill, archiving ---
        asyncio.create_task(_retry_missing_summaries())
        asyncio.create_task(_staggered_startup_tasks())
        log_mem("_deferred_startup: all tasks launched (LEADER)")
    else:
        # --- FOLLOWER: lightweight prewarms only, plus periodic GC ---
        asyncio.create_task(_follower_lightweight_startup())
        log_mem("_deferred_startup: lightweight startup (FOLLOWER)")

    force_gc()
    logger.info(f"Deferred startup complete — role={'LEADER' if _pod_is_leader else 'FOLLOWER'}")


async def _follower_lightweight_startup():
    """Follower-only startup: read-only prewarms + periodic GC.
    
    The follower serves HTTP traffic, so it needs cache prewarms.
    It does NOT need: retry summaries, dedup, seed, backfill, archive creation.
    It also lacks the periodic GC the leader gets from comparison loops.
    """
    from core.memlog import log_mem, force_gc
    
    log_mem("Follower lightweight startup begin")
    
    _g = globals()
    for _name in ["_prewarm_extraction_cache", "_prewarm_validation_cache", "_prewarm_all_experiment_caches"]:
        _fn = _g.get(_name)
        if _fn:
            asyncio.create_task(_fn())
    
    asyncio.create_task(_prewarm_summary_bias_caches())
    asyncio.create_task(_prewarm_summarizer_ratings())
    
    await asyncio.sleep(10)
    force_gc("follower lightweight startup complete")
    log_mem("Follower lightweight startup done")
    
    # Periodic GC — leader gets GC between comparison rounds, follower doesn't
    asyncio.create_task(_follower_periodic_gc())


async def _follower_periodic_gc():
    """Periodic GC for follower pod to prevent memory creep."""
    from core.memlog import force_gc
    await asyncio.sleep(120)
    while True:
        force_gc("follower periodic")
        await asyncio.sleep(300)


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
        "_startup_dedup_archives",
        "_startup_backfill_dedup_pair",
        "_startup_fix_dotted_model_keys",
        "_startup_seed_rankings",
        "_startup_backfill_unique_opponents",
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

    # OpenSkill caches are only refreshed via admin buttons — no auto-prewarm on startup.
    # Summary bias caches are lightweight and safe to prewarm.
    asyncio.create_task(_prewarm_summary_bias_caches())
    asyncio.create_task(_prewarm_summarizer_ratings())

    # Final GC after all startup tasks — critical for follower pod which
    # won't run scheduler loops that trigger periodic GC
    await asyncio.sleep(5)
    force_gc("staggered startup complete")



async def _prewarm_all_experiment_caches():
    """Load ALL validation data from precomputed JSON files. No computation.
    
    If data isn't in the JSON files, endpoints return 'no_data'.
    To update: run admin precompute-experiments on preview, deploy the new JSON files.
    """
    await asyncio.sleep(3)
    logger.info("All experiment caches loaded from precomputed JSON (no computation)")
    app.state.prewarm_status = {"done": True, "step": ""}


async def _prewarm_summarizer_ratings():
    """Prewarm summarizer rating distributions cache on startup."""
    await asyncio.sleep(5)
    try:
        from routers.si_benchmark import _compute_summarizer_ratings, _summarizer_rating_cache
        result = await _compute_summarizer_ratings()
        _summarizer_rating_cache["data"] = result
        n_models = len(result.get("models", []))
        logger.info(f"Summarizer rating cache warmed ({n_models} models)")
    except Exception as e:
        logger.warning(f"Summarizer rating prewarm failed: {e}")


async def _prewarm_summary_bias_caches():
    """Pre-warm summary bias caches (lightweight, no match replay)."""
    await asyncio.sleep(15)
    try:
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
        logger.warning(f"Summary bias cache prewarm failed: {e}")



async def _startup_dedup_archives():
    """Remove duplicate archive snapshots caused by multi-pod race conditions.
    Keeps the first (oldest) document for each (category, period_type, scoring_method, year, week, month) combo."""
    flag = await db.settings.find_one({"key": "dedup_archives_v1"}, {"_id": 0})
    if flag and flag.get("done"):
        return

    pipeline = [
        {"$group": {
            "_id": {"category": "$category", "period_type": "$period_type", "scoring_method": "$scoring_method",
                    "year": "$year", "week": "$week", "month": "$month"},
            "count": {"$sum": 1},
            "ids": {"$push": "$_id"},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    removed = 0
    async for group in db.leaderboard_archives.aggregate(pipeline):
        # Keep the first, delete the rest
        ids_to_delete = group["ids"][1:]
        if ids_to_delete:
            await db.leaderboard_archives.delete_many({"_id": {"$in": ids_to_delete}})
            removed += len(ids_to_delete)

    if removed:
        logger.info(f"Archive dedup: removed {removed} duplicate snapshots")

    await db.settings.update_one(
        {"key": "dedup_archives_v1"},
        {"$set": {"key": "dedup_archives_v1", "done": True, "removed": removed}},
        upsert=True,
    )


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




async def _startup_backfill_dedup_pair():
    """One-time migration: add dedup_pair field to existing matches for O(1) repeat-match checks."""
    flag = await db.settings.find_one({"key": "dedup_pair_backfill_v1"}, {"_id": 0})
    if flag and flag.get("done"):
        return

    missing = await db.matches.count_documents({"dedup_pair": {"$exists": False}})
    if missing == 0:
        await db.settings.update_one(
            {"key": "dedup_pair_backfill_v1"},
            {"$set": {"key": "dedup_pair_backfill_v1", "done": True, "backfilled": 0}},
            upsert=True,
        )
        return

    logger.info(f"Backfilling dedup_pair for {missing} matches...")
    backfilled = 0
    async for m in db.matches.find(
        {"dedup_pair": {"$exists": False}},
        {"_id": 1, "paper1_id": 1, "paper2_id": 1},
    ):
        p1, p2 = m["paper1_id"], m["paper2_id"]
        a, b = (p1, p2) if p1 < p2 else (p2, p1)
        await db.matches.update_one(
            {"_id": m["_id"]},
            {"$set": {"dedup_pair": f"{a}|{b}"}},
        )
        backfilled += 1
        if backfilled % 5000 == 0:
            logger.info(f"  dedup_pair backfill: {backfilled}/{missing}")

    await db.settings.update_one(
        {"key": "dedup_pair_backfill_v1"},
        {"$set": {"key": "dedup_pair_backfill_v1", "done": True, "backfilled": backfilled}},
        upsert=True,
    )
    logger.info(f"Backfilled dedup_pair for {backfilled} matches")



async def _startup_fix_dotted_model_keys():
    """One-time migration: replace dots in model_stats/model_ts keys in rankings.
    
    MongoDB interprets dots in $inc paths as nested objects. Old incremental writes
    created broken nested keys like {"openai/gpt-5": {"2": {"total": N}}}.
    This migration flattens everything to underscore keys: "openai/gpt-5_2".
    After this, no normalizer code is needed when reading model_stats/model_ts.
    """
    flag = await db.settings.find_one({"key": "fix_dotted_model_keys_v1"}, {"_id": 0})
    if flag and flag.get("done"):
        return

    fixed = 0
    async for doc in db.rankings.find(
        {"model_stats": {"$exists": True}},
        {"_id": 1, "model_stats": 1, "model_ts": 1},
    ):
        new_ms = {}
        changed = False
        for mk, stats in (doc.get("model_stats") or {}).items():
            if isinstance(stats, dict) and stats.get("total") is not None:
                # Flat key — just normalize dots
                safe = mk.replace(".", "_")
                if safe in new_ms:
                    new_ms[safe] = {"total": new_ms[safe]["total"] + stats.get("total", 0),
                                    "wins": new_ms[safe]["wins"] + stats.get("wins", 0)}
                else:
                    new_ms[safe] = {"total": stats.get("total", 0), "wins": stats.get("wins", 0)}
                if safe != mk:
                    changed = True
            elif isinstance(stats, dict):
                # Broken nested key — reconstruct and flatten
                for sub_key, sub_val in stats.items():
                    if isinstance(sub_val, dict) and sub_val.get("total") is not None:
                        safe = f"{mk}.{sub_key}".replace(".", "_")
                        if safe in new_ms:
                            new_ms[safe] = {"total": new_ms[safe]["total"] + sub_val.get("total", 0),
                                            "wins": new_ms[safe]["wins"] + sub_val.get("wins", 0)}
                        else:
                            new_ms[safe] = {"total": sub_val.get("total", 0), "wins": sub_val.get("wins", 0)}
                        changed = True

        new_mts = {}
        for mk, ts in (doc.get("model_ts") or {}).items():
            if isinstance(ts, dict) and ts.get("mu") is not None:
                safe = mk.replace(".", "_")
                new_mts[safe] = ts
                if safe != mk:
                    changed = True
            elif isinstance(ts, dict):
                for sub_key, sub_val in ts.items():
                    if isinstance(sub_val, dict) and sub_val.get("mu") is not None:
                        safe = f"{mk}.{sub_key}".replace(".", "_")
                        new_mts[safe] = sub_val
                        changed = True

        if changed:
            update = {"model_stats": new_ms}
            if new_mts:
                update["model_ts"] = new_mts
            await db.rankings.update_one({"_id": doc["_id"]}, {"$set": update})
            fixed += 1

    await db.settings.update_one(
        {"key": "fix_dotted_model_keys_v1"},
        {"$set": {"key": "fix_dotted_model_keys_v1", "done": True, "fixed": fixed}},
        upsert=True,
    )
    if fixed:
        logger.info(f"Fixed dotted model keys in {fixed} ranking documents")




async def _startup_seed_rankings():
    """Ensure all papers with summaries have ranking entries.
    
    Gap-fill approach: only creates missing ranking entries (no match loading,
    no score recomputation). Scores build up naturally via update_rankings_for_match.
    
    Falls back to full reseed only if rankings collection is completely empty
    (cold start) or >20% of papers are unranked (catastrophic recovery).
    """
    try:
        from services.ranking import seed_rankings, insert_ranking_for_paper
        from core.auth import get_settings
        from core.config import CATEGORIES
        from core.memlog import force_gc

        settings = await get_settings()
        cats = settings.get("active_categories", list(CATEGORIES.keys()))

        rankings_count = await db.rankings.count_documents({})
        papers_count = await db.papers.count_documents({"summaries": {"$exists": True, "$ne": {}}})

        if rankings_count == 0 and papers_count > 0:
            # Cold start: full reseed needed (no rankings exist at all)
            logger.info(f"Cold start: seeding rankings from {papers_count} papers...")
            seeded = await seed_rankings(db)
            logger.info(f"Rankings seeded: {seeded} entries")
            return

        # Gap-fill: find papers with summaries but no ranking entry
        total_filled = 0
        for cat in cats:
            # Get paper IDs that have summaries for this category
            cat_paper_ids = set()
            async for doc in db.papers.find(
                {"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}},
                {"_id": 0, "id": 1},
            ):
                cat_paper_ids.add(doc["id"])

            if not cat_paper_ids:
                continue

            # Get paper IDs that already have rankings
            ranked_ids = set()
            async for doc in db.rankings.find(
                {"category": cat},
                {"_id": 0, "paper_id": 1},
            ):
                ranked_ids.add(doc["paper_id"])

            missing = cat_paper_ids - ranked_ids

            if not missing:
                continue

            # Catastrophic recovery: if >20% unranked, fall back to full reseed
            if len(missing) > len(cat_paper_ids) * 0.2 and len(missing) > 10:
                logger.info(f"[{cat}] {len(missing)}/{len(cat_paper_ids)} unranked (>{20}%) — full reseed")
                await seed_rankings(db, category=cat)
                force_gc()
                total_filled += len(missing)
                continue

            # Normal gap-fill: create blank ranking entries for missing papers
            logger.info(f"[{cat}] Gap-filling {len(missing)} missing ranking entries")
            for pid in missing:
                paper_doc = await db.papers.find_one(
                    {"id": pid},
                    {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                     "link": 1, "published": 1, "added_at": 1, "categories": 1, "ai_rating": 1},
                )
                if paper_doc:
                    await insert_ranking_for_paper(db, paper_doc)
                    total_filled += 1

        if total_filled:
            logger.info(f"Gap-filled {total_filled} ranking entries across {len(cats)} categories")
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
                logger.info(f"Rankings up to date ({rankings_count} entries)")

    except Exception as e:
        logger.warning(f"Rankings startup failed: {e}")



async def _startup_backfill_unique_opponents():
    """Migration: populate unique_opponents field on rankings.
    
    Sets unique_opponents = comparisons (correct with dedup — every match is unique).
    v1 had a bug where the dedup_pair aggregation counted opponents outside the tournament.
    v2 fixes this by using the authoritative comparisons field from rankings.
    """
    flag = await db.settings.find_one({"key": "backfill_unique_opponents_v2"}, {"_id": 0})
    if flag and flag.get("done"):
        return

    # Fix ALL rankings: set unique_opponents = comparisons
    # This is correct because dedup prevents repeat matches, so comparisons = unique opponents.
    result = await db.rankings.update_many(
        {},
        [{"$set": {"unique_opponents": "$comparisons"}}],
    )

    await db.settings.update_one(
        {"key": "backfill_unique_opponents_v2"},
        {"$set": {"key": "backfill_unique_opponents_v2", "done": True, "backfilled": result.modified_count}},
        upsert=True,
    )
    if result.modified_count:
        logger.info(f"Backfilled unique_opponents = comparisons for {result.modified_count} rankings (v2 fix)")



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
    uptime_s = _time.monotonic() - _server_start_time
    uptime_min = uptime_s / 60
    logger.info(f"[SHUTDOWN] Server shutting down after {uptime_min:.1f}min uptime. Reason={_shutdown_reason} pod={_pod_id}")
    # Persist shutdown event for admin visibility
    try:
        await db.system_logs.insert_one({
            "ts": datetime.now(timezone.utc),
            "level": "event",
            "event": "server_shutdown",
            "label": f"Graceful shutdown after {uptime_min:.1f}min",
            "uptime_seconds": round(uptime_s),
            "uptime_minutes": round(uptime_min, 1),
            "reason": _shutdown_reason,
            "pod_id": _pod_id,
            "pid": os.getpid(),
        })
    except Exception:
        pass
    from core.config import client
    client.close()
