import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional
from core.config import logger


async def fetch_arxiv_papers(
    category: str = "cs.RO",
    max_results: int = 50,
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
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(base_url, params=params, timeout=30.0)
                response.raise_for_status()
            return _parse_arxiv_response(response.text)
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code == 429:
                wait_time = (attempt + 1) * 5
                logger.warning(f"ArXiv rate limited, waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                raise

    raise last_error


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
