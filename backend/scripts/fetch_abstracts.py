#!/usr/bin/env python3
"""Fetch and cache anonymized abstracts for all ICLR 2026 validation papers."""

import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from scripts.iclr_batch_summaries import anonymize_text, download_pdf_playwright

CSV_PATH = "/tmp/sampled_matches.csv"
ABSTRACTS_CACHE = ROOT.parent / "memory" / "iclr_2026_abstracts.json"


def extract_abstract(full_text: str) -> str:
    m = re.search(
        r'\bABSTRACT\b\s*(.*?)(?:\b(?:1\s+INTRODUCTION|INTRODUCTION|1\.\s+INTRODUCTION|Keywords)\b)',
        full_text, re.IGNORECASE | re.DOTALL
    )
    if m and len(m.group(1).strip()) > 50:
        return m.group(1).strip()[:3000]
    m = re.search(
        r'\bAbstract\b[.:\s]*(.*?)(?:\b[1-9]\s+[A-Z]|\bIntroduction\b)',
        full_text, re.DOTALL
    )
    if m and len(m.group(1).strip()) > 50:
        return m.group(1).strip()[:3000]
    sample = full_text[:200]
    word_chars = sum(1 for c in sample if c.isalpha())
    if word_chars < len(sample) * 0.3:
        return ""
    return ""


async def main():
    # Load all needed IDs from CSV
    with open(CSV_PATH) as f:
        ids = set()
        for r in csv.DictReader(f):
            ids.add(r["id_1"])
            ids.add(r["id_2"])
    print(f"Total unique papers: {len(ids)}")

    # Load cache
    cache = {}
    if ABSTRACTS_CACHE.exists():
        with open(ABSTRACTS_CACHE) as f:
            cache = json.load(f)
        has = sum(1 for v in cache.values() if v)
        print(f"Cached: {len(cache)} ({has} with content)")

    missing = sorted(ids - set(cache.keys()))
    if not missing:
        has = sum(1 for v in cache.values() if v)
        print(f"All {len(ids)} done ({has} with abstracts)")
        return
    print(f"Missing: {len(missing)}")

    PARALLEL = 3
    sem = asyncio.Semaphore(PARALLEL)
    fetched, failed = 0, 0
    t0 = time.time()

    async def fetch_one(oid: str):
        nonlocal fetched, failed
        async with sem:
            full_text = await download_pdf_playwright(oid, max_retries=2)
            if full_text:
                anon = anonymize_text(full_text)
                abstract = extract_abstract(anon)
                cache[oid] = abstract
                if abstract:
                    fetched += 1
                else:
                    failed += 1
            else:
                cache[oid] = ""
                failed += 1

    # Process in batches, save cache periodically
    BATCH = 50
    for i in range(0, len(missing), BATCH):
        batch = missing[i:i + BATCH]
        await asyncio.gather(*[fetch_one(oid) for oid in batch])
        with open(ABSTRACTS_CACHE, "w") as f:
            json.dump(cache, f)
        elapsed = time.time() - t0
        done = fetched + failed
        rate = done / elapsed * 3600 if elapsed > 0 else 0
        remaining_time = (len(missing) - done) / (rate / 3600) if rate > 0 else 0
        print(f"  [{done}/{len(missing)}] ok={fetched} empty={failed} rate={rate:.0f}/hr ETA={remaining_time/60:.0f}m")

    # Cleanup
    from scripts.iclr_batch_summaries import _browser, _pw
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()

    has = sum(1 for v in cache.values() if v)
    print(f"\nDone: {has} abstracts, {failed} empty/failed, total cached={len(cache)}")


if __name__ == "__main__":
    asyncio.run(main())
