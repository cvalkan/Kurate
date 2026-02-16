"""ChemRxiv paper fetcher — scrapes search results from chemrxiv.org."""
import re
import httpx
from typing import List, Dict, Optional
from core.config import logger

CHEMRXIV_SEARCH_URL = "https://chemrxiv.org/action/doSearch"

# Subject IDs for ChemRxiv categories
CHEMRXIV_SUBJECTS = {
    "chemrxiv.IC": {"concept_id": "502564", "name": "Inorganic Chemistry"},
}


async def fetch_chemrxiv_papers(category: str = "chemrxiv.IC", max_results: int = 50) -> List[Dict]:
    """Fetch recent papers from ChemRxiv by scraping search results.
    
    Returns list of paper dicts with keys: title, authors, abstract, published,
    link, pdf_link, doi, chemrxiv_id, categories.
    """
    subject = CHEMRXIV_SUBJECTS.get(category)
    if not subject:
        logger.error(f"Unknown ChemRxiv category: {category}")
        return []

    papers = []
    pages_needed = (max_results + 19) // 20  # 20 results per page

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for page in range(pages_needed):
            if len(papers) >= max_results:
                break
            try:
                params = {
                    "ConceptID": subject["concept_id"],
                    "sortBy": "Earliest",
                    "startPage": str(page),
                    "pageSize": "20",
                }
                resp = await client.get(CHEMRXIV_SEARCH_URL, params=params)
                resp.raise_for_status()
                html = resp.text

                page_papers = _parse_search_results(html, category)
                papers.extend(page_papers)
                logger.info(f"ChemRxiv page {page}: found {len(page_papers)} papers")
            except Exception as e:
                logger.error(f"ChemRxiv fetch page {page} failed: {e}")
                break

    papers = papers[:max_results]

    # Fetch full abstracts for each paper (search results are truncated)
    for i, paper in enumerate(papers):
        if paper.get("link"):
            try:
                full_abstract = await _fetch_full_abstract(client=None, url=paper["link"])
                if full_abstract and len(full_abstract) > len(paper.get("abstract", "")):
                    paper["abstract"] = full_abstract
            except Exception as e:
                logger.debug(f"Could not fetch full abstract for {paper.get('title', '')[:40]}: {e}")

    logger.info(f"ChemRxiv: fetched {len(papers)} {category} papers")
    return papers


def _parse_search_results(html: str, category: str) -> List[Dict]:
    """Parse papers from ChemRxiv search results HTML."""
    papers = []

    # Pattern: links to individual paper pages
    # Format: https://chemrxiv.org/doi/full/10.26434/chemrxiv.XXXXX/vN or chemrxiv-XXXX-XXXXX/vN
    paper_blocks = re.findall(
        r'<a[^>]*href="(https://chemrxiv\.org/doi/full/([^"]+))"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )

    # Also capture dates - they appear as text like "16 February 2026"
    date_pattern = re.compile(r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})')
    dates = date_pattern.findall(html)

    # Parse author blocks
    author_pattern = re.compile(r'ContribAuthorRaw=[^"]*"[^>]*>([^<]+)</a>')
    
    # Split HTML into paper sections (each starts with a date)
    sections = re.split(r'(?=\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})', html)

    for section in sections[1:]:  # Skip the first (header) section
        # Extract date
        date_match = date_pattern.search(section)
        if not date_match:
            continue
        date_str = date_match.group(1)

        # Extract title and DOI link
        title_match = re.search(
            r'<a[^>]*href="(https://chemrxiv\.org/doi/full/([^"]+))"[^>]*>(.*?)</a>',
            section, re.DOTALL
        )
        if not title_match:
            continue

        link = title_match.group(1)
        doi_path = title_match.group(2)
        raw_title = title_match.group(3)
        # Clean title: remove HTML tags and extra whitespace
        title = re.sub(r'<[^>]+>', '', raw_title).strip()
        title = re.sub(r'\s+', ' ', title)

        if not title or len(title) < 10:
            continue

        # Extract DOI
        doi = f"10.26434/{doi_path.split('/v')[0]}" if doi_path else ""

        # Extract authors
        authors = author_pattern.findall(section)
        # Deduplicate while preserving order
        seen = set()
        unique_authors = []
        for a in authors:
            a = a.strip()
            if a and a not in seen and len(a) > 1:
                seen.add(a)
                unique_authors.append(a)

        # Extract abstract snippet (text after the author list, before "View all")
        abstract = ""
        # Find text content after authors block
        abstract_match = re.search(
            r'(?:and\s*\d+\s*others|0\s*others)\s*</.*?>(.*?)(?:<a[^>]*>View all|$)',
            section, re.DOTALL
        )
        if abstract_match:
            abstract = re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
            abstract = re.sub(r'\s+', ' ', abstract)

        # Parse date to ISO format
        try:
            from datetime import datetime
            parsed_date = datetime.strptime(date_str, "%d %B %Y")
            published = parsed_date.strftime("%Y-%m-%dT00:00:00Z")
        except Exception:
            published = date_str

        # Construct PDF link from DOI
        # ChemRxiv PDF pattern: /doi/pdf/{doi_path}
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


async def _fetch_full_abstract(client: Optional[httpx.AsyncClient], url: str) -> Optional[str]:
    """Fetch the full abstract from an individual paper page."""
    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        should_close = True

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

        # Look for abstract in meta tag or structured content
        # Try og:description meta tag first
        meta_match = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"', html)
        if meta_match:
            abstract = meta_match.group(1).strip()
            if len(abstract) > 100:
                return abstract

        # Try finding abstract section in the page
        abstract_match = re.search(
            r'(?:abstract|Abstract).*?</h\d>.*?<(?:p|div)[^>]*>(.*?)</(?:p|div)>',
            html, re.DOTALL
        )
        if abstract_match:
            abstract = re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
            abstract = re.sub(r'\s+', ' ', abstract)
            if len(abstract) > 100:
                return abstract

        return None
    except Exception:
        return None
    finally:
        if should_close:
            await client.aclose()
