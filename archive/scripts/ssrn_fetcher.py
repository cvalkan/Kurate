#!/usr/bin/env python3
"""SSRN paper fetcher — discovers DeFi/Crypto preprints via OpenAlex,
extracts metadata, and optionally downloads PDFs via Playwright.

OpenAlex indexes 1.5M+ SSRN papers with full metadata (title, authors,
abstract, DOI). No authentication or Cloudflare bypass needed for discovery.
PDF download still requires Playwright (SSRN blocks programmatic access).

Usage:
    # Discovery + metadata only (fast, no browser needed)
    python3 scripts/ssrn_fetcher.py --query "decentralized finance" --max-papers 20

    # With PDF download (slower, uses Playwright)
    python3 scripts/ssrn_fetcher.py --query "cryptocurrency" --max-papers 10 --download-pdfs

    # Specific SSRN IDs
    python3 scripts/ssrn_fetcher.py --ssrn-ids 6190060,6120207,4942313

    # Save to MongoDB
    python3 scripts/ssrn_fetcher.py --query "DeFi" --save-to-db
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

OPENALEX_SSRN_SOURCE = "S4210172589"  # SSRN Electronic Journal


def search_openalex(query: str, max_results: int = 20, years: str = "2024|2025|2026") -> list[dict]:
    """Search SSRN papers via OpenAlex API. Returns metadata without needing Cloudflare bypass."""
    import requests

    papers = []
    page = 1
    per_page = min(max_results, 50)

    while len(papers) < max_results:
        r = requests.get("https://api.openalex.org/works", params={
            "search": query,
            "filter": f"locations.source.id:{OPENALEX_SSRN_SOURCE},publication_year:{years}",
            "sort": "publication_date:desc",
            "per_page": per_page,
            "page": page,
        }, timeout=15)

        if r.status_code != 200:
            print(f"  OpenAlex error: HTTP {r.status_code}")
            break

        d = r.json()
        results = d.get("results", [])
        if not results:
            break

        for p in results:
            doi = (p.get("doi") or "").replace("https://doi.org/", "")
            ssrn_id = doi.replace("10.2139/ssrn.", "") if "ssrn" in doi else ""
            if not ssrn_id:
                continue

            # Reconstruct abstract from inverted index
            abstract = ""
            aidx = p.get("abstract_inverted_index") or {}
            if aidx:
                wp = [(pos, w) for w, positions in aidx.items() for pos in positions]
                wp.sort()
                abstract = " ".join(w for _, w in wp)

            authors = [a.get("author", {}).get("display_name", "")
                       for a in p.get("authorships", [])]

            keywords = [k.get("display_name", "") for k in p.get("keywords", [])]
            topics = [t.get("display_name", "") for t in p.get("topics", [])[:5]]

            papers.append({
                "ssrn_id": ssrn_id,
                "title": p.get("title", ""),
                "authors": [a for a in authors if a],
                "abstract": abstract,
                "doi": doi,
                "publication_date": p.get("publication_date", ""),
                "keywords": keywords,
                "topics": topics,
                "cited_by_count": p.get("cited_by_count", 0),
                "url": f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}",
                "openalex_id": p.get("id", ""),
            })

        if len(results) < per_page:
            break
        page += 1

    return papers[:max_results]


def fetch_by_ssrn_ids(ssrn_ids: list[str]) -> list[dict]:
    """Fetch metadata for specific SSRN papers via OpenAlex DOI lookup."""
    import requests

    papers = []
    for sid in ssrn_ids:
        doi = f"10.2139/ssrn.{sid}"
        r = requests.get(f"https://api.openalex.org/works/doi:{doi}", timeout=10)
        if r.status_code == 200:
            p = r.json()
            abstract = ""
            aidx = p.get("abstract_inverted_index") or {}
            if aidx:
                wp = [(pos, w) for w, positions in aidx.items() for pos in positions]
                wp.sort()
                abstract = " ".join(w for _, w in wp)

            authors = [a.get("author", {}).get("display_name", "")
                       for a in p.get("authorships", [])]

            papers.append({
                "ssrn_id": sid,
                "title": p.get("title", ""),
                "authors": [a for a in authors if a],
                "abstract": abstract,
                "doi": doi,
                "publication_date": p.get("publication_date", ""),
                "url": f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={sid}",
                "openalex_id": p.get("id", ""),
            })
        else:
            print(f"  SSRN {sid}: not found in OpenAlex (HTTP {r.status_code})")

    return papers


async def download_pdf_playwright(ssrn_id: str, output_dir: str) -> str | None:
    """Download PDF from SSRN using Playwright (handles Cloudflare)."""
    from playwright.async_api import async_playwright

    pdf_path = os.path.join(output_dir, f"ssrn_{ssrn_id}.pdf")
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 10000:
        return pdf_path

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            # Navigate to abstract page
            url = f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for Cloudflare
            try:
                await page.wait_for_function(
                    "document.title !== 'Just a moment...'", timeout=30000)
            except:
                print(f"    Cloudflare blocked PDF download for {ssrn_id}")
                await browser.close()
                return None

            await page.wait_for_timeout(2000)

            # Try downloading
            try:
                async with page.expect_download(timeout=15000) as dl_info:
                    await page.click('a[href*="Delivery.cfm"]', timeout=5000)
                download = await dl_info.value
                await download.save_as(pdf_path)
                size = os.path.getsize(pdf_path)
                if size > 10000:
                    await browser.close()
                    return pdf_path
                os.remove(pdf_path)
            except:
                pass

            await browser.close()
    except Exception as e:
        print(f"    PDF download error: {e}")

    return None


async def main():
    parser = argparse.ArgumentParser(description="SSRN DeFi/Crypto paper fetcher via OpenAlex")
    parser.add_argument("--query", type=str, default="decentralized finance", help="Search query")
    parser.add_argument("--ssrn-ids", type=str, default="", help="Comma-separated SSRN IDs (skip search)")
    parser.add_argument("--max-papers", type=int, default=20, help="Max papers to fetch")
    parser.add_argument("--years", type=str, default="2024|2025|2026", help="Publication years filter")
    parser.add_argument("--output-dir", type=str, default="/tmp/ssrn_papers", help="Output directory")
    parser.add_argument("--download-pdfs", action="store_true", help="Download PDFs via Playwright (slow)")
    parser.add_argument("--save-to-db", action="store_true", help="Save to MongoDB ssrn_papers collection")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Step 1: Discover papers
    if args.ssrn_ids:
        ids = [s.strip() for s in args.ssrn_ids.split(",") if s.strip()]
        print(f"Fetching {len(ids)} SSRN papers by ID...")
        papers = fetch_by_ssrn_ids(ids)
    else:
        print(f'Searching SSRN via OpenAlex: "{args.query}" (years: {args.years})')
        papers = search_openalex(args.query, args.max_papers, args.years)

    print(f"Found {len(papers)} papers\n")

    for i, p in enumerate(papers):
        print(f"[{i+1}] {p['title'][:65]}")
        print(f"    Authors: {', '.join(p['authors'][:3])}")
        print(f"    Date: {p['publication_date']}, SSRN: {p['ssrn_id']}, Cited: {p.get('cited_by_count', 0)}")
        if p.get('abstract'):
            print(f"    Abstract: {p['abstract'][:120]}...")

        # Step 2: Download PDF if requested
        if args.download_pdfs:
            print(f"    Downloading PDF...")
            pdf_path = await download_pdf_playwright(p['ssrn_id'], args.output_dir)
            p['pdf_path'] = pdf_path
            print(f"    PDF: {pdf_path or 'FAILED (Cloudflare)'}")

        print()

    # Step 3: Save to JSONL
    output_file = os.path.join(args.output_dir, "ssrn_papers.jsonl")
    with open(output_file, "w") as f:
        for p in papers:
            f.write(json.dumps(p, default=str) + "\n")
    print(f"Saved {len(papers)} papers to {output_file}")

    # Step 4: Save to DB
    if args.save_to_db and papers:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent / ".env")
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]

            saved = 0
            for p in papers:
                await db.ssrn_papers.update_one(
                    {"ssrn_id": p["ssrn_id"]},
                    {"$set": {
                        **p,
                        "source": "openalex",
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
                saved += 1
            print(f"Saved {saved} papers to MongoDB (ssrn_papers collection)")
        except Exception as e:
            print(f"DB save failed: {e}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"Papers: {len(papers)}")
    if args.download_pdfs:
        pdfs = sum(1 for p in papers if p.get("pdf_path"))
        print(f"PDFs downloaded: {pdfs}/{len(papers)}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
