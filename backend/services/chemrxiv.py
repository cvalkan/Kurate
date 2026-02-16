"""ChemRxiv paper fetcher — uses Playwright to bypass Cloudflare and scrape search results."""
import re
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from core.config import logger

CHEMRXIV_SEARCH_URL = "https://chemrxiv.org/action/doSearch"

CHEMRXIV_SUBJECTS = {
    "chemrxiv.IC": {"concept_id": "502564", "name": "Inorganic Chemistry"},
}


async def fetch_chemrxiv_papers(category: str = "chemrxiv.IC", max_results: int = 50) -> List[Dict]:
    """Fetch recent papers from ChemRxiv using Playwright to handle Cloudflare."""
    subject = CHEMRXIV_SUBJECTS.get(category)
    if not subject:
        logger.error(f"Unknown ChemRxiv category: {category}")
        return []

    papers = []
    pages_needed = (max_results + 19) // 20

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed — cannot fetch ChemRxiv papers")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        for pg in range(pages_needed):
            if len(papers) >= max_results:
                break
            url = f"{CHEMRXIV_SEARCH_URL}?ConceptID={subject['concept_id']}&sortBy=Earliest&startPage={pg}&pageSize=20"
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)
                html = await page.content()
                page_papers = _parse_search_results(html, category)
                papers.extend(page_papers)
                logger.info(f"ChemRxiv page {pg}: found {len(page_papers)} papers")
            except Exception as e:
                logger.error(f"ChemRxiv fetch page {pg} failed: {e}")
                break

        # Fetch full abstracts for papers with truncated ones
        for paper in papers[:max_results]:
            if paper.get("link") and len(paper.get("abstract", "")) < 200:
                try:
                    await page.goto(paper["link"], wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(1000)
                    html = await page.content()
                    full_abs = _extract_full_abstract(html)
                    if full_abs and len(full_abs) > len(paper.get("abstract", "")):
                        paper["abstract"] = full_abs
                except Exception:
                    pass

        await browser.close()

    papers = papers[:max_results]
    logger.info(f"ChemRxiv: fetched {len(papers)} {category} papers")
    return papers


def _parse_search_results(html: str, category: str) -> List[Dict]:
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


def _extract_full_abstract(html: str) -> Optional[str]:
    """Extract full abstract from a ChemRxiv paper page."""
    meta_match = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"', html)
    if meta_match:
        abstract = meta_match.group(1).strip()
        if len(abstract) > 100:
            return abstract
    abstract_match = re.search(
        r'class="abstract[^"]*"[^>]*>(.*?)</(?:div|section)>',
        html, re.DOTALL,
    )
    if abstract_match:
        abstract = re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
        abstract = re.sub(r'\s+', ' ', abstract)
        if len(abstract) > 100:
            return abstract
    return None
