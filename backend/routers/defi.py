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
    subset: str = Query("all", description="Filter: all, ai, agents"),
    availability: str = Query("all", description="Filter: all, pdf, abstract_only"),
    group: str = Query("", description="Filter by tagged group (e.g. blockchain_ai_agents)"),
):
    """List DeFi papers. subset=ai/agents filters topic, availability=pdf/abstract_only filters by PDF."""
    query = {}
    
    if group:
        query["group"] = group
    elif subset == "ai":
        ai_terms = ["artificial intelligence", "machine learning", "deep learning", "neural network",
                     "reinforcement learning", "llm", "large language model", "gpt", "chatgpt",
                     "ai agent", "autonomous agent", "multi-agent", "intelligent agent", "agentic",
                     "ai-driven", "ai-powered", "ai-based"]
        subset_cond = {"$or": [
            {"title": {"$regex": "|".join(ai_terms), "$options": "i"}},
            {"abstract": {"$regex": "|".join(ai_terms[:8]), "$options": "i"}},
        ]}
        query = {"$and": [query, subset_cond]} if query else subset_cond
    elif subset == "agents":
        agent_terms = ["ai agent", "autonomous agent", "multi-agent", "intelligent agent",
                       "llm agent", "agentic", "agent-based", "on-chain agent",
                       "autonomous trading", "automated agent"]
        subset_cond = {"$or": [
            {"title": {"$regex": "|".join(agent_terms), "$options": "i"}},
            {"abstract": {"$regex": "|".join(agent_terms), "$options": "i"}},
        ]}
        query = {"$and": [query, subset_cond]} if query else subset_cond

    if availability == "pdf":
        query["pdf_downloaded"] = True
    elif availability == "abstract_only":
        query["pdf_downloaded"] = {"$ne": True}
    
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
        "ai_rating": "ai_rating",
    }.get(sort, "publication_date")
    sort_dir = -1 if dir == "desc" else 1

    total = await db.defi_papers.count_documents(query)
    papers = []
    async for doc in db.defi_papers.find(
        query,
        {"_id": 0, "title": 1, "authors": 1, "abstract": 1, "doi": 1,
         "ssrn_id": 1, "arxiv_id": 1, "publication_date": 1, "type": 1,
         "source": 1, "cited_by_count": 1, "keywords": 1, "topics": 1,
         "url": 1, "openalex_id": 1, "pdf_url": 1,
         "ai_rating": 1, "summary_scores": 1, "paper_id": 1,
         "tournament_score": 1, "tournament_win_rate": 1,
         "tournament_comparisons": 1, "tournament_wilson_margin": 1,
         "tournament_rank": 1, "gap_score": 1},
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
    pdf_downloaded = await db.defi_papers.count_documents({"pdf_downloaded": True})
    abstract_only = await db.defi_papers.count_documents({"pdf_downloaded": {"$ne": True}})

    ai_terms_regex = "artificial intelligence|machine learning|deep learning|neural network|reinforcement learning|llm|large language model|gpt|ai agent|autonomous agent|multi-agent|agentic|ai-driven|ai-powered"
    ai_count = await db.defi_papers.count_documents({"$or": [
        {"title": {"$regex": ai_terms_regex, "$options": "i"}},
        {"abstract": {"$regex": ai_terms_regex, "$options": "i"}},
    ]})

    agent_terms_regex = "ai agent|autonomous agent|multi-agent|intelligent agent|llm agent|agentic|agent-based|on-chain agent|autonomous trading|automated agent"
    agent_count = await db.defi_papers.count_documents({"$or": [
        {"title": {"$regex": agent_terms_regex, "$options": "i"}},
        {"abstract": {"$regex": agent_terms_regex, "$options": "i"}},
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

    blockchain_ai_agents_count = await db.defi_papers.count_documents({"group": "blockchain_ai_agents"})

    return {
        "total": total,
        "ai_count": ai_count,
        "agent_count": blockchain_ai_agents_count,
        "pdf_downloaded": pdf_downloaded,
        "abstract_only": abstract_only,
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
