"""GPT-5.2 positional-bias controlled A/B test.

Hypothesis: GPT-5.2's live-tournament Pos1 rate of ~35% (W14+) is driven by
infrastructure pressure (scheduler thread-pool starvation + LLM proxy load)
rather than a genuine shift in the model's content preferences.

Design:
1. Harvest recent GPT-5.2 pairs from production (kurate.org public API).
2. Fetch each paper's abstract + Claude Opus 4.6 thinking summary.
3. For each pair, call compare_papers twice with model_override=gpt-5.2:
     once with paper A in position 1, once with paper B in position 1.
4. Run at low concurrency from this pod (no scheduler queueing).
5. Report pos1 rate, per-pair consistency, and direction of inconsistencies.

Usage:
    cd /app/backend && python3 scripts/positional_ab_gpt52.py \
        --n-pairs 500 --concurrency 5 --since 2026-04-01

Output: prints aggregate + writes JSONL to /app/backend/data/positional_ab_gpt52.jsonl
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

# Ensure backend modules importable when run from /app/backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.llm import compare_papers  # noqa: E402
from core.config import logger  # noqa: E402


PRODUCTION_BASE = "https://kurate.org"
CATEGORIES = [
    "cs.LG", "cs.AI", "cs.CL", "cs.CV", "cs.RO",
    "stat.ML", "cs.NE", "cs.IR", "cs.HC", "cs.CY",
    "q-bio.BM", "q-bio.GN", "q-bio.NC",
    "physics.optics", "astro-ph.GA", "cond-mat.soft", "math.OC",
]

SUM_KEY = "anthropic:claude-opus-4-6:thinking"


async def _http_get(client: httpx.AsyncClient, path: str, params: Optional[dict] = None, retries: int = 5):
    for attempt in range(retries):
        try:
            r = await client.get(f"{PRODUCTION_BASE}{path}", params=params, timeout=30)
            if r.status_code == 429:
                # Respect rate limit with exponential backoff
                wait = 2 ** (attempt + 1)
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                logger.warning(f"GET {path} failed after {retries} attempts: {str(e)[:100]}")
                return None
            await asyncio.sleep(1.5 ** attempt)
    return None


async def harvest_pairs(n_pairs: int, since: str) -> list[tuple[str, str]]:
    """Scan production leaderboards → each paper → its matches → collect GPT-5.2 pairs."""
    seen_pairs: set[tuple[str, str]] = set()
    candidate_pairs: list[tuple[str, str]] = []

    async with httpx.AsyncClient() as client:
        for category in CATEGORIES:
            if len(candidate_pairs) >= n_pairs * 3:
                break
            lb = await _http_get(client, "/api/leaderboard", {"category": category, "limit": 150})
            if not lb:
                continue
            paper_ids = [row.get("id") for row in lb.get("leaderboard", []) if row.get("id")]
            # Shuffle for paper-id diversity
            random.shuffle(paper_ids)

            # Fetch match history for a subset — don't exhaust the API
            for pid in paper_ids[:60]:
                if len(candidate_pairs) >= n_pairs * 3:
                    break
                detail = await _http_get(client, f"/api/papers/{pid}")
                await asyncio.sleep(0.15)
                if not detail:
                    continue
                for m in detail.get("matches", []):
                    mu = m.get("model_used") or {}
                    if mu.get("model") != "gpt-5.2":
                        continue
                    if m.get("failed"):
                        continue
                    if (m.get("created_at") or "") < since:
                        continue
                    opp = m.get("opponent_id")
                    if not opp:
                        continue
                    key = tuple(sorted([pid, opp]))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    candidate_pairs.append((pid, opp))

    print(f"Harvested {len(candidate_pairs)} unique GPT-5.2 pairs from production")
    if len(candidate_pairs) > n_pairs:
        candidate_pairs = random.sample(candidate_pairs, n_pairs)
    return candidate_pairs


async def fetch_paper_content(client: httpx.AsyncClient, paper_id: str) -> Optional[dict]:
    """Fetch a paper's abstract + Claude thinking summary from production."""
    d = await _http_get(client, f"/api/papers/{paper_id}")
    if not d:
        return None
    p = d.get("paper") or {}
    summaries = p.get("summaries") or {}
    summary = summaries.get(SUM_KEY, "")
    if not summary or len(summary) < 50:
        return None
    return {
        "id": p.get("id", paper_id),
        "title": p.get("title", ""),
        "abstract": p.get("abstract", ""),
        "ai_impact_summary": summary,
    }


async def run_ab(
    pairs: list[tuple[str, str]],
    concurrency: int,
    model_override: dict,
    out_path: Path,
    prompt_config: Optional[dict] = None,
) -> dict:
    print(f"\nFetching paper content for {len(pairs)} pairs...")
    paper_cache: dict[str, dict] = {}
    async with httpx.AsyncClient() as client:
        unique_ids = list({pid for pair in pairs for pid in pair})
        # Sequential fetches with small delay to respect rate limit (production returns 429 under concurrent load)
        for i, pid in enumerate(unique_ids):
            doc = await fetch_paper_content(client, pid)
            if doc:
                paper_cache[pid] = doc
            if i % 50 == 49:
                print(f"  fetched {i+1}/{len(unique_ids)} papers ({len(paper_cache)} with Claude summary)")
            await asyncio.sleep(0.15)  # ~6 req/s — below typical rate limits

    usable = [(a, b) for a, b in pairs if a in paper_cache and b in paper_cache]
    print(f"Usable pairs (both papers have Claude thinking summary): {len(usable)}/{len(pairs)}")
    if not usable:
        return {"error": "no usable pairs"}

    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    t_start = time.time()
    done_count = 0

    async def _judge_once(p_first: dict, p_second: dict):
        async with sem:
            try:
                res = await asyncio.wait_for(
                    compare_papers(
                        p_first, p_second,
                        prompt_config=prompt_config,
                        content_mode="abstract_plus_summary",
                        model_override=model_override,
                    ),
                    timeout=120,
                )
                return p_first["id"] if res.get("winner") == "paper1" else p_second["id"]
            except Exception as e:
                logger.warning(f"judge failed {p_first['id']} vs {p_second['id']}: {str(e)[:120]}")
                return None

    async def _run_pair(idx: int, a_id: str, b_id: str):
        nonlocal done_count
        a = paper_cache[a_id]
        b = paper_cache[b_id]
        win_ab, win_ba = await asyncio.gather(
            _judge_once(a, b),
            _judge_once(b, a),
        )
        row = {
            "idx": idx,
            "paper_a_id": a_id,
            "paper_b_id": b_id,
            "ab_winner": win_ab,
            "ba_winner": win_ba,
            "ab_pos1_win": (win_ab == a_id) if win_ab else None,
            "ba_pos1_win": (win_ba == b_id) if win_ba else None,
            "consistent": (win_ab == win_ba) if (win_ab and win_ba) else None,
        }
        results.append(row)
        done_count += 1
        if done_count % 25 == 0 or done_count == len(usable):
            elapsed = time.time() - t_start
            rate = done_count / elapsed if elapsed > 0 else 0
            eta_min = (len(usable) - done_count) / rate / 60 if rate > 0 else 0
            print(f"  progress: {done_count}/{len(usable)} pairs  ({rate:.1f} pair/s, ETA {eta_min:.1f} min)")

    await asyncio.gather(*[_run_pair(i, a, b) for i, (a, b) in enumerate(usable)])

    # Write per-pair results
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Aggregate
    pos1_wins = pos1_total = 0
    consistent = consistent_total = 0
    toward_first = toward_second = 0
    calls_failed = 0

    for r in results:
        for k in ("ab_pos1_win", "ba_pos1_win"):
            v = r[k]
            if v is None:
                calls_failed += 1
            else:
                pos1_total += 1
                if v:
                    pos1_wins += 1
        c = r["consistent"]
        if c is not None:
            consistent_total += 1
            if c:
                consistent += 1
            else:
                ab_p1 = r["ab_pos1_win"]
                ba_p1 = r["ba_pos1_win"]
                if ab_p1 and ba_p1:
                    toward_first += 1
                elif ab_p1 is False and ba_p1 is False:
                    toward_second += 1

    summary = {
        "n_pairs_judged": len(results),
        "calls_completed": pos1_total,
        "calls_failed": calls_failed,
        "pos1_rate_pct": round(pos1_wins / pos1_total * 100, 2) if pos1_total else None,
        "consistency_rate_pct": round(consistent / consistent_total * 100, 2) if consistent_total else None,
        "inconsistent_pairs": consistent_total - consistent,
        "inconsistent_toward_first_pct": round(toward_first / consistent_total * 100, 2) if consistent_total else None,
        "inconsistent_toward_second_pct": round(toward_second / consistent_total * 100, 2) if consistent_total else None,
        "production_baseline_pos1_rate_pct_w14_plus": 35.5,
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pairs", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--since", type=str, default="2026-04-01")
    ap.add_argument("--provider", type=str, default="openai")
    ap.add_argument("--model", type=str, default="gpt-5.2")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--prompt-file", type=str, default=None,
                    help="Path to JSON file with {system_prompt, user_prompt}. "
                         "If not provided, uses DEFAULT_EVALUATION_PROMPT.")
    args = ap.parse_args()

    random.seed(args.seed)

    prompt_config = None
    if args.prompt_file:
        with open(args.prompt_file) as f:
            prompt_config = json.load(f)
        print(f"Loaded custom prompt_config from {args.prompt_file} "
              f"(system={len(prompt_config['system_prompt'])}ch, user={len(prompt_config['user_prompt'])}ch)")

    out_path = Path(__file__).resolve().parent.parent / "data" / "positional_ab_gpt52.jsonl"

    async def _main():
        t0 = time.time()
        print(f"Harvesting pairs (target {args.n_pairs}, since {args.since})...")
        pairs = await harvest_pairs(args.n_pairs, args.since)
        if not pairs:
            print("No pairs harvested — aborting")
            return
        model_override = {"provider": args.provider, "model": args.model}
        summary = await run_ab(pairs, args.concurrency, model_override, out_path, prompt_config)
        print("\n" + "=" * 70)
        print("RESULT")
        print("=" * 70)
        print(json.dumps(summary, indent=2))
        print("=" * 70)
        print(f"Elapsed: {(time.time()-t0)/60:.1f} min")
        print(f"Per-pair JSONL: {out_path}")

    asyncio.run(_main())


if __name__ == "__main__":
    main()
