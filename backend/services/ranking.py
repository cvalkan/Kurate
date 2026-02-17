import math
import numpy as np
from typing import Dict, List, Optional, Tuple
from scipy import stats as scipy_stats


def calculate_bradley_terry(matches: List[dict], paper_ids: List[str]) -> Dict[str, float]:
    n = len(paper_ids)
    if n == 0:
        return {}

    pid_set = set(paper_ids)
    scores = {pid: 1.0 for pid in paper_ids}
    wins = {pid: 0 for pid in paper_ids}
    comparisons = {pid: 0 for pid in paper_ids}

    # Pre-filter valid matches and index by paper
    valid_matches = []
    paper_matches = {pid: [] for pid in paper_ids}  # pid -> list of (opponent_pid, match_idx)

    for match in matches:
        if match.get("completed") and match.get("winner_id") and not match.get("failed"):
            p1, p2 = match["paper1_id"], match["paper2_id"]
            if p1 not in pid_set or p2 not in pid_set:
                continue
            winner = match["winner_id"]
            idx = len(valid_matches)
            valid_matches.append((p1, p2))
            if winner in wins:
                wins[winner] += 1
            if p1 in comparisons:
                comparisons[p1] += 1
                paper_matches[p1].append(idx)
            if p2 in comparisons:
                comparisons[p2] += 1
                paper_matches[p2].append(idx)

    for _ in range(50):
        new_scores = {}
        for pid in paper_ids:
            if comparisons.get(pid, 0) > 0:
                denominator = 0.0
                for midx in paper_matches[pid]:
                    p1, p2 = valid_matches[midx]
                    denominator += 1.0 / (scores.get(p1, 1.0) + scores.get(p2, 1.0))
                if denominator > 0:
                    new_scores[pid] = wins.get(pid, 0) / denominator
                else:
                    new_scores[pid] = scores[pid]
            else:
                new_scores[pid] = scores[pid]

        total = sum(new_scores.values())
        if total > 0:
            scores = {k: v / total * n for k, v in new_scores.items()}
        else:
            scores = new_scores

    return scores


def calculate_confidence_interval(wins: int, comparisons: int, confidence_level: float = 0.95) -> Dict:
    if comparisons == 0:
        return {
            "win_rate": 0.5,
            "lower_bound": 0.0,
            "upper_bound": 1.0,
            "margin_of_error": 0.5,
            "confidence_level": confidence_level,
            "comparisons": 0,
        }

    p = wins / comparisons
    n = comparisons
    z = scipy_stats.norm.ppf(1 - (1 - confidence_level) / 2)

    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

    lower = max(0, center - spread)
    upper = min(1, center + spread)

    return {
        "win_rate": round(p, 4),
        "lower_bound": round(lower, 4),
        "upper_bound": round(upper, 4),
        "margin_of_error": round((upper - lower) / 2, 4),
        "confidence_level": confidence_level,
        "comparisons": comparisons,
    }


def compute_leaderboard(papers: List[dict], matches: List[dict]) -> List[dict]:
    paper_ids = [p["id"] for p in papers]
    ELO_BASE = 1200

    if not paper_ids or not matches:
        return [
            {
                "id": p["id"],
                "rank": i + 1,
                "title": p["title"],
                "authors": p.get("authors", []),
                "arxiv_id": p.get("arxiv_id", ""),
                "link": p.get("link", ""),
                "published": p.get("published", ""),
                "score": ELO_BASE,
                "ci": 0,
                "wins": 0,
                "losses": 0,
                "comparisons": 0,
                "confidence": calculate_confidence_interval(0, 0),
            }
            for i, p in enumerate(papers)
        ]

    _bt_scores = calculate_bradley_terry(matches, paper_ids)  # noqa: F841 — computed for model validation

    stats = {pid: {"wins": 0, "losses": 0, "comparisons": 0} for pid in paper_ids}
    for match in matches:
        if match.get("completed") and match.get("winner_id") and not match.get("failed"):
            p1, p2 = match["paper1_id"], match["paper2_id"]
            winner = match["winner_id"]
            loser = p2 if winner == p1 else p1
            if winner in stats:
                stats[winner]["wins"] += 1
                stats[winner]["comparisons"] += 1
            if loser in stats:
                stats[loser]["losses"] += 1
                stats[loser]["comparisons"] += 1

    elo_scores = {}
    elo_ci = {}
    for pid in paper_ids:
        s = stats.get(pid, {"wins": 0, "comparisons": 0})
        w, n = s["wins"], s["comparisons"]

        if n == 0:
            elo_scores[pid] = ELO_BASE
            elo_ci[pid] = 0
            continue

        # Regularized win rate (Jeffreys prior: add 0.5 wins and 0.5 losses)
        p_reg = (w + 0.5) / (n + 1.0)
        p_reg = max(0.02, min(0.98, p_reg))

        # Elo from logistic: Elo = 400 * log10(p/(1-p)) + base
        elo = 400.0 * math.log10(p_reg / (1.0 - p_reg)) + ELO_BASE
        elo_scores[pid] = round(elo)

        # 95% CI in Elo points
        se_logit = 1.0 / math.sqrt((n + 1.0) * p_reg * (1.0 - p_reg))
        se_elo = (400.0 / math.log(10)) * se_logit
        ci = round(1.96 * se_elo)
        elo_ci[pid] = min(ci, 400)  # Cap at 400

    paper_lookup = {p["id"]: p for p in papers}
    ranked = sorted(paper_ids, key=lambda pid: elo_scores.get(pid, ELO_BASE), reverse=True)

    leaderboard = []
    for rank, pid in enumerate(ranked, 1):
        p = paper_lookup.get(pid)
        if not p:
            continue
        s = stats.get(pid, {"wins": 0, "losses": 0, "comparisons": 0})
        w, n = s["wins"], s["comparisons"]

        # Wilson CI margin (same metric used for goal convergence)
        wilson_m = wilson_margin_pct(w, n)

        # Win rate
        win_rate = round(100 * w / n, 1) if n > 0 else 0

        leaderboard.append({
            "id": pid,
            "rank": rank,
            "title": p["title"],
            "authors": p.get("authors", []),
            "arxiv_id": p.get("arxiv_id", ""),
            "link": p.get("link", ""),
            "published": p.get("published", ""),
            "score": elo_scores.get(pid, ELO_BASE),
            "ci": elo_ci.get(pid, 0),
            "wilson_margin": wilson_m,
            "win_rate": win_rate,
            "wins": s["wins"],
            "losses": s["losses"],
            "comparisons": s["comparisons"],
        })

    return leaderboard


def wilson_margin_pct(wins, comparisons):
    """Wilson CI half-width as percentage points (e.g. 5.2 means +/-5.2%). Single source of truth."""
    from scipy import stats as scipy_stats
    if comparisons == 0:
        return 0
    p = wins / comparisons
    n = comparisons
    z = scipy_stats.norm.ppf(0.975)
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * ((p * (1 - p) + z**2 / (4 * n)) / n) ** 0.5 / denom
    lower = max(0, center - spread)
    upper = min(1, center + spread)
    return round((upper - lower) / 2 * 100, 1)
