import re
import os
import time
import random
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from core.config import logger

# Proxy for arXiv requests (IPRoyal rotating residential)
_ARXIV_PROXY = os.environ.get("ARXIV_PROXY_URL") or None
if _ARXIV_PROXY:
    logger.info(f"[arXiv] Using proxy: {_ARXIV_PROXY.split('@')[-1] if '@' in _ARXIV_PROXY else 'configured'}")


def strip_arxiv_version(arxiv_id: str) -> Tuple[str, int]:
    """Strip version suffix from an arXiv ID.
    '2602.12345v2' → ('2602.12345', 2)
    '2602.12345'   → ('2602.12345', 1)
    """
    m = re.match(r'^(.+?)v(\d+)$', arxiv_id)
    if m:
        return m.group(1), int(m.group(2))
    return arxiv_id, 1


# ── Global arXiv request throttle ──────────────────────────────────────
# 3s minimum between requests — polite regardless of proxy/IP rotation.
_MIN_INTERVAL = 3.0
_throttle_lock = asyncio.Lock()
_last_request_ts = 0.0


async def _throttle():
    """Block until at least _MIN_INTERVAL has elapsed since the last arXiv request."""
    global _last_request_ts
    async with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = time.monotonic()



async def fetch_arxiv_papers(
    category: str = "cs.RO",
    max_results: int = 50,
    primary_only: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[dict]:
    """Fetch papers from arXiv API.

    When date_from is provided (catch-up mode), pages through ALL papers
    since that date instead of capping at max_results. This ensures no
    papers are missed between fetches, even for high-volume categories.
    """
    base_url = "https://export.arxiv.org/api/query"
    query_parts = [f"cat:{category}"]

    catch_up = bool(date_from)
    if date_from or date_to:
        from_str = date_from.replace("-", "") + "0000" if date_from else "190001010000"
        to_str = date_to.replace("-", "") + "2359" if date_to else "209912312359"
        query_parts.append(f"submittedDate:[{from_str} TO {to_str}]")

    query = " AND ".join(query_parts)
    collected = []
    start = 0
    batch_size = max(max_results * 3, 150)
    # In catch-up mode: allow more pages to collect everything since last fetch.
    # Safety cap at 2000 primary papers to prevent runaway fetches.
    # max_pages kept low (5) to avoid sustained arXiv request bursts —
    # the round-robin fetch loop will revisit categories that need more.
    max_pages = 5 if catch_up else 3
    hard_cap = 2000 if catch_up else max_results

    for page in range(max_pages):
        if len(collected) >= hard_cap:
            break

        params = {
            "search_query": query,
            "start": start,
            "max_results": batch_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        max_retries = 3
        last_error = None
        papers_batch = None

        for attempt in range(max_retries):
            await _throttle()
            try:
                # Each new AsyncClient gets a fresh proxy connection = fresh IP
                async with httpx.AsyncClient(
                    timeout=60.0 if _ARXIV_PROXY else 45.0,
                    proxy=_ARXIV_PROXY,
                ) as http_client:
                    response = await http_client.get(base_url, params=params)
                    response.raise_for_status()
                papers_batch = _parse_arxiv_response(response.text)
                break
            except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectTimeout,
                    httpx.ProxyError, Exception) as e:
                last_error = e
                status = getattr(getattr(e, 'response', None), 'status_code', None)
                is_retryable = (
                    status in (429, 500, 502, 503, 504)
                    or isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ProxyError))
                )
                if is_retryable and attempt < max_retries - 1:
                    wait = 3 + random.uniform(0, 2.0)
                    kind = f"HTTP {status}" if status else type(e).__name__
                    logger.warning(f"[{category}] ArXiv {kind}, retry {attempt+1}/{max_retries} "
                                   f"in {wait:.0f}s" + (" (new proxy IP)" if _ARXIV_PROXY else ""))
                    await asyncio.sleep(wait)
                else:
                    raise

        if papers_batch is None:
            if last_error:
                logger.error(f"[{category}] ArXiv fetch exhausted {max_retries} retries: "
                             f"{type(last_error).__name__}: {str(last_error)[:140]}")
                raise last_error
            break

        if not papers_batch:
            break  # No more results from arXiv

        if primary_only:
            primary_papers = [p for p in papers_batch if p["categories"] and p["categories"][0] == category]
            collected.extend(primary_papers)
        else:
            collected.extend(papers_batch)

        # If this batch returned fewer than requested, arXiv has no more
        if len(papers_batch) < batch_size:
            break

        start += batch_size
        logger.info(f"ArXiv pagination: page {page+1}, collected {len(collected)} primary {category} papers so far")
        # (request pacing is handled by the global _throttle() before every request)

    # Deduplicate by arxiv_id (in case of overlap)
    seen = set()
    unique = []
    for p in collected:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)

    return unique[:hard_cap]


def _parse_arxiv_response(xml_text: str) -> List[dict]:
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    papers = []
    for entry in root.findall("atom:entry", ns):
        arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
        title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
        abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
        published = entry.find("atom:published", ns).text

        authors = [
            a.find("atom:name", ns).text
            for a in entry.findall("atom:author", ns)
        ]

        categories = [c.get("term") for c in entry.findall("atom:category", ns)]

        link = entry.find("atom:id", ns).text
        pdf_link = None
        for l in entry.findall("atom:link", ns):
            if l.get("title") == "pdf":
                pdf_link = l.get("href")

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors[:8],
            "abstract": abstract[:2000],
            "categories": categories,
            "published": published,
            "link": link,
            "pdf_link": pdf_link,
        })

    return papers
