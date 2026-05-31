#!/usr/bin/env python3
"""Generate Opus 4.8 thinking summaries for the summarizer-rating benchmark papers.

Uses the same prompt and format as production (IMPACT_ASSESSMENT_PROMPT).
Stores results in papers.summaries['anthropic:claude-opus-4-8:thinking'].
Resumable — skips papers that already have the summary.

Usage:
    python3 /app/tools/run_opus48_summaries.py --dry-run
    python3 /app/tools/run_opus48_summaries.py --parallel 3
"""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import litellm
litellm.suppress_debug_info = True

from core.config import db, logger
from services.llm import IMPACT_ASSESSMENT_PROMPT

SUMMARY_KEY = "anthropic:claude-opus-4-8:thinking"
MODEL = "anthropic/claude-opus-4-8"
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MAX_RETRIES = 5
RETRY_DELAYS = [2, 5, 10, 20, 30]


async def generate_summary(title, content, sem):
    async with sem:
        prompt = IMPACT_ASSESSMENT_PROMPT["user_prompt"].format(title=title, content=content)
        t0 = time.time()
        for attempt in range(MAX_RETRIES):
            try:
                resp = await asyncio.to_thread(litellm.completion,
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": IMPACT_ASSESSMENT_PROMPT["system_prompt"]},
                        {"role": "user", "content": prompt},
                    ],
                    api_key=API_KEY,
                    timeout=180,
                )
                text = resp.choices[0].message.content if resp.choices else ""
                if text and text.strip():
                    tokens_in = resp.usage.prompt_tokens if resp.usage else 0
                    tokens_out = resp.usage.completion_tokens if resp.usage else 0
                    return {
                        "text": text.strip(),
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "elapsed_s": round(time.time() - t0, 1),
                        "error": None,
                    }
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                else:
                    return {"text": None, "error": str(e)[:300], "elapsed_s": round(time.time() - t0, 1)}
        return {"text": None, "error": "All attempts returned empty", "elapsed_s": round(time.time() - t0, 1)}


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load target papers (same set as summarizer-rating benchmark)
    papers = []
    async for doc in db.papers.find(
        {"summaries.openai:gpt-5_5": {"$exists": True, "$ne": ""},
         f"summaries.{SUMMARY_KEY}": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1},
    ):
        papers.append(doc)

    total_with_summary = await db.papers.count_documents({f"summaries.{SUMMARY_KEY}": {"$exists": True, "$ne": ""}})
    print(f"Opus 4.8 Summarization")
    print(f"  Target papers: 695, Already done: {total_with_summary}, Remaining: {len(papers)}")
    print(f"  Model: {MODEL}, Parallel: {args.parallel}")

    if args.dry_run:
        for p in papers[:3]:
            print(f"  {p['title'][:60]}")
        return

    if not papers:
        print("  All done!")
        return

    sem = asyncio.Semaphore(args.parallel)
    stats = {"ok": 0, "failed": 0, "total": 0, "tokens_in": 0, "tokens_out": 0, "start": time.time()}

    async def process_one(paper):
        content = f"Abstract: {paper['abstract']}\n\nFull Paper Text:\n{paper['full_text']}"
        result = await generate_summary(paper["title"], content, sem)

        if result["text"]:
            # Store summary in DB
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {f"summaries.{SUMMARY_KEY}": result["text"]}},
            )
            stats["ok"] += 1
            stats["tokens_in"] += result.get("tokens_in", 0)
            stats["tokens_out"] += result.get("tokens_out", 0)
        else:
            stats["failed"] += 1

        stats["total"] += 1
        if stats["total"] % 5 == 0:
            elapsed = time.time() - stats["start"]
            rate = stats["total"] / elapsed * 3600 if elapsed > 0 else 0
            eta = (len(papers) - stats["total"]) / (rate / 3600) if rate > 0 else 0
            print(f"  [{stats['total']:>4}/{len(papers)}] ok={stats['ok']} fail={stats['failed']} "
                  f"rate={rate:.0f}/hr ETA={eta/60:.0f}m tokens={stats['tokens_in']+stats['tokens_out']:,}")

    batch_size = args.parallel * 2
    for i in range(0, len(papers), batch_size):
        batch = papers[i:i + batch_size]
        await asyncio.gather(*[process_one(p) for p in batch])
        await asyncio.sleep(0.5)

    elapsed = time.time() - stats["start"]
    print(f"\nDone in {elapsed/60:.1f}m: ok={stats['ok']}, failed={stats['failed']}, "
          f"tokens={stats['tokens_in']+stats['tokens_out']:,}")


if __name__ == "__main__":
    asyncio.run(main())
