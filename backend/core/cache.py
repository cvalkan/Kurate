"""MongoDB-backed persistent cache for expensive computations.

Uses a CACHE_VERSION to auto-invalidate stale entries on deploy.
Bump CACHE_VERSION whenever the computation logic changes in a way
that makes old cached results incorrect.
"""
from core.config import db, logger

# Bump this whenever cached computation logic changes materially
CACHE_VERSION = 4  # v4: fix race condition — JSON loaded before accepting connections

_memory_cache = {}


async def get_cached(key: str):
    """Get from memory cache, then MongoDB. Returns None if version mismatch."""
    if key in _memory_cache:
        return _memory_cache[key]
    doc = await db.computation_cache.find_one({"key": key}, {"_id": 0, "data": 1, "version": 1})
    if doc and doc.get("data"):
        if doc.get("version", 0) != CACHE_VERSION:
            # Stale version — invalidate
            await db.computation_cache.delete_one({"key": key})
            logger.info(f"Cache invalidated (version mismatch): {key}")
            return None
        _memory_cache[key] = doc["data"]
        return doc["data"]
    return None


async def set_cached(key: str, data):
    """Store in both memory and MongoDB with version tag."""
    _memory_cache[key] = data
    await db.computation_cache.update_one(
        {"key": key},
        {"$set": {"key": key, "data": data, "version": CACHE_VERSION}},
        upsert=True,
    )


async def invalidate_cached(key: str):
    """Remove from both caches."""
    _memory_cache.pop(key, None)
    await db.computation_cache.delete_one({"key": key})
