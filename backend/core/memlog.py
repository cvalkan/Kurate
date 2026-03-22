"""Lightweight process memory reporter for diagnosing OOM issues.

Logs to both stdout and MongoDB (system_logs collection with 7-day TTL).
"""
import os
import time
import psutil
import logging
from datetime import datetime, timezone

logger = logging.getLogger("papersumo")

_process = psutil.Process(os.getpid())
_db = None


def _get_db():
    global _db
    if _db is None:
        from core.config import db
        _db = db
    return _db


def get_mem_mb() -> float:
    """Current RSS in MB."""
    return _process.memory_info().rss / 1024 / 1024


def log_mem(label: str):
    """Log current memory usage with a label. Also persists to MongoDB."""
    mb = get_mem_mb()
    logger.info(f"[MEM] {label}: {mb:.0f}MB RSS")
    _persist("mem", label, {"rss_mb": round(mb)})


def log_event(level: str, label: str, data: dict = None):
    """Log a structured event to stdout and MongoDB."""
    msg = f"[{level.upper()}] {label}"
    if data:
        msg += f": {data}"
    logger.info(msg)
    _persist(level, label, data or {})


def _persist(level: str, label: str, data: dict):
    """Fire-and-forget write to MongoDB system_logs collection."""
    try:
        db = _get_db()
        doc = {
            "ts": datetime.now(timezone.utc),
            "level": level,
            "label": label,
            **data,
        }
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_persist(db, doc))
        except RuntimeError:
            pass
    except Exception:
        pass


async def _async_persist(db, doc):
    try:
        await db.system_logs.insert_one(doc)
    except Exception:
        pass


async def ensure_ttl_index(db):
    """Create TTL index on system_logs (auto-delete after 7 days). Call once at startup."""
    try:
        await db.system_logs.create_index("ts", expireAfterSeconds=7 * 86400, name="ttl_7d")
    except Exception:
        pass
