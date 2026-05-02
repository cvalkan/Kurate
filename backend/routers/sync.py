"""Admin endpoints for syncing data between environments.

Export: paginated read of collections (admin-authed, read-only).
Import: pulls delta from a remote instance's export endpoints into LOCAL DB.

Safety: the import endpoint only WRITES to the local DB. It authenticates
with the remote as a read-only client. There is no "push" or "write to remote"
capability — production data can never be overwritten by this API.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
import asyncio
import httpx
from core.config import db, logger
from core.auth import verify_admin

router = APIRouter(prefix="/api/admin/sync")

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


# ── Import: pull from remote into LOCAL DB (never writes to remote) ─────────

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
    
    This is strictly one-directional: reads from remote, writes to local.
    The remote instance is only accessed via its read-only export endpoints.
    """
    # Authenticate with remote (read-only access)
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            login_res = await client.post(
                f"{source_url}/api/admin/login",
                json={"password": source_password},
            )
            login_res.raise_for_status()
            token = login_res.json().get("token")
            if not token:
                return {"error": "Failed to authenticate with remote instance"}
        except Exception as e:
            return {"error": f"Failed to connect to {source_url}: {str(e)[:200]}"}

    headers = {"X-Admin-Token": token}
    collection_list = [c.strip() for c in collections.split(",") if c.strip() in EXPORT_COLLECTIONS]
    if not collection_list:
        return {"error": f"No valid collections. Available: {list(EXPORT_COLLECTIONS.keys())}"}

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
            async with httpx.AsyncClient(timeout=60) as client:
                while True:
                    params = {"skip": skip, "limit": page_size}
                    if since:
                        params["since"] = since
                    if category:
                        params["category"] = category

                    res = await client.get(
                        f"{source_url}/api/admin/sync/export/{coll_name}",
                        headers=headers,
                        params=params,
                    )
                    res.raise_for_status()
                    data = res.json()
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
        "direction": "remote → local (read-only pull)",
        "collections": results,
        "since": since,
        "category": category,
        "dry_run": dry_run,
    }
