"""ChemRxiv paper fetcher — uses crawl_tool data or lightweight scraping."""
import re
import json
import httpx
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from core.config import logger

CHEMRXIV_SUBJECTS = {
    "chemrxiv.IC": {"concept_id": "502564", "name": "Inorganic Chemistry"},
}

SEED_FILE = Path(__file__).parent.parent / "data" / "chemrxiv_seed.json"


async def fetch_chemrxiv_papers(category: str = "chemrxiv.IC", max_results: int = 50) -> List[Dict]:
    """Fetch papers from ChemRxiv. Uses seed file if available, else tries HTTP scraping."""
    subject = CHEMRXIV_SUBJECTS.get(category)
    if not subject:
        logger.error(f"Unknown ChemRxiv category: {category}")
        return []

    # Check for seed file first
    if SEED_FILE.exists():
        try:
            with open(SEED_FILE) as f:
                papers = json.load(f)
            papers = [p for p in papers if category in p.get("categories", [])]
            logger.info(f"ChemRxiv: loaded {len(papers)} papers from seed file")
            return papers[:max_results]
        except Exception as e:
            logger.warning(f"ChemRxiv seed file error: {e}")

    # Fallback: try HTTP with browser-like headers
    papers = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    pages_needed = (max_results + 19) // 20

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for pg in range(pages_needed):
            if len(papers) >= max_results:
                break
            url = f"https://chemrxiv.org/action/doSearch?ConceptID={subject['concept_id']}&sortBy=Earliest&startPage={pg}&pageSize=20"
            try:
                resp = await client.get(url)
                if resp.status_code == 403:
                    logger.warning(f"ChemRxiv 403 (Cloudflare) on page {pg} — use seed file instead")
                    break
                resp.raise_for_status()
                page_papers = parse_search_html(resp.text, category)
                papers.extend(page_papers)
            except Exception as e:
                logger.error(f"ChemRxiv fetch page {pg}: {e}")
                break

    logger.info(f"ChemRxiv: fetched {len(papers)} {category} papers")
    return papers[:max_results]


def parse_search_html(html: str, category: str) -> List[Dict]:
    """Parse papers from ChemRxiv search results HTML."""
    papers = []
    date_pattern = re.compile(
        r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})'
    )
    author_pattern = re.compile(r'ContribAuthorRaw=[^"]*"[^>]*>([^<]+)</a>')

    sections = re.split(
        r'(?=\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
        html,
    )

    for section in sections[1:]:
        date_match = date_pattern.search(section)
        if not date_match:
            continue
        date_str = date_match.group(1)

        title_match = re.search(
            r'<a[^>]*href="(https://chemrxiv\.org/doi/full/([^"]+))"[^>]*>(.*?)</a>',
            section, re.DOTALL,
        )
        if not title_match:
            continue

        link = title_match.group(1)
        doi_path = title_match.group(2)
        title = re.sub(r'<[^>]+>', '', title_match.group(3)).strip()
        title = re.sub(r'\s+', ' ', title)
        if not title or len(title) < 10:
            continue

        doi = f"10.26434/{doi_path.split('/v')[0]}" if doi_path else ""

        authors = author_pattern.findall(section)
        seen = set()
        unique_authors = []
        for a in authors:
            a = a.strip()
            if a and a not in seen and len(a) > 1:
                seen.add(a)
                unique_authors.append(a)

        abstract = ""
        abstract_match = re.search(
            r'(?:and\s*\d+\s*others|0\s*others)\s*</.*?>(.*?)(?:<a[^>]*>View all|$)',
            section, re.DOTALL,
        )
        if abstract_match:
            abstract = re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
            abstract = re.sub(r'\s+', ' ', abstract)

        try:
            parsed_date = datetime.strptime(date_str, "%d %B %Y")
            published = parsed_date.strftime("%Y-%m-%dT00:00:00Z")
        except Exception:
            published = date_str

        pdf_link = f"https://chemrxiv.org/doi/pdf/{doi_path}" if doi_path else None

        papers.append({
            "title": title,
            "authors": unique_authors,
            "abstract": abstract,
            "published": published,
            "link": link,
            "pdf_link": pdf_link,
            "doi": doi,
            "chemrxiv_id": doi_path,
            "categories": [category],
        })

    return papers
