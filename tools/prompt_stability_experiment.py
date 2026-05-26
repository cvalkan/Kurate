#!/usr/bin/env python3
"""Prompt Stability Experiment — Two controlled tests:

Experiment 1 (BASELINE): Re-run the exact production prompt on the top 100 papers
    to measure rating stability (same prompt, same model, different run).

Experiment 2 (REASONS): Add one-sentence reasoning for each of the 5 existing
    dimensions. Check if adding reasons shifts the scores.

Both compare against the original ratings embedded in the existing summaries.

Usage:
    python3 /app/tools/prompt_stability_experiment.py --dry-run
    python3 /app/tools/prompt_stability_experiment.py --experiment 1 --n 100 --parallel 10
    python3 /app/tools/prompt_stability_experiment.py --experiment 2 --n 100 --parallel 10
    python3 /app/tools/prompt_stability_experiment.py --analyze
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
litellm.set_verbose = False

from core.config import db, EMERGENT_LLM_KEY
from emergentintegrations.llm.utils import get_integration_proxy_url
from services.llm import IMPACT_ASSESSMENT_PROMPT

PROXY_URL = get_integration_proxy_url() + "/llm"
OUTPUT_DIR = Path("/app/memory")

# ── Experiment 2 prompt: production + per-dimension reasoning ──
PROMPT_WITH_REASONS = {
    "system_prompt": IMPACT_ASSESSMENT_PROMPT["system_prompt"].replace(
        """After your assessment, provide numerical ratings on a JSON line. Rate each dimension from 1.0 to 10.0 (one decimal place):

```json
{"score": 7.5, "significance": 8.0, "rigor": 7.0, "novelty": 7.5, "clarity": 8.0}
```""",
        """After your assessment, provide numerical ratings as a JSON block. Rate each dimension from 1.0 to 10.0 (one decimal place). For each dimension, include a one-sentence justification.

```json
{
  "score": 7.5,
  "score_reason": "Strong contribution with broad applicability, limited by incremental methodology",
  "significance": 8.0,
  "significance_reason": "Addresses a key bottleneck in the field with clear downstream applications",
  "rigor": 7.0,
  "rigor_reason": "Well-designed experiments with proper baselines, but missing ablation on key hyperparameter",
  "novelty": 7.5,
  "novelty_reason": "Novel combination of existing techniques applied to an underexplored problem setting",
  "clarity": 8.0,
  "clarity_reason": "Well-structured paper with clear figures, though notation in Section 3 is dense"
}
```"""
    ),
    "user_prompt": IMPACT_ASSESSMENT_PROMPT["user_prompt"],
}


async def generate_summary(title, content, prompt_config, sem):
    async with sem:
        prompt = prompt_config["user_prompt"].format(title=title, content=content)
        params = {
            "model": "claude-opus-4-6",
            "messages": [
                {"role": "system", "content": prompt_config["system_prompt"]},
                {"role": "user", "content": prompt},
            ],
            "api_key": EMERGENT_LLM_KEY,
            "api_base": PROXY_URL,
            "custom_llm_provider": "openai",
        }
        t0 = time.time()
        for attempt in range(3):
            try:
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: litellm.completion(**params))
                text = resp.choices[0].message.content
                if text is None or not text.strip():
                    if attempt < 2:
                        await asyncio.sleep(3)
                        continue
                    return {"error": "Model returned empty/None content after 3 attempts", "elapsed_s": round(time.time() - t0, 1)}
                text = text.strip()
                tokens_in = resp.usage.prompt_tokens if resp.usage else 0
                tokens_out = resp.usage.completion_tokens if resp.usage else 0

                ratings = None
                match = re.search(r'\{[^{}]*"score"[^}]*\}', text[-800:], re.DOTALL)
                if match:
                    try:
                        ratings = json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

                return {
                    "summary": text,
                    "ratings": ratings,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "elapsed_s": round(time.time() - t0, 1),
                    "error": None,
                }
            except Exception as e:
                if attempt < 2 and "Budget" not in str(e):
                    await asyncio.sleep(3)
                    continue
                return {"error": str(e)[:300], "elapsed_s": round(time.time() - t0, 1)}


async def load_top_papers(n):
    """Load N random papers (with full text and original ratings) across all categories."""
    import random

    # Get all papers with sufficient comparisons
    all_ranked = await db.rankings.find(
        {"comparisons": {"$gte": 10}},
        {"_id": 0, "paper_id": 1, "category": 1, "ts_score": 1, "score": 1},
    ).to_list(10000)

    random.shuffle(all_ranked)

    papers = []
    for rank_doc in all_ranked:
        if len(papers) >= n:
            break
        paper = await db.papers.find_one(
            {"id": rank_doc["paper_id"], "full_text": {"$exists": True, "$ne": ""}},
            {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
             "summaries.anthropic:claude-opus-4-6:thinking": 1, "ai_rating": 1},
        )
        if not paper:
            continue

        summary = (paper.get("summaries") or {}).get("anthropic:claude-opus-4-6:thinking", "")
        original_ratings = None
        match = re.search(r'\{[^{}]*"score"[^}]*\}', summary[-400:], re.DOTALL)
        if match:
            try:
                original_ratings = json.loads(match.group())
            except json.JSONDecodeError:
                pass

        if not original_ratings:
            continue

        papers.append({
            "id": paper["id"],
            "title": paper["title"],
            "abstract": paper.get("abstract", ""),
            "full_text": paper["full_text"],
            "category": rank_doc["category"],
            "elo_score": rank_doc["score"],
            "original_ratings": original_ratings,
        })

    return papers


async def run_experiment(experiment, papers, parallel):
    prompt_config = IMPACT_ASSESSMENT_PROMPT if experiment == 1 else PROMPT_WITH_REASONS
    label = "baseline" if experiment == 1 else "with_reasons"
    output_path = OUTPUT_DIR / f"prompt_stability_exp{experiment}_{label}.jsonl"

    # Load already completed
    done = set()
    if output_path.exists():
        for line in open(output_path):
            try:
                r = json.loads(line)
                if r.get("new_ratings"):
                    done.add(r["paper_id"])
            except:
                pass

    remaining = [p for p in papers if p["id"] not in done]
    print(f"\nExperiment {experiment} ({label})")
    print(f"  Papers: {len(papers)}, Already done: {len(done)}, Remaining: {len(remaining)}")

    if not remaining:
        print("  All done!")
        return

    sem = asyncio.Semaphore(parallel)
    stats = {"ok": 0, "failed": 0, "total": 0, "start": time.time()}

    async def process_one(paper):
        content = f"Abstract: {paper['abstract']}\n\nFull Paper Text:\n{paper['full_text']}"
        result = await generate_summary(paper["title"], content, prompt_config, sem)

        entry = {
            "paper_id": paper["id"],
            "title": paper["title"],
            "category": paper["category"],
            "elo_score": paper["elo_score"],
            "original_ratings": paper["original_ratings"],
            "new_ratings": result.get("ratings"),
            "tokens_in": result.get("tokens_in", 0),
            "tokens_out": result.get("tokens_out", 0),
            "elapsed_s": result.get("elapsed_s", 0),
            "error": result.get("error"),
        }

        with open(output_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        if result.get("ratings"):
            stats["ok"] += 1
        else:
            stats["failed"] += 1
        stats["total"] += 1

        if stats["total"] % 10 == 0:
            elapsed = time.time() - stats["start"]
            rate = stats["total"] / elapsed * 3600 if elapsed > 0 else 0
            eta = (len(remaining) - stats["total"]) / (rate / 3600) if rate > 0 else 0
            print(f"  [{stats['total']:>4}/{len(remaining)}] ok={stats['ok']} fail={stats['failed']} rate={rate:.0f}/hr ETA={eta/60:.0f}m")

    # Process in batches
    batch_size = parallel * 3
    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i + batch_size]
        await asyncio.gather(*[process_one(p) for p in batch])
        await asyncio.sleep(1)

    print(f"  Done: ok={stats['ok']}, failed={stats['failed']}")


def analyze():
    """Compare original vs new ratings across both experiments."""
    import numpy as np
    from scipy import stats as sp_stats

    dims = ["score", "significance", "rigor", "novelty", "clarity"]

    for exp in [1, 2]:
        label = "baseline" if exp == 1 else "with_reasons"
        path = OUTPUT_DIR / f"prompt_stability_exp{exp}_{label}.jsonl"
        if not path.exists():
            print(f"\nExperiment {exp}: no data yet")
            continue

        records = []
        for line in open(path):
            r = json.loads(line)
            if r.get("original_ratings") and r.get("new_ratings"):
                records.append(r)

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

        # Overall shift
        all_orig = []
        all_new = []
        for dim in dims:
            all_orig.extend([r["original_ratings"].get(dim, 0) for r in records])
            all_new.extend([r["new_ratings"].get(dim, 0) for r in records])
        all_orig = np.array(all_orig, dtype=float)
        all_new = np.array(all_new, dtype=float)
        valid = (all_orig > 0) & (all_new > 0)
        print(f"\n  Overall MAE: {np.abs(all_new[valid] - all_orig[valid]).mean():.2f}")
        print(f"  Overall mean shift: {(all_new[valid] - all_orig[valid]).mean():+.2f}")
        print(f"  Pearson r (all dims): {sp_stats.pearsonr(all_orig[valid], all_new[valid])[0]:.3f}")

        # Check for reason fields in experiment 2
        if exp == 2 and records:
            reason_fields = [k for k in records[0].get("new_ratings", {}) if k.endswith("_reason")]
            if reason_fields:
                print(f"\n  Reason fields present: {reason_fields}")
                sample = records[0]["new_ratings"]
                for rf in reason_fields[:3]:
                    print(f"    {rf}: {sample.get(rf, '')[:80]}")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=int, choices=[1, 2], help="Which experiment to run")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--parallel", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--paper-ids", type=str, default=None, help="JSON file with fixed paper IDs to use")
    args = parser.parse_args()

    if args.analyze:
        analyze()
        return

    papers = await load_top_papers(args.n)
    
    # If fixed paper IDs provided, filter to only those
    if args.paper_ids:
        fixed_ids = set(json.load(open(args.paper_ids)))
        papers = [p for p in papers if p["id"] in fixed_ids]
        # Also load any missing papers that were in the fixed set but not in random sample
        loaded_ids = {p["id"] for p in papers}
        missing = fixed_ids - loaded_ids
        if missing:
            for pid in missing:
                rank_doc = await db.rankings.find_one({"paper_id": pid}, {"_id": 0, "paper_id": 1, "category": 1, "ts_score": 1, "score": 1})
                if not rank_doc: continue
                paper = await db.papers.find_one(
                    {"id": pid, "full_text": {"$exists": True, "$ne": ""}},
                    {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                     "summaries.anthropic:claude-opus-4-6:thinking": 1, "ai_rating": 1},
                )
                if not paper: continue
                summary = (paper.get("summaries") or {}).get("anthropic:claude-opus-4-6:thinking", "")
                original_ratings = None
                match = re.search(r'\{[^{}]*"score"[^}]*\}', summary[-400:], re.DOTALL)
                if match:
                    try: original_ratings = json.loads(match.group())
                    except: pass
                if original_ratings:
                    papers.append({"id": paper["id"], "title": paper["title"], "abstract": paper.get("abstract", ""),
                                   "full_text": paper["full_text"], "category": rank_doc["category"],
                                   "elo_score": rank_doc["score"], "original_ratings": original_ratings})
    
    print(f"Loaded {len(papers)} papers with original ratings")

    if args.dry_run:
        for p in papers[:5]:
            print(f"  [{p['category']}] {p['title'][:50]} — orig: {p['original_ratings']}")
        print(f"\n  Prompt with reasons system_prompt length: {len(PROMPT_WITH_REASONS['system_prompt'])}")
        # Verify the reasons prompt has the right JSON example
        match = re.search(r'\{[^{}]*"score"[^}]*\}', PROMPT_WITH_REASONS["system_prompt"][-800:], re.DOTALL)
        if match:
            example = json.loads(match.group())
            print(f"  Reasons prompt JSON fields: {sorted(example.keys())}")
        return

    if args.experiment:
        await run_experiment(args.experiment, papers, args.parallel)
    else:
        print("Specify --experiment 1 or --experiment 2 (or --analyze)")


if __name__ == "__main__":
    asyncio.run(main())
