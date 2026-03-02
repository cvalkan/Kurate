"""
Background Task Tracker — persistent task state in MongoDB.

Tracks long-running background tasks so that:
1. On server restart, we know which tasks were interrupted
2. Interrupted tasks can be logged as warnings (or auto-resumed where possible)
3. The admin UI can show task history and current status

Usage:
    tracker = TaskTracker("experiment_name")
    task_id = await tracker.start(metadata={"dataset_id": "iclr-llm"})
    # ... do work, updating progress ...
    await tracker.progress(task_id, done=50, total=100)
    # ... on completion ...
    await tracker.complete(task_id)
    # ... on failure ...
    await tracker.fail(task_id, error="LLM quota exceeded")
"""
from datetime import datetime, timezone
from core.config import db, logger


class TaskTracker:
    """Lightweight persistent task tracker backed by MongoDB."""

    COLLECTION = "background_tasks"

    def __init__(self, task_type: str):
        self.task_type = task_type

    async def start(self, metadata: dict = None) -> str:
        """Register a new task as running. Returns task_id."""
        import uuid
        task_id = f"{self.task_type}:{uuid.uuid4().hex[:8]}"
        doc = {
            "task_id": task_id,
            "task_type": self.task_type,
            "status": "running",
            "metadata": metadata or {},
            "done": 0,
            "total": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db[self.COLLECTION].insert_one(doc)
        return task_id

    async def progress(self, task_id: str, done: int = None, total: int = None, phase: str = None):
        """Update progress on a running task."""
        update = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if done is not None:
            update["done"] = done
        if total is not None:
            update["total"] = total
        if phase is not None:
            update["metadata.phase"] = phase
        await db[self.COLLECTION].update_one(
            {"task_id": task_id},
            {"$set": update},
        )

    async def complete(self, task_id: str):
        """Mark task as successfully completed."""
        await db[self.COLLECTION].update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    async def fail(self, task_id: str, error: str = ""):
        """Mark task as failed."""
        await db[self.COLLECTION].update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "failed",
                "error": error[:500],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    @classmethod
    async def warn_interrupted(cls):
        """Startup check: log warnings for any tasks that were running when the server stopped.

        Marks them as 'interrupted' so they don't trigger warnings again.
        Returns list of interrupted task docs.
        """
        interrupted = await db[cls.COLLECTION].find(
            {"status": "running"},
            {"_id": 0},
        ).to_list(100)

        if interrupted:
            logger.warning(f"Found {len(interrupted)} tasks interrupted by server restart:")
            for t in interrupted:
                meta = t.get("metadata", {})
                logger.warning(
                    f"  [{t['task_type']}] {t['task_id']} — "
                    f"started {t.get('started_at', '?')}, "
                    f"progress {t.get('done', 0)}/{t.get('total', '?')}, "
                    f"metadata={meta}"
                )

            await db[cls.COLLECTION].update_many(
                {"status": "running"},
                {"$set": {
                    "status": "interrupted",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )

        return interrupted

    @classmethod
    async def recent(cls, task_type: str = None, limit: int = 20) -> list:
        """Get recent tasks for admin dashboard."""
        query = {}
        if task_type:
            query["task_type"] = task_type
        return await db[cls.COLLECTION].find(
            query, {"_id": 0}
        ).sort("started_at", -1).limit(limit).to_list(limit)

    @classmethod
    async def cleanup_old(cls, days: int = 30):
        """Remove tasks older than N days."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = await db[cls.COLLECTION].delete_many({
            "status": {"$in": ["complete", "interrupted", "failed"]},
            "updated_at": {"$lt": cutoff},
        })
        if result.deleted_count:
            logger.info(f"Cleaned up {result.deleted_count} old background tasks")
