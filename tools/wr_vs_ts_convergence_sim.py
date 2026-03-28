"""
WR vs TrueSkill Convergence Simulation
=======================================
Replays actual match history incrementally and measures how quickly
each scoring method's ranking converges to the final ranking.

Metrics:
1. Spearman rank correlation with final ranking (overall stability)
2. Top-K agreement (do the top papers stabilize faster?)
3. Average rank displacement (how much does a paper's rank jump per match?)
4. CI convergence (when does the median paper reach target CI?)
"""

import asyncio
import math
import sys
from collections import defaultdict
from datetime import datetime

import motor.motor_asyncio
import trueskill
from scipy import stats as scipy_stats
import numpy as np


MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"
SCORE_BASE = 1200
TS_SCALE = 10.0
WILSON_Z = scipy_stats.norm.ppf(0.975)


def wilson_margin_pct(wins, comparisons):
    if comparisons == 0:
        return 100.0
    n = comparisons
    p_hat = wins / n
    denom = 1 + WILSON_Z**2 / n
    centre = (p_hat + WILSON_Z**2 / (2 * n)) / denom
    spread = WILSON_Z * math.sqrt((p_hat * (1 - p_hat) + WILSON_Z**2 / (4 * n)) / n) / denom
    lower = max(0, centre - spread)
    upper = min(1, centre + spread)
    return round((upper - lower) * 100, 1)


def wr_score(wins, comparisons):
    if comparisons == 0:
        return SCORE_BASE
    p_reg = (wins + 0.5) / (comparisons + 1.0)
    p_reg = max(0.02, min(0.98, p_reg))
    return round(400.0 * math.log10(p_reg / (1.0 - p_reg)) + SCORE_BASE)


def ts_elo(mu, sigma):
    conservative = mu - 3 * sigma
    return round(conservative * TS_SCALE + SCORE_BASE)


def spearman_corr(ranking_a, ranking_b, paper_ids):
    """Compute Spearman rank correlation between two ranking dicts."""
    common = [pid for pid in paper_ids if pid in ranking_a and pid in ranking_b]
    if len(common) < 5:
        return 0.0
    a = [ranking_a[pid] for pid in common]
    b = [ranking_b[pid] for pid in common]
    rho, _ = scipy_stats.spearmanr(a, b)
    return float(rho) if not np.isnan(rho) else 0.0


def top_k_overlap(ranking_a, ranking_b, k):
    """Fraction of top-K papers that are the same in both rankings."""
    top_a = set(sorted(ranking_a, key=ranking_a.get)[:k])
    top_b = set(sorted(ranking_b, key=ranking_b.get)[:k])
    if not top_a or not top_b:
        return 0.0
    return len(top_a & top_b) / k


async def run_simulation(category="cs.RO"):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Load all completed matches for the category, sorted by timestamp
    print(f"Loading matches for {category}...")
    matches = []
    async for m in db.matches.find(
        {
            "completed": True,
            "failed": {"$ne": True},
            "primary_category": category,
            "mode": {"$exists": False},
        },
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
         "completed_at": 1, "created_at": 1},
    ).sort("completed_at", 1):
        matches.append(m)

    print(f"Loaded {len(matches)} matches")

    # Get all paper IDs that appear in matches
    paper_ids = set()
    for m in matches:
        paper_ids.add(m["paper1_id"])
        paper_ids.add(m["paper2_id"])
    paper_ids = sorted(paper_ids)
    print(f"Papers involved: {len(paper_ids)}")

    # --- Compute FINAL rankings (ground truth after all matches) ---
    wr_wins = defaultdict(int)
    wr_comps = defaultdict(int)
    ts_env = trueskill.TrueSkill(draw_probability=0.0)
    ts_ratings = {pid: ts_env.create_rating() for pid in paper_ids}

    for m in matches:
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        wr_comps[p1] += 1
        wr_comps[p2] += 1
        if w == p1:
            wr_wins[p1] += 1
        elif w == p2:
            wr_wins[p2] += 1

        if w == p1:
            ts_ratings[p1], ts_ratings[p2] = trueskill.rate_1vs1(
                ts_ratings[p1], ts_ratings[p2], env=ts_env)
        elif w == p2:
            ts_ratings[p2], ts_ratings[p1] = trueskill.rate_1vs1(
                ts_ratings[p2], ts_ratings[p1], env=ts_env)

    # Final WR ranking
    final_wr_scores = {pid: wr_score(wr_wins[pid], wr_comps[pid]) for pid in paper_ids}
    final_wr_ranking = {}
    for rank, pid in enumerate(sorted(paper_ids, key=lambda p: final_wr_scores[p], reverse=True), 1):
        final_wr_ranking[pid] = rank

    # Final TS ranking
    final_ts_scores = {pid: ts_elo(ts_ratings[pid].mu, ts_ratings[pid].sigma) for pid in paper_ids}
    final_ts_ranking = {}
    for rank, pid in enumerate(sorted(paper_ids, key=lambda p: final_ts_scores[p], reverse=True), 1):
        final_ts_ranking[pid] = rank

    # WR-TS final ranking correlation
    rho_wr_ts = spearman_corr(final_wr_ranking, final_ts_ranking, paper_ids)
    print(f"Final WR-TS ranking Spearman: {rho_wr_ts:.3f}")
    print(f"Total matches per paper (avg): {sum(wr_comps.values()) / len(paper_ids):.1f}")
    print()

    # --- Incremental replay ---
    inc_wr_wins = defaultdict(int)
    inc_wr_comps = defaultdict(int)
    inc_ts_env = trueskill.TrueSkill(draw_probability=0.0)
    inc_ts_ratings = {pid: inc_ts_env.create_rating() for pid in paper_ids}

    # Checkpoint interval: measure every N matches
    total = len(matches)
    # Use percentage-based checkpoints for smoother curves
    checkpoints_pct = list(range(1, 101, 1))  # every 1%
    checkpoint_indices = sorted(set(max(1, int(total * p / 100)) for p in checkpoints_pct))

    results = []

    for i, m in enumerate(matches):
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        inc_wr_comps[p1] += 1
        inc_wr_comps[p2] += 1
        if w == p1:
            inc_wr_wins[p1] += 1
        elif w == p2:
            inc_wr_wins[p2] += 1

        if w == p1:
            inc_ts_ratings[p1], inc_ts_ratings[p2] = trueskill.rate_1vs1(
                inc_ts_ratings[p1], inc_ts_ratings[p2], env=inc_ts_env)
        elif w == p2:
            inc_ts_ratings[p2], inc_ts_ratings[p1] = trueskill.rate_1vs1(
                inc_ts_ratings[p2], inc_ts_ratings[p1], env=inc_ts_env)

        match_idx = i + 1
        if match_idx not in checkpoint_indices:
            continue

        # Papers that have been seen so far
        seen = [pid for pid in paper_ids if inc_wr_comps[pid] > 0]
        if len(seen) < 10:
            continue

        # Current WR ranking (among seen papers only)
        cur_wr_scores = {pid: wr_score(inc_wr_wins[pid], inc_wr_comps[pid]) for pid in seen}
        cur_wr_ranking = {}
        for rank, pid in enumerate(sorted(seen, key=lambda p: cur_wr_scores[p], reverse=True), 1):
            cur_wr_ranking[pid] = rank

        # Current TS ranking
        cur_ts_scores = {pid: ts_elo(inc_ts_ratings[pid].mu, inc_ts_ratings[pid].sigma) for pid in seen}
        cur_ts_ranking = {}
        for rank, pid in enumerate(sorted(seen, key=lambda p: cur_ts_scores[p], reverse=True), 1):
            cur_ts_ranking[pid] = rank

        # Correlate with FINAL rankings
        wr_rho = spearman_corr(cur_wr_ranking, final_wr_ranking, seen)
        ts_rho = spearman_corr(cur_ts_ranking, final_ts_ranking, seen)
        # Cross: how well does current TS predict final WR? (and vice versa)
        ts_predicts_wr = spearman_corr(cur_ts_ranking, final_wr_ranking, seen)

        # Top-K overlap with final
        k = min(10, len(seen) // 5)
        if k < 3:
            k = 3
        wr_topk = top_k_overlap(cur_wr_ranking, final_wr_ranking, k)
        ts_topk = top_k_overlap(cur_ts_ranking, final_ts_ranking, k)

        # Median CI
        wr_margins = [wilson_margin_pct(inc_wr_wins[pid], inc_wr_comps[pid]) for pid in seen]
        ts_sigmas = [inc_ts_ratings[pid].sigma for pid in seen]
        ts_cis = [round(1.96 * s * TS_SCALE) for s in ts_sigmas]

        median_wr_ci = float(np.median(wr_margins))
        median_ts_ci = float(np.median(ts_cis))

        avg_matches_per_paper = sum(inc_wr_comps[pid] for pid in seen) / len(seen)

        pct = round(match_idx / total * 100, 1)

        results.append({
            "pct": pct,
            "match_idx": match_idx,
            "papers_seen": len(seen),
            "avg_mpp": round(avg_matches_per_paper, 1),
            "wr_rho": round(wr_rho, 4),
            "ts_rho": round(ts_rho, 4),
            "ts_predicts_wr": round(ts_predicts_wr, 4),
            "wr_topk": round(wr_topk, 3),
            "ts_topk": round(ts_topk, 3),
            "k": k,
            "median_wr_ci": round(median_wr_ci, 1),
            "median_ts_ci": round(median_ts_ci),
        })

    # --- Print results ---
    print("=" * 110)
    print(f"{'%':>5} {'Match#':>7} {'Papers':>7} {'Avg M/P':>8} {'WR rho':>8} {'TS rho':>8} {'TS->WR':>8} {'WR top':>7} {'TS top':>7} {'WR CI':>7} {'TS CI':>7}")
    print("=" * 110)
    # Print every 5% for readability
    for r in results:
        if r["pct"] % 5 == 0 or r == results[-1] or r == results[0]:
            print(f"{r['pct']:>4.0f}% {r['match_idx']:>7} {r['papers_seen']:>7} {r['avg_mpp']:>8.1f} "
                  f"{r['wr_rho']:>8.4f} {r['ts_rho']:>8.4f} {r['ts_predicts_wr']:>8.4f} "
                  f"{r['wr_topk']:>6.1%} {r['ts_topk']:>6.1%} "
                  f"±{r['median_wr_ci']:>5.1f}% ±{r['median_ts_ci']:>4}pts")

    # --- Key analysis: When does each method reach target correlation? ---
    print()
    print("=" * 80)
    print("CONVERGENCE MILESTONES")
    print("=" * 80)

    for target_rho in [0.80, 0.85, 0.90, 0.95, 0.98]:
        wr_match = None
        ts_match = None
        for r in results:
            if wr_match is None and r["wr_rho"] >= target_rho:
                wr_match = r
            if ts_match is None and r["ts_rho"] >= target_rho:
                ts_match = r
        
        wr_pct = f"{wr_match['pct']:.0f}% ({wr_match['avg_mpp']:.0f} m/p)" if wr_match else "never"
        ts_pct = f"{ts_match['pct']:.0f}% ({ts_match['avg_mpp']:.0f} m/p)" if ts_match else "never"
        
        if wr_match and ts_match:
            savings = round((1 - ts_match['avg_mpp'] / wr_match['avg_mpp']) * 100, 1)
            ratio = round(wr_match['avg_mpp'] / ts_match['avg_mpp'], 2)
        else:
            savings = "N/A"
            ratio = "N/A"

        print(f"  rho >= {target_rho}:  WR at {wr_pct:>25}  |  TS at {ts_pct:>25}  |  savings: {savings}%  (TS needs {ratio}x fewer matches)")

    # --- Top-K convergence ---
    print()
    print("TOP-K CONVERGENCE MILESTONES")
    print("-" * 80)
    for target_topk in [0.6, 0.7, 0.8, 0.9, 1.0]:
        wr_match = None
        ts_match = None
        for r in results:
            if wr_match is None and r["wr_topk"] >= target_topk:
                wr_match = r
            if ts_match is None and r["ts_topk"] >= target_topk:
                ts_match = r
        
        wr_pct = f"{wr_match['pct']:.0f}% ({wr_match['avg_mpp']:.0f} m/p)" if wr_match else "never"
        ts_pct = f"{ts_match['pct']:.0f}% ({ts_match['avg_mpp']:.0f} m/p)" if ts_match else "never"
        
        if wr_match and ts_match:
            savings = round((1 - ts_match['avg_mpp'] / wr_match['avg_mpp']) * 100, 1)
        else:
            savings = "N/A"

        k = results[0]["k"] if results else "?"
        print(f"  Top-{k} overlap >= {target_topk:.0%}:  WR at {wr_pct:>25}  |  TS at {ts_pct:>25}  |  savings: {savings}%")

    # --- Efficiency at fixed match budget ---
    print()
    print("RANKING QUALITY AT FIXED MATCH BUDGETS")
    print("-" * 80)
    for target_mpp in [5, 10, 15, 20, 30, 40]:
        closest = None
        for r in results:
            if closest is None or abs(r["avg_mpp"] - target_mpp) < abs(closest["avg_mpp"] - target_mpp):
                closest = r
        if closest:
            diff = closest["ts_rho"] - closest["wr_rho"]
            print(f"  At ~{target_mpp} matches/paper: WR rho={closest['wr_rho']:.3f}  TS rho={closest['ts_rho']:.3f}  "
                  f"delta={diff:+.3f}  WR top-K={closest['wr_topk']:.0%}  TS top-K={closest['ts_topk']:.0%}")

    client.close()
    return results


if __name__ == "__main__":
    cat = sys.argv[1] if len(sys.argv) > 1 else "cs.RO"
    asyncio.run(run_simulation(cat))
