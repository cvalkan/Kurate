"""
Simulation: Binary Search vs Closest-Score opponent selection for TrueSkill ranking.

Creates a synthetic category of papers with known true strengths, runs both
matchmaking strategies, and compares:
1. Rank accuracy (Kendall tau correlation with true ranking)
2. Number of matches to convergence
3. Sigma convergence curves
4. 100% WR paper behavior
"""
import random
import math
from collections import defaultdict

# Use trueskill library
import trueskill

# ─── Simulation Parameters ───
N_PAPERS = 100
N_ROUNDS = 30  # comparison rounds
MATCHES_PER_ROUND = 50
SIGMA_TARGET = 2.5
MIN_COMPS_FLOOR = 50
SEED = 42

random.seed(SEED)

# ─── Generate True Strengths ───
# Some papers are genuinely strong, some weak, most average
true_strengths = {}
for i in range(N_PAPERS):
    # Mix of distributions to create realistic spread
    if i < 5:  # 5 truly exceptional papers
        strength = random.gauss(40, 2)
    elif i < 15:  # 10 strong papers
        strength = random.gauss(32, 3)
    elif i < 85:  # 70 average papers
        strength = random.gauss(25, 4)
    else:  # 15 weak papers
        strength = random.gauss(18, 3)
    true_strengths[f"paper_{i}"] = strength

# Sort by true strength for reference
true_ranking = sorted(true_strengths.keys(), key=lambda p: -true_strengths[p])
true_rank = {p: i+1 for i, p in enumerate(true_ranking)}

print(f"=== Simulation: {N_PAPERS} papers, {N_ROUNDS} rounds, {MATCHES_PER_ROUND} matches/round ===")
print(f"True strength range: {min(true_strengths.values()):.1f} - {max(true_strengths.values()):.1f}")
print()


def simulate_match(p1, p2):
    """Simulate match outcome based on true strengths (Bradley-Terry model)."""
    s1, s2 = true_strengths[p1], true_strengths[p2]
    p_win = 1 / (1 + math.exp(-(s1 - s2) / 4))  # logistic with scale=4
    return p1 if random.random() < p_win else p2


def kendall_tau(ranking_a, ranking_b):
    """Kendall tau correlation between two rankings (dicts of paper -> rank)."""
    papers = list(ranking_a.keys())
    concordant = 0
    discordant = 0
    for i in range(len(papers)):
        for j in range(i+1, len(papers)):
            pi, pj = papers[i], papers[j]
            diff_a = ranking_a[pi] - ranking_a[pj]
            diff_b = ranking_b[pi] - ranking_b[pj]
            if diff_a * diff_b > 0:
                concordant += 1
            elif diff_a * diff_b < 0:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else 0


def run_simulation(strategy_name, select_opponent_fn):
    """Run a full simulation with the given opponent selection strategy."""
    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = {p: env.create_rating() for p in true_strengths}
    stats = {p: {"wins": 0, "losses": 0, "comparisons": 0} for p in true_strengths}
    
    # Binary search bounds (only used by binary_search strategy)
    search_lo = {p: 0.0 for p in true_strengths}  # lowest score beaten
    search_hi = {p: 50.0 for p in true_strengths}  # highest score lost to
    
    # Track per-round metrics
    history = []
    total_matches = 0
    
    for round_num in range(N_ROUNDS):
        # Compute current scores and sigmas
        scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in true_strengths}
        sigmas = {p: ratings[p].sigma for p in true_strengths}
        
        # Determine needy papers
        needy = []
        established = []
        for p in true_strengths:
            if stats[p]["comparisons"] == 0:
                needy.append(p)
            elif sigmas[p] > SIGMA_TARGET and stats[p]["comparisons"] < MIN_COMPS_FLOOR:
                needy.append(p)
            elif (stats[p]["wins"] == stats[p]["comparisons"] or stats[p]["wins"] == 0) and stats[p]["comparisons"] < MIN_COMPS_FLOOR and stats[p]["comparisons"] > 0:
                needy.append(p)  # undefeated/all-losses below floor
            else:
                established.append(p)
        
        needy.sort(key=lambda p: sigmas[p], reverse=True)
        
        if not needy:
            break  # all converged
        
        # Generate pairs
        pairs = []
        used_this_round = set()
        
        for p1 in needy:
            if len(pairs) >= MATCHES_PER_ROUND:
                break
            if p1 in used_this_round:
                continue
            
            # Select opponent using strategy
            p2 = select_opponent_fn(
                p1, established, needy, scores, sigmas, stats,
                search_lo, search_hi, used_this_round
            )
            
            if p2 and p2 != p1:
                pairs.append((p1, p2))
                used_this_round.add(p1)
                used_this_round.add(p2)
        
        # Execute matches
        for p1, p2 in pairs:
            winner = simulate_match(p1, p2)
            loser = p2 if winner == p1 else p1
            
            # Update TrueSkill
            (nr1,), (nr2,) = env.rate([(ratings[winner],), (ratings[loser],)], ranks=[0, 1])
            ratings[winner] = nr1
            ratings[loser] = nr2
            
            # Update stats
            stats[winner]["wins"] += 1
            stats[winner]["comparisons"] += 1
            stats[loser]["losses"] += 1
            stats[loser]["comparisons"] += 1
            
            # Update search bounds
            winner_score = scores.get(winner, 25)
            loser_score = scores.get(loser, 25)
            search_lo[winner] = max(search_lo[winner], loser_score)
            search_hi[loser] = min(search_hi[loser], winner_score)
            
            total_matches += 1
        
        # Compute current ranking
        current_scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in true_strengths}
        current_ranking = sorted(true_strengths.keys(), key=lambda p: -current_scores[p])
        current_rank = {p: i+1 for i, p in enumerate(current_ranking)}
        
        tau = kendall_tau(true_rank, current_rank)
        avg_sigma = sum(ratings[p].sigma for p in true_strengths) / N_PAPERS
        converged = sum(1 for p in true_strengths if ratings[p].sigma <= SIGMA_TARGET or stats[p]["comparisons"] >= MIN_COMPS_FLOOR)
        
        # Track 100% WR papers
        perfect_wr = [p for p in true_strengths if stats[p]["comparisons"] > 0 and stats[p]["wins"] == stats[p]["comparisons"]]
        perfect_avg_comps = sum(stats[p]["comparisons"] for p in perfect_wr) / len(perfect_wr) if perfect_wr else 0
        
        history.append({
            "round": round_num + 1,
            "matches": len(pairs),
            "total_matches": total_matches,
            "tau": tau,
            "avg_sigma": avg_sigma,
            "converged": converged,
            "needy": len(needy),
            "perfect_wr_count": len(perfect_wr),
            "perfect_wr_avg_comps": perfect_avg_comps,
        })
    
    return history, ratings, stats, search_lo, search_hi


# ─── Strategy 1: Closest-Score (current approach) ───
def closest_score_opponent(p1, established, needy, scores, sigmas, stats, search_lo, search_hi, used):
    """Current approach: pick the closest-scored established opponent."""
    my_score = scores.get(p1, 25)
    if stats[p1]["comparisons"] == 0:
        # New paper: use median
        all_scores = sorted(scores.values())
        my_score = all_scores[len(all_scores) // 2]
    
    best = None
    best_dist = float('inf')
    
    # Prefer established
    for p2 in established:
        if p2 == p1 or p2 in used:
            continue
        dist = abs(scores[p2] - my_score)
        if dist < best_dist:
            best_dist = dist
            best = p2
    
    # Fallback to needy
    if best is None:
        for p2 in needy:
            if p2 == p1 or p2 in used:
                continue
            dist = abs(scores[p2] - my_score)
            if dist < best_dist:
                best_dist = dist
                best = p2
    
    return best


# ─── Strategy 2: Binary Search ───
def binary_search_opponent(p1, established, needy, scores, sigmas, stats, search_lo, search_hi, used):
    """Binary search: target midpoint of search bounds."""
    lo = search_lo[p1]
    hi = search_hi[p1]
    target = (lo + hi) / 2
    
    best = None
    best_dist = float('inf')
    
    # Prefer established
    for p2 in established:
        if p2 == p1 or p2 in used:
            continue
        dist = abs(scores[p2] - target)
        if dist < best_dist:
            best_dist = dist
            best = p2
    
    # Fallback to needy
    if best is None:
        for p2 in needy:
            if p2 == p1 or p2 in used:
                continue
            dist = abs(scores[p2] - target)
            if dist < best_dist:
                best_dist = dist
                best = p2
    
    return best


# ─── Run Both Simulations ───
print("Running closest-score simulation...")
h1, r1, s1, _, _ = run_simulation("Closest-Score", closest_score_opponent)

# Reset random seed for fair comparison
random.seed(SEED)
print("Running binary-search simulation...")
h2, r2, s2, sl2, sh2 = run_simulation("Binary-Search", binary_search_opponent)

# ─── Compare Results ───
print()
print(f"{'Round':>5} │ {'Closest-Score':^30} │ {'Binary-Search':^30} │")
print(f"{'':>5} │ {'tau':>6} {'σ_avg':>6} {'conv':>5} {'match':>5} │ {'tau':>6} {'σ_avg':>6} {'conv':>5} {'match':>5} │")
print("─" * 75)

for i in range(max(len(h1), len(h2))):
    r1_data = h1[i] if i < len(h1) else None
    r2_data = h2[i] if i < len(h2) else None
    
    if r1_data and r2_data:
        print(f"{i+1:>5} │ {r1_data['tau']:>6.3f} {r1_data['avg_sigma']:>6.2f} {r1_data['converged']:>5} {r1_data['total_matches']:>5} │ {r2_data['tau']:>6.3f} {r2_data['avg_sigma']:>6.2f} {r2_data['converged']:>5} {r2_data['total_matches']:>5} │")
    elif r1_data:
        print(f"{i+1:>5} │ {r1_data['tau']:>6.3f} {r1_data['avg_sigma']:>6.2f} {r1_data['converged']:>5} {r1_data['total_matches']:>5} │ {'DONE':>30} │")
    elif r2_data:
        print(f"{i+1:>5} │ {'DONE':>30} │ {r2_data['tau']:>6.3f} {r2_data['avg_sigma']:>6.2f} {r2_data['converged']:>5} {r2_data['total_matches']:>5} │")

# Final comparison
print()
print("=== FINAL COMPARISON ===")
for name, h, r, s in [("Closest-Score", h1, r1, s1), ("Binary-Search", h2, r2, s2)]:
    last = h[-1] if h else {}
    total = last.get("total_matches", 0)
    tau = last.get("tau", 0)
    conv = last.get("converged", 0)
    
    # Count 100% WR papers at end
    perfect = [p for p in s if s[p]["comparisons"] > 0 and s[p]["wins"] == s[p]["comparisons"]]
    perfect_comps = [s[p]["comparisons"] for p in perfect]
    
    # Top-5 rank accuracy
    current_scores = {p: (r[p].mu - 3 * r[p].sigma) for p in true_strengths}
    current_ranking = sorted(true_strengths.keys(), key=lambda p: -current_scores[p])
    top5_correct = sum(1 for i, p in enumerate(current_ranking[:5]) if true_rank[p] <= 5)
    top10_correct = sum(1 for i, p in enumerate(current_ranking[:10]) if true_rank[p] <= 10)
    
    print(f"\n  {name}:")
    print(f"    Total matches: {total}")
    print(f"    Kendall tau: {tau:.4f}")
    print(f"    Converged: {conv}/{N_PAPERS}")
    print(f"    Top-5 accuracy: {top5_correct}/5")
    print(f"    Top-10 accuracy: {top10_correct}/10")
    print(f"    100% WR papers remaining: {len(perfect)} (avg {sum(perfect_comps)/len(perfect_comps):.0f} matches)" if perfect else "    100% WR papers remaining: 0")

# ─── Detailed: What happened to the strongest papers? ───
print()
print("=== TOP-5 TRUE PAPERS: detailed comparison ===")
for p in true_ranking[:5]:
    ts = true_strengths[p]
    
    cs_sigma = r1[p].sigma
    cs_comps = s1[p]["comparisons"]
    cs_wr = s1[p]["wins"] / s_comps if (s_comps := s1[p]["comparisons"]) > 0 else 0
    cs_score = r1[p].mu - 3 * r1[p].sigma
    
    bs_sigma = r2[p].sigma
    bs_comps = s2[p]["comparisons"]
    bs_wr = s2[p]["wins"] / s_comps2 if (s_comps2 := s2[p]["comparisons"]) > 0 else 0
    bs_score = r2[p].mu - 3 * r2[p].sigma
    
    print(f"  {p} (true={ts:.1f}):")
    print(f"    Closest:  score={cs_score:.1f} σ={cs_sigma:.2f} comps={cs_comps} WR={cs_wr:.0%}")
    print(f"    BinSearch: score={bs_score:.1f} σ={bs_sigma:.2f} comps={bs_comps} WR={bs_wr:.0%}")
