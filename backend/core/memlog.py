"""Lightweight process memory reporter for diagnosing OOM issues.

Logs to both stdout and MongoDB (system_logs collection with 7-day TTL).
"""
import os
import gc
import ctypes
import time
import asyncio
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


_pod_id = None
_pod_role = None  # "leader" or "follower"


def set_pod_id(pod_id: str):
    global _pod_id
    _pod_id = pod_id


def set_pod_role(role: str):
    global _pod_role
    _pod_role = role


# Set pod_id immediately from process info (before scheduler starts)
_pod_id = f"pod-{os.getpid()}"
logger.info(f"[memlog] pod_id initialized to: {_pod_id}")


def _persist(level: str, label: str, data: dict):
    """Fire-and-forget write to MongoDB system_logs collection."""
    try:
        db = _get_db()
        doc = {
            "ts": datetime.now(timezone.utc),
            "level": level,
            "label": label,
            **data,
            "pod_id": _pod_id,
            "pod_role": _pod_role,  # "leader" or "follower"
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


def _event_doc(event: str, detail: str, category: str, count: int,
               level: str, success: bool, extra: dict) -> dict:
    """Build a single, consistent system_logs event document. The ONE shape used
    by every event writer (fetch cycles, archives, slow queries, repair queue,
    badge views, server lifecycle). `success=False` flags an event that failed
    even if the surrounding cycle otherwise ran — so the UI never shows an errored
    event as 'ok'."""
    doc = {
        "ts": datetime.now(timezone.utc),
        "level": level,
        "event": event,
        "detail": detail,
        "category": category,
        "count": count,
        "success": success,
        "pod_id": _pod_id,
        "pod_role": _pod_role,
    }
    doc.update(extra)
    return doc


async def log_event(event: str, detail: str = "", category: str = "", count: int = 0,
                    level: str = "event", success: bool = True, **extra):
    """Canonical async event logger — writes one consistent doc to system_logs
    (admin Logs tab). Use for any pipeline/system event."""
    db = _get_db()
    try:
        await db.system_logs.insert_one(
            _event_doc(event, detail, category, count, level, success, extra))
    except Exception:
        pass


def log_event_nowait(event: str, detail: str = "", category: str = "", count: int = 0,
                     level: str = "event", success: bool = True, **extra):
    """Fire-and-forget event logger for sync contexts / hot paths (slow queries,
    badge views, signal handlers, pre-startup). Schedules the insert on the
    running loop; falls back to a short-lived sync client when there's no loop."""
    doc = _event_doc(event, detail, category, count, level, success, extra)
    db = _get_db()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_persist(db, doc))
    except RuntimeError:
        try:
            from pymongo import MongoClient
            sc = MongoClient(os.environ.get("MONGO_URL"), serverSelectionTimeoutMS=2000)
            sc[os.environ.get("DB_NAME", "papersumo")].system_logs.insert_one(doc)
            sc.close()
        except Exception:
            pass
