"""Admin endpoints for syncing data between environments.

Export: paginated read of collections (admin-authed, read-only). Available everywhere.
Pull:   imports from a remote instance's export endpoints into LOCAL DB.
        DISABLED unless SYNC_PULL_ENABLED=true in .env (never set on production).
"""
import os
from fastapi import APIRouter, Depends, Query
from typing import Optional
import asyncio
import httpx
from core.config import db, logger
from core.auth import verify_admin

router = APIRouter(prefix="/api/admin/sync")

_PULL_ENABLED = os.environ.get("SYNC_PULL_ENABLED", "").lower() == "true"

# ── Export endpoints (read-only, serve data to other environments) ──────────

EXPORT_COLLECTIONS = {
    "papers": {
        "projection": {"_id": 0},
        "sort": [("added_at", -1)],
        "id_field": "id",
    },
    "matches": {
        "projection": {"_id": 0},
        "sort": [("created_at", -1)],
        "id_field": "id",
    },
    "rankings": {
        "projection": {"_id": 0},
        "sort": [("updated_at", -1)],
        "id_field": "paper_id",
    },
    "tournaments": {
        "projection": {"_id": 0},
        "sort": [("category", 1)],
        "id_field": "tournament_id",
    },
    "leaderboard_archives": {
        "projection": {"_id": 0},
        "sort": [("year", -1), ("week", -1)],
        "id_field": None,
    },
    "settings": {
        "projection": {"_id": 0},
        "sort": [("key", 1)],
        "id_field": "key",
    },
}


@router.get("/export/{collection}", dependencies=[Depends(verify_admin)])
async def export_collection(
    collection: str,
    since: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    category: Optional[str] = None,
):
    """Paginated read-only export of a collection. Use `since` for delta sync."""
    if collection not in EXPORT_COLLECTIONS:
        return {"error": f"Unknown collection. Available: {list(EXPORT_COLLECTIONS.keys())}"}

    config = EXPORT_COLLECTIONS[collection]
    query = {}

    if since:
        date_fields = ["added_at", "updated_at", "created_at"]
        or_clauses = [{f: {"$gte": since}} for f in date_fields]
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
    cursor = coll.find(query, config["projection"]).sort(config["sort"]).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)

    return {
        "collection": collection,
        "total": total,
        "skip": skip,
        "limit": limit,
        "count": len(docs),
        "has_more": skip + len(docs) < total,
        "docs": docs,
    }


@router.get("/export-stats", dependencies=[Depends(verify_admin)])
async def export_stats():
    """Collection sizes for planning imports."""
    stats = {}
    for name in EXPORT_COLLECTIONS:
        stats[name] = await db[name].count_documents({})
    return {"collections": stats}


# ── Pull: read from remote, write to LOCAL DB (never writes to remote) ──────

def _login_remote(source_url, password):
    """Authenticate with remote via subprocess curl to avoid Cloudflare/proxy issues."""
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
    """Fetch one page from remote export via subprocess curl."""
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


@router.post("/pull", dependencies=[Depends(verify_admin)])
async def pull_from_remote(
    source_url: str = "https://kurate.org",
    source_password: str = "",
    collections: str = "papers,matches,rankings,tournaments",
    since: Optional[str] = None,
    category: Optional[str] = None,
    dry_run: bool = False,
):
    """Pull data from a remote instance into the LOCAL database.

    Disabled unless SYNC_PULL_ENABLED=true is set in .env.
    This must NEVER be set on production to prevent accidental overwrites.
    """
    if not _PULL_ENABLED:
        return {"error": "Pull is disabled on this instance. Set SYNC_PULL_ENABLED=true in .env to enable (never on production)."}

    collection_list = [c.strip() for c in collections.split(",") if c.strip() in EXPORT_COLLECTIONS]
    if not collection_list:
        return {"error": f"No valid collections. Available: {list(EXPORT_COLLECTIONS.keys())}"}

    # Authenticate with remote (sync httpx in thread to avoid event loop conflicts)
    try:
        token = await asyncio.to_thread(_login_remote, source_url, source_password)
        if not token:
            return {"error": "Failed to authenticate with remote instance"}
    except Exception as e:
        return {"error": f"Failed to connect to {source_url}: {str(e)[:200]}"}

    results = {}
    for coll_name in collection_list:
        config = EXPORT_COLLECTIONS[coll_name]
        id_field = config["id_field"]
        inserted = 0
        updated = 0
        skipped = 0
        errors = 0
        total_remote = 0
        skip = 0
        page_size = 1000

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

                if not docs:
                    break

                if not dry_run:
                    for doc in docs:
                        try:
                            if id_field and doc.get(id_field):
                                result = await db[coll_name].update_one(
                                    {id_field: doc[id_field]},
                                    {"$set": doc},
                                    upsert=True,
                                )
                                if result.upserted_id:
                                    inserted += 1
                                elif result.modified_count > 0:
                                    updated += 1
                                else:
                                    skipped += 1
                            else:
                                await db[coll_name].insert_one(doc)
                                inserted += 1
                        except Exception as e:
                            errors += 1
                            if errors <= 3:
                                logger.warning(f"Sync pull error ({coll_name}): {e}")
                else:
                    inserted = total_remote

                if not data["has_more"]:
                    break
                skip += page_size
                await asyncio.sleep(0.5)

            results[coll_name] = {
                "remote_total": total_remote,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "errors": errors,
            }
            logger.info(f"Sync pull {coll_name}: {inserted} inserted, {updated} updated, {skipped} unchanged, {errors} errors (from {total_remote} remote)")

        except Exception as e:
            results[coll_name] = {"error": str(e)[:200]}
            logger.error(f"Sync pull {coll_name} failed: {e}")

    if not dry_run and any(r.get("inserted", 0) > 0 or r.get("updated", 0) > 0 for r in results.values()):
        from routers.leaderboard import notify_data_changed
        notify_data_changed()

    return {
        "source": source_url,
        "direction": "remote -> local (read-only pull)",
        "collections": results,
        "since": since,
        "category": category,
        "dry_run": dry_run,
    }
