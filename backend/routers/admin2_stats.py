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
from datetime import datetime, timezone
import asyncio

from core.config import db, logger, CATEGORIES
from core.auth import verify_admin, get_settings
import routers.admin as _admin
import routers.leaderboard as _lb

router = APIRouter(prefix="/api/admin2")

# Average tokens for an untracked summary generation (fallback pricing)
AVG_IN, AVG_OUT = 10375, 1788


def _safe_day(raw) -> Optional[str]:
    """Extract YYYY-MM-DD from a value that may be a BSON Date or a string."""
    if raw is None:
        return None
    return raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]


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


async def record_summary_daily_stat(category: str, model_key: str, added_at=None):
    """Increment daily_stats summaries count + summary_cost on a new summary."""
    try:
        day = _safe_day(added_at) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cat = category or "unknown"
        provider = model_key.split(":")[0] if ":" in model_key else model_key
        pk = _admin._SUMMARY_PRICING.get(provider, "anthropic/claude-opus-4-6")
        cost = _admin._price_match(AVG_IN, AVG_OUT, *pk.split("/"))
        from pymongo import UpdateOne
        ops = [UpdateOne({"date": day, "category": c},
                         {"$inc": {"summaries": 1, "summary_cost": cost}}, upsert=True)
               for c in (cat, "_total")]
        await db.daily_stats.bulk_write(ops, ordered=False)
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

        all_models = {}
        while cur < end:
            ce = min(cur + _td(days=7), end)
            try:
                _, mt = await _admin._backfill_daily_stats_chunk(cur.isoformat(), ce.isoformat())
                for mk, ms in mt.items():
                    a = all_models.setdefault(mk, {"matches": 0, "input_tokens": 0, "output_tokens": 0})
                    for f in ("matches", "input_tokens", "output_tokens"):
                        a[f] += ms.get(f, 0)
            except Exception as ce_err:
                logger.warning(f"[ADMIN2] backfill chunk [{cur}..{ce}) failed: {ce_err}")
            cur = ce

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
        logger.info(f"[ADMIN2] backfill complete: {len(all_models)} models")
    except Exception as e:
        logger.error(f"[ADMIN2] backfill failed: {e}")
    finally:
        _admin._ts_backfill_running = False


def _kick_backfill() -> bool:
    """Start the background backfill if not already running. Returns True if
    a backfill is in progress (newly started or already running)."""
    if getattr(_admin, "_ts_backfill_running", False):
        return True
    asyncio.ensure_future(_run_backfill())
    return True


# ──────────────────────────────────────────────────────────────────────────
# Read-path helpers
# ──────────────────────────────────────────────────────────────────────────

def _build_summary_models() -> list:
    """Per-model summary panel from the in-memory leaderboard cache."""
    ss = (_lb._cache or {}).get("_summary_stats", {}) or {}
    allm = ss.get("__all__", {}).get("models", {}) or {}
    out = []
    for mk, m in allm.items():
        count = m.get("summaries", 0) or 0
        if count <= 0:
            continue
        ti, to, tc = m.get("tracked_input", 0), m.get("tracked_output", 0), m.get("tracked_count", 0)
        provider = mk.split(":")[0] if ":" in mk else mk
        pk = _admin._SUMMARY_PRICING.get(provider, "anthropic/claude-opus-4-6")
        p = _admin.MODEL_PRICING.get(pk, {"input": 2.0, "output": 10.0})
        if tc and ti:
            avg_in, avg_out = ti / tc, to / tc
        else:
            avg_in, avg_out = AVG_IN, AVG_OUT
        cost = (avg_in * count / 1_000_000) * p["input"] + (avg_out * count / 1_000_000) * p["output"]
        out.append({"name": mk, "count": count, "cost": round(cost, 4)})
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


async def _user_registrations() -> list:
    """Cumulative user registrations over time. Bounded by user count (small).
    Type-safe for BSON Date vs string created_at."""
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
        logger.warning(f"[ADMIN2] user registration aggregation failed: {e}")
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

    # 1. daily_stats (bounded by number of days — instant)
    total_by_date, cat_by_key = {}, {}
    async for doc in db.daily_stats.find({"category": "_total"}, {"_id": 0}):
        if doc.get("date"):
            total_by_date[doc["date"]] = doc
    async for doc in db.daily_stats.find({"category": {"$in": cats}}, {"_id": 0}):
        if doc.get("date"):
            cat_by_key[(doc["date"], doc["category"])] = doc

    backfilling = False
    if force or len(total_by_date) < 5:
        backfilling = _kick_backfill()

    # 2. per-model match totals
    model_totals = {}
    async for d in db.model_match_stats.find({}, {"_id": 0}):
        if d.get("model"):
            model_totals[d["model"]] = {
                "matches": d.get("matches", 0),
                "input_tokens": d.get("input_tokens", 0),
                "output_tokens": d.get("output_tokens", 0),
            }
    if not model_totals:
        meta = await db.daily_stats.find_one({"_meta": "model_stats"}, {"_id": 0})
        if meta:
            model_totals = meta.get("models", {}) or {}

    # 3. timeseries series (pure builder; computes per-model cost too)
    result = _admin._build_series_from_daily_stats(total_by_date, cat_by_key, cats, model_totals)
    totals = result["totals"]

    # 4. panels
    match_models = _build_match_models(result.get("models", {}))
    summary_models = _build_summary_models()
    user_series = await _user_registrations()

    # 5. summary cards — papers/matches from cheap leaderboard snapshot, fall
    #    back to daily_stats cumulative if the cache hasn't warmed.
    lb = _lb._cache or {}
    total_papers = lb.get("total_papers") or totals.get("papers", 0)
    total_matches = lb.get("total_matches") or totals.get("matches", 0)
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

    return {
        "summary": summary,
        "series": result["series"],
        "categories": result["categories"],
        "match_models": match_models,
        "summary_models": summary_models,
        "user_registrations": user_series,
        "backfilling": backfilling,
        "data_complete": len(total_by_date) >= 5,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/backfill", dependencies=[Depends(verify_admin)])
async def trigger_backfill():
    """Manually (re)build the daily_stats materialized view in the background."""
    already = getattr(_admin, "_ts_backfill_running", False)
    _kick_backfill()
    return {"started": True, "already_running": already}


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
