"""Admin endpoints for syncing data between environments.

Export: paginated read of collections (admin-authed, read-only). Available everywhere.
Pull:   imports from a remote instance's export endpoints into LOCAL DB.
        DISABLED unless SYNC_PULL_ENABLED=true in .env (never set on production).
        Runs in the background; poll /pull-status for progress.
"""
import os
from fastapi import APIRouter, Depends, Query, Request
from typing import Optional
from datetime import datetime, timezone
import asyncio
from core.config import db, logger
from core.auth import verify_admin

router = APIRouter(prefix="/api/admin/sync")

_PULL_ENABLED = os.environ.get("SYNC_PULL_ENABLED", "").lower() == "true"

# Background pull state
_pull_state = {"running": False, "progress": {}, "result": None}

# ── Export endpoints (read-only) ────────────────────────────────────────────

EXPORT_COLLECTIONS = {
    "papers": {"projection": {"_id": 0}, "sort": [("added_at", -1)], "id_field": "id"},
    "matches": {"projection": {"_id": 0}, "sort": [("created_at", -1)], "id_field": "id"},
    "rankings": {"projection": {"_id": 0}, "sort": [("updated_at", -1)], "id_field": "paper_id"},
    "tournaments": {"projection": {"_id": 0}, "sort": [("category", 1)], "id_field": "tournament_id"},
    "leaderboard_archives": {"projection": {"_id": 0}, "sort": [("year", -1), ("week", -1)], "id_field": "_composite", "composite_key": ["category", "year", "period_type", "week", "month"]},
    "settings": {"projection": {"_id": 0}, "sort": [("key", 1)], "id_field": "key"},
}


@router.get("/export/{collection}", dependencies=[Depends(verify_admin)])
async def export_collection(
    collection: str,
    since: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    category: Optional[str] = None,
):
    """Paginated read-only export of a collection."""
    if collection not in EXPORT_COLLECTIONS:
        return {"error": f"Unknown collection. Available: {list(EXPORT_COLLECTIONS.keys())}"}

    config = EXPORT_COLLECTIONS[collection]
    query = {}
    if since:
        or_clauses = [{f: {"$gte": since}} for f in ["added_at", "updated_at", "created_at"]]
        query["$or"] = or_clauses
    if category:
        if collection == "papers":
            query["categories.0"] = category
        elif collection == "matches":
            query["primary_category"] = category
        elif collection in ("rankings", "tournaments"):
            query["category"] = category

    coll = db[collection]
    total = await coll.count_documents(query)
    docs = await coll.find(query, config["projection"]).sort(config["sort"]).skip(skip).limit(limit).to_list(length=limit)

    return {
        "collection": collection, "total": total,
        "skip": skip, "limit": limit, "count": len(docs),
        "has_more": skip + len(docs) < total, "docs": docs,
    }


@router.get("/export-stats", dependencies=[Depends(verify_admin)])
async def export_stats():
    stats = {}
    for name in EXPORT_COLLECTIONS:
        stats[name] = await db[name].count_documents({})
    return {"collections": stats}


# ── Pull: background import from remote ─────────────────────────────────────

def _login_remote(source_url, password):
    import subprocess, json
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{source_url}/api/admin/login",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"password": password})],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise Exception(f"curl failed: {result.stderr[:200]}")
    data = json.loads(result.stdout)
    if not data.get("success"):
        raise Exception(f"Login failed: {result.stdout[:200]}")
    return data.get("token")


def _fetch_remote_page(source_url, token, collection, params):
    import subprocess, json, urllib.parse
    qs = urllib.parse.urlencode(params)
    url = f"{source_url}/api/admin/sync/export/{collection}?{qs}"
    result = subprocess.run(
        ["curl", "-s", url, "-H", f"X-Admin-Token: {token}"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise Exception(f"curl failed: {result.stderr[:200]}")
    return json.loads(result.stdout)


async def _run_pull_bg(source_url, source_password, collection_list, since, category):
    """Background pull task."""
    global _pull_state
    _pull_state = {"running": True, "progress": {}, "result": None,
                   "started_at": datetime.now(timezone.utc).isoformat()}

    try:
        token = await asyncio.to_thread(_login_remote, source_url, source_password)
    except Exception as e:
        _pull_state = {"running": False, "progress": {}, "result": {"error": str(e)[:200]}}
        return

    results = {}
    for coll_name in collection_list:
        config = EXPORT_COLLECTIONS[coll_name]
        id_field = config["id_field"]
        inserted = updated = skipped = errors = 0
        total_remote = 0
        skip = 0
        page_size = 500

        _pull_state["progress"][coll_name] = {"status": "pulling", "fetched": 0, "total": 0}

        try:
            while True:
                params = {"skip": skip, "limit": page_size}
                if since:
                    params["since"] = since
                if category:
                    params["category"] = category

                data = await asyncio.to_thread(
                    _fetch_remote_page, source_url, token, coll_name, params
                )
                total_remote = data["total"]
                docs = data["docs"]
                _pull_state["progress"][coll_name]["total"] = total_remote

                if not docs:
                    break

                for doc in docs:
                    try:
                        composite_key = config.get("composite_key")
                        if composite_key:
                            filt = {k: doc.get(k) for k in composite_key if doc.get(k) is not None}
                            if len(filt) >= 2:
                                r = await db[coll_name].update_one(filt, {"$set": doc}, upsert=True)
                                if r.upserted_id: inserted += 1
                                elif r.modified_count > 0: updated += 1
                                else: skipped += 1
                            else:
                                await db[coll_name].insert_one(doc)
                                inserted += 1
                        elif id_field and doc.get(id_field):
                            r = await db[coll_name].update_one(
                                {id_field: doc[id_field]}, {"$set": doc}, upsert=True,
                            )
                            if r.upserted_id: inserted += 1
                            elif r.modified_count > 0: updated += 1
                            else: skipped += 1
                        else:
                            await db[coll_name].insert_one(doc)
                            inserted += 1
                    except Exception as e:
                        errors += 1
                        if errors <= 3:
                            logger.warning(f"Sync pull error ({coll_name}): {e}")

                _pull_state["progress"][coll_name]["fetched"] = skip + len(docs)

                if not data["has_more"]:
                    break
                skip += page_size
                await asyncio.sleep(0.2)

            results[coll_name] = {
                "remote_total": total_remote, "inserted": inserted,
                "updated": updated, "skipped": skipped, "errors": errors,
            }
            _pull_state["progress"][coll_name]["status"] = "done"
            logger.info(f"Sync pull {coll_name}: {inserted} ins, {updated} upd, {skipped} skip, {errors} err (from {total_remote})")

        except Exception as e:
            results[coll_name] = {"error": str(e)[:200]}
            _pull_state["progress"][coll_name]["status"] = f"error: {str(e)[:100]}"
            logger.error(f"Sync pull {coll_name} failed: {e}")

    if any(r.get("inserted", 0) > 0 or r.get("updated", 0) > 0 for r in results.values()):
        from routers.leaderboard import notify_data_changed
        notify_data_changed()

    _pull_state = {
        "running": False,
        "progress": _pull_state["progress"],
        "result": {"source": source_url, "collections": results},
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/pull", dependencies=[Depends(verify_admin)])
async def pull_from_remote(request: Request):
    """Start a background pull from a remote instance. Poll /pull-status for progress."""
    if not _PULL_ENABLED:
        return {"error": "Pull is disabled. Set SYNC_PULL_ENABLED=true in .env (never on production)."}
    if _pull_state.get("running"):
        return {"error": "Pull already running", "progress": _pull_state["progress"]}

    body = await request.json()
    source_url = body.get("source_url", "https://kurate.org")
    source_password = body.get("source_password", "")
    collections = body.get("collections", "papers,matches,rankings,tournaments")
    since = body.get("since")
    category = body.get("category")

    collection_list = [c.strip() for c in collections.split(",") if c.strip() in EXPORT_COLLECTIONS]
    if not collection_list:
        return {"error": f"No valid collections. Available: {list(EXPORT_COLLECTIONS.keys())}"}

    asyncio.create_task(_run_pull_bg(source_url, source_password, collection_list, since, category))
    return {"status": "started", "collections": collection_list}


@router.get("/pull-status", dependencies=[Depends(verify_admin)])
async def pull_status():
    """Poll this to check background pull progress."""
    return _pull_state
