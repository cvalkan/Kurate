"""
Multi-category WR vs TS efficiency comparison.
For each category, measures: at what match-count does each method reach
stable rankings (rho >= threshold with final ranking)?

Also includes a "controlled" simulation that only measures papers that
existed from the start (no mid-tournament additions confounding results).
"""
import asyncio
import math
from collections import defaultdict
import motor.motor_asyncio
import trueskill
from scipy import stats as scipy_stats
import numpy as np

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"
SCORE_BASE = 1200
TS_SCALE = 10.0


def wr_score(wins, comps):
    if comps == 0: return SCORE_BASE
    p = max(0.02, min(0.98, (wins + 0.5) / (comps + 1.0)))
    return round(400.0 * math.log10(p / (1.0 - p)) + SCORE_BASE)


def ts_elo(mu, sigma):
    return round((mu - 3 * sigma) * TS_SCALE + SCORE_BASE)


def spearman(d1, d2, pids):
    common = [p for p in pids if p in d1 and p in d2]
    if len(common) < 5: return 0.0
    rho, _ = scipy_stats.spearmanr([d1[p] for p in common], [d2[p] for p in common])
    return float(rho) if not np.isnan(rho) else 0.0


def topk_overlap(d1, d2, k):
    a = set(sorted(d1, key=d1.get)[:k])
    b = set(sorted(d2, key=d2.get)[:k])
    return len(a & b) / k if k > 0 else 0


async def simulate_category(db, category):
    matches = []
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category,
         "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed_at": 1},
    ).sort("completed_at", 1):
        matches.append(m)

    if len(matches) < 100:
        return None

    all_pids = set()
    for m in matches:
        all_pids.add(m["paper1_id"])
        all_pids.add(m["paper2_id"])
    all_pids = sorted(all_pids)

    # --- Controlled subset: papers that appear in the first 10% of matches ---
    early_cutoff = len(matches) // 10
    controlled_pids = set()
    for m in matches[:early_cutoff]:
        controlled_pids.add(m["paper1_id"])
        controlled_pids.add(m["paper2_id"])
    controlled_pids = sorted(controlled_pids)

    # --- Full replay for final ground truth ---
    wr_w, wr_c = defaultdict(int), defaultdict(int)
    env = trueskill.TrueSkill(draw_probability=0.0)
    ts_r = {p: env.create_rating() for p in all_pids}

    for m in matches:
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        wr_c[p1] += 1; wr_c[p2] += 1
        if w == p1: wr_w[p1] += 1
        elif w == p2: wr_w[p2] += 1
        if w == p1: ts_r[p1], ts_r[p2] = trueskill.rate_1vs1(ts_r[p1], ts_r[p2], env=env)
        elif w == p2: ts_r[p2], ts_r[p1] = trueskill.rate_1vs1(ts_r[p2], ts_r[p1], env=env)

    final_wr = {p: wr_score(wr_w[p], wr_c[p]) for p in all_pids}
    final_wr_rank = {p: r for r, p in enumerate(sorted(all_pids, key=lambda x: final_wr[x], reverse=True), 1)}
    final_ts = {p: ts_elo(ts_r[p].mu, ts_r[p].sigma) for p in all_pids}
    final_ts_rank = {p: r for r, p in enumerate(sorted(all_pids, key=lambda x: final_ts[x], reverse=True), 1)}

    # Also compute final controlled rankings
    ctrl_final_wr_rank = {p: r for r, p in enumerate(
        sorted(controlled_pids, key=lambda x: final_wr.get(x, SCORE_BASE), reverse=True), 1)}
    ctrl_final_ts_rank = {p: r for r, p in enumerate(
        sorted(controlled_pids, key=lambda x: final_ts.get(x, SCORE_BASE), reverse=True), 1)}

    # --- Incremental replay with checkpoints ---
    inc_wr_w, inc_wr_c = defaultdict(int), defaultdict(int)
    inc_ts = {p: env.create_rating() for p in all_pids}

    checkpoints = sorted(set(max(1, int(len(matches) * p / 100)) for p in range(2, 101, 2)))
    rows = []

    for i, m in enumerate(matches):
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        inc_wr_c[p1] += 1; inc_wr_c[p2] += 1
        if w == p1: inc_wr_w[p1] += 1
        elif w == p2: inc_wr_w[p2] += 1
        if w == p1: inc_ts[p1], inc_ts[p2] = trueskill.rate_1vs1(inc_ts[p1], inc_ts[p2], env=env)
        elif w == p2: inc_ts[p2], inc_ts[p1] = trueskill.rate_1vs1(inc_ts[p2], inc_ts[p1], env=env)

        if (i + 1) not in checkpoints:
            continue

        seen = [p for p in all_pids if inc_wr_c[p] > 0]
        ctrl_seen = [p for p in controlled_pids if inc_wr_c[p] > 0]
        if len(seen) < 10 or len(ctrl_seen) < 10:
            continue

        # Current rankings
        cur_wr = {p: wr_score(inc_wr_w[p], inc_wr_c[p]) for p in seen}
        cur_wr_rank = {p: r for r, p in enumerate(sorted(seen, key=lambda x: cur_wr[x], reverse=True), 1)}
        cur_ts = {p: ts_elo(inc_ts[p].mu, inc_ts[p].sigma) for p in seen}
        cur_ts_rank = {p: r for r, p in enumerate(sorted(seen, key=lambda x: cur_ts[x], reverse=True), 1)}

        # Controlled subset rankings
        ctrl_wr = {p: wr_score(inc_wr_w[p], inc_wr_c[p]) for p in ctrl_seen}
        ctrl_wr_rank = {p: r for r, p in enumerate(sorted(ctrl_seen, key=lambda x: ctrl_wr[x], reverse=True), 1)}
        ctrl_ts = {p: ts_elo(inc_ts[p].mu, inc_ts[p].sigma) for p in ctrl_seen}
        ctrl_ts_rank = {p: r for r, p in enumerate(sorted(ctrl_seen, key=lambda x: ctrl_ts[x], reverse=True), 1)}

        avg_mpp = sum(inc_wr_c[p] for p in seen) / len(seen)
        ctrl_avg_mpp = sum(inc_wr_c[p] for p in ctrl_seen) / len(ctrl_seen) if ctrl_seen else 0

        k = max(3, min(10, len(seen) // 10))
        ctrl_k = max(3, min(10, len(ctrl_seen) // 10))

        rows.append({
            "pct": round((i + 1) / len(matches) * 100),
            "avg_mpp": round(avg_mpp, 1),
            "ctrl_mpp": round(ctrl_avg_mpp, 1),
            # Full set
            "wr_rho": round(spearman(cur_wr_rank, final_wr_rank, seen), 4),
            "ts_rho": round(spearman(cur_ts_rank, final_ts_rank, seen), 4),
            "wr_topk": round(topk_overlap(cur_wr_rank, final_wr_rank, k), 3),
            "ts_topk": round(topk_overlap(cur_ts_rank, final_ts_rank, k), 3),
            # Controlled set (no new-paper noise)
            "ctrl_wr_rho": round(spearman(ctrl_wr_rank, ctrl_final_wr_rank, ctrl_seen), 4),
            "ctrl_ts_rho": round(spearman(ctrl_ts_rank, ctrl_final_ts_rank, ctrl_seen), 4),
            "ctrl_wr_topk": round(topk_overlap(ctrl_wr_rank, ctrl_final_wr_rank, ctrl_k), 3),
            "ctrl_ts_topk": round(topk_overlap(ctrl_ts_rank, ctrl_final_ts_rank, ctrl_k), 3),
        })

    return {
        "category": category,
        "n_matches": len(matches),
        "n_papers": len(all_pids),
        "n_controlled": len(controlled_pids),
        "avg_mpp": round(sum(wr_c.values()) / len(all_pids), 1),
        "wr_ts_final_rho": round(spearman(final_wr_rank, final_ts_rank, all_pids), 3),
        "rows": rows,
    }


def find_milestone(rows, key, target, mpp_key="avg_mpp"):
    for r in rows:
        if r[key] >= target:
            return r[mpp_key]
    return None


async def main():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    cats = ["cs.RO", "cs.DC", "econ.GN", "physics.comp-ph", "q-bio.BM"]
    results = {}

    for cat in cats:
        print(f"\n{'='*60}")
        print(f"Simulating {cat}...")
        r = await simulate_category(db, cat)
        if r is None:
            print(f"  Skipping (too few matches)")
            continue
        results[cat] = r
        print(f"  {r['n_matches']} matches, {r['n_papers']} papers, avg {r['avg_mpp']} m/p")
        print(f"  Final WR-TS Spearman: {r['wr_ts_final_rho']}")

    # === SUMMARY TABLE ===
    print("\n\n" + "=" * 100)
    print("MULTI-CATEGORY CONVERGENCE SUMMARY")
    print("=" * 100)

    # For each target, show m/p needed for WR and TS across categories
    for target in [0.85, 0.90, 0.95]:
        print(f"\n--- Ranking stability rho >= {target} ---")
        print(f"{'Category':>20} {'Papers':>7} {'WR (m/p)':>10} {'TS (m/p)':>10} {'Savings':>10} {'Speedup':>10}")
        print("-" * 75)
        total_wr, total_ts, count = 0, 0, 0
        for cat, r in results.items():
            wr_mpp = find_milestone(r["rows"], "ctrl_wr_rho", target, "ctrl_mpp")
            ts_mpp = find_milestone(r["rows"], "ctrl_ts_rho", target, "ctrl_mpp")
            if wr_mpp and ts_mpp:
                savings = round((1 - ts_mpp / wr_mpp) * 100, 1) if wr_mpp > 0 else 0
                speedup = round(wr_mpp / ts_mpp, 2) if ts_mpp > 0 else 0
                total_wr += wr_mpp; total_ts += ts_mpp; count += 1
            else:
                savings = "N/A"
                speedup = "N/A"
            wr_str = f"{wr_mpp:.0f}" if wr_mpp else "never"
            ts_str = f"{ts_mpp:.0f}" if ts_mpp else "never"
            print(f"{cat:>20} {r['n_controlled']:>7} {wr_str:>10} {ts_str:>10} {str(savings)+'%':>10} {str(speedup)+'x':>10}")
        if count > 0:
            avg_savings = round((1 - total_ts / total_wr) * 100, 1)
            avg_speedup = round(total_wr / total_ts, 2)
            print(f"{'AVERAGE':>20} {'':>7} {total_wr/count:>10.0f} {total_ts/count:>10.0f} {avg_savings}%{' ':>5} {avg_speedup}x")

    # === CONTROLLED CONVERGENCE CURVES ===
    print("\n\n" + "=" * 100)
    print("CONTROLLED CONVERGENCE (early papers only — no new-paper noise)")
    print("=" * 100)
    for cat, r in results.items():
        print(f"\n--- {cat} ({r['n_controlled']} controlled papers) ---")
        print(f"{'M/P':>6} {'WR rho':>8} {'TS rho':>8} {'delta':>8} {'WR top':>8} {'TS top':>8}")
        prev_mpp = -1
        for row in r["rows"]:
            mpp = row["ctrl_mpp"]
            # Print at meaningful intervals
            if mpp < prev_mpp + 3:
                continue
            prev_mpp = mpp
            d = row["ctrl_ts_rho"] - row["ctrl_wr_rho"]
            print(f"{mpp:>5.0f}  {row['ctrl_wr_rho']:>8.3f} {row['ctrl_ts_rho']:>8.3f} {d:>+8.3f} "
                  f"{row['ctrl_wr_topk']:>7.0%} {row['ctrl_ts_topk']:>7.0%}")

    # === AT FIXED MATCH BUDGETS ===
    print("\n\n" + "=" * 100)
    print("RANKING QUALITY AT FIXED MATCH BUDGETS (controlled papers)")
    print("=" * 100)
    for target_mpp in [10, 20, 30, 40, 50]:
        print(f"\n--- At ~{target_mpp} matches/paper ---")
        print(f"{'Category':>20} {'WR rho':>8} {'TS rho':>8} {'TS advantage':>14} {'WR top-K':>9} {'TS top-K':>9}")
        for cat, r in results.items():
            closest = min(r["rows"], key=lambda x: abs(x["ctrl_mpp"] - target_mpp))
            d = closest["ctrl_ts_rho"] - closest["ctrl_wr_rho"]
            print(f"{cat:>20} {closest['ctrl_wr_rho']:>8.3f} {closest['ctrl_ts_rho']:>8.3f} {d:>+14.3f} "
                  f"{closest['ctrl_wr_topk']:>8.0%} {closest['ctrl_ts_topk']:>8.0%}")

    client.close()


asyncio.run(main())
