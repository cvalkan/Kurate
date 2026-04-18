"""Deeper analysis of why Claude Opus 4.6 underperforms on ICLR 2026.

Checks:
  1. Decisiveness / tie rates per model
  2. Does each model see pairs with similar rating-gap distribution? (fairness)
  3. Per-score-bucket accuracy (is Claude bad on mid-range vs extremes?)
  4. Pairwise agreement with ground-truth on "easy pairs" (large rating gap)
  5. Position bias per model (paper1 vs paper2 win rate)
  6. Failure-retry pattern: are Claude's completed matches biased by which pairs got through?

Also: subsampled "equal-density" pooled rho — does the pooled ensemble
actually add signal, or is it just more data?
"""
import asyncio
import os
import random
from collections import defaultdict

import trueskill
from scipy.stats import spearmanr
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv()

DATASET_ID = "iclr-2026-validation"
MODELS = ["gpt-5.4", "claude-opus-4-6", "gemini-3-pro-preview"]


async def load_full(db):
    """Load matches with model + gt rating-gap info."""
    gt = {}
    async for p in db.validation_papers.find(
        {"dataset_id": DATASET_ID, "h1_avg_rating": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "h1_avg_rating": 1}
    ):
        try:
            gt[p["id"]] = float(p["h1_avg_rating"])
        except Exception:
            pass

    matches = []
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET_ID, "completed": True, "failed": {"$ne": True},
         "winner_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}
    ):
        model = (m.get("model_used") or {}).get("model", "?")
        matches.append({
            "p1": m["paper1_id"],
            "p2": m["paper2_id"],
            "w": m["winner_id"],
            "model": model,
        })
    return matches, gt


def fit_ts(pairs):
    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = defaultdict(env.create_rating)
    for winner, loser in pairs:
        nw, nl = env.rate_1vs1(ratings[winner], ratings[loser])
        ratings[winner] = nw
        ratings[loser] = nl
    return {pid: r.mu - 3 * r.sigma for pid, r in ratings.items()}


def rho_against_gt(scores, gt):
    shared = sorted(set(scores) & set(gt))
    if len(shared) < 30:
        return None, len(shared)
    xs = [scores[p] for p in shared]
    ys = [gt[p] for p in shared]
    rho, _ = spearmanr(xs, ys)
    return rho, len(shared)


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        all_matches, gt = await load_full(db)
        print(f"Loaded {len(all_matches):,} completed matches · {len(gt):,} GT-rated papers\n")

        # Bucket matches per model
        per_model = defaultdict(list)
        for m in all_matches:
            per_model[m["model"]].append(m)

        # ── 1. Rating-gap distribution per model ────────────────────────────
        print("── Test 1: rating-gap distribution per model ──")
        print("  (Higher abs-gap = easier pair to judge; should be ~equal across models)")
        print(f"  {'model':30} {'N':>7} {'|Δrating| mean':>14} {'|Δrating| p50':>14}")
        for model in MODELS + ["POOLED"]:
            ms = all_matches if model == "POOLED" else per_model[model]
            gaps = []
            for m in ms:
                r1, r2 = gt.get(m["p1"]), gt.get(m["p2"])
                if r1 is not None and r2 is not None:
                    gaps.append(abs(r1 - r2))
            if not gaps:
                continue
            gaps.sort()
            mean = sum(gaps) / len(gaps)
            p50 = gaps[len(gaps) // 2]
            print(f"  {model:30} {len(gaps):>7,} {mean:>14.3f} {p50:>14.3f}")

        # ── 2. Easy-pair accuracy: large rating-gap pairs only ──────────────
        print("\n── Test 2: per-model accuracy on 'easy' pairs (|Δrating| ≥ 1.0) ──")
        print(f"  {'model':30} {'easy N':>7} {'correct':>8} {'accuracy':>10}")
        for model in MODELS:
            correct, n = 0, 0
            for m in per_model[model]:
                r1, r2 = gt.get(m["p1"]), gt.get(m["p2"])
                if r1 is None or r2 is None:
                    continue
                if abs(r1 - r2) < 1.0:
                    continue
                n += 1
                better_id = m["p1"] if r1 > r2 else m["p2"]
                if m["w"] == better_id:
                    correct += 1
            if n:
                print(f"  {model:30} {n:>7,} {correct:>8,} {100*correct/n:>9.2f}%")

        # ── 3. Close-pair accuracy ──────────────────────────────────────────
        print("\n── Test 3: accuracy on 'hard' pairs (|Δrating| < 0.5) ──")
        print(f"  {'model':30} {'hard N':>7} {'correct':>8} {'accuracy':>10}")
        for model in MODELS:
            correct, n = 0, 0
            for m in per_model[model]:
                r1, r2 = gt.get(m["p1"]), gt.get(m["p2"])
                if r1 is None or r2 is None:
                    continue
                if abs(r1 - r2) >= 0.5 or r1 == r2:
                    continue
                n += 1
                better_id = m["p1"] if r1 > r2 else m["p2"]
                if m["w"] == better_id:
                    correct += 1
            if n:
                print(f"  {model:30} {n:>7,} {correct:>8,} {100*correct/n:>9.2f}%")

        # ── 4. Position bias ────────────────────────────────────────────────
        print("\n── Test 4: position bias per model (paper1 win rate — 50% is unbiased) ──")
        print(f"  {'model':30} {'N':>7} {'paper1 wins':>12} {'rate':>8}")
        for model in MODELS:
            p1_wins, n = 0, 0
            for m in per_model[model]:
                n += 1
                if m["w"] == m["p1"]:
                    p1_wins += 1
            if n:
                print(f"  {model:30} {n:>7,} {p1_wins:>12,} {100*p1_wins/n:>7.2f}%")

        # ── 5. Score-bucket accuracy (quality tier by GT rating) ────────────
        print("\n── Test 5: per-model accuracy by winner's quality bucket ──")
        print("  (Buckets are the winner's h1_avg_rating tier)")
        BUCKETS = [(0, 3.5, "bottom"), (3.5, 5.0, "mid-low"),
                   (5.0, 6.5, "mid-high"), (6.5, 10, "top")]
        for model in MODELS:
            print(f"  {model}")
            for lo, hi, label in BUCKETS:
                correct, n = 0, 0
                for m in per_model[model]:
                    r1, r2 = gt.get(m["p1"]), gt.get(m["p2"])
                    if r1 is None or r2 is None:
                        continue
                    true_winner_rating = max(r1, r2)
                    if not (lo <= true_winner_rating < hi):
                        continue
                    n += 1
                    better_id = m["p1"] if r1 > r2 else m["p2"]
                    if m["w"] == better_id:
                        correct += 1
                if n:
                    print(f"    {label:10} [{lo}-{hi}) : n={n:>5,}   accuracy={100*correct/n:.2f}%")

        # ── 6. Subsampled equal-density pooled rho ──────────────────────────
        print("\n── Test 6: is the POOLED lift just 'more data'? ──")
        print("  (Subsample pooled matches to match single-model match count, re-run, average 5 seeds)")
        target_n = min(len(per_model[m]) for m in MODELS)
        print(f"  Subsampling to {target_n:,} matches (size of smallest per-model corpus)")
        rhos = []
        for seed in range(5):
            rng = random.Random(seed)
            subset = rng.sample(all_matches, target_n)
            pairs = [(m["w"], m["p2"] if m["w"] == m["p1"] else m["p1"]) for m in subset]
            scores = fit_ts(pairs)
            rho, _ = rho_against_gt(scores, gt)
            rhos.append(rho)
        mean_rho = sum(rhos) / len(rhos)
        print(f"  POOLED @ N={target_n:,}:  "
              f"mean Spearman = {mean_rho:+.4f}   "
              f"(seeds: {', '.join(f'{r:+.4f}' for r in rhos)})")
        # Single-model baselines at same match count
        for model in MODELS:
            ms = per_model[model]
            pairs = [(m["w"], m["p2"] if m["w"] == m["p1"] else m["p1"]) for m in ms]
            scores = fit_ts(pairs)
            rho, n = rho_against_gt(scores, gt)
            print(f"  {model:30}  N={len(ms):,}  Spearman = {rho:+.4f}")

        # ── 7. Model tie / draw rate ────────────────────────────────────────
        # Each model always picks a winner (no draws allowed in prompt), but
        # check if winner_id distribution reveals any tie-breaking quirks.
        print("\n── Test 7: sanity — every match has a winner (no ties in data) ──")
        for model in MODELS:
            no_winner = sum(1 for m in per_model[model] if not m["w"])
            print(f"  {model}: {no_winner} matches without winner_id")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
