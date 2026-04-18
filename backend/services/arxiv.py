import re
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from core.config import logger


def strip_arxiv_version(arxiv_id: str) -> Tuple[str, int]:
    """Strip version suffix from an arXiv ID.
    '2602.12345v2' → ('2602.12345', 2)
    '2602.12345'   → ('2602.12345', 1)
    """
    m = re.match(r'^(.+?)v(\d+)$', arxiv_id)
    if m:
        return m.group(1), int(m.group(2))
    return arxiv_id, 1


async def fetch_arxiv_papers(
    category: str = "cs.RO",
    max_results: int = 50,
    primary_only: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[dict]:
    base_url = "https://export.arxiv.org/api/query"
    query_parts = [f"cat:{category}"]

    if date_from or date_to:
        from_str = date_from.replace("-", "") + "0000" if date_from else "190001010000"
        to_str = date_to.replace("-", "") + "2359" if date_to else "209912312359"
        query_parts.append(f"submittedDate:[{from_str} TO {to_str}]")

    query = " AND ".join(query_parts)
    collected = []
    start = 0
    # For niche categories, primary papers may be sparse — paginate to find enough
    batch_size = max(max_results * 3, 150)
    max_pages = 5  # Safety limit: don't fetch more than 5 pages

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

        max_retries = 3
        last_error = None
        papers_batch = None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.get(base_url, params=params, timeout=30.0)
                    response.raise_for_status()
                papers_batch = _parse_arxiv_response(response.text)
                break
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429 or e.response.status_code >= 500:
                    wait_time = (attempt + 1) * 5
                    logger.warning(f"ArXiv error {e.response.status_code}, waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    raise

        if papers_batch is None:
            if last_error:
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
        await asyncio.sleep(3)  # Rate limit between pages

    # Deduplicate by arxiv_id (in case of overlap)
    seen = set()
    unique = []
    for p in collected:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)

    return unique[:max_results]


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
