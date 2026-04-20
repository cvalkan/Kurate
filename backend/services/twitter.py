"""Twitter/X handle discovery service using TweetAPI.com."""

import os
import httpx
import asyncio
from datetime import datetime, timezone
from core.config import db, logger

TWEETAPI_KEY = os.environ.get("TWEETAPI_KEY", "")
TWEETAPI_BASE = "https://api.tweetapi.com/tw-v2"

# Bot accounts to exclude from author matching
BOT_USERNAMES = {
    "scifi", "arxiv_org", "theqi0", "fly51fly", "arxivemcinco",
    "arxivbot", "paperswithcode", "grok", "openai",
}


async def search_tweets(query: str, search_type: str = "Latest", max_results: int = 20) -> list:
    """Search tweets via TweetAPI. Returns list of tweet dicts."""
    if not TWEETAPI_KEY:
        logger.warning("TWEETAPI_KEY not set — skipping tweet search")
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{TWEETAPI_BASE}/search",
            headers={"X-API-Key": TWEETAPI_KEY},
            params={"query": query, "type": search_type},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data.get("tweets", []))[:max_results]


def _is_bot(username: str) -> bool:
    return username.lower() in BOT_USERNAMES


def _name_similarity(author_name: str, tweet_name: str) -> float:
    """Simple name matching score. Returns 0-1."""
    a_parts = set(author_name.lower().split())
    t_parts = set(tweet_name.lower().split())
    if not a_parts or not t_parts:
        return 0
    overlap = a_parts & t_parts
    return len(overlap) / max(len(a_parts), len(t_parts))


async def discover_handles_for_paper(paper: dict) -> dict:
    """Search X for tweets about a paper. Returns discovery result with tweets and candidate handles.
    
    Args:
        paper: dict with title, authors, arxiv_id
    
    Returns:
        {paper_id, title, tweets: [...], candidates: [{handle, name, confidence, tweet_url}]}
    """
    title = paper.get("title", "")
    authors = paper.get("authors", [])
    arxiv_id = paper.get("arxiv_id", "")

    # Build search queries in priority order
    queries = []
    # 1. Quoted title + arxiv (most precise)
    short_title = title[:60].rsplit(" ", 1)[0] if len(title) > 60 else title
    queries.append(f'"{short_title}" arxiv')
    # 2. First author + title keywords
    if authors:
        title_words = " ".join(title.split()[:4])
        queries.append(f'"{authors[0]}" {title_words}')

    all_tweets = []
    seen_tweet_ids = set()
    for query in queries:
        try:
            tweets = await search_tweets(query, search_type="Latest")
            for t in tweets:
                tid = t.get("id", "")
                if tid and tid not in seen_tweet_ids:
                    seen_tweet_ids.add(tid)
                    all_tweets.append(t)
            await asyncio.sleep(1.5)  # Rate limit courtesy
        except Exception as e:
            logger.warning(f"Tweet search failed for '{title[:40]}': {e}")

    # Extract candidate handles
    candidates = []
    seen_handles = set()
    for t in all_tweets:
        author = t.get("author", {})
        username = author.get("username", "")
        if not username or username.lower() in seen_handles or _is_bot(username):
            continue
        seen_handles.add(username.lower())

        name = author.get("name", "")
        bio = author.get("bio", "")
        followers = author.get("followers", 0)

        # Confidence scoring
        confidence = "low"
        best_match = 0
        matched_author = ""
        for paper_author in authors:
            sim = _name_similarity(paper_author, name)
            if sim > best_match:
                best_match = sim
                matched_author = paper_author
        
        # Also check bio for author name
        bio_match = any(a.lower() in bio.lower() for a in authors if len(a) > 3)
        
        if best_match >= 0.5 or bio_match:
            confidence = "high"
        elif best_match >= 0.3 or followers > 500:
            confidence = "medium"

        tweet_text = t.get("text", "")
        tweet_url = f"https://x.com/{username}/status/{t.get('id', '')}"

        candidates.append({
            "handle": username,
            "name": name,
            "bio": bio[:200],
            "followers": followers,
            "confidence": confidence,
            "matched_author": matched_author,
            "name_similarity": round(best_match, 2),
            "tweet_url": tweet_url,
            "tweet_text": tweet_text[:280],
            "tweet_likes": t.get("likeCount", 0),
            "tweet_retweets": t.get("retweetCount", 0),
        })

    # Sort: high confidence first, then by followers
    conf_order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (conf_order.get(c["confidence"], 3), -c["followers"]))

    return {
        "paper_id": paper.get("id", ""),
        "title": title,
        "authors": authors,
        "arxiv_id": arxiv_id,
        "total_tweets": len(all_tweets),
        "candidates": candidates,
    }


async def discover_handles_batch(papers: list) -> list:
    """Discover handles for a batch of papers, skipping already-discovered ones.
    
    Returns list of discovery results.
    """
    results = []
    for i, paper in enumerate(papers):
        pid = paper.get("id", "")
        
        # Skip if already discovered
        existing = await db.x_handle_discoveries.find_one(
            {"paper_id": pid},
            {"_id": 0, "paper_id": 1},
        )
        if existing:
            # Return cached result
            cached = await db.x_handle_discoveries.find_one(
                {"paper_id": pid}, {"_id": 0}
            )
            if cached:
                results.append(cached)
            continue

        logger.info(f"[x-discovery] ({i+1}/{len(papers)}) Searching for '{paper.get('title', '')[:40]}'")
        result = await discover_handles_for_paper(paper)
        result["discovered_at"] = datetime.now(timezone.utc).isoformat()
        
        # Store in DB
        await db.x_handle_discoveries.update_one(
            {"paper_id": pid},
            {"$set": result},
            upsert=True,
        )
        results.append(result)
        
        # Rate limit: ~4s between searches (2 queries per paper × 1.5s + overhead)
        if i < len(papers) - 1:
            await asyncio.sleep(1)

    return results
