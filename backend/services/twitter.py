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

# P0+P1 confidence-scoring heuristics ----------------------------------------
# Bios containing any of these phrases are near-certainly curator/digest bots
# and cannot be paper authors, no matter how many engagements they rack up.
CURATOR_BIO_KEYWORDS = [
    "papers from", "daily papers", "weekly papers", "latest papers",
    "arxiv digest", "paper digest", "daily digest", "weekly digest",
    "papers bot", "arxiv bot", "feed bot", "bot account",
    "papers roundup", "research roundup", "newsletter",
    "automated", "autofeed", "rss feed",
]
# Tweet-text phrases that indicate a curator sharing someone else's work
CURATOR_TWEET_KEYWORDS = [
    "today's papers", "daily digest", "weekly papers", "papers roundup",
    "i've gathered", "reading list", "top papers of", "weekly arxiv",
    "papers of the week", "papers i've been",
]
# Tweet-text phrases strongly suggesting authorship of the paper
AUTHOR_TWEET_KEYWORDS = [
    "our new paper", "our paper", "our new preprint", "our preprint",
    "we present", "we show", "we introduce", "we propose", "we demonstrate",
    "happy to share", "happy to announce", "excited to share",
    "excited to announce", "proud to share", "proud to announce",
    "just posted", "just released", "just published",
    "check out our", "new paper from my group", "first-author paper",
]


def _normalize_name_tokens(name: str) -> list:
    """Split a name into lowercased tokens, dropping punctuation and tokens < 2 chars."""
    import re
    return [t for t in re.split(r"[^\w]+", (name or "").lower()) if len(t) > 1]


def _is_reply_tweet(text: str) -> bool:
    """Return True when a tweet starts with an @mention (so it's a reply, not
    a self-authorship announcement)."""
    return (text or "").lstrip().startswith("@")


def _contains_any(text: str, phrases: list) -> bool:
    tl = (text or "").lower()
    return any(p in tl for p in phrases)


def _name_match_strong(author: str, display_name: str):
    """Return (fuzzy_score 0-100, has_full_name_match) using rapidfuzz's
    token_set_ratio plus a first-and-last token containment check."""
    try:
        from rapidfuzz import fuzz
    except ImportError:
        # Fallback to difflib if rapidfuzz is unavailable
        from difflib import SequenceMatcher
        fuzz_score = SequenceMatcher(None, author.lower(), (display_name or "").lower()).ratio() * 100
    else:
        fuzz_score = fuzz.token_set_ratio(author.lower(), (display_name or "").lower())

    a_tokens = _normalize_name_tokens(author)
    c_tokens = _normalize_name_tokens(display_name)
    has_full = False
    if len(a_tokens) >= 2 and c_tokens:
        first, last = a_tokens[0], a_tokens[-1]
        has_full = (first in c_tokens) and (last in c_tokens) and first != last
    return float(fuzz_score), has_full


def _bio_mentions_author(bio: str, authors: list) -> bool:
    """True if any author's first+last name appears as whole words in the bio
    (word-boundary check). Guards against false substring matches like
    'King' matching inside 'Kingdom'."""
    import re
    bio_low = (bio or "").lower()
    if not bio_low:
        return False
    for a in authors:
        tokens = _normalize_name_tokens(a)
        if len(tokens) < 2:
            continue
        if f"{tokens[0]} {tokens[-1]}" in bio_low:
            return True
        pattern = r"\b" + re.escape(tokens[0]) + r"\b[^\n]{0,40}\b" + re.escape(tokens[-1]) + r"\b"
        if re.search(pattern, bio_low):
            return True
    return False


def score_candidate_v2(paper_authors: list, candidate: dict):
    """P0+P1 confidence scoring applied to a candidate dict.

    Returns a tuple of (confidence, signals_dict) where signals_dict has
    human-readable reasons that can be surfaced in the UI for debugging.
    """
    bio = candidate.get("bio", "") or ""
    name = candidate.get("name", "") or ""
    handle = (candidate.get("handle", "") or "").lower()
    followers = int(candidate.get("followers", 0) or 0)
    tweet_text = candidate.get("tweet_text", "") or ""
    verified = bool(candidate.get("verified") or candidate.get("is_blue_verified"))

    signals = {"reasons": []}

    # --- HARD NEGATIVES (cap at LOW) ---
    if _contains_any(bio, CURATOR_BIO_KEYWORDS):
        signals["reasons"].append("curator_bio")
        return "low", signals
    if _contains_any(tweet_text, CURATOR_TWEET_KEYWORDS):
        signals["reasons"].append("curator_tweet")
        return "low", signals
    # If the handle itself screams "papers curator"
    if any(k in handle for k in ("papers", "arxiv", "digest", "roundup")):
        if not _bio_mentions_author(bio, paper_authors):
            signals["reasons"].append("curator_handle")
            return "low", signals

    reply_cap = _is_reply_tweet(tweet_text)
    if reply_cap:
        signals["reasons"].append("reply")

    # --- POSITIVE signals ---
    best_score, best_full, matched_author = 0.0, False, ""
    for a in paper_authors:
        score, has_full = _name_match_strong(a, name)
        if score > best_score:
            best_score, best_full, matched_author = score, has_full, a

    bio_match = _bio_mentions_author(bio, paper_authors)
    author_lang = _contains_any(tweet_text, AUTHOR_TWEET_KEYWORDS)

    signals["name_fuzzy"] = round(best_score, 1)
    signals["name_full_match"] = best_full
    signals["matched_author"] = matched_author
    signals["bio_match"] = bio_match
    signals["author_language"] = author_lang
    signals["verified"] = verified

    strong = (best_score >= 85 and best_full) or bio_match or (author_lang and best_score >= 70)
    moderate = (best_score >= 70 and best_full) or (best_score >= 85) or author_lang

    if strong:
        conf = "high"
        if bio_match: signals["reasons"].append("bio_fullname_match")
        if best_score >= 85 and best_full: signals["reasons"].append("strong_name_match")
        if author_lang: signals["reasons"].append("author_language")
    elif moderate:
        conf = "medium"
        if best_score >= 70: signals["reasons"].append(f"name_fuzzy_{int(best_score)}")
        if author_lang: signals["reasons"].append("author_language")
    else:
        conf = "low"

    # Reply tweets can still be from authors, but only keep HIGH if there's a
    # very strong bio or name match supporting it
    if reply_cap and conf == "high" and not (bio_match or (best_score >= 90 and best_full)):
        conf = "medium"
        signals["reasons"].append("reply_cap")

    # Small bonus: verified + already-medium → keep medium (no promotion to
    # high on verification alone since influencers are often verified)
    if followers > 50000 and conf == "low" and (best_score >= 60):
        signals["reasons"].append("influencer_soft_hint")

    return conf, signals


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
    # 1. Arxiv ID (most precise — finds anyone who shared the paper link)
    if arxiv_id:
        bare_id = arxiv_id.replace("v1", "").replace("v2", "").replace("v3", "").replace("v4", "")
        queries.append(bare_id)
    # 2. Quoted title + arxiv
    short_title = title[:60].rsplit(" ", 1)[0] if len(title) > 60 else title
    queries.append(f'"{short_title}" arxiv')
    # 3. First author + title keywords
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
    # Group tweets by author, prefer the first tweet in a thread (1/N) or earliest
    tweets_by_author = {}
    for t in all_tweets:
        author = t.get("author", {})
        username = author.get("username", "")
        if not username or _is_bot(username):
            continue
        key = username.lower()
        if key not in tweets_by_author:
            tweets_by_author[key] = []
        tweets_by_author[key].append(t)

    candidates = []
    for username_lower, author_tweets in tweets_by_author.items():
        # Pick the best tweet: prefer thread starters (1/N), then earliest by ID
        def _tweet_sort_key(t):
            text = t.get("text", "")
            # Thread starters: "1/", "(1/", "[1/"
            is_start = any(text.lstrip().startswith(p) for p in ["1/", "(1/", "[1/", "🧵"])
            # Conversation root (not a reply)
            is_root = not t.get("inReplyToId") and t.get("id") == t.get("conversationId", t.get("id"))
            return (0 if is_start else (1 if is_root else 2), t.get("id", ""))
        
        author_tweets.sort(key=_tweet_sort_key)
        t = author_tweets[0]  # Best tweet for this author
        
        author = t.get("author", {})
        username = author.get("username", "")
        name = author.get("name", "")
        bio = author.get("bio", "")
        followers = author.get("followers", 0)

        tweet_text = t.get("text", "")
        tweet_url = f"https://x.com/{username}/status/{t.get('id', '')}"

        raw_candidate = {
            "handle": username,
            "name": name,
            "bio": bio[:500],  # give the scorer more bio to work with
            "followers": followers,
            "tweet_text": tweet_text,
            "verified": bool(author.get("verified") or author.get("is_blue_verified")),
        }
        confidence, signals = score_candidate_v2(authors, raw_candidate)

        candidates.append({
            "handle": username,
            "name": name,
            "bio": bio[:200],
            "followers": followers,
            "confidence": confidence,
            "matched_author": signals.get("matched_author", ""),
            "name_similarity": round((signals.get("name_fuzzy", 0.0)) / 100.0, 2),
            "scoring_signals": signals,
            "tweet_url": tweet_url,
            "tweet_text": tweet_text[:280],
            "tweet_likes": t.get("likeCount", 0),
            "tweet_retweets": t.get("retweetCount", 0),
            "verified": raw_candidate["verified"],
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
