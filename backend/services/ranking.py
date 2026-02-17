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


def calculate_bt_confidence_intervals(
    matches: List[dict], paper_ids: List[str], confidence_level: float = 0.95,
) -> Dict[str, Dict]:
    """Compute Bradley-Terry confidence intervals using the observed Fisher information.
    
    Matches should be pre-filtered (completed=True, failed!=True).
    Returns per-paper: {bt_score, win_prob, bt_ci_lower, bt_ci_upper, bt_ci_width}
    """
    n = len(paper_ids)
    if n < 2:
        return {pid: {"bt_score": 1.0, "win_prob": 0.5, "bt_ci_lower": 0.0, "bt_ci_upper": 1.0, "bt_ci_width": 1.0} for pid in paper_ids}

    # Build pairwise win counts
    pid_to_idx = {pid: i for i, pid in enumerate(paper_ids)}
    pid_set = set(paper_ids)
    wins = {pid: 0 for pid in paper_ids}
    comparisons = {pid: 0 for pid in paper_ids}
    win_matrix = np.zeros((n, n))

    for m in matches:
        p1, p2 = m.get("paper1_id"), m.get("paper2_id")
        w = m.get("winner_id")
        if not (p1 and p2 and w and p1 in pid_set and p2 in pid_set):
            continue
        i, j = pid_to_idx[p1], pid_to_idx[p2]
        comparisons[p1] = comparisons.get(p1, 0) + 1
        comparisons[p2] = comparisons.get(p2, 0) + 1
        wins[w] = wins.get(w, 0) + 1
        if w == p1:
            win_matrix[i][j] += 1
        else:
            win_matrix[j][i] += 1

    total_matches = sum(comparisons.values()) // 2
    if total_matches < n:
        return {pid: {"bt_score": 1.0, "win_prob": 0.5, "bt_ci_lower": 0.0, "bt_ci_upper": 1.0, "bt_ci_width": 1.0} for pid in paper_ids}

    # Compute BT scores via iterative algorithm (same as calculate_bradley_terry but inline)
    scores = np.ones(n)
    paper_opp = [[] for _ in range(n)]  # (opponent_idx, n_matches) pairs
    for i in range(n):
        for j in range(n):
            n_ij = win_matrix[i][j] + win_matrix[j][i]
            if n_ij > 0 and i != j:
                paper_opp[i].append((j, n_ij))

    for _ in range(100):
        new_scores = np.zeros(n)
        for i in range(n):
            w_i = wins.get(paper_ids[i], 0)
            if w_i == 0:
                new_scores[i] = 1e-6
                continue
            denom = sum(n_ij / (scores[i] + scores[j]) for j, n_ij in paper_opp[i])
            new_scores[i] = w_i / denom if denom > 0 else scores[i]
        # Normalize
        total = new_scores.sum()
        if total > 0:
            new_scores = new_scores / total * n
        # Check convergence BEFORE overwriting scores
        if np.max(np.abs(scores - new_scores)) < 1e-8:
            scores = new_scores
            break
        scores = new_scores

    # Fisher information matrix (n-1 free params, last is reference)
    m_size = n - 1
    fisher = np.zeros((m_size, m_size))
    for i in range(n):
        for j in range(i + 1, n):
            n_ij = win_matrix[i][j] + win_matrix[j][i]
            if n_ij == 0:
                continue
            p_ij = scores[i] / (scores[i] + scores[j])
            info = n_ij * p_ij * (1 - p_ij)
            if i < m_size:
                fisher[i][i] += info
            if j < m_size:
                fisher[j][j] += info
            if i < m_size and j < m_size:
                fisher[i][j] -= info
                fisher[j][i] -= info

    z = scipy_stats.norm.ppf(1 - (1 - confidence_level) / 2)
    results = {}

    try:
        fisher += np.eye(m_size) * 1e-6
        cov = np.linalg.inv(fisher)
        mean_score = scores.mean()

        for i, pid in enumerate(paper_ids):
            sc = float(scores[i])
            se = float(math.sqrt(max(float(cov[i][i]), 0))) if i < m_size else 0.0

            win_prob = sc / (sc + mean_score)
            deriv = sc * mean_score / (sc + mean_score) ** 2
            win_prob_se = deriv * se

            lower = max(0.0, win_prob - z * win_prob_se)
            upper = min(1.0, win_prob + z * win_prob_se)
            width = upper - lower

            results[pid] = {
                "bt_score": round(sc, 4),
                "win_prob": round(win_prob, 4),
                "bt_ci_lower": round(lower, 4),
                "bt_ci_upper": round(upper, 4),
                "bt_ci_width": round(width, 4),
            }
    except Exception as e:
        import logging
        logging.getLogger("papersumo").warning(f"BT CI computation failed: {type(e).__name__}: {e}")
        for pid in paper_ids:
            results[pid] = {"bt_score": 1.0, "win_prob": 0.5, "bt_ci_lower": 0.0, "bt_ci_upper": 1.0, "bt_ci_width": 1.0}

    return results


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
