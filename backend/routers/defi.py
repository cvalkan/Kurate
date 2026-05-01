"""DeFi papers API — serves the OpenAlex-sourced DeFi/crypto paper collection."""

from fastapi import APIRouter, Query, Depends
from core.config import db
from core.auth import verify_admin

router = APIRouter(prefix="/api/defi", tags=["defi"])


@router.get("/papers")
async def get_defi_papers(
    sort: str = Query("date", description="Sort by: date, citations, title"),
    dir: str = Query("desc", description="Sort direction: asc, desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Search title/authors/keywords"),
    subset: str = Query("all", description="Filter: all, ai"),
):
    """List DeFi papers with sorting and search. subset=ai filters to AI/ML intersection."""
    query = {}
    
    if subset == "ai":
        ai_terms = ["ai agent", "autonomous agent", "multi-agent", "intelligent agent",
                     "llm agent", "on-chain agent", "agentic", "agent-based",
                     "large language model", "llm", "gpt", "chatgpt",
                     "reinforcement learning", "autonomous trading",
                     "ai-driven", "ai-powered", "ai-based"]
        query["$or"] = [
            {"title": {"$regex": "|".join(ai_terms), "$options": "i"}},
            {"abstract": {"$regex": "|".join(ai_terms), "$options": "i"}},
            {"keywords": {"$regex": "|".join(ai_terms), "$options": "i"}},
        ]
    
    if search:
        search_cond = {"$or": [
            {"title": {"$regex": search, "$options": "i"}},
            {"authors": {"$regex": search, "$options": "i"}},
            {"keywords": {"$regex": search, "$options": "i"}},
        ]}
        if query:
            query = {"$and": [query, search_cond]}
        else:
            query = search_cond

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

    ai_terms_regex = "ai agent|autonomous agent|multi-agent|intelligent agent|llm agent|on-chain agent|agentic|agent-based|large language model|llm|gpt|chatgpt|reinforcement learning|autonomous trading|ai-driven|ai-powered|ai-based"
    ai_count = await db.defi_papers.count_documents({"$or": [
        {"title": {"$regex": ai_terms_regex, "$options": "i"}},
        {"abstract": {"$regex": ai_terms_regex, "$options": "i"}},
    ]})
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
        "ai_count": ai_count,
        "with_pdf": with_pdf,
        "with_abstract": with_abstract,
        "by_year": by_year,
        "top_sources": top_sources,
    }


@router.post("/import", dependencies=[Depends(verify_admin)])
async def import_defi_papers(papers: list[dict]):
    """Bulk import DeFi papers. Used for one-time data migration."""
    saved = 0
    for p in papers:
        key = {"doi": p["doi"]} if p.get("doi") else {"title": p["title"]}
        await db.defi_papers.update_one(key, {"$set": p}, upsert=True)
        saved += 1
    return {"status": "ok", "saved": saved}
