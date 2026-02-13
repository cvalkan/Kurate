"""
Pairwise Expert Comparison — Unbiased human vs AI agreement testing.

Fetches real reviewer pairs from Qeios (1 pair per reviewer, no ties),
runs AI on the exact same pairs, and measures agreement rate.
"""
import asyncio
import uuid
import re
import random
import time as _time
import requests
import aiohttp
from datetime import datetime, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger, DEFAULT_EVALUATION_PROMPT, TOURNAMENT_MODELS
from core.auth import verify_admin
from services.llm import compare_papers

router = APIRouter(prefix="/api/pairwise")

_state = {"fetching": False, "tournament_running": False, "progress": {}}

CROSSREF_HEADERS = {"User-Agent": "PaperSumo/1.0 (mailto:test@example.com)"}
# Parallelism settings
PARALLEL_FETCHES = 5  # Number of pairs to fetch data for simultaneously
PARALLEL_EVALS = 3    # Number of pairs to evaluate with AI simultaneously


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _extract_qeios_page(qeios_id: str) -> dict:
    """Extract title, abstract, full text from a Qeios page."""
    r = requests.get(f"https://www.qeios.com/read/{qeios_id}", timeout=15)
    html = r.text
    result = {}

    # Find the publication JSON blob
    pub_idx = html.find('publication = {')
    if pub_idx < 0:
        return result
    pub_chunk = html[pub_idx:]

    # domain_name
    idx = pub_chunk.find('"domain_name"')
    if idx >= 0:
        m = re.search(r':\s*"([^"]+)"', pub_chunk[idx + 13:idx + 100])
        if m:
            result["domain"] = m.group(1)

    # title — from the publication object
    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)+)"', pub_chunk[:500])
    if m:
        raw = m.group(1).replace('\\"', '"').replace('\\/', '/')
        result["title"] = re.sub(r'<[^>]+>', '', raw).strip()

    # abstract
    idx = pub_chunk.find('"abstract"')
    if idx >= 0:
        m = re.search(r':\s*"((?:[^"\\]|\\.)+)"', pub_chunk[idx + 10:idx + 10000])
        if m:
            raw = m.group(1).replace('\\"', '"').replace('\\/', '/')
            result["abstract"] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw)).strip()

    # body (full text)
    idx = pub_chunk.find('"body":')
    if idx >= 0:
        start = pub_chunk.find('"', idx + 7)
        if start >= 0:
            start += 1
            pos = start
            while pos < len(pub_chunk) and pos < start + 200000:
                if pub_chunk[pos] == '"' and pub_chunk[pos - 1] != '\\':
                    break
                pos += 1
            raw = pub_chunk[start:pos].replace('\\"', '"').replace('\\/', '/').replace('\\n', ' ')
            text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw)).strip()
            if len(text) > 500:
                result["full_text"] = text

    return result


def _get_review_rating(review_qeios_id: str) -> Optional[float]:
    r = requests.get(f"https://www.qeios.com/read/{review_qeios_id}", timeout=10)
    m = re.search(r'"borne_rating"\s*:\s*(\d+(?:\.\d+)?)', r.text)
    return float(m.group(1)) if m else None


def _parse_qeios_html(html: str) -> dict:
    """Parse Qeios HTML to extract paper data."""
    result = {}
    pub_idx = html.find('publication = {')
    if pub_idx < 0:
        return result
    pub_chunk = html[pub_idx:]

    # domain_name
    idx = pub_chunk.find('"domain_name"')
    if idx >= 0:
        m = re.search(r':\s*"([^"]+)"', pub_chunk[idx + 13:idx + 100])
        if m:
            result["domain"] = m.group(1)

    # title
    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)+)"', pub_chunk[:500])
    if m:
        raw = m.group(1).replace('\\"', '"').replace('\\/', '/')
        result["title"] = re.sub(r'<[^>]+>', '', raw).strip()

    # abstract
    idx = pub_chunk.find('"abstract"')
    if idx >= 0:
        m = re.search(r':\s*"((?:[^"\\]|\\.)+)"', pub_chunk[idx + 10:idx + 10000])
        if m:
            raw = m.group(1).replace('\\"', '"').replace('\\/', '/')
            result["abstract"] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw)).strip()

    # body (full text)
    idx = pub_chunk.find('"body":')
    if idx >= 0:
        start = pub_chunk.find('"', idx + 7)
        if start >= 0:
            start += 1
            pos = start
            while pos < len(pub_chunk) and pos < start + 200000:
                if pub_chunk[pos] == '"' and pub_chunk[pos - 1] != '\\':
                    break
                pos += 1
            raw = pub_chunk[start:pos].replace('\\"', '"').replace('\\/', '/').replace('\\n', ' ')
            text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw)).strip()
            if len(text) > 500:
                result["full_text"] = text

    return result


def _parse_rating_html(html: str) -> Optional[float]:
    """Parse rating from review HTML."""
    m = re.search(r'"borne_rating"\s*:\s*(\d+(?:\.\d+)?)', html)
    return float(m.group(1)) if m else None


async def _fetch_url_async(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch URL asynchronously."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            return await resp.text()
    except Exception:
        return ""


async def _fetch_pair_data_async(session: aiohttp.ClientSession, reviewer: str, papers: list) -> Optional[dict]:
    """Fetch all data for a single pair asynchronously."""
    try:
        # Pick 2 random papers
        pair_papers = random.sample(papers, min(2, len(papers)))
        if len(pair_papers) < 2:
            return None

        # Fetch ratings for both reviews in parallel
        rating_urls = [f"https://www.qeios.com/read/{doi.split('/')[-1].upper()}" for _, doi in pair_papers]
        rating_htmls = await asyncio.gather(*[_fetch_url_async(session, url) for url in rating_urls])
        
        ratings = []
        for (paper_doi, review_doi), html in zip(pair_papers, rating_htmls):
            rating = _parse_rating_html(html)
            if rating is not None:
                ratings.append((paper_doi, review_doi, rating))

        if len(ratings) < 2 or ratings[0][2] == ratings[1][2]:
            return None  # Not enough or tie

        human_winner = "paper1" if ratings[0][2] > ratings[1][2] else "paper2"

        # Fetch paper data in parallel
        paper_urls = [f"https://www.qeios.com/read/{doi.split('/')[-1].upper()}" for doi, _, _ in ratings]
        paper_htmls = await asyncio.gather(*[_fetch_url_async(session, url) for url in paper_urls])

        paper_data = []
        for (paper_doi, review_doi, rating), html in zip(ratings, paper_htmls):
            page = _parse_qeios_html(html)
            if not page.get("title") or not page.get("abstract"):
                return None
            qeios_id = paper_doi.split("/")[-1].upper()
            paper_data.append({
                "doi": paper_doi, "qeios_id": qeios_id,
                "title": page.get("title", ""), "abstract": page.get("abstract", ""),
                "full_text": page.get("full_text"), "domain": page.get("domain", "Unknown"),
                "rating": rating,
            })

        if len(paper_data) < 2:
            return None

        return {
            "reviewer": reviewer,
            "domain": paper_data[0]["domain"],
            "paper1": paper_data[0],
            "paper2": paper_data[1],
            "human_winner": human_winner,
            "human_score1": ratings[0][2],
            "human_score2": ratings[1][2],
        }
    except Exception as e:
        logger.debug(f"Fetch error for {reviewer}: {e}")
        return None


async def _evaluate_pair_async(pair_data: dict, prompt_config: dict) -> dict:
    """Run AI evaluation on a single pair with all 3 models."""
    p1_dict = {"title": pair_data["paper1"]["title"], "abstract": pair_data["paper1"]["abstract"], "full_text": pair_data["paper1"].get("full_text")}
    p2_dict = {"title": pair_data["paper2"]["title"], "abstract": pair_data["paper2"]["abstract"], "full_text": pair_data["paper2"].get("full_text")}
    abstract_only = not (pair_data["paper1"].get("full_text") and pair_data["paper2"].get("full_text"))

    # Run all 3 models in parallel with random presentation order
    model_tasks = []
    for model_info in TOURNAMENT_MODELS:
        if random.random() < 0.5:
            model_tasks.append((model_info, p2_dict, p1_dict, True))
        else:
            model_tasks.append((model_info, p1_dict, p2_dict, False))

    coros = [
        compare_papers(pa, pb, prompt_config, abstract_only=abstract_only, model_override=mi)
        for mi, pa, pb, _ in model_tasks
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    ai_results = {}
    for (mi, _, _, swapped), result in zip(model_tasks, results):
        mk = f"{mi['provider']}:{mi['model']}"
        if isinstance(result, Exception):
            ai_results[mk] = {"winner": None, "error": str(result)[:100]}
        else:
            winner_key = result.get("winner", "paper1")
            if swapped:
                ai_winner = "paper2" if winner_key == "paper1" else "paper1"
            else:
                ai_winner = winner_key
            ai_results[mk] = {"winner": ai_winner, "reasoning": result.get("reasoning", "")}

    # Majority vote
    votes = [v["winner"] for v in ai_results.values() if v.get("winner")]
    majority = None
    if votes:
        c = Counter(votes)
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            majority = best

    return {
        **pair_data,
        "id": str(uuid.uuid4()),
        "source": "qeios",
        "ai_results": ai_results,
        "ai_majority": majority,
        "ai_completed": True,
        "ai_failed": False,
        "used_full_text": not abstract_only,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    total = await db.pairwise_comparisons.count_documents({})
    with_ai = await db.pairwise_comparisons.count_documents({"ai_completed": True})
    failed = await db.pairwise_comparisons.count_documents({"ai_failed": True})

    domains = {}
    pipeline = [{"$group": {"_id": "$domain", "count": {"$sum": 1}}}]
    async for r in db.pairwise_comparisons.aggregate(pipeline):
        domains[r["_id"] or "Unknown"] = r["count"]

    return {
        "total_pairs": total,
        "ai_completed": with_ai,
        "ai_failed": failed,
        "ai_pending": total - with_ai - failed,
        "domains": domains,
        "fetching": _state["fetching"],
        "tournament_running": _state["tournament_running"],
        "progress": _state["progress"],
    }


# ─── Fetch Pairs ───────────────────────────────────────────────────────────────

class FetchPairsRequest(BaseModel):
    source: str = "qeios"
    num_pairs: int = 50


@router.post("/fetch-pairs", dependencies=[Depends(verify_admin)])
async def fetch_pairs(body: FetchPairsRequest):
    if _state["fetching"]:
        return {"status": "already_fetching"}

    if body.source != "qeios":
        return {"status": "error", "message": f"Unknown source: {body.source}"}

    asyncio.create_task(_fetch_qeios_pairs(body.num_pairs))
    return {"status": "started", "num_pairs": body.num_pairs}


async def _fetch_qeios_pairs(num_pairs: int):
    _state["fetching"] = True
    _state["progress"] = {"phase": "scanning", "found": 0, "target": num_pairs}

    try:
        # Phase 1: Build reviewer→paper graph from Crossref
        logger.info(f"Pairwise fetch: scanning Crossref for Qeios reviews...")
        reviewer_reviews = defaultdict(list)  # reviewer -> [(paper_doi, review_doi, paper_doi)]
        total = 0
        cursor = "*"

        for page in range(20):
            try:
                r = requests.get(
                    f"https://api.crossref.org/works?filter=type:peer-review&query.publisher-name=Qeios&rows=1000&cursor={cursor}",
                    headers=CROSSREF_HEADERS, timeout=20,
                )
                d = r.json()
                items = d.get("message", {}).get("items", [])
                cursor = d.get("message", {}).get("next-cursor", "")
                total += len(items)
                for item in items:
                    paper_doi = None
                    for ref in item.get("relation", {}).get("is-review-of", []):
                        if ref.get("id-type") == "doi":
                            paper_doi = ref["id"]
                    reviewer = None
                    for a in item.get("author", []):
                        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                        if name:
                            reviewer = name
                            break
                    review_doi = item.get("DOI", "")
                    if paper_doi and reviewer and review_doi:
                        reviewer_reviews[reviewer].append((paper_doi, review_doi))
                if not items or not cursor:
                    break
                _time.sleep(0.8)
            except Exception:
                break

        # Filter to reviewers with ≥2 papers
        eligible = {r: ps for r, ps in reviewer_reviews.items() if len(ps) >= 2}
        logger.info(f"Pairwise fetch: {total} reviews, {len(eligible)} eligible reviewers")
        _state["progress"]["phase"] = "fetching ratings"

        # Phase 2: For each reviewer, fetch ratings for 2 papers, derive winner
        # Already used reviewers from DB
        existing_reviewers = set()
        async for doc in db.pairwise_comparisons.find({}, {"_id": 0, "reviewer": 1}):
            existing_reviewers.add(doc["reviewer"])

        reviewers = list(eligible.items())
        random.shuffle(reviewers)
        pairs_created = 0

        for reviewer, papers in reviewers:
            if pairs_created >= num_pairs:
                break
            if reviewer in existing_reviewers:
                continue

            # Pick 2 random papers from this reviewer
            random.shuffle(papers)
            pair_papers = papers[:2]

            try:
                # Fetch ratings
                ratings = []
                for paper_doi, review_doi in pair_papers:
                    rev_qid = review_doi.split("/")[-1].upper()
                    rating = _get_review_rating(rev_qid)
                    if rating is not None:
                        ratings.append((paper_doi, review_doi, rating))
                    _time.sleep(0.3)

                if len(ratings) < 2:
                    continue

                # Check for tie
                if ratings[0][2] == ratings[1][2]:
                    continue  # Skip ties

                # Determine winner
                if ratings[0][2] > ratings[1][2]:
                    human_winner = "paper1"
                else:
                    human_winner = "paper2"

                # Fetch full paper data
                paper_data = []
                for paper_doi, review_doi, rating in ratings:
                    qeios_id = paper_doi.split("/")[-1].upper()
                    page = _extract_qeios_page(qeios_id)
                    if not page.get("title") or not page.get("abstract"):
                        break
                    paper_data.append({
                        "doi": paper_doi,
                        "qeios_id": qeios_id,
                        "title": page.get("title", ""),
                        "abstract": page.get("abstract", ""),
                        "full_text": page.get("full_text"),
                        "domain": page.get("domain", "Unknown"),
                        "rating": rating,
                    })
                    _time.sleep(0.4)

                if len(paper_data) < 2:
                    continue

                # Use the domain of the first paper
                domain = paper_data[0]["domain"]

                doc = {
                    "id": str(uuid.uuid4()),
                    "source": "qeios",
                    "reviewer": reviewer,
                    "domain": domain,
                    "paper1": paper_data[0],
                    "paper2": paper_data[1],
                    "human_winner": human_winner,
                    "human_score1": ratings[0][2],
                    "human_score2": ratings[1][2],
                    "ai_results": {},  # model_key -> {winner, reasoning}
                    "ai_completed": False,
                    "ai_failed": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

                await db.pairwise_comparisons.update_one(
                    {"reviewer": reviewer, "source": "qeios"},
                    {"$set": doc}, upsert=True,
                )
                pairs_created += 1
                existing_reviewers.add(reviewer)
                _state["progress"]["found"] = pairs_created

                has_ft = "FT" if paper_data[0].get("full_text") and paper_data[1].get("full_text") else "AB"
                logger.info(f"Pairwise [{pairs_created}/{num_pairs}] {has_ft} | {domain} | {reviewer[:20]}")

            except Exception as e:
                logger.warning(f"Pairwise fetch error for {reviewer}: {e}")
                continue

        logger.info(f"Pairwise fetch complete: {pairs_created} pairs created")
    except Exception as e:
        logger.error(f"Pairwise fetch error: {e}")
    finally:
        _state["fetching"] = False
        _state["progress"] = {"phase": "done", "found": pairs_created if 'pairs_created' in dir() else 0}


# ─── Fetch & Run (combined) ────────────────────────────────────────────────────

class FetchAndRunRequest(BaseModel):
    source: str = "qeios"
    num_pairs: int = 50


@router.post("/fetch-and-run", dependencies=[Depends(verify_admin)])
async def fetch_and_run(body: FetchAndRunRequest):
    """Fetch pairs AND immediately run all 3 models on each."""
    if _state["fetching"] or _state["tournament_running"]:
        return {"status": "already_running"}
    if body.source != "qeios":
        return {"status": "error", "message": f"Unknown source: {body.source}"}

    asyncio.create_task(_fetch_and_run_qeios(body.num_pairs))
    return {"status": "started", "num_pairs": body.num_pairs}


async def _fetch_and_run_qeios(num_pairs: int):
    _state["fetching"] = True
    _state["tournament_running"] = True
    _state["progress"] = {"phase": "scanning", "pairs_fetched": 0, "pairs_evaluated": 0, "target": num_pairs}

    try:
        # Phase 1: Build reviewer graph from Crossref
        logger.info("Pairwise fetch+run: scanning Crossref...")
        reviewer_reviews = defaultdict(list)
        total = 0
        cursor = "*"

        for page in range(20):
            try:
                r = requests.get(
                    f"https://api.crossref.org/works?filter=type:peer-review&query.publisher-name=Qeios&rows=1000&cursor={cursor}",
                    headers=CROSSREF_HEADERS, timeout=20,
                )
                d = r.json()
                items = d.get("message", {}).get("items", [])
                cursor = d.get("message", {}).get("next-cursor", "")
                total += len(items)
                for item in items:
                    paper_doi = None
                    for ref in item.get("relation", {}).get("is-review-of", []):
                        if ref.get("id-type") == "doi":
                            paper_doi = ref["id"]
                    reviewer = None
                    for a in item.get("author", []):
                        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                        if name:
                            reviewer = name
                            break
                    review_doi = item.get("DOI", "")
                    if paper_doi and reviewer and review_doi:
                        reviewer_reviews[reviewer].append((paper_doi, review_doi))
                if not items or not cursor:
                    break
                _time.sleep(0.8)
            except Exception:
                break

        eligible = {r: ps for r, ps in reviewer_reviews.items() if len(ps) >= 2}
        logger.info(f"Pairwise: {total} reviews, {len(eligible)} eligible reviewers")

        # Already used reviewers
        existing_reviewers = set()
        async for doc in db.pairwise_comparisons.find({}, {"_id": 0, "reviewer": 1}):
            existing_reviewers.add(doc["reviewer"])

        _state["progress"]["phase"] = "fetching & evaluating"
        reviewers = list(eligible.items())
        random.shuffle(reviewers)
        pairs_done = 0
        prompt_config = DEFAULT_EVALUATION_PROMPT

        for reviewer, papers in reviewers:
            if pairs_done >= num_pairs:
                break
            if not _state["tournament_running"]:
                break
            if reviewer in existing_reviewers:
                continue

            random.shuffle(papers)
            pair_papers = papers[:2]

            try:
                # Fetch ratings
                ratings = []
                for paper_doi, review_doi in pair_papers:
                    rev_qid = review_doi.split("/")[-1].upper()
                    rating = _get_review_rating(rev_qid)
                    if rating is not None:
                        ratings.append((paper_doi, review_doi, rating))
                    _time.sleep(0.3)

                if len(ratings) < 2 or ratings[0][2] == ratings[1][2]:
                    continue  # Skip if not enough or tie

                human_winner = "paper1" if ratings[0][2] > ratings[1][2] else "paper2"

                # Fetch full paper data
                paper_data = []
                for paper_doi, review_doi, rating in ratings:
                    qeios_id = paper_doi.split("/")[-1].upper()
                    page = _extract_qeios_page(qeios_id)
                    if not page.get("title") or not page.get("abstract"):
                        break
                    paper_data.append({
                        "doi": paper_doi, "qeios_id": qeios_id,
                        "title": page.get("title", ""), "abstract": page.get("abstract", ""),
                        "full_text": page.get("full_text"), "domain": page.get("domain", "Unknown"),
                        "rating": rating,
                    })
                    _time.sleep(0.3)

                if len(paper_data) < 2:
                    continue

                domain = paper_data[0]["domain"]
                _state["progress"]["pairs_fetched"] = pairs_done + 1

                # Run all 3 models on this pair
                p1_dict = {"title": paper_data[0]["title"], "abstract": paper_data[0]["abstract"], "full_text": paper_data[0].get("full_text")}
                p2_dict = {"title": paper_data[1]["title"], "abstract": paper_data[1]["abstract"], "full_text": paper_data[1].get("full_text")}
                abstract_only = not (paper_data[0].get("full_text") and paper_data[1].get("full_text"))

                ai_results = {}
                # Run all 3 models in parallel
                model_tasks = []
                for model_info in TOURNAMENT_MODELS:
                    # Random presentation order per model
                    if random.random() < 0.5:
                        model_tasks.append((model_info, p2_dict, p1_dict, True))
                    else:
                        model_tasks.append((model_info, p1_dict, p2_dict, False))

                coros = [
                    compare_papers(pa, pb, prompt_config, abstract_only=abstract_only, model_override=mi)
                    for mi, pa, pb, _ in model_tasks
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)

                for (mi, _, _, swapped), result in zip(model_tasks, results):
                    mk = f"{mi['provider']}:{mi['model']}"
                    if isinstance(result, Exception):
                        ai_results[mk] = {"winner": None, "error": str(result)[:100]}
                    else:
                        winner_key = result.get("winner", "paper1")
                        if swapped:
                            ai_winner = "paper2" if winner_key == "paper1" else "paper1"
                        else:
                            ai_winner = winner_key
                        ai_results[mk] = {"winner": ai_winner, "reasoning": result.get("reasoning", "")}

                # Majority vote
                votes = [v["winner"] for v in ai_results.values() if v.get("winner")]
                majority = None
                if votes:
                    c = Counter(votes)
                    best, n = c.most_common(1)[0]
                    if n > len(votes) / 2:
                        majority = best

                doc = {
                    "id": str(uuid.uuid4()), "source": "qeios",
                    "reviewer": reviewer, "domain": domain,
                    "paper1": paper_data[0], "paper2": paper_data[1],
                    "human_winner": human_winner,
                    "human_score1": ratings[0][2], "human_score2": ratings[1][2],
                    "ai_results": ai_results,
                    "ai_majority": majority,
                    "ai_completed": True, "ai_failed": False,
                    "used_full_text": not abstract_only,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

                await db.pairwise_comparisons.insert_one(doc)
                pairs_done += 1
                existing_reviewers.add(reviewer)
                _state["progress"]["pairs_evaluated"] = pairs_done

                agrees = sum(1 for v in ai_results.values() if v.get("winner") == human_winner)
                ft_tag = "FT" if not abstract_only else "AB"
                logger.info(f"Pairwise [{pairs_done}/{num_pairs}] {ft_tag} | {domain} | {agrees}/3 agree | {reviewer[:20]}")

            except Exception as e:
                logger.warning(f"Pairwise error for {reviewer}: {e}")
                continue

        logger.info(f"Pairwise fetch+run complete: {pairs_done} pairs")
    except Exception as e:
        logger.error(f"Pairwise fetch+run error: {e}")
    finally:
        _state["fetching"] = False
        _state["tournament_running"] = False


# ─── Run pending (for pairs fetched without AI) ──────────────────────────────

class RunTournamentRequest(BaseModel):
    parallel: int = 10


@router.post("/run-tournament", dependencies=[Depends(verify_admin)])
async def run_tournament(body: RunTournamentRequest):
    if _state["tournament_running"]:
        return {"status": "already_running"}

    pending = await db.pairwise_comparisons.count_documents({"ai_completed": False, "ai_failed": {"$ne": True}})
    if pending == 0:
        return {"status": "error", "message": "No pending pairs to evaluate"}

    asyncio.create_task(_run_pairwise_tournament(min(max(body.parallel, 1), 30)))
    return {"status": "started", "pending_pairs": pending}


@router.post("/stop-tournament", dependencies=[Depends(verify_admin)])
async def stop_tournament():
    _state["tournament_running"] = False
    _state["fetching"] = False
    return {"status": "stopped"}


async def _run_pairwise_tournament(parallel: int):
    _state["tournament_running"] = True
    _state["progress"] = {"phase": "running", "completed": 0, "total": 0}

    try:
        pending = await db.pairwise_comparisons.find(
            {"ai_completed": False, "ai_failed": {"$ne": True}},
            {"_id": 0},
        ).to_list(10000)

        _state["progress"]["total"] = len(pending)
        prompt_config = DEFAULT_EVALUATION_PROMPT
        completed = 0

        for i in range(0, len(pending), parallel):
            if not _state["tournament_running"]:
                logger.info("Pairwise tournament stopped by user")
                break

            batch = pending[i:i + parallel]

            # Build paper dicts for compare_papers
            tasks = []
            for pair in batch:
                p1 = pair["paper1"]
                p2 = pair["paper2"]
                # Randomly swap presentation order
                if random.random() < 0.5:
                    tasks.append((pair, p2, p1, True))  # swapped
                else:
                    tasks.append((pair, p1, p2, False))

            coros = [
                compare_papers(
                    {"title": p1["title"], "abstract": p1["abstract"], "full_text": p1.get("full_text")},
                    {"title": p2["title"], "abstract": p2["abstract"], "full_text": p2.get("full_text")},
                    prompt_config,
                    abstract_only=not (p1.get("full_text") and p2.get("full_text")),
                )
                for _, p1, p2, _ in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for (pair, p1, p2, swapped), result in zip(tasks, results):
                update = {}
                if isinstance(result, Exception):
                    update = {"ai_failed": True, "ai_error": str(result)[:200]}
                else:
                    winner_key = result.get("winner", "paper1")
                    # Unswap if needed
                    if swapped:
                        ai_winner = "paper2" if winner_key == "paper1" else "paper1"
                    else:
                        ai_winner = winner_key

                    update = {
                        "ai_completed": True,
                        "ai_failed": False,
                        "ai_winner": ai_winner,
                        "ai_reasoning": result.get("reasoning", ""),
                        "ai_model": result.get("model_used", {}),
                        "used_full_text": bool(p1.get("full_text") and p2.get("full_text")),
                    }
                    completed += 1

                await db.pairwise_comparisons.update_one(
                    {"id": pair["id"]}, {"$set": update}
                )
                _state["progress"]["completed"] = completed

            await asyncio.sleep(0.2)

        logger.info(f"Pairwise tournament: {completed}/{len(pending)} completed")
    except Exception as e:
        logger.error(f"Pairwise tournament error: {e}")
    finally:
        _state["tournament_running"] = False


# ─── Results ───────────────────────────────────────────────────────────────────

@router.get("/results")
async def get_results():
    pairs = await db.pairwise_comparisons.find(
        {"ai_completed": True},
        {"_id": 0},
    ).to_list(10000)

    if not pairs:
        return {"status": "no_data", "total": 0}

    total = len(pairs)

    # Per-model agreement
    model_stats = defaultdict(lambda: {"agree": 0, "total": 0})
    for p in pairs:
        for mk, res in p.get("ai_results", {}).items():
            if res.get("winner"):
                model_stats[mk]["total"] += 1
                if res["winner"] == p["human_winner"]:
                    model_stats[mk]["agree"] += 1

    model_results = {
        m: {"agree": s["agree"], "total": s["total"],
            "rate": round(s["agree"] / max(s["total"], 1) * 100, 1)}
        for m, s in sorted(model_stats.items(), key=lambda x: -x[1]["total"])
    }

    # Majority vote agreement
    maj_agree = sum(1 for p in pairs if p.get("ai_majority") == p["human_winner"])
    maj_total = sum(1 for p in pairs if p.get("ai_majority"))

    # By domain (using majority vote)
    domain_stats = defaultdict(lambda: {"agree": 0, "total": 0})
    for p in pairs:
        d = p.get("domain") or "Unknown"
        if p.get("ai_majority"):
            domain_stats[d]["total"] += 1
            if p["ai_majority"] == p["human_winner"]:
                domain_stats[d]["agree"] += 1

    domain_results = {
        d: {"agree": s["agree"], "total": s["total"],
            "rate": round(s["agree"] / max(s["total"], 1) * 100, 1)}
        for d, s in sorted(domain_stats.items(), key=lambda x: -x[1]["total"])
    }

    # By score gap
    gap_stats = defaultdict(lambda: {"agree": 0, "total": 0})
    for p in pairs:
        if not p.get("ai_majority"):
            continue
        gap = abs(p["human_score1"] - p["human_score2"])
        gap_label = f"{gap:.0f}" if gap == int(gap) else f"{gap:.1f}"
        gap_stats[gap_label]["total"] += 1
        if p["ai_majority"] == p["human_winner"]:
            gap_stats[gap_label]["agree"] += 1

    gap_results = {
        g: {"agree": s["agree"], "total": s["total"],
            "rate": round(s["agree"] / max(s["total"], 1) * 100, 1)}
        for g, s in sorted(gap_stats.items(), key=lambda x: float(x[0]))
    }

    # Full text vs abstract
    ft_pairs = [p for p in pairs if p.get("used_full_text") and p.get("ai_majority")]
    ab_pairs = [p for p in pairs if not p.get("used_full_text") and p.get("ai_majority")]
    ft_agree = sum(1 for p in ft_pairs if p["ai_majority"] == p["human_winner"])
    ab_agree = sum(1 for p in ab_pairs if p["ai_majority"] == p["human_winner"])

    # Inter-model agreement
    inter_model = defaultdict(lambda: {"agree": 0, "total": 0})
    models = sorted(model_stats.keys())
    for p in pairs:
        ar = p.get("ai_results", {})
        for i, m1 in enumerate(models):
            for m2 in models[i + 1:]:
                w1 = ar.get(m1, {}).get("winner")
                w2 = ar.get(m2, {}).get("winner")
                if w1 and w2:
                    key = f"{m1} vs {m2}"
                    inter_model[key]["total"] += 1
                    if w1 == w2:
                        inter_model[key]["agree"] += 1

    inter_model_results = {
        k: {"agree": s["agree"], "total": s["total"],
            "rate": round(s["agree"] / max(s["total"], 1) * 100, 1)}
        for k, s in inter_model.items()
    }

    # Sample pairs table
    sample = [{
        "paper1_title": p["paper1"]["title"],
        "paper2_title": p["paper2"]["title"],
        "domain": p.get("domain", "?"),
        "human_winner": p["human_winner"],
        "human_score1": p["human_score1"],
        "human_score2": p["human_score2"],
        "ai_majority": p.get("ai_majority"),
        "majority_agree": p.get("ai_majority") == p["human_winner"] if p.get("ai_majority") else None,
        "models_agree": sum(1 for v in p.get("ai_results", {}).values() if v.get("winner") == p["human_winner"]),
        "models_total": sum(1 for v in p.get("ai_results", {}).values() if v.get("winner")),
        "score_gap": abs(p["human_score1"] - p["human_score2"]),
    } for p in pairs[:100]]

    return {
        "status": "ok",
        "total_pairs": total,
        "majority_agreement": {"agree": maj_agree, "total": maj_total, "rate": round(maj_agree / max(maj_total, 1) * 100, 1)},
        "by_model": model_results,
        "by_domain": domain_results,
        "by_score_gap": gap_results,
        "inter_model": inter_model_results,
        "full_text_vs_abstract": {
            "full_text": {"agree": ft_agree, "total": len(ft_pairs), "rate": round(ft_agree / max(len(ft_pairs), 1) * 100, 1)},
            "abstract_only": {"agree": ab_agree, "total": len(ab_pairs), "rate": round(ab_agree / max(len(ab_pairs), 1) * 100, 1)},
        },
        "sample_pairs": sample,
    }


# ─── Reset ─────────────────────────────────────────────────────────────────────

@router.post("/reset", dependencies=[Depends(verify_admin)])
async def reset_pairs():
    if _state["tournament_running"] or _state["fetching"]:
        return {"status": "error", "message": "Cannot reset while running"}
    r = await db.pairwise_comparisons.delete_many({})
    return {"status": "ok", "deleted": r.deleted_count}
