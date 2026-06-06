#!/usr/bin/env python3
"""
Retry failed/empty abstracts from iclr_2026_abstracts.jsonl.
- download_failed: retry the PDF download
- empty: retry with improved extraction (broader end-boundary matching)

Rewrites the JSONL in place, replacing failed entries with retried results.

Usage:
  python3 scripts/retry_abstracts.py --parallel 5
  python3 scripts/retry_abstracts.py --parallel 5 --dry-run
"""

import asyncio
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

ABSTRACTS_JSONL = ROOT.parent / "memory" / "iclr_2026_abstracts.jsonl"


def extract_abstract_v2(full_text: str) -> str:
    """Improved abstract extraction — more tolerant of PDF artifacts."""
    # Normalize spaces within words (e.g. "I NTRODUCTION" → "INTRODUCTION")
    normalized = re.sub(r'(?<=[A-Z])\s(?=[A-Z]{2,})', '', full_text)

    # Find ABSTRACT start
    abs_match = re.search(r'\bABSTRACT\b', normalized, re.IGNORECASE)
    if not abs_match:
        return ""

    after_abstract = normalized[abs_match.end():]

    # Try multiple end boundaries, take the first that gives a reasonable chunk
    end_patterns = [
        # Standard: "1 INTRODUCTION" or "1. Introduction"
        r'\b[1-9]\s*\.?\s*(?:INTRODUCTION|Introduction)',
        # Typos: NTRODUCION, INTRODUCION, etc.
        r'\b[1-9]\s*\.?\s*I\s*N\s*T\s*R\s*O\s*D',
        # Any numbered section header: "1 SOME TITLE" or "1. Some Title"
        r'\n\s*[1-9]\s*\.?\s+[A-Z][A-Za-z]',
        # Keywords section
        r'\b(?:Keywords|KEYWORDS)\b',
        # Double newline followed by section-like content
        r'\n\s*\n\s*(?:1\b|I\b)',
    ]

    for pattern in end_patterns:
        m = re.search(pattern, after_abstract)
        if m:
            candidate = after_abstract[:m.start()].strip()
            if len(candidate) > 50:
                return candidate[:3000]

    # Last resort: take up to 2000 chars after ABSTRACT if text looks real
    candidate = after_abstract[:2000].strip()
    word_chars = sum(1 for c in candidate[:200] if c.isalpha())
    if word_chars > 80:
        # Trim at last sentence boundary
        last_period = candidate.rfind('.')
        if last_period > 200:
            return candidate[:last_period + 1]
        return candidate

    return ""


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=["empty", "failed", "both"], default="both")
    args = parser.parse_args()

    # Load all entries
    entries = {}
    with open(ABSTRACTS_JSONL) as f:
        for line in f:
            doc = json.loads(line)
            entries[doc["openreview_id"]] = doc

    retry_ids = []
    for oid, doc in entries.items():
        if args.only == "both" and doc["status"] in ("empty", "download_failed"):
            retry_ids.append(oid)
        elif args.only == "empty" and doc["status"] == "empty":
            retry_ids.append(oid)
        elif args.only == "failed" and doc["status"] == "download_failed":
            retry_ids.append(oid)

    n_empty = sum(1 for oid in retry_ids if entries[oid]["status"] == "empty")
    n_failed = sum(1 for oid in retry_ids if entries[oid]["status"] == "download_failed")
    print(f"Total entries: {len(entries)}")
    print(f"To retry: {len(retry_ids)} (empty={n_empty}, download_failed={n_failed})")
    print(f"Parallel: {args.parallel}")

    if args.dry_run or not retry_ids:
        return

    sem = asyncio.Semaphore(args.parallel)
    stats = {"fixed": 0, "still_empty": 0, "still_failed": 0, "total": 0, "t0": time.time()}

    async def retry_one(oid: str):
        async with sem:
            text = await download_pdf_playwright(oid, max_retries=3)
            if text:
                anon = anonymize_text(text)
                abstract = extract_abstract_v2(anon)
                if abstract:
                    entries[oid] = {**entries[oid], "abstract": abstract, "abstract_chars": len(abstract), "status": "ok"}
                    stats["fixed"] += 1
                else:
                    entries[oid] = {**entries[oid], "abstract": "", "abstract_chars": 0, "status": "empty"}
                    stats["still_empty"] += 1
            else:
                entries[oid] = {**entries[oid], "abstract": "", "abstract_chars": 0, "status": "download_failed"}
                stats["still_failed"] += 1

            stats["total"] += 1
            if stats["total"] % 10 == 0:
                elapsed = time.time() - stats["t0"]
                print(f"  [{stats['total']}/{len(retry_ids)}] fixed={stats['fixed']} still_empty={stats['still_empty']} still_failed={stats['still_failed']} ({elapsed:.0f}s)")

    BATCH = 50
    for i in range(0, len(retry_ids), BATCH):
        batch = retry_ids[i:i + BATCH]
        await asyncio.gather(*[retry_one(oid) for oid in batch])

    # Cleanup Playwright
    from scripts.iclr_batch_summaries import _browser, _pw
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()

    # Rewrite JSONL
    with open(ABSTRACTS_JSONL, "w") as f:
        for doc in entries.values():
            f.write(json.dumps(doc) + "\n")

    ok = sum(1 for d in entries.values() if d["status"] == "ok")
    print(f"\nDone. fixed={stats['fixed']}, still_empty={stats['still_empty']}, still_failed={stats['still_failed']}")
    print(f"Final: {ok}/{len(entries)} with abstracts ({ok/len(entries)*100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
