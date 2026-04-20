"""Admin routes for X/Twitter outreach handle discovery."""

import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.config import db, logger
from routers.admin import verify_admin

router = APIRouter(prefix="/api/admin/outreach", tags=["admin-outreach"])


class DiscoverRequest(BaseModel):
    category: Optional[str] = None  # None = all categories
    period: str = "all"  # "recent", "7d", "30d", "all", or "archive:YYYY-WW"
    top_n: int = 10


_discover_status = {"running": False, "category": None, "progress": 0, "total": 0}


@router.post("/discover", dependencies=[Depends(verify_admin)])
async def discover_handles(body: DiscoverRequest):
    """Discover X handles for top-N papers. Runs in background, returns immediately."""
    from services.twitter import discover_handles_batch

    if _discover_status["running"]:
        return {"status": "already_running", "progress": _discover_status["progress"], "total": _discover_status["total"]}

    papers = await _get_papers_for_period(body.category, body.period, body.top_n)
    if not papers:
        return {"status": "no_papers", "message": "No papers found for this selection."}

    _discover_status["running"] = True
    _discover_status["category"] = body.category
    _discover_status["progress"] = 0
    _discover_status["total"] = len(papers)

    async def _run():
        try:
            results = await discover_handles_batch(papers)
            _discover_status["progress"] = len(results)
        except Exception as e:
            logger.error(f"Discovery failed: {e}")
        finally:
            _discover_status["running"] = False

    asyncio.create_task(_run())

    return {
        "status": "started",
        "total_requested": len(papers),
        "message": f"Searching X for {len(papers)} papers in background. Refresh to see results.",
    }


@router.get("/discover-status", dependencies=[Depends(verify_admin)])
async def discover_status():
    """Check discovery progress."""
    return _discover_status


@router.get("/medalists", dependencies=[Depends(verify_admin)])
async def get_medalists(period: str = "current", top_n: int = 3):
    """Get top-N medalists across all categories.
    
    period: "weekly:YYYY-WW" or "monthly:YYYY-MM"
    Returns: {categories: [{category, name, papers: [{rank, title, authors, ...}]}]}
    """
    from core.config import CATEGORIES

    cat_names = dict(CATEGORIES)
    result_cats = []

    # Parse period
    if period.startswith("weekly:"):
        parts = period.split(":")[1].split("-")
        period_type, query_filter = "weekly", {"year": int(parts[0]), "week": int(parts[1])}
    elif period.startswith("monthly:"):
        parts = period.split(":")[1].split("-")
        period_type, query_filter = "monthly", {"year": int(parts[0]), "month": int(parts[1])}
    else:
        return {"period": period, "categories": [], "total_papers": 0, "total_discovered": 0,
                "error": "Use weekly:YYYY-WW or monthly:YYYY-MM"}

    async for archive in db.leaderboard_archives.find(
        {"period_type": period_type, **query_filter},
        {"_id": 0, "category": 1, "leaderboard": {"$slice": top_n}, "label": 1},
    ):
        cat = archive["category"]
        papers = []
        for p in archive.get("leaderboard", [])[:top_n]:
            disc = await db.x_handle_discoveries.find_one(
                {"paper_id": p.get("id")}, {"_id": 0, "candidates": 1, "total_tweets": 1}
            )
            papers.append({
                "id": p.get("id"),
                "rank": p.get("rank"),
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "arxiv_id": p.get("arxiv_id"),
                "ts_score": p.get("ts_score") or p.get("score"),
                "ai_rating": p.get("ai_rating"),
                "link": p.get("link"),
                "candidates": disc.get("candidates", []) if disc else [],
                "total_tweets": disc.get("total_tweets", 0) if disc else 0,
                "discovered": disc is not None,
            })
        if papers:
            result_cats.append({
                "category": cat,
                "name": cat_names.get(cat, cat),
                "label": archive.get("label", ""),
                "papers": papers,
            })

    result_cats.sort(key=lambda c: c["category"])

    return {
        "period": period,
        "categories": result_cats,
        "total_papers": sum(len(c["papers"]) for c in result_cats),
        "total_discovered": sum(1 for c in result_cats for p in c["papers"] if p["discovered"]),
    }


@router.get("/archive-periods", dependencies=[Depends(verify_admin)])
async def get_archive_periods():
    """List available weekly and monthly archive periods."""
    weekly = []
    monthly = []
    
    async for doc in db.leaderboard_archives.aggregate([
        {"$match": {"period_type": "weekly"}},
        {"$group": {"_id": {"year": "$year", "week": "$week"}, "label": {"$first": "$label"},
                     "categories": {"$sum": 1}, "total_papers": {"$sum": "$paper_count"}}},
        {"$sort": {"_id.year": -1, "_id.week": -1}},
        {"$limit": 30},
    ]):
        weekly.append({
            "value": f"{doc['_id']['year']}-{doc['_id']['week']}",
            "label": doc.get("label") or f"Week {doc['_id']['week']}, {doc['_id']['year']}",
            "categories": doc["categories"],
            "total_papers": doc["total_papers"],
        })
    
    async for doc in db.leaderboard_archives.aggregate([
        {"$match": {"period_type": "monthly"}},
        {"$group": {"_id": {"year": "$year", "month": "$month"}, "label": {"$first": "$label"},
                     "categories": {"$sum": 1}, "total_papers": {"$sum": "$paper_count"}}},
        {"$sort": {"_id.year": -1, "_id.month": -1}},
        {"$limit": 24},
    ]):
        monthly.append({
            "value": f"{doc['_id']['year']}-{doc['_id']['month']}",
            "label": doc.get("label") or f"{doc['_id']['year']}-{doc['_id']['month']:02d}",
            "categories": doc["categories"],
            "total_papers": doc["total_papers"],
        })
    
    return {"weekly": weekly, "monthly": monthly}



@router.post("/discover-medalists", dependencies=[Depends(verify_admin)])
async def discover_medalists(period: str = "current", top_n: int = 3):
    """Discover X handles for all medalists across all categories. Runs in background."""
    from services.twitter import discover_handles_batch

    if _discover_status["running"]:
        return {"status": "already_running", "progress": _discover_status["progress"], "total": _discover_status["total"]}

    # Collect all medalist papers
    medalists_resp = await get_medalists(period=period, top_n=top_n)
    all_papers = []
    for cat_data in medalists_resp["categories"]:
        for p in cat_data["papers"]:
            all_papers.append(p)

    if not all_papers:
        return {"status": "no_papers", "message": "No medalists found."}

    _discover_status["running"] = True
    _discover_status["category"] = "all-medalists"
    _discover_status["progress"] = 0
    _discover_status["total"] = len(all_papers)

    async def _run():
        try:
            results = await discover_handles_batch(all_papers)
            _discover_status["progress"] = len(results)
        except Exception as e:
            logger.error(f"Medalist discovery failed: {e}")
        finally:
            _discover_status["running"] = False

    asyncio.create_task(_run())

    return {
        "status": "started",
        "total_papers": len(all_papers),
        "total_categories": len(medalists_resp["categories"]),
        "message": f"Searching X for {len(all_papers)} medalists across {len(medalists_resp['categories'])} categories.",
    }



@router.get("/discoveries", dependencies=[Depends(verify_admin)])
async def get_discoveries(
    category: Optional[str] = None,
    period: str = "all",
    top_n: int = 10,
    confidence: Optional[str] = None,
):
    """Get cached discovery results for a category/period without triggering new searches."""
    papers = await _get_papers_for_period(category, period, top_n)
    if not papers:
        return {"papers": [], "total": 0}

    paper_ids = [p["id"] for p in papers]
    discoveries = {}
    async for doc in db.x_handle_discoveries.find(
        {"paper_id": {"$in": paper_ids}}, {"_id": 0}
    ):
        discoveries[doc["paper_id"]] = doc

    # Build response: papers with their discovery status
    result_papers = []
    for p in papers:
        pid = p["id"]
        disc = discoveries.get(pid)
        entry = {
            "id": pid,
            "title": p.get("title", ""),
            "authors": p.get("authors", []),
            "arxiv_id": p.get("arxiv_id", ""),
            "rank": p.get("rank"),
            "ts_score": p.get("ts_score"),
            "ai_rating": p.get("ai_rating"),
            "comparisons": p.get("comparisons", 0),
            "discovered": disc is not None,
            "total_tweets": disc.get("total_tweets", 0) if disc else 0,
            "candidates": disc.get("candidates", []) if disc else [],
            "discovered_at": disc.get("discovered_at") if disc else None,
        }
        if confidence and disc:
            entry["candidates"] = [c for c in entry["candidates"] if c["confidence"] == confidence]
        result_papers.append(entry)

    return {
        "papers": result_papers,
        "total": len(result_papers),
        "discovered_count": sum(1 for p in result_papers if p["discovered"]),
    }



class DraftTweetRequest(BaseModel):
    paper_id: str
    tweet_url: str  # The original tweet to quote
    handle: str  # Author's X handle
    category: str
    rank: int  # 1=gold, 2=silver, 3=bronze
    period_label: str = ""  # e.g. "Week 17, 2026"


@router.post("/draft-tweet", dependencies=[Depends(verify_admin)])
async def draft_tweet(body: DraftTweetRequest):
    """Generate a draft quote tweet congratulating a paper medalist."""
    paper = await db.papers.find_one(
        {"id": body.paper_id},
        {"_id": 0, "title": 1, "authors": 1, "arxiv_id": 1, "abstract": 1,
         "ai_rating": 1, "categories": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")

    medal = {1: "gold", 2: "silver", 3: "bronze"}.get(body.rank, f"#{body.rank}")
    medal_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(body.rank, "🏅")

    # Build the badge URL
    # Find the archive entry to get year/week
    badge_url = f"https://kurate.org/paper/{body.paper_id}"

    # Generate draft text with Claude
    from services.llm import _ANTHROPIC_DIRECT_KEY
    import litellm
    prompt = f"""Write a short congratulatory quote tweet (max 240 chars, leave room for the link) for an academic paper that won {medal} medal {medal_emoji} in the {body.category} category on kurate.org's AI paper rankings{' for ' + body.period_label if body.period_label else ''}.

Paper: "{paper['title']}"
Authors: {', '.join(paper.get('authors', [])[:3])}
Author X handle: @{body.handle}
Rating: {paper.get('ai_rating', 'N/A')}/10

Rules:
- Tag @{body.handle}
- Include {medal_emoji}
- Mention the category naturally
- Be genuine and specific about what makes the paper notable (use the title)
- Don't use hashtags
- Don't say "Congratulations" — be more creative
- End with the kurate.org link
- Keep it under 240 chars total (excluding the quoted tweet)

Output ONLY the tweet text, nothing else."""

    try:
        litellm.suppress_debug_info = True
        resp = litellm.completion(
            model="anthropic/claude-sonnet-4-5",
            messages=[{"role": "user", "content": prompt}],
            api_key=_ANTHROPIC_DIRECT_KEY,
            max_tokens=150,
            temperature=0.8,
        )
        draft = resp.choices[0].message.content.strip().strip('"')
    except Exception as e:
        # Fallback template
        logger.warning(f"Draft generation failed: {e}")
        short_title = paper["title"][:60] + ("..." if len(paper["title"]) > 60 else "")
        draft = f"{medal_emoji} @{body.handle}'s \"{short_title}\" takes {medal} in {body.category} on kurate.org!\n\n{badge_url}"

    if badge_url not in draft:
        draft = draft.rstrip() + f"\n\n{badge_url}"

    # Store draft
    draft_doc = {
        "paper_id": body.paper_id,
        "handle": body.handle,
        "tweet_url": body.tweet_url,
        "category": body.category,
        "rank": body.rank,
        "period_label": body.period_label,
        "draft_text": draft,
        "badge_url": badge_url,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tweet_drafts.update_one(
        {"paper_id": body.paper_id, "handle": body.handle},
        {"$set": draft_doc},
        upsert=True,
    )

    return {
        "draft_text": draft,
        "badge_url": badge_url,
        "tweet_url": body.tweet_url,
        "handle": body.handle,
        "paper_id": body.paper_id,
    }


@router.post("/save-draft", dependencies=[Depends(verify_admin)])
async def save_draft(paper_id: str, handle: str, text: str):
    """Save an edited draft tweet."""
    await db.tweet_drafts.update_one(
        {"paper_id": paper_id, "handle": handle},
        {"$set": {"draft_text": text, "status": "edited", "edited_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "ok"}


@router.get("/drafts", dependencies=[Depends(verify_admin)])
async def get_drafts(status: str = None):
    """List tweet drafts."""
    query = {}
    if status:
        query["status"] = status
    drafts = []
    async for doc in db.tweet_drafts.find(query, {"_id": 0}).sort("created_at", -1).limit(100):
        drafts.append(doc)
    return {"drafts": drafts, "count": len(drafts)}


@router.get("/handle-stats", dependencies=[Depends(verify_admin)])
async def get_handle_stats():
    """Summary stats for all discovered handles across the platform."""
    pipeline = [
        {"$unwind": "$candidates"},
        {"$group": {
            "_id": "$candidates.confidence",
            "count": {"$sum": 1},
            "unique_handles": {"$addToSet": "$candidates.handle"},
        }},
    ]
    stats = {}
    async for doc in db.x_handle_discoveries.aggregate(pipeline):
        stats[doc["_id"]] = {
            "count": doc["count"],
            "unique": len(doc["unique_handles"]),
        }

    total_papers = await db.x_handle_discoveries.count_documents({})
    papers_with_candidates = await db.x_handle_discoveries.count_documents(
        {"candidates.0": {"$exists": True}}
    )

    return {
        "total_papers_searched": total_papers,
        "papers_with_candidates": papers_with_candidates,
        "by_confidence": stats,
    }


@router.delete("/discovery/{paper_id}", dependencies=[Depends(verify_admin)])
async def delete_discovery(paper_id: str):
    """Delete a cached discovery to force re-search."""
    result = await db.x_handle_discoveries.delete_one({"paper_id": paper_id})
    return {"deleted": result.deleted_count > 0}


async def _get_papers_for_period(category: str, period: str, top_n: int) -> list:
    """Fetch ranked papers for a category/period, matching leaderboard logic."""
    
    if period.startswith("archive:"):
        # Weekly archive: "archive:2026-15"
        parts = period.split(":")[1].split("-")
        if len(parts) == 2:
            year, week = int(parts[0]), int(parts[1])
            archive = await db.leaderboard_archives.find_one(
                {"category": category, "period_type": "weekly", "year": year, "week": week},
                {"_id": 0, "leaderboard": 1},
            )
            if archive and archive.get("leaderboard"):
                return archive["leaderboard"][:top_n]
        return []

    # Live leaderboard
    query = {"category": category} if category else {}
    
    if period == "recent":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        query["added_at"] = {"$gte": cutoff}
    elif period == "7d":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query["added_at"] = {"$gte": cutoff}
    elif period == "30d":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        query["added_at"] = {"$gte": cutoff}

    papers = []
    async for doc in db.rankings.find(
        query,
        {"_id": 0, "paper_id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
         "rank": 1, "ts_score": 1, "ai_rating": 1, "comparisons": 1,
         "category": 1, "added_at": 1, "link": 1},
    ).sort("ts_score", -1).limit(top_n):
        doc["id"] = doc.pop("paper_id")
        papers.append(doc)
    
    return papers
