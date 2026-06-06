#!/usr/bin/env python3
"""DeFi paper fetcher — discovers and downloads decentralized finance papers
from all sources via OpenAlex (1,700+ papers, 70% open access).

Fetches metadata + PDFs from any open access source (SSRN, arXiv, journals,
preprint servers). No Cloudflare bypass needed for most PDFs.

Usage:
    # Fetch metadata only (fast)
    python3 scripts/defi_fetcher.py --max-papers 100

    # Fetch + download all available PDFs
    python3 scripts/defi_fetcher.py --max-papers 200 --download-pdfs

    # Custom query
    python3 scripts/defi_fetcher.py --query "cryptocurrency regulation" --max-papers 50 --download-pdfs

    # Save to MongoDB
    python3 scripts/defi_fetcher.py --max-papers 500 --download-pdfs --save-to-db
"""

import argparse
import asyncio
import json
import os
import sys
import time
import requests as req
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

OPENALEX_EMAIL = "kurate@kurate.org"


def fetch_openalex(query: str, max_results: int, years: str, types: str = None) -> list[dict]:
    """Fetch papers from OpenAlex across ALL sources (not just SSRN)."""
    papers = []
    cursor = "*"

    filters = [f"publication_year:{years}"]
    if types:
        filters.append(f"type:{types}")

    print(f'  Fetching from OpenAlex (cursor pagination)...')

    while len(papers) < max_results:
        per_page = min(200, max_results - len(papers))
        params = {
            "search": query,
            "filter": ",".join(filters),
            "sort": "publication_date:desc",
            "per_page": per_page,
            "cursor": cursor,
            "mailto": OPENALEX_EMAIL,
        }
        r = req.get("https://api.openalex.org/works", params=params, timeout=30)
        if r.status_code != 200:
            print(f'  OpenAlex error: HTTP {r.status_code}')
            break

        d = r.json()
        results = d.get("results", [])
        cursor = d.get("meta", {}).get("next_cursor")

        if not results:
            break

        for p in results:
            doi = (p.get("doi") or "").replace("https://doi.org/", "")

            # Reconstruct abstract
            abstract = ""
            aidx = p.get("abstract_inverted_index") or {}
            if aidx:
                wp = [(pos, w) for w, positions in aidx.items() for pos in positions]
                wp.sort()
                abstract = " ".join(w for _, w in wp)

            authors = [a.get("author", {}).get("display_name", "")
                       for a in p.get("authorships", []) if a.get("author", {}).get("display_name")]

            # Find PDF URL from any OA location
            pdf_url = None
            source_name = ""
            for loc in p.get("locations", []):
                if loc.get("pdf_url"):
                    pdf_url = loc["pdf_url"]
                    src = loc.get("source") or {}
                    source_name = src.get("display_name", "")
                    break
            # Fallback: best_oa_location
            if not pdf_url:
                best_oa = p.get("best_oa_location") or {}
                pdf_url = best_oa.get("pdf_url") or best_oa.get("url")
                if pdf_url and not pdf_url.endswith(".pdf"):
                    pdf_url = None  # Landing page, not a PDF

            # Primary source
            primary_loc = p.get("primary_location") or {}
            primary_source = (primary_loc.get("source") or {}).get("display_name", "")

            # Extract SSRN ID if applicable
            ssrn_id = ""
            if "ssrn" in doi:
                ssrn_id = doi.replace("10.2139/ssrn.", "")

            # ArXiv ID
            arxiv_id = ""
            for loc in p.get("locations", []):
                landing = loc.get("landing_page_url") or ""
                if "arxiv.org" in landing:
                    import re
                    m = re.search(r"(\d{4}\.\d{4,5})", landing)
                    if m:
                        arxiv_id = m.group(1)

            keywords = [k.get("display_name", "") for k in p.get("keywords", []) if k.get("display_name")]
            topics = [t.get("display_name", "") for t in p.get("topics", [])[:5] if t.get("display_name")]

            papers.append({
                "title": p.get("title", ""),
                "authors": authors,
                "abstract": abstract,
                "doi": doi,
                "ssrn_id": ssrn_id,
                "arxiv_id": arxiv_id,
                "publication_date": p.get("publication_date", ""),
                "type": p.get("type", ""),
                "source": primary_source,
                "pdf_url": pdf_url,
                "pdf_source": source_name,
                "is_oa": p.get("is_oa", False),
                "cited_by_count": p.get("cited_by_count", 0),
                "keywords": keywords,
                "topics": topics,
                "openalex_id": p.get("id", ""),
            })

        print(f'  ...{len(papers)} papers fetched')

        if not cursor:
            break
        time.sleep(0.1)  # Rate limit

    return papers[:max_results]


def download_pdf(url: str, output_path: str, timeout: int = 30) -> bool:
    """Download a PDF from a direct URL. Returns True on success."""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
        return True

    try:
        r = req.get(url, timeout=timeout, stream=True,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; KurateBot/1.0; mailto:kurate@kurate.org)"})
        if r.status_code == 200:
            content_type = r.headers.get("content-type", "")
            # Accept PDF or octet-stream
            if "pdf" in content_type or "octet" in content_type or url.endswith(".pdf"):
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                size = os.path.getsize(output_path)
                if size > 10000:
                    return True
                os.remove(output_path)
        return False
    except Exception:
        return False


async def main():
    parser = argparse.ArgumentParser(description="DeFi paper fetcher via OpenAlex")
    parser.add_argument("--query", type=str, default='"decentralized finance"',
                        help='Search query (use quotes for exact phrase)')
    parser.add_argument("--max-papers", type=int, default=100, help="Max papers to fetch")
    parser.add_argument("--years", type=str, default="2025|2026", help="Publication years")
    parser.add_argument("--types", type=str, default=None,
                        help="Filter by type: article|preprint|book-chapter (comma-separated)")
    parser.add_argument("--output-dir", type=str, default="/tmp/defi_papers", help="Output directory")
    parser.add_argument("--download-pdfs", action="store_true", help="Download available PDFs")
    parser.add_argument("--save-to-db", action="store_true", help="Save to MongoDB")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    pdf_dir = os.path.join(args.output_dir, "pdfs")
    if args.download_pdfs:
        os.makedirs(pdf_dir, exist_ok=True)

    # Step 1: Fetch metadata
    print(f'Searching OpenAlex: {args.query} (years: {args.years})')
    papers = fetch_openalex(args.query, args.max_papers, args.years, args.types)
    print(f'\nTotal: {len(papers)} papers')

    oa_count = sum(1 for p in papers if p["is_oa"])
    pdf_available = sum(1 for p in papers if p["pdf_url"])
    print(f'Open access: {oa_count} ({oa_count*100//max(len(papers),1)}%)')
    print(f'PDF URL available: {pdf_available}')

    # Step 2: Download PDFs
    downloaded = 0
    if args.download_pdfs:
        print(f'\nDownloading PDFs...')
        for i, p in enumerate(papers):
            if not p["pdf_url"]:
                continue

            safe_name = (p["doi"] or p["title"][:40]).replace("/", "_").replace(" ", "_")
            pdf_path = os.path.join(pdf_dir, f"{safe_name}.pdf")

            success = download_pdf(p["pdf_url"], pdf_path)
            if success:
                p["pdf_path"] = pdf_path
                downloaded += 1
            else:
                p["pdf_path"] = None

            if (i + 1) % 50 == 0:
                print(f'  ...{i+1}/{len(papers)} checked, {downloaded} downloaded')
            time.sleep(0.2)

        print(f'Downloaded: {downloaded}/{pdf_available} PDFs')

    # Step 3: Save metadata
    output_file = os.path.join(args.output_dir, "defi_papers.jsonl")
    with open(output_file, "w") as f:
        for p in papers:
            f.write(json.dumps(p, default=str) + "\n")

    # Step 4: Save to DB
    if args.save_to_db:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent / ".env")
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]

            saved = 0
            for p in papers:
                key = {"doi": p["doi"]} if p["doi"] else {"title": p["title"]}
                await db.defi_papers.update_one(key, {"$set": {
                    **p,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }}, upsert=True)
                saved += 1
            print(f'Saved {saved} papers to MongoDB (defi_papers collection)')
        except Exception as e:
            print(f'DB save failed: {e}')

    # Summary
    by_source = {}
    for p in papers:
        src = p["source"] or "Unknown"
        by_source[src] = by_source.get(src, 0) + 1

    print(f'\n=== Summary ===')
    print(f'Papers: {len(papers)}')
    print(f'Open access: {oa_count}')
    print(f'PDFs available: {pdf_available}')
    if args.download_pdfs:
        print(f'PDFs downloaded: {downloaded}')
    print(f'Output: {output_file}')
    print(f'\nTop sources:')
    for src, count in sorted(by_source.items(), key=lambda x: -x[1])[:10]:
        print(f'  {src[:50]:50s} {count}')


if __name__ == "__main__":
    asyncio.run(main())
