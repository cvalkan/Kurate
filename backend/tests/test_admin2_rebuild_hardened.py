"""Regression tests for the hardened admin2 daily_stats rebuild.

Proves the properties that the old per-chunk `$set` crawl violated on prod
(daily=422,838 vs true 567,649, silently):

  1. Σ daily_stats._total.matches == count(completed, active) — EXACT.
  2. A paper added today but PUBLISHED on an old day does NOT clobber that old
     day's match total (the production failure mode).
  3. Matches with null / string / BSON-Date created_at are ALL counted (never
     silently dropped) — null falls back to the ObjectId timestamp.

All synthetic data is namespaced under a sentinel category and a flag field so
cleanup is exact; a final clean rebuild restores preview to a pristine state.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from core.config import db
from core.auth import get_settings
import routers.admin2_stats as a2

SENTINEL = "zz.regress"
OLD_DAY_MATCH = "2015-01-05"
FLAG = "_regress_test"
MODEL = {"provider": "openai", "model": "gpt-5.2"}
TOK = {"input_est": 100, "output_est": 50}


async def _set_active_includes_sentinel(include: bool):
    settings = await db.settings.find_one({"key": "global"}, {"active_categories": 1})
    active = list((settings or {}).get("active_categories") or [])
    if include and SENTINEL not in active:
        active.append(SENTINEL)
    if not include:
        active = [c for c in active if c != SENTINEL]
    await db.settings.update_one({"key": "global"}, {"$set": {"active_categories": active}})


async def _cleanup():
    await db.matches.delete_many({FLAG: True})
    await db.papers.delete_many({FLAG: True})
    await db.daily_stats.delete_many({"category": SENTINEL})
    await db.daily_stats.delete_many({"date": OLD_DAY_MATCH, "category": "_total"})
    await _set_active_includes_sentinel(False)


async def _run_clean_rebuild():
    a2._admin._ts_backfill_running = False
    await a2._run_backfill()


@pytest.fixture(autouse=True)
def _around():
    asyncio.get_event_loop().run_until_complete(_cleanup())
    yield
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_cleanup())
    loop.run_until_complete(_run_clean_rebuild())  # restore pristine state


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_reconciles_exactly_on_real_data():
    async def go():
        await _run_clean_rebuild()
        s = await get_settings()
        active = [c for c in (s.get("active_categories") or []) if c and c.strip()]
        expected = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": {"$in": active}})
        daily = await a2._sum_daily_total_matches()
        # today's in-flight $inc tolerance (<0.5%)
        assert abs(daily - expected) <= max(50, expected * 0.005), (daily, expected)
        st = await db.daily_stats.find_one({"_meta": "backfill_status"}, {"_id": 0})
        assert st and st.get("reconciled") is True, st
    _run(go())


def test_republished_old_paper_does_not_clobber_matches():
    async def go():
        K = 7
        await _set_active_includes_sentinel(True)
        # K completed matches on an OLD day.
        old_dt = datetime(2015, 1, 5, 12, 0, tzinfo=timezone.utc)
        await db.matches.insert_many([{
            "id": str(ObjectId()),
            FLAG: True, "completed": True, "failed": False,
            "primary_category": SENTINEL, "created_at": old_dt,
            "model_used": MODEL, "tokens": TOK,
        } for _ in range(K)])
        # A paper ADDED TODAY but PUBLISHED on the same old day (the prod scenario
        # that used to overwrite the old day's match bucket).
        await db.papers.insert_one({
            "id": str(ObjectId()),
            FLAG: True, "categories": [SENTINEL],
            "added_at": datetime.now(timezone.utc),
            "published": "2015-01-05T08:00:00+00:00",
            "summaries": {},
        })
        await _run_clean_rebuild()
        bucket = await db.daily_stats.find_one(
            {"date": OLD_DAY_MATCH, "category": SENTINEL}, {"_id": 0})
        assert bucket is not None, "old-day sentinel bucket missing"
        assert bucket.get("matches") == K, (bucket, "matches were clobbered")
        # The republished paper buckets by added_at (today), NOT the old match day.
        assert bucket.get("papers", 0) == 0, bucket
    _run(go())


def test_null_string_and_date_created_at_all_counted():
    async def go():
        await _set_active_includes_sentinel(True)
        # (a) NULL created_at on an OLD _id → must fall back to the _id day (2015-02-01).
        old_oid = ObjectId.from_datetime(datetime(2015, 2, 1, 9, 0, tzinfo=timezone.utc))
        await db.matches.insert_one({
            "_id": old_oid, "id": str(ObjectId()), FLAG: True, "completed": True, "failed": False,
            "primary_category": SENTINEL, "created_at": None,
            "model_used": MODEL, "tokens": TOK,
        })
        # (b) STRING created_at.
        await db.matches.insert_one({
            "id": str(ObjectId()), FLAG: True, "completed": True, "failed": False,
            "primary_category": SENTINEL, "created_at": "2015-02-02T10:00:00+00:00",
            "model_used": MODEL, "tokens": TOK,
        })
        # (c) BSON Date created_at.
        await db.matches.insert_one({
            "id": str(ObjectId()), FLAG: True, "completed": True, "failed": False,
            "primary_category": SENTINEL,
            "created_at": datetime(2015, 2, 3, 10, 0, tzinfo=timezone.utc),
            "model_used": MODEL, "tokens": TOK,
        })
        await _run_clean_rebuild()
        # All three counted in the sentinel category (none dropped).
        agg = await db.daily_stats.aggregate([
            {"$match": {"category": SENTINEL}},
            {"$group": {"_id": None, "m": {"$sum": "$matches"}}},
        ]).to_list(1)
        sentinel_total = int(agg[0]["m"]) if agg else 0
        assert sentinel_total == 3, sentinel_total
        # And the null-created_at one bucketed to its ObjectId day.
        b = await db.daily_stats.find_one({"date": "2015-02-01", "category": SENTINEL}, {"_id": 0})
        assert b and b.get("matches") == 1, b
    _run(go())
