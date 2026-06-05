"""arXiv paper fetcher — REST API with rate-limited round-robin.

Simple approach: one API call per category, once per day after arXiv's
daily update (~20:00 UTC). 45 categories × 3s throttle = 2.5 minutes total.
No OAI-PMH, no caching, no complex date logic needed.
"""
import re
import time
import random
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from core.config import logger


def strip_arxiv_version(arxiv_id: str) -> Tuple[str, int]:
    """'2602.12345v2' → ('2602.12345', 2), '2602.12345' → ('2602.12345', 1)"""
    m = re.match(r'^(.+?)v(\d+)$', arxiv_id)
    if m:
        return m.group(1), int(m.group(2))
    return arxiv_id, 1


# ── Global throttle: max 1 request per 3 seconds ──────────────────────
_MIN_INTERVAL = 3.0
_throttle_lock = asyncio.Lock()
_last_request_ts = 0.0


async def _throttle():
    """Hard guarantee: at least 3s between any two arXiv API requests."""
    global _last_request_ts
    async with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = time.monotonic()


async def fetch_arxiv_papers(
    category: str = "cs.RO",
    max_results: int = 200,
    primary_only: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[dict]:
    """Fetch papers from arXiv REST API for a single category.

    Returns papers with versioned IDs, correct published dates, and proper
    category filtering. One call typically sufficient for daily fetching.
    """
    base_url = "https://export.arxiv.org/api/query"
    query_parts = [f"cat:{category}"]

    if date_from or date_to:
        from_str = date_from.replace("-", "") + "0000" if date_from else "190001010000"
        to_str = date_to.replace("-", "") + "2359" if date_to else "209912312359"
        query_parts.append(f"submittedDate:[{from_str} TO {to_str}]")

    query = " AND ".join(query_parts)
    collected = []
    start = 0
    batch_size = max(max_results, 200)
    max_pages = 5

    for page in range(max_pages):
        if len(collected) >= max_results:
            break

        params = {
            "search_query": query,
            "start": start,
            "max_results": batch_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        papers_batch = None
        for attempt in range(3):
            await _throttle()
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    response = await client.get(base_url, params=params)
                    response.raise_for_status()
                papers_batch = _parse_response(response.text)
                break
            except (httpx.HTTPStatusError, httpx.ReadTimeout,
                    httpx.ConnectTimeout, Exception) as e:
                status = getattr(getattr(e, 'response', None), 'status_code', None)
                is_retryable = status in (429, 500, 502, 503, 504) or isinstance(
                    e, (httpx.ReadTimeout, httpx.ConnectTimeout))
                if is_retryable and attempt < 2:
                    wait = 5 + random.uniform(0, 3.0)
                    logger.warning(f"[{category}] arXiv API error ({status or type(e).__name__}), "
                                   f"retry {attempt+1}/3 in {wait:.0f}s")
                    await asyncio.sleep(wait)
                else:
                    raise

        if not papers_batch:
            break

        if primary_only:
            collected.extend([p for p in papers_batch if p["categories"] and p["categories"][0] == category])
        else:
            collected.extend(papers_batch)

        if len(papers_batch) < batch_size:
            break

        start += batch_size
        logger.info(f"[{category}] Pagination: page {page+1}, {len(collected)} primary papers so far")

    # Deduplicate
    seen = set()
    unique = []
    for p in collected:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)

    return unique[:max_results]


def _parse_response(xml_text: str) -> List[dict]:
    """Parse arXiv Atom response into paper dicts."""
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    papers = []
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        if id_el is None or "/abs/" not in id_el.text:
            continue

        arxiv_id = id_el.text.split("/abs/")[-1]
        title = (entry.find("atom:title", ns).text or "").strip().replace("\n", " ")
        abstract = (entry.find("atom:summary", ns).text or "").strip().replace("\n", " ")
        published = entry.find("atom:published", ns).text

        authors = [a.find("atom:name", ns).text
                   for a in entry.findall("atom:author", ns)
                   if a.find("atom:name", ns) is not None]

        categories = [c.get("term") for c in entry.findall("atom:category", ns)]

        pdf_link = None
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "pdf":
                pdf_link = link.get("href")

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors[:8],
            "abstract": abstract[:2000],
            "categories": categories,
            "published": published,
            "link": id_el.text,
            "pdf_link": pdf_link,
        })

    return papers
