from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.config import db, logger, DEFAULT_SETTINGS
from core.auth import verify_admin, get_settings
from services.scheduler import run_fetch_cycle, run_comparison_round, scheduler_status

router = APIRouter(prefix="/api/admin")


class AdminLogin(BaseModel):
    password: str


class SettingsUpdate(BaseModel):
    fetch_interval_hours: Optional[int] = None
    max_papers_per_fetch: Optional[int] = None
    comparisons_per_round: Optional[int] = None
    parallel_agents: Optional[int] = None
    top_k_focus: Optional[int] = None
    exploration_constant: Optional[float] = None
    anchor_comparisons: Optional[int] = None
    min_matches_per_paper: Optional[int] = None
    auto_process: Optional[bool] = None
    admin_password: Optional[str] = None


class PromptUpdate(BaseModel):
    system_prompt: str
    user_prompt: str


@router.post("/login")
async def admin_login(body: AdminLogin):
    settings = await get_settings()
    if body.password != settings.get("admin_password", DEFAULT_SETTINGS["admin_password"]):
        raise HTTPException(status_code=403, detail="Invalid password")
    return {"success": True, "token": settings.get("admin_password")}


@router.get("/settings", dependencies=[Depends(verify_admin)])
async def get_admin_settings():
    settings = await get_settings()
    settings.pop("_id", None)
    return {"settings": settings}


@router.put("/settings", dependencies=[Depends(verify_admin)])
async def update_settings(update: SettingsUpdate):
    update_dict = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")

    await db.settings.update_one(
        {"key": "global"},
        {"$set": update_dict},
        upsert=True,
    )
    logger.info(f"Admin updated settings: {list(update_dict.keys())}")
    return {"success": True, "updated": list(update_dict.keys())}


@router.post("/fetch", dependencies=[Depends(verify_admin)])
async def trigger_fetch():
    result = await run_fetch_cycle()
    return result


@router.post("/compare", dependencies=[Depends(verify_admin)])
async def trigger_comparison():
    import asyncio
    asyncio.create_task(run_comparison_round())
    return {"status": "started", "message": "Comparison round started in background"}


@router.get("/status", dependencies=[Depends(verify_admin)])
async def get_admin_status():
    total_papers = await db.papers.count_documents({})
    total_matches = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}})
    failed_matches = await db.matches.count_documents({"failed": True})
    papers_without_text = await db.papers.count_documents({"full_text": None})
    papers_no_comparisons = await db.papers.count_documents({})

    # Count papers with 0 comparisons
    all_paper_ids = [p["id"] async for p in db.papers.find({}, {"_id": 0, "id": 1})]
    match_paper_ids = set()
    async for m in db.matches.find({"completed": True}, {"_id": 0, "paper1_id": 1, "paper2_id": 1}):
        match_paper_ids.add(m["paper1_id"])
        match_paper_ids.add(m["paper2_id"])
    unranked = len([pid for pid in all_paper_ids if pid not in match_paper_ids])

    # Recent matches
    recent_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(10)

    # Enrich with paper titles
    paper_ids_needed = set()
    for m in recent_matches:
        paper_ids_needed.add(m["paper1_id"])
        paper_ids_needed.add(m["paper2_id"])
        if m.get("winner_id"):
            paper_ids_needed.add(m["winner_id"])

    paper_titles = {}
    async for p in db.papers.find({"id": {"$in": list(paper_ids_needed)}}, {"_id": 0, "id": 1, "title": 1}):
        paper_titles[p["id"]] = p["title"]

    enriched_recent = []
    for m in recent_matches:
        enriched_recent.append({
            "id": m["id"],
            "paper1_title": paper_titles.get(m["paper1_id"], "Unknown"),
            "paper2_title": paper_titles.get(m["paper2_id"], "Unknown"),
            "winner_title": paper_titles.get(m.get("winner_id", ""), "Unknown"),
            "reasoning": m.get("reasoning", ""),
            "model_used": m.get("model_used", {}),
            "created_at": m.get("created_at", ""),
        })

    return {
        "total_papers": total_papers,
        "total_matches": total_matches,
        "failed_matches": failed_matches,
        "papers_without_text": papers_without_text,
        "unranked_papers": unranked,
        "scheduler": scheduler_status,
        "recent_matches": enriched_recent,
    }


@router.get("/progress", dependencies=[Depends(verify_admin)])
async def get_progress_estimate():
    """Estimate remaining matches needed to reach confidence targets."""
    import math
    settings = await get_settings()
    min_matches = settings.get("min_matches_per_paper", 3)
    top_k = settings.get("top_k_focus", 10)

    all_paper_ids = []
    async for p in db.papers.find({}, {"_id": 0, "id": 1}):
        all_paper_ids.append(p["id"])

    total_papers = len(all_paper_ids)
    if total_papers == 0:
        return {"total_papers": 0, "matches_needed": 0, "progress_pct": 100}

    # Count matches per paper
    paper_match_count = {pid: 0 for pid in all_paper_ids}
    paper_wins = {pid: 0 for pid in all_paper_ids}
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        if m["paper1_id"] in paper_match_count:
            paper_match_count[m["paper1_id"]] += 1
        if m["paper2_id"] in paper_match_count:
            paper_match_count[m["paper2_id"]] += 1
        w = m.get("winner_id")
        if w and w in paper_wins:
            paper_wins[w] += 1

    # Papers at or above min matches
    papers_at_min = sum(1 for c in paper_match_count.values() if c >= min_matches)
    below_min_count = total_papers - papers_at_min

    # Matches needed to bring all papers to min_matches
    # Each match covers 2 papers, so rough estimate:
    deficit = sum(max(0, min_matches - c) for c in paper_match_count.values())
    matches_for_min = max(0, (deficit + 1) // 2)

    # Papers converged: CI ≤ ±100 Elo (reasonable for this scale)
    papers_converged = 0
    for pid in all_paper_ids:
        n = paper_match_count[pid]
        if n >= min_matches:
            ci = _elo_ci(paper_wins.get(pid, 0), n)
            if ci <= 100:
                papers_converged += 1

    total_matches_done = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}})
    papers_with_pdf = await db.papers.count_documents({"full_text": {"$ne": None}})

    # Overall progress: weighted by papers at min matches
    progress_pct = min(100, round(100 * papers_at_min / total_papers)) if total_papers > 0 else 100

    return {
        "total_papers": total_papers,
        "total_matches": total_matches_done,
        "papers_with_pdf": papers_with_pdf,
        "papers_at_min_matches": papers_at_min,
        "papers_below_min_matches": below_min_count,
        "matches_needed_for_min": matches_for_min,
        "papers_converged": papers_converged,
        "estimated_rounds": max(0, matches_for_min // 20 + (1 if matches_for_min % 20 else 0)),
        "min_matches_setting": min_matches,
        "progress_pct": progress_pct,
    }


def _elo_ci(wins, comparisons):
    import math
    if comparisons < 2:
        return 999
    p = max(0.02, min(0.98, (wins + 0.5) / (comparisons + 1.0)))
    se_logit = 1.0 / math.sqrt((comparisons + 1.0) * p * (1 - p))
    se_elo = (400 / math.log(10)) * se_logit
    return 1.96 * se_elo


@router.get("/stats", dependencies=[Depends(verify_admin)])
async def get_usage_stats():
    """Token usage by model with cost estimation."""
    # Pricing per 1M tokens (input, output)
    MODEL_PRICING = {
        "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
        "anthropic/claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
        "gemini/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    }

    model_stats = {}
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "model_used": 1, "tokens": 1},
    ):
        mu = m.get("model_used", {})
        key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        if key not in model_stats:
            model_stats[key] = {"matches": 0, "input_tokens": 0, "output_tokens": 0}
        model_stats[key]["matches"] += 1
        tokens = m.get("tokens", {})
        model_stats[key]["input_tokens"] += tokens.get("input_est", 0)
        model_stats[key]["output_tokens"] += tokens.get("output_est", 0)

    # Calculate cost per model
    total_cost = 0.0
    for key, stats in model_stats.items():
        pricing = MODEL_PRICING.get(key, {"input": 2.0, "output": 10.0})
        cost_in = (stats["input_tokens"] / 1_000_000) * pricing["input"]
        cost_out = (stats["output_tokens"] / 1_000_000) * pricing["output"]
        stats["cost_input"] = round(cost_in, 4)
        stats["cost_output"] = round(cost_out, 4)
        stats["cost_total"] = round(cost_in + cost_out, 4)
        total_cost += cost_in + cost_out

    total_input = sum(s["input_tokens"] for s in model_stats.values())
    total_output = sum(s["output_tokens"] for s in model_stats.values())

    # Storage
    pipeline = [
        {"$match": {"full_text": {"$ne": None}}},
        {"$project": {"text_len": {"$strLenCP": "$full_text"}}},
        {"$group": {"_id": None, "total_chars": {"$sum": "$text_len"}, "count": {"$sum": 1}}},
    ]
    storage_result = await db.papers.aggregate(pipeline).to_list(1)
    if storage_result:
        total_chars = storage_result[0]["total_chars"]
        papers_with_text = storage_result[0]["count"]
    else:
        total_chars = 0
        papers_with_text = 0

    total_papers = await db.papers.count_documents({})

    return {
        "models": model_stats,
        "totals": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_matches": sum(s["matches"] for s in model_stats.values()),
            "total_cost": round(total_cost, 4),
        },
        "storage": {
            "papers_with_text": papers_with_text,
            "total_papers": total_papers,
            "total_chars": total_chars,
            "size_mb": round(total_chars / (1024 * 1024), 2),
        },
    }
    }


@router.get("/prompt", dependencies=[Depends(verify_admin)])
async def get_evaluation_prompt():
    from core.config import DEFAULT_EVALUATION_PROMPT
    custom = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
    if custom:
        return {
            "system_prompt": custom.get("system_prompt", DEFAULT_EVALUATION_PROMPT["system_prompt"]),
            "user_prompt": custom.get("user_prompt", DEFAULT_EVALUATION_PROMPT["user_prompt"]),
            "is_custom": True,
        }
    return {
        "system_prompt": DEFAULT_EVALUATION_PROMPT["system_prompt"],
        "user_prompt": DEFAULT_EVALUATION_PROMPT["user_prompt"],
        "is_custom": False,
    }


@router.put("/prompt", dependencies=[Depends(verify_admin)])
async def update_evaluation_prompt(update: PromptUpdate):
    await db.settings.update_one(
        {"key": "custom_prompt"},
        {"$set": {
            "key": "custom_prompt",
            "system_prompt": update.system_prompt,
            "user_prompt": update.user_prompt,
        }},
        upsert=True,
    )
    return {"success": True}


@router.delete("/prompt", dependencies=[Depends(verify_admin)])
async def reset_evaluation_prompt():
    await db.settings.delete_one({"key": "custom_prompt"})
    return {"success": True}
