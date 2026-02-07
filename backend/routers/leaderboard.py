from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
import asyncio
import time
from core.config import db, logger, CATEGORIES
from services.ranking import compute_leaderboard, calculate_confidence_interval, _wilson_margin_pct

router = APIRouter(prefix="/api")

# Pre-computed cache — refreshed in the background, never blocks requests
_cache = {"ts": 0, "categories": {}, "total_papers": 0, "total_matches": 0}
_CACHE_TTL = 20
_cache_lock = asyncio.Lock()
_bg_task_started = False


async def _refresh_cache():
    """Heavy computation — runs in background, never on the request path."""
    all_papers = await db.papers.find(
        {}, {"_id": 0, "full_text": 0, "abstract": 0}
    ).to_list(5000)

    all_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ).to_list(200000)

    utc_now = datetime.now(timezone.utc)
    categories_data = {}

    # Group papers by primary category
    papers_by_cat = {}
    for p in all_papers:
        cat = p.get("categories", ["unknown"])[0] if p.get("categories") else "unknown"
        papers_by_cat.setdefault(cat, []).append(p)

    # Load settings once
    from core.auth import get_settings
    settings = await get_settings()
    _min = settings.get("min_matches_per_paper", 3)
    _ci_target = settings.get("ci_target", 12)
    _top_k = settings.get("top_k_focus", 10)
    _max_matches = settings.get("max_matches_per_paper", 150)

    for cat_id in CATEGORIES:
        cat_papers = papers_by_cat.get(cat_id, [])
        if not cat_papers:
            categories_data[cat_id] = {
                "all": [], "recent": [], "week": [], "month": [],
                "_matches": 0, "_papers": 0, "_is_ranking": False,
            }
            continue

        cat_paper_ids = {p["id"] for p in cat_papers}
        cat_matches = [m for m in all_matches if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids]

        full = compute_leaderboard(cat_papers, cat_matches)

        paper_dates = {}
        for entry in full:
            try:
                paper_dates[entry["id"]] = datetime.fromisoformat(entry.get("published", "").replace("Z", "+00:00"))
            except (ValueError, KeyError):
                pass

        max_date = max(paper_dates.values()) if paper_dates else utc_now
        recent_cutoff = datetime(max_date.year, max_date.month, max_date.day, tzinfo=timezone.utc)

        def filter_and_rerank(cutoff, entries=full):
            filtered = [{**e} for e in entries if e["id"] in paper_dates and paper_dates[e["id"]] >= cutoff]
            for i, e in enumerate(filtered):
                e["rank"] = i + 1
            return filtered

        # Compute is_ranking from match data already in memory
        cat_match_counts = {pid: 0 for pid in cat_paper_ids}
        cat_win_counts = {pid: 0 for pid in cat_paper_ids}
        for m in cat_matches:
            if m["paper1_id"] in cat_match_counts:
                cat_match_counts[m["paper1_id"]] += 1
            if m["paper2_id"] in cat_match_counts:
                cat_match_counts[m["paper2_id"]] += 1
            w = m.get("winner_id")
            if w and w in cat_win_counts:
                cat_win_counts[w] += 1

        goal1_unmet = any(c < _min for c in cat_match_counts.values()) if cat_match_counts else False
        goal2_unmet = False
        if cat_match_counts and len(cat_match_counts) >= 2:
            sorted_by_wr = sorted(
                cat_paper_ids,
                key=lambda pid: cat_win_counts.get(pid, 0) / max(cat_match_counts.get(pid, 0), 1),
                reverse=True,
            )
            top_k_ids = sorted_by_wr[:min(_top_k, len(sorted_by_wr))]
            for pid in top_k_ids:
                n = cat_match_counts.get(pid, 0)
                if n >= _max_matches:
                    continue
                w = cat_win_counts.get(pid, 0)
                margin = _wilson_margin_pct(w, n)
                if margin > _ci_target:
                    goal2_unmet = True
                    break

        categories_data[cat_id] = {
            "all": full,
            "recent": filter_and_rerank(recent_cutoff),
            "week": filter_and_rerank(utc_now - timedelta(weeks=1)),
            "month": filter_and_rerank(utc_now - timedelta(days=30)),
            "_matches": len(cat_matches),
            "_papers": len(cat_papers),
            "_is_ranking": goal1_unmet or goal2_unmet,
        }

    _cache.update({
        "ts": time.time(),
        "categories": categories_data,
        "total_papers": len(all_papers),
        "total_matches": len(all_matches),
    })


async def _bg_cache_loop():
    """Background loop that keeps the cache fresh."""
    global _bg_task_started
    _bg_task_started = True
    # Initial warm
    try:
        await _refresh_cache()
        logger.info("Leaderboard cache warmed (background)")
    except Exception as e:
        logger.warning(f"Initial cache warm failed: {e}")

    while True:
        await asyncio.sleep(_CACHE_TTL)
        try:
            await _refresh_cache()
        except Exception as e:
            logger.warning(f"Background cache refresh failed: {e}")


def start_cache_bg():
    """Start the background cache refresh task. Called from startup."""
    global _bg_task_started
    if not _bg_task_started:
        asyncio.create_task(_bg_cache_loop())


async def _get_cached_leaderboard():
    """Returns pre-computed cache instantly. Falls back to sync refresh if cache is empty."""
    if _cache["categories"]:
        return _cache
    # First call before bg task has run — do a one-time sync refresh
    await _refresh_cache()
    return _cache


@router.get("/categories")
async def get_categories():
    from core.auth import get_settings
    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))
    return {
        "categories": [{"id": k, "name": v} for k, v in CATEGORIES.items() if k in active],
        "default": active[0] if active else "cs.RO",
    }


@router.get("/leaderboard")
async def get_leaderboard(
    category: Optional[str] = Query("cs.RO", description="arXiv category"),
    period: Optional[str] = Query("all", description="Filter: recent, week, month, all"),
    limit: int = Query(100, description="Max papers to return"),
    offset: int = Query(0, description="Offset for pagination"),
):
    cache = await _get_cached_leaderboard()
    cat_data = cache["categories"].get(category, {})
    data = cat_data.get(period, cat_data.get("all", []))

    return {
        "leaderboard": data[offset:offset + limit],
        "total_papers": cat_data.get("_papers", 0),
        "total_in_period": len(data),
        "total_matches": cat_data.get("_matches", 0),
        "is_ranking": cat_data.get("_is_ranking", False),
        "period": period,
        "category": category,
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


_status_cache = {"data": None, "ts": 0}


@router.get("/status")
async def get_system_status():
    from services.scheduler import get_scheduler_status

    now = time.time()
    if _status_cache["data"] is None or now - _status_cache["ts"] > 10:
        total_papers = await db.papers.count_documents({})
        total_matches = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}})
        failed_matches = await db.matches.count_documents({"failed": True})
        _status_cache["data"] = {
            "total_papers": total_papers,
            "total_matches": total_matches,
            "failed_matches": failed_matches,
        }
        _status_cache["ts"] = now

    cached = _status_cache["data"]
    return {
        **cached,
        "scheduler": get_scheduler_status(),
    }


@router.get("/model-correlation")
async def get_model_correlation(
    category: Optional[str] = Query(None, description="Filter by category (None = all)"),
):
    """Correlation analysis between the 3 LLMs used for rankings."""
    import numpy as np
    from scipy import stats as scipy_stats

    cat_paper_ids = None
    if category:
        cat_paper_ids = set()
        async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
            cat_paper_ids.add(p["id"])

    matches_raw = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "model_used": {"$exists": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
    ).to_list(100000)

    if cat_paper_ids is not None:
        matches = [m for m in matches_raw if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids]
    else:
        matches = matches_raw

    if not matches:
        return {"models": [], "correlations": {}, "agreement": {}, "n_common_papers": 0, "category": category}

    paper_titles = {}
    async for p in db.papers.find({}, {"_id": 0, "id": 1, "title": 1}):
        paper_titles[p["id"]] = p["title"]

    model_keys = set()
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        model_keys.add(key)
    model_keys = sorted(model_keys)

    paper_ids = set()
    for m in matches:
        paper_ids.add(m["paper1_id"])
        paper_ids.add(m["paper2_id"])
    paper_ids = sorted(paper_ids)

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

    pair_judgments = {}
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pair not in pair_judgments:
            pair_judgments[pair] = {}
        pair_judgments[pair][key] = m.get("winner_id")

    agreement_counts = {}
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

    model_summaries = {}
    for mk in model_keys:
        total_by_model = sum(1 for m in matches if f"{m.get('model_used',{}).get('provider','')}/{m.get('model_used',{}).get('model','')}" == mk)
        model_summaries[mk] = {
            "total_matches": total_by_model,
            "papers_judged": len(model_paper_stats[mk]),
        }

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
        "category": category,
    }
