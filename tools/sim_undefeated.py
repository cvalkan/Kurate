"""
Simulation: Closest-Score vs Closest-Score + Undefeated Urgency

The undefeated urgency fix: papers with 100% WR (or 0% WR) below the match
floor stay mildly needy (urgency 0.1) even when sigma is below target.
This gives them more matches against calibration opponents until they lose
or reach the floor.
"""
import random
import math
import trueskill

N_PAPERS = 100
N_ROUNDS = 40
MATCHES_PER_ROUND = 50
SIGMA_TARGET = 2.5
MIN_COMPS_FLOOR = 50
SEED = 42


def setup():
    random.seed(SEED)
    true_strengths = {}
    for i in range(N_PAPERS):
        if i < 5:
            strength = random.gauss(40, 2)
        elif i < 15:
            strength = random.gauss(32, 3)
        elif i < 85:
            strength = random.gauss(25, 4)
        else:
            strength = random.gauss(18, 3)
        true_strengths[f"paper_{i}"] = strength
    true_ranking = sorted(true_strengths.keys(), key=lambda p: -true_strengths[p])
    true_rank = {p: i+1 for i, p in enumerate(true_ranking)}
    return true_strengths, true_rank


def simulate_match(p1, p2, true_strengths):
    s1, s2 = true_strengths[p1], true_strengths[p2]
    p_win = 1 / (1 + math.exp(-(s1 - s2) / 4))
    return p1 if random.random() < p_win else p2


def kendall_tau(ra, rb):
    papers = list(ra.keys())
    c = d = 0
    for i in range(len(papers)):
        for j in range(i+1, len(papers)):
            da = ra[papers[i]] - ra[papers[j]]
            db = rb[papers[i]] - rb[papers[j]]
            if da * db > 0: c += 1
            elif da * db < 0: d += 1
    return (c - d) / (c + d) if (c + d) > 0 else 0


def run(strategy_name, use_undefeated_urgency, true_strengths, true_rank):
    random.seed(SEED)
    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = {p: env.create_rating() for p in true_strengths}
    stats = {p: {"wins": 0, "losses": 0, "comparisons": 0} for p in true_strengths}
    history = []
    total_matches = 0

    for round_num in range(N_ROUNDS):
        scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in true_strengths}
        sigmas = {p: ratings[p].sigma for p in true_strengths}
        score_list = sorted(scores.values())
        median_score = score_list[len(score_list) // 2]

        def urgency(p):
            if stats[p]["comparisons"] == 0:
                return 999
            if stats[p]["comparisons"] >= MIN_COMPS_FLOOR:
                return 0
            excess = sigmas[p] - SIGMA_TARGET
            if excess > 0:
                return excess
            # Sigma met but below floor
            if use_undefeated_urgency:
                w, c = stats[p]["wins"], stats[p]["comparisons"]
                if w == c or w == 0:  # 100% WR or 0% WR
                    return 0.1
            return 0

        needy = sorted(true_strengths.keys(), key=lambda p: urgency(p), reverse=True)
        needy = [p for p in needy if urgency(p) > 0]
        established = [p for p in true_strengths if urgency(p) == 0]

        if not needy:
            # Record final state and stop
            current_scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in true_strengths}
            current_ranking = sorted(true_strengths.keys(), key=lambda p: -current_scores[p])
            current_rank = {p: i+1 for i, p in enumerate(current_ranking)}
            tau = kendall_tau(true_rank, current_rank)
            history.append({
                "round": round_num + 1, "matches": 0, "total_matches": total_matches,
                "tau": tau, "avg_sigma": sum(sigmas.values()) / N_PAPERS,
                "converged": N_PAPERS, "needy": 0, "perfect_wr": 0, "perfect_wr_avg_comps": 0,
            })
            break

        pairs = []
        used = set()
        for p1 in needy:
            if len(pairs) >= MATCHES_PER_ROUND or p1 in used:
                continue
            # Closest-score opponent selection
            my_score = scores[p1] if stats[p1]["comparisons"] > 0 else median_score
            best, best_dist = None, float('inf')
            for p2 in (established + needy):
                if p2 == p1 or p2 in used:
                    continue
                dist = abs(scores[p2] - my_score)
                if dist < best_dist:
                    best_dist = dist
                    best = p2
            if best:
                pairs.append((p1, best))
                used.add(p1)
                used.add(best)

        for p1, p2 in pairs:
            winner = simulate_match(p1, p2, true_strengths)
            loser = p2 if winner == p1 else p1
            (nr1,), (nr2,) = env.rate([(ratings[winner],), (ratings[loser],)], ranks=[0, 1])
            ratings[winner] = nr1
            ratings[loser] = nr2
            stats[winner]["wins"] += 1
            stats[winner]["comparisons"] += 1
            stats[loser]["losses"] += 1
            stats[loser]["comparisons"] += 1
            total_matches += 1

        current_scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in true_strengths}
        current_ranking = sorted(true_strengths.keys(), key=lambda p: -current_scores[p])
        current_rank = {p: i+1 for i, p in enumerate(current_ranking)}
        tau = kendall_tau(true_rank, current_rank)

        perfect = [p for p in true_strengths if stats[p]["comparisons"] > 0 and stats[p]["wins"] == stats[p]["comparisons"]]
        conv = sum(1 for p in true_strengths if (sigmas[p] <= SIGMA_TARGET and (stats[p]["wins"] != stats[p]["comparisons"] and stats[p]["wins"] != 0 or stats[p]["comparisons"] >= MIN_COMPS_FLOOR)) or stats[p]["comparisons"] >= MIN_COMPS_FLOOR)

        history.append({
            "round": round_num + 1, "matches": len(pairs), "total_matches": total_matches,
            "tau": tau, "avg_sigma": sum(sigmas.values()) / N_PAPERS,
            "converged": conv, "needy": len(needy),
            "perfect_wr": len(perfect),
            "perfect_wr_avg_comps": sum(stats[p]["comparisons"] for p in perfect) / len(perfect) if perfect else 0,
        })

    return history, ratings, stats


# Run both
true_strengths, true_rank = setup()
print(f"=== {N_PAPERS} papers, {N_ROUNDS} rounds, {MATCHES_PER_ROUND} matches/round ===\n")

h1, r1, s1 = run("Current", False, true_strengths, true_rank)
h2, r2, s2 = run("Undefeated-Urgency", True, true_strengths, true_rank)

# Side-by-side
print(f"{'Rnd':>3} │ {'Current (no undefeated fix)':^35} │ {'With undefeated urgency':^35} │")
print(f"{'':>3} │ {'tau':>6} {'conv':>4} {'100%WR':>6} {'mtch':>5} {'needy':>5} │ {'tau':>6} {'conv':>4} {'100%WR':>6} {'mtch':>5} {'needy':>5} │")
print("─" * 82)
for i in range(max(len(h1), len(h2))):
    a = h1[i] if i < len(h1) else None
    b = h2[i] if i < len(h2) else None
    if a and b:
        print(f"{i+1:>3} │ {a['tau']:>6.3f} {a['converged']:>4} {a['perfect_wr']:>6} {a['total_matches']:>5} {a['needy']:>5} │ {b['tau']:>6.3f} {b['converged']:>4} {b['perfect_wr']:>6} {b['total_matches']:>5} {b['needy']:>5} │")
    elif a:
        print(f"{i+1:>3} │ {a['tau']:>6.3f} {a['converged']:>4} {a['perfect_wr']:>6} {a['total_matches']:>5} {a['needy']:>5} │ {'DONE':>35} │")
    elif b:
        print(f"{i+1:>3} │ {'DONE':>35} │ {b['tau']:>6.3f} {b['converged']:>4} {b['perfect_wr']:>6} {b['total_matches']:>5} {b['needy']:>5} │")

# Final comparison
print("\n=== FINAL ===")
for name, h, r, s in [("Current", h1, r1, s1), ("Undefeated-Urgency", h2, r2, s2)]:
    last = h[-1]
    current_scores = {p: (r[p].mu - 3 * r[p].sigma) for p in true_strengths}
    current_ranking = sorted(true_strengths.keys(), key=lambda p: -current_scores[p])
    top5_ok = sum(1 for i, p in enumerate(current_ranking[:5]) if true_rank[p] <= 5)
    top10_ok = sum(1 for i, p in enumerate(current_ranking[:10]) if true_rank[p] <= 10)
    perfect = [p for p in s if s[p]["comparisons"] > 0 and s[p]["wins"] == s[p]["comparisons"]]

    print(f"\n  {name}:")
    print(f"    Matches: {last['total_matches']}")
    print(f"    Kendall tau: {last['tau']:.4f}")
    print(f"    Top-5: {top5_ok}/5, Top-10: {top10_ok}/10")
    print(f"    100% WR remaining: {len(perfect)}")

    # Show top-5 true papers
    for p in sorted(true_strengths.keys(), key=lambda p: -true_strengths[p])[:5]:
        ts = true_strengths[p]
        sig = r[p].sigma
        sc = r[p].mu - 3 * r[p].sigma
        w, c = s[p]["wins"], s[p]["comparisons"]
        wr = w/c*100 if c else 0
        print(f"      {p} true={ts:.1f}: score={sc:.1f} σ={sig:.2f} comps={c} WR={wr:.0f}%")
