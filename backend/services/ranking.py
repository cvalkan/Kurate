import math
import asyncio
import concurrent.futures
from typing import Dict, List
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
        sorted_papers = sorted(papers, key=lambda p: hashlib.sha256(p["title"].encode()).hexdigest(), reverse=True)
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
        return hashlib.sha256(title.encode()).hexdigest()
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


def compute_leaderboard_trueskill(papers: List[dict], matches: List[dict]) -> List[dict]:
    """TrueSkill-based leaderboard. Same interface as compute_leaderboard but uses
    TrueSkill ratings (mu - 3*sigma on Elo scale) instead of regularized win-rate."""
    import trueskill
    import hashlib
    paper_ids = [p["id"] for p in papers]
    SCORE_BASE = 1200
    TS_SCALE = 10.0

    if not paper_ids or not matches:
        sorted_papers = sorted(papers, key=lambda p: hashlib.sha256(p["title"].encode()).hexdigest(), reverse=True)
        return [{"id": p["id"], "rank": i + 1, "title": p["title"], "authors": p.get("authors", []),
                 "arxiv_id": p.get("arxiv_id", ""), "link": p.get("link", ""), "published": p.get("published", ""),
                 "score": SCORE_BASE, "ci": 0, "wins": 0, "losses": 0, "comparisons": 0,
                 "confidence": calculate_confidence_interval(0, 0)} for i, p in enumerate(sorted_papers)]

    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = {pid: env.create_rating() for pid in paper_ids}
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
            if p1 in ratings and p2 in ratings:
                r1, r2 = ratings[p1], ratings[p2]
                if winner == p1:
                    (nr1,), (nr2,) = env.rate([(r1,), (r2,)], ranks=[0, 1])
                else:
                    (nr1,), (nr2,) = env.rate([(r1,), (r2,)], ranks=[1, 0])
                ratings[p1] = nr1
                ratings[p2] = nr2

    ts_scores = {}
    for pid in paper_ids:
        r = ratings[pid]
        ts_scores[pid] = round((r.mu - 3 * r.sigma) * TS_SCALE + SCORE_BASE)

    paper_lookup = {p["id"]: p for p in papers}
    def _title_hash(pid):
        title = paper_lookup.get(pid, {}).get("title", pid)
        return hashlib.sha256(title.encode()).hexdigest()

    ranked = sorted(paper_ids, key=lambda pid: (ts_scores.get(pid, SCORE_BASE), _title_hash(pid)), reverse=True)
    entries = []
    for i, pid in enumerate(ranked):
        s = stats.get(pid, {"wins": 0, "losses": 0, "comparisons": 0})
        p = paper_lookup.get(pid, {})
        wr = s["wins"] / s["comparisons"] * 100 if s["comparisons"] else 50
        entries.append({
            "id": pid, "rank": i + 1, "title": p.get("title", ""),
            "authors": p.get("authors", []), "arxiv_id": p.get("arxiv_id", ""),
            "link": p.get("link", ""), "published": p.get("published", ""),
            "score": ts_scores.get(pid, SCORE_BASE), "ci": 0,
            "wins": s["wins"], "losses": s["losses"], "comparisons": s["comparisons"],
            "win_rate": round(wr, 1),
            "confidence": calculate_confidence_interval(s["wins"], s["comparisons"]),
        })
    return entries


async def compute_leaderboard_ts_async(papers: List[dict], matches: List[dict]) -> List[dict]:
    """Run compute_leaderboard_trueskill in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_compute_pool, compute_leaderboard_trueskill, papers, matches)



def compute_bt_ranking_scores(matches: List[dict], paper_ids: List[str]) -> Dict[str, float]:
    """Compute Bradley-Terry MLE strengths for ranking correlation analysis.

    Returns {paper_id: bt_strength}. Higher = better.
    Uses prior_strength=2.0 (same as the main BT implementation).
    """
    return calculate_bradley_terry(matches, paper_ids, prior_strength=2.0)


def compute_trueskill_ranking_scores(matches: List[dict], paper_ids: List[str]) -> Dict[str, float]:
    """Compute TrueSkill mu scores from pairwise matches.

    Uses 3 passes through shuffled matches for convergence (TrueSkill is order-sensitive).
    Returns {paper_id: mu}. Higher = better.
    Initialization: mu=25.0, sigma=25/3 (TrueSkill defaults), draw_probability=0.
    """
    import trueskill
    import random as _rng

    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = {pid: env.create_rating() for pid in paper_ids}
    pid_set = set(paper_ids)

    valid = [m for m in matches
             if m.get("completed") and m.get("winner_id") and not m.get("failed")
             and m["paper1_id"] in pid_set and m["paper2_id"] in pid_set]

    if not valid:
        return {pid: ratings[pid].mu for pid in paper_ids}

    _rng.seed(42)
    for _ in range(3):
        _rng.shuffle(valid)
        for m in valid:
            winner = m["winner_id"]
            loser = m["paper2_id"] if winner == m["paper1_id"] else m["paper1_id"]
            if winner in ratings and loser in ratings:
                new_w, new_l = trueskill.rate_1vs1(ratings[winner], ratings[loser])
                ratings[winner] = new_w
                ratings[loser] = new_l

    return {pid: ratings[pid].mu for pid in paper_ids}


def compute_openskill_tm_scores(matches: List[dict], paper_ids: List[str], passes: int = 3) -> Dict[str, float]:
    """Compute OpenSkill Thurstone-Mosteller Full scores from pairwise matches.

    Uses the Weng-Lin closed-form approximation to TrueSkill (same Gaussian model,
    no iterative EP). Multiple passes through shuffled matches improve convergence.
    Returns {paper_id: mu}. Higher = better.
    Caller is expected to pre-filter for completed/non-failed matches.
    CPU-bound — use compute_openskill_tm_scores_async() from async contexts.
    """
    from openskill.models import ThurstoneMostellerFull
    import random as _rng

    model = ThurstoneMostellerFull()
    ratings = {pid: model.rating() for pid in paper_ids}
    pid_set = set(paper_ids)

    valid = [m for m in matches
             if m.get("winner_id")
             and m.get("paper1_id", "") in pid_set
             and m.get("paper2_id", "") in pid_set]

    if not valid:
        return {pid: ratings[pid].mu for pid in paper_ids}

    _rng.seed(42)
    for _ in range(passes):
        _rng.shuffle(valid)
        for m in valid:
            winner = m["winner_id"]
            p1, p2 = m["paper1_id"], m["paper2_id"]
            loser = p2 if winner == p1 else p1
            if winner in ratings and loser in ratings:
                result = model.rate([[ratings[winner]], [ratings[loser]]])
                ratings[winner] = result[0][0]
                ratings[loser] = result[1][0]

    return {pid: ratings[pid].mu for pid in paper_ids}


async def compute_openskill_tm_scores_async(matches: List[dict], paper_ids: List[str], passes: int = 3) -> Dict[str, float]:
    """Async wrapper — runs compute_openskill_tm_scores in a thread pool to avoid blocking the event loop."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, compute_openskill_tm_scores, matches, paper_ids, passes)



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


TS_SCALE = 10.0  # Elo points per conservative-score unit for TrueSkill normalization
OS_SCALE = 15.0  # Elo points per conservative-score unit for OpenSkill (higher to match Elo std≈200)

def _extract_ai_rating(entry: dict) -> float | None:
    """Extract a single numeric AI rating from a ranking entry.
    
    Priority: averaged si_ratings > ai_rating dict > ai_rating scalar.
    Returns None if no valid rating found.
    """
    si = entry.get("si_ratings", {})
    if isinstance(si, dict) and si:
        scores = [v.get("score") for v in si.values() if isinstance(v, dict) and v.get("score")]
        if scores:
            return round(sum(scores) / len(scores), 1)
    ar = entry.get("ai_rating")
    if ar and isinstance(ar, dict) and ar.get("score"):
        return round(ar["score"], 1)
    if ar and isinstance(ar, (int, float)):
        return round(ar, 1)
    return None


def _compute_ts_elo(entries: list) -> dict:
    """Normalize TrueSkill mu/sigma to Elo-like scale for all entries.
    
    Uses mu - 3*sigma (conservative score, standard TrueSkill ranking).
    Default: mu=25, sigma=25/3≈8.33 → conservative=0 → ts_score=1200
    """
    ts_elo = {}
    for e in entries:
        raw_mu = e.get("ts_mu", 25.0)
        raw_sigma = e.get("ts_sigma", 25.0 / 3)
        if raw_mu is not None:
            conservative = raw_mu - 3 * raw_sigma
            ts_elo[e["paper_id"]] = round(conservative * TS_SCALE + SCORE_BASE_CONST)
        else:
            ts_elo[e["paper_id"]] = SCORE_BASE_CONST
    return ts_elo


def _compute_ranks(entries: list, ts_elo: dict) -> tuple:
    """Sort entries by WR score and TS score, return (rank_wr, rank_ts) dicts."""
    import hashlib
    wr_sorted = sorted(
        entries,
        key=lambda e: (e.get("score", SCORE_BASE_CONST),
                       hashlib.sha256(e.get("title", e["paper_id"]).encode()).hexdigest()),
        reverse=True,
    )
    rank_wr = {e["paper_id"]: rank for rank, e in enumerate(wr_sorted, 1)}

    ts_sorted = sorted(
        entries,
        key=lambda e: (ts_elo.get(e["paper_id"], SCORE_BASE_CONST),
                       hashlib.sha256(e.get("title", e["paper_id"]).encode()).hexdigest()),
        reverse=True,
    )
    rank_ts = {e["paper_id"]: rank for rank, e in enumerate(ts_sorted, 1)}

    return rank_wr, rank_ts


def _compute_gap_scores(entries: list, ts_elo: dict) -> tuple:
    """Compute WR and TS gap scores (percentile difference vs AI rating).
    
    Returns (gap_scores_wr, gap_scores_ts) dicts.
    """
    ai_ratings = {}
    for e in entries:
        rating = _extract_ai_rating(e)
        if rating is not None:
            ai_ratings[e["paper_id"]] = rating

    gap_wr = {}
    gap_ts = {}
    entries_with_both = [
        e for e in entries
        if ai_ratings.get(e["paper_id"]) and e.get("comparisons", 0) >= 3
    ]
    if len(entries_with_both) >= 2:
        import numpy as _np
        _wr_vals = _np.array([e["score"] for e in entries_with_both])
        _si_vals = _np.array([ai_ratings[e["paper_id"]] for e in entries_with_both])
        _wr_pct = scipy_stats.rankdata(_wr_vals) / len(entries_with_both) * 100
        _si_pct = scipy_stats.rankdata(_si_vals) / len(entries_with_both) * 100
        _gap_wr_raw = _wr_pct - _si_pct
        for i, entry in enumerate(entries_with_both):
            gap_wr[entry["paper_id"]] = round(float(_gap_wr_raw[i]), 1)

        _ts_vals = _np.array([ts_elo.get(e["paper_id"], SCORE_BASE_CONST) for e in entries_with_both])
        _ts_pct = scipy_stats.rankdata(_ts_vals) / len(entries_with_both) * 100
        _gap_ts_raw = _ts_pct - _si_pct
        for i, entry in enumerate(entries_with_both):
            gap_ts[entry["paper_id"]] = round(float(_gap_ts_raw[i]), 1)

    return gap_wr, gap_ts



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
    from core.memlog import log_mem

    settings = await get_settings()
    if category:
        cats = [category]
    else:
        cats = settings.get("active_categories", list(CATEGORIES.keys()))

    log_mem(f"seed_rankings start ({len(cats)} categories)")
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
             "mode": {"$exists": False}, "revision_superseded": {"$ne": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
             "completed": 1, "failed": 1},
        ))

        lb = compute_leaderboard(papers, matches)

        # Compute unique opponents per paper (for stall detection)
        unique_opps = {}
        for m in matches:
            if m.get("completed") and m.get("winner_id") and not m.get("failed"):
                p1, p2 = m["paper1_id"], m["paper2_id"]
                unique_opps.setdefault(p1, set()).add(p2)
                unique_opps.setdefault(p2, set()).add(p1)
        unique_opp_counts = {pid: len(opps) for pid, opps in unique_opps.items()}
        del unique_opps

        # Build lookups from paper data before freeing
        ai_ratings = {}
        paper_lookup = {}
        for p in papers:
            paper_lookup[p["id"]] = p
            r = p.get("ai_rating")
            if r and isinstance(r, dict) and r.get("score"):
                ai_ratings[p["id"]] = round(r["score"], 1)
            elif r and isinstance(r, (int, float)):
                ai_ratings[p["id"]] = round(r, 1)

        # Free raw data
        del papers, matches
        from core.memlog import force_gc
        force_gc()

        # Bulk upsert into rankings
        from pymongo import UpdateOne
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

        # Compute gap scores (WR percentile - AI percentile)
        gap_scores = {}
        entries_with_both = [e for e in lb if ai_ratings.get(e["id"]) and e.get("comparisons", 0) >= 3]
        if len(entries_with_both) >= 2:
            from scipy import stats as _sp_stats
            import numpy as _np
            _bt_vals = _np.array([e["score"] for e in entries_with_both])
            _si_vals = _np.array([ai_ratings[e["id"]] for e in entries_with_both])
            _bt_pct = _sp_stats.rankdata(_bt_vals) / len(entries_with_both) * 100
            _si_pct = _sp_stats.rankdata(_si_vals) / len(entries_with_both) * 100
            _gap_raw = _bt_pct - _si_pct
            for i, entry in enumerate(entries_with_both):
                gap_scores[entry["id"]] = round(float(_gap_raw[i]), 1)

        # Build lookups from paper data (leaderboard entries don't carry all fields)
        ops = []
        for entry in lb:
            p = paper_lookup.get(entry["id"], {})
            doc = {
                "paper_id": entry["id"],
                "category": cat,
                "rank": entry["rank"],
                "rank_wr": entry["rank"],
                "rank_ts": entry["rank"],
                "score": entry["score"],
                "ts_mu": 25.0,
                "ts_sigma": 25.0 / 3,
                "ts_score": SCORE_BASE_CONST,
                "ci": entry["ci"],
                "wilson_margin": entry.get("wilson_margin", 100.0),
                "win_rate": entry.get("win_rate", 0.0),
                "wins": entry["wins"],
                "losses": entry["losses"],
                "comparisons": entry["comparisons"],
                "unique_opponents": unique_opp_counts.get(entry["id"], 0),
                "title": entry["title"],
                "authors": entry.get("authors", []),
                "arxiv_id": entry.get("arxiv_id", ""),
                "link": entry.get("link", ""),
                "published": p.get("published") or "",
                "added_at": p.get("added_at") or "",
                "categories": p.get("categories", [cat]),
                "ai_rating": ai_ratings.get(entry["id"]),
                "gap_score": gap_scores.get(entry["id"]),
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


async def update_rankings_for_match(db, category: str, winner_id: str, loser_id: str, model_used: dict = None):
    """Incrementally update rankings after a single match completes.
    
    Updates WR scores, TrueSkill ratings, and per-model win stats for the 2 affected papers.
    O(1) per match — no match history loading.
    Retries once on failure. If retry fails, queues for background repair.
    """
    import trueskill
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    # Compute model key for per-model stats
    _OPUS_MERGE = {
        "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
        "anthropic/claude-opus-4-6": "anthropic/claude-opus",
    }
    model_key = None
    if model_used and isinstance(model_used, dict):
        raw_key = f"{model_used.get('provider', 'unknown')}/{model_used.get('model', 'unknown')}"
        model_key = _OPUS_MERGE.get(raw_key, raw_key)
        # MongoDB interprets dots as nested paths — replace with underscores
        if model_key:
            model_key = model_key.replace(".", "_")

    # --- Step 1: Update WR counts + scores + per-model stats for both papers ---
    for paper_id, is_winner in [(winner_id, True), (loser_id, False)]:
        inc_fields = {"comparisons": 1, "unique_opponents": 1}
        if is_winner:
            inc_fields["wins"] = 1
        else:
            inc_fields["losses"] = 1

        # Also increment per-model stats
        if model_key:
            inc_fields[f"model_stats.{model_key}.total"] = 1
            if is_winner:
                inc_fields[f"model_stats.{model_key}.wins"] = 1

        try:
            doc = await db.rankings.find_one_and_update(
                {"paper_id": paper_id, "category": category},
                {"$inc": inc_fields, "$set": {"updated_at": now_iso}},
                return_document=True,
                projection={"_id": 0, "wins": 1, "comparisons": 1},
            )
            if not doc:
                # Ranking doesn't exist yet (race: compare loop ran before fetch loop created it).
                # Create the ranking entry, then retry the increment.
                paper_doc = await db.papers.find_one(
                    {"id": paper_id},
                    {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                     "link": 1, "published": 1, "added_at": 1, "categories": 1, "ai_rating": 1},
                )
                if paper_doc:
                    await insert_ranking_for_paper(db, paper_doc)
                    doc = await db.rankings.find_one_and_update(
                        {"paper_id": paper_id, "category": category},
                        {"$inc": inc_fields, "$set": {"updated_at": now_iso}},
                        return_document=True,
                        projection={"_id": 0, "wins": 1, "comparisons": 1},
                    )
            if doc:
                new_stats = compute_paper_score(doc["wins"], doc["comparisons"])
                await db.rankings.update_one(
                    {"paper_id": paper_id, "category": category,
                     "comparisons": doc["comparisons"]},
                    {"$set": new_stats},
                )
        except Exception:
            try:
                await asyncio.sleep(0.5)
                doc = await db.rankings.find_one_and_update(
                    {"paper_id": paper_id, "category": category},
                    {"$inc": inc_fields, "$set": {"updated_at": now_iso}},
                    return_document=True,
                    projection={"_id": 0, "wins": 1, "comparisons": 1},
                )
                if not doc:
                    paper_doc = await db.papers.find_one(
                        {"id": paper_id},
                        {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1,
                         "link": 1, "published": 1, "added_at": 1, "categories": 1, "ai_rating": 1},
                    )
                    if paper_doc:
                        await insert_ranking_for_paper(db, paper_doc)
                        doc = await db.rankings.find_one_and_update(
                            {"paper_id": paper_id, "category": category},
                            {"$inc": inc_fields, "$set": {"updated_at": now_iso}},
                            return_document=True,
                            projection={"_id": 0, "wins": 1, "comparisons": 1},
                        )
                if doc:
                    new_stats = compute_paper_score(doc["wins"], doc["comparisons"])
                    await db.rankings.update_one(
                        {"paper_id": paper_id, "category": category,
                         "comparisons": doc["comparisons"]},
                        {"$set": new_stats},
                    )
            except Exception:
                await _queue_repair(db, category, paper_id)

    # --- Step 2: Incremental TrueSkill update for both papers ---
    try:
        env = trueskill.TrueSkill(draw_probability=0.0)
        # Load current TS ratings
        w_doc = await db.rankings.find_one(
            {"paper_id": winner_id, "category": category},
            {"_id": 0, "ts_mu": 1, "ts_sigma": 1},
        )
        l_doc = await db.rankings.find_one(
            {"paper_id": loser_id, "category": category},
            {"_id": 0, "ts_mu": 1, "ts_sigma": 1},
        )
        if w_doc and l_doc:
            w_mu = w_doc.get("ts_mu", 25.0)
            w_sigma = w_doc.get("ts_sigma", 25.0 / 3)
            l_mu = l_doc.get("ts_mu", 25.0)
            l_sigma = l_doc.get("ts_sigma", 25.0 / 3)
            w_rating = env.create_rating(mu=w_mu, sigma=w_sigma)
            l_rating = env.create_rating(mu=l_mu, sigma=l_sigma)
            new_w, new_l = trueskill.rate_1vs1(w_rating, l_rating)
            # CAS: only write if ts_mu hasn't changed since we read (prevents race condition)
            await db.rankings.update_one(
                {"paper_id": winner_id, "category": category, "ts_mu": w_mu},
                {"$set": {"ts_mu": new_w.mu, "ts_sigma": new_w.sigma}},
            )
            await db.rankings.update_one(
                {"paper_id": loser_id, "category": category, "ts_mu": l_mu},
                {"$set": {"ts_mu": new_l.mu, "ts_sigma": new_l.sigma}},
            )
    except Exception:
        pass  # TS update is best-effort; WR is the primary score

    # --- Step 3: Incremental per-model TrueSkill update ---
    if model_key:
        try:
            env = trueskill.TrueSkill(draw_probability=0.0)
            w_doc = await db.rankings.find_one(
                {"paper_id": winner_id, "category": category},
                {"_id": 0, f"model_ts.{model_key}": 1},
            )
            l_doc = await db.rankings.find_one(
                {"paper_id": loser_id, "category": category},
                {"_id": 0, f"model_ts.{model_key}": 1},
            )
            w_ts = (w_doc or {}).get("model_ts", {}).get(model_key, {})
            l_ts = (l_doc or {}).get("model_ts", {}).get(model_key, {})
            w_rating = env.create_rating(mu=w_ts.get("mu", 25.0), sigma=w_ts.get("sigma", 25.0/3))
            l_rating = env.create_rating(mu=l_ts.get("mu", 25.0), sigma=l_ts.get("sigma", 25.0/3))
            new_w, new_l = trueskill.rate_1vs1(w_rating, l_rating)
            await db.rankings.update_one(
                {"paper_id": winner_id, "category": category},
                {"$set": {f"model_ts.{model_key}.mu": new_w.mu, f"model_ts.{model_key}.sigma": new_w.sigma}},
            )
            await db.rankings.update_one(
                {"paper_id": loser_id, "category": category},
                {"$set": {f"model_ts.{model_key}.mu": new_l.mu, f"model_ts.{model_key}.sigma": new_l.sigma}},
            )
        except Exception:
            pass

    # --- Step 4: Incremental global OpenSkill update ---
    # Uses ALL matches (not per-model) — same data volume as TrueSkill.
    # Stored as os_mu/os_sigma on ranking doc (parallel to ts_mu/ts_sigma).
    try:
        from openskill.models import ThurstoneMostellerFull
        _os_global = ThurstoneMostellerFull()
        w_doc_g = await db.rankings.find_one(
            {"paper_id": winner_id, "category": category},
            {"_id": 0, "os_mu": 1, "os_sigma": 1},
        )
        l_doc_g = await db.rankings.find_one(
            {"paper_id": loser_id, "category": category},
            {"_id": 0, "os_mu": 1, "os_sigma": 1},
        )
        w_os_g = _os_global.rating(
            mu=(w_doc_g or {}).get("os_mu", 25.0),
            sigma=(w_doc_g or {}).get("os_sigma", 25.0 / 3),
        )
        l_os_g = _os_global.rating(
            mu=(l_doc_g or {}).get("os_mu", 25.0),
            sigma=(l_doc_g or {}).get("os_sigma", 25.0 / 3),
        )
        [[new_w_g], [new_l_g]] = _os_global.rate([[w_os_g], [l_os_g]], ranks=[1, 2])
        await db.rankings.update_one(
            {"paper_id": winner_id, "category": category},
            {"$set": {"os_mu": new_w_g.mu, "os_sigma": new_w_g.sigma}},
        )
        await db.rankings.update_one(
            {"paper_id": loser_id, "category": category},
            {"$set": {"os_mu": new_l_g.mu, "os_sigma": new_l_g.sigma}},
        )
    except Exception:
        pass

    # --- Step 5: Incremental per-model OpenSkill update ---
    if model_key:
        try:
            from openskill.models import ThurstoneMostellerFull
            _os_model_pm = ThurstoneMostellerFull()
            w_doc = await db.rankings.find_one(
                {"paper_id": winner_id, "category": category},
                {"_id": 0, f"model_os.{model_key}": 1},
            )
            l_doc = await db.rankings.find_one(
                {"paper_id": loser_id, "category": category},
                {"_id": 0, f"model_os.{model_key}": 1},
            )
            w_os = (w_doc or {}).get("model_os", {}).get(model_key, {})
            l_os = (l_doc or {}).get("model_os", {}).get(model_key, {})
            w_rating = _os_model_pm.rating(mu=w_os.get("mu", 25.0), sigma=w_os.get("sigma", 25.0 / 3))
            l_rating = _os_model_pm.rating(mu=l_os.get("mu", 25.0), sigma=l_os.get("sigma", 25.0 / 3))
            [[new_w], [new_l]] = _os_model_pm.rate([[w_rating], [l_rating]], ranks=[1, 2])
            await db.rankings.update_one(
                {"paper_id": winner_id, "category": category},
                {"$set": {f"model_os.{model_key}.mu": new_w.mu, f"model_os.{model_key}.sigma": new_w.sigma}},
            )
            await db.rankings.update_one(
                {"paper_id": loser_id, "category": category},
                {"$set": {f"model_os.{model_key}.mu": new_l.mu, f"model_os.{model_key}.sigma": new_l.sigma}},
            )
        except Exception:
            pass


async def _queue_repair(db, category: str, paper_id: str):
    """Queue a paper for background ranking repair."""
    from datetime import datetime, timezone
    await db.rankings_repair_queue.update_one(
        {"paper_id": paper_id, "category": category},
        {"$set": {"paper_id": paper_id, "category": category,
                  "queued_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


async def process_repair_queue(db):
    """Process queued ranking repairs. Verifies and fixes only the specific papers
    that had failed incremental updates. O(queue_size), not O(total_papers).
    
    Returns number of papers repaired.
    """
    from core.config import logger
    repaired = 0
    async for item in db.rankings_repair_queue.find({}, {"_id": 0}):
        pid = item["paper_id"]
        cat = item["category"]
        try:
            # Count actual wins/comparisons from matches
            comparisons = await db.matches.count_documents({
                "completed": True, "failed": {"$ne": True}, "primary_category": cat,
                "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
                "$or": [{"paper1_id": pid}, {"paper2_id": pid}],
            })
            wins = await db.matches.count_documents({
                "completed": True, "failed": {"$ne": True}, "primary_category": cat,
                "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
                "winner_id": pid,
            })
            new_stats = compute_paper_score(wins, comparisons)
            await db.rankings.update_one(
                {"paper_id": pid, "category": cat},
                {"$set": {"wins": wins, "losses": comparisons - wins,
                          "comparisons": comparisons, **new_stats}},
            )
            await db.rankings_repair_queue.delete_one({"paper_id": pid, "category": cat})
            repaired += 1
        except Exception as e:
            logger.warning(f"Repair failed for {pid} in {cat}: {e}")
    return repaired


async def rerank_category_light(db, category: str):
    """Lightweight rank re-sort from pre-computed scores.
    
    Both WR and TrueSkill scores are updated incrementally per-match.
    This function just re-sorts rank numbers, normalizes TS to Elo scale,
    and refreshes derived fields (gap scores, community likes).
    Single-pass: loads rankings once, computes everything, writes once.
    No match loading — O(P) reads + O(P) writes.
    
    Called after every comparison round.
    """
    from core.memlog import log_mem
    import time as _time
    from pymongo import UpdateOne

    _t0 = _time.perf_counter()

    entries = []
    async for doc in db.rankings.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "score": 1, "title": 1,
         "ts_mu": 1, "ts_sigma": 1, "os_mu": 1, "os_sigma": 1,
         "wins": 1, "comparisons": 1,
         "si_ratings": 1, "ai_rating": 1, "model_os": 1},
    ):
        entries.append(doc)

    if not entries:
        return

    # Compute all derived values
    ts_elo = _compute_ts_elo(entries)
    rank_wr, rank_ts = _compute_ranks(entries, ts_elo)
    gap_wr, gap_ts = _compute_gap_scores(entries, ts_elo)

    # Compute global OpenSkill score from os_mu/os_sigma (same pattern as TrueSkill)
    os_elo = {}
    os_sigma_map = {}
    for e in entries:
        raw_mu = e.get("os_mu")
        raw_sigma = e.get("os_sigma", 25.0 / 3)
        if raw_mu is not None:
            conservative = raw_mu - 3 * raw_sigma
            os_elo[e["paper_id"]] = round(conservative * OS_SCALE + SCORE_BASE_CONST)
            os_sigma_map[e["paper_id"]] = round(raw_sigma, 4)

    # Rank by OS score
    import hashlib
    os_sorted = sorted(
        [e for e in entries if e["paper_id"] in os_elo],
        key=lambda e: (os_elo.get(e["paper_id"], SCORE_BASE_CONST),
                       hashlib.sha256(e.get("title", e["paper_id"]).encode()).hexdigest()),
        reverse=True,
    )
    rank_os = {e["paper_id"]: rank for rank, e in enumerate(os_sorted, 1)}

    # Single bulk write — ranks + ts_score + os_score + gap scores
    ops = []
    for e in entries:
        pid = e["paper_id"]
        update = {
            "ts_score": ts_elo.get(pid, SCORE_BASE_CONST),
            "rank": rank_wr[pid],
            "rank_wr": rank_wr[pid],
            "rank_ts": rank_ts[pid],
        }
        if pid in os_elo:
            update["os_score"] = os_elo[pid]
            update["os_sigma"] = os_sigma_map.get(pid)
            update["rank_os"] = rank_os.get(pid)
        if pid in gap_wr:
            update["gap_score"] = gap_wr[pid]
        if pid in gap_ts:
            update["gap_score_ts"] = gap_ts[pid]
        ops.append(UpdateOne({"paper_id": pid, "category": category}, {"$set": update}))
    if ops:
        await db.rankings.bulk_write(ops, ordered=False)

    _elapsed = _time.perf_counter() - _t0
    log_mem(f"rerank_category_light({category}) done ({len(entries)} papers, {_elapsed:.1f}s)")

    from core.memlog import force_gc
    force_gc()



async def rerank_category(db, category: str):
    """Full rank recompute with win/loss count verification.
    
    Expensive: runs $facet aggregation over ALL matches to verify actual
    win/loss counts against stored values. Fixes any drift.
    Then re-sorts ranks using the same logic as rerank_category_light.
    
    Only use for admin-triggered reconciliation, not after every comparison round.
    """
    import hashlib
    from core.memlog import log_mem
    import time as _time
    from pymongo import UpdateOne

    _t0 = _time.perf_counter()
    log_mem(f"rerank_category({category}) start")

    # Step 1: Compute actual win/loss counts from matches via aggregation
    actual_stats = {}
    async for doc in db.matches.aggregate([
        {"$match": {"completed": True, "failed": {"$ne": True},
                     "primary_category": category, "mode": {"$exists": False},
                     "revision_superseded": {"$ne": True}}},
        {"$facet": {
            "as_p1": [
                {"$group": {"_id": "$paper1_id", "total": {"$sum": 1},
                            "wins": {"$sum": {"$cond": [{"$eq": ["$winner_id", "$paper1_id"]}, 1, 0]}}}}
            ],
            "as_p2": [
                {"$group": {"_id": "$paper2_id", "total": {"$sum": 1},
                            "wins": {"$sum": {"$cond": [{"$eq": ["$winner_id", "$paper2_id"]}, 1, 0]}}}}
            ],
        }},
    ]):
        for entry in doc.get("as_p1", []):
            pid = entry["_id"]
            actual_stats.setdefault(pid, {"wins": 0, "comparisons": 0})
            actual_stats[pid]["wins"] += entry["wins"]
            actual_stats[pid]["comparisons"] += entry["total"]
        for entry in doc.get("as_p2", []):
            pid = entry["_id"]
            actual_stats.setdefault(pid, {"wins": 0, "comparisons": 0})
            actual_stats[pid]["wins"] += entry["wins"]
            actual_stats[pid]["comparisons"] += entry["total"]

    # Step 2: Load all rankings, fix drifted counts
    entries = []
    fix_ops = []
    drifted_papers = 0
    async for doc in db.rankings.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "score": 1, "title": 1, "wins": 1, "comparisons": 1,
         "ts_mu": 1, "ts_sigma": 1, "si_ratings": 1, "ai_rating": 1},
    ):
        pid = doc["paper_id"]
        actual = actual_stats.get(pid, {"wins": 0, "comparisons": 0})
        a_wins = actual["wins"]
        a_comp = actual["comparisons"]

        if doc.get("wins", 0) != a_wins or doc.get("comparisons", 0) != a_comp:
            new_stats = compute_paper_score(a_wins, a_comp)
            fix_ops.append(UpdateOne(
                {"paper_id": pid, "category": category},
                {"$set": {"wins": a_wins, "losses": a_comp - a_wins,
                          "comparisons": a_comp, **new_stats}},
            ))
            doc["score"] = new_stats.get("score", SCORE_BASE_CONST)
            doc["wins"] = a_wins
            doc["comparisons"] = a_comp
            drifted_papers += 1

        entries.append(doc)

    if fix_ops:
        await db.rankings.bulk_write(fix_ops, ordered=False)

    if not entries:
        return

    # Step 3: Compute all derived values (same as light version)
    ts_elo = _compute_ts_elo(entries)
    rank_wr, rank_ts = _compute_ranks(entries, ts_elo)
    gap_wr, gap_ts = _compute_gap_scores(entries, ts_elo)

    # Step 4: Single bulk write — ranks + ts_score + gap scores
    ops = []
    for e in entries:
        pid = e["paper_id"]
        update = {
            "ts_score": ts_elo.get(pid, SCORE_BASE_CONST),
            "rank": rank_wr[pid],
            "rank_wr": rank_wr[pid],
            "rank_ts": rank_ts[pid],
        }
        if pid in gap_wr:
            update["gap_score"] = gap_wr[pid]
        if pid in gap_ts:
            update["gap_score_ts"] = gap_ts[pid]
        ops.append(UpdateOne({"paper_id": pid, "category": category}, {"$set": update}))
    if ops:
        await db.rankings.bulk_write(ops, ordered=False)

    _elapsed = _time.perf_counter() - _t0
    drift_msg = f", fixed {drifted_papers} drifted" if drifted_papers else ""
    log_mem(f"rerank_category({category}) done ({len(entries)} papers, {_elapsed:.1f}s{drift_msg})")

    from core.memlog import force_gc
    force_gc()




async def insert_ranking_for_paper(db, paper_doc: dict):
    """Add a ranking entry for a newly inserted paper. Score = 1200, rank = last.
    
    Only inserts if the paper has a Claude thinking summary — non-Claude papers
    must NOT enter the tournament.
    """
    from datetime import datetime, timezone

    CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
    summaries = paper_doc.get("summaries") or {}
    if not summaries.get(CLAUDE_KEY):
        return  # No Claude thinking summary → don't insert

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
            "rank_wr": next_rank,
            "rank_ts": next_rank,
            "score": SCORE_BASE_CONST,
            "ts_mu": 25.0,
            "ts_sigma": 25.0 / 3,
            "ts_score": SCORE_BASE_CONST,
            "ci": 0,
            "wilson_margin": 100.0,
            "win_rate": 0.0,
            "wins": 0,
            "losses": 0,
            "comparisons": 0,
            "unique_opponents": 0,
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
    """Verify ranking scores are consistent with actual match data.
    
    Lightweight approach: compare each paper's (wins, comparisons) in the rankings
    collection against actual counts from the matches collection. No bulk loading
    of papers or matches into memory — uses per-paper DB queries.
    
    Returns {category: {drifted: bool, drifted_papers: int, papers_checked: int}}.
    """
    from core.auth import get_settings
    from core.config import CATEGORIES, logger
    from core.memlog import log_mem
    import time as _time

    _t0 = _time.perf_counter()
    log_mem("reconcile_rankings start")

    settings = await get_settings()
    cats = [category] if category else settings.get("active_categories", list(CATEGORIES.keys()))
    results = {}

    for cat in cats:
        drifted_papers = 0
        papers_checked = 0

        async for r in db.rankings.find(
            {"category": cat},
            {"_id": 0, "paper_id": 1, "wins": 1, "comparisons": 1, "score": 1}
        ):
            pid = r["paper_id"]
            papers_checked += 1

            # Count actual wins and comparisons from matches collection
            actual_comparisons = await db.matches.count_documents({
                "completed": True, "failed": {"$ne": True}, "primary_category": cat,
                "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
                "$or": [{"paper1_id": pid}, {"paper2_id": pid}],
            })
            actual_wins = await db.matches.count_documents({
                "completed": True, "failed": {"$ne": True}, "primary_category": cat,
                "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
                "winner_id": pid,
            })

            # Count actual unique opponents (distinct opponent IDs from dedup_pair)
            actual_unique_opps = 0
            pair_keys_for_pid = []
            async for m in db.matches.find(
                {"completed": True, "failed": {"$ne": True}, "primary_category": cat,
                 "mode": {"$exists": False}, "revision_superseded": {"$ne": True},
                 "dedup_pair": {"$exists": True},
                 "$or": [{"paper1_id": pid}, {"paper2_id": pid}]},
                {"_id": 0, "dedup_pair": 1},
            ):
                pair_keys_for_pid.append(m["dedup_pair"])
            actual_unique_opps = len(set(pair_keys_for_pid))

            # Check if rankings match reality
            if (r.get("wins", 0) != actual_wins or
                r.get("comparisons", 0) != actual_comparisons or
                r.get("unique_opponents", 0) != actual_unique_opps):
                drifted_papers += 1
                # Fix the paper's stats and recompute score
                new_stats = compute_paper_score(actual_wins, actual_comparisons)
                await db.rankings.update_one(
                    {"paper_id": pid, "category": cat},
                    {"$set": {
                        "wins": actual_wins,
                        "losses": actual_comparisons - actual_wins,
                        "comparisons": actual_comparisons,
                        "unique_opponents": actual_unique_opps,
                        **new_stats,
                    }},
                )

        results[cat] = {
            "drifted": drifted_papers > 0,
            "drifted_papers": drifted_papers,
            "papers_checked": papers_checked,
        }

        # If any drift was found, rerank the category
        if drifted_papers > 0:
            logger.warning(f"Rankings drift in {cat}: {drifted_papers} papers corrected")
            await rerank_category(db, cat)

        from core.memlog import force_gc
        force_gc()
        await asyncio.sleep(0)

    _elapsed = _time.perf_counter() - _t0
    log_mem(f"reconcile_rankings done ({len(cats)} categories, {_elapsed:.1f}s)")
    return results



async def backfill_trueskill(db, category: str = None):
    """One-time migration: compute TrueSkill ratings from historical matches.
    
    Replays all matches chronologically through TrueSkill for each category.
    Stores ts_mu, ts_sigma, ts_score on each ranking doc.
    Processes one category at a time to limit memory usage.
    """
    import trueskill
    import time as _time
    from core.auth import get_settings
    from core.config import CATEGORIES, logger
    from core.memlog import log_mem

    settings = await get_settings()
    if category:
        cats = [category]
    else:
        cats = settings.get("active_categories", list(CATEGORIES.keys()))

    _t0 = _time.perf_counter()
    log_mem(f"backfill_trueskill start ({len(cats)} categories)")

    for cat in cats:
        env = trueskill.TrueSkill(draw_probability=0.0)

        # Load all matches for this category, sorted chronologically
        matches = []
        async for m in db.matches.find(
            {"completed": True, "failed": {"$ne": True},
             "primary_category": cat, "mode": {"$exists": False},
             "revision_superseded": {"$ne": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "created_at": 1},
        ).sort("created_at", 1):
            matches.append(m)

        if not matches:
            continue

        # Initialize ratings for all papers in this category
        paper_ids = set()
        for m in matches:
            paper_ids.add(m["paper1_id"])
            paper_ids.add(m["paper2_id"])
        ratings = {pid: env.create_rating() for pid in paper_ids}

        # Replay matches chronologically (single pass — natural ordering)
        for m in matches:
            winner = m.get("winner_id")
            loser = m["paper2_id"] if winner == m["paper1_id"] else m["paper1_id"]
            if winner in ratings and loser in ratings:
                new_w, new_l = trueskill.rate_1vs1(ratings[winner], ratings[loser])
                ratings[winner] = new_w
                ratings[loser] = new_l

        # Normalize to Elo scale using conservative score (mu - 3*sigma, fixed scale)
        TS_SCALE = 10.0
        from pymongo import UpdateOne
        ops = []
        for pid, rating in ratings.items():
            conservative = rating.mu - 3 * rating.sigma
            ts_elo = round(conservative * TS_SCALE + SCORE_BASE_CONST)
            ops.append(UpdateOne(
                {"paper_id": pid, "category": cat},
                {"$set": {
                    "ts_mu": rating.mu,
                    "ts_sigma": rating.sigma,
                    "ts_score": ts_elo,
                }},
            ))
        if ops:
            await db.rankings.bulk_write(ops, ordered=False)

        logger.info(f"[{cat}] Backfilled TrueSkill for {len(ratings)} papers from {len(matches)} matches")

        # Free memory
        del matches, ratings
        from core.memlog import force_gc
        force_gc()

    _elapsed = _time.perf_counter() - _t0
    log_mem(f"backfill_trueskill done ({len(cats)} categories, {_elapsed:.1f}s)")



async def backfill_model_stats(db, category: str = None):
    """One-time migration: compute per-model win stats from historical matches.
    
    Stores model_stats = {model_key: {wins: N, total: M}} on each ranking doc.
    Processes one category at a time. Uses streaming cursor, not bulk load.
    """
    import time as _time
    from collections import defaultdict
    from core.auth import get_settings
    from core.config import CATEGORIES, logger
    from core.memlog import log_mem
    from pymongo import UpdateOne

    _OPUS_MERGE = {
        "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
        "anthropic/claude-opus-4-6": "anthropic/claude-opus",
    }

    settings = await get_settings()
    cats = [category] if category else settings.get("active_categories", list(CATEGORIES.keys()))

    _t0 = _time.perf_counter()
    log_mem(f"backfill_model_stats start ({len(cats)} categories)")

    for cat in cats:
        # Accumulate per-paper per-model stats AND per-model match lists for TrueSkill
        paper_model_stats = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0}))
        model_match_lists = defaultdict(list)  # {model_key: [match_dicts]}
        match_count = 0

        async for m in db.matches.find(
            {"completed": True, "failed": {"$ne": True},
             "primary_category": cat, "mode": {"$exists": False},
             "revision_superseded": {"$ne": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
        ):
            mu = m.get("model_used", {})
            if not mu:
                continue
            raw_key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
            model_key = _OPUS_MERGE.get(raw_key, raw_key)
            # MongoDB interprets dots as nested paths — replace with underscores
            model_key = model_key.replace(".", "_")
            winner = m.get("winner_id")
            p1, p2 = m["paper1_id"], m["paper2_id"]

            paper_model_stats[p1][model_key]["total"] += 1
            paper_model_stats[p2][model_key]["total"] += 1
            if winner == p1:
                paper_model_stats[p1][model_key]["wins"] += 1
            elif winner == p2:
                paper_model_stats[p2][model_key]["wins"] += 1

            model_match_lists[model_key].append(m)
            match_count += 1

        # Compute per-model TrueSkill ratings
        import trueskill
        paper_model_ts = defaultdict(dict)  # {paper_id: {model_key: {mu, sigma}}}
        for mk, mk_matches in model_match_lists.items():
            if len(mk_matches) < 20:
                continue
            env = trueskill.TrueSkill(draw_probability=0.0)
            mk_pids = set()
            for m in mk_matches:
                mk_pids.add(m["paper1_id"])
                mk_pids.add(m["paper2_id"])
            ratings = {pid: env.create_rating() for pid in mk_pids}
            for m in mk_matches:
                w = m.get("winner_id")
                l = m["paper2_id"] if w == m["paper1_id"] else m["paper1_id"]
                if w in ratings and l in ratings:
                    new_w, new_l = trueskill.rate_1vs1(ratings[w], ratings[l])
                    ratings[w] = new_w
                    ratings[l] = new_l
            for pid, r in ratings.items():
                paper_model_ts[pid][mk] = {"mu": r.mu, "sigma": r.sigma}
        del model_match_lists

        # Bulk write model_stats + model_ts to rankings
        ops = []
        for pid, mstats in paper_model_stats.items():
            model_stats = {mk: dict(v) for mk, v in mstats.items()}
            update = {"model_stats": model_stats}
            if pid in paper_model_ts:
                update["model_ts"] = paper_model_ts[pid]
            ops.append(UpdateOne(
                {"paper_id": pid, "category": cat},
                {"$set": update},
            ))
        if ops:
            await db.rankings.bulk_write(ops, ordered=False)

        logger.info(f"[{cat}] Backfilled model_stats + model_ts for {len(paper_model_stats)} papers from {match_count} matches")

        del paper_model_stats, paper_model_ts
        from core.memlog import force_gc
        force_gc()

    _elapsed = _time.perf_counter() - _t0
    log_mem(f"backfill_model_stats done ({len(cats)} categories, {_elapsed:.1f}s)")



async def backfill_si_ratings(db, category: str = None):
    """Copy SI ratings from papers to rankings docs for fast Model Analysis queries.
    
    Stores si_ratings = {claude: {score,significance,rigor,novelty,clarity}, gpt: {...}, gemini: {...}}
    on each ranking doc. After this, si-rating-stats reads from rankings (not papers).
    """
    import time as _time
    from core.auth import get_settings
    from core.config import CATEGORIES, logger
    from core.memlog import log_mem
    from pymongo import UpdateOne

    settings = await get_settings()
    cats = [category] if category else settings.get("active_categories", list(CATEGORIES.keys()))

    _t0 = _time.perf_counter()
    log_mem(f"backfill_si_ratings start ({len(cats)} categories)")

    for cat in cats:
        ops = []
        async for p in db.papers.find(
            {"categories.0": cat},
            {"_id": 0, "id": 1, "ai_rating": 1, "ai_ratings_by_model": 1},
        ):
            si = {}
            by_model = p.get("ai_ratings_by_model", {})
            if isinstance(by_model, dict):
                for mk in ("claude", "gpt", "gemini"):
                    r = by_model.get(mk)
                    if isinstance(r, dict) and r.get("score"):
                        si[mk] = {k: r[k] for k in ("score", "significance", "rigor", "novelty", "clarity") if r.get(k)}

            # Fallback: ai_rating → claude
            if "claude" not in si:
                ai_r = p.get("ai_rating")
                if isinstance(ai_r, dict) and ai_r.get("score"):
                    si["claude"] = {k: ai_r[k] for k in ("score", "significance", "rigor", "novelty", "clarity") if ai_r.get(k)}

            if si:
                update_fields = {"si_ratings": si}
                # Copy ai_rating to ranking doc as a numeric score (never a dict)
                ai_r = p.get("ai_rating")
                if isinstance(ai_r, dict) and ai_r.get("score"):
                    update_fields["ai_rating"] = round(ai_r["score"], 1)
                elif isinstance(ai_r, (int, float)):
                    update_fields["ai_rating"] = round(ai_r, 1)
                ops.append(UpdateOne(
                    {"paper_id": p["id"], "category": cat},
                    {"$set": update_fields},
                ))

        if ops:
            await db.rankings.bulk_write(ops, ordered=False)
        logger.info(f"[{cat}] Backfilled si_ratings for {len(ops)} papers")

        from core.memlog import force_gc
        force_gc()

    _elapsed = _time.perf_counter() - _t0
    log_mem(f"backfill_si_ratings done ({len(cats)} categories, {_elapsed:.1f}s)")
