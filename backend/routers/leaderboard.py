from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
from core.config import db, logger
from services.ranking import compute_leaderboard, calculate_confidence_interval

router = APIRouter(prefix="/api")


@router.get("/leaderboard")
async def get_leaderboard(
    period: Optional[str] = Query("all", description="Filter: today, week, month, all"),
):
    # Always compute global rankings from ALL papers and ALL matches
    all_papers = await db.papers.find(
        {}, {"_id": 0, "full_text": 0}
    ).to_list(5000)

    if not all_papers:
        return {"leaderboard": [], "total_papers": 0, "total_matches": 0, "period": period}

    all_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0},
    ).to_list(100000)

    # Compute global leaderboard (scores are always from ALL data)
    global_leaderboard = compute_leaderboard(all_papers, all_matches)

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

    total_matches = len(all_matches)

    return {
        "leaderboard": global_leaderboard,
        "total_papers": len(all_papers),
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
