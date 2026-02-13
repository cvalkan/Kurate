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
from services.llm import call_llm

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
    
    # Find all referee reports with ratings
    # Reports are in <div class="report" id="report_N">...</div>
    report_pattern = r'<div class="report" id="report_(\d+)">(.*?)</div>\s*</div>\s*</div>\s*</div>'
    report_matches = re.findall(report_pattern, html, re.DOTALL)
    
    for report_num, block in report_matches:
        report = {"report_num": int(report_num)}
        
        # Extract referee name
        referee_match = re.search(r'Report #\d+ by\s*(.*?)\s*(?:\(|on\s+\d)', block)
        if referee_match:
            referee = referee_match.group(1).strip()
            report["referee"] = referee if referee and "Anonymous" not in referee else f"Anonymous_{report_num}"
        else:
            report["referee"] = f"Referee_{report_num}"
        
        # Extract ratings from the ratings div
        ratings_match = re.search(r'<div class="ratings">(.*?)</div>', block, re.DOTALL)
        if ratings_match:
            ratings_html = ratings_match.group(1)
            for dim in DIMENSIONS + ["formatting", "grammar"]:
                dim_match = re.search(rf'{dim}:\s*(\w+)', ratings_html, re.I)
                if dim_match:
                    rating_text = dim_match.group(1).lower()
                    report[dim] = RATING_SCALE.get(rating_text, 0)
        
        # Only include reports with at least some ratings
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
    url = f"https://scipost.org/submissions/{submission_id}/"
    html = await _fetch_url(session, url)
    if not html:
        return None
    
    data = _parse_scipost_submission(html, submission_id)
    
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
        dim_counts[dim] = await db.scipost_comparisons.count_documents({f"dimension": dim, "ai_completed": True})
    
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
    
    # Sample comparisons
    samples = [{
        "paper_title": c.get("paper_title", "")[:60],
        "dimension": c.get("dimension"),
        "human_rating": c.get("human_rating"),
        "human_label": c.get("human_rating_label"),
        "ai_consensus": c.get("ai_consensus_rating"),
        "ai_ratings": {k: v.get("rating") for k, v in c.get("ai_results", {}).items()},
        "field": c.get("field"),
    } for c in comparisons[:50]]
    
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
    }


# ─── Reset ─────────────────────────────────────────────────────────────────────

@router.post("/reset", dependencies=[Depends(verify_admin)])
async def reset():
    if _state["running"] or _state["fetching"]:
        return {"status": "error", "message": "Cannot reset while running"}
    r = await db.scipost_comparisons.delete_many({})
    return {"status": "ok", "deleted": r.deleted_count}
