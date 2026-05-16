"""
Simulation: New papers arriving into an established category.
This reproduces the production scenario: 80 papers already converged,
20 new papers arrive and need to be ranked.
"""
import random
import math
import trueskill

N_ESTABLISHED = 80
N_NEW = 20
N_ROUNDS = 30
MATCHES_PER_ROUND = 30
SIGMA_TARGET = 2.5
MIN_COMPS_FLOOR = 50
SEED = 42


def setup():
    random.seed(SEED)
    true_strengths = {}
    # Established papers: spread across full range
    for i in range(N_ESTABLISHED):
        true_strengths[f"est_{i}"] = random.gauss(25, 6)
    # New papers: some strong, some average (the interesting case)
    for i in range(N_NEW):
        if i < 3:  # 3 truly exceptional new papers
            true_strengths[f"new_{i}"] = random.gauss(40, 2)
        elif i < 8:  # 5 strong
            true_strengths[f"new_{i}"] = random.gauss(33, 2)
        else:  # 12 average
            true_strengths[f"new_{i}"] = random.gauss(25, 4)
    return true_strengths


def sim_match(p1, p2, ts):
    s1, s2 = ts[p1], ts[p2]
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


def run(name, use_undefeated, true_strengths):
    random.seed(SEED)
    env = trueskill.TrueSkill(draw_probability=0.0)

    # Pre-establish the first 80 papers (50 matches each, low sigma)
    ratings = {p: env.create_rating() for p in true_strengths}
    stats = {p: {"wins": 0, "losses": 0, "comparisons": 0} for p in true_strengths}
    
    est_papers = [p for p in true_strengths if p.startswith("est_")]
    new_papers = [p for p in true_strengths if p.startswith("new_")]
    
    # Run 50 rounds of matches among established papers to pre-converge them
    for _ in range(100):
        pairs = []
        available = list(est_papers)
        random.shuffle(available)
        for i in range(0, len(available) - 1, 2):
            pairs.append((available[i], available[i+1]))
        for p1, p2 in pairs[:40]:
            winner = sim_match(p1, p2, true_strengths)
            loser = p2 if winner == p1 else p1
            (nr1,), (nr2,) = env.rate([(ratings[winner],), (ratings[loser],)], ranks=[0, 1])
            ratings[winner] = nr1
            ratings[loser] = nr2
            stats[winner]["wins"] += 1; stats[winner]["comparisons"] += 1
            stats[loser]["losses"] += 1; stats[loser]["comparisons"] += 1

    # Verify established papers are converged
    est_avg_sigma = sum(ratings[p].sigma for p in est_papers) / len(est_papers)
    est_avg_comps = sum(stats[p]["comparisons"] for p in est_papers) / len(est_papers)
    
    # Now run the tournament with new papers arriving
    all_papers = list(true_strengths.keys())
    true_ranking = sorted(all_papers, key=lambda p: -true_strengths[p])
    true_rank = {p: i+1 for i, p in enumerate(true_ranking)}
    # Also compute true ranking for NEW papers only
    new_true_ranking = sorted(new_papers, key=lambda p: -true_strengths[p])
    new_true_rank = {p: i+1 for i, p in enumerate(new_true_ranking)}

    history = []
    total_new_matches = 0

    for round_num in range(N_ROUNDS):
        scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in all_papers}
        sigmas = {p: ratings[p].sigma for p in all_papers}
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
            if use_undefeated:
                w, c = stats[p]["wins"], stats[p]["comparisons"]
                if w == c or w == 0:
                    return 0.1
            return 0

        needy = sorted(all_papers, key=lambda p: urgency(p), reverse=True)
        needy = [p for p in needy if urgency(p) > 0]
        established = [p for p in all_papers if urgency(p) == 0]

        if not needy:
            history.append({"round": round_num+1, "matches": 0, "total": total_new_matches,
                            "new_needy": 0, "perfect_new": 0, "tau_new": 0, "tau_all": 0,
                            "new_avg_comps": 0, "new_avg_sigma": 0})
            break

        pairs = []
        used = set()
        for p1 in needy:
            if len(pairs) >= MATCHES_PER_ROUND or p1 in used:
                continue
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
            winner = sim_match(p1, p2, true_strengths)
            loser = p2 if winner == p1 else p1
            (nr1,), (nr2,) = env.rate([(ratings[winner],), (ratings[loser],)], ranks=[0, 1])
            ratings[winner] = nr1
            ratings[loser] = nr2
            stats[winner]["wins"] += 1; stats[winner]["comparisons"] += 1
            stats[loser]["losses"] += 1; stats[loser]["comparisons"] += 1
            if p1.startswith("new_") or p2.startswith("new_"):
                total_new_matches += 1

        # Metrics for new papers only
        new_needy = sum(1 for p in new_papers if urgency(p) > 0)
        perfect_new = [p for p in new_papers if stats[p]["comparisons"] > 0 and stats[p]["wins"] == stats[p]["comparisons"]]
        new_avg_comps = sum(stats[p]["comparisons"] for p in new_papers) / N_NEW
        new_avg_sigma = sum(ratings[p].sigma for p in new_papers) / N_NEW

        # Ranking accuracy for new papers
        new_scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in new_papers}
        new_est_ranking = sorted(new_papers, key=lambda p: -new_scores[p])
        new_est_rank = {p: i+1 for i, p in enumerate(new_est_ranking)}
        tau_new = kendall_tau(new_true_rank, new_est_rank)

        all_scores = {p: (ratings[p].mu - 3 * ratings[p].sigma) for p in all_papers}
        all_est_ranking = sorted(all_papers, key=lambda p: -all_scores[p])
        all_est_rank = {p: i+1 for i, p in enumerate(all_est_ranking)}
        tau_all = kendall_tau(true_rank, all_est_rank)

        history.append({
            "round": round_num+1, "matches": len(pairs), "total": total_new_matches,
            "new_needy": new_needy, "perfect_new": len(perfect_new),
            "tau_new": tau_new, "tau_all": tau_all,
            "new_avg_comps": new_avg_comps, "new_avg_sigma": new_avg_sigma,
        })

    return history, ratings, stats, est_avg_sigma, est_avg_comps


true_strengths = setup()
print(f"=== {N_ESTABLISHED} established + {N_NEW} new papers ===")
new_strs = [f'{true_strengths[f"new_{i}"]:.1f}' for i in range(N_NEW)]
print(f"New paper strengths: {', '.join(new_strs)}")
print()

h1, r1, s1, es1, ec1 = run("Current", False, true_strengths)
h2, r2, s2, es2, ec2 = run("Undefeated-Urgency", True, true_strengths)

print(f"Established papers pre-state: avg_sigma={es1:.2f}, avg_comps={ec1:.0f}")
print()

print(f"{'Rnd':>3} │ {'Current':^40} │ {'Undefeated-Urgency':^40} │")
print(f"{'':>3} │ {'tau_new':>7} {'needy':>5} {'100%':>4} {'comps':>5} {'sigma':>5} {'mtch':>5} │ {'tau_new':>7} {'needy':>5} {'100%':>4} {'comps':>5} {'sigma':>5} {'mtch':>5} │")
print("─" * 95)

for i in range(max(len(h1), len(h2))):
    a = h1[i] if i < len(h1) else None
    b = h2[i] if i < len(h2) else None
    def fmt(x):
        if x is None: return " " * 40
        return f"{x['tau_new']:>7.3f} {x['new_needy']:>5} {x['perfect_new']:>4} {x['new_avg_comps']:>5.1f} {x['new_avg_sigma']:>5.2f} {x['total']:>5}"
    print(f"{i+1:>3} │ {fmt(a)} │ {fmt(b)} │")

print("\n=== FINAL: New papers detail ===")
for name, r, s in [("Current", r1, s1), ("Undefeated", r2, s2)]:
    print(f"\n  {name}:")
    new_papers = sorted([p for p in true_strengths if p.startswith("new_")], key=lambda p: -true_strengths[p])
    for p in new_papers:
        ts = true_strengths[p]
        sc = r[p].mu - 3 * r[p].sigma
        sig = r[p].sigma
        w, c = s[p]["wins"], s[p]["comparisons"]
        wr = w/c*100 if c else 0
        marker = " *** 100%WR" if w == c and c > 0 else ""
        print(f"    {p} true={ts:.1f}: score={sc:.1f} σ={sig:.2f} comps={c} WR={wr:.0f}%{marker}")
