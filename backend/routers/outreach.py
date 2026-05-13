"""Admin routes for X/Twitter outreach handle discovery."""

import asyncio
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.config import db, logger
from routers.admin import verify_admin

router = APIRouter(prefix="/api/admin/outreach", tags=["admin-outreach"])

TWEETAPI_KEY = os.environ.get("TWEETAPI_KEY", "")
TWITTER_PROXY = os.environ.get("TWITTER_PROXY") or os.environ.get("TWITTER PROXY") or os.environ.get("TWITTER_PROXY_URL") or os.environ.get("TWITTERPROXY") or ""
# Debug: log which variant was found
_proxy_source = (
    "TWITTER_PROXY" if os.environ.get("TWITTER_PROXY") else
    "TWITTER PROXY" if os.environ.get("TWITTER PROXY") else
    "TWITTER_PROXY_URL" if os.environ.get("TWITTER_PROXY_URL") else
    "TWITTERPROXY" if os.environ.get("TWITTERPROXY") else
    "none"
)


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


def _tweet_id_from_url(u: str) -> str:
    if not u:
        return ""
    return u.rstrip("/").split("/")[-1].split("?")[0]


async def _annotate_candidates(paper_ids: list, candidates_by_paper: dict) -> None:
    """Mutates the per-paper candidate lists in place, attaching
    liked / quote_tweeted / followed state from the tweet_likes,
    tweet_drafts and tweet_follows collections. Used by both
    /discoveries and /medalists so the UI stays consistent across views."""
    if not paper_ids:
        return

    liked_by_paper: dict = {}
    async for doc in db.tweet_likes.find(
        {"paper_id": {"$in": paper_ids}, "status": "liked"},
        {"_id": 0, "paper_id": 1, "tweet_id": 1, "liked_at": 1},
    ):
        liked_by_paper.setdefault(doc["paper_id"], {})[doc["tweet_id"]] = doc.get("liked_at")

    qt_by_paper: dict = {}
    async for doc in db.tweet_drafts.find(
        {"paper_id": {"$in": paper_ids}, "status": "posted"},
        {"_id": 0, "paper_id": 1, "handle": 1, "quote_tweet_id": 1,
         "quote_tweet_url": 1, "posted_at": 1},
    ):
        qt_by_paper.setdefault(doc["paper_id"], {})[doc["handle"]] = {
            "quote_tweet_id": doc.get("quote_tweet_id"),
            "quote_tweet_url": doc.get("quote_tweet_url") or (
                f"https://x.com/KurateOrg/status/{doc['quote_tweet_id']}"
                if doc.get("quote_tweet_id") else None
            ),
            "quote_tweeted_at": doc.get("posted_at"),
        }

    # Follows are tracked globally by handle (not per paper) since you follow
    # a person once, then that persists across every paper they appear in.
    handles = {c.get("handle") for cands in candidates_by_paper.values() for c in cands}
    handles.discard(None)
    handles.discard("")
    follows: dict = {}
    if handles:
        async for doc in db.tweet_follows.find(
            {"handle": {"$in": list(handles)}, "status": "followed"},
            {"_id": 0, "handle": 1, "followed_at": 1},
        ):
            follows[doc["handle"]] = doc.get("followed_at")

    for pid, cands in candidates_by_paper.items():
        liked_map = liked_by_paper.get(pid, {})
        qt_map = qt_by_paper.get(pid, {})
        for c in cands:
            tid = _tweet_id_from_url(c.get("tweet_url", ""))
            if tid and tid in liked_map:
                c["liked"] = True
                c["liked_at"] = liked_map[tid]
            else:
                c["liked"] = False
            qt = qt_map.get(c.get("handle", ""))
            if qt and qt.get("quote_tweet_id"):
                c["quote_tweeted"] = True
                c["quote_tweet_id"] = qt["quote_tweet_id"]
                c["quote_tweet_url"] = qt["quote_tweet_url"]
                c["quote_tweeted_at"] = qt["quote_tweeted_at"]
            else:
                c["quote_tweeted"] = False
            h = c.get("handle")
            if h and h in follows:
                c["followed"] = True
                c["followed_at"] = follows[h]
            else:
                c["followed"] = False


@router.get("/medalists", dependencies=[Depends(verify_admin)])
async def get_medalists(period: str = "current", top_n: int = 3):
    """Get top-N medalists across all categories.
    
    period: "weekly:YYYY-WW" or "monthly:YYYY-MM"
    Only shows categories whose archive_frequency matches the period type.
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

    # Get archive_frequency setting to filter categories
    from core.auth import get_settings
    settings = await get_settings() or {}
    freq_config = settings.get("archive_frequency") or {}
    # If no frequency config exists, show all categories in both views (no filtering)
    has_freq_config = bool(freq_config)

    async for archive in db.leaderboard_archives.find(
        {"period_type": period_type, **query_filter},
        {"_id": 0, "category": 1, "leaderboard": {"$slice": top_n}, "label": 1},
    ):
        cat = archive["category"]
        
        # Only filter by frequency if the setting exists
        if has_freq_config:
            default_freq = freq_config.get("default", "weekly")
            cat_freq = freq_config.get(cat, default_freq)
            if cat_freq != period_type:
                continue
        papers = []
        candidates_by_paper: dict = {}
        for i, p in enumerate(archive.get("leaderboard", [])[:top_n]):
            disc = await db.x_handle_discoveries.find_one(
                {"paper_id": p.get("id")}, {"_id": 0, "candidates": 1, "total_tweets": 1}
            )
            cands = disc.get("candidates", []) if disc else []
            candidates_by_paper[p.get("id")] = cands
            papers.append({
                "id": p.get("id"),
                "rank": i + 1,
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "arxiv_id": p.get("arxiv_id"),
                "ts_score": p.get("score") or p.get("ts_score"),
                "ai_rating": p.get("ai_rating"),
                "link": p.get("link"),
                "candidates": cands,
                "total_tweets": disc.get("total_tweets", 0) if disc else 0,
                "discovered": disc is not None,
            })
        # Hydrate liked / quote_tweeted state into the candidate dicts in place
        await _annotate_candidates(list(candidates_by_paper.keys()), candidates_by_paper)
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
    from core.auth import get_settings
    settings = await get_settings() or {}
    freq_config = settings.get("archive_frequency") or {}
    default_freq = freq_config.get("default", "weekly")
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
    
    return {"weekly": weekly, "monthly": monthly, "archive_frequency": freq_config, "default_frequency": default_freq if freq_config else None}



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

    # Hydrate liked / quote_tweeted state into each candidate in place
    candidates_by_paper = {
        pid: (discoveries.get(pid, {}).get("candidates") or []) for pid in paper_ids
    }
    await _annotate_candidates(paper_ids, candidates_by_paper)

    # Build response: papers with their discovery status
    result_papers = []
    for i, p in enumerate(papers):
        pid = p["id"] if "id" in p else p.get("paper_id", "")
        disc = discoveries.get(pid)
        candidates = candidates_by_paper.get(pid, [])
        entry = {
            "id": pid,
            "title": p.get("title", ""),
            "authors": p.get("authors", []),
            "arxiv_id": p.get("arxiv_id", ""),
            "rank": p.get("rank") or (i + 1),
            "ts_score": p.get("score") or p.get("ts_score"),
            "ai_rating": p.get("ai_rating"),
            "comparisons": p.get("comparisons", 0),
            "discovered": disc is not None,
            "total_tweets": disc.get("total_tweets", 0) if disc else 0,
            "candidates": candidates,
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
    handle: str  # Primary handle (the one whose tweet we're quoting)
    category: str
    rank: int  # 1=gold, 2=silver, 3=bronze
    period_label: str = ""


def _build_congrats_text(paper: dict, handle: str, all_candidates: list, rank: int, category: str, period_label: str) -> str:
    """Build congrats text tagging all discovered handles, naming others."""
    authors = paper.get("authors", [])

    # Map author names to discovered handles (only high-confidence matches)
    handle_map = {}
    for c in all_candidates:
        if c.get("confidence") == "high" and c.get("matched_author"):
            handle_map[c["matched_author"].lower()] = c["handle"]

    # Build author parts: @handle if matched, plain name otherwise
    author_parts = []
    tagged = set()
    for a in authors[:3]:
        h = handle_map.get(a.lower())
        if h and h not in tagged:
            author_parts.append(f"@{h}")
            tagged.add(h)
        else:
            author_parts.append(a)
    
    # Don't add unmatched handles — they're not authors

    if len(authors) > 3:
        author_text = ", ".join(author_parts) + " et al."
    elif len(author_parts) == 3:
        author_text = f"{author_parts[0]}, {author_parts[1]} & {author_parts[2]}"
    elif len(author_parts) == 2:
        author_text = f"{author_parts[0]} & {author_parts[1]}"
    else:
        author_text = author_parts[0] if author_parts else "the authors"

    tier = {1: "Gold ", 2: "Silver ", 3: "Bronze "}.get(rank, "")
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "🏅")

    text = f"{medal} Congrats to {author_text} for ranking #{rank} {tier}in {category} Preprints"
    if period_label:
        text += f" ({period_label})"
    text += " on Kurate.org!"
    return text


def _build_share_url(paper_id: str, category: str = None, year: int = None, week: int = None, month: int = None) -> str:
    """Build the badge share URL with correct period type for unfurling."""
    if category and year and month:
        return f"https://kurate.org/api/badge/{category}/{year}/m{month}/{paper_id}/share"
    elif category and year and week:
        return f"https://kurate.org/api/badge/{category}/{year}/w{week}/{paper_id}/share"
    return f"https://kurate.org/api/badge/paper/{paper_id}/share/page"


@router.post("/draft-tweet", dependencies=[Depends(verify_admin)])
async def draft_tweet(body: DraftTweetRequest):
    """Generate a draft quote tweet using standard badge congratulations text."""
    paper = await db.papers.find_one(
        {"id": body.paper_id},
        {"_id": 0, "title": 1, "authors": 1, "arxiv_id": 1, "categories": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")

    # Parse period to get year/week/month for badge URL
    year, week, month = None, None, None
    if body.period_label:
        import re
        _MONTH_MAP = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                      "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
        wm = re.search(r'Week (\d+),?\s*(\d{4})', body.period_label)
        mm = re.search(r'(\w+)\s+(\d{4})', body.period_label)
        if wm:
            week, year = int(wm.group(1)), int(wm.group(2))
        elif mm:
            month_name = mm.group(1).lower()
            year = int(mm.group(2))
            month = _MONTH_MAP.get(month_name)

    share_url = _build_share_url(body.paper_id, body.category, year, week, month)

    # Get all discovered candidates for this paper
    disc = await db.x_handle_discoveries.find_one(
        {"paper_id": body.paper_id}, {"_id": 0, "candidates": 1}
    )
    all_candidates = disc.get("candidates", []) if disc else []

    draft_text = _build_congrats_text(paper, body.handle, all_candidates, body.rank, body.category, body.period_label)

    # Store draft
    draft_doc = {
        "paper_id": body.paper_id,
        "handle": body.handle,
        "tweet_url": body.tweet_url,
        "category": body.category,
        "rank": body.rank,
        "period_label": body.period_label,
        "draft_text": draft_text,
        "share_url": share_url,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tweet_drafts.update_one(
        {"paper_id": body.paper_id, "handle": body.handle},
        {"$set": draft_doc},
        upsert=True,
    )

    return {
        "draft_text": draft_text,
        "share_url": share_url,
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


class PostTweetRequest(BaseModel):
    paper_id: str
    handle: str
    text: Optional[str] = None  # if provided, saves + uses this edited text instead of the stored draft


@router.post("/post-tweet", dependencies=[Depends(verify_admin)])
async def post_tweet(body: PostTweetRequest):
    """Post a draft tweet as a quote tweet from @kurateorg via TweetAPI.

    If `text` is provided, it replaces the stored draft before posting (atomically
    save-and-post). Clicking "Reply" a second time re-posts a new quote tweet
    using the latest text — drafts are not consumed on post.
    """
    draft = await db.tweet_drafts.find_one(
        {"paper_id": body.paper_id, "handle": body.handle},
        {"_id": 0},
    )
    if not draft:
        raise HTTPException(404, "No draft found for this paper/handle")

    # If the client sent edited text, save it to the draft before posting so
    # the stored record always reflects what was actually tweeted.
    if body.text is not None and body.text.strip():
        edited = body.text.strip()
        if len(edited) > 280:
            raise HTTPException(400, f"Tweet text is {len(edited)} chars (max 280)")
        await db.tweet_drafts.update_one(
            {"paper_id": body.paper_id, "handle": body.handle},
            {"$set": {
                "draft_text": edited,
                "edited_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        draft["draft_text"] = edited

    auth_token, _src = await _get_twitter_auth_token()
    proxy = TWITTER_PROXY
    if not auth_token:
        raise HTTPException(500, "No X auth token configured (set via Admin → Outreach → X Auth, or TWITTER_AUTH_TOKEN env)")

    from tweetapi import TweetAPI
    client = TweetAPI(api_key=TWEETAPI_KEY)

    try:
        # Step 1: Post quote tweet with congrats text (no share URL — it conflicts with unfurl)
        congrats_text = draft["draft_text"].split("\n\nhttps://")[0]  # Strip share URL from text
        tweet_id_to_quote = draft["tweet_url"].rstrip("/").split("/")[-1]

        quote_result = client.post.create_post_quote(
            auth_token=auth_token,
            text=congrats_text,
            attachment_url=draft["tweet_url"],
            proxy=proxy,
        )

        rd = quote_result if isinstance(quote_result, dict) else (quote_result.data if hasattr(quote_result, "data") else {})
        quote_tweet_id = rd.get("data", rd).get("metadata", {}).get("tweet_id", "") if isinstance(rd, dict) else ""

        logger.info(f"[outreach] Quote tweet posted: {quote_tweet_id}")

        # Step 2: Reply to our own quote tweet with the badge share URL (unfurls)
        reply_result = None
        if quote_tweet_id and draft.get("share_url"):
            import asyncio as _aio
            await _aio.sleep(2)  # Brief pause between posts
            try:
                reply_result = client.post.reply_post(
                    auth_token=auth_token,
                    text=draft["share_url"],
                    tweet_id=str(quote_tweet_id),
                    proxy=proxy,
                )
                logger.info(f"[outreach] Badge reply posted under {quote_tweet_id}")
            except Exception as re:
                logger.warning(f"[outreach] Badge reply failed (quote succeeded): {re}")

        # Update draft status. Push to history list so repeated posts are tracked.
        now = datetime.now(timezone.utc).isoformat()
        quote_url = f"https://x.com/KurateOrg/status/{quote_tweet_id}" if quote_tweet_id else ""
        await db.tweet_drafts.update_one(
            {"paper_id": body.paper_id, "handle": body.handle},
            {
                "$set": {
                    "status": "posted",
                    "posted_at": now,
                    "quote_tweet_id": str(quote_tweet_id),
                    "quote_tweet_url": quote_url,
                    "reply_result": str(reply_result)[:300] if reply_result else None,
                },
                "$push": {
                    "post_history": {
                        "quote_tweet_id": str(quote_tweet_id),
                        "quote_tweet_url": quote_url,
                        "posted_at": now,
                        "text": draft["draft_text"],
                    }
                },
            },
        )
        return {"status": "posted", "quote_tweet_id": quote_tweet_id, "url": quote_url, "posted_at": now}

    except Exception as e:
        logger.error(f"[outreach] Failed to post tweet: {e}")
        await db.tweet_drafts.update_one(
            {"paper_id": body.paper_id, "handle": body.handle},
            {"$set": {"status": "post_failed", "post_error": str(e)[:500]}},
        )
        raise HTTPException(500, f"Failed to post: {str(e)[:200]}")


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


class LikeTweetRequest(BaseModel):
    paper_id: str
    tweet_url: str  # Original candidate tweet to like
    handle: str     # For tracking/display


def _extract_tweet_id(tweet_url: str) -> str:
    """Parse the numeric tweet ID from an x.com / twitter.com status URL."""
    return tweet_url.rstrip("/").split("/")[-1].split("?")[0]


# ──────────────────────────────────────────────────────────────────────────
# X (Twitter) auth-token management
# ──────────────────────────────────────────────────────────────────────────
# We store the current auth_token in db.settings with key="twitter_auth" so
# the admin can rotate it from the UI without editing .env or restarting.
# If no DB entry exists we fall back to TWITTER_AUTH_TOKEN from the env.

async def _get_twitter_auth_token() -> tuple[str, str]:
    """Return (auth_token, source) where source is 'db' or 'env' or ''."""
    doc = await db.settings.find_one({"key": "twitter_auth"}, {"_id": 0})
    if doc and doc.get("auth_token"):
        return doc["auth_token"], "db"
    env_tok = os.environ.get("TWITTER_AUTH_TOKEN") or ""
    return env_tok, ("env" if env_tok else "")


def _mask_token(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 10:
        return "****"
    return f"{tok[:4]}…{tok[-4:]}"


class TwitterAuthRequest(BaseModel):
    auth_token: str
    verify: bool = True


@router.get("/twitter-auth/status", dependencies=[Depends(verify_admin)])
async def twitter_auth_status():
    """Return non-secret metadata about the currently configured X auth token."""
    doc = await db.settings.find_one({"key": "twitter_auth"}, {"_id": 0})
    tok, source = await _get_twitter_auth_token()
    return {
        "configured": bool(tok),
        "source": source,
        "masked": _mask_token(tok),
        "length": len(tok),
        "updated_at": (doc or {}).get("updated_at"),
        "last_verified_at": (doc or {}).get("last_verified_at"),
        "proxy_configured": bool(TWITTER_PROXY),
        "proxy_source": _proxy_source,
        "proxy_masked": TWITTER_PROXY[:15] + "..." if len(TWITTER_PROXY) > 15 else ("(empty)" if not TWITTER_PROXY else TWITTER_PROXY),
        "tweetapi_key_configured": bool(TWEETAPI_KEY),
    }


@router.post("/twitter-auth", dependencies=[Depends(verify_admin)])
async def set_twitter_auth_token(body: TwitterAuthRequest):
    """Save a new auth_token. If verify=True, runs a zero-effect Like+Unlike
    round-trip on a known Kurate tweet to confirm the token is valid before
    persisting. Returns masked info only — never the token itself."""
    new_tok = (body.auth_token or "").strip()
    if len(new_tok) < 20 or not all(c.isalnum() for c in new_tok):
        raise HTTPException(400, "auth_token must be a 20+ char alphanumeric string")

    now = datetime.now(timezone.utc).isoformat()
    proxy = TWITTER_PROXY or None

    verification: dict = {"verified": False, "error": None}
    if body.verify:
        if not TWEETAPI_KEY:
            raise HTTPException(500, "TWEETAPI_KEY not configured — cannot verify")
        # Known @KurateOrg tweet id used purely as a target for a self-like round-trip
        verify_tweet_id = os.environ.get("TWITTER_VERIFY_TWEET_ID") or "2046687272339452032"
        try:
            from tweetapi import TweetAPI
            client = TweetAPI(api_key=TWEETAPI_KEY)
            r1 = client.interaction.favorite_post(
                auth_token=new_tok, tweet_id=verify_tweet_id, proxy=proxy,
            )
            # Best-effort restore; ignore failure (token is already proven valid)
            try:
                client.interaction.unfavorite_post(
                    auth_token=new_tok, tweet_id=verify_tweet_id, proxy=proxy,
                )
            except Exception:
                pass
            ok = bool(r1.data if hasattr(r1, "data") else r1)
            verification = {"verified": ok, "error": None}
            if not ok:
                raise HTTPException(400, "Token could not be verified — TweetAPI returned empty result")
        except HTTPException:
            raise
        except Exception as e:
            err = str(e)[:250]
            logger.warning(f"[outreach] Token verification failed: {err}")
            raise HTTPException(400, f"Token verification failed: {err}")

    await db.settings.update_one(
        {"key": "twitter_auth"},
        {"$set": {
            "key": "twitter_auth",
            "auth_token": new_tok,
            "masked": _mask_token(new_tok),
            "length": len(new_tok),
            "updated_at": now,
            "last_verified_at": now if verification["verified"] else None,
        }},
        upsert=True,
    )
    logger.info(f"[outreach] X auth token rotated (verified={verification['verified']}, "
                f"masked={_mask_token(new_tok)})")
    return {
        "status": "saved",
        "masked": _mask_token(new_tok),
        "length": len(new_tok),
        "updated_at": now,
        "verified": verification["verified"],
    }


@router.delete("/twitter-auth", dependencies=[Depends(verify_admin)])
async def clear_twitter_auth_token():
    """Remove the DB-stored token so the system falls back to env-configured one."""
    r = await db.settings.delete_one({"key": "twitter_auth"})
    return {"status": "cleared", "deleted": r.deleted_count}



@router.post("/like-tweet", dependencies=[Depends(verify_admin)])
async def like_tweet(body: LikeTweetRequest):
    """Like a candidate tweet as @kurateorg — softer alternative to quote-tweeting."""
    tweet_id = _extract_tweet_id(body.tweet_url)
    if not tweet_id.isdigit():
        raise HTTPException(400, f"Could not parse tweet_id from URL: {body.tweet_url}")

    # Idempotency: if we already liked this, return cached state
    existing = await db.tweet_likes.find_one(
        {"paper_id": body.paper_id, "tweet_id": tweet_id, "status": "liked"},
        {"_id": 0},
    )
    if existing:
        return {"status": "already_liked", "tweet_id": tweet_id, "liked_at": existing.get("liked_at")}

    auth_token, _src = await _get_twitter_auth_token()
    proxy = TWITTER_PROXY
    if not auth_token:
        raise HTTPException(500, "No X auth token configured (set via Admin → Outreach → X Auth, or TWITTER_AUTH_TOKEN env)")
    if not TWEETAPI_KEY:
        raise HTTPException(500, "TWEETAPI_KEY not configured")

    from tweetapi import TweetAPI
    client = TweetAPI(api_key=TWEETAPI_KEY)

    try:
        result = client.interaction.favorite_post(
            auth_token=auth_token,
            tweet_id=tweet_id,
            proxy=proxy,
        )
        now = datetime.now(timezone.utc).isoformat()
        await db.tweet_likes.update_one(
            {"paper_id": body.paper_id, "tweet_id": tweet_id},
            {"$set": {
                "paper_id": body.paper_id,
                "handle": body.handle,
                "tweet_url": body.tweet_url,
                "tweet_id": tweet_id,
                "status": "liked",
                "liked_at": now,
                "result_repr": str(result)[:300],
            }},
            upsert=True,
        )
        logger.info(f"[outreach] Liked tweet {tweet_id} (paper={body.paper_id}, @{body.handle})")
        return {"status": "liked", "tweet_id": tweet_id, "liked_at": now}

    except Exception as e:
        err = str(e)[:500]
        logger.error(f"[outreach] Failed to like tweet {tweet_id}: {err}")
        await db.tweet_likes.update_one(
            {"paper_id": body.paper_id, "tweet_id": tweet_id},
            {"$set": {
                "paper_id": body.paper_id,
                "handle": body.handle,
                "tweet_url": body.tweet_url,
                "tweet_id": tweet_id,
                "status": "like_failed",
                "like_error": err,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        raise HTTPException(500, f"Failed to like tweet: {err[:200]}")


@router.post("/unlike-tweet", dependencies=[Depends(verify_admin)])
async def unlike_tweet(body: LikeTweetRequest):
    """Unlike a previously-liked tweet (for corrections)."""
    tweet_id = _extract_tweet_id(body.tweet_url)
    if not tweet_id.isdigit():
        raise HTTPException(400, f"Could not parse tweet_id from URL: {body.tweet_url}")

    auth_token, _src = await _get_twitter_auth_token()
    proxy = TWITTER_PROXY
    if not auth_token:
        raise HTTPException(500, "No X auth token configured (set via Admin → Outreach → X Auth, or TWITTER_AUTH_TOKEN env)")

    from tweetapi import TweetAPI
    client = TweetAPI(api_key=TWEETAPI_KEY)
    try:
        client.interaction.unfavorite_post(
            auth_token=auth_token,
            tweet_id=tweet_id,
            proxy=proxy,
        )
        await db.tweet_likes.update_one(
            {"paper_id": body.paper_id, "tweet_id": tweet_id},
            {"$set": {
                "status": "unliked",
                "unliked_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return {"status": "unliked", "tweet_id": tweet_id}
    except Exception as e:
        raise HTTPException(500, f"Failed to unlike: {str(e)[:200]}")


class FollowHandleRequest(BaseModel):
    handle: str
    paper_id: Optional[str] = None  # optional, for activity-log context


async def _resolve_user_id(handle: str) -> str:
    """Return the numeric X user_id for a handle, consulting a small on-DB
    cache before hitting TweetAPI so we don't burn API calls on repeats."""
    doc = await db.twitter_user_cache.find_one({"handle": handle}, {"_id": 0, "user_id": 1})
    if doc and doc.get("user_id"):
        return str(doc["user_id"])
    if not TWEETAPI_KEY:
        raise HTTPException(500, "TWEETAPI_KEY not configured — cannot resolve user_id")
    from tweetapi import TweetAPI
    client = TweetAPI(api_key=TWEETAPI_KEY)
    try:
        resp = client.user.get_by_username(username=handle)
        data = resp.data if hasattr(resp, "data") else resp
        if isinstance(data, dict):
            # TweetAPI wraps the user under {'data': {'id', 'username', ...}} —
            # unwrap that nesting before pulling the id, otherwise we'd read
            # from the outer envelope which has no id field.
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            user_id = str(
                inner.get("user_id") or inner.get("id_str") or inner.get("id") or ""
            )
        else:
            user_id = str(getattr(data, "user_id", "") or getattr(data, "id", ""))
        if not user_id or not user_id.isdigit():
            raise HTTPException(400, f"Could not resolve @{handle} to a numeric user_id (raw={str(data)[:200]})")
        await db.twitter_user_cache.update_one(
            {"handle": handle},
            {"$set": {"handle": handle, "user_id": user_id,
                      "cached_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        return user_id
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to look up @{handle}: {str(e)[:200]}")


@router.post("/follow-handle", dependencies=[Depends(verify_admin)])
async def follow_handle(body: FollowHandleRequest):
    """Follow an X handle as @kurateorg. Idempotent — returns already_followed
    if we already have an active follow record."""
    handle = (body.handle or "").strip().lstrip("@")
    if not handle:
        raise HTTPException(400, "handle is required")

    existing = await db.tweet_follows.find_one(
        {"handle": handle, "status": "followed"},
        {"_id": 0},
    )
    if existing:
        return {"status": "already_followed", "handle": handle,
                "followed_at": existing.get("followed_at")}

    auth_token, _src = await _get_twitter_auth_token()
    proxy = TWITTER_PROXY
    if not auth_token:
        raise HTTPException(500, "No X auth token configured")
    if not TWEETAPI_KEY:
        raise HTTPException(500, "TWEETAPI_KEY not configured")

    user_id = await _resolve_user_id(handle)

    from tweetapi import TweetAPI
    client = TweetAPI(api_key=TWEETAPI_KEY)
    try:
        result = client.interaction.follow(
            auth_token=auth_token,
            user_id=user_id,
            proxy=proxy,
        )
        now = datetime.now(timezone.utc).isoformat()
        await db.tweet_follows.update_one(
            {"handle": handle},
            {"$set": {
                "handle": handle,
                "user_id": user_id,
                "paper_id": body.paper_id,
                "status": "followed",
                "followed_at": now,
                "result_repr": str(result)[:300],
            }},
            upsert=True,
        )
        logger.info(f"[outreach] Followed @{handle} (user_id={user_id})")
        return {"status": "followed", "handle": handle, "user_id": user_id, "followed_at": now}
    except Exception as e:
        err = str(e)[:500]
        logger.error(f"[outreach] Failed to follow @{handle}: {err}")
        await db.tweet_follows.update_one(
            {"handle": handle},
            {"$set": {
                "handle": handle,
                "user_id": user_id,
                "paper_id": body.paper_id,
                "status": "follow_failed",
                "follow_error": err,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        raise HTTPException(500, f"Failed to follow: {err[:200]}")


@router.post("/unfollow-handle", dependencies=[Depends(verify_admin)])
async def unfollow_handle(body: FollowHandleRequest):
    """Unfollow an X handle (for corrections)."""
    handle = (body.handle or "").strip().lstrip("@")
    if not handle:
        raise HTTPException(400, "handle is required")

    auth_token, _src = await _get_twitter_auth_token()
    proxy = TWITTER_PROXY
    if not auth_token:
        raise HTTPException(500, "No X auth token configured")

    user_id = await _resolve_user_id(handle)
    from tweetapi import TweetAPI
    client = TweetAPI(api_key=TWEETAPI_KEY)
    try:
        client.interaction.unfollow(
            auth_token=auth_token,
            user_id=user_id,
            proxy=proxy,
        )
        await db.tweet_follows.update_one(
            {"handle": handle},
            {"$set": {
                "status": "unfollowed",
                "unfollowed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return {"status": "unfollowed", "handle": handle}
    except Exception as e:
        raise HTTPException(500, f"Failed to unfollow: {str(e)[:200]}")




@router.get("/activity", dependencies=[Depends(verify_admin)])
async def get_activity(limit: int = 200):
    """Return all quote tweets, likes and follows cast from @KurateOrg,
    joined with paper title/authors, sorted by time. Used by the Activity page."""
    # Quote tweets (successful posts only)
    quotes = []
    async for d in db.tweet_drafts.find(
        {"status": "posted", "quote_tweet_id": {"$nin": [None, ""]}},
        {"_id": 0},
    ).sort("posted_at", -1).limit(limit):
        quotes.append(d)

    # Likes
    likes = []
    async for d in db.tweet_likes.find(
        {"status": "liked"},
        {"_id": 0},
    ).sort("liked_at", -1).limit(limit):
        likes.append(d)

    # Follows
    follows = []
    async for d in db.tweet_follows.find(
        {"status": "followed"},
        {"_id": 0},
    ).sort("followed_at", -1).limit(limit):
        follows.append(d)

    # Batch-load papers for titles/authors
    paper_ids = ({q["paper_id"] for q in quotes}
                 | {li["paper_id"] for li in likes}
                 | {f["paper_id"] for f in follows if f.get("paper_id")})
    papers = {}
    if paper_ids:
        async for p in db.papers.find(
            {"id": {"$in": list(paper_ids)}},
            {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1},
        ):
            papers[p["id"]] = p

    def _enrich(d):
        p = papers.get(d.get("paper_id"), {}) if d.get("paper_id") else {}
        return {
            **d,
            "paper_title": p.get("title", ""),
            "paper_authors": p.get("authors", []),
            "paper_arxiv_id": p.get("arxiv_id", ""),
        }

    return {
        "quotes": [_enrich(q) for q in quotes],
        "likes": [_enrich(li) for li in likes],
        "follows": [_enrich(f) for f in follows],
        "counts": {"quotes": len(quotes), "likes": len(likes), "follows": len(follows)},
    }


@router.get("/confidence-preview", dependencies=[Depends(verify_admin)])
async def confidence_preview(period: str = "monthly:2026-3", top_n: int = 3):
    """Re-score every medalist candidate with the new V2 algorithm so admins
    can compare V1 (current stored) vs V2 (strict + signal-rich) side-by-side
    WITHOUT hitting the Twitter API again."""
    from services.twitter import score_candidate_v2

    result = await get_medalists(period=period, top_n=top_n)
    for cat in result.get("categories", []):
        for p in cat.get("papers", []):
            authors = p.get("authors", [])
            for c in p.get("candidates", []):
                c["confidence_v1"] = c.get("confidence", "low")
                # Pass through the richest view the scorer wants
                raw_candidate = {
                    "handle": c.get("handle", ""),
                    "name": c.get("name", ""),
                    "bio": c.get("bio", ""),
                    "followers": c.get("followers", 0),
                    "tweet_text": c.get("tweet_text", ""),
                    "verified": bool(c.get("verified") or c.get("is_blue_verified")),
                }
                v2_conf, v2_signals = score_candidate_v2(authors, raw_candidate)
                c["confidence_v2"] = v2_conf
                c["signals_v2"] = v2_signals
    return result


@router.post("/recompute-confidence", dependencies=[Depends(verify_admin)])
async def recompute_confidence(dry_run: bool = False):
    """Apply the V2 algorithm to every stored discovery, updating the
    candidate.confidence field in-place. Set dry_run=true to preview changes
    without persisting. Returns a summary of confidence transitions."""
    from services.twitter import score_candidate_v2

    transitions = {"high→low": 0, "high→medium": 0, "medium→low": 0,
                   "medium→high": 0, "low→medium": 0, "low→high": 0,
                   "unchanged": 0}
    total = 0
    async for doc in db.x_handle_discoveries.find({}, {"_id": 0}):
        authors = doc.get("authors", [])
        changed = False
        for c in doc.get("candidates", []):
            total += 1
            old = c.get("confidence", "low")
            raw_candidate = {
                "handle": c.get("handle", ""),
                "name": c.get("name", ""),
                "bio": c.get("bio", ""),
                "followers": c.get("followers", 0),
                "tweet_text": c.get("tweet_text", ""),
                "verified": bool(c.get("verified")),
            }
            new, signals = score_candidate_v2(authors, raw_candidate)
            if new != old:
                transitions[f"{old}→{new}"] = transitions.get(f"{old}→{new}", 0) + 1
                c["confidence"] = new
                c["scoring_signals"] = signals
                changed = True
            else:
                transitions["unchanged"] += 1
        if changed and not dry_run:
            await db.x_handle_discoveries.update_one(
                {"paper_id": doc["paper_id"]},
                {"$set": {"candidates": doc["candidates"]}},
            )
    return {"total_candidates": total, "transitions": transitions, "dry_run": dry_run}


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
