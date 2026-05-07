"""IACR ePrint Archive fetcher.

Uses OAI-PMH for date-range queries (bulk/catchup) and RSS for recent papers.
Respects robots.txt: only /oai and /rss are allowed for automated access.
"""
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from core.config import logger

OAI_BASE = "https://eprint.iacr.org/oai"
RSS_URL = "https://eprint.iacr.org/rss/rss.xml"

# IACR categories
IACR_CATEGORIES = [
    "Applications",
    "Cryptographic protocols",
    "Foundations",
    "Implementation",
    "Secret-key cryptography",
    "Public-key cryptography",
    "Attacks and cryptanalysis",
]

# Namespaces for XML parsing
NS_OAI = {"oai": "http://www.openarchives.org/OAI/2.0/"}
NS_DC = {"dc": "http://purl.org/dc/elements/1.1/"}
NS_OAI_DC = {"oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/"}


async def fetch_iacr_papers_oai(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_papers: int = 500,
) -> List[dict]:
    """Fetch papers from IACR ePrint via OAI-PMH.

    Args:
        date_from: ISO date string (YYYY-MM-DD). Defaults to 7 days ago.
        date_to: ISO date string. Defaults to today.
        max_papers: Safety cap on total papers fetched.

    Returns:
        List of paper dicts matching the Kurate paper schema.
    """
    if not date_from:
        date_from = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    collected = []
    resumption_token = None
    page = 0
    max_pages = 50  # Safety limit (~50 papers/page × 50 = 2500 max)

    while page < max_pages and len(collected) < max_papers:
        params = {}
        if resumption_token:
            params["verb"] = "ListRecords"
            params["resumptionToken"] = resumption_token
        else:
            params = {
                "verb": "ListRecords",
                "metadataPrefix": "oai_dc",
                "from": date_from,
                "until": date_to,
            }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    OAI_BASE, params=params, timeout=30.0,
                    headers={"User-Agent": "Kurate.org/1.0 (Academic Research Aggregator; mailto:info@kurate.org)"},
                )
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"IACR OAI-PMH request failed (page {page}): {e}")
            from core.memlog import log_mem
            log_mem(f"IACR OAI-PMH FAILED (page {page}): {str(e)[:100]}")
            break

        papers, token = _parse_oai_response(resp.text)
        collected.extend(papers)
        resumption_token = token

        if not token:
            break  # No more pages

        page += 1
        await asyncio.sleep(2)  # Be polite

    logger.info(f"IACR OAI-PMH: fetched {len(collected)} papers from {date_from} to {date_to}")
    return collected[:max_papers]


async def fetch_iacr_papers_rss() -> List[dict]:
    """Fetch the ~100 most recent papers from IACR RSS feed.

    Useful for quick checks of new papers without date math.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                RSS_URL, timeout=20.0,
                headers={"User-Agent": "Kurate.org/1.0 (Academic Research Aggregator; mailto:info@kurate.org)"},
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"IACR RSS fetch failed: {e}")
        return []

    papers = _parse_rss_response(resp.text)
    logger.info(f"IACR RSS: fetched {len(papers)} recent papers")
    return papers


def _parse_oai_response(xml_text: str) -> tuple:
    """Parse OAI-PMH ListRecords response.

    Returns (papers_list, resumption_token_or_None).
    """
    root = ET.fromstring(xml_text)

    # Check for OAI error
    error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
    if error is not None:
        code = error.get("code", "unknown")
        logger.warning(f"IACR OAI-PMH error: {code} - {error.text}")
        return [], None

    papers = []
    records = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")

    for record in records:
        header = record.find("{http://www.openarchives.org/OAI/2.0/}header")
        if header is None:
            continue
        # Skip deleted records
        if header.get("status") == "deleted":
            continue

        identifier = header.findtext("{http://www.openarchives.org/OAI/2.0/}identifier", "")
        datestamp = header.findtext("{http://www.openarchives.org/OAI/2.0/}datestamp", "")

        metadata = record.find(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
        if metadata is None:
            continue

        # Extract fields
        title = _dc_text(metadata, "title")
        if not title:
            continue

        authors = [el.text.strip() for el in metadata.findall("{http://purl.org/dc/elements/1.1/}creator") if el.text]
        subjects = [el.text.strip() for el in metadata.findall("{http://purl.org/dc/elements/1.1/}subject") if el.text]
        description = _dc_text(metadata, "description")
        url = _dc_text(metadata, "identifier")

        # Extract paper ID (e.g., "2026/821" from identifier)
        iacr_id = ""
        if "eprint.iacr.org" in (url or ""):
            iacr_id = url.rstrip("/").split("eprint.iacr.org/")[-1]
        elif "oai:eprint.iacr.org:" in identifier:
            iacr_id = identifier.split("oai:eprint.iacr.org:")[-1]

        # Build published datetime from datestamp
        published = datestamp if datestamp else ""

        papers.append({
            "iacr_id": iacr_id,
            "title": title.replace("\n", " ").strip(),
            "authors": authors[:10],
            "abstract": (description or "")[:3000],
            "categories": [_normalize_category(s) for s in subjects] or ["iacr.crypto"],
            "published": published,
            "link": url or f"https://eprint.iacr.org/{iacr_id}",
            "pdf_link": f"https://eprint.iacr.org/{iacr_id}.pdf" if iacr_id else None,
        })

    # Get resumption token
    token_el = root.find(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
    token = token_el.text.strip() if token_el is not None and token_el.text else None

    return papers, token


def _parse_rss_response(xml_text: str) -> List[dict]:
    """Parse IACR RSS feed."""
    root = ET.fromstring(xml_text)
    papers = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        if not title:
            continue

        link = item.findtext("link", "").strip()
        description = item.findtext("description", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        category = item.findtext("category", "").strip()

        # Authors from dc:creator elements
        authors = [el.text.strip() for el in item.findall("{http://purl.org/dc/elements/1.1/}creator") if el.text]

        # PDF from enclosure
        enclosure = item.find("enclosure")
        pdf_link = enclosure.get("url") if enclosure is not None else None

        # Extract IACR ID from link
        iacr_id = ""
        if "eprint.iacr.org" in link:
            iacr_id = link.rstrip("/").split("eprint.iacr.org/")[-1]

        # Parse pubDate to ISO format
        published = ""
        if pub_date:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub_date)
                published = dt.isoformat()
            except Exception:
                published = pub_date

        papers.append({
            "iacr_id": iacr_id,
            "title": title.replace("\n", " "),
            "authors": authors[:10],
            "abstract": description[:3000],
            "categories": [_normalize_category(category)] if category else ["iacr.crypto"],
            "published": published,
            "link": link,
            "pdf_link": pdf_link,
        })

    return papers


def _dc_text(metadata_el, field: str) -> Optional[str]:
    """Get text from a dc:field element."""
    el = metadata_el.find(f"{{http://purl.org/dc/elements/1.1/}}{field}")
    return el.text.strip() if el is not None and el.text else None


def _normalize_category(subject: str) -> str:
    """Normalize IACR subject to a consistent category key."""
    mapping = {
        "applications": "iacr.app",
        "cryptographic protocols": "iacr.proto",
        "foundations": "iacr.found",
        "implementation": "iacr.impl",
        "secret-key cryptography": "iacr.sk",
        "public-key cryptography": "iacr.pk",
        "attacks and cryptanalysis": "iacr.attack",
    }
    return mapping.get(subject.lower().strip(), "iacr.crypto")
