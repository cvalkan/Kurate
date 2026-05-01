"""DeFi papers API — serves the OpenAlex-sourced DeFi/crypto paper collection."""

from fastapi import APIRouter, Query
from core.config import db

router = APIRouter(prefix="/api/defi", tags=["defi"])


@router.get("/papers")
async def get_defi_papers(
    sort: str = Query("date", description="Sort by: date, citations, title"),
    dir: str = Query("desc", description="Sort direction: asc, desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Search title/authors/keywords"),
):
    """List DeFi papers with sorting and search."""
    query = {}
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"authors": {"$regex": search, "$options": "i"}},
            {"keywords": {"$regex": search, "$options": "i"}},
        ]

    sort_field = {
        "date": "publication_date",
        "citations": "cited_by_count",
        "title": "title",
    }.get(sort, "publication_date")
    sort_dir = -1 if dir == "desc" else 1

    total = await db.defi_papers.count_documents(query)
    papers = []
    async for doc in db.defi_papers.find(
        query,
        {"_id": 0, "title": 1, "authors": 1, "abstract": 1, "doi": 1,
         "ssrn_id": 1, "arxiv_id": 1, "publication_date": 1, "type": 1,
         "source": 1, "cited_by_count": 1, "keywords": 1, "topics": 1,
         "url": 1, "openalex_id": 1, "pdf_url": 1},
    ).sort(sort_field, sort_dir).skip(offset).limit(limit):
        papers.append(doc)

    return {
        "papers": papers,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/stats")
async def get_defi_stats():
    """Summary statistics for the DeFi collection."""
    total = await db.defi_papers.count_documents({})
    with_pdf = await db.defi_papers.count_documents({"pdf_url": {"$ne": None, "$ne": ""}})
    with_abstract = await db.defi_papers.count_documents({"abstract": {"$ne": ""}})

    # By year
    by_year = {}
    async for doc in db.defi_papers.aggregate([
        {"$group": {"_id": {"$substr": ["$publication_date", 0, 4]}, "count": {"$sum": 1}}},
        {"$sort": {"_id": -1}},
    ]):
        by_year[doc["_id"]] = doc["count"]

    # Top sources
    top_sources = []
    async for doc in db.defi_papers.aggregate([
        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]):
        top_sources.append({"source": doc["_id"], "count": doc["count"]})

    return {
        "total": total,
        "with_pdf": with_pdf,
        "with_abstract": with_abstract,
        "by_year": by_year,
        "top_sources": top_sources,
    }
