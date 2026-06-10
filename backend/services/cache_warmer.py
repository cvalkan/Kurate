"""Leaderboard cache warming.

Pre-warms all category × period combinations so every user hits warm cache.
Triggered on:
  - Server startup (after DB connection settles)
  - Data changes (new match, new papers ingested, archive sealed)

Memory: Each HTTP request reads the response but doesn't store it — the cache
lives in the leaderboard router's internal dict, not here. The httpx client
streams responses and discards them after status check.
"""
import asyncio
import time
import httpx
from datetime import datetime, timezone
from core.config import logger, db

_warming = False
_last_warm_at = 0

PERIODS = ["recent", "week", "month", "all"]


async def _log_to_admin(event: str, detail: str, success: bool = True):
    """Write a cache warm event to system_logs for the admin dashboard."""
    try:
        await db.system_logs.insert_one({
            "ts": datetime.now(timezone.utc),
            "event": "cache_warm",
            "level": "event",
            "label": event,
            "detail": detail,
            "success": success,
        })
    except Exception:
        pass

_warming = False
_last_warm_at = 0

PERIODS = ["recent", "week", "month", "all"]


async def warm_leaderboard_cache():
    """Warm all leaderboard cache entries. Safe to call concurrently — deduplicates."""
    global _warming, _last_warm_at

    if _warming:
        logger.debug("Cache warm: already in progress, skipping")
        return
    if time.time() - _last_warm_at < 60:
        logger.debug("Cache warm: warmed <60s ago, skipping")
        return

    _warming = True
    t0 = time.time()
    success = 0
    failed = 0
    errors = []

    try:
        from core.auth import get_settings
        from routers.homepage import clear_homepage_cache
        clear_homepage_cache()
        settings = await get_settings()
        categories = sorted(c for c in (settings.get("active_categories") or []) if c and c.strip())
        total_queries = (len(categories) + 1) * len(PERIODS) + 3
        logger.info(f"Cache warm starting: {len(categories)} categories × {len(PERIODS)} periods + homepage = {total_queries} queries")
        await _log_to_admin("Cache warm started", f"{total_queries} queries ({len(categories)} categories × {len(PERIODS)} periods + homepage)")

        # Single client, reused for all requests. Responses are not stored.
        async with httpx.AsyncClient(base_url="http://localhost:8001", timeout=60) as client:

            async def _warm(url: str, label: str):
                nonlocal success, failed
                try:
                    r = await client.get(url)
                    # Read and discard body to free memory
                    _ = r.status_code
                    if r.status_code == 200:
                        success += 1
                    else:
                        failed += 1
                        errors.append(f"{label}: HTTP {r.status_code}")
                        logger.warning(f"Cache warm {label}: HTTP {r.status_code}")
                except httpx.TimeoutException:
                    failed += 1
                    errors.append(f"{label}: timeout")
                    logger.warning(f"Cache warm {label}: timeout (60s)")
                except Exception as e:
                    failed += 1
                    errors.append(f"{label}: {type(e).__name__}")
                    logger.warning(f"Cache warm {label}: {type(e).__name__}: {e}")

            # 1. All Categories × all periods
            for period in PERIODS:
                await _warm(f"/api/leaderboard?show_all=true&period={period}&limit=50", f"all/{period}")
                await asyncio.sleep(0.5)

            # 2. Each category × all periods
            for cat in categories:
                for period in PERIODS:
                    await _warm(f"/api/leaderboard?category={cat}&period={period}&limit=50", f"{cat}/{period}")
                    await asyncio.sleep(0.4)

            # 3. Homepage endpoints
            for ep in ["/api/homepage/categories", "/api/homepage/metrics", "/api/homepage/recent"]:
                await _warm(ep, ep.split("/")[-1])

        elapsed = time.time() - t0
        _last_warm_at = time.time()

        if failed == 0:
            logger.info(f"Cache warm complete: {success}/{total_queries} ok in {elapsed:.1f}s")
            await _log_to_admin("Cache warm complete", f"{success}/{total_queries} ok in {elapsed:.1f}s")
        else:
            logger.warning(f"Cache warm done: {success} ok, {failed} failed in {elapsed:.1f}s. Errors: {'; '.join(errors[:5])}")
            await _log_to_admin("Cache warm partial", f"{success} ok, {failed} failed in {elapsed:.1f}s. {'; '.join(errors[:5])}", success=False)

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"Cache warm aborted after {elapsed:.1f}s: {type(e).__name__}: {e}", exc_info=True)
        await _log_to_admin("Cache warm aborted", f"{type(e).__name__}: {e} (after {elapsed:.1f}s)", success=False)
    finally:
        _warming = False


async def warm_on_startup():
    """Startup warm — waits for DB to settle, then warms with retries."""
    await asyncio.sleep(15)
    for attempt in range(3):
        try:
            await warm_leaderboard_cache()
            if _last_warm_at > 0:
                return  # Success
            logger.warning(f"Cache warm startup attempt {attempt+1}: completed but no timestamp set")
        except Exception as e:
            logger.error(f"Cache warm startup attempt {attempt+1} failed: {type(e).__name__}: {e}")
        await asyncio.sleep(10)
    logger.error("Cache warm startup: all 3 attempts failed — users will hit cold cache")
    await _log_to_admin("Cache warm startup failed", "All 3 attempts failed — users will hit cold cache", success=False)


def trigger_warm():
    """Non-blocking trigger — call from scheduler after data changes."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(warm_leaderboard_cache())
            logger.debug("Cache warm triggered (data changed)")
        else:
            logger.warning("Cache warm trigger: no running event loop")
    except Exception as e:
        logger.error(f"Cache warm trigger failed: {type(e).__name__}: {e}")
