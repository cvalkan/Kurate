#!/usr/bin/env python3
"""A/B test: Extended Impact Assessment Prompt v2 vs production prompt.

Runs both prompts on the same papers and compares score distributions.
Uses Claude Opus 4.6 via Emergent key (same as production).

Usage:
    python3 /app/tools/test_extended_prompt.py --dry-run
    python3 /app/tools/test_extended_prompt.py --n 10 --parallel 5
    python3 /app/tools/test_extended_prompt.py --n 50 --parallel 10 --only-v2
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
from prompts.extended_impact_v2 import EXTENDED_IMPACT_PROMPT_V2

PROXY_URL = get_integration_proxy_url() + "/llm"
OUTPUT_DIR = Path("/app/memory")


async def generate_summary(title, content, prompt_config, sem):
    """Generate impact assessment using given prompt config."""
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
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: litellm.completion(**params))
            text = resp.choices[0].message.content
            if text is None:
                return {"error": "Model refused (None content)", "elapsed_s": round(time.time() - t0, 1)}
            text = text.strip()
            tokens_in = resp.usage.prompt_tokens if resp.usage else 0
            tokens_out = resp.usage.completion_tokens if resp.usage else 0

            # Extract JSON block
            ratings = None
            # Try multi-line JSON first
            match = re.search(r'\{[^{}]*"score"[^}]*\}', text[-600:], re.DOTALL)
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
            return {"error": str(e)[:300], "elapsed_s": round(time.time() - t0, 1)}


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10, help="Number of papers to test")
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-v2", action="store_true", help="Only run v2 prompt (skip A/B comparison)")
    parser.add_argument("--category", type=str, default="cs.AI", help="Category to sample from")
    args = parser.parse_args()

    print(f"Extended Prompt A/B Test")
    print(f"Papers: {args.n}, Parallel: {args.parallel}, Category: {args.category}")
    print(f"Mode: {'V2 only' if args.only_v2 else 'A/B comparison'}")

    # Sample papers with full text
    papers = []
    async for doc in db.papers.find(
        {"categories.0": args.category, "full_text": {"$exists": True, "$ne": ""}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1},
    ).limit(args.n):
        papers.append(doc)

    print(f"Sampled {len(papers)} papers with full text")

    if args.dry_run:
        for p in papers[:3]:
            print(f"  {p['title'][:60]}")
        return

    sem = asyncio.Semaphore(args.parallel)
    v1_output = OUTPUT_DIR / f"prompt_test_v1_{args.category.replace('.', '_')}.jsonl"
    v2_output = OUTPUT_DIR / f"prompt_test_v2_{args.category.replace('.', '_')}.jsonl"

    for i, paper in enumerate(papers):
        title = paper["title"]
        content = f"Abstract: {paper['abstract']}\n\nFull Paper Text:\n{paper['full_text']}"
        print(f"\n[{i+1}/{len(papers)}] {title[:60]}")

        # V2 (extended prompt)
        r2 = await generate_summary(title, content, EXTENDED_IMPACT_PROMPT_V2, sem)
        if r2.get("ratings"):
            print(f"  V2: score={r2['ratings'].get('score')} novelty={r2['ratings'].get('novelty')} "
                  f"difficulty={r2['ratings'].get('difficulty')} surprisingness={r2['ratings'].get('surprisingness')} "
                  f"reproducibility={r2['ratings'].get('reproducibility')} translational={r2['ratings'].get('translational_potential')}")
            # Show reasoning
            for dim in ["difficulty", "surprisingness", "reproducibility", "translational_potential"]:
                reason = r2["ratings"].get(f"{dim}_reason", "")
                if reason:
                    print(f"       {dim}: {reason[:80]}")
        else:
            print(f"  V2: {'ERROR: ' + r2.get('error', '')[:60] if r2.get('error') else 'no ratings parsed'}")

        with open(v2_output, "a") as f:
            f.write(json.dumps({"paper_id": paper["id"], "title": title, "prompt": "v2", **r2}) + "\n")

        # V1 (production prompt) for comparison
        if not args.only_v2:
            r1 = await generate_summary(title, content, IMPACT_ASSESSMENT_PROMPT, sem)
            if r1.get("ratings"):
                print(f"  V1: score={r1['ratings'].get('score')} novelty={r1['ratings'].get('novelty')}")
            else:
                print(f"  V1: {'ERROR: ' + r1.get('error', '')[:60] if r1.get('error') else 'no ratings parsed'}")

            with open(v1_output, "a") as f:
                f.write(json.dumps({"paper_id": paper["id"], "title": title, "prompt": "v1", **r1}) + "\n")

    # Summary comparison
    if not args.only_v2:
        print(f"\n{'='*60}")
        print("Score comparison (V1 vs V2):")
        v1_scores = []
        v2_scores = []
        for line in open(v1_output):
            r = json.loads(line)
            if r.get("ratings", {}).get("score"):
                v1_scores.append(r["ratings"]["score"])
        for line in open(v2_output):
            r = json.loads(line)
            if r.get("ratings", {}).get("score"):
                v2_scores.append(r["ratings"]["score"])
        if v1_scores and v2_scores:
            import numpy as np
            v1 = np.array(v1_scores)
            v2 = np.array(v2_scores[:len(v1_scores)])
            print(f"  V1 mean={v1.mean():.2f} std={v1.std():.2f}")
            print(f"  V2 mean={v2.mean():.2f} std={v2.std():.2f}")
            if len(v1) == len(v2):
                diff = v2 - v1
                print(f"  Mean shift: {diff.mean():+.2f} (positive = V2 scores higher)")


if __name__ == "__main__":
    asyncio.run(main())
