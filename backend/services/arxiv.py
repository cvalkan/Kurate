"""arXiv paper fetcher — OAI-PMH primary, REST API fallback.

OAI-PMH (export.arxiv.org/oai2) is the intended protocol for bulk harvesting.
One harvest per top-level set (cs, math, physics, ...) returns ALL subcategories
at once. Results are cached per-set so subsequent categories reuse the same data.

With ~7 top-level sets covering all 45 categories, this replaces 45 individual
API calls with ~7 OAI-PMH harvests — and OAI-PMH doesn't trip rate limits.
"""
import re
import os
import time
import random
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple, Dict
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


def _proxy_with_session() -> str:
    """Return the proxy URL with a random session ID in the password,
    forcing IPRoyal to assign a different IP for each request."""
    if not _ARXIV_PROXY:
        return None
    from urllib.parse import urlparse, urlunparse
    p = urlparse(_ARXIV_PROXY)
    session_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
    session_pass = f"{p.password}_session-{session_id}_lifetime-1m"
    new_netloc = f"{p.username}:{session_pass}@{p.hostname}:{p.port}"
    return urlunparse(p._replace(netloc=new_netloc))


async def lookup_arxiv_version(arxiv_id_base: str) -> Optional[dict]:
    """Look up the latest version of a paper via the REST API.
    Returns {full_id, version, published} or None on failure.
    Used for revision detection — OAI-PMH doesn't provide version numbers,
    and its 'created' field is unreliable for revised papers."""
    await _throttle()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={"id_list": arxiv_id_base, "max_results": "1"},
            )
            resp.raise_for_status()
            import re
            id_match = re.search(r'<id>http://arxiv\.org/abs/(.+?)</id>', resp.text)
            pub_match = re.search(r'<published>(.*?)</published>', resp.text)
            if id_match:
                full_id = id_match.group(1)
                base, version = strip_arxiv_version(full_id)
                return {
                    "full_id": full_id,
                    "version": version,
                    "published": pub_match.group(1) if pub_match else None,
                }
    except Exception as e:
        logger.warning(f"[arXiv] Version lookup failed for {arxiv_id_base}: {e}")
    return None


# ── OAI-PMH set-level cache ───────────────────────────────────────────
# Key: (oai_set, date_from) → list of ALL papers from that set since date_from.
# Populated on first category request, reused by subsequent categories in the
# same set. Cleared after 2 hours or when date_from changes.
_oai_cache: Dict[str, dict] = {}  # {oai_set: {"date_from": str, "papers": [...], "ts": float}}
_OAI_CACHE_TTL = 7200  # 2 hours


def _category_to_oai_set(category: str) -> str:
    """Map an arXiv category to its OAI-PMH set name.
    cs.LG → 'cs', hep-th → 'physics:hep-th', quant-ph → 'physics:quant-ph'"""
    if "." in category:
        prefix = category.split(".")[0]
        # Top-level archives that have their own OAI set
        if prefix in ("cs", "math", "stat", "econ", "eess"):
            return prefix
        if prefix in ("q-bio", "q-fin"):
            return prefix
        # Physics sub-archives: astro-ph, cond-mat, nlin, physics → physics:prefix
        return f"physics:{prefix}"
    # Standalone physics categories: hep-th, gr-qc, quant-ph, math-ph, etc.
    return f"physics:{category}"


async def fetch_arxiv_papers(
    category: str = "cs.RO",
    max_results: int = 50,
    primary_only: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[dict]:
    """Fetch papers from arXiv via OAI-PMH (primary) with REST API fallback.

    Uses set-level caching: the first category in a set (e.g., cs.LG) triggers
    a full OAI-PMH harvest for the entire set (cs). Subsequent categories
    (cs.AI, cs.RO, ...) reuse the cached data — zero additional requests.
    """
    oai_set = _category_to_oai_set(category)

    # Check cache — accept any cached harvest whose date_from is <= requested.
    # A wider harvest (older date_from) always includes all papers from a narrower one.
    cached = _oai_cache.get(oai_set)
    if (cached
            and cached.get("date_from", "9999") <= (date_from or "")
            and time.monotonic() - cached.get("ts", 0) < _OAI_CACHE_TTL):
        all_papers = cached["papers"]
        logger.info(f"[{category}] OAI-PMH cache hit for set={oai_set} ({len(all_papers)} total)")
    else:
        # Harvest the full set via OAI-PMH
        try:
            all_papers = await _oai_harvest(oai_set, date_from=date_from)
            _oai_cache[oai_set] = {
                "date_from": date_from or "",
                "papers": all_papers,
                "ts": time.monotonic(),
            }
            logger.info(f"[{category}] OAI-PMH harvested set={oai_set}: {len(all_papers)} papers")
        except Exception as e:
            logger.warning(f"[{category}] OAI-PMH failed ({e}), falling back to REST API")
            return await _fetch_arxiv_api(category, max_results, primary_only, date_from, date_to)

    # Filter for this specific category
    if primary_only:
        filtered = [p for p in all_papers if p.get("categories") and p["categories"][0] == category]
    else:
        filtered = [p for p in all_papers if category in (p.get("categories") or [])]

    # Do NOT filter by created date here — the scheduler needs both new papers
    # AND revisions of existing papers. Classification happens in run_fetch_cycle:
    #   - New paper: created >= date_from AND not in DB
    #   - Revision: base in DB AND updated is newer
    #   - Skip: created < date_from AND not in DB (old paper we never tracked)

    # Deduplicate by arxiv_id
    seen = set()
    unique = []
    for p in filtered:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)

    # Don't cap here — the scheduler needs the FULL list to detect revisions
    # of tracked papers. The scheduler applies its own per-cycle processing cap
    # (max_papers_per_fetch) to limit PDF downloads and summaries.
    return unique


# ── OAI-PMH harvester ─────────────────────────────────────────────────

_OAI_BASE = "https://export.arxiv.org/oai2"
_OAI_NS = "http://www.openarchives.org/OAI/2.0/"
_ARXIV_NS = "http://arxiv.org/OAI/arXiv/"


async def _oai_harvest(oai_set: str, date_from: Optional[str] = None) -> List[dict]:
    """Harvest all records from an OAI-PMH set since date_from.
    Follows resumption tokens for complete pagination."""
    collected = []
    resumption_token = None
    page = 0
    max_pages = 30  # Safety limit

    while page < max_pages:
        if resumption_token:
            params = {"verb": "ListRecords", "resumptionToken": resumption_token}
        else:
            params = {
                "verb": "ListRecords",
                "metadataPrefix": "arXiv",
                "set": oai_set,
            }
            if date_from:
                params["from"] = date_from

        # OAI-PMH request with retry — no throttle needed (designed for bulk harvesting)
        xml_text = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=60.0,
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(_OAI_BASE, params=params)
                    resp.raise_for_status()
                    xml_text = resp.text
                    break
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"[OAI-PMH] set={oai_set} page {page} attempt {attempt+1} failed: "
                                   f"{type(e).__name__}: {str(e)[:80]}")
                    await asyncio.sleep(5 + random.uniform(0, 3))
                else:
                    raise

        if not xml_text:
            break

        papers, token = _parse_oai_arxiv_response(xml_text)
        collected.extend(papers)
        resumption_token = token

        if not token:
            break  # No more pages

        page += 1
        await asyncio.sleep(1)  # Brief pause between pages

    return collected


def _parse_oai_arxiv_response(xml_text: str) -> Tuple[List[dict], Optional[str]]:
    """Parse OAI-PMH ListRecords response with arXiv metadata prefix.
    Returns (papers_list, resumption_token_or_None)."""
    root = ET.fromstring(xml_text)

    # Check for OAI error
    error = root.find(f".//{{{_OAI_NS}}}error")
    if error is not None:
        code = error.get("code", "unknown")
        if code == "noRecordsMatch":
            return [], None
        raise ValueError(f"OAI-PMH error: {code} — {error.text}")

    papers = []
    for record in root.findall(f".//{{{_OAI_NS}}}record"):
        header = record.find(f"{{{_OAI_NS}}}header")
        if header is None or header.get("status") == "deleted":
            continue

        metadata = record.find(f".//{{{_ARXIV_NS}}}arXiv")
        if metadata is None:
            continue

        arxiv_id = _oai_text(metadata, "id") or ""
        if not arxiv_id:
            continue

        title = _oai_text(metadata, "title") or ""
        abstract = _oai_text(metadata, "abstract") or ""
        categories_str = _oai_text(metadata, "categories") or ""
        created = _oai_text(metadata, "created") or ""
        updated = _oai_text(metadata, "updated") or ""

        # Authors — structured in arXiv OAI format
        authors = []
        for author_el in metadata.findall(f".//{{{_ARXIV_NS}}}author"):
            keyname = author_el.findtext(f"{{{_ARXIV_NS}}}keyname", "").strip()
            forenames = author_el.findtext(f"{{{_ARXIV_NS}}}forenames", "").strip()
            if keyname:
                name = f"{forenames} {keyname}".strip() if forenames else keyname
                authors.append(name)

        categories = categories_str.split() if categories_str else []
        published = created  # Use CREATION date, not update date — revisions are handled by the dedup system

        # Build versioned arxiv_id if needed
        full_arxiv_id = arxiv_id  # OAI returns base IDs without version

        papers.append({
            "arxiv_id": full_arxiv_id,
            "title": title.strip().replace("\n", " "),
            "authors": authors[:8],
            "abstract": abstract.strip().replace("\n", " ")[:2000],
            "categories": categories,
            "published": published,
            "created": created,
            "updated": updated,
            "link": f"https://arxiv.org/abs/{full_arxiv_id}",
            "pdf_link": f"https://arxiv.org/pdf/{full_arxiv_id}",
        })

    # Get resumption token
    token_el = root.find(f".//{{{_OAI_NS}}}resumptionToken")
    token = token_el.text.strip() if token_el is not None and token_el.text else None

    return papers, token


def _oai_text(parent, tag: str) -> Optional[str]:
    """Get text from an arXiv-namespaced element."""
    el = parent.find(f"{{{_ARXIV_NS}}}{tag}")
    return el.text.strip() if el is not None and el.text else None


# ── REST API fallback ──────────────────────────────────────────────────

async def _fetch_arxiv_api(
    category: str = "cs.RO",
    max_results: int = 50,
    primary_only: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[dict]:
    """Fallback: fetch via the arXiv REST API (export.arxiv.org/api/query).
    Used when OAI-PMH is unavailable."""
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
                async with httpx.AsyncClient(timeout=45.0) as http_client:
                    response = await http_client.get(base_url, params=params)
                    response.raise_for_status()
                papers_batch = _parse_api_response(response.text)
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
                    logger.warning(f"[{category}] ArXiv API {kind}, retry {attempt+1}/{max_retries}")
                    await asyncio.sleep(wait)
                else:
                    raise

        if papers_batch is None:
            if last_error:
                raise last_error
            break

        if not papers_batch:
            break

        if primary_only:
            primary_papers = [p for p in papers_batch if p["categories"] and p["categories"][0] == category]
            collected.extend(primary_papers)
        else:
            collected.extend(papers_batch)

        if len(papers_batch) < batch_size:
            break

        start += batch_size
        logger.info(f"ArXiv API pagination: page {page+1}, collected {len(collected)} primary {category} papers")

    seen = set()
    unique = []
    for p in collected:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)

    return unique[:hard_cap]


def _parse_api_response(xml_text: str) -> List[dict]:
    """Parse arXiv REST API Atom response."""
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
