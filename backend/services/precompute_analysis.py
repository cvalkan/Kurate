"""Precompute model analysis and store in MongoDB for fast serving.

Runs once daily from the scheduler. Processes one category at a time
to keep memory bounded. Results are served by the /api/model-analysis endpoint.
"""
import asyncio
import time
from datetime import datetime, timezone

from core.config import db, logger
from core.memlog import force_gc


COLLECTION = "model_analysis_precomputed"
ALL_KEY = "__all__"


async def ensure_index():
    await db[COLLECTION].create_index("key", unique=True)


async def get_precomputed(key: str):
    """Read precomputed analysis. Returns None if not found."""
    doc = await db[COLLECTION].find_one({"key": key}, {"_id": 0})
    return doc


async def precompute_model_analysis(categories: list = None):
    """Compute model analysis for all categories + all-combined, one at a time."""
    from services.model_analysis import _compute_live_analysis_impl
    from core.auth import get_settings

    if categories is None:
        settings = await get_settings()
        categories = settings.get("active_categories", [])

    total_start = time.perf_counter()
    success = 0
    failed = 0

    # Per-category, then all-combined
    keys = [(cat, cat) for cat in categories] + [(None, ALL_KEY)]

    for category, key in keys:
        t0 = time.perf_counter()
        try:
            result = await _compute_live_analysis_impl(category)
            elapsed = round(time.perf_counter() - t0, 1)

            await db[COLLECTION].update_one(
                {"key": key},
                {"$set": {
                    "key": key,
                    "data": result,
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                    "compute_time_s": elapsed,
                }},
                upsert=True,
            )
            success += 1
            logger.info(f"[precompute] {key}: {elapsed}s")
        except Exception as e:
            failed += 1
            logger.warning(f"[precompute] {key} failed: {e}")

        # Free memory between categories
        del result
        force_gc(f"precompute-{key}")
        await asyncio.sleep(2)

    total = round(time.perf_counter() - total_start, 1)
    logger.info(f"[precompute] Done: {success} ok, {failed} failed, {total}s total")

    # Update last run timestamp
    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"last_model_analysis_precompute": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    return {"success": success, "failed": failed, "total_time_s": total}


async def should_run_precompute(interval_hours=24):
    """Check if precompute should run (>interval_hours since last run, or never run)."""
    settings = await db.settings.find_one({"key": "global"}, {"_id": 0, "last_model_analysis_precompute": 1})
    last_run = (settings or {}).get("last_model_analysis_precompute")
    if not last_run:
        return True
    from dateutil.parser import parse as dt_parse
    elapsed = (datetime.now(timezone.utc) - dt_parse(last_run)).total_seconds() / 3600
    return elapsed >= interval_hours
