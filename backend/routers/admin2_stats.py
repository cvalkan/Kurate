"""Admin Statistics v2 — scalable rebuild at /api/admin2.

Design principles (see /app/memory/ADMIN2_STATS_REBUILD.md):
- The READ path NEVER aggregates `matches`/`papers`. It only reads the
  pre-aggregated `daily_stats` materialized view (~150 docs), the small
  `model_match_stats` collection, the in-memory leaderboard cache, and a
  bounded `users` aggregation. This is instant regardless of data scale.
- The `daily_stats` view is kept fresh by fire-and-forget O(1) `$inc` calls
  at write time (match completion / paper add / summary generation).
- A one-time, bounded, type-safe (BSON Date vs string) chunked backfill
  populates `daily_stats` when empty. It runs in the BACKGROUND, never on
  the read path, so the endpoint always responds immediately.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
import asyncio
import time
import os
import uuid

from core.config import db, logger, CATEGORIES
from core.auth import verify_admin, get_settings
import routers.admin as _admin

router = APIRouter(prefix="/api/admin2")

# Average tokens for an untracked summary generation (fallback pricing)
AVG_IN, AVG_OUT = 10375, 1788

# If daily_stats has fewer than this many day-buckets, treat it as empty/sparse
# and kick a background backfill (never blocks the read path).
_SPARSE_THRESHOLD = 5

# In-process response cache so repeated reads are O(1) regardless of data scale.
_CACHE = {}
_CACHE_TTL = 45  # seconds

# ── Distributed backfill lock ────────────────────────────────────────────────
# The per-process `_ts_backfill_running` flag only guards within one pod. In a
# multi-pod deployment, `POST /api/admin2/backfill` (routed to ANY pod by the
# load balancer) can run concurrently with the leader's periodic self-heal on a
# DIFFERENT pod. Two `_run_backfill`s then issue conflicting per-day `$set`s,
# corrupting daily_stats (observed on prod: reconciled=False, 422k vs 568k).
# This MongoDB lease lock (same pattern as scheduler leader election) ensures
# only ONE pod rebuilds cluster-wide at a time.
_LOCK_ID = "admin2_backfill"
_LOCK_TTL = 900  # 15 min — generous upper bound; IXSCAN chunks are fast
_LOCK_HOLDER = f"pod-{uuid.uuid4().hex[:8]}-{os.getpid()}"


async def _acquire_backfill_lock(ttl: int = _LOCK_TTL) -> bool:
    """Atomically claim the cluster-wide backfill lock. Returns True if held."""
    now = datetime.now(timezone.utc)
    try:
        result = await db.admin2_lock.find_one_and_update(
            {"_id": _LOCK_ID, "$or": [
                {"expires_at": {"$lt": now}},
                {"holder": _LOCK_HOLDER},
            ]},
            {"$set": {"holder": _LOCK_HOLDER,
                      "expires_at": now + timedelta(seconds=ttl),
                      "acquired_at": now}},
            upsert=True, return_document=True,
        )
        return bool(result and result.get("holder") == _LOCK_HOLDER)
    except Exception:
        # DuplicateKey on upsert → a live lock is held by another pod.
        return False


async def _release_backfill_lock():
    """Release the lock if we hold it (expire it immediately)."""
    try:
        await db.admin2_lock.update_one(
            {"_id": _LOCK_ID, "holder": _LOCK_HOLDER},
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
        )
    except Exception as e:
        logger.warning(f"[ADMIN2] release_backfill_lock failed: {e}")


def _cache_get(key):
    e = _CACHE.get(key)
    if e and (time.time() - e[0]) < _CACHE_TTL:
        return e[1]
    return None


def _cache_set(key, val):
    _CACHE[key] = (time.time(), val)


def _cache_clear():
    _CACHE.clear()


async def ensure_indexes():
    """Create the indexes the read + backfill paths rely on. Idempotent.

    Without these, daily_stats reads (filtered by `category`) and the per-model
    / registration lookups degrade to collection scans as data grows — the exact
    O(N) behaviour that caused the original timeouts.
    """
    try:
        # Read path filters by category first, then iterates dates → category-prefixed index.
        await db.daily_stats.create_index([("category", 1), ("date", 1)], name="cat_date_idx")
        await db.model_match_stats.create_index([("model", 1)], unique=True, name="model_idx")
        await db.model_summary_stats.create_index([("model", 1)], unique=True, name="model_idx")
        await db.daily_registrations.create_index([("date", 1)], unique=True, name="date_idx")
        # Backfill scans/sorts papers by added_at.
        await db.papers.create_index([("added_at", 1)], name="added_at_idx")
        logger.info("[ADMIN2] ensure_indexes complete")
    except Exception as e:
        logger.warning(f"[ADMIN2] ensure_indexes failed: {e}")


def _safe_day(raw) -> Optional[str]:
    """Extract YYYY-MM-DD from a value that may be a BSON Date or a string."""
    if raw is None:
        return None
    return raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]


def _price_for_summary(model_key: str):
    """Return (price_in, price_out) per-million-tokens for a summary model key
    (colon format, e.g. 'anthropic:claude-opus-4-6:thinking')."""
    provider = model_key.split(":")[0] if ":" in model_key else model_key
    pk = _admin._SUMMARY_PRICING.get(provider) or "anthropic/claude-opus-4-6"
    p = _admin.MODEL_PRICING.get(pk, {"input": 5.0, "output": 25.0})
    return p["input"], p["output"]


# ──────────────────────────────────────────────────────────────────────────
# Write-time incremental updates (O(1), fire-and-forget). Called by scheduler.
# ──────────────────────────────────────────────────────────────────────────

async def record_match_daily_stat(match_doc: dict):
    """Increment daily_stats + model_match_stats on a completed match."""
    try:
        if not match_doc.get("completed") or match_doc.get("failed"):
            return
        day = _safe_day(match_doc.get("created_at")) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cat = match_doc.get("primary_category") or "unknown"
        tk = match_doc.get("tokens", {}) or {}
        inp = tk.get("input_est", tk.get("input", 0)) or 0
        out = tk.get("output_est", tk.get("output", 0)) or 0
        mu = match_doc.get("model_used", {}) or {}
        prov, model = mu.get("provider", "unknown"), mu.get("model", "unknown")
        cost = _admin._price_match(inp, out, prov, model)
        from pymongo import UpdateOne
        ops = [
            UpdateOne({"date": day, "category": c},
                      {"$inc": {"matches": 1, "input_tokens": inp, "output_tokens": out, "cost": cost}},
                      upsert=True)
            for c in (cat, "_total")
        ]
        await db.daily_stats.bulk_write(ops, ordered=False)
        mk = f"{prov}/{model}"
        if mk != "unknown/unknown":
            # `model` stored as a value (not a field key) → safe for dotted names.
            await db.model_match_stats.update_one(
                {"model": mk},
                {"$inc": {"matches": 1, "input_tokens": inp, "output_tokens": out}},
                upsert=True,
            )
    except Exception as e:
        logger.warning(f"[ADMIN2] record_match_daily_stat failed: {e}")


async def record_paper_daily_stat(category: str, added_at=None):
    """Increment daily_stats papers count on a new paper."""
    try:
        day = _safe_day(added_at) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cat = category or "unknown"
        from pymongo import UpdateOne
        ops = [UpdateOne({"date": day, "category": c}, {"$inc": {"papers": 1}}, upsert=True)
               for c in (cat, "_total")]
        await db.daily_stats.bulk_write(ops, ordered=False)
    except Exception as e:
        logger.warning(f"[ADMIN2] record_paper_daily_stat failed: {e}")


async def record_summary_daily_stat(category: str, model_key: str, added_at=None, tokens=None):
    """Increment daily_stats summaries count + summary_cost on a new summary.

    Uses ACTUAL token counts when provided (accurate); falls back to the
    fixed average estimate only when the generation didn't report tokens.
    """
    try:
        day = _safe_day(added_at) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cat = category or "unknown"
        pin, pout = _price_for_summary(model_key)
        if tokens and (tokens.get("input") or tokens.get("output")):
            inp = tokens.get("input", 0) or 0
            out = tokens.get("output", 0) or 0
        else:
            inp, out = AVG_IN, AVG_OUT
        cost = (inp / 1_000_000) * pin + (out / 1_000_000) * pout
        from pymongo import UpdateOne
        ops = [UpdateOne({"date": day, "category": c},
                         {"$inc": {"summaries": 1, "summary_cost": cost}}, upsert=True)
               for c in (cat, "_total")]
        await db.daily_stats.bulk_write(ops, ordered=False)
        # Per-model summary totals (model stored as a value → safe for dotted keys).
        await db.model_summary_stats.update_one(
            {"model": model_key},
            {"$inc": {"summaries": 1, "input_tokens": inp, "output_tokens": out, "cost": cost}},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[ADMIN2] record_summary_daily_stat failed: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Backfill (background only, never on read path)
# ──────────────────────────────────────────────────────────────────────────

async def _run_backfill():
    """Full-range, cumulative rebuild of daily_stats + per-model match totals.

    Reuses the legacy per-chunk function (correct per chunk) but loops the FULL
    date range so per-model totals are cumulative (the legacy whole-run
    accumulator had a resume bug that made the meta doc partial). Bounded by
    7-day chunks using the created_at index — never an unbounded scan.
    """
    if getattr(_admin, "_ts_backfill_running", False):
        return
    if not await _acquire_backfill_lock():
        logger.info("[ADMIN2] full backfill skipped — lock held by another pod")
        return
    _admin._ts_backfill_running = True
    try:
        from datetime import date as _date, timedelta as _td, datetime as _dt, timezone as _tz
        earliest = await db.papers.find_one(
            {"added_at": {"$exists": True, "$ne": None}},
            {"_id": 0, "added_at": 1}, sort=[("added_at", 1)],
        )
        if not earliest or not earliest.get("added_at"):
            return
        ea = earliest["added_at"]
        start = ea.strftime("%Y-%m-%d") if hasattr(ea, "strftime") else str(ea)[:10]
        today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
        cur = _date.fromisoformat(start)
        end = _date.fromisoformat(today) + _td(days=1)

        # Build the ordered list of [from, to) chunk ranges once so we can retry
        # any that fail rather than silently dropping their matches (the failure
        # mode behind the production undercount).
        ranges = []
        while cur < end:
            ce = min(cur + _td(days=7), end)
            ranges.append((cur.isoformat(), ce.isoformat()))
            cur = ce

        async def _process_ranges(rs):
            """Run the given chunk ranges; return (accumulated models, failures)."""
            models, failed = {}, []
            for df, dtq in rs:
                try:
                    _, mt = await _admin._backfill_daily_stats_chunk(df, dtq)
                    for mk, ms in mt.items():
                        a = models.setdefault(mk, {"matches": 0, "input_tokens": 0, "output_tokens": 0})
                        for f in ("matches", "input_tokens", "output_tokens"):
                            a[f] += ms.get(f, 0)
                except Exception as ce_err:
                    logger.warning(f"[ADMIN2] backfill chunk [{df}..{dtq}) failed: {ce_err}")
                    failed.append((df, dtq))
            return models, failed

        all_models, failed_ranges = await _process_ranges(ranges)
        # One bounded retry of only the chunks that failed (e.g. transient Atlas
        # timeout). Merge their model totals into the running accumulator.
        if failed_ranges:
            logger.warning(f"[ADMIN2] retrying {len(failed_ranges)} failed chunk(s)")
            retry_models, failed_ranges = await _process_ranges(failed_ranges)
            for mk, a in retry_models.items():
                tgt = all_models.setdefault(mk, {"matches": 0, "input_tokens": 0, "output_tokens": 0})
                for f in ("matches", "input_tokens", "output_tokens"):
                    tgt[f] += a.get(f, 0)

        from pymongo import UpdateOne
        if all_models:
            await db.model_match_stats.delete_many({"model": {"$nin": list(all_models.keys())}})
            await db.model_match_stats.bulk_write(
                [UpdateOne({"model": mk}, {"$set": {"model": mk, **a}}, upsert=True)
                 for mk, a in all_models.items()], ordered=False)
            # Keep the legacy meta doc consistent too (benefits the old page).
            await db.daily_stats.update_one(
                {"_meta": "model_stats"},
                {"$set": {"_meta": "model_stats", "models": all_models}}, upsert=True)

        # Recompute summary counts + costs ACCURATELY (real tracked tokens where
        # available). Overwrites the chunk's fixed-average estimate so the cost
        # timeseries and the per-model summary panel reconcile on real data.
        await _backfill_summary_costs()
        await _backfill_registrations()

        # ── Completeness guard ───────────────────────────────────────────────
        # The per-model accumulator (`all_models`) is built straight from the
        # chunk results and is immune to the per-day `$set` overwrite, so its
        # match sum is the authoritative "expected" total. Compare it against the
        # materialized daily_stats `_total` sum: a meaningful gap means a chunk
        # silently dropped data (the exact production failure mode). Surface it
        # immediately via an ERROR log + a status doc instead of letting it hide
        # until the next ~12h self-heal.
        expected_matches = sum(a.get("matches", 0) for a in all_models.values())
        daily_matches = await _sum_daily_total_matches()
        # Tolerate tiny drift from live $inc hooks firing during the run (today's
        # in-flight matches). Flag only a material divergence (>0.5%).
        denom = expected_matches or 1
        diverged = bool(failed_ranges) or (abs(daily_matches - expected_matches) / denom > 0.005)
        status = {
            "_meta": "backfill_status",
            "ts": datetime.now(timezone.utc).isoformat(),
            "expected_matches": expected_matches,
            "daily_matches": daily_matches,
            "failed_chunks": len(failed_ranges),
            "reconciled": not diverged,
        }
        await db.daily_stats.update_one(
            {"_meta": "backfill_status"}, {"$set": status}, upsert=True)
        if diverged:
            logger.error(
                f"[ADMIN2] backfill NOT reconciled: daily_total={daily_matches} "
                f"expected={expected_matches} failed_chunks={len(failed_ranges)}")
        else:
            logger.info(
                f"[ADMIN2] backfill complete & reconciled: {len(all_models)} models, "
                f"{daily_matches} matches")
        _cache_clear()
    except Exception as e:
        logger.error(f"[ADMIN2] backfill failed: {e}")
    finally:
        _admin._ts_backfill_running = False
        await _release_backfill_lock()


async def _run_incremental_backfill(days_back: int = 10):
    """Cheap recent-days-only refresh of daily_stats.

    Past days are immutable once their matches are recorded, so only RECENT
    day-buckets can drift (from in-flight writes or a prior racey rebuild).
    Re-running just the last `days_back` days keeps the frequent self-heal O(days)
    instead of O(all-history), removing the recurring full-scan cost and shrinking
    the window for cross-pod contention. Distributed-locked so it never races a
    full rebuild. Does NOT touch all-time model_match_stats / accurate summary
    costs — those stay current via $inc hooks + the periodic full self_heal.
    """
    if getattr(_admin, "_ts_backfill_running", False):
        return
    if not await _acquire_backfill_lock(ttl=300):
        logger.info("[ADMIN2] incremental refresh skipped — lock held by another pod")
        return
    _admin._ts_backfill_running = True
    try:
        from datetime import date as _date, timedelta as _td, datetime as _dt, timezone as _tz
        today = _dt.now(_tz.utc).date()
        start = today - _td(days=days_back)
        end = today + _td(days=1)
        # Clear the recent day-buckets first so stale/racey values can't survive
        # (a day that should now be zero, or was overwritten with a partial sum,
        # gets fully recomputed from source). `_meta` docs have no `date` field
        # and are untouched.
        await db.daily_stats.delete_many(
            {"date": {"$gte": start.isoformat(), "$lt": end.isoformat()}})
        cur = start
        while cur < end:
            ce = min(cur + _td(days=7), end)
            try:
                await _admin._backfill_daily_stats_chunk(cur.isoformat(), ce.isoformat())
            except Exception as e:
                logger.warning(f"[ADMIN2] incremental chunk [{cur}..{ce}) failed: {e}")
            cur = ce
        await _backfill_registrations()
        _cache_clear()
        logger.info(f"[ADMIN2] incremental refresh complete (last {days_back}d)")
    except Exception as e:
        logger.warning(f"[ADMIN2] incremental backfill failed: {e}")
    finally:
        _admin._ts_backfill_running = False
        await _release_backfill_lock()


async def _sum_daily_total_matches() -> int:
    """Sum of `matches` across all daily_stats `_total` day-buckets (the
    materialized figure the cards/charts display)."""
    agg = await db.daily_stats.aggregate([
        {"$match": {"category": "_total"}},
        {"$group": {"_id": None, "m": {"$sum": "$matches"}}},
    ]).to_list(1)
    return int(agg[0]["m"]) if agg else 0


async def ensure_fresh():
    """Entry point for the frequent periodic scheduler task (leader only).

    Cold start / empty views → full rebuild. Otherwise → cheap incremental
    recent-days refresh (corrects any drift in recent buckets without an
    all-history scan). The periodic `self_heal` still does an occasional full
    re-sync to keep all-time model totals + accurate summary costs aligned.
    """
    try:
        n_days = await db.daily_stats.count_documents({"category": "_total"})
        n_sum = await db.model_summary_stats.estimated_document_count()
        if n_days < _SPARSE_THRESHOLD or n_sum == 0:
            await _run_backfill()  # one-time historical rebuild
        else:
            await _run_incremental_backfill()  # recent-days only (+ registrations)
        _cache_clear()
    except Exception as e:
        logger.warning(f"[ADMIN2] ensure_fresh failed: {e}")


async def self_heal():
    """Periodic full self-heal rebuild (runs less frequently than ensure_fresh)."""
    await _run_backfill()
    _cache_clear()


async def _backfill_summary_costs():
    """Recompute daily_stats `summaries` + `summary_cost` per day/category using
    ACTUAL per-summary tokens (papers.summary_tokens) where available, falling
    back to each model's own tracked average for untracked summaries. The grand
    total reconciles exactly with _build_summary_models() (same per-summary cost).
    """
    from collections import defaultdict
    from pymongo import UpdateOne

    settings = await get_settings()
    cat_set = set(settings.get("active_categories", list(CATEGORIES.keys())))

    def day_expr(f):
        return {"$substrCP": [{"$toString": {"$ifNull": [f"${f}", ""]}}, 0, 10]}

    # 1. Per-model tracked averages (for pricing untracked summaries accurately).
    model_avg = {}  # mk -> (avg_in, avg_out)
    async for doc in db.papers.aggregate([
        {"$match": {"summary_tokens": {"$exists": True, "$ne": {}}}},
        {"$project": {"pairs": {"$objectToArray": "$summary_tokens"}}},
        {"$unwind": "$pairs"},
        {"$match": {"pairs.v": {"$type": "object"}}},
        {"$group": {"_id": "$pairs.k",
                    "in": {"$sum": {"$ifNull": ["$pairs.v.input", 0]}},
                    "out": {"$sum": {"$ifNull": ["$pairs.v.output", 0]}},
                    "cnt": {"$sum": 1}}},
    ], allowDiskUse=True):
        cnt = doc["cnt"] or 1
        model_avg[doc["_id"]] = (doc["in"] / cnt, doc["out"] / cnt)

    cost_by = defaultdict(float)   # (day, cat) -> summary_cost
    cnt_by = defaultdict(int)      # (day, cat) -> summaries count
    tracked_cnt = defaultdict(int)  # (day, cat) -> tracked summaries count
    by_model = defaultdict(lambda: {"summaries": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})

    # 2a. Tracked tokens per day×category×model → exact cost.
    async for doc in db.papers.aggregate([
        {"$match": {"summary_tokens": {"$exists": True, "$ne": {}}}},
        {"$addFields": {"_day": day_expr("added_at"),
                        "_cat": {"$ifNull": [{"$arrayElemAt": ["$categories", 0]}, "unknown"]}}},
        {"$project": {"_day": 1, "_cat": 1, "pairs": {"$objectToArray": "$summary_tokens"}}},
        {"$unwind": "$pairs"},
        {"$match": {"pairs.v": {"$type": "object"}, "_day": {"$ne": ""}}},
        {"$group": {"_id": {"day": "$_day", "cat": "$_cat", "mk": "$pairs.k"},
                    "in": {"$sum": {"$ifNull": ["$pairs.v.input", 0]}},
                    "out": {"$sum": {"$ifNull": ["$pairs.v.output", 0]}},
                    "cnt": {"$sum": 1}}},
    ], allowDiskUse=True):
        day, cat, mk = doc["_id"]["day"], doc["_id"]["cat"], doc["_id"]["mk"]
        if cat not in cat_set:
            continue  # only active categories count toward the System total (tracked pass)
        pin, pout = _price_for_summary(mk)
        c = (doc["in"] / 1_000_000) * pin + (doc["out"] / 1_000_000) * pout
        cost_by[(day, cat)] += c
        cost_by[(day, "_total")] += c
        tracked_cnt[(day, cat)] += doc["cnt"]
        tracked_cnt[(day, "_total")] += doc["cnt"]
        m = by_model[mk]
        m["summaries"] += doc["cnt"]
        m["input_tokens"] += doc["in"]
        m["output_tokens"] += doc["out"]
        m["cost"] += c

    # 2b. Total summary counts per day×category×model (all keys, tracked or not).
    #     Untracked = total - tracked, priced at the model's tracked average.
    async for doc in db.papers.aggregate([
        {"$match": {"summaries": {"$exists": True, "$ne": {}}}},
        {"$addFields": {"_day": day_expr("added_at"),
                        "_cat": {"$ifNull": [{"$arrayElemAt": ["$categories", 0]}, "unknown"]}}},
        {"$project": {"_day": 1, "_cat": 1,
                      "keys": {"$map": {"input": {"$objectToArray": {"$ifNull": ["$summaries", {}]}},
                                        "as": "s", "in": "$$s.k"}}}},
        {"$unwind": "$keys"},
        {"$match": {"_day": {"$ne": ""}}},
        {"$group": {"_id": {"day": "$_day", "cat": "$_cat", "mk": "$keys"}, "cnt": {"$sum": 1}}},
    ], allowDiskUse=True):
        day, cat, mk = doc["_id"]["day"], doc["_id"]["cat"], doc["_id"]["mk"]
        if cat not in cat_set:
            continue  # only active categories count toward the System total (count pass)
        n = doc["cnt"]
        cnt_by[(day, cat)] += n
        cnt_by[(day, "_total")] += n

    # 2c. Untracked-summary cost: (total - tracked) per (day,cat) is hard to split
    #     by model here, so price untracked at a per-(day,cat) model-weighted avg.
    #     Instead recompute untracked cost from the count pipeline grouped by model.
    async for doc in db.papers.aggregate([
        {"$match": {"summaries": {"$exists": True, "$ne": {}}}},
        {"$addFields": {"_day": day_expr("added_at"),
                        "_cat": {"$ifNull": [{"$arrayElemAt": ["$categories", 0]}, "unknown"]},
                        "_tk": {"$objectToArray": {"$ifNull": ["$summary_tokens", {}]}}}},
        {"$project": {"_day": 1, "_cat": 1,
                      "tracked_keys": {"$map": {"input": "$_tk", "as": "t", "in": "$$t.k"}},
                      "keys": {"$map": {"input": {"$objectToArray": {"$ifNull": ["$summaries", {}]}},
                                        "as": "s", "in": "$$s.k"}}}},
        {"$project": {"_day": 1, "_cat": 1,
                      "untracked": {"$setDifference": ["$keys", "$tracked_keys"]}}},
        {"$unwind": "$untracked"},
        {"$match": {"_day": {"$ne": ""}}},
        {"$group": {"_id": {"day": "$_day", "cat": "$_cat", "mk": "$untracked"}, "cnt": {"$sum": 1}}},
    ], allowDiskUse=True):
        day, cat, mk = doc["_id"]["day"], doc["_id"]["cat"], doc["_id"]["mk"]
        if cat not in cat_set:
            continue  # only active categories count toward the System total (untracked pass)
        pin, pout = _price_for_summary(mk)
        avg_in, avg_out = model_avg.get(mk, (AVG_IN, AVG_OUT))
        c = doc["cnt"] * ((avg_in / 1_000_000) * pin + (avg_out / 1_000_000) * pout)
        cost_by[(day, cat)] += c
        cost_by[(day, "_total")] += c
        m = by_model[mk]
        m["summaries"] += doc["cnt"]
        m["input_tokens"] += int(avg_in * doc["cnt"])
        m["output_tokens"] += int(avg_out * doc["cnt"])
        m["cost"] += c

    # 3. Persist accurate summaries count + summary_cost per (day, category).
    keys = set(cost_by) | set(cnt_by)
    ops = [UpdateOne({"date": day, "category": cat},
                     {"$set": {"summaries": cnt_by.get((day, cat), 0),
                               "summary_cost": round(cost_by.get((day, cat), 0.0), 6)}},
                     upsert=True)
           for (day, cat) in keys]
    for i in range(0, len(ops), 500):
        await db.daily_stats.bulk_write(ops[i:i + 500], ordered=False)

    # 4. Persist per-model summary totals (same pass → reconciles with daily_stats).
    if by_model:
        await db.model_summary_stats.delete_many({"model": {"$nin": list(by_model.keys())}})
        await db.model_summary_stats.bulk_write(
            [UpdateOne({"model": mk},
                       {"$set": {"model": mk, "summaries": v["summaries"],
                                 "input_tokens": int(v["input_tokens"]),
                                 "output_tokens": int(v["output_tokens"]),
                                 "cost": round(v["cost"], 6)}}, upsert=True)
             for mk, v in by_model.items()], ordered=False)


def _is_leader_pod() -> bool:
    """Whether this pod holds scheduler leadership. The backfill only runs on the
    leader so concurrent rebuilds across pods are impossible by construction
    (the distributed lock is kept as defense-in-depth during leadership handoff)."""
    try:
        from services.scheduler import is_scheduler_leader
        return is_scheduler_leader()
    except Exception:
        return False


async def consume_backfill_request() -> bool:
    """Atomically claim a queued manual rebuild request (set by a non-leader pod
    that received POST /backfill). Returns True if one was pending."""
    doc = await db.admin2_lock.find_one_and_delete({"_id": "backfill_request"})
    return doc is not None


def _kick_backfill() -> bool:
    """Start the background backfill if not already running. LEADER-ONLY: on a
    non-leader pod this is a no-op (the leader's periodic loop keeps the views
    fresh), preventing cross-pod write races at the source. Returns True if a
    backfill is in progress (newly started or already running)."""
    if getattr(_admin, "_ts_backfill_running", False):
        return True
    if not _is_leader_pod():
        logger.info("[ADMIN2] backfill not kicked — this pod is not the leader")
        return False
    asyncio.ensure_future(_run_backfill())
    return True


# ──────────────────────────────────────────────────────────────────────────
# Read-path helpers
# ──────────────────────────────────────────────────────────────────────────

async def _build_summary_models() -> list:
    """Per-model summary panel from the model_summary_stats collection.

    Single source of truth: this collection is written by the same backfill pass
    (and write-time hook) that populates daily_stats.summary_cost, so the panel
    rows sum exactly to summary.summary_cost — no leaderboard-cache dependency.
    """
    out = []
    async for d in db.model_summary_stats.find({}, {"_id": 0}):
        count = d.get("summaries", 0) or 0
        if count <= 0:
            continue
        out.append({"name": d["model"], "count": count, "cost": round(d.get("cost", 0.0), 4)})
    total = sum(x["cost"] for x in out) or 1.0
    for x in out:
        x["pct"] = round(100.0 * x["cost"] / total, 1)
    out.sort(key=lambda x: -x["cost"])
    return out


def _build_match_models(model_totals: dict) -> list:
    """Per-model match panel. model_totals entries carry cost_total (computed
    by _build_series_from_daily_stats)."""
    out = []
    for mk, m in (model_totals or {}).items():
        out.append({"name": mk, "count": m.get("matches", 0), "cost": m.get("cost_total", 0.0)})
    total = sum(x["cost"] for x in out) or 1.0
    for x in out:
        x["pct"] = round(100.0 * x["cost"] / total, 1)
    out.sort(key=lambda x: -x["cost"])
    return out


async def record_registration(created_at=None):
    """Fire-and-forget increment of daily_registrations on a new signup."""
    try:
        day = _safe_day(created_at) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await db.daily_registrations.update_one(
            {"date": day}, {"$inc": {"count": 1}}, upsert=True)
    except Exception as e:
        logger.warning(f"[ADMIN2] record_registration failed: {e}")


async def _backfill_registrations():
    """Recompute daily_registrations from the users collection (bounded output:
    one doc per day). Keeps the read path O(days) instead of O(users)."""
    by_date = {}
    try:
        async for doc in db.users.aggregate([
            {"$match": {"created_at": {"$exists": True, "$ne": None}}},
            {"$project": {"day": {"$substrCP": [{"$toString": {"$ifNull": ["$created_at", ""]}}, 0, 10]}}},
            {"$match": {"day": {"$ne": ""}}},
            {"$group": {"_id": "$day", "n": {"$sum": 1}}},
        ]):
            by_date[doc["_id"]] = doc["n"]
    except Exception as e:
        logger.warning(f"[ADMIN2] registration backfill aggregation failed: {e}")
        return
    if by_date:
        from pymongo import UpdateOne
        await db.daily_registrations.bulk_write(
            [UpdateOne({"date": d}, {"$set": {"date": d, "count": n}}, upsert=True)
             for d, n in by_date.items()], ordered=False)


async def _user_registrations() -> list:
    """Cumulative user registrations over time, read from the precomputed
    daily_registrations collection (O(days), never scans the users collection)."""
    by_date = {}
    async for doc in db.daily_registrations.find({}, {"_id": 0}):
        if doc.get("date"):
            by_date[doc["date"]] = doc.get("count", 0)
    if not by_date:
        # First run before any backfill — populate once in the background.
        asyncio.ensure_future(_backfill_registrations())
    cum, out = 0, []
    for d in sorted(by_date):
        cum += by_date[d]
        out.append({"date": d, "daily": by_date[d], "cumulative": cum})
    return out


# ──────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────

@router.get("/stats-overview", dependencies=[Depends(verify_admin)])
async def stats_overview(category: Optional[str] = None, force: bool = False):
    """All stats in one response, read entirely from pre-aggregated data.

    Never scans matches/papers. If daily_stats is empty, a background backfill
    is kicked and we respond immediately with whatever data exists.
    """
    settings = await get_settings()
    cats = [category] if category else sorted(settings.get("active_categories", list(CATEGORIES.keys())))

    cache_key = category or "__all__"
    if not force:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    # 1. daily_stats (bounded by number of days — instant)
    total_by_date, cat_by_key = {}, {}
    async for doc in db.daily_stats.find({"category": "_total"}, {"_id": 0}):
        if doc.get("date"):
            total_by_date[doc["date"]] = doc
    async for doc in db.daily_stats.find({"category": {"$in": cats}}, {"_id": 0}):
        if doc.get("date"):
            cat_by_key[(doc["date"], doc["category"])] = doc

    backfilling = False
    summary_present = await db.model_summary_stats.estimated_document_count()
    if force or len(total_by_date) < _SPARSE_THRESHOLD or summary_present == 0:
        backfilling = _kick_backfill()

    # 2. per-model match totals (single source: model_match_stats collection)
    model_totals = {}
    async for d in db.model_match_stats.find({}, {"_id": 0}):
        if d.get("model"):
            model_totals[d["model"]] = {
                "matches": d.get("matches", 0),
                "input_tokens": d.get("input_tokens", 0),
                "output_tokens": d.get("output_tokens", 0),
            }

    # 3. timeseries series (pure builder; computes per-model match cost too)
    result = _admin._build_series_from_daily_stats(total_by_date, cat_by_key, cats, model_totals)
    totals = result["totals"]

    # 4. per-model panels (each reconciles with its daily_stats total by construction)
    match_models = _build_match_models(result.get("models", {}))
    summary_models = await _build_summary_models()
    user_series = await _user_registrations()
    backfill_status = await db.daily_stats.find_one({"_meta": "backfill_status"}, {"_id": 0, "_meta": 0})

    # 5. SINGLE SOURCE OF TRUTH: every aggregate number comes from daily_stats
    #    cumulative totals. Per-model panels are written by the same backfill pass
    #    so their row-sums equal these totals exactly.
    total_papers = totals.get("papers", 0)
    total_matches = totals.get("matches", 0)
    match_cost = totals.get("match_cost", 0.0)
    summary_cost = totals.get("summary_cost", 0.0)
    total_cost = round(match_cost + summary_cost, 4)
    pp = total_papers or 1

    summary = {
        "total_papers": total_papers,
        "total_matches": total_matches,
        "avg_matches_per_paper": round(total_matches / pp, 1),
        "input_tokens": totals.get("input_tokens", 0),
        "output_tokens": totals.get("output_tokens", 0),
        "total_tokens": totals.get("tokens", 0),
        "match_cost": round(match_cost, 4),
        "summary_cost": round(summary_cost, 4),
        "total_cost": total_cost,
        "cost_per_paper": round(total_cost / pp, 4),
        "match_cost_per_paper": round(match_cost / pp, 4),
        "summary_cost_per_paper": round(summary_cost / pp, 4),
    }

    # Objects consumed by the AdminStatistics component. All totals reference the
    # SAME daily_stats cumulative figures used by the cards and the charts, so the
    # cards, panel headers, rows, and timeseries are mutually consistent.
    result["refreshed_at"] = result.get("computed_at")
    stats = {
        "models": result.get("models", {}),
        "totals": {"total_cost": round(match_cost, 4), "total_matches": total_matches},
        "storage": {"total_papers": total_papers},
        "summaries": {
            "models": {m["name"]: {"summaries": m["count"], "cost_total": m["cost"]}
                       for m in summary_models},
            "totals": {"total_cost": round(summary_cost, 4)},
        },
    }

    response = {
        # Consumed by AdminStatistics:
        "timeseries": result,
        "stats": stats,
        # Standalone fields (also used by pytest regression):
        "summary": summary,
        "series": result["series"],
        "categories": result["categories"],
        "match_models": match_models,
        "summary_models": summary_models,
        "user_registrations": user_series,
        "backfilling": backfilling,
        "data_complete": len(total_by_date) >= _SPARSE_THRESHOLD,
        "backfill_status": backfill_status,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    if not backfilling:
        _cache_set(cache_key, response)
    return response


@router.post("/backfill", dependencies=[Depends(verify_admin)])
async def trigger_backfill():
    """Manually (re)build the daily_stats materialized view. LEADER-ONLY execution:
    if this pod is the leader it starts immediately; otherwise the request is
    queued and the leader picks it up within ~60s. This guarantees a single
    rebuilder cluster-wide (no cross-pod write races)."""
    already = getattr(_admin, "_ts_backfill_running", False)
    if _is_leader_pod():
        _kick_backfill()
        return {"started": True, "already_running": already, "leader": True}
    await db.admin2_lock.update_one(
        {"_id": "backfill_request"},
        {"$set": {"requested_at": datetime.now(timezone.utc)}}, upsert=True)
    return {"started": False, "already_running": already, "leader": False,
            "queued": True,
            "message": "Rebuild queued — the leader pod will run it within ~60s."}


@router.get("/memory", dependencies=[Depends(verify_admin)])
async def memory_usage(hours: int = Query(24, ge=1, le=168)):
    """RSS memory over a configurable window, downsampled to 1 point/minute."""
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    bucket_seconds = 60
    points = []
    pipeline = [
        {"$match": {"level": "mem", "ts": {"$gte": since}}},
        {"$addFields": {"bucket": {"$subtract": [
            {"$toLong": "$ts"}, {"$mod": [{"$toLong": "$ts"}, bucket_seconds * 1000]}]}}},
        {"$sort": {"rss_mb": -1}},
        {"$group": {
            "_id": {"bucket": "$bucket", "pod_role": {"$ifNull": ["$pod_role", "unknown"]}},
            "ts": {"$first": "$ts"},
            "rss_mb": {"$max": "$rss_mb"},
            "pod_role": {"$first": {"$ifNull": ["$pod_role", "unknown"]}},
        }},
        {"$sort": {"_id.bucket": 1}},
        {"$limit": hours * 60 * 3},
    ]
    try:
        async for doc in db.system_logs.aggregate(pipeline):
            ts = doc.get("ts")
            points.append({
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "rss_mb": round(doc["rss_mb"]) if doc.get("rss_mb") else None,
                "pod_role": doc.get("pod_role", "unknown"),
            })
    except Exception as e:
        logger.warning(f"[ADMIN2] memory aggregation failed: {e}")
    return {"points": points, "hours": hours}
