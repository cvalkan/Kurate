"""ChemRxiv paper fetcher using the Cambridge Open Engage API (same as paperscraper)."""
import asyncio
import re
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from core.config import logger

# Cambridge Open Engage API (fallback that bypasses Cloudflare on chemrxiv.org)
COE_API_BASE = "https://www.cambridge.org/engage/coe/public-api/v1/"
COE_ORIGIN = "CHEMRXIV"

CHEMRXIV_SUBJECTS = {
    "chemrxiv.IC": {"name": "Inorganic Chemistry"},
}

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "paperscraper/1.0 (+https)",
}


async def fetch_chemrxiv_papers(category: str = "chemrxiv.IC", max_results: int = 50) -> List[Dict]:
    """Fetch recent papers from ChemRxiv via the Cambridge Open Engage API.
    
    Uses the same API as paperscraper but filtered for the target subject area.
    Returns papers with full metadata suitable for the tournament pipeline.
    """
    subject = CHEMRXIV_SUBJECTS.get(category)
    if not subject:
        logger.error(f"Unknown ChemRxiv category: {category}")
        return []

    papers = []
    page_size = 50
    skip = 0

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        while len(papers) < max_results:
            params = {
                "limit": page_size,
                "skip": skip,
                "sort": "PUBLISHED_DATE_DESC",
            }
            try:
                resp = await client.get(f"{COE_API_BASE}items", params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"ChemRxiv API error at skip={skip}: {e}")
                break

            hits = data.get("itemHits", [])
            if not hits:
                break

            for hit in hits:
                item = hit.get("item", hit)
                # Filter: only CHEMRXIV origin papers
                if item.get("origin") != COE_ORIGIN:
                    continue

                # Filter by subject (check if paper has the target subject)
                item_subjects = [s.get("name", "") for s in (item.get("subjects") or []) if isinstance(s, dict)]
                if subject["name"] not in item_subjects:
                    continue

                paper = _parse_item(item, category)
                if paper:
                    papers.append(paper)
                    if len(papers) >= max_results:
                        break

            skip += page_size
            if len(hits) < page_size:
                break  # Last page

    logger.info(f"ChemRxiv API: fetched {len(papers)} {category} papers")
    return papers[:max_results]


def _parse_item(item: dict, category: str) -> Optional[Dict]:
    """Parse a Cambridge Open Engage API item into our paper format."""
    title = item.get("title", "").strip()
    if not title or len(title) < 10:
        return None

    # Authors
    authors = []
    for author in item.get("authors", []) or []:
        first = (author or {}).get("firstName", "")
        last = (author or {}).get("lastName", "")
        name = " ".join(part for part in [first, last] if part).strip()
        if name:
            authors.append(name)

    # Abstract (HTML → plain text)
    abstract_html = item.get("abstract", "")
    if abstract_html:
        abstract = BeautifulSoup(abstract_html, "html.parser").get_text(separator=" ").strip()
        if abstract.startswith("Abstract"):
            abstract = abstract[8:].strip()
    else:
        abstract = ""

    # DOI
    doi = item.get("doi", "")

    # Published date
    status_date = item.get("statusDate", "")
    published = status_date if status_date else datetime.now(timezone.utc).isoformat()

    # Paper link
    link = f"https://chemrxiv.org/doi/full/{doi}" if doi else item.get("url", "")

    # PDF URL from asset
    pdf_link = None
    asset = item.get("asset")
    if isinstance(asset, dict):
        original = asset.get("original")
        if isinstance(original, dict) and original.get("url"):
            pdf_link = original["url"]

    # Use DOI as the dedup key (strip version suffix for consistency)
    chemrxiv_id = doi

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "link": link,
        "pdf_link": pdf_link,
        "doi": doi,
        "chemrxiv_id": chemrxiv_id,
        "categories": [category],
    }
