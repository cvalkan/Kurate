#!/usr/bin/env python3
"""
Fetch ICLR 2026 abstracts via Playwright forum scraping → JSONL.

Scrapes the OpenReview forum page HTML directly (structured, reliable)
instead of downloading PDFs and regex-parsing.

Resumable: skips openreview_ids already present in the output JSONL.

Usage:
  python3 scripts/fetch_abstracts_forum.py --parallel 20
  python3 scripts/fetch_abstracts_forum.py --parallel 20 --limit 100
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright

SUMMARIES_PATH = ROOT.parent / "memory" / "iclr_2026_summaries.jsonl"
OUTPUT_PATH = ROOT.parent / "memory" / "iclr_2026_abstracts.jsonl"


def load_paper_ids() -> dict:
    """Return {openreview_id: title} for all papers with summaries."""
    papers = {}
    with open(SUMMARIES_PATH) as f:
        for line in f:
            doc = json.loads(line)
            oid = doc.get("openreview_id")
            if oid and doc.get("summary"):
                papers[oid] = doc.get("title", "")
    return papers


def load_completed() -> set:
    done = set()
    if not OUTPUT_PATH.exists():
        return done
    with open(OUTPUT_PATH) as f:
        for line in f:
            try:
                done.add(json.loads(line)["openreview_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


async def scrape_abstract(browser, oid: str, title: str, sem, out_f, lock, stats):
    async with sem:
        t0 = time.time()
        page = await browser.new_page()
        abstract = ""
        status = "empty"
        try:
            resp = await page.goto(
                f"https://openreview.net/forum?id={oid}",
                wait_until="networkidle",
                timeout=25000,
            )
            if resp.status != 200:
                status = f"http_{resp.status}"
            else:
                await page.wait_for_timeout(1500)
                elements = await page.query_selector_all(".note-content-value")
                for el in elements:
                    try:
                        parent = await el.evaluate_handle("el => el.parentElement")
                        label_el = await parent.query_selector(
                            "strong.note-content-field"
                        )
                        if label_el:
                            label = await label_el.inner_text()
                            if "Abstract" in label:
                                abstract = (await el.inner_text()).strip()
                                status = "ok"
                                break
                    except Exception:
                        continue
        except Exception as e:
            err = str(e)[:100]
            status = "timeout" if "Timeout" in err else "error"
        finally:
            await page.close()

        row = {
            "openreview_id": oid,
            "title": title,
            "abstract": abstract,
            "abstract_chars": len(abstract),
            "status": status,
        }
        async with lock:
            out_f.write(json.dumps(row) + "\n")
            out_f.flush()

        if status == "ok":
            stats["ok"] += 1
        else:
            stats["fail"] += 1
        stats["total"] += 1

        if stats["total"] % 20 == 0:
            elapsed = time.time() - stats["t0"]
            rate = stats["total"] / elapsed * 3600
            remaining = stats["target"] - stats["total"]
            eta = remaining / max(rate / 3600, 0.001)
            print(
                f"  [{stats['total']:>5}/{stats['target']}]"
                f"  ok={stats['ok']} fail={stats['fail']}"
                f"  {rate:.0f}/hr  ETA={eta/60:.0f}m"
            )


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    papers = load_paper_ids()
    completed = load_completed()
    remaining = [(oid, t) for oid, t in papers.items() if oid not in completed]

    if args.limit > 0:
        remaining = remaining[: args.limit]

    print(f"Total papers:  {len(papers)}")
    print(f"Already done:  {len(completed)}")
    print(f"To fetch:      {len(remaining)}")
    print(f"Parallelism:   {args.parallel}")

    if not remaining:
        print("All done!")
        return

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    sem = asyncio.Semaphore(args.parallel)
    lock = asyncio.Lock()
    out_f = open(OUTPUT_PATH, "a")
    stats = {"ok": 0, "fail": 0, "total": 0, "target": len(remaining), "t0": time.time()}

    # Process in batches to manage browser memory
    BATCH = 100
    for i in range(0, len(remaining), BATCH):
        batch = remaining[i : i + BATCH]
        await asyncio.gather(
            *[scrape_abstract(browser, oid, title, sem, out_f, lock, stats) for oid, title in batch]
        )

    out_f.close()
    elapsed = time.time() - stats["t0"]
    print(f"\nDone in {elapsed/60:.1f}m — ok={stats['ok']} fail={stats['fail']}")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
