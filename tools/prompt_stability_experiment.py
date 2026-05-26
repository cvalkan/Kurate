#!/usr/bin/env python3
"""Prompt Stability Experiment — Robust, resumable pipeline.

Design principles:
  - NEVER write failed results to the output JSONL. Only successes are persisted.
  - Resume by reading the JSONL — if a paper_id is present, it succeeded. Period.
  - Paper sets are deterministic (fixed seed) and saved to a manifest file.
  - Direct Anthropic API key is used as primary (not fallback) to avoid proxy issues.
  - Retries happen in-process with exponential backoff. No manual cleanup needed.
  - File writes are atomic (write to temp, rename).

Experiments:
  1 = Baseline: exact production prompt re-run
  2 = With reasons: adds per-dimension one-sentence justification
  3 = Extended: adds 6 new dimensions (difficulty, surprisingness, reproducibility,
      translational_potential, evidence_strength, generalisability)

Usage:
    python3 /app/tools/prompt_stability_experiment.py --experiment 3 --n 100 --parallel 3
    python3 /app/tools/prompt_stability_experiment.py --analyze
"""

import asyncio
import json
import os
import re
import sys
import time
import random
import fcntl
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

from core.config import db, EMERGENT_LLM_KEY
from emergentintegrations.llm.utils import get_integration_proxy_url
from services.llm import IMPACT_ASSESSMENT_PROMPT

PROXY_URL = get_integration_proxy_url() + "/llm"
ANTHROPIC_DIRECT = os.environ.get("ANTHROPIC_API_KEY")
OUTPUT_DIR = Path("/app/memory")

# ── Prompt variants ──

PROMPT_WITH_REASONS = {
    "system_prompt": IMPACT_ASSESSMENT_PROMPT["system_prompt"].replace(
        'After your assessment, provide numerical ratings on a JSON line. Rate each dimension from 1.0 to 10.0 (one decimal place):\n\n```json\n{"score": 7.5, "significance": 8.0, "rigor": 7.0, "novelty": 7.5, "clarity": 8.0}\n```',
        'After your assessment, provide numerical ratings as a JSON block. Rate each dimension from 1.0 to 10.0 (one decimal place). For each dimension, include a one-sentence justification.\n\n```json\n{\n  "score": 7.5,\n  "score_reason": "Strong contribution with broad applicability, limited by incremental methodology",\n  "significance": 8.0,\n  "significance_reason": "Addresses a key bottleneck in the field with clear downstream applications",\n  "rigor": 7.0,\n  "rigor_reason": "Well-designed experiments with proper baselines, but missing ablation on key hyperparameter",\n  "novelty": 7.5,\n  "novelty_reason": "Novel combination of existing techniques applied to an underexplored problem setting",\n  "clarity": 8.0,\n  "clarity_reason": "Well-structured paper with clear figures, though notation in Section 3 is dense"\n}\n```'
    ),
    "user_prompt": IMPACT_ASSESSMENT_PROMPT["user_prompt"],
}


# ── LLM call with robust retry ──

MAX_RETRIES = 5
RETRY_DELAYS = [2, 5, 10, 20, 30]  # seconds


async def call_llm(prompt_config, title, content):
    """Call LLM with retries across both direct and proxy. Returns (text, usage) or raises."""
    messages = [
        {"role": "system", "content": prompt_config["system_prompt"]},
        {"role": "user", "content": prompt_config["user_prompt"].format(title=title, content=content)},
    ]

    providers = []
    # Prefer direct Anthropic key — more reliable than proxy
    if ANTHROPIC_DIRECT:
        providers.append(("direct", {
            "model": "anthropic/claude-opus-4-6",
            "messages": messages,
            "api_key": ANTHROPIC_DIRECT,
            "timeout": 180,
        }))
    # Proxy as fallback
    providers.append(("proxy", {
        "model": "claude-opus-4-6",
        "messages": messages,
        "api_key": EMERGENT_LLM_KEY,
        "api_base": PROXY_URL,
        "custom_llm_provider": "openai",
    }))

    last_error = None
    for attempt in range(MAX_RETRIES):
        provider_name, params = providers[attempt % len(providers)]
        try:
            resp = await asyncio.to_thread(litellm.completion, **params)
            text = resp.choices[0].message.content if resp.choices else ""
            if text and text.strip():
                return text.strip(), resp.usage
            # Empty response — retry with other provider
            last_error = f"Empty response from {provider_name}"
        except Exception as e:
            last_error = f"{provider_name}: {str(e)[:200]}"

        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        await asyncio.sleep(delay)

    raise RuntimeError(f"All {MAX_RETRIES} attempts failed. Last: {last_error}")


def parse_ratings(text):
    """Extract JSON ratings from summary text. Handles multi-line JSON blocks."""
    # Try ```json ... ``` block first
    match = re.search(r'```json\s*(\{.*?\})\s*```', text[-2000:], re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Fallback: last { ... } containing "score"
    matches = list(re.finditer(r'\{[^{}]*"score"[^{}]*\}', text[-1000:]))
    if matches:
        try:
            return json.loads(matches[-1].group())
        except json.JSONDecodeError:
            pass
    return None


# ── File I/O — append-only, never overwrite ──

def append_result(path, entry):
    """Atomically append one JSON line. Uses file locking to prevent corruption."""
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def load_completed(path):
    """Load set of paper_ids that have successful results."""
    done = set()
    if not path.exists():
        return done
    for line in open(path):
        try:
            r = json.loads(line)
            # Only count as done if ratings were successfully parsed
            if r.get("new_ratings") and r.get("new_ratings", {}).get("score"):
                done.add(r["paper_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


# ── Paper loading — deterministic ──

async def load_papers(n, seed=42, paper_ids_file=None):
    """Load papers deterministically. Same seed = same papers."""
    if paper_ids_file and Path(paper_ids_file).exists():
        fixed_ids = json.load(open(paper_ids_file))
    else:
        fixed_ids = None

    # Get all eligible papers
    all_ranked = await db.rankings.find(
        {"comparisons": {"$gte": 10}},
        {"_id": 0, "paper_id": 1, "category": 1, "ts_score": 1, "score": 1},
    ).to_list(10000)

    rng = random.Random(seed)
    rng.shuffle(all_ranked)

    papers = []
    for rank_doc in all_ranked:
        if len(papers) >= n:
            break
        pid = rank_doc["paper_id"]
        if fixed_ids and pid not in fixed_ids:
            continue
        paper = await db.papers.find_one(
            {"id": pid, "full_text": {"$exists": True, "$ne": ""}},
            {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
             "summaries.anthropic:claude-opus-4-6:thinking": 1},
        )
        if not paper:
            continue
        summary = (paper.get("summaries") or {}).get("anthropic:claude-opus-4-6:thinking", "")
        original_ratings = parse_ratings(summary)
        if not original_ratings:
            continue
        papers.append({
            "id": pid,
            "title": paper["title"],
            "abstract": paper.get("abstract", ""),
            "full_text": paper["full_text"],
            "category": rank_doc["category"],
            "elo_score": rank_doc["score"],
            "original_ratings": original_ratings,
        })

    # If we had fixed_ids, also load any that weren't in the random sample
    if fixed_ids:
        loaded = {p["id"] for p in papers}
        for pid in fixed_ids:
            if pid in loaded or len(papers) >= n:
                continue
            rank_doc = await db.rankings.find_one({"paper_id": pid}, {"_id": 0, "paper_id": 1, "category": 1, "ts_score": 1, "score": 1})
            if not rank_doc:
                continue
            paper = await db.papers.find_one(
                {"id": pid, "full_text": {"$exists": True, "$ne": ""}},
                {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                 "summaries.anthropic:claude-opus-4-6:thinking": 1},
            )
            if not paper:
                continue
            summary = (paper.get("summaries") or {}).get("anthropic:claude-opus-4-6:thinking", "")
            original_ratings = parse_ratings(summary)
            if original_ratings:
                papers.append({
                    "id": pid, "title": paper["title"], "abstract": paper.get("abstract", ""),
                    "full_text": paper["full_text"], "category": rank_doc["category"],
                    "elo_score": rank_doc["score"], "original_ratings": original_ratings,
                })

    return papers


# ── Experiment runner ──

async def run_experiment(experiment, papers, parallel, output_path, prompt_config):
    label = {1: "baseline", 2: "with_reasons", 3: "extended"}[experiment]

    # Save manifest (paper IDs) so future runs use the exact same set
    manifest_path = OUTPUT_DIR / f"prompt_stability_exp{experiment}_manifest.json"
    if not manifest_path.exists():
        json.dump([p["id"] for p in papers], open(manifest_path, "w"))

    done = load_completed(output_path)
    remaining = [p for p in papers if p["id"] not in done]

    print(f"\nExperiment {experiment} ({label})")
    print(f"  Output: {output_path}")
    print(f"  Papers: {len(papers)}, Completed: {len(done)}, Remaining: {len(remaining)}")

    if not remaining:
        print("  All done!")
        return

    sem = asyncio.Semaphore(parallel)
    stats = {"ok": 0, "failed": 0, "total": 0, "start": time.time()}

    async def process_one(paper):
        async with sem:
            content = f"Abstract: {paper['abstract']}\n\nFull Paper Text:\n{paper['full_text']}"
            t0 = time.time()

            try:
                text, usage = await call_llm(prompt_config, paper["title"], content)
                ratings = parse_ratings(text)
                if not ratings or not ratings.get("score"):
                    stats["failed"] += 1
                    stats["total"] += 1
                    return  # Don't write — will be retried on next run

                entry = {
                    "paper_id": paper["id"],
                    "title": paper["title"],
                    "category": paper["category"],
                    "elo_score": paper["elo_score"],
                    "original_ratings": paper["original_ratings"],
                    "new_ratings": ratings,
                    "tokens_in": usage.prompt_tokens if usage else 0,
                    "tokens_out": usage.completion_tokens if usage else 0,
                    "elapsed_s": round(time.time() - t0, 1),
                    "error": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                append_result(output_path, entry)
                stats["ok"] += 1

            except Exception as e:
                # Log but DON'T write to JSONL — will be retried on next run
                stats["failed"] += 1

            stats["total"] += 1
            if stats["total"] % 5 == 0:
                elapsed = time.time() - stats["start"]
                rate = stats["total"] / elapsed * 3600 if elapsed > 0 else 0
                eta = (len(remaining) - stats["total"]) / (rate / 3600) if rate > 0 else 0
                print(f"  [{stats['total']:>4}/{len(remaining)}] ok={stats['ok']} fail={stats['failed']} rate={rate:.0f}/hr ETA={eta/60:.0f}m")

    # Process sequentially in small batches to avoid overwhelming the API
    batch_size = max(parallel, 3)
    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i + batch_size]
        await asyncio.gather(*[process_one(p) for p in batch])
        await asyncio.sleep(0.5)

    elapsed = time.time() - stats["start"]
    print(f"  Done in {elapsed/60:.1f}m: ok={stats['ok']}, failed={stats['failed']}")
    if stats["failed"] > 0:
        print(f"  {stats['failed']} papers need retry — just re-run the same command.")


# ── Analysis ──

def analyze():
    import numpy as np
    from scipy import stats as sp_stats

    dims = ["score", "significance", "rigor", "novelty", "clarity"]

    for exp in [1, 2, 3]:
        labels = {1: "baseline", 2: "with_reasons", 3: "extended"}
        label = labels[exp]
        path = OUTPUT_DIR / f"prompt_stability_exp{exp}_{label}.jsonl"
        if not path.exists():
            print(f"\nExperiment {exp}: no data yet")
            continue

        records = list(load_completed_records(path))
        if not records:
            print(f"\nExperiment {exp}: no valid records")
            continue

        print(f"\n{'='*60}")
        print(f"Experiment {exp}: {label.upper()} ({len(records)} papers)")
        print(f"{'='*60}")

        print(f"\n{'Dimension':<15} {'Orig':>6} {'New':>6} {'Diff':>7} {'Corr':>6} {'p':>8} {'MAE':>6}")
        print("-" * 60)

        for dim in dims:
            orig = np.array([r["original_ratings"].get(dim, 0) for r in records], dtype=float)
            new = np.array([r["new_ratings"].get(dim, 0) for r in records], dtype=float)
            valid = (orig > 0) & (new > 0)
            orig, new = orig[valid], new[valid]
            if len(orig) < 5:
                continue
            diff = new - orig
            corr, p_val = sp_stats.pearsonr(orig, new)
            mae = np.abs(diff).mean()
            print(f"{dim:<15} {orig.mean():>6.2f} {new.mean():>6.2f} {diff.mean():>+7.2f} {corr:>6.3f} {p_val:>8.4f} {mae:>6.2f}")

        all_orig = np.concatenate([np.array([r["original_ratings"].get(d, 0) for r in records]) for d in dims])
        all_new = np.concatenate([np.array([r["new_ratings"].get(d, 0) for r in records]) for d in dims])
        valid = (all_orig > 0) & (all_new > 0)
        print(f"\n  Overall MAE: {np.abs(all_new[valid] - all_orig[valid]).mean():.2f}")
        print(f"  Overall mean shift: {(all_new[valid] - all_orig[valid]).mean():+.2f}")
        print(f"  Pearson r (all dims): {sp_stats.pearsonr(all_orig[valid], all_new[valid])[0]:.3f}")

        # Extended dimensions
        if exp == 3:
            ext_dims = ["difficulty", "surprisingness", "reproducibility", "translational_potential", "evidence_strength", "generalisability"]
            print(f"\n  Extended dimensions:")
            for dim in ext_dims:
                vals = [r["new_ratings"].get(dim) for r in records if r.get("new_ratings", {}).get(dim) is not None]
                if vals:
                    arr = np.array(vals, dtype=float)
                    null_count = sum(1 for r in records if r.get("new_ratings", {}).get(dim) is None)
                    print(f"    {dim:<25} mean={arr.mean():.2f}  std={arr.std():.2f}  n={len(vals)}  null={null_count}")


def load_completed_records(path):
    """Load all successful records from JSONL."""
    for line in open(path):
        try:
            r = json.loads(line)
            if r.get("new_ratings") and r.get("new_ratings", {}).get("score") and r.get("original_ratings"):
                yield r
        except (json.JSONDecodeError, KeyError):
            continue


# ── Main ──

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=int, choices=[1, 2, 3])
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--paper-ids", type=str, default=None)
    args = parser.parse_args()

    if args.analyze:
        analyze()
        return

    if not args.experiment:
        print("Specify --experiment 1, 2, or 3 (or --analyze)")
        return

    # Load manifest if it exists (deterministic paper set from previous run)
    labels = {1: "baseline", 2: "with_reasons", 3: "extended"}
    label = labels[args.experiment]
    manifest_path = OUTPUT_DIR / f"prompt_stability_exp{args.experiment}_manifest.json"
    paper_ids_file = args.paper_ids or (str(manifest_path) if manifest_path.exists() else None)

    papers = await load_papers(args.n, seed=args.seed, paper_ids_file=paper_ids_file)
    print(f"Loaded {len(papers)} papers (seed={args.seed})")

    if args.dry_run:
        for p in papers[:5]:
            print(f"  [{p['category']}] {p['title'][:50]} — {p['original_ratings']}")
        return

    # Select prompt
    if args.experiment == 1:
        prompt_config = IMPACT_ASSESSMENT_PROMPT
    elif args.experiment == 2:
        prompt_config = PROMPT_WITH_REASONS
    elif args.experiment == 3:
        from prompts.extended_impact_v2 import EXTENDED_IMPACT_PROMPT_V2
        prompt_config = EXTENDED_IMPACT_PROMPT_V2

    output_path = OUTPUT_DIR / f"prompt_stability_exp{args.experiment}_{label}.jsonl"

    await run_experiment(args.experiment, papers, args.parallel, output_path, prompt_config)


if __name__ == "__main__":
    asyncio.run(main())
