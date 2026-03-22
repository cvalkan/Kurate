import math
import asyncio
import concurrent.futures
import numpy as np
from typing import Dict, List, Optional, Tuple
from scipy import stats as scipy_stats

# Shared thread pool for CPU-bound leaderboard computations.
# This keeps heavy math OFF the async event loop so HTTP requests never stall.
_compute_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="lb-compute")


def calculate_bradley_terry(matches: List[dict], paper_ids: List[str], prior_strength: float = 2.0) -> Dict[str, float]:
    """BT MLE with optional regularization prior.
    
    prior_strength > 0 adds virtual matches: each paper beats a phantom opponent
    with `prior_strength` virtual wins, preventing degenerate scores for papers
    with few or zero wins. Equivalent to a Dirichlet prior on BT strengths.
    Set prior_strength=0 for pure MLE (only suitable with 50+ matches/paper).
    """
    n = len(paper_ids)
    if n == 0:
        return {}

    pid_set = set(paper_ids)
    scores = {pid: 1.0 for pid in paper_ids}
    wins = {pid: prior_strength for pid in paper_ids}  # Prior: virtual wins
    comparisons = {pid: 2 * prior_strength for pid in paper_ids}  # Prior: virtual matches

    # Pre-filter valid matches and index by paper
    valid_matches = []
    paper_matches = {pid: [] for pid in paper_ids}  # pid -> list of match indices

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
                # BT update: include prior contribution
                denominator = prior_strength / (scores.get(pid, 1.0) + 1.0)  # Prior: vs phantom with strength 1.0
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


def compute_weighted_bt(matches: List[dict], paper_ids: List[str], weight_fn=None) -> Dict[str, float]:
    """Compute Elo scores with per-match fractional weights in the likelihood.
    
    Unlike match duplication, this properly weights the BT likelihood:
    weighted_wins = sum(weight_i * win_i), weighted_n = sum(weight_i)
    Then applies the same regularized Elo formula.
    
    weight_fn: callable(match_dict) -> float weight >= 0. Default: uniform (1.0).
    Returns: {paper_id: elo_score}
    """
    SCORE_BASE = 1200
    if not paper_ids or not matches:
        return {pid: SCORE_BASE for pid in paper_ids}
    
    pid_set = set(paper_ids)
    stats = {pid: {"w": 0.0, "n": 0.0} for pid in paper_ids}
    
    for m in matches:
        p1, p2 = m.get("paper1_id"), m.get("paper2_id")
        winner = m.get("winner_id")
        if not (p1 and p2 and winner):
            continue
        if p1 not in pid_set or p2 not in pid_set:
            continue
        
        weight = weight_fn(m) if weight_fn else 1.0
        if weight <= 0:
            continue
        
        winner = m["winner_id"]
        loser = p2 if winner == p1 else p1
        
        if winner in stats:
            stats[winner]["w"] += weight
            stats[winner]["n"] += weight
        if loser in stats:
            stats[loser]["n"] += weight
    
    scores = {}
    for pid in paper_ids:
        s = stats[pid]
        if s["n"] == 0:
            scores[pid] = SCORE_BASE
            continue
        # Same regularized Elo but with fractional wins/comparisons
        p_reg = (s["w"] + 0.5) / (s["n"] + 1.0)
        p_reg = max(0.02, min(0.98, p_reg))
        scores[pid] = round(400.0 * math.log10(p_reg / (1.0 - p_reg)) + SCORE_BASE)
    
    return scores


async def compute_weighted_bt_async(matches, paper_ids, weight_fn=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_compute_pool, compute_weighted_bt, matches, paper_ids, weight_fn)




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


def _bt_to_score(bt_scores: Dict[str, float], base: int = 1200) -> Dict[str, int]:
    """Convert raw BT strengths to Elo-scale scores for display.
    Maps BT strengths to a familiar range (~800-1600) by converting each paper's
    implied win probability vs the average opponent to an Elo score."""
    if not bt_scores:
        return {}
    vals = [v for v in bt_scores.values() if v > 0]
    if not vals:
        return {pid: base for pid in bt_scores}
    # Average strength = geometric mean (since BT is multiplicative)
    avg = math.exp(sum(math.log(max(v, 1e-10)) for v in vals) / len(vals))
    scores = {}
    for pid, strength in bt_scores.items():
        if strength <= 0 or avg <= 0:
            scores[pid] = base - 400
        else:
            # Win probability vs average opponent: p = s / (s + avg)
            p = strength / (strength + avg)
            p = max(0.02, min(0.98, p))
            scores[pid] = round(400.0 * math.log10(p / (1.0 - p)) + base)
    return scores


def compute_leaderboard(papers: List[dict], matches: List[dict]) -> List[dict]:
    paper_ids = [p["id"] for p in papers]
    SCORE_BASE = 1200

    if not paper_ids or not matches:
        import hashlib
        sorted_papers = sorted(papers, key=lambda p: hashlib.md5(p["title"].encode()).hexdigest(), reverse=True)
        return [
            {
                "id": p["id"],
                "rank": i + 1,
                "title": p["title"],
                "authors": p.get("authors", []),
                "arxiv_id": p.get("arxiv_id", ""),
                "link": p.get("link", ""),
                "published": p.get("published", ""),
                "score": SCORE_BASE,
                "ci": 0,
                "wins": 0,
                "losses": 0,
                "comparisons": 0,
                "confidence": calculate_confidence_interval(0, 0),
            }
            for i, p in enumerate(sorted_papers)
        ]

    # Compute win/loss stats
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

    # Ranking via regularized win-rate.
    # Equivalent to a Bayesian posterior with a Jeffreys prior (assumes all opponents
    # equally strong). This is optimal for sparse data (<50 matches/paper) where opponent
    # strength cannot be reliably estimated.
    wr_scores = {}
    for pid in paper_ids:
        s = stats.get(pid, {"wins": 0, "comparisons": 0})
        w, n = s["wins"], s["comparisons"]
        if n == 0:
            wr_scores[pid] = SCORE_BASE
        else:
            p_reg = (w + 0.5) / (n + 1.0)
            p_reg = max(0.02, min(0.98, p_reg))
            wr_scores[pid] = round(400.0 * math.log10(p_reg / (1.0 - p_reg)) + SCORE_BASE)

    # CI from win-rate (simpler to compute than BT Fisher information)
    wr_ci = {}
    for pid in paper_ids:
        s = stats.get(pid, {"wins": 0, "comparisons": 0})
        w, n = s["wins"], s["comparisons"]
        if n == 0:
            wr_ci[pid] = 0
            continue
        p_reg = (w + 0.5) / (n + 1.0)
        p_reg = max(0.02, min(0.98, p_reg))
        se_logit = 1.0 / math.sqrt((n + 1.0) * p_reg * (1.0 - p_reg))
        se_elo = (400.0 / math.log(10)) * se_logit
        wr_ci[pid] = min(round(1.96 * se_elo), 400)

    paper_lookup = {p["id"]: p for p in papers}
    # Deterministic tiebreaker for papers with equal scores (e.g., all at 1200 with 0 matches)
    # Uses title hash so the ordering is stable across subsample sizes
    import hashlib
    def _title_hash(pid):
        title = paper_lookup.get(pid, {}).get("title", pid)
        return hashlib.md5(title.encode()).hexdigest()
    ranked = sorted(paper_ids, key=lambda pid: (wr_scores.get(pid, SCORE_BASE), _title_hash(pid)), reverse=True)

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
            "score": wr_scores.get(pid, SCORE_BASE),
            "ci": wr_ci.get(pid, 0),
            "wilson_margin": wilson_m,
            "win_rate": win_rate,
            "wins": s["wins"],
            "losses": s["losses"],
            "comparisons": s["comparisons"],
        })

    return leaderboard


async def compute_leaderboard_async(papers: List[dict], matches: List[dict]) -> List[dict]:
    """Run compute_leaderboard in a thread pool so the event loop is never blocked."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_compute_pool, compute_leaderboard, papers, matches)


# Pre-compute the z-value (constant) to avoid repeated scipy calls
_WILSON_Z = scipy_stats.norm.ppf(0.975)


def wilson_margin_pct(wins, comparisons):
    """Wilson CI half-width as percentage points (e.g. 5.2 means +/-5.2%). Single source of truth."""
    if comparisons == 0:
        return 100  # No data = maximum uncertainty
    p = wins / comparisons
    n = comparisons
    z = _WILSON_Z
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * ((p * (1 - p) + z**2 / (4 * n)) / n) ** 0.5 / denom
    lower = max(0, center - spread)
    upper = min(1, center + spread)
    return round((upper - lower) / 2 * 100, 1)


# ─── DB-Backed Rankings (Phase 1 of Option 3) ────────────────────────────────
# The `rankings` collection stores pre-computed scores and ranks per paper.
# Updated incrementally on each match completion. Serves leaderboard queries
# directly from indexed DB queries — O(1) memory regardless of paper count.

SCORE_BASE_CONST = 1200  # Same base as compute_leaderboard


def compute_paper_score(wins: int, comparisons: int) -> dict:
    """Compute score, CI, wilson_margin, win_rate for a single paper.
    
    Mathematically identical to compute_leaderboard's per-paper logic.
    Used for incremental updates (2 papers per match) instead of full recomputation.
    """
    if comparisons == 0:
        return {"score": SCORE_BASE_CONST, "ci": 0, "wilson_margin": 100.0, "win_rate": 0.0}

    w, n = wins, comparisons
    p_reg = (w + 0.5) / (n + 1.0)
    p_reg = max(0.02, min(0.98, p_reg))
    score = round(400.0 * math.log10(p_reg / (1.0 - p_reg)) + SCORE_BASE_CONST)

    se_logit = 1.0 / math.sqrt((n + 1.0) * p_reg * (1.0 - p_reg))
    se_elo = (400.0 / math.log(10)) * se_logit
    ci = min(round(1.96 * se_elo), 400)

    wm = wilson_margin_pct(w, n)
    wr = round(100 * w / n, 1)

    return {"score": score, "ci": ci, "wilson_margin": wm, "win_rate": wr}


async def seed_rankings(db, category: str = None):
    """Seed the rankings collection from current papers + matches.
    
    Runs compute_leaderboard per category and inserts the results.
    Idempotent: uses upsert on paper_id.
    """
    from routers.validation_utils import collect_all
    from core.auth import get_settings
    from core.config import CATEGORIES

    settings = await get_settings()
    if category:
        cats = [category]
    else:
        cats = settings.get("active_categories", list(CATEGORIES.keys()))

    total_seeded = 0
    for cat in cats:
        papers = await collect_all(db.papers.find(
            {"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}},
            {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
             "link": 1, "published": 1, "added_at": 1, "categories": 1,
             "ai_rating": 1},
        ))
        if not papers:
            continue

        matches = await collect_all(db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": cat,
             "mode": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
             "completed": 1, "failed": 1},
        ))

        lb = compute_leaderboard(papers, matches)

        # Bulk upsert into rankings
        from pymongo import UpdateOne
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

        # Build ai_rating lookup
        ai_ratings = {}
        for p in papers:
            r = p.get("ai_rating")
            if r and isinstance(r, dict) and r.get("score"):
                ai_ratings[p["id"]] = round(r["score"], 1)
            elif r and isinstance(r, (int, float)):
                ai_ratings[p["id"]] = round(r, 1)

        ops = []
        for entry in lb:
            doc = {
                "paper_id": entry["id"],
                "category": cat,
                "rank": entry["rank"],
                "score": entry["score"],
                "ci": entry["ci"],
                "wilson_margin": entry.get("wilson_margin", 100.0),
                "win_rate": entry.get("win_rate", 0.0),
                "wins": entry["wins"],
                "losses": entry["losses"],
                "comparisons": entry["comparisons"],
                "title": entry["title"],
                "authors": entry.get("authors", []),
                "arxiv_id": entry.get("arxiv_id", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "added_at": entry.get("added_at", ""),
                "categories": next((p.get("categories", []) for p in papers if p["id"] == entry["id"]), [cat]),
                "ai_rating": ai_ratings.get(entry["id"]),
                "updated_at": now_iso,
            }
            ops.append(UpdateOne(
                {"paper_id": entry["id"]},
                {"$set": doc},
                upsert=True,
            ))

        if ops:
            await db.rankings.bulk_write(ops, ordered=False)
            total_seeded += len(ops)

        await asyncio.sleep(0)  # Yield between categories

    return total_seeded


async def update_rankings_for_match(db, category: str, winner_id: str, loser_id: str):
    """Incrementally update rankings after a single match completes.
    
    Updates only the 2 affected papers' scores. O(1) per match.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    for paper_id, is_winner in [(winner_id, True), (loser_id, False)]:
        inc_fields = {"comparisons": 1}
        if is_winner:
            inc_fields["wins"] = 1
        else:
            inc_fields["losses"] = 1

        # Atomic increment + fetch updated stats
        doc = await db.rankings.find_one_and_update(
            {"paper_id": paper_id, "category": category},
            {"$inc": inc_fields, "$set": {"updated_at": now_iso}},
            return_document=True,  # Return the document AFTER update
            projection={"_id": 0, "wins": 1, "comparisons": 1},
        )

        if doc:
            # Recompute score from updated stats
            new_stats = compute_paper_score(doc["wins"], doc["comparisons"])
            await db.rankings.update_one(
                {"paper_id": paper_id, "category": category},
                {"$set": new_stats},
            )


async def rerank_category(db, category: str):
    """Recompute rank numbers for all papers in a category.
    
    Called after a batch of matches completes. O(papers_in_category).
    Uses score descending with title hash tiebreaker (same as compute_leaderboard).
    """
    import hashlib

    # Fetch all papers in category sorted by score desc
    cursor = db.rankings.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "score": 1, "title": 1},
    ).sort("score", -1)

    # Sort with tiebreaker
    entries = []
    async for doc in cursor:
        title_hash = hashlib.md5(doc.get("title", doc["paper_id"]).encode()).hexdigest()
        entries.append((doc["paper_id"], doc["score"], title_hash))

    # Stable sort: score desc, then title hash desc (same as compute_leaderboard)
    entries.sort(key=lambda e: (e[1], e[2]), reverse=True)

    # Bulk update ranks
    from pymongo import UpdateOne
    ops = []
    for rank, (paper_id, _, _) in enumerate(entries, 1):
        ops.append(UpdateOne(
            {"paper_id": paper_id, "category": category},
            {"$set": {"rank": rank}},
        ))
    if ops:
        await db.rankings.bulk_write(ops, ordered=False)


async def insert_ranking_for_paper(db, paper_doc: dict):
    """Add a ranking entry for a newly inserted paper. Score = 1200, rank = last."""
    from datetime import datetime, timezone

    cat = paper_doc.get("categories", ["unknown"])[0] if paper_doc.get("categories") else "unknown"

    # Get current max rank for this category
    last = await db.rankings.find_one(
        {"category": cat}, sort=[("rank", -1)], projection={"_id": 0, "rank": 1}
    )
    next_rank = (last["rank"] + 1) if last else 1

    r = paper_doc.get("ai_rating")
    ai_rating = None
    if r and isinstance(r, dict) and r.get("score"):
        ai_rating = round(r["score"], 1)
    elif r and isinstance(r, (int, float)):
        ai_rating = round(r, 1)

    await db.rankings.update_one(
        {"paper_id": paper_doc["id"]},
        {"$set": {
            "paper_id": paper_doc["id"],
            "category": cat,
            "rank": next_rank,
            "score": SCORE_BASE_CONST,
            "ci": 0,
            "wilson_margin": 100.0,
            "win_rate": 0.0,
            "wins": 0,
            "losses": 0,
            "comparisons": 0,
            "title": paper_doc["title"],
            "authors": paper_doc.get("authors", []),
            "arxiv_id": paper_doc.get("arxiv_id", ""),
            "link": paper_doc.get("link", ""),
            "published": paper_doc.get("published", ""),
            "added_at": paper_doc.get("added_at", datetime.now(timezone.utc).isoformat()),
            "categories": paper_doc.get("categories", [cat]),
            "ai_rating": ai_rating,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def reconcile_rankings(db, category: str = None):
    """Full recomputation and comparison with incremental rankings.
    
    Used as a daily consistency check. Overwrites if drift detected.
    Returns {category: {drifted: bool, max_score_diff: int, papers_checked: int}}.
    """
    from routers.validation_utils import collect_all
    from core.auth import get_settings
    from core.config import CATEGORIES, logger

    settings = await get_settings()
    cats = [category] if category else settings.get("active_categories", list(CATEGORIES.keys()))
    results = {}

    for cat in cats:
        papers = await collect_all(db.papers.find(
            {"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}},
            {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
             "link": 1, "published": 1, "added_at": 1, "categories": 1,
             "ai_rating": 1},
        ))
        matches = await collect_all(db.matches.find(
            {"completed": True, "failed": {"$ne": True}, "primary_category": cat,
             "mode": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
             "completed": 1, "failed": 1},
        ))

        lb = compute_leaderboard(papers, matches)
        recomputed = {e["id"]: e for e in lb}

        # Compare with current rankings
        max_diff = 0
        drifted_papers = 0
        async for r in db.rankings.find({"category": cat}, {"_id": 0, "paper_id": 1, "score": 1}):
            expected = recomputed.get(r["paper_id"])
            if expected:
                diff = abs(r["score"] - expected["score"])
                max_diff = max(max_diff, diff)
                if diff > 0:
                    drifted_papers += 1

        results[cat] = {
            "drifted": max_diff > 0,
            "max_score_diff": max_diff,
            "papers_checked": len(recomputed),
            "drifted_papers": drifted_papers,
        }

        # If drift detected, overwrite with full recomputation
        if max_diff > 0:
            logger.warning(f"Rankings drift in {cat}: max_diff={max_diff}, {drifted_papers} papers affected. Reseeding.")
            await seed_rankings(db, category=cat)

        await asyncio.sleep(0)

    return results
