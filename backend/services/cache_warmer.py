"""Leaderboard cache warming.

Pre-warms all category × period combinations so every user hits warm cache.
Triggered on:
  - Server startup (after DB connection settles)
  - Data changes (new match, new papers ingested, archive sealed)
"""
import asyncio
import time
import httpx
from core.config import logger

_warming = False
_last_warm_at = 0

PERIODS = ["recent", "week", "month", "all"]


async def warm_leaderboard_cache():
    """Warm all leaderboard cache entries. Safe to call concurrently — deduplicates."""
    global _warming, _last_warm_at

    # Skip if already warming or warmed < 60s ago
    if _warming:
        logger.info("Leaderboard warm: already in progress, skipping")
        return
    if time.time() - _last_warm_at < 60:
        logger.info("Leaderboard warm: warmed <60s ago, skipping")
        return

    _warming = True
    t0 = time.time()
    try:
        from core.auth import get_settings
        from routers.homepage import clear_homepage_cache
        clear_homepage_cache()
        settings = await get_settings()
        categories = sorted(c for c in (settings.get("active_categories") or []) if c and c.strip())

        async with httpx.AsyncClient(base_url="http://localhost:8001", timeout=60) as client:
            success = 0
            failed = 0

            # 1. All Categories × all periods
            for period in PERIODS:
                try:
                    r = await client.get(f"/api/leaderboard?show_all=true&period={period}&limit=50")
                    if r.status_code == 200:
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.3)

            # 2. Each category × all periods
            for cat in categories:
                for period in PERIODS:
                    try:
                        r = await client.get(f"/api/leaderboard?category={cat}&period={period}&limit=50")
                        if r.status_code == 200:
                            success += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                    await asyncio.sleep(0.2)

            # 3. Homepage endpoints
            for ep in ["/api/homepage/categories", "/api/homepage/metrics", "/api/homepage/recent"]:
                try:
                    await client.get(ep)
                    success += 1
                except Exception:
                    failed += 1

            elapsed = time.time() - t0
            _last_warm_at = time.time()
            logger.info(f"Leaderboard warm complete: {success} ok, {failed} failed, {elapsed:.1f}s")

    except Exception as e:
        logger.warning(f"Leaderboard warm failed: {e}")
    finally:
        _warming = False


async def warm_on_startup():
    """Startup warm — waits for DB to settle, then warms with retries."""
    await asyncio.sleep(15)
    for attempt in range(3):
        try:
            await warm_leaderboard_cache()
            return
        except Exception as e:
            logger.warning(f"Startup warm attempt {attempt+1} failed: {e}")
            await asyncio.sleep(10)


def trigger_warm():
    """Non-blocking trigger — call from scheduler after data changes."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(warm_leaderboard_cache())
        else:
            asyncio.run(warm_leaderboard_cache())
    except Exception:
        pass
