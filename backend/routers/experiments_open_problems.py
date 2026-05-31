"""Experimental: open-problems extraction results endpoint.

Serves the documents that `tools/extract_open_problems.py` deposits in the
`open_problems` collection. Kept under a distinct router so we can swap the
storage layer later (e.g. denormalize once the experiment is settled).
"""
from fastapi import APIRouter, Query
from typing import Optional
from server import db

router = APIRouter(prefix="/api/experiments/open-problems", tags=["experiments"])


@router.get("")
async def list_open_problems(
    source_section: Optional[str] = Query(None),
    scope: Optional[str] = Query(None, description='paper_specific | field_general'),
    paper_id: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
):
    """List extracted open problems. Default: 500 most-recently-extracted."""
    q = {}
    if source_section:
        q["source_section"] = source_section
    if scope:
        q["scope"] = scope
    if paper_id:
        q["paper_id"] = paper_id

    cursor = db.open_problems.find(q, {"_id": 0}).sort("paper_score", -1).limit(limit)
    rows = [doc async for doc in cursor]

    total = await db.open_problems.count_documents(q)
    papers_with_problems = await db.open_problems.distinct("paper_id", q)
    papers_meta = await db.open_problems_meta.count_documents({})
    papers_no_problems = await db.open_problems_meta.count_documents({"no_problems": True})

    return {
        "problems": rows,
        "total": total,
        "papers_with_problems": len(papers_with_problems),
        "papers_total": papers_meta,
        "papers_no_problems": papers_no_problems,
    }


@router.get("/meta")
async def list_meta():
    """One row per processed paper — including ones with no problems."""
    cursor = db.open_problems_meta.find({}, {"_id": 0}).sort("paper_score", -1)
    return {"rows": [d async for d in cursor]}
