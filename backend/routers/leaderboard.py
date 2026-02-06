from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
import time
from core.config import db, logger
from services.ranking import compute_leaderboard, calculate_confidence_interval

router = APIRouter(prefix="/api")

# In-memory leaderboard cache (avoids recomputing BT on every request)
_leaderboard_cache = {"data": None, "total_papers": 0, "total_matches": 0, "ts": 0}
_CACHE_TTL = 30  # seconds


async def _get_cached_leaderboard():
    now = time.time()
    if _leaderboard_cache["data"] is not None and now - _leaderboard_cache["ts"] < _CACHE_TTL:
        return _leaderboard_cache

    all_papers = await db.papers.find(
        {}, {"_id": 0, "full_text": 0, "abstract": 0}
    ).to_list(5000)

    if not all_papers:
        _leaderboard_cache.update({"data": [], "total_papers": 0, "total_matches": 0, "ts": now})
        return _leaderboard_cache

    all_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ).to_list(200000)

    leaderboard = compute_leaderboard(all_papers, all_matches)
    _leaderboard_cache.update({
        "data": leaderboard,
        "total_papers": len(all_papers),
        "total_matches": len(all_matches),
        "ts": now,
    })
    return _leaderboard_cache


@router.get("/leaderboard")
async def get_leaderboard(
    period: Optional[str] = Query("all", description="Filter: today, week, month, all"),
    limit: int = Query(100, description="Max papers to return"),
    offset: int = Query(0, description="Offset for pagination"),
):
    cache = await _get_cached_leaderboard()
    global_leaderboard = list(cache["data"])  # shallow copy

    # Filter display by period (but keep global scores)
    if period and period != "all":
        now = datetime.now(timezone.utc)
        if period == "today":
            cutoff = now - timedelta(days=1)
        elif period == "week":
            cutoff = now - timedelta(weeks=1)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = None

        if cutoff:
            paper_dates = {}
            for p in all_papers:
                try:
                    paper_dates[p["id"]] = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
                except (ValueError, KeyError):
                    pass

            filtered = [
                entry for entry in global_leaderboard
                if entry["id"] in paper_dates and paper_dates[entry["id"]] >= cutoff
            ]
            # Re-rank within the filtered set (1, 2, 3...) but keep global scores
            for i, entry in enumerate(filtered):
                entry["rank"] = i + 1
            global_leaderboard = filtered

    total_matches = cache["total_matches"]
    total_in_period = len(global_leaderboard)

    paginated = global_leaderboard[offset:offset + limit]

    return {
        "leaderboard": paginated,
        "total_papers": cache["total_papers"],
        "total_in_period": total_in_period,
        "total_matches": total_matches,
        "period": period,
    }


@router.get("/papers/{paper_id}")
async def get_paper_detail(paper_id: str):
    paper = await db.papers.find_one({"id": paper_id}, {"_id": 0, "full_text": 0})
    if not paper:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get all matches for this paper
    matches = await db.matches.find(
        {
            "completed": True,
            "$or": [{"paper1_id": paper_id}, {"paper2_id": paper_id}],
        },
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)

    # Get opponent paper titles
    opponent_ids = set()
    for m in matches:
        if m["paper1_id"] == paper_id:
            opponent_ids.add(m["paper2_id"])
        else:
            opponent_ids.add(m["paper1_id"])

    opponents = await db.papers.find(
        {"id": {"$in": list(opponent_ids)}},
        {"_id": 0, "id": 1, "title": 1, "arxiv_id": 1, "link": 1},
    ).to_list(500)
    opponent_lookup = {o["id"]: o for o in opponents}

    # Enrich matches with paper titles
    enriched_matches = []
    for m in matches:
        opponent_id = m["paper2_id"] if m["paper1_id"] == paper_id else m["paper1_id"]
        opp = opponent_lookup.get(opponent_id, {})
        won = m.get("winner_id") == paper_id
        enriched_matches.append({
            "id": m["id"],
            "opponent_id": opponent_id,
            "opponent_title": opp.get("title", "Unknown"),
            "opponent_arxiv_id": opp.get("arxiv_id", ""),
            "won": won,
            "reasoning": m.get("reasoning", ""),
            "model_used": m.get("model_used", {}),
            "created_at": m.get("created_at", ""),
            "failed": m.get("failed", False),
        })

    # Compute stats
    wins = sum(1 for m in enriched_matches if m["won"] and not m["failed"])
    total = sum(1 for m in enriched_matches if not m["failed"])
    ci = calculate_confidence_interval(wins, total)

    return {
        "paper": paper,
        "matches": enriched_matches,
        "stats": {
            "wins": wins,
            "losses": total - wins,
            "comparisons": total,
            "confidence": ci,
        },
    }


@router.get("/status")
async def get_system_status():
    from services.scheduler import scheduler_status

    total_papers = await db.papers.count_documents({})
    total_matches = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}})
    failed_matches = await db.matches.count_documents({"failed": True})

    settings = await db.settings.find_one({"key": "global"}, {"_id": 0, "admin_password": 0})

    return {
        "total_papers": total_papers,
        "total_matches": total_matches,
        "failed_matches": failed_matches,
        "scheduler": scheduler_status,
        "settings": settings,
    }


@router.get("/model-correlation")
async def get_model_correlation():
    """Correlation analysis between the 3 LLMs used for rankings."""
    import numpy as np
    from scipy import stats as scipy_stats

    # Load all successful matches with model info
    matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "model_used": {"$exists": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
    ).to_list(100000)

    if not matches:
        return {"models": [], "papers": [], "correlations": {}, "agreement": {}}

    # Get all paper titles
    paper_titles = {}
    async for p in db.papers.find({}, {"_id": 0, "id": 1, "title": 1}):
        paper_titles[p["id"]] = p["title"]

    # Group matches by model
    model_keys = set()
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        model_keys.add(key)

    model_keys = sorted(model_keys)

    # Per-paper, per-model: wins and total
    paper_ids = set()
    for m in matches:
        paper_ids.add(m["paper1_id"])
        paper_ids.add(m["paper2_id"])
    paper_ids = sorted(paper_ids)

    # Build stats: {model: {paper_id: {wins, total}}}
    model_paper_stats = {mk: {} for mk in model_keys}
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
        for pid in [p1, p2]:
            if pid not in model_paper_stats[key]:
                model_paper_stats[key][pid] = {"wins": 0, "total": 0}
            model_paper_stats[key][pid]["total"] += 1
        if w and w in model_paper_stats[key]:
            model_paper_stats[key][w]["wins"] += 1

    # Compute win rates per model per paper (only papers with ≥3 matches from that model)
    model_win_rates = {}
    common_papers = set(paper_ids)
    for mk in model_keys:
        model_win_rates[mk] = {}
        papers_with_data = set()
        for pid in paper_ids:
            s = model_paper_stats[mk].get(pid)
            if s and s["total"] >= 3:
                model_win_rates[mk][pid] = s["wins"] / s["total"]
                papers_with_data.add(pid)
        common_papers &= papers_with_data

    common_papers = sorted(common_papers)

    # Pairwise correlations (Spearman rank correlation on common papers)
    correlations = {}
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j:
                continue
            rates1 = [model_win_rates[m1].get(pid, 0.5) for pid in common_papers]
            rates2 = [model_win_rates[m2].get(pid, 0.5) for pid in common_papers]
            if len(rates1) >= 5:
                spearman_r, spearman_p = scipy_stats.spearmanr(rates1, rates2)
                pearson_r, pearson_p = scipy_stats.pearsonr(rates1, rates2)
                correlations[f"{m1} vs {m2}"] = {
                    "spearman_r": round(float(spearman_r), 3),
                    "spearman_p": round(float(spearman_p), 4),
                    "pearson_r": round(float(pearson_r), 3),
                    "pearson_p": round(float(pearson_p), 4),
                    "n_papers": len(common_papers),
                }

    # Agreement rate: for matches where multiple models judged the same pair,
    # what % of the time do they agree?
    pair_judgments = {}  # {(p1,p2): {model: winner}}
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pair not in pair_judgments:
            pair_judgments[pair] = {}
        pair_judgments[pair][key] = m.get("winner_id")

    agreement_counts = {}
    total_pairs_compared = 0
    for pair, judgments in pair_judgments.items():
        models_involved = list(judgments.keys())
        for i in range(len(models_involved)):
            for j in range(i + 1, len(models_involved)):
                m1, m2 = models_involved[i], models_involved[j]
                pair_key = f"{m1} vs {m2}" if m1 < m2 else f"{m2} vs {m1}"
                if pair_key not in agreement_counts:
                    agreement_counts[pair_key] = {"agree": 0, "disagree": 0}
                if judgments[m1] == judgments[m2]:
                    agreement_counts[pair_key]["agree"] += 1
                else:
                    agreement_counts[pair_key]["disagree"] += 1
                total_pairs_compared += 1

    agreement = {}
    for pair_key, counts in agreement_counts.items():
        total = counts["agree"] + counts["disagree"]
        if total > 0:
            agreement[pair_key] = {
                "agree": counts["agree"],
                "disagree": counts["disagree"],
                "total": total,
                "rate": round(counts["agree"] / total * 100, 1),
            }

    # Per-model summary stats
    model_summaries = {}
    for mk in model_keys:
        total_by_model = sum(1 for m in matches if f"{m.get('model_used',{}).get('provider','')}/{m.get('model_used',{}).get('model','')}" == mk)
        model_summaries[mk] = {
            "total_matches": total_by_model,
            "papers_judged": len(model_paper_stats[mk]),
        }

    # Build scatter data for frontend (win rates per model for common papers)
    scatter_data = []
    for pid in common_papers:
        entry = {"id": pid, "title": paper_titles.get(pid, "Unknown")[:50]}
        for mk in model_keys:
            short_name = mk.split("/")[-1]
            entry[short_name] = round(model_win_rates[mk].get(pid, 0.5) * 100, 1)
        scatter_data.append(entry)

    return {
        "models": [{"key": mk, "short": mk.split("/")[-1], **model_summaries.get(mk, {})} for mk in model_keys],
        "correlations": correlations,
        "agreement": agreement,
        "scatter_data": scatter_data,
        "n_common_papers": len(common_papers),
    }
