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
