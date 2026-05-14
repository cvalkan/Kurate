"""Lightweight process memory reporter for diagnosing OOM issues.

Logs to both stdout and MongoDB (system_logs collection with 7-day TTL).
"""
import os
import gc
import ctypes
import time
import psutil
import logging
from datetime import datetime, timezone

logger = logging.getLogger("papersumo")

_process = psutil.Process(os.getpid())
_db = None

# Load libc for malloc_trim — forces glibc to return freed arenas to OS
try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:
    _libc = None


def _get_db():
    global _db
    if _db is None:
        from core.config import db
        _db = db
    return _db


def get_mem_mb() -> float:
    """Current RSS in MB."""
    return _process.memory_info().rss / 1024 / 1024


def force_gc(label: str = ""):
    """GC + malloc_trim to actually return freed memory to the OS.
    
    Python's gc.collect() frees Python objects but glibc's arena allocator
    holds onto the pages. malloc_trim(0) forces glibc to release them.
    Returns (before_mb, after_mb) for diagnostics.
    """
    before = get_mem_mb()
    collected = gc.collect()
    if _libc:
        _libc.malloc_trim(0)
    after = get_mem_mb()
    freed = before - after
    if freed > 5 or label:  # Only log if meaningful or explicitly labeled
        logger.info(f"[GC] {label}: {before:.0f}→{after:.0f}MB (freed {freed:.0f}MB, {collected} objects)")
    return before, after


def log_mem(label: str):
    """Log current memory usage with a label. Also persists to MongoDB."""
    mb = get_mem_mb()
    # Use WARNING for failure labels to avoid log viewer misclassification
    if "FAILED" in label:
        logger.warning(f"[MEM] {label}: {mb:.0f}MB RSS")
    else:
        logger.info(f"[MEM] {label}: {mb:.0f}MB RSS")
    _persist("mem", label, {"rss_mb": round(mb)})


def log_event(level: str, label: str, data: dict = None):
    """Log a structured event to stdout and MongoDB."""
    msg = f"[{level.upper()}] {label}"
    if data:
        msg += f": {data}"
    logger.info(msg)
    _persist(level, label, data or {})


_pod_id = None  # Set by server.py after scheduler assigns leader ID


def set_pod_id(pod_id: str):
    global _pod_id
    _pod_id = pod_id


# Set pod_id immediately from process info (before scheduler starts)
# Will be updated later with the scheduler's leader_id if available
_pod_id = f"pod-{os.getpid()}"


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
        if _pod_id:
            doc["pod_id"] = _pod_id
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


async def log_event(event: str, detail: str = "", category: str = "", count: int = 0, **extra):
    """Log a pipeline event (fetch, download, summary, archive, tournament) to system_logs.
    These appear in the admin Logs tab alongside LLM usage."""
    db = _get_db()
    doc = {
        "ts": datetime.now(timezone.utc),
        "level": "event",
        "event": event,
        "detail": detail,
        "category": category,
        "count": count,
        **extra,
    }
    try:
        await db.system_logs.insert_one(doc)
    except Exception:
        pass
