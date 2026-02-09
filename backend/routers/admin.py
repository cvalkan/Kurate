from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from collections import defaultdict
from datetime import datetime, timezone
from core.config import db, logger, DEFAULT_SETTINGS, CATEGORIES
from core.auth import verify_admin, get_settings
from services.scheduler import run_fetch_cycle, run_comparison_round, get_scheduler_status, _get_cat_status, wake_scheduler

router = APIRouter(prefix="/api/admin")


class AdminLogin(BaseModel):
    password: str


class SettingsUpdate(BaseModel):
    fetch_interval_hours: Optional[int] = None
    max_papers_per_fetch: Optional[int] = None
    parallel_agents: Optional[int] = None
    top_k_focus: Optional[int] = None
    min_matches_per_paper: Optional[int] = None
    max_matches_per_paper: Optional[int] = None
    max_new_matches_per_round: Optional[int] = None
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
    if not new_state:
        wake_scheduler()  # Wake immediately on unpause
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
    total_papers = await db.papers.count_documents({"categories.0": category})

    # Use indexed count queries instead of scanning all matches
    total_matches = await db.matches.count_documents(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}}
    )
    failed_matches = await db.matches.count_documents(
        {"failed": True, "primary_category": category, "mode": {"$exists": False}}
    )

    # Count papers with at least one match
    cat_paper_ids = set()
    async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
        cat_paper_ids.add(p["id"])
    match_paper_ids = set()
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ).limit(5000):
        match_paper_ids.add(m["paper1_id"])
        match_paper_ids.add(m["paper2_id"])
    unranked = len(cat_paper_ids - match_paper_ids)

    # Recent matches for this category (standard only)
    recent_all = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(10)

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

    # Per-category scheduler status
    cat_scheduler = _get_cat_status(category)

    return {
        "total_papers": total_papers,
        "total_matches": total_matches,
        "failed_matches": failed_matches,
        "unranked_papers": unranked,
        "category": category,
        "scheduler": cat_scheduler,
        "recent_matches": enriched_recent,
    }


@router.get("/progress", dependencies=[Depends(verify_admin)])
async def get_progress_estimate(category: str = "cs.RO"):
    """Triple-goal progress with estimated remaining matches and time."""
    settings = await get_settings()
    min_matches = settings.get("min_matches_per_paper", 3)
    max_matches = settings.get("max_matches_per_paper", 150)
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 12)
    global_paused = settings.get("paused", False)
    parallel_agents = settings.get("parallel_agents", 5)

    # Check tournament-level pause status
    tid = f"cat={category}|mode=standard"
    tournament = await db.tournaments.find_one({"tournament_id": tid}, {"_id": 0, "status": 1})
    tournament_paused = tournament and tournament.get("status") == "paused"
    is_paused = global_paused or tournament_paused

    all_paper_ids = []
    async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1}):
        all_paper_ids.append(p["id"])

    total_papers = len(all_paper_ids)
    if total_papers == 0:
        return {"total_papers": 0, "goals_met": True, "paused": is_paused, "category": category}

    pid_set = set(all_paper_ids)
    paper_match_count = {pid: 0 for pid in all_paper_ids}
    paper_wins = {pid: 0 for pid in all_paper_ids}
    compared_pairs = set()
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1
            compared_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
            w = m.get("winner_id")
            if w and w in paper_wins:
                paper_wins[w] += 1

    # Goal 1: All papers at min matches
    papers_at_min = sum(1 for c in paper_match_count.values() if c >= min_matches)
    deficit = sum(max(0, min_matches - c) for c in paper_match_count.values())
    matches_for_goal1 = max(0, (deficit + 1) // 2)
    goal1_met = papers_at_min == total_papers

    # Goal 2: Top-K papers have Wilson CI margin <= ci_target %
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

    # Goal 3: Cross-matches among non-capped top-K papers
    # Papers at max_matches are exempt — they've played enough
    topk_capped = {pid for pid in top_k_ids if paper_match_count[pid] >= max_matches}
    topk_crossmatch_ids = [pid for pid in top_k_ids if pid not in topk_capped]
    topk_total_pairs = len(topk_crossmatch_ids) * (len(topk_crossmatch_ids) - 1) // 2
    topk_matched_pairs = 0
    for i in range(len(topk_crossmatch_ids)):
        for j in range(i + 1, len(topk_crossmatch_ids)):
            pair = tuple(sorted([topk_crossmatch_ids[i], topk_crossmatch_ids[j]]))
            if pair in compared_pairs:
                topk_matched_pairs += 1
    matches_for_goal3 = topk_total_pairs - topk_matched_pairs
    goal3_met = bool(topk_matched_pairs == topk_total_pairs)

    total_est = matches_for_goal1 + matches_for_goal2 + matches_for_goal3
    seconds_per_match = 10.0 / max(parallel_agents, 1)
    est_minutes = max(0, round(total_est * seconds_per_match / 60))

    # Per-category counts
    cat_matches_done = sum(paper_match_count.values()) // 2  # each match counted twice
    cat_papers_with_pdf = await db.papers.count_documents({"categories.0": category, "full_text": {"$ne": None}})

    return {
        "total_papers": total_papers,
        "total_matches": cat_matches_done,
        "papers_with_pdf": cat_papers_with_pdf,
        "paused": is_paused,
        "global_paused": global_paused,
        "tournament_paused": bool(tournament_paused),
        "category": category,
        "goals_met": bool(goal1_met and goal2_met and goal3_met),
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
        "goal3": {
            "met": bool(goal3_met),
            "label": f"Top-{len(topk_crossmatch_ids)} cross-matches" + (f" ({len(topk_capped)} capped)" if topk_capped else ""),
            "done": int(topk_matched_pairs),
            "total": int(topk_total_pairs),
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
async def get_usage_stats(category: str = None):
    """Token usage by model with cost estimation, optionally filtered by category."""
    model_stats = {}
    match_query = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}
    if category:
        match_query["primary_category"] = category
    async for m in db.matches.find(
        match_query,
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
    if category:
        storage_pipeline = [
            {"$match": {"full_text": {"$ne": None}, "categories.0": category}},
            {"$project": {"text_len": {"$strLenCP": "$full_text"}}},
            {"$group": {"_id": None, "total_chars": {"$sum": "$text_len"}, "count": {"$sum": 1}}},
        ]
        total_papers = await db.papers.count_documents({"categories.0": category})
    else:
        storage_pipeline = [
            {"$match": {"full_text": {"$ne": None}}},
            {"$project": {"text_len": {"$strLenCP": "$full_text"}}},
            {"$group": {"_id": None, "total_chars": {"$sum": "$text_len"}, "count": {"$sum": 1}}},
        ]
        total_papers = await db.papers.count_documents({})

    storage_result = await db.papers.aggregate(storage_pipeline).to_list(1)
    if storage_result:
        total_chars = storage_result[0]["total_chars"]
        papers_with_text = storage_result[0]["count"]
    else:
        total_chars = 0
        papers_with_text = 0

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


# --- Prediction Experiment (Surprisingly Popular) ---

DEFAULT_PREDICTION_PROMPT = {
    "system_prompt": """You are predicting scientific consensus. Your task is NOT to evaluate the papers yourself, but to anticipate which paper the broader scientific community would consider more impactful.

Think about what most researchers in the field would say. Consider:
1. Which paper addresses a more widely recognized problem?
2. Which methodology would appeal to the mainstream research community?
3. Which results would generate more citations and follow-up work?
4. Which paper aligns better with current funding priorities and trends?

You MUST respond with valid JSON only:
{"winner": "paper1" or "paper2", "reasoning": "Explain why the scientific crowd would favor this paper (max 200 words)"}""",
    "user_prompt": """Predict which paper the scientific community would consider more impactful:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper would most researchers pick as more impactful? Respond with JSON only.""",
}


@router.get("/prediction-prompt", dependencies=[Depends(verify_admin)])
async def get_prediction_prompt():
    doc = await db.settings.find_one({"key": "prediction_prompt"}, {"_id": 0})
    if doc and doc.get("system_prompt"):
        return {
            "system_prompt": doc.get("system_prompt", ""),
            "user_prompt": doc.get("user_prompt", ""),
        }
    await db.settings.update_one(
        {"key": "prediction_prompt"},
        {"$set": {"key": "prediction_prompt", **DEFAULT_PREDICTION_PROMPT}},
        upsert=True,
    )
    return DEFAULT_PREDICTION_PROMPT


@router.put("/prediction-prompt", dependencies=[Depends(verify_admin)])
async def update_prediction_prompt(update: PromptUpdate):
    await db.settings.update_one(
        {"key": "prediction_prompt"},
        {"$set": {
            "key": "prediction_prompt",
            "system_prompt": update.system_prompt,
            "user_prompt": update.user_prompt,
        }},
        upsert=True,
    )
    return {"success": True}


class PredictionRunRequest(BaseModel):
    num_matches: int = 50
    category: str = "cs.RO"
    use_full_text: bool = False


@router.post("/run-prediction", dependencies=[Depends(verify_admin)])
async def run_prediction_tournament(body: PredictionRunRequest = PredictionRunRequest()):
    """Run prediction tournament with crowd-prediction prompt."""
    import asyncio
    mode = "prediction-fulltext" if body.use_full_text else "prediction"
    asyncio.create_task(_run_prediction_round(body.category, min(max(body.num_matches, 1), 500), abstract_only=not body.use_full_text, mode=mode))
    return {"status": "started", "category": body.category, "num_matches": body.num_matches, "mode": mode}


async def _run_prediction_round(category: str, max_pairs: int, abstract_only: bool = True, mode: str = "prediction"):
    """Run a prediction comparison round."""
    import uuid
    import random
    from services.llm import compare_papers

    # Load prediction prompt
    prompt_doc = await db.settings.find_one({"key": "prediction_prompt"}, {"_id": 0})
    if not prompt_doc or not prompt_doc.get("system_prompt"):
        prompt_config = DEFAULT_PREDICTION_PROMPT
    else:
        prompt_config = {
            "system_prompt": prompt_doc["system_prompt"],
            "user_prompt": prompt_doc["user_prompt"],
        }

    # Load papers
    fields = {"_id": 0, "id": 1, "title": 1, "abstract": 1, "authors": 1, "arxiv_id": 1, "published": 1}
    if not abstract_only:
        fields["full_text"] = 1
    all_papers = await db.papers.find(
        {"categories.0": category}, fields,
    ).to_list(5000)

    if len(all_papers) < 2:
        logger.warning(f"Prediction: not enough papers for {category}")
        return

    # Get existing matches for this mode to avoid duplicates
    existing = await db.matches.find(
        {"mode": mode, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ).to_list(100000)

    cat_paper_ids = {p["id"] for p in all_papers}
    compared = set()
    for m in existing:
        if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids:
            compared.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    # Generate random pairs (simple uniform sampling)
    paper_ids = [p["id"] for p in all_papers]
    pairs = []
    attempts = 0
    while len(pairs) < max_pairs and attempts < max_pairs * 10:
        p1, p2 = random.sample(paper_ids, 2)
        key = tuple(sorted([p1, p2]))
        if key not in compared:
            pairs.append((p1, p2))
            compared.add(key)
        attempts += 1

    if not pairs:
        logger.info(f"Prediction: no new pairs for {category}")
        return

    paper_lookup = {p["id"]: p for p in all_papers}
    settings = await get_settings()
    parallel = min(max(settings.get("parallel_agents", 5), 1), 20)
    completed = 0
    import asyncio as aio

    for i in range(0, len(pairs), parallel):
        batch = pairs[i:i + parallel]
        tasks = []
        presented = []
        for p1_id, p2_id in batch:
            if random.random() < 0.5:
                presented.append((p2_id, p1_id))
            else:
                presented.append((p1_id, p2_id))
        for p1_id, p2_id in presented:
            tasks.append(compare_papers(paper_lookup[p1_id], paper_lookup[p2_id], prompt_config, abstract_only=abstract_only))

        results = await aio.gather(*tasks, return_exceptions=True)

        for (p1_id, p2_id), result in zip(presented, results):
            match_doc = {
                "id": str(uuid.uuid4()),
                "paper1_id": p1_id,
                "paper2_id": p2_id,
                "mode": mode,
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

            await db.matches.insert_one(match_doc)
        await aio.sleep(0.5)

    logger.info(f"Prediction round for {category}: {completed}/{len(pairs)} completed")


@router.get("/experiment-comparison", dependencies=[Depends(verify_admin)])
async def get_experiment_comparison(category: str = "cs.RO"):
    """Compare standard vs prediction rankings for the Surprisingly Popular experiment."""
    from services.ranking import compute_leaderboard

    # Load papers
    all_papers = await db.papers.find(
        {"categories.0": category},
        {"_id": 0, "full_text": 0},
    ).to_list(5000)

    if not all_papers:
        return {"papers": [], "category": category, "standard_matches": 0, "prediction_matches": 0}

    cat_paper_ids = {p["id"] for p in all_papers}

    # Load standard matches (no mode field or mode=standard)
    all_matches_raw = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "mode": 1, "completed": 1, "failed": 1},
    ).to_list(200000)

    standard_matches = [m for m in all_matches_raw
                        if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids
                        and not m.get("mode")]

    prediction_matches = [m for m in all_matches_raw
                          if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids
                          and m.get("mode") == "prediction"]

    prediction_ft_matches = [m for m in all_matches_raw
                             if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids
                             and m.get("mode") == "prediction-fulltext"]

    # Compute rankings for each mode
    std_ranking = compute_leaderboard(all_papers, standard_matches)
    pred_ranking = compute_leaderboard(all_papers, prediction_matches)
    pred_ft_ranking = compute_leaderboard(all_papers, prediction_ft_matches)

    # Build lookup
    std_lookup = {p["id"]: p for p in std_ranking}
    pred_lookup = {p["id"]: p for p in pred_ranking}
    pred_ft_lookup = {p["id"]: p for p in pred_ft_ranking}

    # Merge into comparison table
    comparison = []
    for paper in all_papers:
        pid = paper["id"]
        std = std_lookup.get(pid, {})
        pred = pred_lookup.get(pid, {})
        pred_ft = pred_ft_lookup.get(pid, {})
        std_rank = std.get("rank", 999)
        pred_rank = pred.get("rank", 999)
        pred_ft_rank = pred_ft.get("rank", 999)
        comparison.append({
            "id": pid,
            "title": paper["title"],
            "authors": paper.get("authors", [])[:3],
            "arxiv_id": paper.get("arxiv_id", ""),
            "standard_rank": std_rank,
            "standard_score": std.get("score", 1200),
            "standard_win_rate": std.get("win_rate", 0),
            "standard_matches": std.get("comparisons", 0),
            "prediction_rank": pred_rank,
            "prediction_score": pred.get("score", 1200),
            "prediction_win_rate": pred.get("win_rate", 0),
            "prediction_matches": pred.get("comparisons", 0),
            "rank_delta": pred_rank - std_rank,
            "pred_ft_rank": pred_ft_rank,
            "pred_ft_score": pred_ft.get("score", 1200),
            "pred_ft_win_rate": pred_ft.get("win_rate", 0),
            "pred_ft_matches": pred_ft.get("comparisons", 0),
            "rank_delta_ft": pred_ft_rank - std_rank,
        })

    return {
        "papers": comparison,
        "category": category,
        "standard_matches": len(standard_matches),
        "prediction_matches": len(prediction_matches),
        "prediction_ft_matches": len(prediction_ft_matches),
    }


MODEL_PRICING = {
    "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
    "anthropic/claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "gemini/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
}


@router.get("/timeseries", dependencies=[Depends(verify_admin)])
async def get_timeseries(category: Optional[str] = None):
    """Return daily time-series data for papers, matches, tokens, costs."""
    # --- Papers by day ---
    paper_query = {}
    if category:
        paper_query["categories.0"] = category
    papers_daily = defaultdict(lambda: defaultdict(int))
    total_papers_count = 0
    async for p in db.papers.find(paper_query, {"_id": 0, "added_at": 1, "published": 1, "categories": 1}):
        total_papers_count += 1
        # Prefer added_at, fall back to published date
        added = p.get("added_at") or p.get("published") or ""
        if not added or len(added) < 10:
            continue
        day = added[:10]  # "YYYY-MM-DD"
        cats = p.get("categories") or []
        cat = cats[0] if cats else "unknown"
        papers_daily[day][cat] += 1
        papers_daily[day]["_total"] += 1

    # --- Matches by day + model stats ---
    match_query = {"completed": True, "failed": {"$ne": True}}
    if category:
        match_query["primary_category"] = category
    matches_daily = defaultdict(lambda: defaultdict(lambda: {
        "count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0
    }))
    # System-wide model breakdown (not per-category, always total)
    model_stats = {}

    async for m in db.matches.find(
        match_query,
        {"_id": 0, "created_at": 1, "primary_category": 1, "tokens": 1, "model_used": 1, "mode": 1},
    ):
        if m.get("mode"):
            continue  # Exclude experiment matches
        created = m.get("created_at") or ""
        if not created or len(created) < 10:
            continue
        day = created[:10]
        cat = m.get("primary_category") or "unknown"
        tokens = m.get("tokens") or {}
        inp = tokens.get("input_est", 0) or 0
        out = tokens.get("output_est", 0) or 0
        mu = m.get("model_used") or {}
        provider = mu.get("provider", "unknown")
        model = mu.get("model", "unknown")
        model_key = f"{provider}/{model}" if provider != "unknown" or model != "unknown" else "unknown"
        pricing = MODEL_PRICING.get(model_key, {"input": 2.0, "output": 10.0})
        cost = (inp / 1_000_000) * pricing["input"] + (out / 1_000_000) * pricing["output"]

        for key in [cat, "_total"]:
            bucket = matches_daily[day][key]
            bucket["count"] += 1
            bucket["input_tokens"] += inp
            bucket["output_tokens"] += out
            bucket["cost"] += cost

        # Accumulate per-model stats (system-wide, always unfiltered by category)
        if model_key != "unknown":
            if model_key not in model_stats:
                model_stats[model_key] = {"matches": 0, "input_tokens": 0, "output_tokens": 0}
            model_stats[model_key]["matches"] += 1
            model_stats[model_key]["input_tokens"] += inp
            model_stats[model_key]["output_tokens"] += out

    # Build sorted date list
    all_dates = sorted(set(list(papers_daily.keys()) + list(matches_daily.keys())))
    settings_for_cats = await get_settings()
    all_cats = sorted(settings_for_cats.get("active_categories", list(CATEGORIES.keys())))

    # Build daily series
    series = []
    cum_papers = defaultdict(int)
    cum_matches = defaultdict(int)
    cum_tokens = defaultdict(int)
    cum_cost = defaultdict(float)

    for day in all_dates:
        entry = {"date": day}

        # Papers
        p_total = papers_daily[day].get("_total", 0)
        cum_papers["_total"] += p_total
        entry["papers_daily"] = p_total
        entry["papers_cumulative"] = cum_papers["_total"]

        # Per-category papers
        for cat in all_cats:
            p_cat = papers_daily[day].get(cat, 0)
            cum_papers[cat] += p_cat
            entry[f"papers_daily_{cat}"] = p_cat
            entry[f"papers_cumulative_{cat}"] = cum_papers[cat]

        # Matches
        m_data = matches_daily[day].get("_total", {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        cum_matches["_total"] += m_data["count"]
        cum_tokens["_total"] += m_data["input_tokens"] + m_data["output_tokens"]
        cum_cost["_total"] += m_data["cost"]
        entry["matches_daily"] = m_data["count"]
        entry["matches_cumulative"] = cum_matches["_total"]
        entry["tokens_daily"] = m_data["input_tokens"] + m_data["output_tokens"]
        entry["tokens_cumulative"] = cum_tokens["_total"]
        entry["cost_daily"] = round(m_data["cost"], 4)
        entry["cost_cumulative"] = round(cum_cost["_total"], 4)
        entry["input_tokens_daily"] = m_data["input_tokens"]
        entry["output_tokens_daily"] = m_data["output_tokens"]

        # Per-category matches
        for cat in all_cats:
            mc = matches_daily[day].get(cat, {"count": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
            cum_matches[cat] += mc["count"]
            cum_tokens[cat] += mc["input_tokens"] + mc["output_tokens"]
            cum_cost[cat] += mc["cost"]
            entry[f"matches_daily_{cat}"] = mc["count"]
            entry[f"matches_cumulative_{cat}"] = cum_matches[cat]
            entry[f"tokens_daily_{cat}"] = mc["input_tokens"] + mc["output_tokens"]
            entry[f"tokens_cumulative_{cat}"] = cum_tokens[cat]
            entry[f"cost_daily_{cat}"] = round(mc["cost"], 4)
            entry[f"cost_cumulative_{cat}"] = round(cum_cost[cat], 4)

        series.append(entry)

    # Compute per-model costs
    total_model_cost = 0.0
    for key, stats in model_stats.items():
        pricing = MODEL_PRICING.get(key, {"input": 2.0, "output": 10.0})
        cost_in = (stats["input_tokens"] / 1_000_000) * pricing["input"]
        cost_out = (stats["output_tokens"] / 1_000_000) * pricing["output"]
        stats["cost_input"] = round(cost_in, 4)
        stats["cost_output"] = round(cost_out, 4)
        stats["cost_total"] = round(cost_in + cost_out, 4)
        total_model_cost += cost_in + cost_out

    return {
        "series": series,
        "categories": all_cats,
        "totals": {
            "papers": max(cum_papers["_total"], total_papers_count),
            "matches": cum_matches["_total"],
            "tokens": cum_tokens["_total"],
            "input_tokens": sum(s.get("input_tokens", 0) for s in model_stats.values()),
            "output_tokens": sum(s.get("output_tokens", 0) for s in model_stats.values()),
            "cost": round(cum_cost["_total"], 4),
        },
        "models": model_stats,
    }


@router.get("/tournaments", dependencies=[Depends(verify_admin)])
async def get_tournaments():
    tournaments = await db.tournaments.find({}, {"_id": 0}).sort("category", 1).to_list(500)
    return {"tournaments": tournaments}


@router.post("/tournaments/{tournament_id}/status", dependencies=[Depends(verify_admin)])
async def update_tournament_status(tournament_id: str, request: Request):
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("active", "paused"):
        raise HTTPException(400, "Status must be 'active' or 'paused'")

    result = await db.tournaments.update_one(
        {"tournament_id": tournament_id},
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Tournament not found")

    # Wake scheduler immediately on resume so it doesn't wait up to 30s
    if new_status == "active":
        wake_scheduler()

    return {"status": "ok", "tournament_status": new_status}



# --- Category Management ---

@router.get("/arxiv-categories", dependencies=[Depends(verify_admin)])
async def get_arxiv_categories():
    """Return full arXiv taxonomy for searchable category picker."""
    from core.arxiv_categories import ARXIV_TAXONOMY, get_group
    settings = await get_settings()
    active = set(settings.get("active_categories", list(CATEGORIES.keys())))

    cats = []
    for cat_id, name in sorted(ARXIV_TAXONOMY.items()):
        cats.append({
            "id": cat_id,
            "name": name,
            "group": get_group(cat_id),
            "active": cat_id in active,
        })
    return {"categories": cats, "active": sorted(active)}


class CategoryAction(BaseModel):
    category_id: str


@router.post("/categories/add", dependencies=[Depends(verify_admin)])
async def add_category(body: CategoryAction):
    """Add a new tournament category."""
    from core.arxiv_categories import ARXIV_TAXONOMY
    cat_id = body.category_id.strip()
    if cat_id not in ARXIV_TAXONOMY:
        raise HTTPException(400, f"Unknown arXiv category: {cat_id}")

    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))
    if cat_id in active:
        raise HTTPException(400, f"{cat_id} is already active")

    active.append(cat_id)
    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"active_categories": active}},
        upsert=True,
    )

    # Initialize tournament for the new category
    from services.scheduler import init_tournament_registry
    await init_tournament_registry()

    logger.info(f"Admin added category: {cat_id}")
    return {"status": "ok", "active_categories": active}


@router.post("/categories/remove", dependencies=[Depends(verify_admin)])
async def remove_category(body: CategoryAction):
    """Remove a tournament category (keeps data, just stops tournaments)."""
    cat_id = body.category_id.strip()
    settings = await get_settings()
    active = settings.get("active_categories", list(CATEGORIES.keys()))

    if cat_id not in active:
        raise HTTPException(400, f"{cat_id} is not active")
    if len(active) <= 1:
        raise HTTPException(400, "Cannot remove the last category")

    active = [c for c in active if c != cat_id]
    await db.settings.update_one(
        {"key": "global"},
        {"$set": {"active_categories": active}},
        upsert=True,
    )

    # Pause the tournament (don't delete data)
    tid = f"cat={cat_id}|mode=standard"
    await db.tournaments.update_one(
        {"tournament_id": tid},
        {"$set": {"status": "paused", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )

    logger.info(f"Admin removed category: {cat_id}")
    return {"status": "ok", "active_categories": active}


@router.get("/category-estimate/{cat_id}", dependencies=[Depends(verify_admin)])
async def estimate_category(cat_id: str):
    """Estimate weekly paper volume and tournament cost for a category."""
    from core.arxiv_categories import ARXIV_TAXONOMY
    from services.arxiv import fetch_arxiv_papers

    if cat_id not in ARXIV_TAXONOMY:
        raise HTTPException(400, f"Unknown arXiv category: {cat_id}")

    # Fetch a small sample to estimate volume
    try:
        sample = await fetch_arxiv_papers(category=cat_id, max_results=100)
        total_fetched = len(sample)
    except Exception as e:
        logger.warning(f"Failed to estimate {cat_id}: {e}")
        total_fetched = 0

    # Estimate weekly papers from the sample date range
    weekly_papers = 0
    if total_fetched >= 2:
        from datetime import datetime, timezone
        dates = []
        for p in sample:
            try:
                d = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
                dates.append(d)
            except (ValueError, KeyError):
                pass
        if len(dates) >= 2:
            dates.sort()
            span_days = max((dates[-1] - dates[0]).days, 1)
            weekly_papers = round(len(dates) / span_days * 7)
    if weekly_papers == 0 and total_fetched > 0:
        weekly_papers = total_fetched  # conservative fallback

    # Cost estimate based on historical matches-per-paper ratio
    settings = await get_settings()
    min_matches = settings.get("min_matches_per_paper", 5)
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 12)

    # Check if we already have papers for this category
    existing_papers = await db.papers.count_documents({"categories.0": cat_id})
    existing_matches = await db.matches.count_documents(
        {"completed": True, "failed": {"$ne": True}, "primary_category": cat_id, "mode": {"$exists": False}}
    )

    # Calculate matches-per-paper ratio from historical data across ALL categories
    # This captures the real cost including CI convergence, top-K focus, and re-matches
    total_hist_papers = 0
    total_hist_matches = 0
    active_cats = settings.get("active_categories", list(CATEGORIES.keys()))
    for ac in active_cats:
        hp = await db.papers.count_documents({"categories.0": ac})
        hm = await db.matches.count_documents(
            {"completed": True, "failed": {"$ne": True}, "primary_category": ac, "mode": {"$exists": False}}
        )
        total_hist_papers += hp
        total_hist_matches += hm

    # Use historical ratio if available, otherwise estimate from settings
    if total_hist_papers >= 20 and total_hist_matches >= 100:
        matches_per_paper = total_hist_matches / total_hist_papers
    else:
        # Theoretical estimate when no history: min_matches * ~4 (empirical multiplier
        # accounting for CI convergence rounds, top-K focus, and re-matching)
        matches_per_paper = min_matches * 4

    matches_needed = round(weekly_papers * matches_per_paper)

    # Cost per match: average across 3 models (~$0.015 per comparison)
    avg_cost_per_match = 0.015
    weekly_cost = round(matches_needed * avg_cost_per_match, 2)

    return {
        "category_id": cat_id,
        "name": ARXIV_TAXONOMY.get(cat_id, cat_id),
        "estimated_weekly_papers": weekly_papers,
        "estimated_weekly_matches": matches_needed,
        "estimated_weekly_cost": weekly_cost,
        "existing_papers": existing_papers,
        "existing_matches": existing_matches,
        "sample_size": total_fetched,
        "settings_used": {
            "min_matches_per_paper": min_matches,
            "top_k_focus": top_k,
            "ci_target": ci_target,
            "matches_per_paper_ratio": round(matches_per_paper, 1),
        },
    }
