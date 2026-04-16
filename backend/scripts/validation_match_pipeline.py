#!/usr/bin/env python3
"""
Validation Match Pipeline — Parallelized & Resumable

Runs 58K+ pairwise comparisons from a CSV of (id_1, id_2) pairs using
round-robin model selection (GPT-5.4, Claude Opus 4.6, Gemini 3 Pro).

Uses the SAME prompt, content format, anonymization, and response parsing
as the live tournament system — imported directly, not reimplemented.

Usage:
  python3 scripts/validation_match_pipeline.py --dry-run
  python3 scripts/validation_match_pipeline.py --parallel 30 --parallel-pdf 3
"""

import asyncio
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

# ── imports from live system ──
from core.config import DEFAULT_EVALUATION_PROMPT, EMERGENT_LLM_KEY
from emergentintegrations.llm.utils import get_integration_proxy_url
from scripts.iclr_batch_summaries import anonymize_text, download_pdf_playwright

PROXY_URL = get_integration_proxy_url() + "/llm"
OPENAI_KEY_DIRECT = os.environ.get("OPENAI_API_KEY_DIRECT")

# ── paths ──
CSV_PATH = Path("/tmp/sampled_matches.csv")
SUMMARIES_PATH = ROOT.parent / "memory" / "iclr_2026_summaries.jsonl"
ABSTRACTS_CACHE = ROOT.parent / "memory" / "iclr_2026_abstracts.json"
OUTPUT_PATH = ROOT.parent / "memory" / "validation_match_results.jsonl"

# ── models (round-robin) ──
MODELS = [
    {
        "name": "gpt-5.4",
        "provider": "openai",
        "model": "gpt-5.4",
        "litellm_model": "gpt-5.4",
        "api_key": OPENAI_KEY_DIRECT,
        "api_base": None,
        "custom_llm_provider": None,
    },
    {
        "name": "claude-opus-4-6",
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "litellm_model": "claude-opus-4-6",
        "api_key": EMERGENT_LLM_KEY,
        "api_base": PROXY_URL,
        "custom_llm_provider": "openai",
    },
    {
        "name": "gemini-3-pro-preview",
        "provider": "gemini",
        "model": "gemini-3-pro-preview",
        "litellm_model": "gemini/gemini-3-pro-preview",
        "api_key": EMERGENT_LLM_KEY,
        "api_base": PROXY_URL,
        "custom_llm_provider": "openai",
    },
]

_model_counter = 0


def pick_model() -> dict:
    global _model_counter
    m = MODELS[_model_counter % len(MODELS)]
    _model_counter += 1
    return m


# ── content building: IDENTICAL to compare_papers() lines 592-598 ──

def build_paper_content(paper: dict) -> str:
    """Build content string exactly as compare_papers does for abstract_plus_summary mode."""
    abstract = paper.get("abstract", "")
    summary = (paper.get("ai_impact_summary_thinking", "")
               or paper.get("ai_impact_summary_opus46", "")
               or paper.get("ai_impact_summary", ""))
    if summary:
        return f"Abstract: {abstract}\n\nAI Impact Assessment:\n{summary}"
    return f"Abstract: {abstract}"


# ── response parsing: IDENTICAL to compare_papers() lines 676-711 ──

def parse_comparison_response(response_text: str) -> dict:
    """Parse LLM response exactly as compare_papers does."""
    text = response_text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    # Extract JSON if not at start
    if not text.startswith("{"):
        json_match = re.search(r'\{[^{}]*"winner"[^{}]*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group()
        else:
            raise ValueError(f"No JSON found in response: {text[:200]}")
    result = json.loads(text)
    if "winner" not in result or result["winner"] not in ("paper1", "paper2"):
        raise ValueError(f"Invalid response format: {result}")
    return result


# ── abstract extraction from PDF text ──

def extract_abstract(full_text: str) -> str:
    """Extract the abstract section from PDF text."""
    # Normalize common PDF extraction artifacts: spaces within words
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


# ── abstract fetching via Playwright (reuses iclr_batch_summaries.download_pdf_playwright) ──

async def fetch_abstracts(paper_ids: set, cache_path: str, parallel: int = 3) -> dict:
    """Fetch abstracts from OpenReview PDFs via Playwright, with file cache."""
    abstracts = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            abstracts = json.load(f)
        has = sum(1 for v in abstracts.values() if v)
        print(f"  Loaded {len(abstracts)} cached ({has} with content)")

    missing = paper_ids - set(abstracts.keys())
    if not missing:
        print(f"  All {len(paper_ids)} abstracts cached")
        return abstracts

    print(f"  Downloading {len(missing)} PDFs via Playwright (parallel={parallel})...")
    sem = asyncio.Semaphore(parallel)
    fetched, failed = 0, 0

    async def fetch_one(oid: str):
        nonlocal fetched, failed
        async with sem:
            full_text = await download_pdf_playwright(oid, max_retries=2)
            if full_text:
                anon_text = anonymize_text(full_text)
                abstract = extract_abstract(anon_text)
                abstracts[oid] = abstract
                if abstract:
                    fetched += 1
                else:
                    failed += 1
            else:
                abstracts[oid] = ""
                failed += 1

            done = fetched + failed
            if done % 50 == 0:
                print(f"    ... {done}/{len(missing)} ({fetched} ok, {failed} empty)")

    # Process in batches, save cache after each
    missing_list = list(missing)
    batch_size = 100
    for i in range(0, len(missing_list), batch_size):
        batch = missing_list[i:i + batch_size]
        await asyncio.gather(*[fetch_one(oid) for oid in batch])
        with open(cache_path, "w") as f:
            json.dump(abstracts, f)
        print(f"    Cached after batch {i // batch_size + 1} ({fetched + failed}/{len(missing)})")

    # Close the shared Playwright browser
    from scripts.iclr_batch_summaries import _browser, _pw
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()

    print(f"  Done: {fetched} abstracts, {failed} empty/failed")
    return abstracts


# ── data loading ──

def load_matches(csv_path: str) -> list:
    with open(csv_path) as f:
        return [(r["id_1"], r["id_2"]) for r in csv.DictReader(f)]


def load_summaries(jsonl_path: str) -> dict:
    papers = {}
    with open(jsonl_path) as f:
        for line in f:
            doc = json.loads(line)
            oid = doc.get("openreview_id")
            if oid and doc.get("summary"):
                papers[oid] = doc
    return papers


def load_completed(output_path: str) -> set:
    completed = set()
    if not os.path.exists(output_path):
        return completed
    with open(output_path) as f:
        for line in f:
            try:
                r = json.loads(line)
                completed.add(f"{r['id_1']}|{r['id_2']}")
            except (json.JSONDecodeError, KeyError):
                continue
    return completed


# ── single comparison ──

async def run_comparison(
    id_1: str, id_2: str,
    paper1: dict, paper2: dict,
    sem: asyncio.Semaphore,
    output_file,
    output_lock: asyncio.Lock,
    stats: dict,
) -> None:
    async with sem:
        model = pick_model()
        system_msg = DEFAULT_EVALUATION_PROMPT["system_prompt"]
        user_template = DEFAULT_EVALUATION_PROMPT["user_prompt"]

        p1_content = build_paper_content(paper1)
        p2_content = build_paper_content(paper2)

        # Random 50% flip for positional bias (same as scheduler.py line 1316)
        flipped = random.random() < 0.5
        if flipped:
            prompt_p1, prompt_p2 = paper2, paper1
            prompt_c1, prompt_c2 = p2_content, p1_content
        else:
            prompt_p1, prompt_p2 = paper1, paper2
            prompt_c1, prompt_c2 = p1_content, p2_content

        prompt = user_template.format(
            paper1_title=prompt_p1["title"],
            paper1_content=prompt_c1,
            paper2_title=prompt_p2["title"],
            paper2_content=prompt_c2,
        )

        params = {
            "model": model["litellm_model"],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "api_key": model["api_key"],
            "max_tokens": 500,
            "temperature": 0.3,
        }
        if model["api_base"]:
            params["api_base"] = model["api_base"]
        if model["custom_llm_provider"]:
            params["custom_llm_provider"] = model["custom_llm_provider"]

        t0 = time.time()
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: litellm.completion(**params))
            raw = resp.choices[0].message.content

            parsed = parse_comparison_response(raw)

            # Map winner back through flip
            winner_raw = parsed["winner"]
            if winner_raw == "paper1":
                winner_id = id_2 if flipped else id_1
            else:
                winner_id = id_1 if flipped else id_2

            elapsed = time.time() - t0
            tokens_in = resp.usage.prompt_tokens if resp.usage else 0
            tokens_out = resp.usage.completion_tokens if resp.usage else 0

            result = {
                "id_1": id_1,
                "id_2": id_2,
                "winner": winner_id,
                "model": model["name"],
                "flipped": flipped,
                "reasoning": parsed.get("reasoning", "")[:300],
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "elapsed_s": round(elapsed, 2),
            }

            async with output_lock:
                output_file.write(json.dumps(result) + "\n")
                output_file.flush()

            stats["ok"] += 1
            stats["tokens_in"] += tokens_in
            stats["tokens_out"] += tokens_out
            stats["by_model"][model["name"]] = stats["by_model"].get(model["name"], 0) + 1

        except Exception as e:
            elapsed = time.time() - t0
            result = {
                "id_1": id_1,
                "id_2": id_2,
                "winner": None,
                "model": model["name"],
                "flipped": flipped,
                "error": str(e)[:200],
                "elapsed_s": round(elapsed, 2),
            }
            async with output_lock:
                output_file.write(json.dumps(result) + "\n")
                output_file.flush()

            stats["failed"] += 1
            if "rate" in str(e).lower() or "429" in str(e):
                stats["rate_limited"] += 1

        stats["total"] += 1
        if stats["total"] % 50 == 0:
            elapsed_total = time.time() - stats["start_time"]
            rate = stats["total"] / elapsed_total * 3600
            remaining = (stats["target"] - stats["total"]) / (rate / 3600) if rate > 0 else 0
            print(
                f"  [{stats['total']:>6}/{stats['target']}]"
                f"  ok={stats['ok']} fail={stats['failed']}"
                f"  rate={rate:.0f}/hr"
                f"  ETA={remaining/60:.0f}m"
                f"  tokens={stats['tokens_in']+stats['tokens_out']:,}"
                f"  models={stats['by_model']}"
            )


# ── main ──

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validation match pipeline")
    parser.add_argument("--parallel", type=int, default=30, help="Max concurrent LLM calls")
    parser.add_argument("--parallel-pdf", type=int, default=3, help="Max concurrent PDF downloads")
    parser.add_argument("--dry-run", action="store_true", help="Load data and report stats without running")
    parser.add_argument("--limit", type=int, default=0, help="Limit matches (0 = all)")
    parser.add_argument("--csv", type=str, default=str(CSV_PATH), help="Input CSV path")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="Output JSONL path")
    args = parser.parse_args()

    print("=" * 60)
    print("Validation Match Pipeline")
    print("=" * 60)

    # 1. Load matches
    print(f"\n1. Loading matches from {args.csv}")
    matches = load_matches(args.csv)
    print(f"   {len(matches):,} pairs loaded")

    # 2. Load summaries
    print(f"\n2. Loading summaries from {SUMMARIES_PATH}")
    summaries = load_summaries(SUMMARIES_PATH)
    print(f"   {len(summaries):,} papers with summaries")

    # 3. Filter runnable matches
    runnable = []
    skipped = 0
    for id_1, id_2 in matches:
        if id_1 in summaries and id_2 in summaries:
            runnable.append((id_1, id_2))
        else:
            skipped += 1
    print(f"\n3. Runnable matches: {len(runnable):,} (skipped {skipped} missing summaries)")

    # 4. Resume
    completed = load_completed(args.output)
    remaining = [(a, b) for a, b in runnable if f"{a}|{b}" not in completed]
    print(f"\n4. Resumability: {len(completed):,} done, {len(remaining):,} remaining")

    if args.limit > 0:
        remaining = remaining[:args.limit]
        print(f"   Limited to {args.limit} matches")

    # 5. Fetch abstracts only for papers in remaining matches
    needed_ids = set()
    for id_1, id_2 in remaining:
        needed_ids.add(id_1)
        needed_ids.add(id_2)
    print(f"\n5. Fetching abstracts for {len(needed_ids):,} papers")
    abstracts = await fetch_abstracts(needed_ids, str(ABSTRACTS_CACHE), parallel=args.parallel_pdf)

    # 6. Build paper dicts (same shape as live system)
    print(f"\n6. Building paper dicts...")
    paper_dicts = {}
    for oid in needed_ids:
        summary_doc = summaries[oid]
        paper_dicts[oid] = {
            "title": summary_doc["title"],
            "abstract": abstracts.get(oid, ""),
            "ai_impact_summary_thinking": summary_doc["summary"],
        }
    has_abstract = sum(1 for p in paper_dicts.values() if p["abstract"])
    print(f"   {len(paper_dicts):,} papers ({has_abstract} with abstracts)")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Models: {', '.join(m['name'] for m in MODELS)}")
    print(f"Parallelism: {args.parallel} LLM / {args.parallel_pdf} PDF")
    print(f"Matches to run: {len(remaining):,}")
    est_hours = len(remaining) / args.parallel * 3 / 3600
    print(f"Est. time: ~{est_hours:.1f} hours")
    print(f"Output: {args.output}")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\n[DRY RUN] Exiting.")
        return

    if not remaining:
        print("\nAll matches already completed!")
        return

    # 7. Run comparisons
    print(f"\n7. Starting {len(remaining):,} comparisons...")
    sem = asyncio.Semaphore(args.parallel)
    output_lock = asyncio.Lock()
    stats = {
        "ok": 0, "failed": 0, "total": 0, "target": len(remaining),
        "tokens_in": 0, "tokens_out": 0, "rate_limited": 0,
        "by_model": {}, "start_time": time.time(),
    }

    with open(args.output, "a") as out_f:
        tasks = [
            run_comparison(
                id_1, id_2,
                paper_dicts[id_1], paper_dicts[id_2],
                sem, out_f, output_lock, stats,
            )
            for id_1, id_2 in remaining
        ]
        await asyncio.gather(*tasks)

    elapsed = time.time() - stats["start_time"]
    print(f"\n{'=' * 60}")
    print(f"DONE in {elapsed / 3600:.1f} hours")
    print(f"  OK: {stats['ok']:,}")
    print(f"  Failed: {stats['failed']:,}")
    print(f"  Rate limited: {stats['rate_limited']}")
    print(f"  Tokens: {stats['tokens_in'] + stats['tokens_out']:,}")
    print(f"  By model: {stats['by_model']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
