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
    parallel_agents: Optional[int] = None
    top_k_focus: Optional[int] = None
    exploration_constant: Optional[float] = None
    anchor_comparisons: Optional[int] = None
    min_matches_per_paper: Optional[int] = None
    max_matches_per_paper: Optional[int] = None
    ci_target: Optional[int] = None
    paused: Optional[bool] = None
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


class FetchRequest(BaseModel):
    category: str = "cs.RO"


@router.post("/fetch", dependencies=[Depends(verify_admin)])
async def trigger_fetch(body: FetchRequest = FetchRequest()):
    result = await run_fetch_cycle(category=body.category)
    return result


@router.post("/toggle-pause", dependencies=[Depends(verify_admin)])
async def toggle_pause():
    settings = await get_settings()
    new_state = not settings.get("paused", False)
    await db.settings.update_one({"key": "global"}, {"$set": {"paused": new_state}}, upsert=True)
    return {"paused": new_state}


class ManualCompareRequest(BaseModel):
    num_matches: int = 50
    category: str = "cs.RO"


@router.post("/compare", dependencies=[Depends(verify_admin)])
async def trigger_comparison(body: ManualCompareRequest = ManualCompareRequest()):
    import asyncio
    num = min(max(body.num_matches, 1), 500)
    asyncio.create_task(run_comparison_round(max_pairs_override=num, category=body.category))
    return {"status": "started", "num_matches": num, "category": body.category}


@router.get("/status", dependencies=[Depends(verify_admin)])
async def get_admin_status(category: str = "cs.RO"):
    # Get paper IDs for this category
    cat_paper_ids = set()
    async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
        cat_paper_ids.add(p["id"])

    total_papers = len(cat_paper_ids)

    # Count matches within this category
    total_matches = 0
    failed_matches = 0
    match_paper_ids = set()
    async for m in db.matches.find({}, {"_id": 0, "paper1_id": 1, "paper2_id": 1, "completed": 1, "failed": 1}):
        if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids:
            if m.get("completed") and not m.get("failed"):
                total_matches += 1
                match_paper_ids.add(m["paper1_id"])
                match_paper_ids.add(m["paper2_id"])
            if m.get("failed"):
                failed_matches += 1

    unranked = len(cat_paper_ids - match_paper_ids)

    # Recent matches for this category
    recent_all = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)

    recent_matches = [m for m in recent_all if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids][:10]

    paper_ids_needed = set()
    for m in recent_matches:
        paper_ids_needed.update([m["paper1_id"], m["paper2_id"], m.get("winner_id", "")])

    paper_titles = {}
    async for p in db.papers.find({"id": {"$in": list(paper_ids_needed)}}, {"_id": 0, "id": 1, "title": 1}):
        paper_titles[p["id"]] = p["title"]

    enriched_recent = [
        {
            "id": m["id"],
            "paper1_title": paper_titles.get(m["paper1_id"], "Unknown"),
            "paper2_title": paper_titles.get(m["paper2_id"], "Unknown"),
            "winner_title": paper_titles.get(m.get("winner_id", ""), "Unknown"),
            "reasoning": m.get("reasoning", ""),
            "model_used": m.get("model_used", {}),
            "created_at": m.get("created_at", ""),
        }
        for m in recent_matches
    ]

    return {
        "total_papers": total_papers,
        "total_matches": total_matches,
        "failed_matches": failed_matches,
        "unranked_papers": unranked,
        "category": category,
        "scheduler": scheduler_status,
        "recent_matches": enriched_recent,
    }


@router.get("/progress", dependencies=[Depends(verify_admin)])
async def get_progress_estimate(category: str = "cs.RO"):
    """Dual-goal progress with estimated remaining matches and time."""
    settings = await get_settings()
    min_matches = settings.get("min_matches_per_paper", 3)
    max_matches = settings.get("max_matches_per_paper", 150)
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 12)
    is_paused = settings.get("paused", False)
    parallel_agents = settings.get("parallel_agents", 5)

    all_paper_ids = []
    async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
        all_paper_ids.append(p["id"])

    total_papers = len(all_paper_ids)
    if total_papers == 0:
        return {"total_papers": 0, "goals_met": True, "paused": is_paused, "category": category}

    pid_set = set(all_paper_ids)
    paper_match_count = {pid: 0 for pid in all_paper_ids}
    paper_wins = {pid: 0 for pid in all_paper_ids}
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1
            w = m.get("winner_id")
            if w and w in paper_wins:
                paper_wins[w] += 1

    # Goal 1: All papers at min matches
    papers_at_min = sum(1 for c in paper_match_count.values() if c >= min_matches)
    deficit = sum(max(0, min_matches - c) for c in paper_match_count.values())
    matches_for_goal1 = max(0, (deficit + 1) // 2)
    goal1_met = papers_at_min == total_papers

    # Goal 2: Top-K papers have Wilson CI margin ≤ ci_target %
    sorted_papers = sorted(
        all_paper_ids,
        key=lambda pid: paper_wins.get(pid, 0) / max(paper_match_count.get(pid, 0), 1),
        reverse=True,
    )
    top_k_ids = sorted_papers[:min(top_k, total_papers)]
    top_k_converged = 0
    matches_for_goal2 = 0
    top_k_details = []
    target_frac = ci_target / 100.0

    for pid in top_k_ids:
        n = paper_match_count[pid]
        w = paper_wins.get(pid, 0)
        margin = float(_wilson_margin(w, n))
        margin_pct = round(margin * 100, 1)
        converged = bool(margin_pct <= ci_target or n >= max_matches)
        if converged:
            top_k_converged += 1
        else:
            # Direct solve: Wilson margin ≈ z*sqrt(p(1-p)/n) for large n
            # So n_needed ≈ z² * p*(1-p) / target²
            p = w / n if n > 0 else 0.5
            p = max(0.05, min(0.95, p))
            z = 1.96
            n_for_ci = max(0, int(z * z * p * (1 - p) / (target_frac * target_frac)) - n)
            n_for_cap = max(0, max_matches - n)
            matches_for_goal2 += min(n_for_ci, n_for_cap)
        elo_ci = _elo_ci(w, n)
        top_k_details.append({
            "id": pid, "matches": int(n), "margin_pct": float(margin_pct),
            "elo_ci": int(round(elo_ci)) if elo_ci < 999 else None, "converged": converged,
        })
    goal2_met = bool(top_k_converged == len(top_k_ids))

    total_est = matches_for_goal1 + matches_for_goal2
    seconds_per_match = 10.0 / max(parallel_agents, 1)
    est_minutes = max(0, round(total_est * seconds_per_match / 60))

    # Per-category counts
    cat_matches_done = sum(paper_match_count.values()) // 2  # each match counted twice
    cat_papers_with_pdf = 0
    async for p in db.papers.find({"categories.0": category, "full_text": {"$ne": None}}, {"_id": 0}):
        cat_papers_with_pdf += 1

    return {
        "total_papers": total_papers,
        "total_matches": cat_matches_done,
        "papers_with_pdf": cat_papers_with_pdf,
        "paused": is_paused,
        "category": category,
        "goals_met": bool(goal1_met and goal2_met),
        "goal1": {
            "met": bool(goal1_met),
            "label": f"Min {min_matches} matches/paper",
        },
        "goal2": {
            "met": bool(goal2_met),
            "label": f"CI \u2264 {ci_target}% for top-{len(top_k_ids)}",
            "done": int(top_k_converged),
            "total": int(len(top_k_ids)),
        },
        "estimated_matches_remaining": int(total_est),
        "estimated_minutes": int(est_minutes),
    }


def _wilson_margin(wins, comparisons):
    """Wilson score CI half-width (0 to 0.5 range)."""
    from scipy import stats as scipy_stats
    if comparisons == 0:
        return 0.5
    p = wins / comparisons
    n = comparisons
    z = scipy_stats.norm.ppf(0.975)
    denom = 1 + z**2 / n
    center = (p + z**2 / (2*n)) / denom
    spread = z * ((p*(1-p) + z**2/(4*n)) / n) ** 0.5 / denom
    lower = max(0, center - spread)
    upper = min(1, center + spread)
    return (upper - lower) / 2


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


@router.get("/prompt", dependencies=[Depends(verify_admin)])
async def get_evaluation_prompt():
    from core.config import DEFAULT_EVALUATION_PROMPT
    doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
    if doc:
        return {
            "system_prompt": doc.get("system_prompt", ""),
            "user_prompt": doc.get("user_prompt", ""),
        }
    # No prompt saved yet — save the default and return it
    await db.settings.update_one(
        {"key": "custom_prompt"},
        {"$set": {"key": "custom_prompt", **DEFAULT_EVALUATION_PROMPT}},
        upsert=True,
    )
    return DEFAULT_EVALUATION_PROMPT


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


DEFAULT_SUMMARY_PROMPT = {
    "system_prompt": """You are a scientific impact analyst. Write a concise, informative summary of a paper's scientific impact based on:
1. The paper's content (abstract, methodology, results)
2. How it performed in head-to-head comparisons against other recent papers, as judged by AI models simulating expert panels

Write in third person, factual tone. Structure the summary as:
- Opening sentence: What the paper does and its main contribution
- Key strengths identified through comparisons (2-3 points)
- Limitations or areas where other papers were preferred (1-2 points, if any losses exist)
- Closing assessment of overall impact and significance

Keep it to 150-200 words. Do not use bullet points — write flowing paragraphs.""",
    "user_prompt": """Paper: "{title}"
Authors: {authors}

{paper_content}

Tournament performance: {win_rate}% win rate across {num_matches} comparisons.

{match_context}

Write the scientific impact summary.""",
}


@router.get("/summary-prompt", dependencies=[Depends(verify_admin)])
async def get_summary_prompt():
    doc = await db.settings.find_one({"key": "summary_prompt"}, {"_id": 0})
    if doc:
        return {
            "system_prompt": doc.get("system_prompt", ""),
            "user_prompt": doc.get("user_prompt", ""),
        }
    await db.settings.update_one(
        {"key": "summary_prompt"},
        {"$set": {"key": "summary_prompt", **DEFAULT_SUMMARY_PROMPT}},
        upsert=True,
    )
    return DEFAULT_SUMMARY_PROMPT


@router.put("/summary-prompt", dependencies=[Depends(verify_admin)])
async def update_summary_prompt(update: PromptUpdate):
    await db.settings.update_one(
        {"key": "summary_prompt"},
        {"$set": {
            "key": "summary_prompt",
            "system_prompt": update.system_prompt,
            "user_prompt": update.user_prompt,
        }},
        upsert=True,
    )
    return {"success": True}
