"""
Simulate old vs new matchmaking logic on cs.RO with 50 synthetic new papers.

Uses real established papers from the DB, adds 50 synthetic papers with 
known ground-truth scores, runs both algorithms for N rounds, and measures
how quickly each converges to the true ranking.
"""
import math
import random
import sys
from collections import defaultdict

random.seed(42)

# ─── Ground truth & simulation ───────────────────────────────────────────────

def simulate_match(elo_a, elo_b):
    """Simulate a pairwise comparison using BT model with noise."""
    p_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
    return "a" if random.random() < p_a else "b"


def wilson_margin_pct(wins, comparisons):
    if comparisons == 0:
        return 100.0
    p = wins / comparisons
    n = comparisons
    z = 1.96
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * ((p * (1 - p) + z**2 / (4 * n)) / n) ** 0.5 / denom
    lower = max(0, center - spread)
    upper = min(1, center + spread)
    return round((upper - lower) / 2 * 100, 1)


def compute_elo(wins, comparisons):
    if comparisons == 0:
        return 1200
    p = max(0.02, min(0.98, (wins + 0.5) / (comparisons + 1.0)))
    return 400.0 * math.log10(p / (1.0 - p)) + 1200


def spearman_rho(rank_a, rank_b, ids):
    """Spearman rank correlation between two rankings over a subset of IDs."""
    n = len(ids)
    if n < 2:
        return 0.0
    # Re-rank within the subset (not using global ranks)
    sorted_a = sorted(ids, key=lambda pid: rank_a.get(pid, 9999))
    sorted_b = sorted(ids, key=lambda pid: rank_b.get(pid, 9999))
    local_rank_a = {pid: i + 1 for i, pid in enumerate(sorted_a)}
    local_rank_b = {pid: i + 1 for i, pid in enumerate(sorted_b)}
    d_sq = sum((local_rank_a[pid] - local_rank_b[pid]) ** 2 for pid in ids)
    return 1 - 6 * d_sq / (n * (n * n - 1))


# ─── Build scenario ──────────────────────────────────────────────────────────

def build_scenario():
    """Create 200 established papers + 50 new papers with ground truth."""
    papers = []
    ground_truth = {}  # pid -> true Elo
    stats = {}  # pid -> {wins, losses, comparisons}
    compared_pairs = set()

    # 200 established papers with realistic stats (converged)
    for i in range(200):
        pid = f"est_{i:03d}"
        true_elo = 1000 + i * 4  # Spread from 1000 to 1796
        ground_truth[pid] = true_elo
        # Simulate ~30 matches worth of stats based on true Elo
        n = random.randint(20, 50)
        # Win rate should correlate with true Elo rank
        true_p = (true_elo - 900) / 1000  # Roughly 0.1 to 0.9
        true_p = max(0.1, min(0.9, true_p))
        w = int(n * true_p + random.gauss(0, 1))
        w = max(0, min(n, w))
        stats[pid] = {"wins": w, "losses": n - w, "comparisons": n}
        papers.append({"id": pid})

    # Add some compared pairs among established papers
    est_ids = [f"est_{i:03d}" for i in range(200)]
    for _ in range(3000):
        a, b = random.sample(est_ids, 2)
        compared_pairs.add(tuple(sorted([a, b])))

    # 50 NEW papers (0 matches)
    for i in range(50):
        pid = f"new_{i:02d}"
        # Spread across the full range — some great, some mediocre, some bad
        true_elo = 1000 + random.randint(0, 800)
        ground_truth[pid] = true_elo
        stats[pid] = {"wins": 0, "losses": 0, "comparisons": 0}
        papers.append({"id": pid})

    return papers, ground_truth, stats, compared_pairs


# ─── OLD algorithm (current code) ────────────────────────────────────────────

def select_pairs_old(papers, stats, compared_pairs, max_pairs, top_k=10, max_per_round=3,
                     ci_target=10, ci_target_general=15, calibration_ratio=50):
    paper_ids = [p["id"] for p in papers]
    comparisons = {pid: stats[pid]["comparisons"] for pid in paper_ids}
    wins = {pid: stats[pid]["wins"] for pid in paper_ids}
    margins = {pid: wilson_margin_pct(wins[pid], comparisons[pid]) for pid in paper_ids}

    all_ranked = sorted(paper_ids, key=lambda pid: wins[pid] / max(comparisons[pid], 1), reverse=True)
    top_k_ids = set(all_ranked[:min(top_k, len(all_ranked))])
    top_k_list = all_ranked[:min(top_k, len(all_ranked))]

    pairs = []
    round_count = {pid: 0 for pid in paper_ids}

    def can_pair(p):
        return round_count[p] < max_per_round

    def urgency(pid):
        target = ci_target if pid in top_k_ids else ci_target_general
        if comparisons[pid] == 0:
            return 999
        if margins[pid] > target:
            return margins[pid] - target
        return 0

    needy = sorted(paper_ids, key=lambda pid: urgency(pid), reverse=True)
    needy = [pid for pid in needy if urgency(pid) > 0]
    established = [pid for pid in paper_ids if urgency(pid) == 0]
    pair_idx = 0

    for p1 in needy:
        if len(pairs) >= max_pairs or not can_pair(p1):
            continue
        prefer_established = len(established) > 0 and ((pair_idx * calibration_ratio) % 100 < calibration_ratio)
        pair_idx += 1

        best = None
        best_score = -1

        if prefer_established:
            for p2 in established:
                if p2 == p1 or not can_pair(p2):
                    continue
                pk = tuple(sorted([p1, p2]))
                if pk not in compared_pairs:
                    best = p2
                    break

        if best is None:
            for p2 in needy:
                if p2 == p1 or not can_pair(p2):
                    continue
                pk = tuple(sorted([p1, p2]))
                novel = pk not in compared_pairs
                score = (1000 if novel else 0) + urgency(p2)
                if score > best_score:
                    best_score = score
                    best = p2

        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2):
                    pk = tuple(sorted([p1, p2]))
                    if pk not in compared_pairs:
                        best = p2
                        break
        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2):
                    best = p2
                    break
        if best:
            pk = tuple(sorted([p1, best]))
            pairs.append((p1, best))
            compared_pairs.add(pk)
            round_count[p1] += 1
            round_count[best] += 1

    # Top-K cross-matches
    for i in range(len(top_k_list)):
        for j in range(i + 1, len(top_k_list)):
            if len(pairs) >= max_pairs:
                break
            pk = tuple(sorted([top_k_list[i], top_k_list[j]]))
            if pk not in compared_pairs:
                pairs.append((top_k_list[i], top_k_list[j]))
                compared_pairs.add(pk)
                round_count[top_k_list[i]] += 1
                round_count[top_k_list[j]] += 1
        if len(pairs) >= max_pairs:
            break

    return pairs[:max_pairs]


# ─── NEW algorithm (minimal fix: score-aware established selection) ─────────

def select_pairs_new(papers, stats, compared_pairs, max_pairs, top_k=10, max_per_round=3,
                     ci_target=10, ci_target_general=15, calibration_ratio=50):
    """Same as OLD but with two targeted fixes:
    1. Established opponent selected by Elo proximity (not first-found)
    2. Top-K identification uses Elo scores (not raw win-rate)
    """
    paper_ids = [p["id"] for p in papers]
    comparisons = {pid: stats[pid]["comparisons"] for pid in paper_ids}
    wins = {pid: stats[pid]["wins"] for pid in paper_ids}
    margins = {pid: wilson_margin_pct(wins[pid], comparisons[pid]) for pid in paper_ids}

    # FIX 2: Compute Elo for score-aware top-K and opponent selection
    elo_scores = {pid: compute_elo(wins[pid], comparisons[pid]) for pid in paper_ids}
    elo_vals = sorted(elo_scores.values())
    median_elo = elo_vals[len(elo_vals) // 2]

    # FIX 2: Use Elo for top-K (not raw win-rate)
    all_ranked = sorted(paper_ids, key=lambda pid: elo_scores[pid], reverse=True)
    top_k_ids = set(all_ranked[:min(top_k, len(all_ranked))])
    top_k_list = all_ranked[:min(top_k, len(all_ranked))]

    pairs = []
    round_count = {pid: 0 for pid in paper_ids}

    def can_pair(p):
        return round_count[p] < max_per_round

    def urgency(pid):
        target = ci_target if pid in top_k_ids else ci_target_general
        if comparisons[pid] == 0:
            return 999
        if margins[pid] > target:
            return margins[pid] - target
        return 0

    needy = sorted(paper_ids, key=lambda pid: urgency(pid), reverse=True)
    needy = [pid for pid in needy if urgency(pid) > 0]
    established = [pid for pid in paper_ids if urgency(pid) == 0]
    pair_idx = 0

    for p1 in needy:
        if len(pairs) >= max_pairs or not can_pair(p1):
            continue
        prefer_established = len(established) > 0 and ((pair_idx * calibration_ratio) % 100 < calibration_ratio)
        pair_idx += 1

        best = None
        best_score = -1

        if prefer_established:
            # FIX 1: Pick established opponent closest to target Elo (not first-found)
            target = median_elo if comparisons[p1] == 0 else elo_scores[p1]
            for p2 in established:
                if p2 == p1 or not can_pair(p2):
                    continue
                pk = tuple(sorted([p1, p2]))
                if pk in compared_pairs:
                    continue
                dist = abs(elo_scores[p2] - target)
                score = 10000 - dist  # Closer = better
                if score > best_score:
                    best_score = score
                    best = p2

        # Needy-vs-needy fallback (same as OLD)
        if best is None:
            best_score = -1
            for p2 in needy:
                if p2 == p1 or not can_pair(p2):
                    continue
                pk = tuple(sorted([p1, p2]))
                novel = pk not in compared_pairs
                score = (1000 if novel else 0) + urgency(p2)
                if score > best_score:
                    best_score = score
                    best = p2

        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2):
                    pk = tuple(sorted([p1, p2]))
                    if pk not in compared_pairs:
                        best = p2
                        break
        if best is None:
            for p2 in paper_ids:
                if p2 != p1 and can_pair(p2):
                    best = p2
                    break
        if best:
            pk = tuple(sorted([p1, best]))
            pairs.append((p1, best))
            compared_pairs.add(pk)
            round_count[p1] += 1
            round_count[best] += 1

    # Top-K cross-matches (unchanged)
    for i in range(len(top_k_list)):
        for j in range(i + 1, len(top_k_list)):
            if len(pairs) >= max_pairs:
                break
            pk = tuple(sorted([top_k_list[i], top_k_list[j]]))
            if pk not in compared_pairs:
                pairs.append((top_k_list[i], top_k_list[j]))
                compared_pairs.add(pk)
                round_count[top_k_list[i]] += 1
                round_count[top_k_list[j]] += 1
        if len(pairs) >= max_pairs:
            break

    # Post-convergence: closest-Elo pairs instead of random
    if not needy and len(pairs) < max_pairs:
        elo_sorted = sorted(paper_ids, key=lambda pid: elo_scores[pid])
        for i in range(len(elo_sorted) - 1):
            if len(pairs) >= max_pairs:
                break
            p1, p2 = elo_sorted[i], elo_sorted[i + 1]
            if can_pair(p1) and can_pair(p2):
                pk = tuple(sorted([p1, p2]))
                if pk in compared_pairs:
                    pairs.append((p1, p2))
                    round_count[p1] += 1
                    round_count[p2] += 1

    return pairs[:max_pairs]


# ─── Run simulation ──────────────────────────────────────────────────────────

def run_simulation(algo_name, select_fn, papers, ground_truth, initial_stats, initial_pairs,
                   max_rounds=20, max_pairs_per_round=100):
    """Run the matchmaking algorithm for N rounds, measure convergence."""
    stats = {pid: dict(s) for pid, s in initial_stats.items()}
    compared_pairs = set(initial_pairs)
    
    new_ids = [p["id"] for p in papers if p["id"].startswith("new_")]
    all_ids = [p["id"] for p in papers]
    
    # Ground truth ranking
    gt_rank = {}
    gt_sorted = sorted(all_ids, key=lambda pid: ground_truth[pid], reverse=True)
    for i, pid in enumerate(gt_sorted):
        gt_rank[pid] = i + 1
    
    results = []
    total_matches = 0
    
    for round_num in range(1, max_rounds + 1):
        pairs = select_fn(papers, stats, set(compared_pairs), max_pairs_per_round)
        
        if not pairs:
            break
        
        for p1, p2 in pairs:
            winner = p1 if simulate_match(ground_truth[p1], ground_truth[p2]) == "a" else p2
            loser = p2 if winner == p1 else p1
            stats[winner]["wins"] += 1
            stats[winner]["comparisons"] += 1
            stats[loser]["losses"] += 1
            stats[loser]["comparisons"] += 1
            compared_pairs.add(tuple(sorted([p1, p2])))
            total_matches += 1
        
        # Measure quality
        # 1. Elo from stats
        elo = {pid: compute_elo(stats[pid]["wins"], stats[pid]["comparisons"]) for pid in all_ids}
        ai_sorted = sorted(all_ids, key=lambda pid: elo[pid], reverse=True)
        ai_rank = {pid: i + 1 for i, pid in enumerate(ai_sorted)}
        
        # 2. Spearman rho (all papers)
        rho_all = spearman_rho(ai_rank, gt_rank, all_ids)
        
        # 3. Spearman rho (new papers only)
        new_with_matches = [pid for pid in new_ids if stats[pid]["comparisons"] > 0]
        rho_new = spearman_rho(ai_rank, gt_rank, new_with_matches) if len(new_with_matches) >= 5 else 0
        
        # 4. How many new papers have been matched?
        new_matched = sum(1 for pid in new_ids if stats[pid]["comparisons"] > 0)
        
        # 5. Average CI of new papers
        new_margins = [wilson_margin_pct(stats[pid]["wins"], stats[pid]["comparisons"]) for pid in new_ids]
        avg_new_ci = sum(new_margins) / len(new_margins)
        
        # 6. New papers with CI converged (< 15%)
        new_converged = sum(1 for m in new_margins if m < 15)
        
        # 7. Needy-vs-needy match count this round
        needy_vs_needy = sum(1 for p1, p2 in pairs 
                           if stats[p1]["comparisons"] <= 3 and stats[p2]["comparisons"] <= 3)
        
        # 8. Top-10 accuracy (are the true top-10 in estimated top-10?)
        true_top10 = set(gt_sorted[:10])
        est_top10 = set(ai_sorted[:10])
        top10_overlap = len(true_top10 & est_top10)
        
        results.append({
            "round": round_num,
            "matches": len(pairs),
            "total_matches": total_matches,
            "rho_all": round(rho_all, 4),
            "rho_new": round(rho_new, 4),
            "new_matched": new_matched,
            "new_converged": new_converged,
            "avg_new_ci": round(avg_new_ci, 1),
            "needy_vs_needy": needy_vs_needy,
            "top10_overlap": top10_overlap,
        })
    
    return results


def main():
    papers, ground_truth, stats, compared_pairs = build_scenario()
    
    print("=" * 90)
    print(f"Scenario: {len([p for p in papers if p['id'].startswith('est_')])} established + "
          f"{len([p for p in papers if p['id'].startswith('new_')])} new papers, "
          f"{len(compared_pairs)} existing pairs")
    print("=" * 90)
    
    # Run OLD
    old_results = run_simulation(
        "OLD", select_pairs_old,
        papers, ground_truth, stats, compared_pairs,
        max_rounds=15, max_pairs_per_round=100,
    )
    
    # Run NEW (same scenario, fresh stats copy)
    new_results = run_simulation(
        "NEW", select_pairs_new,
        papers, ground_truth, stats, compared_pairs,
        max_rounds=15, max_pairs_per_round=100,
    )
    
    # Print comparison
    print(f"\n{'Round':>5} | {'--- OLD ---':^52} | {'--- NEW ---':^52}")
    print(f"{'':>5} | {'rho_all':>8} {'rho_new':>8} {'matched':>8} {'convgd':>7} {'avg_CI':>7} {'n-v-n':>6} {'top10':>6} | "
          f"{'rho_all':>8} {'rho_new':>8} {'matched':>8} {'convgd':>7} {'avg_CI':>7} {'n-v-n':>6} {'top10':>6}")
    print("-" * 120)
    
    for o, n in zip(old_results, new_results):
        def fmt(r):
            return (f"{r['rho_all']:>8.4f} {r['rho_new']:>8.4f} {r['new_matched']:>5}/50 "
                    f"{r['new_converged']:>4}/50 {r['avg_new_ci']:>6.1f}% {r['needy_vs_needy']:>5} {r['top10_overlap']:>4}/10")
        print(f"{o['round']:>5} | {fmt(o)} | {fmt(n)}")
    
    # Summary
    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    
    # Find round where all 50 new papers first get matched
    old_all_matched = next((r["round"] for r in old_results if r["new_matched"] == 50), ">15")
    new_all_matched = next((r["round"] for r in new_results if r["new_matched"] == 50), ">15")
    
    # Find round where rho_new first exceeds 0.8
    old_rho_80 = next((r["round"] for r in old_results if r["rho_new"] >= 0.8), ">15")
    new_rho_80 = next((r["round"] for r in new_results if r["rho_new"] >= 0.8), ">15")
    
    # Total needy-vs-needy matches
    old_nvn = sum(r["needy_vs_needy"] for r in old_results)
    new_nvn = sum(r["needy_vs_needy"] for r in new_results)
    
    print(f"  All 50 new papers matched:     OLD = round {old_all_matched},  NEW = round {new_all_matched}")
    print(f"  New-paper rho >= 0.8:          OLD = round {old_rho_80},  NEW = round {new_rho_80}")
    print(f"  Total needy-vs-needy matches:  OLD = {old_nvn},  NEW = {new_nvn}")
    print(f"  Final rho (all):               OLD = {old_results[-1]['rho_all']:.4f},  NEW = {new_results[-1]['rho_all']:.4f}")
    print(f"  Final rho (new):               OLD = {old_results[-1]['rho_new']:.4f},  NEW = {new_results[-1]['rho_new']:.4f}")
    print(f"  Final top-10 overlap:          OLD = {old_results[-1]['top10_overlap']}/10,  NEW = {new_results[-1]['top10_overlap']}/10")
    print(f"  Final new converged (<15% CI): OLD = {old_results[-1]['new_converged']}/50,  NEW = {new_results[-1]['new_converged']}/50")


if __name__ == "__main__":
    main()
