"""
Simulation: Closest-Score vs TrueSkill Quality vs Quality + Undefeated Urgency

80 established papers + 20 new papers (including 1 dominant at true=55).
Compares opponent selection strategies on ranking accuracy, match efficiency,
and handling of 100% WR papers.
"""
import random
import math
import trueskill

N_EST, N_NEW = 80, 20
N_ROUNDS = 30
MATCHES_PER_ROUND = 30
SIGMA_TARGET = 2.5
FLOOR = 50
SEED = 42


def setup():
    random.seed(SEED)
    ts = {}
    for i in range(N_EST):
        ts[f"est_{i}"] = random.gauss(25, 6)
    for i in range(N_NEW):
        if i == 0:
            ts[f"new_{i}"] = 55.0  # dominant
        elif i < 3:
            ts[f"new_{i}"] = random.gauss(38, 2)
        elif i < 8:
            ts[f"new_{i}"] = random.gauss(32, 2)
        else:
            ts[f"new_{i}"] = random.gauss(25, 4)
    return ts


def sim_match(p1, p2, ts):
    s1, s2 = ts[p1], ts[p2]
    return p1 if random.random() < 1 / (1 + math.exp(-(s1 - s2) / 4)) else p2


def kendall_tau(ra, rb):
    papers = list(ra.keys())
    c = d = 0
    for i in range(len(papers)):
        for j in range(i + 1, len(papers)):
            da = ra[papers[i]] - ra[papers[j]]
            db = rb[papers[i]] - rb[papers[j]]
            if da * db > 0: c += 1
            elif da * db < 0: d += 1
    return (c - d) / (c + d) if (c + d) > 0 else 0


def pre_converge(ts, env):
    """Pre-converge established papers with 100 rounds of random pairing."""
    ratings = {p: env.create_rating() for p in ts}
    stats = {p: {"wins": 0, "losses": 0, "comparisons": 0} for p in ts}
    est = [p for p in ts if p.startswith("est_")]
    for _ in range(100):
        random.shuffle(est)
        for i in range(0, len(est) - 1, 2):
            w = sim_match(est[i], est[i + 1], ts)
            l = est[i + 1] if w == est[i] else est[i]
            (nr1,), (nr2,) = env.rate([(ratings[w],), (ratings[l],)], ranks=[0, 1])
            ratings[w] = nr1; ratings[l] = nr2
            stats[w]["wins"] += 1; stats[w]["comparisons"] += 1
            stats[l]["losses"] += 1; stats[l]["comparisons"] += 1
    return ratings, stats


def run(name, select_fn, use_undefeated, ts, base_ratings, base_stats):
    random.seed(SEED)
    env = trueskill.TrueSkill(draw_probability=0.0)
    all_p = list(ts.keys())
    new_p = [p for p in all_p if p.startswith("new_")]

    # Clone base state, reset new papers
    ratings = {p: (base_ratings[p] if p.startswith("est_") else env.create_rating()) for p in all_p}
    stats = {p: (dict(base_stats[p]) if p.startswith("est_") else {"wins": 0, "losses": 0, "comparisons": 0}) for p in all_p}

    true_ranking = sorted(all_p, key=lambda p: -ts[p])
    true_rank = {p: i + 1 for i, p in enumerate(true_ranking)}
    new_true_ranking = sorted(new_p, key=lambda p: -ts[p])
    new_true_rank = {p: i + 1 for i, p in enumerate(new_true_ranking)}

    history = []
    total_new_matches = 0

    for rnd in range(N_ROUNDS):
        scores = {p: ratings[p].mu - 3 * ratings[p].sigma for p in all_p}
        sigmas = {p: ratings[p].sigma for p in all_p}
        sv = sorted(scores.values())
        med = sv[len(sv) // 2]

        def urgency(p):
            if stats[p]["comparisons"] == 0: return 999
            if stats[p]["comparisons"] >= FLOOR: return 0
            ex = sigmas[p] - SIGMA_TARGET
            if ex > 0: return ex
            if use_undefeated:
                w, c = stats[p]["wins"], stats[p]["comparisons"]
                if w == c or w == 0: return 0.1
            return 0

        needy = sorted(all_p, key=lambda p: urgency(p), reverse=True)
        needy = [p for p in needy if urgency(p) > 0]
        established = [p for p in all_p if urgency(p) == 0]
        if not needy:
            break

        pairs = []; used = set()
        for p1 in needy:
            if len(pairs) >= MATCHES_PER_ROUND or p1 in used: continue
            candidates = [p2 for p2 in all_p if p2 != p1 and p2 not in used]
            if not candidates: continue
            best = select_fn(p1, candidates, ratings, scores, stats, med)
            if best:
                pairs.append((p1, best)); used.add(p1); used.add(best)

        for p1, p2 in pairs:
            w = sim_match(p1, p2, ts); l = p2 if w == p1 else p1
            (nr1,), (nr2,) = env.rate([(ratings[w],), (ratings[l],)], ranks=[0, 1])
            ratings[w] = nr1; ratings[l] = nr2
            stats[w]["wins"] += 1; stats[w]["comparisons"] += 1
            stats[l]["losses"] += 1; stats[l]["comparisons"] += 1
            if p1.startswith("new_") or p2.startswith("new_"):
                total_new_matches += 1

        # Metrics
        new_scores = {p: ratings[p].mu - 3 * ratings[p].sigma for p in new_p}
        new_est_ranking = sorted(new_p, key=lambda p: -new_scores[p])
        new_est_rank = {p: i + 1 for i, p in enumerate(new_est_ranking)}
        tau_new = kendall_tau(new_true_rank, new_est_rank)

        all_scores = {p: ratings[p].mu - 3 * ratings[p].sigma for p in all_p}
        all_ranking = sorted(all_p, key=lambda p: -all_scores[p])
        all_rank = {p: i + 1 for i, p in enumerate(all_ranking)}
        tau_all = kendall_tau(true_rank, all_rank)

        perfect = [p for p in new_p if stats[p]["comparisons"] > 0 and stats[p]["wins"] == stats[p]["comparisons"]]
        new_avg_comps = sum(stats[p]["comparisons"] for p in new_p) / N_NEW
        new_avg_sigma = sum(ratings[p].sigma for p in new_p) / N_NEW

        history.append({
            "round": rnd + 1, "total": total_new_matches,
            "tau_new": tau_new, "tau_all": tau_all,
            "new_needy": len([p for p in needy if p.startswith("new_")]),
            "perfect": len(perfect), "avg_comps": new_avg_comps,
            "avg_sigma": new_avg_sigma,
        })

    return history, ratings, stats


# ─── Selection Functions ───

def select_closest(p1, candidates, ratings, scores, stats, median):
    """Current: closest score."""
    target = scores[p1] if stats[p1]["comparisons"] > 0 else median
    return min(candidates, key=lambda p2: abs(scores[p2] - target))


def select_quality(p1, candidates, ratings, scores, stats, median):
    """TrueSkill quality_1vs1: pick opponent maximizing match quality."""
    return max(candidates, key=lambda p2: trueskill.quality_1vs1(ratings[p1], ratings[p2]))


# ─── Run All Three ───

ts = setup()
env = trueskill.TrueSkill(draw_probability=0.0)
random.seed(SEED)
base_r, base_s = pre_converge(ts, env)

strategies = [
    ("Closest-Score", select_closest, False),
    ("Quality", select_quality, False),
    ("Quality+Undefeated", select_quality, True),
]

results = {}
for name, fn, undef in strategies:
    h, r, s = run(name, fn, undef, ts, base_r, base_s)
    results[name] = (h, r, s)

# ─── Print Comparison ───

print(f"=== {N_EST} established + {N_NEW} new papers (1 dominant at true=55) ===\n")

# Round-by-round
header_names = [n for n, _, _ in strategies]
col_w = 28
print(f"{'Rnd':>3} │", end="")
for n in header_names:
    print(f" {n:^{col_w}} │", end="")
print()
print(f"{'':>3} │", end="")
for _ in header_names:
    print(f" {'tau':>5} {'100%':>4} {'cmps':>5} {'σ':>5} {'mtch':>5} │", end="")
print()
print("─" * (6 + (col_w + 3) * len(header_names)))

max_rounds = max(len(results[n][0]) for n in header_names)
for i in range(max_rounds):
    print(f"{i+1:>3} │", end="")
    for n in header_names:
        h = results[n][0]
        if i < len(h):
            d = h[i]
            print(f" {d['tau_new']:>5.3f} {d['perfect']:>4} {d['avg_comps']:>5.1f} {d['avg_sigma']:>5.2f} {d['total']:>5} │", end="")
        else:
            print(f" {'DONE':^{col_w}} │", end="")
    print()

# Final summary
print(f"\n{'='*80}")
print(f"{'Strategy':<25} {'Matches':>7} {'tau_new':>8} {'tau_all':>8} {'Top5':>5} {'100%WR':>6}")
print("-" * 80)

for name in header_names:
    h, r, s = results[name]
    last = h[-1]
    new_p = [p for p in ts if p.startswith("new_")]
    current_scores = {p: r[p].mu - 3 * r[p].sigma for p in ts}
    ranking = sorted(ts.keys(), key=lambda p: -current_scores[p])
    true_ranking = sorted(ts.keys(), key=lambda p: -ts[p])
    true_rank_map = {p: i+1 for i, p in enumerate(true_ranking)}
    top5 = sum(1 for i, p in enumerate(ranking[:5]) if true_rank_map[p] <= 5)
    perfect = sum(1 for p in new_p if s[p]["comparisons"] > 0 and s[p]["wins"] == s[p]["comparisons"])
    print(f"{name:<25} {last['total']:>7} {last['tau_new']:>8.4f} {last['tau_all']:>8.4f} {top5:>4}/5 {perfect:>6}")

# Dominant paper detail
print(f"\n=== DOMINANT PAPER (new_0, true=55.0) ===")
for name in header_names:
    _, r, s = results[name]
    p = "new_0"
    sc = r[p].mu - 3 * r[p].sigma
    sig = r[p].sigma
    w, c = s[p]["wins"], s[p]["comparisons"]
    wr = w / c * 100 if c else 0
    print(f"  {name:<25} score={sc:>6.1f}  σ={sig:.2f}  comps={c:>3}  WR={wr:.0f}%")

# Strong papers (new_1, new_2)
print(f"\n=== STRONG PAPERS ===")
for p in ["new_1", "new_2"]:
    true_s = ts[p]
    print(f"  {p} (true={true_s:.1f}):")
    for name in header_names:
        _, r, s = results[name]
        sc = r[p].mu - 3 * r[p].sigma
        sig = r[p].sigma
        w, c = s[p]["wins"], s[p]["comparisons"]
        wr = w / c * 100 if c else 0
        print(f"    {name:<25} score={sc:>6.1f}  σ={sig:.2f}  comps={c:>3}  WR={wr:.0f}%")
