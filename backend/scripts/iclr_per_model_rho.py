"""Per-model Spearman rho for ICLR 2026 validation tournament.

For each of the 3 judge models (GPT-5.4, Claude Opus 4.6, Gemini 3 Pro Preview),
this script:
  1. Filters the completed non-failed matches to that model only
  2. Fits a TrueSkill rating per paper from that model's wins/losses
  3. Computes Spearman rho vs h1_avg_rating (ground truth — avg of reviewer scores)
Also reports Kendall tau and the pooled (all-3-models) baseline.
"""
import asyncio
import os
import sys
from collections import defaultdict

import trueskill
from scipy.stats import spearmanr, kendalltau
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv()

DATASET_ID = "iclr-2026-validation"
MODELS = ["gpt-5.4", "claude-opus-4-6", "gemini-3-pro-preview"]


async def load_matches(db, model_filter=None):
    """Return list of (winner_id, loser_id) tuples from completed non-failed matches."""
    q = {"dataset_id": DATASET_ID, "completed": True, "failed": {"$ne": True},
         "winner_id": {"$exists": True, "$ne": None}}
    if model_filter:
        q["model_used.model"] = model_filter
    out = []
    async for m in db.validation_matches.find(
        q,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
    ):
        w = m["winner_id"]
        loser = m["paper1_id"] if w == m["paper2_id"] else m["paper2_id"]
        out.append((w, loser))
    return out


async def load_ground_truth(db):
    """Return {paper_id: h1_avg_rating} for papers with a rating."""
    gt = {}
    async for p in db.validation_papers.find(
        {"dataset_id": DATASET_ID, "h1_avg_rating": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "h1_avg_rating": 1}
    ):
        try:
            v = float(p["h1_avg_rating"])
            gt[p["id"]] = v
        except (TypeError, ValueError):
            pass
    return gt


def fit_trueskill(matches, iterations: int = 1):
    """Run TrueSkill over a list of (winner, loser) pairs.

    Each match updates both paper ratings. One pass through all matches is
    normally sufficient when each pair is judged roughly once; extra iterations
    can smooth convergence but don't change the ordering materially.
    """
    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = defaultdict(env.create_rating)
    for _ in range(iterations):
        for winner, loser in matches:
            r_w = ratings[winner]
            r_l = ratings[loser]
            new_w, new_l = env.rate_1vs1(r_w, r_l)
            ratings[winner] = new_w
            ratings[loser] = new_l
    # Conservative score: mu - 3*sigma (matches the production formula)
    return {pid: r.mu - 3 * r.sigma for pid, r in ratings.items()}


def correlate(scores, gt):
    """Spearman rho + Kendall tau between fit scores and ground-truth ratings,
    restricted to papers present in both."""
    shared = sorted(set(scores.keys()) & set(gt.keys()))
    if len(shared) < 30:
        return None, None, len(shared)
    xs = [scores[p] for p in shared]
    ys = [gt[p] for p in shared]
    rho, _ = spearmanr(xs, ys)
    tau, _ = kendalltau(xs, ys)
    return rho, tau, len(shared)


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        gt = await load_ground_truth(db)
        print(f"Ground-truth papers with h1_avg_rating: {len(gt):,}")

        rows = []

        # Pooled (all 3 models)
        all_matches = await load_matches(db)
        pooled_scores = fit_trueskill(all_matches)
        rho, tau, n = correlate(pooled_scores, gt)
        rows.append(("POOLED (all 3)", len(all_matches), len(pooled_scores), n, rho, tau))

        # Per-model
        for m in MODELS:
            ms = await load_matches(db, model_filter=m)
            scores = fit_trueskill(ms)
            rho, tau, n = correlate(scores, gt)
            rows.append((m, len(ms), len(scores), n, rho, tau))

        # Print table
        print()
        print(f"{'Source':30}  {'Matches':>9}  {'Papers':>7}  {'Overlap':>8}  {'Spearman':>9}  {'Kendall':>8}")
        print("-" * 86)
        for src, nm, np_, n, rho, tau in rows:
            rho_s = f"{rho:+.4f}" if rho is not None else "  n/a"
            tau_s = f"{tau:+.4f}" if tau is not None else "  n/a"
            print(f"{src:30}  {nm:>9,}  {np_:>7,}  {n:>8,}  {rho_s:>9}  {tau_s:>8}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
