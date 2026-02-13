"""
SciPost Pairwise Comparison — Compare AI vs human referees on specific dimensions.

Fetches papers with referee reports from SciPost Physics, compares AI judgments
against human ratings on: validity, significance, originality, clarity.
"""
import asyncio
import uuid
import re
import random
import time as _time
import aiohttp
from datetime import datetime, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional, List

from core.config import db, logger, TOURNAMENT_MODELS
from core.auth import verify_admin
from services.llm import call_llm, compare_papers

router = APIRouter(prefix="/api/scipost")

_state = {"fetching": False, "running": False, "progress": {}}

# SciPost rating scale (convert to numeric for comparison)
RATING_SCALE = {"top": 6, "high": 5, "good": 4, "ok": 3, "low": 2, "poor": 1}
DIMENSIONS = ["validity", "significance", "originality", "clarity"]

# Cache for SciPost submissions
_scipost_cache = {"submissions": None, "ts": 0, "ttl": 600}  # 10 min TTL


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch URL asynchronously."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            return await resp.text()
    except Exception as e:
        logger.debug(f"Fetch error {url}: {e}")
        return ""


def _parse_scipost_submission_list(html: str) -> list:
    """Parse SciPost submissions list page to get submission IDs."""
    # Find all submission links like /submissions/scipost_202507_00056v2/
    pattern = r'href="/submissions/(scipost_\d+_\d+v\d+)/"'
    return list(set(re.findall(pattern, html)))


def _parse_scipost_submission(html: str, submission_id: str) -> dict:
    """Parse a SciPost submission page to extract paper info and referee reports."""
    result = {"submission_id": submission_id, "reports": []}
    
    # Extract title from <title> tag
    title_match = re.search(r'<title>SciPost Submission:\s*([^<]+)</title>', html)
    if title_match:
        result["title"] = title_match.group(1).strip()
    
    # Extract abstract - it's in a <p> tag after <h3 class="mt-4">Abstract</h3>
    abstract_match = re.search(r'<h3[^>]*>Abstract</h3>\s*<p>([^<]+)</p>', html, re.DOTALL)
    if abstract_match:
        abstract = abstract_match.group(1).strip()
        result["abstract"] = re.sub(r'\s+', ' ', abstract)
    
    # Extract specialty/field from breadcrumb or elsewhere
    field_match = re.search(r'Specialty:\s*([^<\n]+)', html)
    if field_match:
        result["field"] = field_match.group(1).strip()
    else:
        result["field"] = "Physics"
    
    # Find all ratings divs with their content
    # Each ratings div belongs to the previous report div
    ratings_blocks = re.findall(r'<div class="ratings">\s*<ul>(.*?)</ul>\s*</div>', html, re.DOTALL)
    
    for idx, ratings_html in enumerate(ratings_blocks):
        report = {"report_num": idx + 1, "referee": f"Referee_{idx + 1}"}
        
        for dim in DIMENSIONS + ["formatting", "grammar"]:
            dim_match = re.search(rf'{dim}:\s*(\w+)', ratings_html, re.I)
            if dim_match:
                rating_text = dim_match.group(1).lower()
                report[dim] = RATING_SCALE.get(rating_text, 0)
        
        # Only include reports with at least some dimension ratings
        if any(report.get(d) for d in DIMENSIONS):
            result["reports"].append(report)
    
    logger.debug(f"SciPost parse {submission_id}: title={bool(result.get('title'))}, abstract={bool(result.get('abstract'))}, reports={len(result.get('reports', []))}")
    
    return result


async def _fetch_scipost_submissions(session: aiohttp.ClientSession, num_pages: int = 5) -> list:
    """Fetch list of SciPost submissions with reports."""
    submissions = []
    
    # Fetch submissions across different categories that are likely to have reports
    # Focus on published/accepted submissions as they have complete reports
    urls = [
        "https://scipost.org/submissions/?field=physics&status=published",
        "https://scipost.org/submissions/?field=physics&status=resubmission_incoming",
        "https://scipost.org/submissions/?specialty=phys-qp",
        "https://scipost.org/submissions/?specialty=phys-sm",
        "https://scipost.org/submissions/?specialty=phys-he",
    ]
    
    for url in urls:
        try:
            html = await _fetch_url(session, url)
            sub_ids = _parse_scipost_submission_list(html)
            submissions.extend(sub_ids)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.debug(f"SciPost fetch error for {url}: {e}")
    
    return list(set(submissions))


async def _fetch_submission_details(session: aiohttp.ClientSession, submission_id: str) -> Optional[dict]:
    """Fetch and parse a single submission's details."""
    # Try the given version first
    url = f"https://scipost.org/submissions/{submission_id}/"
    html = await _fetch_url(session, url)
    if not html:
        return None
    
    data = _parse_scipost_submission(html, submission_id)
    
    # If no reports found, try earlier versions (v1 if we got v2, etc.)
    if not data.get("reports") and "v" in submission_id:
        version_match = re.search(r'v(\d+)$', submission_id)
        if version_match:
            current_v = int(version_match.group(1))
            # Try v1 through current-1
            for v in range(1, current_v):
                alt_id = re.sub(r'v\d+$', f'v{v}', submission_id)
                alt_url = f"https://scipost.org/submissions/{alt_id}/"
                alt_html = await _fetch_url(session, alt_url)
                if alt_html:
                    alt_data = _parse_scipost_submission(alt_html, alt_id)
                    if alt_data.get("reports"):
                        # Use earlier version's reports but current version's title/abstract
                        data["reports"] = alt_data["reports"]
                        break
    
    # Only return if we have title, abstract, and at least one report with ratings
    if data.get("title") and data.get("abstract") and data.get("reports"):
        return data
    return None


# ─── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    total = await db.scipost_comparisons.count_documents({})
    with_ai = await db.scipost_comparisons.count_documents({"ai_completed": True})
    failed = await db.scipost_comparisons.count_documents({"ai_failed": True})
    
    # Count by dimension
    dim_counts = {}
    for dim in DIMENSIONS:
        dim_counts[dim] = await db.scipost_comparisons.count_documents({"dimension": dim, "ai_completed": True})
    
    return {
        "total_comparisons": total,
        "ai_completed": with_ai,
        "ai_failed": failed,
        "ai_pending": total - with_ai - failed,
        "by_dimension": dim_counts,
        "fetching": _state["fetching"],
        "running": _state["running"],
        "progress": _state["progress"],
    }


# ─── Fetch & Run ───────────────────────────────────────────────────────────────

class FetchAndRunRequest(BaseModel):
    num_papers: int = 20
    dimensions: List[str] = DIMENSIONS


@router.post("/fetch-and-run", dependencies=[Depends(verify_admin)])
async def fetch_and_run(body: FetchAndRunRequest):
    """Fetch SciPost papers and run dimension-specific comparisons."""
    if _state["fetching"] or _state["running"]:
        return {"status": "already_running"}
    
    # Validate dimensions
    valid_dims = [d for d in body.dimensions if d in DIMENSIONS]
    if not valid_dims:
        return {"status": "error", "message": f"Invalid dimensions. Valid: {DIMENSIONS}"}
    
    asyncio.create_task(_fetch_and_run_scipost(body.num_papers, valid_dims))
    return {"status": "started", "num_papers": body.num_papers, "dimensions": valid_dims}


async def _fetch_and_run_scipost(num_papers: int, dimensions: list):
    _state["fetching"] = True
    _state["running"] = True
    _state["progress"] = {"phase": "scanning", "papers_found": 0, "comparisons_done": 0, "target": num_papers}
    
    try:
        async with aiohttp.ClientSession() as session:
            # Phase 1: Get list of submissions
            logger.info("SciPost: scanning for submissions...")
            submission_ids = await _fetch_scipost_submissions(session)
            logger.info(f"SciPost: found {len(submission_ids)} submissions")
            
            if not submission_ids:
                logger.warning("SciPost: no submissions found")
                return
            
            # Shuffle to get variety
            random.shuffle(submission_ids)
            
            # Phase 2: Fetch paper details in parallel batches
            _state["progress"]["phase"] = "fetching papers"
            papers_with_reports = []
            
            for i in range(0, min(len(submission_ids), num_papers * 3), 8):
                if len(papers_with_reports) >= num_papers:
                    break
                    
                batch = submission_ids[i:i+8]
                tasks = [_fetch_submission_details(session, sid) for sid in batch]
                results = await asyncio.gather(*tasks)
                
                for paper in results:
                    if paper and len(papers_with_reports) < num_papers:
                        papers_with_reports.append(paper)
                        _state["progress"]["papers_found"] = len(papers_with_reports)
                
                await asyncio.sleep(0.5)
            
            logger.info(f"SciPost: fetched {len(papers_with_reports)} papers with reports")
            
            if len(papers_with_reports) < 2:
                logger.warning("SciPost: not enough papers with reports")
                return
            
            # Phase 3: Create pairs and evaluate each dimension
            _state["progress"]["phase"] = "evaluating"
            comparisons_done = 0
            
            # For each paper with multiple reports, compare dimensions
            for paper in papers_with_reports:
                if not _state["running"]:
                    break
                
                for report in paper.get("reports", []):
                    for dim in dimensions:
                        if not _state["running"]:
                            break
                        
                        human_rating = report.get(dim)
                        if not human_rating:
                            continue
                        
                        # Create a comparison record
                        comparison = {
                            "id": str(uuid.uuid4()),
                            "source": "scipost",
                            "submission_id": paper["submission_id"],
                            "paper_title": paper.get("title", ""),
                            "paper_abstract": paper.get("abstract", ""),
                            "field": paper.get("field", "Physics"),
                            "referee": report.get("referee", "Anonymous"),
                            "dimension": dim,
                            "human_rating": human_rating,
                            "human_rating_label": [k for k, v in RATING_SCALE.items() if v == human_rating][0] if human_rating in RATING_SCALE.values() else "unknown",
                            "ai_results": {},
                            "ai_completed": False,
                            "ai_failed": False,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                        
                        # Run AI evaluation for this dimension
                        try:
                            ai_results = await _evaluate_dimension(
                                paper.get("title", ""),
                                paper.get("abstract", ""),
                                dim
                            )
                            comparison["ai_results"] = ai_results
                            comparison["ai_completed"] = True
                            
                            # Calculate AI consensus rating
                            ai_ratings = [r.get("rating") for r in ai_results.values() if r.get("rating")]
                            if ai_ratings:
                                comparison["ai_consensus_rating"] = round(sum(ai_ratings) / len(ai_ratings), 1)
                            
                        except Exception as e:
                            logger.warning(f"SciPost eval error: {e}")
                            comparison["ai_failed"] = True
                            comparison["ai_error"] = str(e)[:200]
                        
                        # Save to DB
                        await db.scipost_comparisons.insert_one(comparison)
                        comparisons_done += 1
                        _state["progress"]["comparisons_done"] = comparisons_done
                        
                        logger.info(f"SciPost [{comparisons_done}] {dim}: human={human_rating}, paper={paper.get('title', '')[:30]}...")
            
            logger.info(f"SciPost fetch+run complete: {comparisons_done} comparisons")
            
    except Exception as e:
        logger.error(f"SciPost fetch+run error: {e}")
    finally:
        _state["fetching"] = False
        _state["running"] = False


async def _evaluate_dimension(title: str, abstract: str, dimension: str) -> dict:
    """Ask all 3 models to rate a paper on a specific dimension."""
    
    dimension_prompts = {
        "validity": "Rate the scientific VALIDITY of this paper's methodology and conclusions. Consider: Are the methods sound? Are conclusions supported by evidence? Are there logical flaws?",
        "significance": "Rate the SIGNIFICANCE and potential impact of this paper. Consider: Does it address an important problem? Could it influence the field? Is the contribution substantial?",
        "originality": "Rate the ORIGINALITY of this paper. Consider: Does it present novel ideas or methods? Is it incremental or transformative? Does it open new research directions?",
        "clarity": "Rate the CLARITY of this paper's presentation. Consider: Is it well-written? Are concepts explained clearly? Is the structure logical? Can readers follow the arguments?",
    }
    
    prompt = f"""You are a scientific referee evaluating a physics paper.

PAPER TITLE: {title}

ABSTRACT: {abstract}

TASK: {dimension_prompts.get(dimension, f"Rate the {dimension} of this paper.")}

Rate this paper's {dimension.upper()} on a scale of 1-6:
- 6 = Top (exceptional, among the best)
- 5 = High (very strong)
- 4 = Good (solid, meets standards)
- 3 = OK (acceptable but has issues)
- 2 = Low (significant problems)
- 1 = Poor (major flaws)

Respond with ONLY a JSON object:
{{"rating": <1-6>, "reasoning": "<brief explanation in 1-2 sentences>"}}"""

    results = {}
    tasks = []
    
    for model_info in TOURNAMENT_MODELS:
        tasks.append((model_info, _call_model_for_rating(prompt, model_info)))
    
    responses = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
    
    for (model_info, _), response in zip(tasks, responses):
        mk = f"{model_info['provider']}:{model_info['model']}"
        if isinstance(response, Exception):
            results[mk] = {"rating": None, "error": str(response)[:100]}
        else:
            results[mk] = response
    
    return results


async def _call_model_for_rating(prompt: str, model_info: dict) -> dict:
    """Call a single model and parse the rating response."""
    try:
        response = await call_llm(
            prompt,
            system="You are a scientific paper reviewer. Respond only with valid JSON.",
            model_override=model_info
        )
        
        # Parse JSON response
        import json
        # Try to extract JSON from response
        json_match = re.search(r'\{[^}]+\}', response)
        if json_match:
            data = json.loads(json_match.group())
            rating = data.get("rating")
            if isinstance(rating, (int, float)) and 1 <= rating <= 6:
                return {"rating": int(rating), "reasoning": data.get("reasoning", "")[:200]}
        
        # Fallback: try to find a number
        num_match = re.search(r'\b([1-6])\b', response)
        if num_match:
            return {"rating": int(num_match.group(1)), "reasoning": response[:200]}
        
        return {"rating": None, "error": "Could not parse rating"}
    except Exception as e:
        return {"rating": None, "error": str(e)[:100]}


@router.post("/stop", dependencies=[Depends(verify_admin)])
async def stop():
    _state["running"] = False
    _state["fetching"] = False
    return {"status": "stopped"}


# ─── Results ───────────────────────────────────────────────────────────────────

@router.get("/results")
async def get_results():
    comparisons = await db.scipost_comparisons.find(
        {"ai_completed": True},
        {"_id": 0}
    ).to_list(10000)
    
    if not comparisons:
        return {"status": "no_data", "total": 0}
    
    total = len(comparisons)
    
    # Agreement by dimension (within 1 point = agreement)
    dim_stats = defaultdict(lambda: {"exact": 0, "close": 0, "total": 0, "mae": []})
    for c in comparisons:
        dim = c.get("dimension")
        human = c.get("human_rating")
        ai_consensus = c.get("ai_consensus_rating")
        
        if dim and human and ai_consensus:
            dim_stats[dim]["total"] += 1
            diff = abs(human - ai_consensus)
            dim_stats[dim]["mae"].append(diff)
            if diff == 0:
                dim_stats[dim]["exact"] += 1
            if diff <= 1:
                dim_stats[dim]["close"] += 1
    
    dim_results = {}
    for dim, stats in dim_stats.items():
        mae = sum(stats["mae"]) / len(stats["mae"]) if stats["mae"] else 0
        dim_results[dim] = {
            "total": stats["total"],
            "exact_match": stats["exact"],
            "exact_rate": round(stats["exact"] / max(stats["total"], 1) * 100, 1),
            "close_match": stats["close"],  # within 1 point
            "close_rate": round(stats["close"] / max(stats["total"], 1) * 100, 1),
            "mae": round(mae, 2),  # Mean Absolute Error
        }
    
    # Per-model accuracy by dimension
    model_dim_stats = defaultdict(lambda: defaultdict(lambda: {"exact": 0, "close": 0, "total": 0}))
    for c in comparisons:
        dim = c.get("dimension")
        human = c.get("human_rating")
        for mk, res in c.get("ai_results", {}).items():
            ai_rating = res.get("rating")
            if human and ai_rating:
                model_dim_stats[mk][dim]["total"] += 1
                diff = abs(human - ai_rating)
                if diff == 0:
                    model_dim_stats[mk][dim]["exact"] += 1
                if diff <= 1:
                    model_dim_stats[mk][dim]["close"] += 1
    
    model_results = {}
    for mk, dims in model_dim_stats.items():
        model_results[mk] = {}
        for dim, stats in dims.items():
            model_results[mk][dim] = {
                "total": stats["total"],
                "close_rate": round(stats["close"] / max(stats["total"], 1) * 100, 1),
            }
    
    # Overall model accuracy (across all dimensions)
    model_overall = {}
    for mk, dims in model_dim_stats.items():
        total_close = sum(d["close"] for d in dims.values())
        total_all = sum(d["total"] for d in dims.values())
        model_overall[mk] = {
            "total": total_all,
            "close_rate": round(total_close / max(total_all, 1) * 100, 1),
        }
    
    # Rating distribution comparison
    human_dist = defaultdict(int)
    ai_dist = defaultdict(int)
    for c in comparisons:
        human = c.get("human_rating")
        ai = c.get("ai_consensus_rating")
        if human:
            human_dist[int(human)] += 1
        if ai:
            ai_dist[round(ai)] += 1
    
    # Sample comparisons — include referee and submission_id
    samples = [{
        "paper_title": c.get("paper_title", "")[:60],
        "submission_id": c.get("submission_id", ""),
        "referee": c.get("referee", ""),
        "dimension": c.get("dimension"),
        "human_rating": c.get("human_rating"),
        "human_label": c.get("human_rating_label"),
        "ai_consensus": c.get("ai_consensus_rating"),
        "ai_ratings": {k: v.get("rating") for k, v in c.get("ai_results", {}).items()},
        "field": c.get("field"),
    } for c in comparisons[:50]]
    
    # Dimension prompts used for AI evaluation
    dimension_prompts = {
        "validity": "Rate the scientific VALIDITY of this paper's methodology and conclusions. Consider: Are the methods sound? Are conclusions supported by evidence? Are there logical flaws?",
        "significance": "Rate the SIGNIFICANCE and potential impact of this paper. Consider: Does it address an important problem? Could it influence the field? Is the contribution substantial?",
        "originality": "Rate the ORIGINALITY of this paper. Consider: Does it present novel ideas or methods? Is it incremental or transformative? Does it open new research directions?",
        "clarity": "Rate the CLARITY of this paper's presentation. Consider: Is it well-written? Are concepts explained clearly? Is the structure logical? Can readers follow the arguments?",
    }
    prompt_template = (
        "You are a scientific referee evaluating a physics paper.\n\n"
        "PAPER TITLE: {title}\n\nABSTRACT: {abstract}\n\n"
        "TASK: {task}\n\n"
        "Rate this paper's {DIMENSION} on a scale of 1-6:\n"
        "- 6 = Top (exceptional, among the best)\n"
        "- 5 = High (very strong)\n"
        "- 4 = Good (solid, meets standards)\n"
        "- 3 = OK (acceptable but has issues)\n"
        "- 2 = Low (significant problems)\n"
        "- 1 = Poor (major flaws)\n\n"
        'Respond with ONLY a JSON object:\n'
        '{"rating": <1-6>, "reasoning": "<brief explanation in 1-2 sentences>"}'
    )
    
    return {
        "status": "ok",
        "total_comparisons": total,
        "by_dimension": dim_results,
        "by_model": model_results,
        "model_overall": model_overall,
        "rating_distribution": {
            "human": dict(human_dist),
            "ai": dict(ai_dist),
        },
        "samples": samples,
        "prompts": {
            "template": prompt_template,
            "dimension_tasks": dimension_prompts,
            "system": "You are a scientific paper reviewer. Respond only with valid JSON.",
        },
    }


# ─── Reset ─────────────────────────────────────────────────────────────────────

@router.post("/reset", dependencies=[Depends(verify_admin)])
async def reset():
    if _state["running"] or _state["fetching"]:
        return {"status": "error", "message": "Cannot reset while running"}
    r = await db.scipost_comparisons.delete_many({})
    return {"status": "ok", "deleted": r.deleted_count}


# ═══════════════════════════════════════════════════════════════════════════════
# PAIRWISE COMPARISON (per dimension) — head-to-head paper pairs
# ═══════════════════════════════════════════════════════════════════════════════

_pw_state = {"fetching": False, "running": False, "progress": {}}

DIMENSION_PW_TASKS = {
    "validity": "Which paper demonstrates stronger scientific VALIDITY? Consider: soundness of methods, evidence supporting conclusions, logical consistency.",
    "significance": "Which paper has greater SIGNIFICANCE and potential impact? Consider: importance of the problem, potential to influence the field, magnitude of contribution.",
    "originality": "Which paper shows more ORIGINALITY? Consider: novelty of ideas or methods, whether it opens new research directions, transformative vs incremental.",
    "clarity": "Which paper has better CLARITY of presentation? Consider: quality of writing, logical structure, how well concepts are explained.",
}


class PairwiseFetchRequest(BaseModel):
    num_pairs_per_dim: int = 10
    dimensions: List[str] = DIMENSIONS


@router.post("/pairwise/fetch-and-run", dependencies=[Depends(verify_admin)])
async def pw_fetch_and_run(body: PairwiseFetchRequest):
    if _pw_state["fetching"] or _pw_state["running"]:
        return {"status": "already_running"}
    valid_dims = [d for d in body.dimensions if d in DIMENSIONS]
    if not valid_dims:
        return {"status": "error", "message": "Invalid dimensions"}
    asyncio.create_task(_pw_run(body.num_pairs_per_dim, valid_dims))
    return {"status": "started", "num_pairs_per_dim": body.num_pairs_per_dim, "dimensions": valid_dims}


@router.get("/pairwise/status")
async def pw_status():
    total = await db.scipost_pairwise.count_documents({})
    completed = await db.scipost_pairwise.count_documents({"ai_completed": True})
    failed = await db.scipost_pairwise.count_documents({"ai_failed": True})
    dim_counts = {}
    async for r in db.scipost_pairwise.aggregate([{"$group": {"_id": "$dimension", "count": {"$sum": 1}}}]):
        dim_counts[r["_id"]] = r["count"]
    return {
        "total_pairs": total, "ai_completed": completed, "ai_failed": failed,
        "ai_pending": total - completed - failed, "by_dimension": dim_counts,
        "fetching": _pw_state["fetching"], "running": _pw_state["running"],
        "progress": _pw_state["progress"],
    }


@router.post("/pairwise/stop", dependencies=[Depends(verify_admin)])
async def pw_stop():
    _pw_state["running"] = False
    _pw_state["fetching"] = False
    return {"status": "stopped"}


@router.post("/pairwise/reset", dependencies=[Depends(verify_admin)])
async def pw_reset():
    if _pw_state["running"] or _pw_state["fetching"]:
        return {"status": "error", "message": "Cannot reset while running"}
    r = await db.scipost_pairwise.delete_many({})
    return {"status": "ok", "deleted": r.deleted_count}


async def _pw_run(num_pairs_per_dim: int, dimensions: list):
    _pw_state["fetching"] = True
    _pw_state["running"] = True
    _pw_state["progress"] = {"phase": "scanning", "papers_found": 0, "pairs_done": 0, "target": num_pairs_per_dim * len(dimensions)}
    pairs_done = 0

    try:
        # Phase 1: Fetch papers with reports
        async with aiohttp.ClientSession() as session:
            submission_ids = await _fetch_scipost_submissions(session)
            random.shuffle(submission_ids)

            papers = []
            need = max(num_pairs_per_dim * 4, 30)
            for i in range(0, min(len(submission_ids), need * 2), 6):
                if len(papers) >= need:
                    break
                batch = submission_ids[i:i + 6]
                tasks = [_fetch_submission_details(session, sid) for sid in batch]
                results = await asyncio.gather(*tasks)
                for p in results:
                    if p and p.get("reports"):
                        papers.append(p)
                _pw_state["progress"]["papers_found"] = len(papers)
                await asyncio.sleep(0.5)

        if len(papers) < 2:
            logger.warning("SciPost pairwise: not enough papers")
            return

        _pw_state["progress"]["phase"] = "evaluating"
        _pw_state["fetching"] = False

        # Phase 2: For each dimension, create pairs and evaluate
        for dim in dimensions:
            if not _pw_state["running"]:
                break

            # Compute average score per paper for this dimension
            paper_scores = []
            for paper in papers:
                dim_ratings = []
                for rpt in paper.get("reports", []):
                    val = rpt.get(dim)
                    if val and isinstance(val, (int, float)):
                        dim_ratings.append(val)
                if dim_ratings:
                    avg = sum(dim_ratings) / len(dim_ratings)
                    paper_scores.append((paper, avg))

            if len(paper_scores) < 2:
                continue

            # Create pairs — each paper used at most once
            random.shuffle(paper_scores)
            dim_pairs = []
            for i in range(0, len(paper_scores) - 1, 2):
                if len(dim_pairs) >= num_pairs_per_dim:
                    break
                p1, s1 = paper_scores[i]
                p2, s2 = paper_scores[i + 1]
                if abs(s1 - s2) < 0.3:
                    continue  # skip near-ties
                dim_pairs.append((p1, s1, p2, s2))

            # Evaluate each pair with all 3 models
            task_text = DIMENSION_PW_TASKS.get(dim, f"Which paper is better on {dim}?")
            prompt_config = {
                "system_prompt": "You are a physics peer reviewer. Compare two papers on a specific dimension. You must pick exactly one winner. Respond with valid JSON only.",
                "user_prompt": (
                    f"Compare these two physics papers on their {dim.upper()}.\n\n"
                    "Paper 1: \"{paper1_title}\"\n{paper1_content}\n\n"
                    "Paper 2: \"{paper2_title}\"\n{paper2_content}\n\n"
                    f"{task_text}\n\n"
                    "You MUST pick exactly one winner. Respond with JSON only:\n"
                    "{{\"winner\": \"paper1\" or \"paper2\", \"reasoning\": \"brief explanation\"}}"
                ),
            }

            for p1, s1, p2, s2 in dim_pairs:
                if not _pw_state["running"]:
                    break

                human_winner = "paper1" if s1 > s2 else "paper2"

                # Run all 3 models in parallel with random swap
                ai_results = {}
                model_tasks = []
                for mi in TOURNAMENT_MODELS:
                    swapped = random.random() < 0.5
                    model_tasks.append((mi, swapped))

                coros = []
                for mi, swapped in model_tasks:
                    if swapped:
                        a, b = p2, p1
                    else:
                        a, b = p1, p2
                    coros.append(compare_papers(
                        {"title": a.get("title", ""), "abstract": a.get("abstract", "")},
                        {"title": b.get("title", ""), "abstract": b.get("abstract", "")},
                        prompt_config, abstract_only=True, model_override=mi,
                    ))
                responses = await asyncio.gather(*coros, return_exceptions=True)

                for (mi, swapped), resp in zip(model_tasks, responses):
                    mk = f"{mi['provider']}:{mi['model']}"
                    if isinstance(resp, Exception):
                        ai_results[mk] = {"winner": None, "error": str(resp)[:100]}
                    else:
                        w = resp.get("winner", "paper1")
                        if swapped:
                            w = "paper2" if w == "paper1" else "paper1"
                        ai_results[mk] = {"winner": w, "reasoning": resp.get("reasoning", "")}

                # Majority vote
                votes = [v["winner"] for v in ai_results.values() if v.get("winner")]
                majority = None
                if votes:
                    c = Counter(votes)
                    best, n = c.most_common(1)[0]
                    if n > len(votes) / 2:
                        majority = best

                doc = {
                    "id": str(uuid.uuid4()),
                    "source": "scipost", "dimension": dim,
                    "paper1": {"submission_id": p1.get("submission_id", ""), "title": p1.get("title", ""), "abstract": p1.get("abstract", "")[:500], "human_score": round(s1, 2)},
                    "paper2": {"submission_id": p2.get("submission_id", ""), "title": p2.get("title", ""), "abstract": p2.get("abstract", "")[:500], "human_score": round(s2, 2)},
                    "human_winner": human_winner, "score_gap": round(abs(s1 - s2), 2),
                    "ai_results": ai_results, "ai_majority": majority,
                    "ai_completed": True, "ai_failed": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.scipost_pairwise.insert_one(doc)
                pairs_done += 1
                _pw_state["progress"]["pairs_done"] = pairs_done
                agrees = sum(1 for v in ai_results.values() if v.get("winner") == human_winner)
                logger.info(f"SciPost pw [{pairs_done}] {dim}: {agrees}/3 agree | gap={abs(s1-s2):.1f}")

        logger.info(f"SciPost pairwise complete: {pairs_done} pairs")
    except Exception as e:
        logger.error(f"SciPost pairwise error: {e}")
    finally:
        _pw_state["fetching"] = False
        _pw_state["running"] = False


@router.get("/pairwise/results")
async def pw_results():
    pairs = await db.scipost_pairwise.find({"ai_completed": True}, {"_id": 0}).to_list(10000)
    if not pairs:
        return {"status": "no_data", "total": 0}

    total = len(pairs)
    dim_stats = defaultdict(lambda: {
        "maj_agree": 0, "maj_total": 0,
        "models": defaultdict(lambda: {"agree": 0, "total": 0}),
        "gaps": defaultdict(lambda: {"agree": 0, "total": 0}),
    })

    for p in pairs:
        dim = p.get("dimension")
        hw = p.get("human_winner")
        for mk, res in p.get("ai_results", {}).items():
            if res.get("winner"):
                dim_stats[dim]["models"][mk]["total"] += 1
                if res["winner"] == hw:
                    dim_stats[dim]["models"][mk]["agree"] += 1
        if p.get("ai_majority"):
            dim_stats[dim]["maj_total"] += 1
            if p["ai_majority"] == hw:
                dim_stats[dim]["maj_agree"] += 1
        gap = p.get("score_gap", 0)
        gap_label = "small" if gap <= 1 else "medium" if gap <= 2 else "large"
        if p.get("ai_majority"):
            dim_stats[dim]["gaps"][gap_label]["total"] += 1
            if p["ai_majority"] == hw:
                dim_stats[dim]["gaps"][gap_label]["agree"] += 1

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    dim_results = {}
    for dim, s in dim_stats.items():
        dim_results[dim] = {
            "majority": {"agree": s["maj_agree"], "total": s["maj_total"], "rate": _rate(s["maj_agree"], s["maj_total"])},
            "by_model": {mk: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for mk, v in s["models"].items()},
            "by_gap": {g: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for g, v in sorted(s["gaps"].items())},
        }

    overall_agree = sum(s["maj_agree"] for s in dim_stats.values())
    overall_total = sum(s["maj_total"] for s in dim_stats.values())

    # Inter-model agreement
    all_models = set()
    for p in pairs:
        all_models.update(p.get("ai_results", {}).keys())
    models = sorted(all_models)
    inter_model = defaultdict(lambda: {"agree": 0, "total": 0})
    for p in pairs:
        ar = p.get("ai_results", {})
        for i, m1 in enumerate(models):
            for m2 in models[i + 1:]:
                w1, w2 = ar.get(m1, {}).get("winner"), ar.get(m2, {}).get("winner")
                if w1 and w2:
                    inter_model[f"{m1} vs {m2}"]["total"] += 1
                    if w1 == w2:
                        inter_model[f"{m1} vs {m2}"]["agree"] += 1

    samples = [{
        "dimension": p.get("dimension"),
        "paper1_title": p["paper1"]["title"][:55],
        "paper2_title": p["paper2"]["title"][:55],
        "human_winner": p.get("human_winner"),
        "human_score1": p["paper1"]["human_score"],
        "human_score2": p["paper2"]["human_score"],
        "ai_majority": p.get("ai_majority"),
        "majority_agree": p.get("ai_majority") == p.get("human_winner") if p.get("ai_majority") else None,
        "models_agree": sum(1 for v in p.get("ai_results", {}).values() if v.get("winner") == p["human_winner"]),
        "models_total": sum(1 for v in p.get("ai_results", {}).values() if v.get("winner")),
        "score_gap": p.get("score_gap"),
    } for p in pairs[:80]]

    return {
        "status": "ok",
        "total_pairs": total,
        "overall_majority": {"agree": overall_agree, "total": overall_total, "rate": _rate(overall_agree, overall_total)},
        "by_dimension": dim_results,
        "inter_model": {k: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for k, v in inter_model.items()},
        "samples": samples,
    }
