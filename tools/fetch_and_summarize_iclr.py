#!/usr/bin/env python3
"""Fetch abstracts + generate AI summaries for ICLR papers from OpenReview.

Robust, resumable pipeline that:
1. Fetches abstracts from OpenReview API (with rate limiting)
2. Downloads PDFs and extracts full text
3. Generates AI Impact Assessments using Claude Opus 4.6 (same prompt as production)
4. Outputs results to per-dataset JSONL files (same format as iclr_2026_summaries.jsonl)
5. Skips papers that already have summaries in the DB or JSONL

Usage:
    python3 /app/tools/fetch_and_summarize_iclr.py --dry-run
    python3 /app/tools/fetch_and_summarize_iclr.py --parallel 10
    python3 /app/tools/fetch_and_summarize_iclr.py --only 2025_LLMs --parallel 10
"""

import asyncio
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx
import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

from core.config import db, logger, EMERGENT_LLM_KEY
from emergentintegrations.llm.utils import get_integration_proxy_url
from services.llm import IMPACT_ASSESSMENT_PROMPT, download_and_extract_pdf

PROXY_URL = get_integration_proxy_url() + "/llm"

# ── Configuration ──
DATASETS = {
    "2025_LLMs": {
        "csv": "/tmp/2025_LLMs.csv",
        "output": "/app/memory/iclr_2025_LLMs_summaries.jsonl",
        "dataset_id": "iclr-2025-llm",
    },
    "2025_optimization": {
        "csv": "/tmp/2025_optimization.csv",
        "output": "/app/memory/iclr_2025_optimization_summaries.jsonl",
        "dataset_id": "iclr-2025-optimization",
    },
    "2026_LLMs": {
        "csv": "/tmp/2026_LLMs.csv",
        "output": "/app/memory/iclr_2026_LLMs_summaries.jsonl",
        "dataset_id": "iclr-2026-llm",
    },
    "2026_optimization": {
        "csv": "/tmp/2026_optimization.csv",
        "output": "/app/memory/iclr_2026_optimization_summaries.jsonl",
        "dataset_id": "iclr-2026-optimization",
    },
}

OPENREVIEW_API = "https://api2.openreview.net"


# ── Step 1: Collect unique paper IDs per dataset ──

def load_paper_ids(csv_path):
    rows = list(csv.reader(open(csv_path)))[1:]
    ids = set()
    for r in rows:
        ids.add(r[0]); ids.add(r[1])
    return sorted(ids)


# ── Step 2: Fetch abstract from OpenReview ──

async def fetch_abstract(client, openreview_id):
    """Fetch title + abstract from OpenReview API."""
    url = f"{OPENREVIEW_API}/notes?id={openreview_id}"
    try:
        resp = await client.get(url, timeout=15)
        if resp.status_code == 429:
            await asyncio.sleep(5)
            resp = await client.get(url, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        notes = data.get("notes", [])
        if not notes:
            return None
        note = notes[0]
        content = note.get("content", {})
        title = content.get("title", {}).get("value", "") if isinstance(content.get("title"), dict) else content.get("title", "")
        abstract = content.get("abstract", {}).get("value", "") if isinstance(content.get("abstract"), dict) else content.get("abstract", "")
        pdf_path = content.get("pdf", {}).get("value", "") if isinstance(content.get("pdf"), dict) else content.get("pdf", "")
        pdf_url = f"https://openreview.net{pdf_path}" if pdf_path and pdf_path.startswith("/") else ""
        return {"title": title, "abstract": abstract, "pdf_url": pdf_url}
    except Exception as e:
        return None


# ── Step 3: Generate summary using Claude Opus 4.6 ──

async def generate_summary(paper_title, content_text, sem):
    """Generate impact assessment using same prompt as production."""
    async with sem:
        prompt = IMPACT_ASSESSMENT_PROMPT["user_prompt"].format(
            title=paper_title,
            content=content_text,
        )
        params = {
            "model": "claude-opus-4-6",
            "messages": [
                {"role": "system", "content": IMPACT_ASSESSMENT_PROMPT["system_prompt"]},
                {"role": "user", "content": prompt},
            ],
            "api_key": EMERGENT_LLM_KEY,
            "api_base": PROXY_URL,
            "custom_llm_provider": "openai",
        }
        t0 = time.time()
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: litellm.completion(**params))
            text = resp.choices[0].message.content.strip() if resp.choices else ""
            tokens_in = resp.usage.prompt_tokens if resp.usage else 0
            tokens_out = resp.usage.completion_tokens if resp.usage else 0
            elapsed = time.time() - t0

            # Extract AI rating JSON from end of summary
            ai_rating = None
            match = re.search(r'\{[^{}]*"score"[^{}]*\}', text[-300:])
            if match:
                try:
                    ai_rating = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

            return {
                "summary": text,
                "ai_rating": ai_rating,
                "tokens": {"input": tokens_in, "output": tokens_out},
                "elapsed_s": round(elapsed, 1),
                "error": None,
            }
        except Exception as e:
            return {
                "summary": None,
                "ai_rating": None,
                "tokens": {},
                "elapsed_s": round(time.time() - t0, 1),
                "error": str(e)[:300],
            }


# ── Step 4: Load existing data to skip ──

async def load_existing_summaries(dataset_id, output_path):
    """Load already-completed openreview_ids from DB + JSONL."""
    done = set()

    # From DB
    async for doc in db.validation_papers.find(
        {"dataset_id": {"$in": [dataset_id, "iclr-2026-validation", "iclr-llm", "iclr-optimization"]},
         "ai_impact_summary_thinking": {"$exists": True, "$ne": ""}},
        {"_id": 0, "openreview_id": 1},
    ):
        if doc.get("openreview_id"):
            done.add(doc["openreview_id"])

    # From JSONL (in case DB insert failed but JSONL was written)
    if os.path.exists(output_path):
        with open(output_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok" and r.get("summary"):
                        done.add(r["openreview_id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    # Also check the main 2026 summaries JSONL
    main_jsonl = "/app/memory/iclr_2026_summaries.jsonl"
    if os.path.exists(main_jsonl):
        with open(main_jsonl) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok" and r.get("summary"):
                        done.add(r["openreview_id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    return done


# ── Main pipeline ──

async def process_dataset(name, config, parallel, dry_run):
    csv_path = config["csv"]
    output_path = config["output"]
    dataset_id = config["dataset_id"]

    print(f"\n{'='*60}")
    print(f"Dataset: {name} ({dataset_id})")
    print(f"{'='*60}")

    # 1. Load paper IDs
    paper_ids = load_paper_ids(csv_path)
    print(f"  Papers in CSV: {len(paper_ids)}")

    # 2. Load already done
    done = await load_existing_summaries(dataset_id, output_path)
    remaining = [pid for pid in paper_ids if pid not in done]
    print(f"  Already done: {len(done)}")
    print(f"  Remaining: {len(remaining)}")

    if dry_run or not remaining:
        return {"total": len(paper_ids), "done": len(done), "remaining": len(remaining)}

    # 3. Fetch abstracts + PDFs + generate summaries
    sem = asyncio.Semaphore(parallel)
    stats = {"ok": 0, "failed": 0, "total": 0, "no_abstract": 0,
             "pdf_ok": 0, "pdf_fail": 0, "tokens_in": 0, "tokens_out": 0,
             "start": time.time()}

    output_lock = asyncio.Lock()
    out_f = open(output_path, "a")

    async def process_one(oid):
        async with sem:
            # Fetch abstract
            async with httpx.AsyncClient() as client:
                meta = await fetch_abstract(client, oid)
            if not meta or not meta.get("abstract"):
                stats["no_abstract"] += 1
                stats["total"] += 1
                return

            # Try to download PDF
            full_text = ""
            pdf_ok = False
            if meta.get("pdf_url"):
                try:
                    full_text = await download_and_extract_pdf(meta["pdf_url"]) or ""
                    pdf_ok = bool(full_text)
                except Exception:
                    pass

            if pdf_ok:
                stats["pdf_ok"] += 1
                content = f"Abstract: {meta['abstract']}\n\nFull Paper Text:\n{full_text}"
            else:
                stats["pdf_fail"] += 1
                content = f"Abstract: {meta['abstract']}"

        # Generate summary (sem released for fetch, re-acquired inside generate_summary)
        result = await generate_summary(meta["title"], content, sem)

        # Build JSONL entry
        entry = {
            "openreview_id": oid,
            "title": meta["title"],
            "status": "ok" if result["summary"] else "error",
            "summary": result["summary"] or "",
            "ai_rating": result["ai_rating"],
            "full_text_chars": len(full_text),
            "pdf_ok": pdf_ok,
            "truncated": False,
            "tokens": result["tokens"],
            "elapsed_s": result["elapsed_s"],
            "error": result["error"],
        }

        async with output_lock:
            out_f.write(json.dumps(entry) + "\n")
            out_f.flush()

        if result["summary"]:
            stats["ok"] += 1
            stats["tokens_in"] += result["tokens"].get("input", 0)
            stats["tokens_out"] += result["tokens"].get("output", 0)
        else:
            stats["failed"] += 1

        stats["total"] += 1
        if stats["total"] % 10 == 0:
            elapsed = time.time() - stats["start"]
            rate = stats["total"] / elapsed * 3600 if elapsed > 0 else 0
            eta = (len(remaining) - stats["total"]) / (rate / 3600) if rate > 0 else 0
            print(f"  [{stats['total']:>4}/{len(remaining)}]"
                  f"  ok={stats['ok']} fail={stats['failed']} no_abs={stats['no_abstract']}"
                  f"  pdf={stats['pdf_ok']}/{stats['pdf_ok']+stats['pdf_fail']}"
                  f"  rate={rate:.0f}/hr ETA={eta/60:.0f}m"
                  f"  tokens={stats['tokens_in']+stats['tokens_out']:,}")

    # Process with controlled parallelism
    # Batch to avoid creating too many tasks at once
    batch_size = parallel * 3
    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i+batch_size]
        await asyncio.gather(*[process_one(oid) for oid in batch])
        # Brief pause between batches for rate limiting
        await asyncio.sleep(1)

    out_f.close()

    elapsed = time.time() - stats["start"]
    print(f"\n  DONE in {elapsed/60:.1f}m — ok={stats['ok']} failed={stats['failed']} no_abstract={stats['no_abstract']}")
    print(f"  PDFs: {stats['pdf_ok']} ok, {stats['pdf_fail']} failed")
    print(f"  Tokens: {stats['tokens_in']+stats['tokens_out']:,}")

    return stats


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=str, default=None, help="Run only one dataset (e.g., 2025_LLMs)")
    args = parser.parse_args()

    print("ICLR Fetch & Summarize Pipeline")
    print(f"Parallel: {args.parallel}, Dry run: {args.dry_run}")

    for name, config in DATASETS.items():
        if args.only and args.only != name:
            continue
        await process_dataset(name, config, args.parallel, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
