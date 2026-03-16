"""MongoDB-backed persistent cache for expensive computations."""
from core.config import db, logger

_memory_cache = {}


async def get_cached(key: str):
    """Get from memory cache, then MongoDB."""
    if key in _memory_cache:
        return _memory_cache[key]
    doc = await db.computation_cache.find_one({"key": key}, {"_id": 0, "data": 1})
    if doc and doc.get("data"):
        _memory_cache[key] = doc["data"]
        return doc["data"]
    return None


async def set_cached(key: str, data):
    """Store in both memory and MongoDB."""
    _memory_cache[key] = data
    await db.computation_cache.update_one(
        {"key": key},
        {"$set": {"key": key, "data": data}},
        upsert=True,
    )


async def invalidate_cached(key: str):
    """Remove from both caches."""
    _memory_cache.pop(key, None)
    await db.computation_cache.delete_one({"key": key})
