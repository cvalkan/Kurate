#!/usr/bin/env python3
"""SSRN paper fetcher — downloads DeFi/Crypto preprints via Playwright.

Standalone script. Searches SSRN by keyword, extracts metadata from
abstract pages, and downloads PDFs (login-free papers only).

Usage:
    python3 scripts/ssrn_fetcher.py --query "decentralized finance" --max-papers 20
    python3 scripts/ssrn_fetcher.py --query "cryptocurrency" --max-papers 10 --output-dir /tmp/ssrn
    python3 scripts/ssrn_fetcher.py --ssrn-ids 6190060,6120207,4942313
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

# Add backend to path for DB access
sys.path.insert(0, str(Path(__file__).parent.parent))


async def search_ssrn(page, query: str, max_results: int = 20) -> list[dict]:
    """Search SSRN and return list of paper metadata from search results."""
    papers = []
    page_num = 0
    per_page = 50  # SSRN shows ~25-50 results per page

    while len(papers) < max_results:
        url = f"https://papers.ssrn.com/sol3/JELJOUR_Results.cfm?form_name=journalBrowse&journal_id=&Network=no&lnsrc=&SortOrder=ab_approval_date&nxtres={page_num * per_page}&npage={page_num + 1}&filtertype=keywordsearch&txtKey_Words={query.replace(' ', '+')}"
        print(f"  Fetching search page {page_num + 1}...")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for Cloudflare challenge if present
            await page.wait_for_timeout(3000)

            # Check if Cloudflare challenge page
            content = await page.content()
            if "challenge-platform" in content or "Just a moment" in content:
                print("  Waiting for Cloudflare challenge...")
                await page.wait_for_timeout(8000)
                content = await page.content()

            # Extract paper links and metadata from search results
            results = await page.evaluate("""() => {
                const papers = [];
                // SSRN search results have links to abstract pages
                const links = document.querySelectorAll('a[href*="abstract_id="]');
                const seen = new Set();
                for (const link of links) {
                    const href = link.href;
                    const match = href.match(/abstract_id=(\d+)/);
                    if (match && !seen.has(match[1])) {
                        seen.add(match[1]);
                        papers.push({
                            ssrn_id: match[1],
                            title: link.textContent.trim(),
                            url: href,
                        });
                    }
                }
                return papers;
            }""")

            if not results:
                # Try alternate search URL format
                url2 = f"https://www.ssrn.com/search?searchtype=PAPERS&text={query.replace(' ', '%20')}&availableForm=1&orderBy=submitted&orderDir=desc"
                await page.goto(url2, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)

                results = await page.evaluate("""() => {
                    const papers = [];
                    const seen = new Set();
                    // New SSRN search UI
                    document.querySelectorAll('a[href*="/abstract="], a[href*="abstract_id="]').forEach(link => {
                        let match = link.href.match(/abstract[_=](\d+)/);
                        if (match && !seen.has(match[1]) && link.textContent.trim().length > 10) {
                            seen.add(match[1]);
                            papers.push({
                                ssrn_id: match[1],
                                title: link.textContent.trim(),
                                url: link.href,
                            });
                        }
                    });
                    return papers;
                }""")

            if not results:
                print(f"  No results found on page {page_num + 1}")
                break

            papers.extend(results)
            print(f"  Found {len(results)} papers on page {page_num + 1} (total: {len(papers)})")

            if len(results) < 10:
                break  # Last page
            page_num += 1
            await page.wait_for_timeout(2000)  # Rate limit

        except Exception as e:
            print(f"  Search error: {e}")
            break

    return papers[:max_results]


async def fetch_paper_metadata(page, ssrn_id: str) -> dict:
    """Navigate to an SSRN abstract page and extract full metadata."""
    url = f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"
    print(f"  Fetching metadata for SSRN {ssrn_id}...")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Handle Cloudflare
        content = await page.content()
        if "challenge-platform" in content or "Just a moment" in content:
            print("    Waiting for Cloudflare...")
            await page.wait_for_timeout(10000)

        metadata = await page.evaluate("""() => {
            const getText = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.textContent.trim() : '';
            };
            const getAll = (sel) => [...document.querySelectorAll(sel)].map(el => el.textContent.trim());

            // Title
            let title = getText('h1') || getText('.title');
            if (!title) {
                const h1s = document.querySelectorAll('h1, .abstract-title');
                for (const h of h1s) {
                    if (h.textContent.trim().length > 10) { title = h.textContent.trim(); break; }
                }
            }

            // Authors
            let authors = [];
            document.querySelectorAll('.authors-list a, .author-name a, a[href*="per_id="]').forEach(a => {
                const name = a.textContent.trim();
                if (name && name.length > 2 && !name.includes('SSRN')) authors.push(name);
            });

            // Abstract
            let abstract = '';
            const absDivs = document.querySelectorAll('.abstract-text, #abstract-body, div[class*="abstract"]');
            for (const div of absDivs) {
                const text = div.textContent.trim();
                if (text.length > abstract.length) abstract = text;
            }
            // Fallback: meta tag
            if (!abstract) {
                const meta = document.querySelector('meta[name="description"]');
                if (meta) abstract = meta.content;
            }

            // Date
            let date = '';
            const dateEl = document.querySelector('.note-list .note-type');
            if (dateEl) date = dateEl.textContent.trim();
            // Fallback: look for date patterns
            if (!date) {
                const body = document.body.innerText;
                const match = body.match(/(?:Posted|Last revised|Date Written):\s*(\w+ \d+,?\s*\d{4})/i);
                if (match) date = match[1];
            }

            // Keywords
            let keywords = [];
            document.querySelectorAll('.keyword-group a, a[href*="keyword"]').forEach(a => {
                const kw = a.textContent.trim();
                if (kw && kw.length > 1) keywords.push(kw);
            });

            // Download count
            let downloads = 0;
            const body = document.body.innerText;
            const dlMatch = body.match(/([\d,]+)\s*Downloads/i);
            if (dlMatch) downloads = parseInt(dlMatch[1].replace(',', ''));

            // Check if PDF is available (download button exists)
            const hasDownload = !!document.querySelector('a[href*="Delivery.cfm"], button[class*="download"], .download-button');

            return { title, authors, abstract, date, keywords, downloads, hasDownload };
        }""")

        metadata["ssrn_id"] = ssrn_id
        metadata["url"] = url
        return metadata

    except Exception as e:
        print(f"    Error: {e}")
        return {"ssrn_id": ssrn_id, "url": url, "error": str(e)}


async def download_pdf(page, ssrn_id: str, output_dir: str) -> str | None:
    """Attempt to download the PDF for a paper. Returns filepath or None."""
    pdf_path = os.path.join(output_dir, f"ssrn_{ssrn_id}.pdf")
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 10000:
        print(f"    PDF already exists: {pdf_path}")
        return pdf_path

    # Navigate to abstract page first (sets cookies)
    url = f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Handle Cloudflare
        content = await page.content()
        if "challenge-platform" in content or "Just a moment" in content:
            print("    Waiting for Cloudflare...")
            await page.wait_for_timeout(10000)

        # Look for download button/link
        download_link = await page.evaluate("""() => {
            // Try various download selectors
            const selectors = [
                'a[href*="Delivery.cfm"]',
                'a.download-button',
                'button.download-button',
                'a[data-abstract-id]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) return el.href || el.getAttribute('data-href') || null;
            }
            return null;
        }""")

        if not download_link:
            # Try constructing the URL directly
            download_link = f"https://papers.ssrn.com/sol3/Delivery.cfm/{ssrn_id}.pdf?abstractid={ssrn_id}"

        print(f"    Downloading PDF...")

        # Use Playwright's download handling
        async with page.expect_download(timeout=30000) as download_info:
            await page.goto(download_link, timeout=30000)

        download = await download_info.value
        await download.save_as(pdf_path)

        size = os.path.getsize(pdf_path)
        if size > 10000:
            print(f"    Downloaded: {pdf_path} ({size:,} bytes)")
            return pdf_path
        else:
            print(f"    Download too small ({size} bytes) — likely blocked")
            os.remove(pdf_path)
            return None

    except Exception as e:
        # Fallback: try clicking the download button on the page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            async with page.expect_download(timeout=30000) as download_info:
                await page.click('a[href*="Delivery.cfm"], .download-button', timeout=5000)

            download = await download_info.value
            await download.save_as(pdf_path)
            size = os.path.getsize(pdf_path)
            if size > 10000:
                print(f"    Downloaded via click: {pdf_path} ({size:,} bytes)")
                return pdf_path
        except Exception as e2:
            print(f"    PDF download failed: {e2}")

        return None


async def main():
    parser = argparse.ArgumentParser(description="SSRN paper fetcher for DeFi/Crypto preprints")
    parser.add_argument("--query", type=str, default="decentralized finance", help="Search query")
    parser.add_argument("--ssrn-ids", type=str, default="", help="Comma-separated SSRN IDs (skip search)")
    parser.add_argument("--max-papers", type=int, default=20, help="Max papers to fetch")
    parser.add_argument("--output-dir", type=str, default="/tmp/ssrn_papers", help="Output directory")
    parser.add_argument("--download-pdfs", action="store_true", help="Download PDFs (slower)")
    parser.add_argument("--save-to-db", action="store_true", help="Save metadata to MongoDB")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Step 1: Get paper IDs (from search or command line)
        if args.ssrn_ids:
            paper_ids = [{"ssrn_id": sid.strip(), "title": ""} for sid in args.ssrn_ids.split(",") if sid.strip()]
            print(f"Using {len(paper_ids)} provided SSRN IDs")
        else:
            print(f'Searching SSRN for: "{args.query}"')
            paper_ids = await search_ssrn(page, args.query, args.max_papers)
            print(f"Found {len(paper_ids)} papers")

        if not paper_ids:
            print("No papers found. Try a different query.")
            await browser.close()
            return

        # Step 2: Fetch metadata for each paper
        all_papers = []
        for i, p in enumerate(paper_ids):
            ssrn_id = p["ssrn_id"]
            print(f"\n[{i+1}/{len(paper_ids)}] SSRN {ssrn_id}")

            metadata = await fetch_paper_metadata(page, ssrn_id)

            if metadata.get("title"):
                print(f"  Title: {metadata['title'][:60]}")
                print(f"  Authors: {', '.join(metadata.get('authors', [])[:3])}")
                print(f"  Downloads: {metadata.get('downloads', 0)}")

                # Step 3: Download PDF if requested
                if args.download_pdfs:
                    pdf_path = await download_pdf(page, ssrn_id, args.output_dir)
                    metadata["pdf_path"] = pdf_path

                all_papers.append(metadata)
            else:
                print(f"  Failed to extract metadata (Cloudflare block?)")

            await page.wait_for_timeout(2000)  # Rate limit between papers

        await browser.close()

        # Step 4: Save results
        output_file = os.path.join(args.output_dir, "ssrn_papers.jsonl")
        with open(output_file, "w") as f:
            for paper in all_papers:
                f.write(json.dumps(paper, default=str) + "\n")
        print(f"\nSaved {len(all_papers)} papers to {output_file}")

        # Step 5: Save to DB if requested
        if args.save_to_db and all_papers:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                from dotenv import load_dotenv
                load_dotenv(Path(__file__).parent.parent / ".env")
                client = AsyncIOMotorClient(os.environ["MONGO_URL"])
                db = client[os.environ["DB_NAME"]]

                saved = 0
                for paper in all_papers:
                    if not paper.get("title"):
                        continue
                    await db.ssrn_papers.update_one(
                        {"ssrn_id": paper["ssrn_id"]},
                        {"$set": {
                            "ssrn_id": paper["ssrn_id"],
                            "title": paper["title"],
                            "authors": paper.get("authors", []),
                            "abstract": paper.get("abstract", ""),
                            "date": paper.get("date", ""),
                            "keywords": paper.get("keywords", []),
                            "downloads": paper.get("downloads", 0),
                            "url": paper["url"],
                            "pdf_path": paper.get("pdf_path"),
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
        print(f"Papers found: {len(all_papers)}")
        if args.download_pdfs:
            pdfs = sum(1 for p in all_papers if p.get("pdf_path"))
            print(f"PDFs downloaded: {pdfs}")
        print(f"Output: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
