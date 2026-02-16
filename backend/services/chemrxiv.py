"""ChemRxiv paper fetcher.

Uses a seed file for paper discovery (DOIs from web scraping) and the Cambridge
Open Engage DOI API for full metadata + PDF URLs. Falls back to paperscraper's
save_pdf for DOIs not in the Cambridge API.
"""
import asyncio
import json
import os
import io
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
import httpx
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from core.config import logger

COE_DOI_API = "https://www.cambridge.org/engage/coe/public-api/v1/items/doi/"

CHEMRXIV_SUBJECTS = {
    "chemrxiv.IC": {"name": "Inorganic Chemistry"},
}

SEED_FILE = Path(__file__).parent.parent / "data" / "chemrxiv_seed.json"
HEADERS = {"Accept": "application/json", "User-Agent": "paperscraper/1.0 (+https)"}


async def fetch_chemrxiv_papers(category: str = "chemrxiv.IC", max_results: int = 50) -> List[Dict]:
    """Fetch ChemRxiv papers using seed DOIs + Cambridge DOI API for metadata & PDFs.
    
    Skips enrichment if all seed papers are already in the database.
    """
    if not SEED_FILE.exists():
        logger.error(f"ChemRxiv seed file not found: {SEED_FILE}")
        return []

    with open(SEED_FILE) as f:
        seed_papers = json.load(f)
    seed_papers = [p for p in seed_papers if category in p.get("categories", [])]
    logger.info(f"ChemRxiv: {len(seed_papers)} papers in seed file for {category}")

    # Quick check: if all seed DOIs already exist in DB, skip expensive API enrichment
    from core.config import db as _db
    existing_count = await _db.papers.count_documents({"categories.0": category})
    if existing_count >= len(seed_papers):
        return []  # All papers already ingested

    papers = []
    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        for seed in seed_papers[:max_results]:
            doi = seed.get("doi", "")
            if not doi:
                continue
            enriched = await _enrich_via_api(client, doi, seed, category)
            if enriched:
                papers.append(enriched)
            else:
                papers.append(seed)
            await asyncio.sleep(0.3)

    logger.info(f"ChemRxiv: fetched {len(papers)} {category} papers ({sum(1 for p in papers if p.get('pdf_link'))} with PDF)")
    return papers


async def _enrich_via_api(client: httpx.AsyncClient, doi: str, seed: dict, category: str) -> Optional[Dict]:
    """Enrich a seed paper with full metadata + PDF URL from Cambridge DOI API."""
    try:
        resp = await client.get(f"{COE_DOI_API}{doi}")
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception as e:
        logger.debug(f"ChemRxiv DOI API failed for {doi}: {e}")
        return None

    item = data.get("item", data)

    # Title
    title = item.get("title", seed.get("title", "")).strip()
    if not title:
        return None

    # Authors
    authors = []
    for author in item.get("authors", []) or []:
        first = (author or {}).get("firstName", "")
        last = (author or {}).get("lastName", "")
        name = " ".join(part for part in [first, last] if part).strip()
        if name:
            authors.append(name)
    if not authors:
        authors = seed.get("authors", [])

    # Abstract (HTML → plain text)
    abstract_html = item.get("abstract", "")
    if abstract_html:
        abstract = BeautifulSoup(abstract_html, "html.parser").get_text(separator=" ").strip()
        if abstract.startswith("Abstract"):
            abstract = abstract[8:].strip()
    else:
        abstract = seed.get("abstract", "")

    # Published date
    published = item.get("statusDate", seed.get("published", ""))

    # Link
    link = seed.get("link", f"https://chemrxiv.org/doi/full/{doi}")

    # PDF URL from asset (this is the key value — bypasses Cloudflare)
    pdf_link = None
    asset = item.get("asset")
    if isinstance(asset, dict):
        original = asset.get("original")
        if isinstance(original, dict) and original.get("url"):
            pdf_link = original["url"]

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "link": link,
        "pdf_link": pdf_link,
        "doi": doi,
        "chemrxiv_id": doi,
        "categories": [category],
    }
