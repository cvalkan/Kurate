"""
Human vs AI Validation Experiment

Completely siloed from the main leaderboard system.
Imports papers with human expert ratings from H1 Connect,
runs an AI tournament, and computes rank correlation.
"""
import asyncio
import uuid
import random
import time as _time
from datetime import datetime, timezone
from collections import defaultdict
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import httpx
from scipy import stats as scipy_stats

from core.config import db, logger, DEFAULT_EVALUATION_PROMPT
from core.auth import verify_admin, get_settings
from services.llm import compare_papers
from services.ranking import compute_leaderboard

router = APIRouter(prefix="/api/validation")

H1_SOURCE_URL = "https://papertrend-viz.preview.emergentagent.com/api/papers"
MIN_EXPERT_RATINGS = 5

# In-memory state for the running tournament
_tournament_state = {
    "running": False,
    "completed_matches": 0,
    "total_matches": 0,
    "current_pair": "",
    "started_at": None,
}


# ─── Import ────────────────────────────────────────────────────────────────────

@router.post("/import", dependencies=[Depends(verify_admin)])
async def import_h1_papers():
    """Fetch papers with ≥5 expert ratings from H1 Connect via papertrend-viz API."""
    all_papers = []
    skip = 0
    batch = 100

    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            resp = await client.get(H1_SOURCE_URL, params={"limit": batch, "skip": skip})
            resp.raise_for_status()
            data = resp.json()
            papers = data.get("papers", [])
            if not papers:
                break
            all_papers.extend(papers)
            skip += batch
            if skip >= data.get("total", 0):
                break

    # Filter: H1 source, ≥ MIN_EXPERT_RATINGS evaluations
    h1_papers = [
        p for p in all_papers
        if p.get("source") == "h1" and p.get("h1_rating_count", 0) >= MIN_EXPERT_RATINGS
    ]

    if not h1_papers:
        return {"status": "error", "message": f"No H1 papers found with ≥{MIN_EXPERT_RATINGS} ratings"}

    # Upsert into validation_papers collection
    imported = 0
    for p in h1_papers:
        doc = {
            "id": p["id"],
            "title": p["title"],
            "abstract": p.get("abstract", ""),
            "authors": p.get("authors", []),
            "journal": p.get("journal", ""),
            "publication_date": p.get("publication_date", ""),
            "doi": p.get("doi", ""),
            "pmid": p.get("pmid", ""),
            "h1_url": p.get("h1_url", ""),
            "h1_avg_rating": p.get("h1_avg_rating", 0),
            "h1_rating_count": p.get("h1_rating_count", 0),
            "evaluations": p.get("evaluations", []),
            "classifications": p.get("classifications", []),
            "citations": p.get("citations", 0),
            "avg_h_index": p.get("avg_h_index", 0),
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
        result = await db.validation_papers.update_one(
            {"id": doc["id"]}, {"$set": doc}, upsert=True
        )
        if result.upserted_id:
            imported += 1

    return {
        "status": "ok",
        "total_h1_fetched": len(all_papers),
        "papers_with_enough_ratings": len(h1_papers),
        "newly_imported": imported,
        "total_in_db": await db.validation_papers.count_documents({}),
    }


# ─── Tournament ────────────────────────────────────────────────────────────────

class TournamentRequest(BaseModel):
    num_matches: int = 50
    parallel: int = 3


@router.post("/run-tournament", dependencies=[Depends(verify_admin)])
async def run_tournament(body: TournamentRequest = TournamentRequest()):
    """Run AI pairwise comparisons on imported validation papers."""
    if _tournament_state["running"]:
        return {"status": "already_running", **_tournament_state}

    paper_count = await db.validation_papers.count_documents({})
    if paper_count < 2:
        return {"status": "error", "message": "Need at least 2 imported papers. Run /import first."}

    num = min(max(body.num_matches, 1), 500)
    asyncio.create_task(_run_validation_tournament(num, min(max(body.parallel, 1), 10)))
    return {"status": "started", "num_matches": num}


async def _run_validation_tournament(max_pairs: int, parallel: int):
    """Background task: run pairwise comparisons on validation papers."""
    global _tournament_state
    _tournament_state = {
        "running": True, "completed_matches": 0, "total_matches": max_pairs,
        "current_pair": "Loading papers...", "started_at": _time.time(),
    }

    try:
        papers = await db.validation_papers.find({}, {"_id": 0}).to_list(1000)
        paper_lookup = {p["id"]: p for p in papers}
        paper_ids = list(paper_lookup.keys())

        # Get existing pairs to avoid duplicates
        existing = await db.validation_matches.find(
            {"completed": True, "failed": {"$ne": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ).to_list(100000)
        compared = {tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in existing}

        # Generate random pairs
        pairs = []
        attempts = 0
        while len(pairs) < max_pairs and attempts < max_pairs * 20:
            p1, p2 = random.sample(paper_ids, 2)
            key = tuple(sorted([p1, p2]))
            if key not in compared:
                pairs.append((p1, p2))
                compared.add(key)
            attempts += 1

        if not pairs:
            logger.info("Validation tournament: no new pairs available")
            _tournament_state["running"] = False
            return

        _tournament_state["total_matches"] = len(pairs)

        settings = await get_settings()
        prompt_config = DEFAULT_EVALUATION_PROMPT
        completed = 0

        for i in range(0, len(pairs), parallel):
            batch = pairs[i:i + parallel]
            # Randomize presentation order
            presented = []
            for p1_id, p2_id in batch:
                if random.random() < 0.5:
                    presented.append((p2_id, p1_id))
                else:
                    presented.append((p1_id, p2_id))

            _tournament_state["current_pair"] = f"Batch {i // parallel + 1}"

            tasks = [
                compare_papers(
                    paper_lookup[p1], paper_lookup[p2],
                    prompt_config, abstract_only=True
                )
                for p1, p2 in presented
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (p1_id, p2_id), result in zip(presented, results):
                match_doc = {
                    "id": str(uuid.uuid4()),
                    "paper1_id": p1_id,
                    "paper2_id": p2_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if isinstance(result, Exception):
                    match_doc["completed"] = False
                    match_doc["failed"] = True
                    match_doc["error"] = str(result)[:200]
                else:
                    winner_key = result.get("winner", "paper1")
                    match_doc["winner_id"] = p1_id if winner_key == "paper1" else p2_id
                    match_doc["reasoning"] = result.get("reasoning", "")
                    match_doc["model_used"] = result.get("model_used", {})
                    match_doc["tokens"] = result.get("tokens", {})
                    match_doc["completed"] = True
                    match_doc["failed"] = False
                    completed += 1

                await db.validation_matches.insert_one(match_doc)
                _tournament_state["completed_matches"] = completed

            await asyncio.sleep(0.5)

        logger.info(f"Validation tournament: {completed}/{len(pairs)} completed")
    except Exception as e:
        logger.error(f"Validation tournament error: {e}")
    finally:
        _tournament_state["running"] = False
        _tournament_state["current_pair"] = "Done"


# ─── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_validation_status():
    """Get status of the validation experiment (public endpoint)."""
    paper_count = await db.validation_papers.count_documents({})
    match_count = await db.validation_matches.count_documents({"completed": True, "failed": {"$ne": True}})
    failed_count = await db.validation_matches.count_documents({"failed": True})
    total_possible = paper_count * (paper_count - 1) // 2 if paper_count > 1 else 0

    # Matches per paper distribution
    if match_count > 0:
        pipeline = [
            {"$match": {"completed": True, "failed": {"$ne": True}}},
            {"$group": {
                "_id": None,
                "all_p1": {"$push": "$paper1_id"},
                "all_p2": {"$push": "$paper2_id"},
            }},
        ]
        agg = await db.validation_matches.aggregate(pipeline).to_list(1)
        if agg:
            all_ids = agg[0]["all_p1"] + agg[0]["all_p2"]
            from collections import Counter
            counts = Counter(all_ids)
            avg_matches = sum(counts.values()) / max(len(counts), 1)
            min_matches = min(counts.values()) if counts else 0
            max_matches_val = max(counts.values()) if counts else 0
        else:
            avg_matches = min_matches = max_matches_val = 0
    else:
        avg_matches = min_matches = max_matches_val = 0

    return {
        "papers_imported": paper_count,
        "matches_completed": match_count,
        "matches_failed": failed_count,
        "total_possible_pairs": total_possible,
        "coverage_pct": round(match_count / max(total_possible, 1) * 100, 1),
        "avg_matches_per_paper": round(avg_matches, 1),
        "min_matches_per_paper": min_matches,
        "max_matches_per_paper": max_matches_val,
        "tournament_running": _tournament_state["running"],
        "tournament_progress": _tournament_state,
        "min_expert_ratings": MIN_EXPERT_RATINGS,
    }


# ─── Results & Correlation ─────────────────────────────────────────────────────

@router.get("/results")
async def get_validation_results():
    """Compute AI ranking vs Human ranking and return correlation metrics."""
    papers = await db.validation_papers.find({}, {"_id": 0}).to_list(1000)
    matches = await db.validation_matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
         "completed": 1, "failed": 1, "reasoning": 1, "model_used": 1},
    ).to_list(100000)

    if not papers:
        return {"status": "no_data", "message": "No papers imported yet."}

    # Filter to papers that have at least 1 match
    paper_ids_in_matches = set()
    for m in matches:
        paper_ids_in_matches.add(m["paper1_id"])
        paper_ids_in_matches.add(m["paper2_id"])

    matched_papers = [p for p in papers if p["id"] in paper_ids_in_matches]
    if len(matched_papers) < 2:
        return {"status": "insufficient_matches", "message": "Need matches for at least 2 papers. Run the tournament first."}

    # Compute AI leaderboard (Bradley-Terry + Elo)
    ai_leaderboard = compute_leaderboard(matched_papers, matches)
    ai_lookup = {entry["id"]: entry for entry in ai_leaderboard}

    # Build human ranking from H1 avg rating (higher is better)
    human_sorted = sorted(matched_papers, key=lambda p: p.get("h1_avg_rating", 0), reverse=True)

    # Assign human ranks (handle ties by averaging)
    human_ranks = {}
    i = 0
    while i < len(human_sorted):
        j = i
        while j < len(human_sorted) and human_sorted[j].get("h1_avg_rating", 0) == human_sorted[i].get("h1_avg_rating", 0):
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            human_ranks[human_sorted[k]["id"]] = avg_rank
        i = j

    # Build comparison table
    comparison = []
    ai_ranks_list = []
    human_ranks_list = []

    for paper in matched_papers:
        pid = paper["id"]
        ai_entry = ai_lookup.get(pid, {})
        ai_rank = ai_entry.get("rank", 999)
        h_rank = human_ranks.get(pid, 999)

        ai_ranks_list.append(ai_rank)
        human_ranks_list.append(h_rank)

        comparison.append({
            "id": pid,
            "title": paper["title"],
            "journal": paper.get("journal", ""),
            "h1_avg_rating": paper.get("h1_avg_rating", 0),
            "h1_rating_count": paper.get("h1_rating_count", 0),
            "human_rank": h_rank,
            "ai_rank": ai_rank,
            "ai_score": ai_entry.get("score", 1200),
            "ai_win_rate": ai_entry.get("win_rate", 0),
            "ai_matches": ai_entry.get("comparisons", 0),
            "rank_delta": ai_rank - h_rank,
        })

    comparison.sort(key=lambda x: x["human_rank"])

    # Correlation metrics
    spearman_rho, spearman_p = scipy_stats.spearmanr(ai_ranks_list, human_ranks_list)
    kendall_tau, kendall_p = scipy_stats.kendalltau(ai_ranks_list, human_ranks_list)

    # Also compute correlation with H1 avg rating directly (not just rank)
    ai_scores = [ai_lookup.get(p["id"], {}).get("score", 1200) for p in matched_papers]
    h1_ratings = [p.get("h1_avg_rating", 0) for p in matched_papers]
    pearson_r, pearson_p = scipy_stats.pearsonr(ai_scores, h1_ratings) if len(ai_scores) > 2 else (0, 1)

    # Model usage stats
    model_counts = defaultdict(int)
    for m in matches:
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', '?')}/{mu.get('model', '?')}"
        model_counts[key] += 1

    # Rating distribution
    rating_dist = defaultdict(int)
    for p in matched_papers:
        rating_dist[f"{p.get('h1_avg_rating', 0):.1f}"] += 1

    return {
        "status": "ok",
        "papers_analyzed": len(matched_papers),
        "total_matches": len(matches),
        "correlation": {
            "spearman_rho": round(spearman_rho, 4),
            "spearman_p_value": round(spearman_p, 6),
            "kendall_tau": round(kendall_tau, 4),
            "kendall_p_value": round(kendall_p, 6),
            "pearson_r": round(pearson_r, 4),
            "pearson_p_value": round(pearson_p, 6),
        },
        "interpretation": _interpret_correlation(spearman_rho, spearman_p, len(matched_papers)),
        "comparison": comparison,
        "model_usage": dict(model_counts),
        "rating_distribution": dict(sorted(rating_dist.items())),
    }


def _interpret_correlation(rho: float, p_value: float, n: int) -> str:
    """Human-readable interpretation of the correlation."""
    if n < 5:
        return "Too few papers for meaningful correlation analysis."

    strength = abs(rho)
    if strength >= 0.7:
        level = "strong"
    elif strength >= 0.4:
        level = "moderate"
    elif strength >= 0.2:
        level = "weak"
    else:
        level = "negligible"

    direction = "positive" if rho > 0 else "negative"
    sig = "statistically significant" if p_value < 0.05 else "not statistically significant"

    return (
        f"There is a {level} {direction} correlation (Spearman ρ = {rho:.3f}) "
        f"between AI tournament rankings and human expert ratings. "
        f"This result is {sig} (p = {p_value:.4f}, n = {n})."
    )


# ─── Reset ─────────────────────────────────────────────────────────────────────

@router.post("/reset", dependencies=[Depends(verify_admin)])
async def reset_validation():
    """Reset all validation data (papers + matches)."""
    if _tournament_state["running"]:
        return {"status": "error", "message": "Cannot reset while tournament is running."}

    papers_deleted = await db.validation_papers.delete_many({})
    matches_deleted = await db.validation_matches.delete_many({})
    return {
        "status": "ok",
        "papers_deleted": papers_deleted.deleted_count,
        "matches_deleted": matches_deleted.deleted_count,
    }
