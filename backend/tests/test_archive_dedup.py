"""Regression: leaderboard_archives must never contain duplicate period snapshots.

Covers the recurring "duplicate Week N" bug: a rolling redeploy / two-leader
window made two concurrent create_archive_snapshot() calls both pass the racy
check-then-insert. ensure_archive_integrity() de-dupes and enforces a unique
index so it can never recur.
"""
import os
import asyncio
import pytest
from dotenv import load_dotenv

load_dotenv()
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

TEST_CAT = "__pytest_archive_dedup__"


def _doc(week, papers, created):
    return {"category": TEST_CAT, "period_type": "weekly", "year": 2099,
            "week": week, "month": None, "label": f"Week {week}, 2099",
            "paper_count": papers, "leaderboard": [], "created_at": created}


@pytest.fixture()
def db():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


def test_dedup_removes_duplicates_keeps_most_complete(db):
    from routers.leaderboard import ensure_archive_integrity

    async def run():
        await db.leaderboard_archives.delete_many({"category": TEST_CAT})
        # Drop the unique index so we can stage the raced-duplicate scenario.
        try:
            await db.leaderboard_archives.drop_index("archive_period_unique")
        except Exception:
            pass
        # Insert 3 duplicates of Week 22 (raced inserts) with differing paper_count.
        await db.leaderboard_archives.insert_many([
            _doc(22, 5, "2026-01-01T00:00:00+00:00"),
            _doc(22, 9, "2026-01-02T00:00:00+00:00"),   # most complete -> kept
            _doc(22, 9, "2026-01-03T00:00:00+00:00"),   # tie on papers, newer
            _doc(23, 7, "2026-01-01T00:00:00+00:00"),   # distinct week, untouched
        ])
        await ensure_archive_integrity()

        wk22 = await db.leaderboard_archives.find(
            {"category": TEST_CAT, "week": 22}).to_list(None)
        assert len(wk22) == 1, f"expected 1 Week-22 archive, got {len(wk22)}"
        # tie-break keeps newest created_at among the most-complete copies
        assert wk22[0]["created_at"] == "2026-01-03T00:00:00+00:00"
        wk23 = await db.leaderboard_archives.count_documents(
            {"category": TEST_CAT, "week": 23})
        assert wk23 == 1

        # Unique index now blocks a fresh duplicate insert.
        with pytest.raises(DuplicateKeyError):
            await db.leaderboard_archives.insert_one(_doc(22, 1, "x"))

        await db.leaderboard_archives.delete_many({"category": TEST_CAT})

    asyncio.get_event_loop().run_until_complete(run())
