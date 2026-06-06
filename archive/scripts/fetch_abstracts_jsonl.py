#!/usr/bin/env python3
"""
Fetch ICLR 2026 abstracts → JSONL (one line per paper, resumable, parallelized).

Output format (same style as iclr_2026_summaries.jsonl):
  {"openreview_id": "abc123", "title": "...", "abstract": "...", "status": "ok|empty|download_failed"}

Resumable: reads existing output JSONL to skip already-fetched papers.
Uses Playwright PDF download → anonymize → extract abstract.

Usage:
  python3 scripts/fetch_abstracts_jsonl.py --parallel 5
  python3 scripts/fetch_abstracts_jsonl.py --parallel 5 --dry-run
"""

import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from scripts.iclr_batch_summaries import anonymize_text, download_pdf_playwright

CSV_PATH = "/tmp/sampled_matches.csv"
SUMMARIES_PATH = ROOT.parent / "memory" / "iclr_2026_summaries.jsonl"
OUTPUT_PATH = ROOT.parent / "memory" / "iclr_2026_abstracts.jsonl"


def extract_abstract(full_text: str) -> str:
    normalized = re.sub(r'(?<=[A-Z])\s(?=[A-Z]{2,})', '', full_text)
    m = re.search(
        r'\bABSTRACT\b\s*(.*?)(?:\b(?:[1-9]\s*\.?\s*I\s*(?:NTRODUCTION|ntroduction)|INTRODUCTION|Introduction|Keywords)\b)',
        normalized, re.DOTALL
    )
    if m and len(m.group(1).strip()) > 50:
        return m.group(1).strip()[:3000]
    m = re.search(
        r'\bAbstract\b[.:\s]*(.*?)(?:\b[1-9]\s+[A-Z])',
        normalized, re.DOTALL
    )
    if m and len(m.group(1).strip()) > 50:
        return m.group(1).strip()[:3000]
    sample = full_text[:200]
    word_chars = sum(1 for c in sample if c.isalpha())
    if word_chars < len(sample) * 0.3:
        return ""
    return ""


def load_completed(output_path: str) -> set:
    done = set()
    if not os.path.exists(output_path):
        return done
    with open(output_path) as f:
        for line in f:
            try:
                done.add(json.loads(line)["openreview_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load paper IDs needed
    with open(CSV_PATH) as f:
        ids = set()
        for r in csv.DictReader(f):
            ids.add(r["id_1"])
            ids.add(r["id_2"])

    # Load titles from summaries JSONL
    titles = {}
    with open(SUMMARIES_PATH) as f:
        for line in f:
            doc = json.loads(line)
            oid = doc.get("openreview_id")
            if oid:
                titles[oid] = doc.get("title", "")

    # Resume
    completed = load_completed(str(OUTPUT_PATH))
    remaining = sorted(ids - completed)

    print(f"Total papers: {len(ids)}")
    print(f"Already done: {len(completed)}")
    print(f"Remaining:    {len(remaining)}")
    print(f"Parallel:     {args.parallel}")

    if args.dry_run:
        print("[DRY RUN]")
        return

    if not remaining:
        print("All done!")
        return

    sem = asyncio.Semaphore(args.parallel)
    lock = asyncio.Lock()
    stats = {"ok": 0, "empty": 0, "failed": 0, "total": 0, "t0": time.time()}
    out_f = open(OUTPUT_PATH, "a")

    async def process(oid: str):
        async with sem:
            text = await download_pdf_playwright(oid, max_retries=2)
            if text:
                anon = anonymize_text(text)
                abstract = extract_abstract(anon)
                status = "ok" if abstract else "empty"
            else:
                abstract = ""
                status = "download_failed"

            row = {
                "openreview_id": oid,
                "title": titles.get(oid, ""),
                "abstract": abstract,
                "abstract_chars": len(abstract),
                "status": status,
            }

            async with lock:
                out_f.write(json.dumps(row) + "\n")
                out_f.flush()

            if status == "ok":
                stats["ok"] += 1
            elif status == "empty":
                stats["empty"] += 1
            else:
                stats["failed"] += 1
            stats["total"] += 1

            if stats["total"] % 25 == 0:
                elapsed = time.time() - stats["t0"]
                rate = stats["total"] / elapsed * 3600
                left = (len(remaining) - stats["total"]) / max(rate / 3600, 0.001)
                print(
                    f"  [{stats['total']:>5}/{len(remaining)}]"
                    f"  ok={stats['ok']} empty={stats['empty']} fail={stats['failed']}"
                    f"  {rate:.0f}/hr  ETA={left/60:.0f}m"
                )

    # Process in batches for clean Playwright context management
    BATCH = 100
    for i in range(0, len(remaining), BATCH):
        batch = remaining[i:i + BATCH]
        await asyncio.gather(*[process(oid) for oid in batch])

    out_f.close()

    # Cleanup Playwright
    from scripts.iclr_batch_summaries import _browser, _pw
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()

    elapsed = time.time() - stats["t0"]
    print(f"\nDone in {elapsed/60:.0f}m — ok={stats['ok']} empty={stats['empty']} failed={stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
