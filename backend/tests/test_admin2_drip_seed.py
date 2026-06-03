"""Regression tests for the DURABLE DRIP SEED of daily_stats.

Proves the properties that every prior in-memory rebuild lacked — the ones that
made it freeze on any interruption:

  1. RESUMABLE: progress lives in the DB (`seed_progress`). After processing some
     categories, a brand-new caller (simulating a pod restart / fresh task) picks
     up exactly where the last one left off — `done` categories are NOT reseeded
     and nothing already sealed is lost.
  2. IDEMPOTENT: re-running a single category (the retry-after-timeout path)
     re-`$set`s only that category's buckets — the final reconciled total is
     identical whether or not a category was processed twice.
  3. OBSERVABLE + RECONCILES: a full drain (start → seal each category → finalize)
     ends with status `reconciled` and Σ daily_stats._total.matches == ground
     truth, and `seed_progress` exposes the live "done / total" readout.

All synthetic data is namespaced under a sentinel category so cleanup is exact;
a final clean rebuild restores preview to a pristine state.
"""
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from bson import ObjectId

from core.config import db
from core.auth import get_settings
import routers.admin2_stats as a2

SENTINEL = "zz.dripseed"
FLAG = "_dripseed_test"
MODEL = {"provider": "openai", "model": "gpt-5.2"}
TOK = {"input_est": 100, "output_est": 50}


async def _set_active_includes_sentinel(include: bool):
    s = await db.settings.find_one({"key": "global"}, {"active_categories": 1})
    active = list((s or {}).get("active_categories") or [])
    if include and SENTINEL not in active:
        active.append(SENTINEL)
    if not include:
        active = [c for c in active if c != SENTINEL]
    await db.settings.update_one({"key": "global"}, {"$set": {"active_categories": active}})


async def _cleanup():
    await db.matches.delete_many({FLAG: True})
    await db.papers.delete_many({FLAG: True})
    await db.daily_stats.delete_many({"category": SENTINEL})
    try:
        await db[a2._SEED_MODELS].drop()
    except Exception:
        pass
    await _set_active_includes_sentinel(False)


@pytest.fixture(autouse=True)
def _around():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_cleanup())
    yield
    loop.run_until_complete(_cleanup())
    a2._admin._ts_backfill_running = False
    loop.run_until_complete(a2._run_backfill())  # restore pristine state


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed_sentinel_matches(n: int, day_dt: datetime):
    await db.matches.insert_many([{
        "id": str(ObjectId()), FLAG: True, "completed": True, "failed": False,
        "primary_category": SENTINEL, "created_at": day_dt,
        "model_used": MODEL, "tokens": TOK,
    } for _ in range(n)])


def test_seed_is_resumable_across_a_simulated_restart():
    async def go():
        await _set_active_includes_sentinel(True)
        await _seed_sentinel_matches(5, datetime(2014, 3, 3, 12, tzinfo=timezone.utc))

        # start_seed queues every active category as pending.
        sp = await a2.start_seed("test")
        assert sp["status"] == "running"
        assert SENTINEL in sp["pending"]
        assert sp["done"] == []
        total = sp["total"]

        # Process THREE categories one tick at a time (each tick = one category).
        for _ in range(3):
            await a2.seed_tick()
        mid = await a2.get_seed_progress()
        assert len(mid["done"]) == 3, mid
        assert len(mid["pending"]) == total - 3
        done_snapshot = set(mid["done"])

        # Simulate a restart: a brand-new caller reads the DB checkpoint and
        # continues. The already-`done` categories must NOT reappear in pending.
        sp2 = await a2.get_seed_progress()
        assert set(sp2["done"]) == done_snapshot
        assert not (set(sp2["pending"]) & done_snapshot), "a sealed category leaked back into pending"

        # Drain the rest to completion.
        for _ in range(total + 2):
            await a2.seed_tick()
            cur = await a2.get_seed_progress()
            if cur["status"] in ("reconciled", "drift", "completed_with_failures"):
                break
        final = await a2.get_seed_progress()
        assert final["status"] == "reconciled", final
        # Every category sealed exactly once.
        assert len(final["done"]) == total, final
        # The sentinel's 5 matches are present (resume lost nothing).
        b = await db.daily_stats.find_one({"date": "2014-03-03", "category": SENTINEL}, {"_id": 0})
        assert b and b.get("matches") == 5, b
    _run(go())


def test_reprocessing_a_category_is_idempotent():
    async def go():
        await _set_active_includes_sentinel(True)
        await _seed_sentinel_matches(9, datetime(2014, 4, 4, 12, tzinfo=timezone.utc))

        await a2.start_seed("test")
        model_avg = {}  # tracked-token averages irrelevant for matches-only sentinel

        # Seal the sentinel category TWICE (the retry-after-timeout path).
        await a2._seed_one_category(SENTINEL, model_avg)
        await a2._seed_one_category(SENTINEL, model_avg)

        b = await db.daily_stats.find_one({"date": "2014-04-04", "category": SENTINEL}, {"_id": 0})
        assert b and b.get("matches") == 9, ("double-seal must not double-count", b)

        # The temp per-category model doc holds the single (not doubled) total.
        m = await db[a2._SEED_MODELS].find_one({"_id": f"m|{SENTINEL}"})
        total_matches = sum(row.get("matches", 0) for row in (m or {}).get("models", []))
        assert total_matches == 9, (m, "model contribution doubled")
    _run(go())


def test_large_category_chunking_reconciles_exactly():
    """Forces the IN-CATEGORY month-windowing path (the "category too large to
    aggregate in one read" case) by dropping the chunk threshold, and proves the
    windowed seal counts EVERY match exactly once across multiple months — no
    drop, no double-count."""
    async def go():
        await _set_active_includes_sentinel(True)
        # Spread matches across THREE distinct months, each with a unique _id in
        # that month so they land in three different _id windows.
        months = [
            (datetime(2016, 1, 10, 12, tzinfo=timezone.utc), 4),
            (datetime(2016, 2, 10, 12, tzinfo=timezone.utc), 5),
            (datetime(2016, 3, 10, 12, tzinfo=timezone.utc), 6),
        ]
        for dt, n in months:
            await db.matches.insert_many([{
                "_id": ObjectId.from_datetime(dt + timedelta(seconds=i)),
                "id": str(ObjectId()), FLAG: True, "completed": True, "failed": False,
                "primary_category": SENTINEL, "created_at": dt,
                "model_used": MODEL, "tokens": TOK,
            } for i in range(n)])
        total = 4 + 5 + 6

        await a2.start_seed("test")  # resets the temp model collection

        # Controlled window bounds spanning the three months, and a tiny threshold
        # so the windowed path is taken on this small category.
        ws, we = "2016-01-01T00:00:00+00:00", "2016-03-31T00:00:00+00:00"
        windows = a2._build_match_windows(ws, we)
        assert len(windows) >= 3, ("expected multiple month windows", len(windows))

        orig = a2._SEED_MATCH_CHUNK_THRESHOLD
        a2._SEED_MATCH_CHUNK_THRESHOLD = 2
        try:
            await a2._seed_one_category(SENTINEL, {}, ws, we)
        finally:
            a2._SEED_MATCH_CHUNK_THRESHOLD = orig

        # Each month's bucket is exact, and the grand total == count (no drop/dup).
        for dt, n in months:
            day = dt.strftime("%Y-%m-%d")
            b = await db.daily_stats.find_one({"date": day, "category": SENTINEL}, {"_id": 0})
            assert b and b.get("matches") == n, (day, b)
        agg = await db.daily_stats.aggregate([
            {"$match": {"category": SENTINEL}},
            {"$group": {"_id": None, "m": {"$sum": "$matches"}}},
        ]).to_list(1)
        assert (agg[0]["m"] if agg else 0) == total, agg

        # The per-category model temp doc holds the single (not multiplied) total.
        m = await db[a2._SEED_MODELS].find_one({"_id": f"m|{SENTINEL}"})
        assert sum(r.get("matches", 0) for r in (m or {}).get("models", [])) == total, m
    _run(go())


def test_full_drain_reconciles_exactly():
    async def go():
        await a2.start_seed("test")
        for _ in range(a2._SEED_MAX_ATTEMPTS + 200):
            await a2.seed_tick()
            cur = await a2.get_seed_progress()
            if cur["status"] in ("reconciled", "drift", "completed_with_failures"):
                break
        final = await a2.get_seed_progress()
        assert final["status"] == "reconciled", final

        s = await get_settings()
        active = [c for c in (s.get("active_categories") or []) if c and c.strip()]
        expected = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": {"$in": active}})
        daily = await a2._sum_daily_total_matches()
        assert abs(daily - expected) <= max(50, expected * 0.005), (daily, expected)

        st = await db.daily_stats.find_one({"_meta": "backfill_status"}, {"_id": 0})
        assert st and st.get("reconciled") is True, st
    _run(go())
