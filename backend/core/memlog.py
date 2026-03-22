"""Lightweight process memory reporter for diagnosing OOM issues."""
import os
import time
import psutil
import logging

logger = logging.getLogger("papersumo")

_process = psutil.Process(os.getpid())


def get_mem_mb() -> float:
    """Current RSS in MB."""
    return _process.memory_info().rss / 1024 / 1024


def log_mem(label: str):
    """Log current memory usage with a label."""
    logger.info(f"[MEM] {label}: {get_mem_mb():.0f}MB RSS")


class track_mem:
    """Context manager that logs memory before/after a block + duration.
    
    Usage:
        with track_mem("seed_rankings"):
            await seed_rankings(db)
        # Logs: [MEM] seed_rankings: 320MB → 325MB (+5MB) in 2.3s
    """
    def __init__(self, label: str):
        self.label = label
        self.start_mb = 0.0
        self.start_time = 0.0

    def __enter__(self):
        self.start_mb = get_mem_mb()
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *exc):
        end_mb = get_mem_mb()
        elapsed = time.perf_counter() - self.start_time
        delta = end_mb - self.start_mb
        sign = "+" if delta >= 0 else ""
        logger.info(f"[MEM] {self.label}: {self.start_mb:.0f}MB → {end_mb:.0f}MB ({sign}{delta:.0f}MB) in {elapsed:.1f}s")


class async_track_mem:
    """Async context manager version of track_mem.
    
    Usage:
        async with async_track_mem("reconcile"):
            await reconcile_rankings(db)
    """
    def __init__(self, label: str):
        self.label = label
        self.start_mb = 0.0
        self.start_time = 0.0

    async def __aenter__(self):
        self.start_mb = get_mem_mb()
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, *exc):
        end_mb = get_mem_mb()
        elapsed = time.perf_counter() - self.start_time
        delta = end_mb - self.start_mb
        sign = "+" if delta >= 0 else ""
        logger.info(f"[MEM] {self.label}: {self.start_mb:.0f}MB → {end_mb:.0f}MB ({sign}{delta:.0f}MB) in {elapsed:.1f}s")
