"""Admin Database Explorer API — read-only root access to all MongoDB collections.

Provides generic query, aggregation, and inspection endpoints for debugging
and statistics without requiring direct database access.

All endpoints require admin authentication (X-Admin-Token header).
All responses exclude _id fields. Max 1000 documents per query.
"""

import json as json_mod
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel

from core.config import db, logger
from core.auth import verify_admin

router = APIRouter(prefix="/api/admin/db", tags=["admin-db-explorer"])

MAX_LIMIT = 1000
AGGREGATION_TIMEOUT_MS = 30000
BLOCKED_STAGES = {"$out", "$merge"}


def _parse_json_param(param: Optional[str], default=None):
    """Parse a JSON string query parameter."""
    if not param:
        return default
    try:
        return json_mod.loads(param)
    except (json_mod.JSONDecodeError, TypeError):
        raise HTTPException(400, f"Invalid JSON: {param}")


def _sanitize_doc(doc: dict) -> dict:
    """Remove _id and convert non-serializable types."""
    doc.pop("_id", None)
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
        elif isinstance(v, bytes):
            doc[k] = f"<bytes:{len(v)}>"
    return doc


# --- 1. List Collections ---

@router.get("/collections", dependencies=[Depends(verify_admin)])
async def list_collections():
    """List all collections with document counts."""
    names = await db.list_collection_names()
    result = []
    for name in sorted(names):
        if name.startswith("system."):
            continue
        count = await db[name].estimated_document_count()
        result.append({"name": name, "count": count})
    return {"collections": result}


# --- 2. Generic Document Query ---

@router.get("/{collection}", dependencies=[Depends(verify_admin)])
async def query_collection(
    collection: str,
    filter: Optional[str] = Query(None, description='MongoDB filter as JSON, e.g. {"arxiv_id":"2604.15034v1"}'),
    project: Optional[str] = Query(None, description='Projection as JSON, e.g. {"summaries":1,"ai_rating":1}'),
    sort: Optional[str] = Query(None, description='Sort as JSON, e.g. {"ts_score":-1}'),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    skip: int = Query(0, ge=0),
):
    """Query any collection with MongoDB-style filter, projection, sort, limit, skip."""
    if collection not in await db.list_collection_names():
        raise HTTPException(404, f"Collection '{collection}' not found")

    query_filter = _parse_json_param(filter, {})
    projection = _parse_json_param(project, {"_id": 0})
    if isinstance(projection, dict):
        projection["_id"] = 0
    sort_spec = _parse_json_param(sort)

    cursor = db[collection].find(query_filter, projection)
    if sort_spec:
        cursor = cursor.sort(list(sort_spec.items()))
    cursor = cursor.skip(skip).limit(limit)

    docs = []
    async for doc in cursor:
        docs.append(_sanitize_doc(doc))

    total = await db[collection].count_documents(query_filter) if len(docs) == limit else skip + len(docs)
    return {"collection": collection, "count": len(docs), "total": total, "skip": skip, "docs": docs}


# --- 3. Single Document by ID ---

@router.get("/{collection}/{doc_id}", dependencies=[Depends(verify_admin)])
async def get_document(collection: str, doc_id: str):
    """Get a single document by id, paper_id, or _id string."""
    if collection not in await db.list_collection_names():
        raise HTTPException(404, f"Collection '{collection}' not found")

    # Try common ID fields
    doc = None
    for field in ["id", "paper_id", "user_id", "key"]:
        doc = await db[collection].find_one({field: doc_id}, {"_id": 0})
        if doc:
            break

    if not doc:
        # Try as ObjectId string
        try:
            from bson import ObjectId
            doc = await db[collection].find_one({"_id": ObjectId(doc_id)}, {"_id": 0})
        except Exception:
            pass

    if not doc:
        raise HTTPException(404, f"Document '{doc_id}' not found in '{collection}'")

    return {"collection": collection, "doc": _sanitize_doc(doc)}


# --- 4. Aggregation Pipeline ---

class AggregationRequest(BaseModel):
    pipeline: list


@router.post("/{collection}/aggregate", dependencies=[Depends(verify_admin)])
async def run_aggregation(collection: str, body: AggregationRequest):
    """Run an aggregation pipeline. No write stages ($out, $merge) allowed."""
    if collection not in await db.list_collection_names():
        raise HTTPException(404, f"Collection '{collection}' not found")

    # Safety: block write stages
    for stage in body.pipeline:
        if isinstance(stage, dict):
            for key in stage:
                if key in BLOCKED_STAGES:
                    raise HTTPException(400, f"Stage '{key}' is not allowed (read-only)")

    # Add a $limit if not present to prevent runaway queries
    has_limit = any("$limit" in s for s in body.pipeline if isinstance(s, dict))
    if not has_limit:
        body.pipeline.append({"$limit": MAX_LIMIT})

    results = []
    async for doc in db[collection].aggregate(body.pipeline):
        # In aggregation results, _id is the group key — rename to "group" to avoid confusion
        if "_id" in doc:
            doc["group"] = doc.pop("_id")
        results.append(doc)

    return {"collection": collection, "count": len(results), "results": results}


# --- 5. Distinct Values ---

@router.get("/{collection}/distinct/{field}", dependencies=[Depends(verify_admin)])
async def get_distinct_values(
    collection: str,
    field: str,
    filter: Optional[str] = Query(None),
):
    """Get distinct values for a field, optionally filtered."""
    if collection not in await db.list_collection_names():
        raise HTTPException(404, f"Collection '{collection}' not found")

    query_filter = _parse_json_param(filter, {})
    values = await db[collection].distinct(field, query_filter)

    # Sanitize non-serializable values
    clean = []
    for v in values[:MAX_LIMIT]:
        if isinstance(v, datetime):
            clean.append(v.isoformat())
        elif isinstance(v, bytes):
            clean.append(f"<bytes:{len(v)}>")
        else:
            clean.append(v)

    return {"collection": collection, "field": field, "count": len(clean), "values": clean}


# --- 6. Collection Stats ---

@router.get("/{collection}/stats", dependencies=[Depends(verify_admin)])
async def collection_stats(collection: str):
    """Get collection statistics: count, indexes, sample document keys."""
    if collection not in await db.list_collection_names():
        raise HTTPException(404, f"Collection '{collection}' not found")

    count = await db[collection].estimated_document_count()
    indexes = await db[collection].index_information()

    # Get sample document to show field structure
    sample = await db[collection].find_one({}, {"_id": 0})
    fields = list(sample.keys()) if sample else []

    return {
        "collection": collection,
        "count": count,
        "indexes": {k: {"keys": v.get("key"), "unique": v.get("unique", False)} for k, v in indexes.items()},
        "fields": fields,
    }
