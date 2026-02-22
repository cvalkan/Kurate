"""
Human vs AI Validation Experiment — Multi-Dataset

Completely siloed from the main leaderboard system.
Supports multiple independent datasets, each with its own papers and tournament.
"""
import asyncio
import uuid
import random
import time as _time
import json
import re
import io
import os
import requests
from datetime import datetime, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
import numpy as np
from scipy import stats as scipy_stats

from core.config import db, logger, DEFAULT_EVALUATION_PROMPT
from core.auth import verify_admin, get_settings
from services.llm import compare_papers
from services.ranking import compute_leaderboard
from routers.validation_utils import (
    TIER_ORDER, RANKABLE_TIERS, norm_tier,
    build_expert_ratings, build_human_pairwise_matches, build_expert_majority, build_ai_majority,
    build_content_mode_filter, safe_round, interp, cache_get, cache_set,
)

router = APIRouter(prefix="/api/validation")

# In-memory tournament state per dataset
_tournament_states = {}  # dataset_id -> {running, completed, total, ...}
_tournament_tasks = {}  # dataset_id -> asyncio.Task


def _get_state(dataset_id: str) -> dict:
    if dataset_id not in _tournament_states:
        _tournament_states[dataset_id] = {
            "running": False, "completed_matches": 0,
            "total_matches": 0, "current_pair": "", "started_at": None,
            "cancel_requested": False,
        }
    return _tournament_states[dataset_id]


# ─── Datasets ──────────────────────────────────────────────────────────────────

@router.get("/datasets")
async def list_datasets():
    """List all validation datasets."""
    pipeline = [
        {"$group": {
            "_id": "$dataset_id",
            "count": {"$sum": 1},
            "with_text": {"$sum": {"$cond": [{"$and": [{"$ne": ["$full_text", None]}, {"$ne": ["$full_text", ""]}]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    paper_stats = {r["_id"]: r async for r in db.validation_papers.aggregate(pipeline)}

    match_pipeline = [
        {"$match": {"completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": "$dataset_id", "count": {"$sum": 1}}},
    ]
    match_stats = {r["_id"]: r["count"] async for r in db.validation_matches.aggregate(match_pipeline)}

    # Get dataset metadata
    meta_docs = await db.validation_datasets.find({}, {"_id": 0}).to_list(100)
    meta = {d["dataset_id"]: d for d in meta_docs}

    datasets = []
    for ds_id, ps in paper_stats.items():
        m = meta.get(ds_id, {})
        state = _get_state(ds_id)
        n_papers = ps["count"]
        n_matches = match_stats.get(ds_id, 0)
        datasets.append({
            "dataset_id": ds_id,
            "name": m.get("name", ds_id),
            "description": m.get("description", ""),
            "source": m.get("source", ""),
            "papers": n_papers,
            "papers_with_text": ps["with_text"],
            "matches": n_matches,
            "total_pairs": n_papers * (n_papers - 1) // 2 if n_papers > 1 else 0,
            "tournament_running": state["running"],
        })

    return {"datasets": datasets}


@router.post("/stop-tournament", dependencies=[Depends(verify_admin)])
async def stop_tournament(body: dict):
    """Stop a running tournament for a dataset."""
    dataset_id = body.get("dataset_id")
    if not dataset_id:
        return {"status": "error", "message": "dataset_id required"}
    state = _get_state(dataset_id)
    if not state["running"]:
        return {"status": "not_running"}
    state["cancel_requested"] = True
    # Cancel the asyncio task if we have a reference
    task = _tournament_tasks.get(dataset_id)
    if task and not task.done():
        task.cancel()
    return {"status": "stopping", "completed_so_far": state["completed_matches"]}



# ─── Import ────────────────────────────────────────────────────────────────────

class ImportICLRRequest(BaseModel):
    dataset_id: str
    name: str
    description: str = ""
    label_filter: str = "LLMs"
    years: list = [2024, 2025]
    min_reviews: int = 4
    max_papers: int = 80
    keyword_filter: str = ""


@router.post("/import-iclr", dependencies=[Depends(verify_admin)])
async def import_iclr_dataset(body: ImportICLRRequest):
    """Import ICLR papers from the berenslab dataset, filtered by label/keyword. Runs in background."""
    import pandas as pd

    # Try 26v1 first (has newer labels like PDEs, 3D scenes, molecules, speech), fall back to 25v2
    parquet_path = None
    for p in ['/tmp/iclr-dataset/data/iclr26v1.parquet', '/tmp/iclr-dataset/data/iclr25v2.parquet']:
        try:
            df = pd.read_parquet(p)
            parquet_path = p
            break
        except FileNotFoundError:
            continue
    if parquet_path is None:
        return {"status": "error", "message": "ICLR dataset not found. Download berenslab/iclr-dataset parquet to /tmp/iclr-dataset/data/"}

    def parse_scores(s):
        if isinstance(s, np.ndarray): return s.astype(float).tolist()
        return []

    df['parsed_scores'] = df['scores'].apply(parse_scores)
    df['n_reviews'] = df['parsed_scores'].apply(len)
    df['avg_score'] = df['parsed_scores'].apply(lambda x: float(np.mean(x)) if x else 0)

    # Filter
    filtered = df[
        (df['year'].isin(body.years)) &
        (df['n_reviews'] >= body.min_reviews) &
        (~df['decision'].isin(['Withdrawn', 'Desk rejected', '']))
    ].copy()

    if body.label_filter:
        filtered = filtered[filtered['labels'] == body.label_filter]
    if body.keyword_filter:
        filtered = filtered[filtered['title'].str.contains(body.keyword_filter, case=False, na=False)]

    if len(filtered) == 0:
        return {"status": "error", "message": f"No papers match filters: label={body.label_filter}, keyword={body.keyword_filter}"}

    # If pool fits within max_papers, take all; otherwise stratified sample
    if len(filtered) <= body.max_papers:
        selected = filtered
    else:
        bins = [0, 3, 4, 5, 5.5, 6, 7, 8, 11]
        filtered['score_bin'] = pd.cut(filtered['avg_score'], bins=bins)
        per_bin = max(body.max_papers // len(bins), 5)
        samples = []
        for _, group in filtered.groupby('score_bin', observed=True):
            samples.append(group.sample(min(len(group), per_bin), random_state=42))
        selected = pd.concat(samples)

    total = len(selected)

    # Save dataset metadata immediately
    await db.validation_datasets.update_one(
        {"dataset_id": body.dataset_id},
        {"$set": {
            "dataset_id": body.dataset_id,
            "name": body.name,
            "description": body.description,
            "source": f"ICLR {body.years} / {body.label_filter or body.keyword_filter}",
            "label_filter": body.label_filter,
            "keyword_filter": body.keyword_filter,
            "paper_count": total,
            "import_status": "importing",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    # Run import in background
    asyncio.create_task(_run_iclr_import(body.dataset_id, selected))

    return {"status": "started", "dataset_id": body.dataset_id, "papers_to_import": total}


async def _run_iclr_import(dataset_id: str, selected):
    """Background task to download PDFs and import ICLR papers."""
    imported = 0
    pdfs = 0
    for _, row in selected.iterrows():
        full_text = None
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                r = await client.get(f"https://openreview.net/pdf?id={row['id']}", timeout=30, follow_redirects=True)
                if r.status_code == 200 and r.content[:5] == b'%PDF-':
                    from PyPDF2 import PdfReader
                    reader = PdfReader(io.BytesIO(r.content))
                    parts = [page.extract_text() or "" for page in reader.pages]
                    text = " ".join(" ".join(parts).split()).encode("utf-8", errors="replace").decode("utf-8")
                    if len(text) > 500:
                        full_text = text
                        pdfs += 1
        except Exception as e:
            logger.warning(f"PDF download failed for {row['id']}: {e}")

        evaluations = [{"rating_value": float(s), "evaluator": f"Reviewer_{j+1}", "source": "ICLR"} for j, s in enumerate(row['parsed_scores'])]

        doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": dataset_id,
            "title": row["title"],
            "abstract": row["abstract"],
            "authors": [{"name": a} for a in row["authors"].split(", ")] if isinstance(row["authors"], str) else [],
            "openreview_id": row["id"],
            "year": int(row["year"]),
            "decision": row["decision"],
            "h1_avg_rating": float(row["avg_score"]),
            "h1_rating_count": int(row["n_reviews"]),
            "evaluations": evaluations,
            "scores": row["parsed_scores"],
            "keywords": row["keywords"].tolist() if isinstance(row["keywords"], np.ndarray) else [],
            "label": row["labels"],
            "source": "iclr_openreview",
            "full_text": full_text,
        }
        await db.validation_papers.update_one(
            {"dataset_id": dataset_id, "openreview_id": row["id"]},
            {"$set": doc}, upsert=True
        )
        imported += 1
        if imported % 10 == 0:
            await db.validation_datasets.update_one(
                {"dataset_id": dataset_id},
                {"$set": {"import_progress": imported, "import_pdfs": pdfs}},
            )
        await asyncio.sleep(0.3)

    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"import_status": "complete", "paper_count": imported, "import_progress": imported, "import_pdfs": pdfs}},
    )
    logger.info(f"ICLR import complete: {dataset_id} — {imported} papers, {pdfs} PDFs")


# ─── eLife Import ───────────────────────────────────────────────────────────────

SIG_SCORE_MAP = {"landmark": 5, "fundamental": 4, "important": 3, "valuable": 2, "useful": 1}
STR_SCORE_MAP = {"exceptional": 6, "compelling": 5, "convincing": 4, "solid": 3, "incomplete": 2, "inadequate": 1}


class ImportELifeRequest(BaseModel):
    dataset_id: str
    name: str
    description: str = ""
    subject: str = "Microbiology and Infectious Disease"
    max_papers: int = 80


@router.post("/import-elife", dependencies=[Depends(verify_admin)])
async def import_elife_dataset(body: ImportELifeRequest):
    """Import eLife reviewed preprints with structured significance + strength assessments."""

    await db.validation_datasets.update_one(
        {"dataset_id": body.dataset_id},
        {"$set": {
            "dataset_id": body.dataset_id,
            "name": body.name,
            "description": body.description,
            "source": f"eLife / {body.subject}",
            "import_status": "fetching_papers",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    asyncio.create_task(_run_elife_import(body.dataset_id, body.subject, body.max_papers))
    return {"status": "started", "dataset_id": body.dataset_id}


async def _run_elife_import(dataset_id: str, subject: str, max_papers: int):
    """Background: fetch eLife reviewed preprints, download PDFs, import."""
    ELIFE_API = "https://api.elifesciences.org"

    # Phase 1: Collect papers with assessments
    candidates = []
    for page in range(1, 200):
        try:
            r = requests.get(f"{ELIFE_API}/reviewed-preprints", params={
                "page": page, "per-page": 50, "order": "desc",
            }, timeout=15)
            if r.status_code != 200:
                break
            items = r.json().get("items", [])
            if not items:
                break
            for item in items:
                subjects = [s["name"] for s in item.get("subjects", [])]
                if subject not in subjects:
                    continue
                assessment = item.get("elifeAssessment", {})
                sig = assessment.get("significance", [])
                stren = assessment.get("strength", [])
                if not sig or not stren:
                    continue
                sig_score = SIG_SCORE_MAP.get(sig[0])
                str_score = STR_SCORE_MAP.get(stren[0])
                if sig_score is None or str_score is None:
                    continue
                candidates.append({
                    "elife_id": str(item["id"]),
                    "doi": item.get("doi", ""),
                    "title": item.get("title", ""),
                    "author_line": item.get("authorLine", ""),
                    "subjects": subjects,
                    "sig_label": sig[0],
                    "str_label": stren[0],
                    "sig_score": sig_score,
                    "str_score": str_score,
                })
        except Exception as e:
            logger.warning(f"eLife fetch page {page} failed: {e}")
            break
        await asyncio.sleep(0.2)
        if len(candidates) >= max_papers * 2:
            break

    logger.info(f"eLife import [{dataset_id}]: found {len(candidates)} candidates")
    if not candidates:
        await db.validation_datasets.update_one(
            {"dataset_id": dataset_id},
            {"$set": {"import_status": "error", "error": "No papers found"}},
        )
        return

    # Stratified sample by significance score
    if len(candidates) > max_papers:
        candidates.sort(key=lambda p: p["sig_score"])
        step = len(candidates) / max_papers
        selected = [candidates[int(i * step)] for i in range(max_papers)]
    else:
        selected = candidates

    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"import_status": "downloading", "paper_count": len(selected)}},
    )

    # Phase 2: Fetch full details + PDF for each paper
    import httpx as _httpx
    imported = 0
    pdfs = 0
    for paper in selected:
        # Fetch abstract from article detail
        abstract = ""
        try:
            r = requests.get(f"{ELIFE_API}/reviewed-preprints/{paper['elife_id']}", timeout=15)
            if r.status_code == 200:
                detail = r.json()
                idx = detail.get("indexContent", "")
                if idx and len(idx) > 100:
                    abstract = idx[:3000]
        except Exception:
            pass

        # Download PDF
        full_text = None
        try:
            pdf_url = f"https://elifesciences.org/articles/{paper['elife_id']}.pdf"
            async with _httpx.AsyncClient() as client:
                r = await client.get(pdf_url, timeout=30, follow_redirects=True)
                if r.status_code == 200 and r.content[:5] == b'%PDF-':
                    from PyPDF2 import PdfReader
                    reader = PdfReader(io.BytesIO(r.content))
                    parts = [page.extract_text() or "" for page in reader.pages]
                    text = " ".join(" ".join(parts).split()).encode("utf-8", errors="replace").decode("utf-8")
                    if len(text) > 500:
                        full_text = text
                        pdfs += 1
        except Exception as e:
            logger.warning(f"eLife PDF failed for {paper['elife_id']}: {e}")

        # Parse authors
        authors = []
        if paper.get("author_line"):
            for name in paper["author_line"].split(", "):
                name = name.strip().replace(" ... ", "").replace("...", "")
                if name:
                    authors.append({"name": name})

        doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": dataset_id,
            "title": paper["title"],
            "abstract": abstract,
            "authors": authors,
            "elife_id": paper["elife_id"],
            "doi": paper["doi"],
            "subjects": paper["subjects"],
            "sig_label": paper["sig_label"],
            "str_label": paper["str_label"],
            "sig_score": paper["sig_score"],
            "str_score": paper["str_score"],
            "h1_avg_rating": float(paper["sig_score"]),
            "h1_rating_count": 1,
            "evaluations": [{
                "rating_value": float(paper["sig_score"]),
                "significance": paper["sig_label"],
                "strength": paper["str_label"],
                "evaluator": "eLife Editorial Assessment",
                "source": "eLife",
            }],
            "scores": [paper["sig_score"]],
            "source": "elife_reviewed_preprint",
            "full_text": full_text,
        }
        await db.validation_papers.update_one(
            {"dataset_id": dataset_id, "elife_id": paper["elife_id"]},
            {"$set": doc}, upsert=True,
        )
        imported += 1
        if imported % 10 == 0:
            await db.validation_datasets.update_one(
                {"dataset_id": dataset_id},
                {"$set": {"import_progress": imported, "import_pdfs": pdfs}},
            )
        await asyncio.sleep(0.3)

    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"import_status": "complete", "paper_count": imported, "import_progress": imported, "import_pdfs": pdfs}},
    )
    logger.info(f"eLife import complete: {dataset_id} — {imported} papers, {pdfs} PDFs")



# ─── MIDL Import ────────────────────────────────────────────────────────────────

class ImportMIDLRequest(BaseModel):
    dataset_id: str
    name: str
    description: str = ""
    years: list = [2024, 2025]
    max_papers: int = 80
    include_short: bool = False


@router.post("/import-midl", dependencies=[Depends(verify_admin)])
async def import_midl_dataset(body: ImportMIDLRequest):
    """Import papers from MIDL (Medical Imaging with Deep Learning) via OpenReview API. Runs entirely in background."""

    await db.validation_datasets.update_one(
        {"dataset_id": body.dataset_id},
        {"$set": {
            "dataset_id": body.dataset_id,
            "name": body.name,
            "description": body.description,
            "source": f"MIDL {body.years} / OpenReview",
            "import_status": "fetching_papers",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    asyncio.create_task(_run_midl_full_import(body.dataset_id, body.name, body.description, body.years, body.max_papers, body.include_short))
    return {"status": "started", "dataset_id": body.dataset_id}


async def _run_midl_full_import(dataset_id: str, name: str, description: str, years: list, max_papers: int, include_short: bool):
    """Background task: fetch papers from OpenReview, get reviews, download PDFs, import."""
    OR_API = "https://api2.openreview.net"
    headers = {"User-Agent": "PaperSumo/1.0"}

    # Phase 1: Fetch all submissions
    all_papers = []
    for year in years:
        inv_types = [f"MIDL.io/{year}/Conference/-/Submission"]
        if include_short:
            inv_types.append(f"MIDL.io/{year}/Short_Papers/-/Submission")
        for inv in inv_types:
            offset = 0
            while True:
                try:
                    r = requests.get(f"{OR_API}/notes", params={
                        "invitation": inv, "limit": 50, "offset": offset,
                    }, headers=headers, timeout=20)
                    if r.status_code != 200:
                        break
                    notes = r.json().get("notes", [])
                    for n in notes:
                        content = n.get("content", {})
                        all_papers.append({
                            "forum_id": n["forum"],
                            "title": content.get("title", {}).get("value", ""),
                            "abstract": content.get("abstract", {}).get("value", ""),
                            "authors": content.get("authors", {}).get("value", []),
                            "venue": content.get("venue", {}).get("value", ""),
                            "keywords": content.get("keywords", {}).get("value", []),
                            "year": year,
                        })
                    if len(notes) < 50:
                        break
                    offset += 50
                except Exception:
                    break
                await asyncio.sleep(0.3)

    logger.info(f"MIDL import [{dataset_id}]: found {len(all_papers)} papers, fetching reviews...")
    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"import_status": "fetching_reviews", "papers_found": len(all_papers)}},
    )

    # Phase 2: Fetch reviews for each paper
    papers_with_reviews = []
    for i, paper in enumerate(all_papers):
        await asyncio.sleep(0.3)
        try:
            r = requests.get(f"{OR_API}/notes", params={
                "forum": paper["forum_id"], "limit": 30,
            }, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            forum_notes = r.json().get("notes", [])
            reviews = []
            meta_recommendation = None
            for fn in forum_notes:
                inv_id = fn.get("invitations", [""])[0] if isinstance(fn.get("invitations"), list) else ""
                content = fn.get("content", {})
                if "Official_Review" in inv_id:
                    prelim = content.get("preliminary_rating", {}).get("value")
                    final = content.get("final_rating", {}).get("value")
                    rating = content.get("rating", {}).get("value")
                    conf = content.get("confidence", {}).get("value")
                    rec = content.get("recommendation", {}).get("value")
                    score = float(final) if final is not None else (float(prelim) if prelim is not None else (float(rating) if rating is not None else None))
                    if score is not None:
                        reviews.append({
                            "score": score,
                            "preliminary": float(prelim) if prelim else None,
                            "final": float(final) if final else None,
                            "confidence": int(conf) if conf else None,
                            "recommendation": rec,
                        })
                elif "Meta_Review" in inv_id:
                    meta_recommendation = content.get("recommendation", {}).get("value", "")
            if len(reviews) < 2:
                continue
            scores = [rv["score"] for rv in reviews]
            paper["reviews"] = reviews
            paper["scores"] = scores
            paper["avg_score"] = sum(scores) / len(scores)
            paper["meta_recommendation"] = meta_recommendation
            venue = paper["venue"]
            paper["decision"] = "Oral" if "Oral" in venue else ("Poster" if "Poster" in venue else ("Short Paper" if "Short" in venue else venue))
            papers_with_reviews.append(paper)
        except Exception as e:
            logger.warning(f"MIDL review fetch failed for {paper['forum_id']}: {e}")
        if (i + 1) % 20 == 0:
            await db.validation_datasets.update_one(
                {"dataset_id": dataset_id},
                {"$set": {"import_progress_reviews": i + 1}},
            )

    if not papers_with_reviews:
        await db.validation_datasets.update_one(
            {"dataset_id": dataset_id},
            {"$set": {"import_status": "error", "error": "No papers with 2+ reviews found"}},
        )
        return

    logger.info(f"MIDL import [{dataset_id}]: {len(papers_with_reviews)} papers with reviews")

    # Phase 3: Stratified sample
    if len(papers_with_reviews) > max_papers:
        papers_with_reviews.sort(key=lambda p: p["avg_score"])
        step = len(papers_with_reviews) / max_papers
        selected = [papers_with_reviews[int(i * step)] for i in range(max_papers)]
    else:
        selected = papers_with_reviews

    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"import_status": "downloading_pdfs", "paper_count": len(selected)}},
    )

    # Phase 4: Download PDFs and import
    import httpx as _httpx
    imported = 0
    pdfs = 0
    for paper in selected:
        full_text = None
        try:
            async with _httpx.AsyncClient() as client:
                pdf_url = f"https://openreview.net/pdf?id={paper['forum_id']}"
                r = await client.get(pdf_url, timeout=30, follow_redirects=True)
                if r.status_code == 200 and r.content[:5] == b'%PDF-':
                    from PyPDF2 import PdfReader
                    reader = PdfReader(io.BytesIO(r.content))
                    parts = [page.extract_text() or "" for page in reader.pages]
                    text = " ".join(" ".join(parts).split()).encode("utf-8", errors="replace").decode("utf-8")
                    if len(text) > 500:
                        full_text = text
                        pdfs += 1
        except Exception as e:
            logger.warning(f"MIDL PDF download failed for {paper['forum_id']}: {e}")

        evaluations = []
        for j, rev in enumerate(paper["reviews"]):
            evaluations.append({
                "rating_value": rev["score"],
                "preliminary_rating": rev.get("preliminary"),
                "final_rating": rev.get("final"),
                "confidence": rev.get("confidence"),
                "recommendation": rev.get("recommendation"),
                "evaluator": f"Reviewer_{j+1}",
                "source": "MIDL/OpenReview",
            })

        doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": dataset_id,
            "title": paper["title"],
            "abstract": paper["abstract"],
            "authors": [{"name": a} for a in paper["authors"]] if isinstance(paper["authors"], list) else [],
            "openreview_id": paper["forum_id"],
            "year": paper["year"],
            "decision": paper["decision"],
            "h1_avg_rating": paper["avg_score"],
            "h1_rating_count": len(paper["scores"]),
            "evaluations": evaluations,
            "scores": paper["scores"],
            "keywords": paper.get("keywords", []),
            "venue": paper["venue"],
            "meta_recommendation": paper.get("meta_recommendation"),
            "source": "midl_openreview",
            "full_text": full_text,
        }
        await db.validation_papers.update_one(
            {"dataset_id": dataset_id, "openreview_id": paper["forum_id"]},
            {"$set": doc}, upsert=True,
        )
        imported += 1
        if imported % 10 == 0:
            await db.validation_datasets.update_one(
                {"dataset_id": dataset_id},
                {"$set": {"import_progress": imported, "import_pdfs": pdfs}},
            )
        await asyncio.sleep(0.3)

    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"import_status": "complete", "paper_count": imported, "import_progress": imported, "import_pdfs": pdfs}},
    )
    logger.info(f"MIDL import complete: {dataset_id} — {imported} papers, {pdfs} PDFs")



class ImportPeerReadRequest(BaseModel):
    dataset_id: str
    name: str
    description: str = ""
    venue: str = "acl_2017"
    min_reviews: int = 2
    max_papers: int = 80


@router.post("/import-peerread", dependencies=[Depends(verify_admin)])
async def import_peerread_dataset(body: ImportPeerReadRequest):
    """Import papers from the PeerRead dataset (AllenAI)."""
    import glob as glob_mod

    base_path = f"/tmp/PeerRead/data/{body.venue}"
    if not os.path.isdir(base_path):
        return {"status": "error", "message": f"PeerRead venue not found at {base_path}. Clone github.com/allenai/PeerRead to /tmp/PeerRead/"}

    all_papers = []
    for split in ["train", "dev", "test"]:
        review_dir = os.path.join(base_path, split, "reviews")
        parsed_dir = os.path.join(base_path, split, "parsed_pdfs")
        if not os.path.isdir(review_dir):
            continue

        for rf in glob_mod.glob(os.path.join(review_dir, "*.json")):
            paper_id = os.path.basename(rf).replace(".json", "")
            with open(rf) as f:
                data = json.load(f)

            reviews = data.get("reviews", [])
            scores = []
            for r in reviews:
                rec = r.get("RECOMMENDATION")
                if rec is not None:
                    try:
                        scores.append(int(rec))
                    except (ValueError, TypeError):
                        pass

            if len(scores) < body.min_reviews:
                continue

            # Parse full text from parsed PDF
            full_text = None
            pdf_file = os.path.join(parsed_dir, f"{paper_id}.pdf.json")
            if os.path.exists(pdf_file):
                with open(pdf_file) as f:
                    pdf_data = json.load(f)
                meta = pdf_data.get("metadata", {})
                sections = meta.get("sections", [])
                body_text = " ".join(s.get("text", "") for s in sections)
                if len(body_text) > 500:
                    full_text = body_text

            evaluations = [
                {"rating_value": float(s), "evaluator": f"Reviewer_{j+1}", "source": "PeerRead"}
                for j, s in enumerate(scores)
            ]

            authors = []
            pdf_meta = {}
            if os.path.exists(pdf_file):
                with open(pdf_file) as f:
                    pdf_meta = json.load(f).get("metadata", {})
                authors = [{"name": a} for a in pdf_meta.get("authors", [])]

            all_papers.append({
                "paper_id": paper_id,
                "title": data.get("title", pdf_meta.get("title", f"Paper {paper_id}")),
                "abstract": data.get("abstract", pdf_meta.get("abstractText", "")),
                "authors": authors,
                "scores": scores,
                "evaluations": evaluations,
                "full_text": full_text,
                "split": split,
            })

    if not all_papers:
        return {"status": "error", "message": f"No papers with ≥{body.min_reviews} reviews found in {body.venue}"}

    # Stratified sample by score
    all_papers.sort(key=lambda p: sum(p["scores"]) / len(p["scores"]))
    if len(all_papers) > body.max_papers:
        # Take evenly spaced papers across the score range
        step = len(all_papers) / body.max_papers
        selected = [all_papers[int(i * step)] for i in range(body.max_papers)]
    else:
        selected = all_papers

    imported = 0
    texts = 0
    for p in selected:
        avg = sum(p["scores"]) / len(p["scores"])
        doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": body.dataset_id,
            "title": p["title"],
            "abstract": p["abstract"],
            "authors": p["authors"],
            "peerread_id": p["paper_id"],
            "venue": body.venue,
            "h1_avg_rating": float(avg),
            "h1_rating_count": len(p["scores"]),
            "evaluations": p["evaluations"],
            "scores": p["scores"],
            "source": "peerread",
            "full_text": p["full_text"],
        }
        await db.validation_papers.update_one(
            {"dataset_id": body.dataset_id, "peerread_id": p["paper_id"]},
            {"$set": doc}, upsert=True
        )
        imported += 1
        if p["full_text"]:
            texts += 1

    await db.validation_datasets.update_one(
        {"dataset_id": body.dataset_id},
        {"$set": {
            "dataset_id": body.dataset_id,
            "name": body.name,
            "description": body.description,
            "source": f"PeerRead / {body.venue}",
            "venue": body.venue,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    return {"status": "ok", "dataset_id": body.dataset_id, "imported": imported, "with_full_text": texts, "total_available": len(all_papers)}



class ImportF1000Request(BaseModel):
    dataset_id: str
    name: str
    description: str = ""
    min_reviews: int = 2
    max_papers: int = 80
    start_offset: int = 0
    scan_pages: int = 2000


@router.post("/import-f1000", dependencies=[Depends(verify_admin)])
async def import_f1000_dataset(body: ImportF1000Request):
    """Import papers from F1000Research with structured peer review scores."""
    import xml.etree.ElementTree as ET

    SCORE_MAP = {"approve": 3, "approve-with-reservations": 2, "reject": 1}

    # Phase 1: Collect DOIs
    all_dois = []
    for page in range(body.start_offset, body.start_offset + body.scan_pages, 50):
        try:
            r = requests.get(
                f"https://f1000research.com/extapi/search?q=R_RP:*&rows=50&start={page}",
                timeout=15,
            )
            root = ET.fromstring(r.text)
            all_dois.extend([d.text for d in root.findall('.//doi')])
            _time.sleep(0.4)
        except Exception:
            break

    if not all_dois:
        return {"status": "error", "message": "Failed to fetch DOIs from F1000Research"}

    logger.info(f"F1000 import [{body.dataset_id}]: collected {len(all_dois)} DOIs, scanning...")

    # Phase 2: Parse articles and collect those with good review data
    candidates = []
    for i, doi in enumerate(all_dois):
        if len(candidates) >= body.max_papers * 3:
            break
        try:
            r = requests.get(
                f"https://f1000research.com/extapi/article/xml?doi={doi}",
                timeout=15,
            )
            tree = ET.fromstring(r.content)

            title_el = tree.find('.//article-title')
            title = title_el.text if title_el is not None else None
            if not title:
                continue

            # Abstract
            abstract_el = tree.find('.//abstract')
            abstract = ""
            if abstract_el is not None:
                abstract = " ".join(abstract_el.itertext()).strip()

            # Authors
            authors = []
            for contrib in tree.findall('.//contrib[@contrib-type="author"]'):
                sn = contrib.find('.//surname')
                gn = contrib.find('.//given-names')
                if sn is not None:
                    authors.append({"name": f"{gn.text if gn is not None else ''} {sn.text}".strip()})

            # Subjects
            subjects = []
            for s in tree.findall('.//subj-group/subj-group/subject'):
                if s.text:
                    subjects.append(s.text)

            # Body text from JATS XML
            body_parts = []
            for sec in tree.findall('.//body//sec'):
                for p in sec.findall('.//p'):
                    text = " ".join(p.itertext()).strip()
                    if text:
                        body_parts.append(text)
            full_text = " ".join(body_parts) if body_parts else None
            if full_text and len(full_text) < 500:
                full_text = None

            # Reviews — collect all with recommendation
            reviews = []
            for sub in tree.findall('.//sub-article[@article-type="reviewer-report"]'):
                for meta in sub.findall('.//custom-meta'):
                    mn = meta.find('meta-name')
                    mv = meta.find('meta-value')
                    if mn is not None and 'recommend' in (mn.text or '').lower():
                        rec = mv.text if mv is not None else None
                        if rec and rec in SCORE_MAP:
                            # Get reviewer name
                            reviewer_name = "Anonymous"
                            for c in sub.findall('.//contrib'):
                                sn2 = c.find('.//surname')
                                gn2 = c.find('.//given-names')
                                if sn2 is not None:
                                    reviewer_name = f"{gn2.text if gn2 is not None else ''} {sn2.text}".strip()
                            reviews.append({
                                "rating_value": float(SCORE_MAP[rec]),
                                "rating_label": rec,
                                "evaluator": reviewer_name,
                                "source": "F1000Research",
                            })

            if len(reviews) >= body.min_reviews and abstract:
                scores = [r["rating_value"] for r in reviews]
                candidates.append({
                    "doi": doi,
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "subjects": subjects,
                    "full_text": full_text,
                    "reviews": reviews,
                    "scores": scores,
                    "avg_score": sum(scores) / len(scores),
                    "has_reject": any(r["rating_label"] == "reject" for r in reviews),
                    "mixed": len(set(r["rating_label"] for r in reviews)) > 1,
                })

            _time.sleep(0.6)
        except Exception:
            continue

    if not candidates:
        return {"status": "error", "message": "No suitable articles found"}

    logger.info(f"F1000 import [{body.dataset_id}]: {len(candidates)} candidates found")

    # Phase 3: Select papers with best score distribution
    # Prioritize: papers with rejects, then mixed, then uniform
    rejects = [c for c in candidates if c["has_reject"]]
    mixed = [c for c in candidates if c["mixed"] and not c["has_reject"]]
    uniform = [c for c in candidates if not c["mixed"]]

    selected = []
    # Take all rejects first (they're rare and valuable)
    selected.extend(rejects[:body.max_papers // 3])
    # Fill with mixed reviews
    remaining = body.max_papers - len(selected)
    selected.extend(mixed[:remaining * 2 // 3])
    # Fill rest with uniform
    remaining = body.max_papers - len(selected)
    selected.extend(uniform[:remaining])
    selected = selected[:body.max_papers]

    # Phase 4: Import to DB
    imported = 0
    texts = 0
    for p in selected:
        doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": body.dataset_id,
            "title": p["title"],
            "abstract": p["abstract"],
            "authors": p["authors"],
            "f1000_doi": p["doi"],
            "subjects": p["subjects"],
            "h1_avg_rating": float(p["avg_score"]),
            "h1_rating_count": len(p["reviews"]),
            "evaluations": p["reviews"],
            "scores": p["scores"],
            "source": "f1000research",
            "full_text": p["full_text"],
        }
        await db.validation_papers.update_one(
            {"dataset_id": body.dataset_id, "f1000_doi": p["doi"]},
            {"$set": doc}, upsert=True,
        )
        imported += 1
        if p["full_text"]:
            texts += 1

    await db.validation_datasets.update_one(
        {"dataset_id": body.dataset_id},
        {"$set": {
            "dataset_id": body.dataset_id,
            "name": body.name,
            "description": body.description,
            "source": "F1000Research",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    score_dist = {"approve": 0, "approve-with-reservations": 0, "reject": 0}
    for p in selected:
        for r in p["reviews"]:
            score_dist[r["rating_label"]] = score_dist.get(r["rating_label"], 0) + 1

    return {
        "status": "ok",
        "dataset_id": body.dataset_id,
        "imported": imported,
        "with_full_text": texts,
        "total_candidates": len(candidates),
        "score_distribution": score_dist,
        "papers_with_reject": sum(1 for p in selected if p["has_reject"]),
        "papers_with_mixed": sum(1 for p in selected if p["mixed"]),
    }



# ─── Tournament ────────────────────────────────────────────────────────────────

class TournamentRequest(BaseModel):
    dataset_id: str
    num_matches: int = 500
    parallel: int = 30
    abstract_only: bool = False
    content_mode: Optional[str] = None  # "abstract", "extract", "full_pdf", "abstract_plus_summary"
    custom_prompt: Optional[dict] = None  # {"system_prompt": "...", "user_prompt": "..."}
    prompt_tag: Optional[str] = None  # Tag to identify this prompt variant (e.g., "editorial_v1")


@router.post("/run-tournament", dependencies=[Depends(verify_admin)])
async def run_tournament(body: TournamentRequest):
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    count = await db.validation_papers.count_documents({"dataset_id": body.dataset_id})
    if count < 2:
        return {"status": "error", "message": "Need at least 2 papers. Import first."}

    # Resolve content_mode from legacy abstract_only or new content_mode field
    content_mode = body.content_mode
    if content_mode is None:
        content_mode = "abstract" if body.abstract_only else "extract"

    task = asyncio.create_task(_run_tournament(body.dataset_id, min(max(body.num_matches, 1), 2000), min(max(body.parallel, 1), 50), content_mode=content_mode, custom_prompt=body.custom_prompt, prompt_tag=body.prompt_tag))
    _tournament_tasks[body.dataset_id] = task
    return {"status": "started", "dataset_id": body.dataset_id, "num_matches": body.num_matches, "content_mode": content_mode, "prompt_tag": body.prompt_tag}


async def _run_tournament(dataset_id: str, max_pairs: int, parallel: int, content_mode: str = "extract", custom_prompt: dict = None, prompt_tag: str = None):
    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": max_pairs, "current_pair": "Loading...", "started_at": _time.time()})

    abstract_only = content_mode == "abstract"
    # Use custom prompt if provided, otherwise default
    prompt_config = custom_prompt if custom_prompt else DEFAULT_EVALUATION_PROMPT
    # Effective content_mode for storage: append prompt_tag if present
    storage_mode = f"{content_mode}:{prompt_tag}" if prompt_tag else content_mode

    try:
        papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
        lookup = {p["id"]: p for p in papers}
        pids = list(lookup.keys())

        # Dedup: only check matches of the same storage mode
        match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
        if prompt_tag:
            match_filter["content_mode"] = storage_mode
        elif content_mode in ("abstract_plus_3summaries", "abstract_plus_random_summary"):
            match_filter["content_mode"] = content_mode
        elif content_mode == "abstract":
            match_filter["abstract_only"] = True
        elif content_mode == "full_pdf":
            match_filter["content_mode"] = "full_pdf"
        elif content_mode in ("abstract_plus_summary", "ai_summary", "abstract_plus_impact"):
            match_filter["content_mode"] = content_mode
        else:
            # "extract" mode: exclude abstract, named modes, and tagged variants
            match_filter["abstract_only"] = {"$ne": True}
            match_filter["content_mode"] = {"$nin": ["full_pdf", "ai_summary", "abstract_plus_summary", "abstract_plus_impact"], "$not": {"$regex": ":"}}

        existing = await db.validation_matches.find(
            match_filter,
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ).to_list(100000)
        compared = {tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in existing}

        # Connectivity-aware pair selection:
        # Phase 1 — Ensure every paper appears in at least min_per_paper matches
        # Phase 2 — Fill remaining budget targeting least-matched papers
        from collections import Counter
        match_counts = Counter()
        for m in existing:
            match_counts[m["paper1_id"]] += 1
            match_counts[m["paper2_id"]] += 1

        pairs = []
        min_per_paper = max(3, min(8, max_pairs // len(pids)))

        # Phase 1: Round-robin for under-matched papers
        for _ in range(max_pairs):
            if len(pairs) >= max_pairs:
                break
            # Find paper with fewest matches
            neediest = sorted(pids, key=lambda p: match_counts[p])
            placed = False
            for p1 in neediest:
                if match_counts[p1] >= min_per_paper and all(match_counts[p] >= min_per_paper for p in pids):
                    break  # All papers have min coverage
                candidates = [p for p in pids if p != p1 and tuple(sorted([p1, p])) not in compared]
                if not candidates:
                    continue
                # Pick the least-matched candidate
                candidates.sort(key=lambda p: match_counts[p])
                p2 = candidates[0]
                key = tuple(sorted([p1, p2]))
                pairs.append((p1, p2))
                compared.add(key)
                match_counts[p1] += 1
                match_counts[p2] += 1
                placed = True
                break
            if not placed:
                break

        # Phase 2: Fill remaining with random pairs (biased toward least-matched)
        attempts = 0
        while len(pairs) < max_pairs and attempts < max_pairs * 20:
            # Weighted random: prefer papers with fewer matches
            weights = [1.0 / (match_counts[p] + 1) for p in pids]
            total_w = sum(weights)
            weights = [w / total_w for w in weights]
            p1 = random.choices(pids, weights=weights, k=1)[0]
            p2 = random.choice([p for p in pids if p != p1])
            key = tuple(sorted([p1, p2]))
            if key not in compared:
                pairs.append((p1, p2))
                compared.add(key)
                match_counts[p1] += 1
                match_counts[p2] += 1
            attempts += 1

        logger.info(f"Pair selection [{dataset_id}]: {len(pairs)} pairs, min_per_paper={min_per_paper}, "
                     f"actual min={min(match_counts[p] for p in pids)}, max={max(match_counts[p] for p in pids)}")

        state["total_matches"] = len(pairs)
        completed = 0

        # Semaphore-based pipeline: each result saved immediately as it completes
        # No batch blocking — a slow/failing call never holds up successful ones
        sem = asyncio.Semaphore(parallel)

        async def _run_one(p1_orig, p2_orig):
            nonlocal completed
            if state.get("cancel_requested"):
                return
            # Random flip for positional bias
            if random.random() < 0.5:
                p1_id, p2_id = p2_orig, p1_orig
            else:
                p1_id, p2_id = p1_orig, p2_orig

            async with sem:
                if state.get("cancel_requested"):
                    return
                result = await compare_papers(lookup[p1_id], lookup[p2_id], prompt_config, content_mode=content_mode)

            used_ext = content_mode == "extract" and bool(lookup[p1_id].get("full_text") and lookup[p2_id].get("full_text"))
            doc = {
                "id": str(uuid.uuid4()), "dataset_id": dataset_id,
                "paper1_id": p1_id, "paper2_id": p2_id,
                "used_extraction": used_ext,
                "abstract_only": abstract_only,
                "content_mode": storage_mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if prompt_tag:
                doc["prompt_tag"] = prompt_tag
            if isinstance(result, Exception):
                doc.update({"completed": False, "failed": True, "error": str(result)[:200]})
            else:
                winner_key = result.get("winner", "paper1")
                doc.update({
                    "winner_id": p1_id if winner_key == "paper1" else p2_id,
                    "reasoning": result.get("reasoning", ""),
                    "model_used": result.get("model_used", {}),
                    "tokens": result.get("tokens", {}),
                    "completed": True, "failed": False,
                })
                completed += 1
            await db.validation_matches.insert_one(doc)
            state["completed_matches"] = completed

        all_tasks = [_run_one(p1, p2) for p1, p2 in pairs]
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        # Log any unexpected task-level errors
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Validation match task error: {r}")

        logger.info(f"Validation tournament [{dataset_id}] ({content_mode}): {completed}/{len(pairs)}")
    except (Exception, asyncio.CancelledError) as e:
        if isinstance(e, asyncio.CancelledError):
            logger.info(f"Validation tournament [{dataset_id}] cancelled at {completed}/{len(pairs)}")
        else:
            logger.error(f"Validation tournament [{dataset_id}] error: {e}")
    finally:
        state["running"] = False
        state["cancel_requested"] = False
        _tournament_tasks.pop(dataset_id, None)
        invalidate_dataset_cache(dataset_id)


# ─── Multi-Model Tournament ───────────────────────────────────────────────────

class MultiModelRequest(BaseModel):
    dataset_id: str
    parallel: int = 30
    max_pairs: int = 0  # 0 = all pairs
    content_mode: Optional[str] = None  # "abstract", "extract", "full_pdf"; None = extract (legacy)


@router.post("/run-multimodel", dependencies=[Depends(verify_admin)])
async def run_multimodel_tournament(body: MultiModelRequest):
    """Re-run existing pairs with all 3 models so each pair has 3 verdicts."""
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    content_mode = body.content_mode or "extract"
    asyncio.create_task(_run_multimodel(body.dataset_id, min(max(body.parallel, 1), 50), body.max_pairs, content_mode))
    return {"status": "started", "dataset_id": body.dataset_id, "max_pairs": body.max_pairs, "content_mode": content_mode}


async def _run_multimodel(dataset_id: str, parallel: int, max_pairs: int = 0, content_mode: str = "extract"):
    from core.config import TOURNAMENT_MODELS

    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": 0, "current_pair": "Scanning...", "started_at": _time.time()})

    try:
        papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
        lookup = {p["id"]: p for p in papers}

        # Get completed matches filtered by content_mode
        match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
        match_filter.update(build_content_mode_filter(content_mode))

        matches = await db.validation_matches.find(
            match_filter,
            {"_id": 0},
        ).to_list(100000)

        # Group by pair → which models already ran
        pair_models = defaultdict(list)
        for m in matches:
            pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            model = m.get("model_used", {})
            model_key = f"{model.get('provider', '')}:{model.get('model', '')}"
            pair_models[pair].append(model_key)

        all_model_keys = {f"{m['provider']}:{m['model']}" for m in TOURNAMENT_MODELS}

        # Build tasks: for each pair, run missing models
        # If max_pairs is set, only fill in up to that many pairs
        pairs_needing_work = []
        for pair, done_keys in pair_models.items():
            missing = all_model_keys - set(done_keys)
            if missing:
                pairs_needing_work.append((pair, missing))

        if max_pairs > 0:
            random.shuffle(pairs_needing_work)
            pairs_needing_work = pairs_needing_work[:max_pairs]

        work = []  # (p1_id, p2_id, model_info)
        for pair, missing in pairs_needing_work:
            for mk in missing:
                provider, model = mk.split(":", 1)
                mi = {"provider": provider, "model": model}
                work.append((pair[0], pair[1], mi))

        if not work:
            state["running"] = False
            logger.info(f"Multi-model [{dataset_id}]: all pairs already have all 3 models")
            return

        state["total_matches"] = len(work)
        state["current_pair"] = f"0/{len(work)} remaining"
        prompt_config = DEFAULT_EVALUATION_PROMPT
        completed = 0

        for i in range(0, len(work), parallel):
            batch = work[i:i + parallel]
            state["current_pair"] = f"Batch {i // parallel + 1} ({completed}/{len(work)})"

            tasks = []
            for p1_id, p2_id, model_info in batch:
                # Random presentation order
                if random.random() < 0.5:
                    tasks.append((p2_id, p1_id, model_info))
                else:
                    tasks.append((p1_id, p2_id, model_info))

            coros = [
                compare_papers(
                    lookup[p1], lookup[p2], prompt_config,
                    content_mode=content_mode,
                    model_override=mi,
                )
                for p1, p2, mi in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for (p1_id, p2_id, mi), result in zip(tasks, results):
                used_ext = content_mode == "extract" and bool(lookup[p1_id].get("full_text") and lookup[p2_id].get("full_text"))
                doc = {
                    "id": str(uuid.uuid4()), "dataset_id": dataset_id,
                    "paper1_id": p1_id, "paper2_id": p2_id,
                    "used_extraction": used_ext,
                    "abstract_only": content_mode == "abstract",
                    "content_mode": content_mode,
                    "model_used": mi,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if isinstance(result, Exception):
                    doc.update({"completed": False, "failed": True, "error": str(result)[:200]})
                else:
                    winner_key = result.get("winner", "paper1")
                    doc.update({
                        "winner_id": p1_id if winner_key == "paper1" else p2_id,
                        "reasoning": result.get("reasoning", ""),
                        "model_used": result.get("model_used", mi),
                        "tokens": result.get("tokens", {}),
                        "completed": True, "failed": False,
                    })
                    completed += 1

                await db.validation_matches.insert_one(doc)
                state["completed_matches"] = completed
            await asyncio.sleep(0.2)

        logger.info(f"Multi-model [{dataset_id}]: {completed}/{len(work)} new matches")
    except Exception as e:
        logger.error(f"Multi-model [{dataset_id}] error: {e}")
    finally:
        state["running"] = False
        invalidate_dataset_cache(dataset_id)


# ─── Multi-Model Analysis ─────────────────────────────────────────────────────

@router.get("/multimodel-results")
async def get_multimodel_results(dataset_id: str = Query(...), content_mode: Optional[str] = Query(None)):
    """Inter-model agreement + majority-vote vs expert analysis."""
    from core.config import TOURNAMENT_MODELS

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(content_mode))

    matches = await db.validation_matches.find(
        match_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
    ).to_list(100000)

    if not papers or not matches:
        return {"status": "no_data"}

    # Group matches by pair and model
    pair_verdicts = defaultdict(dict)  # pair -> model_key -> winner_id
    model_keys_seen = set()
    for m in matches:
        pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        mu = m.get("model_used", {})
        mk = f"{mu.get('provider', '')}:{mu.get('model', '')}"
        model_keys_seen.add(mk)
        pair_verdicts[pair][mk] = m["winner_id"]

    # Only use pairs that have all 3 models
    all_models = sorted(model_keys_seen)
    full_pairs = {p: v for p, v in pair_verdicts.items() if len(v) >= len(all_models)}

    if len(full_pairs) < 5:
        return {"status": "insufficient_multimodel_data", "pairs_with_all_models": len(full_pairs), "models_seen": all_models}

    # Inter-model pairwise agreement
    model_agreement = {}
    for i, m1 in enumerate(all_models):
        for j, m2 in enumerate(all_models):
            if j <= i:
                continue
            agree = sum(1 for v in full_pairs.values() if v.get(m1) == v.get(m2))
            total = len(full_pairs)
            model_agreement[f"{m1} vs {m2}"] = {
                "agree": agree, "total": total,
                "rate": round(agree / max(total, 1) * 100, 1),
            }

    # Per-model BT rankings
    paper_ids = {p["id"] for p in papers}
    model_rankings = {}
    for mk in all_models:
        model_matches = [
            {"paper1_id": p[0], "paper2_id": p[1], "winner_id": v[mk], "completed": True, "failed": False}
            for p, v in full_pairs.items() if mk in v
        ]
        mp = [p for p in papers if p["id"] in paper_ids]
        lb = compute_leaderboard(mp, model_matches)
        model_rankings[mk] = {e["id"]: e["rank"] for e in lb}

    # Inter-model rank correlation
    model_correlations = {}
    for i, m1 in enumerate(all_models):
        for j, m2 in enumerate(all_models):
            if j <= i:
                continue
            common = set(model_rankings[m1].keys()) & set(model_rankings[m2].keys())
            if len(common) < 15:
                continue
            ids = sorted(common)
            r1 = [model_rankings[m1][pid] for pid in ids]
            r2 = [model_rankings[m2][pid] for pid in ids]
            sp, sp_p = scipy_stats.spearmanr(r1, r2)
            model_correlations[f"{m1} vs {m2}"] = {
                "spearman_rho": round(sp, 4), "p_value": round(sp_p, 6), "papers": len(common),
            }

    # Majority vote
    majority_winner = {}
    for pair, verdicts in full_pairs.items():
        winners = list(verdicts.values())
        c = Counter(winners)
        best, n = c.most_common(1)[0]
        if n > len(winners) / 2:
            majority_winner[pair] = best

    # Majority vote vs human expert
    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                expert_ratings[name][p["id"]] = ev["rating_value"]

    # Expert majority for each pair
    expert_pair_votes = defaultdict(list)
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                ra, rb = ratings[a], ratings[b]
                if ra != rb:
                    pair = tuple(sorted([a, b]))
                    expert_pair_votes[pair].append(a if ra > rb else b)

    expert_majority = {}
    for pair, votes in expert_pair_votes.items():
        if len(votes) < 2:
            continue
        c = Counter(votes)
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            expert_majority[pair] = best

    # Compare AI majority vs expert majority
    overlap = set(majority_winner.keys()) & set(expert_majority.keys())
    maj_agree = sum(1 for p in overlap if majority_winner[p] == expert_majority[p])

    # Compare each individual model vs expert majority
    per_model_vs_expert = {}
    for mk in all_models:
        agree = 0
        total = 0
        for pair, exp_winner in expert_majority.items():
            if pair in pair_verdicts and mk in pair_verdicts[pair]:
                total += 1
                if pair_verdicts[pair][mk] == exp_winner:
                    agree += 1
        per_model_vs_expert[mk] = {"agree": agree, "total": total, "rate": round(agree / max(total, 1) * 100, 1)}

    # Majority-vote BT ranking vs human BT ranking
    maj_matches = [
        {"paper1_id": p[0], "paper2_id": p[1], "winner_id": w, "completed": True, "failed": False}
        for p, w in majority_winner.items()
    ]
    # Human pairwise matches
    human_matches = []
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                ra, rb = ratings[a], ratings[b]
                if ra != rb:
                    human_matches.append({"paper1_id": a, "paper2_id": b, "winner_id": a if ra > rb else b, "completed": True, "failed": False})

    h_ids = {m["paper1_id"] for m in human_matches} | {m["paper2_id"] for m in human_matches}
    m_ids = {m["paper1_id"] for m in maj_matches} | {m["paper2_id"] for m in maj_matches}
    common = h_ids & m_ids

    maj_correlation = None
    if len(common) >= 3:
        cp = [p for p in papers if p["id"] in common]
        ch = [m for m in human_matches if m["paper1_id"] in common and m["paper2_id"] in common]
        cm = [m for m in maj_matches if m["paper1_id"] in common and m["paper2_id"] in common]
        h_lb = compute_leaderboard(cp, ch)
        m_lb = compute_leaderboard(cp, cm)
        h_rank = {e["id"]: e["rank"] for e in h_lb}
        m_rank = {e["id"]: e["rank"] for e in m_lb}
        ids = sorted(common)
        hr = [h_rank[pid] for pid in ids]
        mr = [m_rank[pid] for pid in ids]
        sp, sp_p = scipy_stats.spearmanr(hr, mr)
        maj_correlation = {"spearman_rho": round(sp, 4), "p_value": round(sp_p, 6), "papers": len(common)}

    return {
        "status": "ok",
        "models": all_models,
        "pairs_with_all_models": len(full_pairs),
        "inter_model_agreement": model_agreement,
        "inter_model_correlation": model_correlations,
        "majority_vs_expert_majority": {
            "agree": maj_agree, "total": len(overlap),
            "rate": round(maj_agree / max(len(overlap), 1) * 100, 1),
        },
        "per_model_vs_expert_majority": per_model_vs_expert,
        "majority_bt_vs_human_bt": maj_correlation,
    }



@router.get("/available-modes")
async def get_available_modes(dataset_id: str = Query(...)):
    """List content modes that have match data for a dataset, including prompt-tagged variants."""
    SUMMARY_TAG_LABELS = {
        "gpt_summary": "Abstract + Summary (GPT-5.2)",
        "gemini_summary": "Abstract + Summary (Gemini 3 Pro)",
        "opus_thinking": "Abstract + Summary (Opus 4.5 Thinking)",
        "gpt_thinking": "Abstract + Summary (GPT-5.2 Thinking)",
        "gemini_thinking": "Abstract + Summary (Gemini 3 Thinking)",
        "opus46": "Abstract + Summary (Opus 4.6)",
    }
    BASE_LABELS = {
        "none": "Extract", "extract": "Extract", "abstract": "Abstract",
        "full_pdf": "Full PDF", "ai_summary": "AI Summary",
        "abstract_plus_summary": "Abstract + Summary (Opus 4.5)",
        "abstract_plus_impact": "Abstract + Impact",
        "abstract_plus_3summaries": "Abstract + 3 Summaries",
        "abstract_plus_random_summary": "Abstract + Random Summary",
    }
    pipeline = [
        {"$match": {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}},
        {"$group": {
            "_id": {"content_mode": {"$ifNull": ["$content_mode", "none"]}, "prompt_tag": {"$ifNull": ["$prompt_tag", None]}},
            "count": {"$sum": 1}
        }},
    ]
    # Single pass: collect raw results and detect variants
    raw_results = []
    has_summary_variants = False
    async for doc in db.validation_matches.aggregate(pipeline):
        cm = doc["_id"]["content_mode"]
        pt = doc["_id"]["prompt_tag"]
        if not pt and ":" in cm:
            pt = cm.split(":", 1)[1]
        if pt and pt in SUMMARY_TAG_LABELS:
            has_summary_variants = True
        raw_results.append((cm, pt, doc["count"]))

    modes = []
    for cm, pt, count in raw_results:
        mode_id = cm if cm != "none" else "extract"
        if pt:
            label = SUMMARY_TAG_LABELS.get(pt, f"{BASE_LABELS.get(cm.split(':')[0], cm)} ({pt})")
            final_id = cm
        elif has_summary_variants and cm == "abstract_plus_summary":
            label = "Abstract + Summary (Opus 4.5)"
            final_id = cm
        else:
            label = BASE_LABELS.get(cm, mode_id.replace("_", " ").title())
            final_id = cm
        modes.append({"id": final_id, "label": label, "prompt_tag": pt, "matches": count})
    return {"modes": sorted(modes, key=lambda m: -m["matches"])}


# ─── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(dataset_id: str = Query(...)):
    cached = await cache_get("status", dataset_id, "")
    if cached:
        # Always update tournament_running from live state
        state = _get_state(dataset_id)
        cached["tournament_running"] = state["running"]
        cached["tournament_progress"] = state
        return cached
    result = await _compute_status(dataset_id)
    await cache_set("status", dataset_id, "", result)
    return result

async def _compute_status(dataset_id: str):
    # Single aggregation for all match counts (replaces 5 separate count_documents calls)
    match_stats_pipeline = [
        {"$match": {"dataset_id": dataset_id}},
        {"$facet": {
            "completed": [
                {"$match": {"completed": True, "failed": {"$ne": True}}},
                {"$group": {"_id": None, "count": {"$sum": 1},
                            "ext": {"$sum": {"$cond": ["$used_extraction", 1, 0]}},
                            "abs_only": {"$sum": {"$cond": ["$abstract_only", 1, 0]}},
                            "p1s": {"$push": "$paper1_id"}, "p2s": {"$push": "$paper2_id"}}},
            ],
            "failed": [
                {"$match": {"failed": True}},
                {"$count": "count"},
            ],
        }},
    ]
    # Paper counts in parallel
    paper_stats_pipeline = [
        {"$match": {"dataset_id": dataset_id}},
        {"$facet": {
            "total": [{"$count": "n"}],
            "with_text": [{"$match": {"full_text": {"$exists": True, "$nin": [None, ""]}}}, {"$count": "n"}],
            "evaluators": [
                {"$unwind": "$evaluations"},
                {"$group": {"_id": "$evaluations.evaluator"}},
                {"$count": "total"},
            ],
            "reviews": [
                {"$group": {"_id": None, "total": {"$sum": "$h1_rating_count"}}},
            ],
        }},
    ]

    match_agg, paper_agg = await asyncio.gather(
        db.validation_matches.aggregate(match_stats_pipeline).to_list(1),
        db.validation_papers.aggregate(paper_stats_pipeline).to_list(1),
    )

    # Parse match stats
    ms = match_agg[0] if match_agg else {}
    comp = ms.get("completed", [{}])[0] if ms.get("completed") else {}
    m = comp.get("count", 0)
    m_ext = comp.get("ext", 0)
    m_abs_only = comp.get("abs_only", 0)
    failed = ms.get("failed", [{}])[0].get("count", 0) if ms.get("failed") else 0

    # Parse paper stats
    ps = paper_agg[0] if paper_agg else {}
    n = ps.get("total", [{}])[0].get("n", 0) if ps.get("total") else 0
    with_text = ps.get("with_text", [{}])[0].get("n", 0) if ps.get("with_text") else 0
    n_evaluators = ps.get("evaluators", [{}])[0].get("total", 0) if ps.get("evaluators") else 0
    total_reviews = ps.get("reviews", [{}])[0].get("total", 0) if ps.get("reviews") else 0

    total_pairs = n * (n - 1) // 2 if n > 1 else 0

    # Match distribution + connectivity (from the aggregation data we already have)
    avg_m = min_m = max_m = 0
    connected_components = 0
    isolated_papers = 0
    if m > 0 and comp.get("p1s"):
        counts = Counter(comp["p1s"] + comp["p2s"])
        avg_m = round(sum(counts.values()) / max(len(counts), 1), 1)
        min_m = min(counts.values())
        max_m = max(counts.values())

        # Graph connectivity via union-find
        parent = {}
        def find(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for p1, p2 in zip(comp["p1s"], comp["p2s"]):
            union(p1, p2)

        matched_papers = set(comp["p1s"] + comp["p2s"])
        roots = set(find(p) for p in matched_papers)
        connected_components = len(roots)

        # Isolated papers
        all_paper_ids = set()
        async for p in db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0, "id": 1}):
            all_paper_ids.add(p["id"])
        isolated_papers = len(all_paper_ids - matched_papers)

    state = _get_state(dataset_id)
    meta = await db.validation_datasets.find_one({"dataset_id": dataset_id}, {"_id": 0}) or {}

    # Evaluator type detection
    evaluator_names = set()
    async for p in db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0, "evaluations": 1}):
        for ev in p.get("evaluations", []):
            evaluator_names.add(ev.get("evaluator", ""))
    has_generic = any(nm.startswith("Reviewer_") or nm in ("Qeios Community", "eLife Editorial Assessment") for nm in evaluator_names)
    human_expert_count = total_reviews if has_generic else n_evaluators

    return {
        "dataset_id": dataset_id,
        "name": meta.get("name", dataset_id),
        "papers_imported": n,
        "papers_with_full_text": with_text,
        "matches_completed": m,
        "matches_with_extraction": m_ext,
        "matches_abstract_only": m - m_ext,
        "matches_abstract_tournament": m_abs_only,
        "matches_failed": failed,
        "total_possible_pairs": total_pairs,
        "coverage_pct": round(m / max(total_pairs, 1) * 100, 1),
        "avg_matches_per_paper": avg_m,
        "min_matches_per_paper": min_m,
        "max_matches_per_paper": max_m,
        "graph_connected_components": connected_components,
        "graph_isolated_papers": isolated_papers,
        "graph_is_connected": connected_components == 1 and isolated_papers == 0,
        "tournament_running": state["running"],
        "tournament_progress": state,
        "human_evaluators": n_evaluators,
        "total_human_reviews": total_reviews,
        "human_expert_count": human_expert_count,
    }


# ─── Results: Pairwise BT ─────────────────────────────────────────────────────



@router.get("/pairwise-results")
async def get_pairwise_results(dataset_id: str = Query(...), abstract_only: Optional[bool] = Query(None), content_mode: Optional[str] = Query(None)):
    cache_mode = content_mode or ("abstract" if abstract_only else "extract")
    cached = await cache_get("pairwise", dataset_id, cache_mode)
    if cached:
        return cached
    result = await _compute_pairwise_results(dataset_id, abstract_only, content_mode)
    if result.get("status") == "ok":
        await cache_set("pairwise", dataset_id, cache_mode, result)
    return result

async def _compute_pairwise_results(dataset_id: str, abstract_only: Optional[bool], content_mode: Optional[str]):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(content_mode, abstract_only))

    ai_matches = await db.validation_matches.find(
        match_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ).to_list(100000)

    if not papers or len(ai_matches) < 2:
        return {"status": "no_data"}

    # Derive human pairwise matches
    expert_ratings = defaultdict(list)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                expert_ratings[name].append((p["id"], ev["rating_value"]))

    human_matches = []
    ties = 0
    experts_used = 0
    for exp, rated in expert_ratings.items():
        if len(rated) < 2: continue
        experts_used += 1
        for i in range(len(rated)):
            for j in range(i + 1, len(rated)):
                a, ra = rated[i]; b, rb = rated[j]
                if ra == rb: ties += 1; continue
                human_matches.append({"paper1_id": a, "paper2_id": b, "winner_id": a if ra > rb else b, "completed": True, "failed": False})

    h_ids = {m["paper1_id"] for m in human_matches} | {m["paper2_id"] for m in human_matches}
    a_ids = {m["paper1_id"] for m in ai_matches} | {m["paper2_id"] for m in ai_matches}
    common = h_ids & a_ids
    if len(common) < 15:
        return {"status": "insufficient_data"}

    cp = [p for p in papers if p["id"] in common]
    ch = [m for m in human_matches if m["paper1_id"] in common and m["paper2_id"] in common]
    ca = [m for m in ai_matches if m["paper1_id"] in common and m["paper2_id"] in common]

    h_lb = compute_leaderboard(cp, ch)
    a_lb = compute_leaderboard(cp, ca)
    h_rank = {e["id"]: e for e in h_lb}
    a_rank = {e["id"]: e for e in a_lb}

    ai_ranks = [a_rank[pid]["rank"] for pid in sorted(common)]
    human_ranks = [h_rank[pid]["rank"] for pid in sorted(common)]
    sp, sp_p = scipy_stats.spearmanr(ai_ranks, human_ranks)
    kt, kt_p = scipy_stats.kendalltau(ai_ranks, human_ranks)
    pr, pr_p = scipy_stats.pearsonr(
        [a_rank[pid]["score"] for pid in sorted(common)],
        [h_rank[pid]["score"] for pid in sorted(common)]
    )

    comparison = sorted([{
        "id": pid, "title": next(p["title"] for p in cp if p["id"] == pid),
        "human_rank": h_rank[pid]["rank"], "human_score": h_rank[pid]["score"],
        "human_win_rate": h_rank[pid]["win_rate"], "human_matches": h_rank[pid]["comparisons"],
        "ai_rank": a_rank[pid]["rank"], "ai_score": a_rank[pid]["score"],
        "ai_win_rate": a_rank[pid]["win_rate"], "ai_matches": a_rank[pid]["comparisons"],
        "rank_delta": a_rank[pid]["rank"] - h_rank[pid]["rank"],
    } for pid in common], key=lambda x: x["human_rank"])

    # ─── Acceptance Tier Metrics ────────────────────────────────────────
    paper_tiers = {}
    for p in papers:
        t = norm_tier(p.get("decision"))
        if t and t in RANKABLE_TIERS:
            paper_tiers[p["id"]] = t

    tier_metrics = None
    if len(paper_tiers) >= 5:
        # Enrich comparison with tier data
        for entry in comparison:
            entry["tier"] = paper_tiers.get(entry["id"])

        # Tier pair accuracy from the AI ranking
        tier_correct = 0
        tier_total = 0
        for i, a in enumerate(comparison):
            for b in comparison[i+1:]:
                ta, tb = paper_tiers.get(a["id"]), paper_tiers.get(b["id"])
                if not ta or not tb or TIER_ORDER.get(ta) == TIER_ORDER.get(tb):
                    continue
                tier_total += 1
                higher = a if TIER_ORDER[ta] < TIER_ORDER[tb] else b
                lower = b if higher == a else a
                if higher["ai_rank"] < lower["ai_rank"]:
                    tier_correct += 1

        # Top-K precision
        top_tier_ids = {pid for pid, t in paper_tiers.items() if t in ("oral", "spotlight")}
        ai_sorted = sorted(comparison, key=lambda e: e["ai_rank"])
        top_k_precision = {}
        for k in [5, 10]:
            top_ids = {e["id"] for e in ai_sorted[:k]}
            hits = len(top_ids & top_tier_ids)
            top_k_precision[f"top_{k}"] = {"hits": hits, "total": min(k, len(ai_sorted)), "precision": round(hits / min(k, len(ai_sorted)) * 100, 1)}

        tier_metrics = {
            "overall_accuracy": round(tier_correct / max(tier_total, 1) * 100, 1),
            "correct": tier_correct,
            "total_pairs": tier_total,
            "top_k_precision": top_k_precision,
            "tier_distribution": {t: sum(1 for v in paper_tiers.values() if v == t) for t in ("oral", "spotlight", "poster", "reject") if any(v == t for v in paper_tiers.values())},
            "papers_with_tiers": len(paper_tiers),
        }

        # ─── Tier-derived ranking vs AI ranking correlation ─────────────
        # Build a ground-truth ranking from tiers (Oral > Spotlight > Poster > Reject)
        # Within each tier, use average reviewer score as tiebreaker
        paper_avg_score = {}
        for p in papers:
            evs = [ev["rating_value"] for ev in p.get("evaluations", []) if ev.get("rating_value")]
            paper_avg_score[p["id"]] = sum(evs) / len(evs) if evs else 0

        tier_ranked_papers = sorted(
            [pid for pid in paper_tiers if pid in a_rank],
            key=lambda pid: (TIER_ORDER[paper_tiers[pid]], -paper_avg_score.get(pid, 0)),
        )
        if len(tier_ranked_papers) >= 5:
            tier_rank_map = {pid: rank + 1 for rank, pid in enumerate(tier_ranked_papers)}
            ai_r = [a_rank[pid]["rank"] for pid in tier_ranked_papers]
            tier_r = [tier_rank_map[pid] for pid in tier_ranked_papers]
            t_sp, t_sp_p = scipy_stats.spearmanr(ai_r, tier_r)
            t_kt, t_kt_p = scipy_stats.kendalltau(ai_r, tier_r)

            tier_metrics["tier_vs_ai_correlation"] = {
                "spearman_rho": round(t_sp, 4) if not np.isnan(t_sp) else 0,
                "spearman_p_value": round(t_sp_p, 6) if not np.isnan(t_sp_p) else 1,
                "kendall_tau": round(t_kt, 4) if not np.isnan(t_kt) else 0,
                "kendall_p_value": round(t_kt_p, 6) if not np.isnan(t_kt_p) else 1,
                "papers": len(tier_ranked_papers),
            }

            # Build comparison table: tier rank vs AI rank
            tier_metrics["tier_ranking"] = [{
                "id": pid,
                "title": next((p["title"] for p in papers if p["id"] == pid), "?"),
                "tier": paper_tiers[pid],
                "tier_rank": tier_rank_map[pid],
                "avg_score": round(paper_avg_score.get(pid, 0), 2),
                "ai_rank": a_rank[pid]["rank"],
                "ai_score": a_rank[pid]["score"],
                "rank_delta": a_rank[pid]["rank"] - tier_rank_map[pid],
            } for pid in tier_ranked_papers]

    return {
        "status": "ok", "method": "pairwise_bt",
        "papers_analyzed": len(cp), "human_matches_derived": len(ch),
        "human_matches_ties_excluded": ties, "ai_matches": len(ca),
        "experts_contributing": experts_used,
        "correlation": {
            "spearman_rho": safe_round(sp), "spearman_p_value": safe_round(sp_p, 6),
            "kendall_tau": safe_round(kt), "kendall_p_value": safe_round(kt_p, 6),
            "pearson_r": safe_round(pr), "pearson_p_value": safe_round(pr_p, 6),
        },
        "interpretation": interp(safe_round(sp), safe_round(sp_p, 6), len(cp), "pairwise BT"),
        "comparison": comparison,
        "tier_metrics": tier_metrics,
    }



# ─── Convergence Analysis ──────────────────────────────────────────────────────

@router.get("/convergence")
async def get_convergence(dataset_id: str = Query(...), content_mode: Optional[str] = Query(None), steps: int = Query(20)):
    """Analyze how AI ranking correlation with HUMAN ground truth improves as more matches are added."""
    cached = await cache_get("convergence", dataset_id, content_mode or "")
    if cached:
        return cached
    result = await _compute_convergence(dataset_id, content_mode, steps)
    if result.get("status") == "ok":
        await cache_set("convergence", dataset_id, content_mode or "", result)
    return result

async def _compute_convergence(dataset_id: str, content_mode: Optional[str], steps: int):
    settings = await get_settings()
    top_k_focus = settings.get("top_k_focus", 10)

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    if not papers:
        return {"status": "no_data"}

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(content_mode))

    all_matches = await db.validation_matches.find(
        match_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1, "created_at": 1},
    ).to_list(100000)

    if len(all_matches) < 10:
        return {"status": "no_data"}

    all_matches.sort(key=lambda m: m.get("created_at", ""))

    # Derive human ground truth from expert ratings
    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                expert_ratings[name][p["id"]] = ev["rating_value"]

    human_matches = []
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                if ratings[a] != ratings[b]:
                    human_matches.append({"paper1_id": a, "paper2_id": b, "winner_id": a if ratings[a] > ratings[b] else b, "completed": True, "failed": False})

    h_ids = {m["paper1_id"] for m in human_matches} | {m["paper2_id"] for m in human_matches}
    if len(h_ids) < 3 or not human_matches:
        return {"status": "no_data", "message": "Insufficient human pairwise data"}

    # Compute graph connectivity of human preference data
    h_adj = defaultdict(set)
    for m in human_matches:
        h_adj[m["paper1_id"]].add(m["paper2_id"])
        h_adj[m["paper2_id"]].add(m["paper1_id"])
    h_visited = set()
    h_components = []
    for pid in h_ids:
        if pid in h_visited:
            continue
        queue = [pid]
        h_visited.add(pid)
        comp = []
        while queue:
            node = queue.pop(0)
            comp.append(node)
            for nb in h_adj[node]:
                if nb not in h_visited:
                    h_visited.add(nb)
                    queue.append(nb)
        h_components.append(comp)
    h_component_sizes = sorted([len(c) for c in h_components], reverse=True)
    h_largest_component = h_component_sizes[0] if h_component_sizes else 0

    # Ground truth: human ranking from expert pairwise preferences
    h_papers = [p for p in papers if p["id"] in h_ids]
    gt_lb = compute_leaderboard(h_papers, human_matches)
    gt_rank = {e["id"]: e["rank"] for e in gt_lb}
    gt_score = {e["id"]: e["score"] for e in gt_lb}
    top_k_values = [top_k_focus] if top_k_focus < len(h_ids) else [min(10, len(h_ids) - 1)]
    gt_topk = {k: set(e["id"] for e in gt_lb if e["rank"] <= k) for k in top_k_values}

    paper_ids = [p["id"] for p in papers]
    pid_set = set(paper_ids)
    n_papers = len(paper_ids)

    # Build tier-based ground truth (Oral > Spotlight > Poster > Reject)
    paper_tiers = {}
    paper_avg_score = {}
    for p in papers:
        t = norm_tier(p.get("decision"))
        if t and t in RANKABLE_TIERS:
            paper_tiers[p["id"]] = t
        evs = [ev["rating_value"] for ev in p.get("evaluations", []) if ev.get("rating_value")]
        paper_avg_score[p["id"]] = sum(evs) / len(evs) if evs else 0

    has_tiers = len(paper_tiers) >= 5
    tier_ranked_papers = []
    tier_rank_map = {}
    if has_tiers:
        tier_ranked_papers = sorted(
            paper_tiers.keys(),
            key=lambda pid: (TIER_ORDER[paper_tiers[pid]], -paper_avg_score.get(pid, 0)),
        )
        tier_rank_map = {pid: rank + 1 for rank, pid in enumerate(tier_ranked_papers)}

    def _compute_tier_corr(sub_rank):
        """Compute tier vs AI rank correlation for a given sub-ranking."""
        if not has_tiers:
            return 0, 0, 0
        common_t = [pid for pid in tier_ranked_papers if pid in sub_rank]
        if len(common_t) < 5:
            return 0, 0, 0
        ai_r = [sub_rank[pid] for pid in common_t]
        tier_r = [tier_rank_map[pid] for pid in common_t]
        t_sp, _ = scipy_stats.spearmanr(ai_r, tier_r)
        t_kt, _ = scipy_stats.kendalltau(ai_r, tier_r)
        return (round(t_sp, 4) if not np.isnan(t_sp) else 0,
                round(t_kt, 4) if not np.isnan(t_kt) else 0,
                len(common_t))

    # Build dual-dimension maps (for eLife datasets with sig_score + str_score)
    sig_map = {p["id"]: p["sig_score"] for p in papers if p.get("sig_score") is not None}
    str_map = {p["id"]: p["str_score"] for p in papers if p.get("str_score") is not None}
    has_dual = len(sig_map) >= 10 and len(str_map) >= 10

    def _compute_dual_corr(sub_lb):
        """Compute AI BT score vs significance and strength correlations."""
        if not has_dual:
            return 0, 0
        score_map = {e["id"]: e["score"] for e in sub_lb}
        common_d = [pid for pid in score_map if pid in sig_map and pid in str_map]
        if len(common_d) < 10:
            return 0, 0
        ai_s = [score_map[pid] for pid in common_d]
        sig_s = [sig_map[pid] for pid in common_d]
        str_s = [str_map[pid] for pid in common_d]
        # Check for constant input
        if len(set(ai_s)) < 2:
            return 0, 0
        sp_sig, _ = scipy_stats.spearmanr(ai_s, sig_s)
        sp_str, _ = scipy_stats.spearmanr(ai_s, str_s)
        return (round(sp_sig, 4) if not np.isnan(sp_sig) else 0,
                round(sp_str, 4) if not np.isnan(sp_str) else 0)

    # Compute max avg matches per paper
    total = len(all_matches)
    full_counts = defaultdict(int)
    for m in all_matches:
        if m["paper1_id"] in pid_set: full_counts[m["paper1_id"]] += 1
        if m["paper2_id"] in pid_set: full_counts[m["paper2_id"]] += 1
    max_avg = sum(full_counts[pid] for pid in paper_ids if full_counts[pid] > 0) / max(sum(1 for pid in paper_ids if full_counts[pid] > 0), 1)

    # ── Pre-compute cumulative avg-per-paper at every match index (O(n) once) ──
    # This eliminates the O(n*log(n)) binary search in Phase 2
    _active_set = set()
    _total_match_sum = 0
    _cum_avg = [0.0] * (total + 1)  # _cum_avg[i] = avg matches per active paper after first i matches
    _cum_active = [0] * (total + 1)
    for i, m in enumerate(all_matches):
        if m["paper1_id"] in pid_set:
            _active_set.add(m["paper1_id"])
            _total_match_sum += 1
        if m["paper2_id"] in pid_set:
            _active_set.add(m["paper2_id"])
            _total_match_sum += 1
        active = len(_active_set)
        _cum_avg[i + 1] = _total_match_sum / active if active > 0 else 0
        _cum_active[i + 1] = active

    # Generate unified set of curve sample points (match indices)
    # Phase 1: absolute match counts for the very start (every 3 matches up to 50)
    sample_indices = set()
    for n in range(3, min(51, total + 1), 3):
        sample_indices.add(n)

    # Phase 2: avg-per-paper targets — use bisect on _cum_avg instead of binary search
    import bisect
    avg_targets = []
    for t in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
        if t <= max_avg:
            avg_targets.append(t)
    for t in range(6, min(16, int(max_avg) + 1)):
        avg_targets.append(float(t))
    if max_avg > 15:
        late_steps = max(steps - 25, 10)
        late_step_size = max(1, int((max_avg - 15) / late_steps))
        for t in range(15 + late_step_size, int(max_avg) + late_step_size, late_step_size):
            avg_targets.append(float(t))
    if avg_targets and avg_targets[-1] < max_avg * 0.95:
        avg_targets.append(max_avg)

    for target_avg in avg_targets:
        # Find smallest index where _cum_avg >= target_avg using linear scan (fast on sorted data)
        idx = bisect.bisect_left(_cum_avg, target_avg, 1, total + 1)
        if idx <= total:
            sample_indices.add(idx)

    # Always include the final point
    if total > 0:
        sample_indices.add(total)

    # Sort and deduplicate
    sample_indices = sorted(sample_indices)

    curve = []

    # Baseline at 0
    curve.append({
        "matches": 0,
        "avg_matches_per_paper": 0,
        "papers_covered": 0,
        "spearman": 0, "kendall": 0, "pearson": 0,
        "tier_spearman": 0, "tier_kendall": 0,
        "sig_spearman": 0, "str_spearman": 0,
        **{f"top_{k}": round(k / len(paper_ids) * 100, 1) if paper_ids else 0 for k in top_k_values},
    })

    # Compute curve points
    for n_matches in sample_indices:
        if n_matches > total or n_matches < 1:
            continue
        if _cum_active[n_matches] < 2:
            continue

        subset = all_matches[:n_matches]
        avg_matches = round(_cum_avg[n_matches], 1)
        papers_covered = _cum_active[n_matches]

        sub_lb = compute_leaderboard(papers, subset)
        sub_rank = {e["id"]: e["rank"] for e in sub_lb}

        common = [pid for pid in paper_ids if pid in gt_rank and pid in sub_rank]
        if len(common) < 15:
            continue

        sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common], [gt_rank[p] for p in common])
        kt, _ = scipy_stats.kendalltau([sub_rank[p] for p in common], [gt_rank[p] for p in common])
        sub_score_map = {e["id"]: e["score"] for e in sub_lb}
        pr, _ = scipy_stats.pearsonr([sub_score_map.get(p, 0) for p in common], [gt_score.get(p, 0) for p in common])

        topk = {}
        for k in top_k_values:
            sub_topk = set(e["id"] for e in sub_lb if e["rank"] <= k)
            overlap = len(sub_topk & gt_topk[k])
            topk[f"top_{k}"] = round(overlap / k * 100, 1)

        t_sp, t_kt, _ = _compute_tier_corr(sub_rank)
        d_sig, d_str = _compute_dual_corr(sub_lb)
        curve.append({
            "matches": n_matches,
            "avg_matches_per_paper": avg_matches,
            "papers_covered": papers_covered,
            "spearman": round(sp, 4) if not np.isnan(sp) else 0,
            "kendall": round(kt, 4) if not np.isnan(kt) else 0,
            "pearson": round(pr, 4) if not np.isnan(pr) else 0,
            "tier_spearman": t_sp, "tier_kendall": t_kt,
            "sig_spearman": d_sig, "str_spearman": d_str,
            **{f"top_{k}": topk.get(f"top_{k}", 0) for k in top_k_values},
        })

    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "content_mode": content_mode or "extract",
        "total_matches": total,
        "total_papers": n_papers,
        "human_matches": len(human_matches),
        "human_papers": len(h_ids),
        "human_evaluators": len(expert_ratings),
        "ground_truth": "human_pairwise",
        "has_tiers": has_tiers,
        "has_dual": has_dual,
        "tier_papers": len(paper_tiers),
        "top_k_values": top_k_values,
        "curve": curve,
        "graph_connectivity": {
            "components": len(h_components),
            "largest_component": h_largest_component,
            "component_sizes": h_component_sizes[:10],
            "is_connected": len(h_components) == 1,
        },
    }



# Simple in-memory cache for convergence-all (TTL-only, no DB match-count checks)
_convergence_all_cache = {}  # dataset_id -> {"data": ..., "ts": float}
_CONV_CACHE_TTL = 900  # 15 minutes


def invalidate_dataset_cache(dataset_id: str):
    """Invalidate all caches for a dataset (call after tournament adds matches)."""
    _convergence_all_cache.pop(dataset_id, None)
    # Also invalidate the general result cache entries for this dataset
    from routers.validation_utils import _result_cache, _match_count_cache
    to_del = [k for k in _result_cache if k[1] == dataset_id]
    for k in to_del:
        del _result_cache[k]
    _match_count_cache.pop(dataset_id, None)

@router.get("/convergence-all")
async def get_convergence_all(dataset_id: str = Query(...), steps: int = Query(20)):
    """Return convergence data for ALL available modes in a single response."""
    entry = _convergence_all_cache.get(dataset_id)
    if entry and _time.time() - entry["ts"] < _CONV_CACHE_TTL:
        return entry["data"]

    # Discover modes
    mode_pipeline = [
        {"$match": {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": {"$ifNull": ["$content_mode", "none"]}, "count": {"$sum": 1}}},
    ]
    SUMMARY_TAG_LABELS = {
        "gpt_summary": "GPT-5.2", "gemini_summary": "Gemini 3 Pro",
        "opus_thinking": "Opus 4.5 Thinking", "gpt_thinking": "GPT-5.2 Thinking",
        "gemini_thinking": "Gemini 3 Thinking", "opus46": "Opus 4.6",
    }
    BASE_LABELS = {
        "none": "Extract", "extract": "Extract", "abstract": "Abstract",
        "full_pdf": "Full PDF", "ai_summary": "AI Summary",
        "abstract_plus_summary": "Abstract + Summary (Opus 4.5)",
    }
    modes = []
    async for doc in db.validation_matches.aggregate(mode_pipeline):
        cm = doc["_id"]
        if cm in ("none", None, ""):
            cm = "extract"
        if doc["count"] >= 10:
            tag = cm.split(":", 1)[1] if ":" in cm else None
            if tag:
                base_id = cm.split(":")[0]
                base_label = BASE_LABELS.get(base_id, base_id.replace("_", " + ").replace("abstract + plus", "Abstract +")).rstrip(")")
                # Strip "(Opus 4.5)" from base when adding a different tag
                base_label = base_label.split(" (")[0]
                tag_label = SUMMARY_TAG_LABELS.get(tag, tag)
                label = f"{base_label} ({tag_label})"
            else:
                label = BASE_LABELS.get(cm, cm.replace("_", " ").title())
            modes.append({"id": cm, "label": label, "matches": doc["count"]})

    if not modes:
        return {"status": "no_data"}

    # Compute convergence for all modes in parallel
    results = await asyncio.gather(*[_compute_convergence(dataset_id, m["id"], steps) for m in modes])

    by_mode = {}
    for mode_info, data in zip(modes, results):
        if data.get("status") == "ok" and data.get("curve"):
            by_mode[mode_info["id"]] = {**data, "name": mode_info["label"]}

    result = {"status": "ok", "dataset_id": dataset_id, "modes": by_mode}
    if by_mode:
        _convergence_all_cache[dataset_id] = {"data": result, "ts": _time.time()}
    return result



# ─── Results: IRT Direct Score ─────────────────────────────────────────────────

@router.get("/irt-results")
async def get_irt_results(dataset_id: str = Query(...), abstract_only: Optional[bool] = Query(None), content_mode: Optional[str] = Query(None)):
    cache_mode = content_mode or ("abstract" if abstract_only else "extract")
    cached = await cache_get("irt", dataset_id, cache_mode)
    if cached:
        return cached
    result = await _compute_irt_results(dataset_id, abstract_only, content_mode)
    if result.get("status") == "ok":
        await cache_set("irt", dataset_id, cache_mode, result)
    return result

async def _compute_irt_results(dataset_id: str, abstract_only, content_mode):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(content_mode, abstract_only))

    ai_matches = await db.validation_matches.find(
        match_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ).to_list(100000)

    if not papers or len(ai_matches) < 2:
        return {"status": "no_data"}

    # Expert params
    expert_ratings = defaultdict(list)
    paper_experts = defaultdict(list)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                expert_ratings[name].append((p["id"], ev["rating_value"]))
                paper_experts[p["id"]].append((name, ev["rating_value"]))

    expert_params = {}
    for exp, rated in expert_ratings.items():
        ratings = [r for _, r in rated]
        mean = float(np.mean(ratings))
        std = float(np.std(ratings, ddof=1)) if len(ratings) > 1 else 0.5
        adj_std = max(min(len(ratings) / 10, 1) * std + (1 - min(len(ratings) / 10, 1)) * 0.6, 0.3)
        expert_params[exp] = {"mean": mean, "adj_std": adj_std, "n": len(ratings)}

    # IRT scores
    paper_scores = {}
    paper_raw = {}
    for pid, evals in paper_experts.items():
        zs = [(r - expert_params[e]["mean"]) / expert_params[e]["adj_std"] for e, r in evals]
        paper_scores[pid] = float(np.mean(zs))
        paper_raw[pid] = float(np.mean([r for _, r in evals]))

    a_ids = {m["paper1_id"] for m in ai_matches} | {m["paper2_id"] for m in ai_matches}
    common = set(paper_scores.keys()) & a_ids
    if len(common) < 15:
        return {"status": "insufficient_data"}

    cp = [p for p in papers if p["id"] in common]
    ca = [m for m in ai_matches if m["paper1_id"] in common and m["paper2_id"] in common]

    irt_sorted = sorted(common, key=lambda pid: -paper_scores[pid])
    irt_rank = {pid: i + 1 for i, pid in enumerate(irt_sorted)}
    raw_sorted = sorted(common, key=lambda pid: -paper_raw.get(pid, 0))
    raw_rank = {pid: i + 1 for i, pid in enumerate(raw_sorted)}

    a_lb = compute_leaderboard(cp, ca)
    a_lookup = {e["id"]: e for e in a_lb}

    ids = sorted(common)
    ir = [irt_rank[pid] for pid in ids]
    ar = [a_lookup[pid]["rank"] for pid in ids]
    rr = [raw_rank[pid] for pid in ids]

    sp_irt, sp_irt_p = scipy_stats.spearmanr(ir, ar)
    kt_irt, kt_irt_p = scipy_stats.kendalltau(ir, ar)
    pr_irt, pr_irt_p = scipy_stats.pearsonr([paper_scores[pid] for pid in ids], [a_lookup[pid]["score"] for pid in ids])
    sp_raw, sp_raw_p = scipy_stats.spearmanr(rr, ar)

    distinct_raw = len(set(round(paper_raw[pid], 2) for pid in ids))
    distinct_irt = len(set(round(paper_scores[pid], 3) for pid in ids))

    comparison = sorted([{
        "id": pid, "title": next(p["title"] for p in cp if p["id"] == pid),
        "irt_score": round(paper_scores[pid], 3), "raw_mean": round(paper_raw.get(pid, 0), 1),
        "n_ratings": len(paper_experts.get(pid, [])),
        "irt_rank": irt_rank[pid], "ai_rank": a_lookup[pid]["rank"],
        "ai_score": a_lookup[pid]["score"], "ai_win_rate": a_lookup[pid]["win_rate"],
        "rank_delta": a_lookup[pid]["rank"] - irt_rank[pid],
    } for pid in common], key=lambda x: x["irt_rank"])

    return {
        "status": "ok", "method": "irt_direct_score",
        "papers_analyzed": len(cp), "experts_analyzed": len(expert_params),
        "ai_matches": len(ca),
        "correlation": {
            "irt_score_vs_ai": {"spearman_rho": round(sp_irt, 4), "spearman_p": round(sp_irt_p, 6), "kendall_tau": round(kt_irt, 4), "kendall_p": round(kt_irt_p, 6), "pearson_r": round(pr_irt, 4), "pearson_p": round(pr_irt_p, 6)},
            "raw_avg_vs_ai": {"spearman_rho": round(sp_raw, 4), "spearman_p": round(sp_raw_p, 6)},
        },
        "improvement": {"raw_spearman": round(sp_raw, 4), "irt_spearman": round(sp_irt, 4), "delta": round(sp_irt - sp_raw, 4), "distinct_scores_raw": distinct_raw, "distinct_scores_irt": distinct_irt},
        "interpretation": interp(sp_irt, sp_irt_p, len(cp), "IRT score"),
        "comparison": comparison,
    }


# ─── Agreement Analysis ────────────────────────────────────────────────────────

@router.get("/agreement-analysis")
async def get_agreement(dataset_id: str = Query(...), abstract_only: Optional[bool] = Query(None), content_mode: Optional[str] = Query(None)):
    cache_mode = content_mode or ("abstract" if abstract_only else "extract")
    cached = await cache_get("agreement", dataset_id, cache_mode)
    if cached:
        return cached
    result = await _compute_agreement(dataset_id, abstract_only, content_mode)
    if result.get("status") == "ok":
        await cache_set("agreement", dataset_id, cache_mode, result)
    return result

async def _compute_agreement(dataset_id: str, abstract_only, content_mode):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(content_mode, abstract_only))

    ai_matches = await db.validation_matches.find(
        match_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)

    if not papers:
        return {"status": "no_data"}

    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name: expert_ratings[name][p["id"]] = ev["rating_value"]

    # AI pair winners — use majority vote when multiple judges evaluated the same pair
    _ai_pair_votes = defaultdict(list)
    for m in ai_matches:
        if m.get("winner_id"):
            _ai_pair_votes[tuple(sorted([m["paper1_id"], m["paper2_id"]]))].append(m["winner_id"])
    ai_pair = {}
    for pair, votes in _ai_pair_votes.items():
        c = Counter(votes)
        ai_pair[pair] = c.most_common(1)[0][0]

    pair_votes = defaultdict(list)
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                ra, rb = ratings[a], ratings[b]
                if ra != rb:
                    pair_votes[tuple(sorted([a, b]))].append((exp, a if ra > rb else b))

    ee_agree = ee_total = 0
    for pair, votes in pair_votes.items():
        if pair not in ai_pair: continue
        if len(votes) < 2: continue
        winners = [w for _, w in votes]
        for i in range(len(winners)):
            for j in range(i + 1, len(winners)):
                ee_total += 1
                if winners[i] == winners[j]: ee_agree += 1

    # AI vs individual expert
    ae_agree = ae_total = 0
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                if ratings[a] == ratings[b]: continue
                pair = tuple(sorted([a, b]))
                if pair not in ai_pair: continue
                ae_total += 1
                if (a if ratings[a] > ratings[b] else b) == ai_pair[pair]:
                    ae_agree += 1

    # AI vs majority
    pair_majority = {}
    for pair, votes in pair_votes.items():
        if len(votes) < 2: continue
        c = Counter(w for _, w in votes)
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2: pair_majority[pair] = best

    overlap = set(pair_majority.keys()) & set(ai_pair.keys())
    maj_agree = sum(1 for p in overlap if ai_pair[p] == pair_majority[p])

    ee_rate = round(ee_agree / max(ee_total, 1) * 100, 1)
    ae_rate = round(ae_agree / max(ae_total, 1) * 100, 1)
    maj_rate = round(maj_agree / max(len(overlap), 1) * 100, 1)

    interp = (
        f"Experts agree with each other {ee_rate}% of the time ({ee_agree}/{ee_total} pairs). "
        f"AI agrees with individual experts {ae_rate}% ({ae_agree}/{ae_total} pairs). "
    )
    if ae_rate > ee_rate:
        interp += "AI-expert agreement exceeds expert-expert agreement."
    elif ae_rate > ee_rate * 0.85:
        interp += f"AI-expert agreement ({ae_rate}%) approaches expert-expert agreement ({ee_rate}%), suggesting AI performs comparably to a human reviewer."
    else:
        interp += f"AI-expert agreement ({ae_rate}%) is below expert-expert agreement ({ee_rate}%)."

    return {
        "status": "ok",
        "expert_expert": {"agree": ee_agree, "total": ee_total, "rate": ee_rate},
        "ai_expert": {"agree": ae_agree, "total": ae_total, "rate": ae_rate},
        "ai_majority": {"agree": maj_agree, "total": len(overlap), "rate": maj_rate},
        "interpretation": interp,
    }



# ─── Head-to-Head Cross-Mode Comparison ─────────────────────────────────────────

@router.get("/cross-mode-agreement")
async def get_cross_mode_agreement(dataset_id: str = Query(...)):
    """Compute AI-expert agreement on the EXACT SAME set of paper pairs across all available content modes."""
    cached = await cache_get("cross-mode", dataset_id, "")
    if cached:
        return cached
    result = await _compute_cross_mode_agreement(dataset_id)
    if result.get("status") == "ok":
        await cache_set("cross-mode", dataset_id, "", result)
    return result

async def _compute_cross_mode_agreement(dataset_id: str):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    if not papers:
        return {"status": "no_data"}

    # Build expert ratings
    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                expert_ratings[name][p["id"]] = ev["rating_value"]

    # Build expert pair preferences (which paper the expert thinks is better)
    expert_pair_prefs = {}  # pair_key -> [(expert, winner_id)]
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                if ratings[a] == ratings[b]:
                    continue
                key = tuple(sorted([a, b]))
                if key not in expert_pair_prefs:
                    expert_pair_prefs[key] = []
                expert_pair_prefs[key].append((exp, a if ratings[a] > ratings[b] else b))

    # Expert majority vote
    pair_majority = {}
    for pair, votes in expert_pair_prefs.items():
        if len(votes) < 2:
            continue
        c = Counter(w for _, w in votes)
        best, n = c.most_common(1)[0]
        if n > len(votes) / 2:
            pair_majority[pair] = best

    # Fetch AI winners per content mode (and per-model data)
    # Dynamically discover all modes with data instead of a hardcoded list
    mode_pipeline = [
        {"$match": {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}},
        {"$group": {"_id": {"$ifNull": ["$content_mode", "extract"]}, "count": {"$sum": 1}}},
    ]
    modes = []
    async for doc in db.validation_matches.aggregate(mode_pipeline):
        cm = doc["_id"]
        # Normalize legacy entries without content_mode
        if cm in ("none", None, ""):
            cm = "extract"
        modes.append(cm)

    mode_ai_pairs = {}
    mode_model_pairs = {}  # mode -> model_key -> {pair: winner}
    for mode in modes:
        match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
        match_filter.update(build_content_mode_filter(mode))
        matches = await db.validation_matches.find(
            match_filter,
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
        ).to_list(100000)
        if matches:
            ai_map = {}
            model_maps = defaultdict(dict)
            for m in matches:
                pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
                ai_map[pair] = m["winner_id"]
                mu = m.get("model_used", {})
                mk = f"{mu.get('provider', '')}:{mu.get('model', '')}" if mu else ""
                if mk:
                    model_maps[mk][pair] = m["winner_id"]
            mode_ai_pairs[mode] = ai_map
            mode_model_pairs[mode] = dict(model_maps)

    available_modes = list(mode_ai_pairs.keys())
    if len(available_modes) < 2:
        return {"status": "insufficient_modes", "available": available_modes}

    # Find common pairs across modes. Use pairwise overlap between modes
    # rather than requiring all modes to share the same pairs.
    # Include any mode with at least 50 pairs.
    core_modes = [m for m in available_modes if len(mode_ai_pairs[m]) >= 50]
    overlay_modes = [m for m in available_modes if m not in core_modes]

    if len(core_modes) < 2:
        return {"status": "insufficient_modes", "available": available_modes}

    # Find the pair of core modes with the most overlap to use as the comparison base
    best_overlap = set()
    best_pair = (core_modes[0], core_modes[1])
    for i in range(len(core_modes)):
        for j in range(i + 1, len(core_modes)):
            overlap = set(mode_ai_pairs[core_modes[i]].keys()) & set(mode_ai_pairs[core_modes[j]].keys())
            if len(overlap) > len(best_overlap):
                best_overlap = overlap
                best_pair = (core_modes[i], core_modes[j])

    # Use the best overlap as the common pairs base, then include other modes that have enough of these pairs
    common_pairs = best_overlap
    comparison_modes = list(best_pair)
    for m in core_modes:
        if m not in comparison_modes:
            m_overlap = set(mode_ai_pairs[m].keys()) & common_pairs
            if len(m_overlap) >= min(50, len(common_pairs) * 0.3):
                comparison_modes.append(m)
                common_pairs = common_pairs & set(mode_ai_pairs[m].keys())

    if len(common_pairs) < 20:
        return {"status": "insufficient_overlap", "available": available_modes, "best_overlap": len(best_overlap), "best_modes": list(best_pair)}

    core_modes = comparison_modes

    # For each mode, compute agreement on the common pairs
    def _compute_agreement(ai_map, pair_set):
        ae_agree = ae_total = 0
        for exp, ratings in expert_ratings.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    if ratings[a] == ratings[b]:
                        continue
                    pair = tuple(sorted([a, b]))
                    if pair not in pair_set or pair not in ai_map:
                        continue
                    ae_total += 1
                    if (a if ratings[a] > ratings[b] else b) == ai_map[pair]:
                        ae_agree += 1

        maj_overlap = pair_set & set(pair_majority.keys()) & set(ai_map.keys())
        maj_agree = sum(1 for p in maj_overlap if ai_map[p] == pair_majority[p])

        return {
            "ai_expert": {"agree": ae_agree, "total": ae_total, "rate": round(ae_agree / max(ae_total, 1) * 100, 1)},
            "ai_majority": {"agree": maj_agree, "total": len(maj_overlap), "rate": round(maj_agree / max(len(maj_overlap), 1) * 100, 1)},
        }

    # Expert-expert agreement on common pairs only
    ee_agree = ee_total = 0
    for pair in common_pairs:
        votes = expert_pair_prefs.get(pair, [])
        if len(votes) < 2:
            continue
        winners = [w for _, w in votes]
        for i in range(len(winners)):
            for j in range(i + 1, len(winners)):
                ee_total += 1
                if winners[i] == winners[j]:
                    ee_agree += 1

    results = {}
    for mode in available_modes:
        # Core modes use common_pairs; overlay modes use their own intersection with common_pairs
        if mode in core_modes:
            results[mode] = _compute_agreement(mode_ai_pairs[mode], common_pairs)
        else:
            # Overlay: compute on the subset of common_pairs this mode has data for
            overlay_pairs = common_pairs & set(mode_ai_pairs[mode].keys())
            if overlay_pairs:
                stats = _compute_agreement(mode_ai_pairs[mode], overlay_pairs)
                stats["pairs_evaluated"] = len(overlay_pairs)
                stats["pairs_total"] = len(common_pairs)
                results[mode] = stats

    # Per-model agreement breakdown
    per_model = {}
    all_model_keys = set()
    for mode in available_modes:
        for mk in mode_model_pairs.get(mode, {}):
            all_model_keys.add(mk)

    for mode in available_modes:
        pair_set = common_pairs if mode in core_modes else (common_pairs & set(mode_ai_pairs.get(mode, {}).keys()))
        per_model[mode] = {}
        for mk in all_model_keys:
            model_map = mode_model_pairs.get(mode, {}).get(mk, {})
            if model_map:
                stats = _compute_agreement(model_map, pair_set)
                per_model[mode][mk] = stats

    # AI majority (3-model vote) vs expert majority — needs pairs with all 3 models
    ai_majority_vs_expert = {}
    for mode in available_modes:
        model_maps = mode_model_pairs.get(mode, {})
        if len(model_maps) < 2:
            continue
        mk_list = list(model_maps.keys())
        # Find pairs evaluated by all models in this mode
        all_model_pairs = set.intersection(*[set(model_maps[mk].keys()) for mk in mk_list]) & common_pairs
        if not all_model_pairs:
            continue
        # Compute 3-model majority vote
        ai_maj_map = {}
        for pair in all_model_pairs:
            votes = Counter(model_maps[mk][pair] for mk in mk_list if pair in model_maps[mk])
            if votes:
                best, n = votes.most_common(1)[0]
                ai_maj_map[pair] = best
        # Agreement with expert majority
        maj_overlap = set(ai_maj_map.keys()) & set(pair_majority.keys())
        maj_agree = sum(1 for p in maj_overlap if ai_maj_map[p] == pair_majority[p])
        # Agreement with individual experts
        ae_agree = ae_total = 0
        for exp, ratings in expert_ratings.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    if ratings[a] == ratings[b]:
                        continue
                    pair = tuple(sorted([a, b]))
                    if pair not in all_model_pairs or pair not in ai_maj_map:
                        continue
                    ae_total += 1
                    if (a if ratings[a] > ratings[b] else b) == ai_maj_map[pair]:
                        ae_agree += 1
        ai_majority_vs_expert[mode] = {
            "pairs_with_all_models": len(all_model_pairs),
            "ai_majority_vs_expert": {"agree": ae_agree, "total": ae_total, "rate": round(ae_agree / max(ae_total, 1) * 100, 1)},
            "ai_majority_vs_expert_majority": {"agree": maj_agree, "total": len(maj_overlap), "rate": round(maj_agree / max(len(maj_overlap), 1) * 100, 1)},
        }

    # Compute pairwise mode disagreement stats — only between core modes
    mode_disagreements = {}
    for i, m1 in enumerate(core_modes):
        for m2 in core_modes[i + 1:]:
            diff_count = sum(1 for p in common_pairs if mode_ai_pairs[m1][p] != mode_ai_pairs[m2][p])
            mode_disagreements[f"{m1}_vs_{m2}"] = {
                "differ": diff_count,
                "agree": len(common_pairs) - diff_count,
                "total": len(common_pairs),
                "differ_pct": round(diff_count / max(len(common_pairs), 1) * 100, 1),
            }

    # modes_compared = modes that have results
    modes_with_results = [m for m in available_modes if m in results]

    # Score gap breakdown: AI agreement rate by expert score difference
    # Only meaningful for datasets with numeric scores (1-5 or similar)
    score_gap = {}
    paper_lookup = {p["id"]: p for p in papers}
    for mode in modes_with_results:
        ai_map = mode_ai_pairs.get(mode, {})
        pair_set = common_pairs if mode in core_modes else (common_pairs & set(ai_map.keys()))
        buckets = {}  # gap_label -> {agree, total}
        for exp, ratings in expert_ratings.items():
            pids = list(ratings.keys())
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    ra, rb = ratings[a], ratings[b]
                    if ra == rb:
                        continue
                    pair = tuple(sorted([a, b]))
                    if pair not in pair_set or pair not in ai_map:
                        continue
                    gap = abs(ra - rb)
                    if gap <= 1:
                        label = "small"
                    elif gap <= 2:
                        label = "medium"
                    else:
                        label = "large"
                    if label not in buckets:
                        buckets[label] = {"agree": 0, "total": 0}
                    buckets[label]["total"] += 1
                    expert_winner = a if ra > rb else b
                    if ai_map[pair] == expert_winner:
                        buckets[label]["agree"] += 1
        for label in buckets:
            buckets[label]["rate"] = round(buckets[label]["agree"] / max(buckets[label]["total"], 1) * 100, 1)
        if buckets:
            score_gap[mode] = buckets

    # ─── Acceptance Tier Analysis ───────────────────────────────────────
    paper_tiers = {}
    for p in papers:
        tier = norm_tier(p.get("decision"))
        if tier and tier in RANKABLE_TIERS:
            paper_tiers[p["id"]] = tier

    tier_analysis = {}
    if len(paper_tiers) >= 5:
        for mode in modes_with_results:
            ai_map = mode_ai_pairs.get(mode, {})
            tier_paper_ids = set(paper_tiers.keys())

            # Fetch matches for this mode to build BT ranking
            mode_match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
            mode_match_filter.update(build_content_mode_filter(mode))
            mode_matches_raw = await db.validation_matches.find(
                mode_match_filter,
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
            ).to_list(100000)
            tier_matches = [m for m in mode_matches_raw if m["paper1_id"] in tier_paper_ids and m["paper2_id"] in tier_paper_ids]

            if len(tier_matches) < 5:
                continue

            tier_papers_list = [p for p in papers if p["id"] in tier_paper_ids]
            ai_lb = compute_leaderboard(tier_papers_list, tier_matches)
            ai_rank_map = {e["id"]: e["rank"] for e in ai_lb}

            # Tier pair accuracy: for each pair of papers in different tiers,
            # does the AI rank the higher-tier paper higher?
            tier_correct = 0
            tier_total = 0
            tier_pair_breakdown = {}  # e.g., "oral_vs_poster": {correct, total}
            for pid_a in paper_tiers:
                for pid_b in paper_tiers:
                    if pid_a >= pid_b:
                        continue
                    tier_a = paper_tiers[pid_a]
                    tier_b = paper_tiers[pid_b]
                    if TIER_ORDER[tier_a] == TIER_ORDER[tier_b]:
                        continue  # Same tier, skip
                    if pid_a not in ai_rank_map or pid_b not in ai_rank_map:
                        continue
                    tier_total += 1
                    # Higher tier = lower TIER_ORDER number = should have lower rank number
                    higher_tier_pid = pid_a if TIER_ORDER[tier_a] < TIER_ORDER[tier_b] else pid_b
                    lower_tier_pid = pid_b if higher_tier_pid == pid_a else pid_a
                    if ai_rank_map[higher_tier_pid] < ai_rank_map[lower_tier_pid]:
                        tier_correct += 1

                    # Breakdown by tier pair
                    tiers_sorted = sorted([tier_a, tier_b], key=lambda t: TIER_ORDER[t])
                    pair_key = f"{tiers_sorted[0]}_vs_{tiers_sorted[1]}"
                    if pair_key not in tier_pair_breakdown:
                        tier_pair_breakdown[pair_key] = {"correct": 0, "total": 0}
                    tier_pair_breakdown[pair_key]["total"] += 1
                    if ai_rank_map[higher_tier_pid] < ai_rank_map[lower_tier_pid]:
                        tier_pair_breakdown[pair_key]["correct"] += 1

            for k in tier_pair_breakdown:
                b = tier_pair_breakdown[k]
                b["accuracy"] = round(b["correct"] / max(b["total"], 1) * 100, 1)

            # Top-K precision: what fraction of AI's top-K are Oral or Spotlight?
            top_tier_set = {pid for pid, t in paper_tiers.items() if t in ("oral", "spotlight")}
            ai_sorted = sorted([e for e in ai_lb if e["id"] in tier_paper_ids], key=lambda e: e["rank"])
            top_k_sizes = [5, 10]
            top_k_precision = {}
            for k in top_k_sizes:
                top_k_ids = {e["id"] for e in ai_sorted[:k]}
                hits = len(top_k_ids & top_tier_set)
                top_k_precision[f"top_{k}"] = {"hits": hits, "total": min(k, len(ai_sorted)), "precision": round(hits / min(k, len(ai_sorted)) * 100, 1)}

            # Tier distribution
            tier_dist = {}
            for t in paper_tiers.values():
                tier_dist[t] = tier_dist.get(t, 0) + 1

            tier_analysis[mode] = {
                "overall_accuracy": round(tier_correct / max(tier_total, 1) * 100, 1),
                "correct": tier_correct,
                "total_pairs": tier_total,
                "by_tier_pair": tier_pair_breakdown,
                "top_k_precision": top_k_precision,
                "tier_distribution": tier_dist,
                "papers_with_tiers": len(paper_tiers),
            }

    return {
        "status": "ok",
        "common_pairs": len(common_pairs),
        "modes_compared": modes_with_results,
        "expert_expert": {"agree": ee_agree, "total": ee_total, "rate": round(ee_agree / max(ee_total, 1) * 100, 1)},
        "by_mode": results,
        "per_model": per_model,
        "ai_majority_vs_expert": ai_majority_vs_expert,
        "mode_disagreements": mode_disagreements,
        "score_gap": score_gap,
        "tier_analysis": tier_analysis if tier_analysis else None,
    }




# ─── AI Impact Summary Generation ────────────────────────────────────────────

class GenerateSummariesRequest(BaseModel):
    dataset_id: str
    parallel: int = 5
    model_provider: str = "anthropic"
    model_name: str = "claude-opus-4-5-20251101"
    extra_params: dict = {}


@router.post("/generate-impact-summaries", dependencies=[Depends(verify_admin)])
async def generate_impact_summaries(body: GenerateSummariesRequest):
    """Generate AI impact assessments for all papers in a dataset using their full text."""
    from services.llm import generate_precomparison_impact_summary

    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    papers = await db.validation_papers.find({"dataset_id": body.dataset_id}, {"_id": 0}).to_list(5000)
    if not papers:
        return {"status": "error", "message": "No papers found."}

    # Find papers missing summaries
    missing = [p for p in papers if not p.get("ai_impact_summary")]
    if not missing:
        has_summary = sum(1 for p in papers if p.get("ai_impact_summary"))
        return {"status": "complete", "message": f"All {has_summary} papers already have impact summaries.", "total": len(papers), "missing": 0}

    model_info = {"provider": body.model_provider, "model": body.model_name}
    if body.extra_params:
        model_info["extra_params"] = body.extra_params
    asyncio.create_task(_generate_summaries(body.dataset_id, missing, model_info, min(max(body.parallel, 1), 15)))
    return {"status": "started", "dataset_id": body.dataset_id, "total_papers": len(papers), "missing": len(missing), "model": model_info}


async def _generate_summaries(dataset_id: str, papers: list, model_info: dict, parallel: int):
    from services.llm import generate_precomparison_impact_summary

    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": len(papers), "current_pair": "Generating summaries...", "started_at": _time.time()})

    completed = 0
    try:
        for i in range(0, len(papers), parallel):
            batch = papers[i:i + parallel]
            state["current_pair"] = f"Summary batch {i // parallel + 1}/{(len(papers) + parallel - 1) // parallel}"

            tasks = [generate_precomparison_impact_summary(p, model_override=model_info) for p in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for paper, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error(f"Summary failed for {paper.get('title', '')[:50]}: {result}")
                elif result and result.get("summary"):
                    await db.validation_papers.update_one(
                        {"dataset_id": dataset_id, "id": paper["id"]},
                        {"$set": {
                            "ai_impact_summary": result["summary"],
                            "ai_impact_summary_model": result["model_used"],
                            "ai_impact_summary_words": result.get("word_count", 0),
                        }},
                    )
                    completed += 1
                state["completed_matches"] = completed
            await asyncio.sleep(0.5)

        logger.info(f"Impact summaries [{dataset_id}]: {completed}/{len(papers)} generated")
    except Exception as e:
        logger.error(f"Impact summary generation [{dataset_id}] error: {e}")
    finally:
        state["running"] = False


@router.get("/impact-summary-status")
async def get_impact_summary_status(dataset_id: str = Query(...)):
    """Check how many papers have AI impact summaries."""
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0, "id": 1, "title": 1, "ai_impact_summary": 1, "ai_impact_summary_model": 1, "ai_impact_summary_words": 1}).to_list(5000)
    with_summary = [p for p in papers if p.get("ai_impact_summary")]
    avg_words = round(sum(p.get("ai_impact_summary_words", 0) for p in with_summary) / max(len(with_summary), 1))
    return {
        "total_papers": len(papers),
        "with_summary": len(with_summary),
        "without_summary": len(papers) - len(with_summary),
        "avg_words": avg_words,
        "model": with_summary[0].get("ai_impact_summary_model") if with_summary else None,
    }


@router.get("/dual-dimension-results")
async def get_dual_dimension_results(dataset_id: str = Query(...), content_mode: Optional[str] = Query(None)):
    """Compute AI ranking correlation against BOTH significance and strength scores (for eLife datasets)."""
    cached = await cache_get("dual-dim", dataset_id, content_mode or "")
    if cached:
        return cached
    result = await _compute_dual_dimension_results(dataset_id, content_mode)
    if result.get("status") == "ok":
        await cache_set("dual-dim", dataset_id, content_mode or "", result)
    return result

async def _compute_dual_dimension_results(dataset_id: str, content_mode: Optional[str]):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    # Check that papers have dual scores
    has_dual = [p for p in papers if p.get("sig_score") is not None and p.get("str_score") is not None]
    if not has_dual:
        return {"status": "no_dual_scores", "message": "Papers don't have separate significance/strength scores"}

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(content_mode))

    ai_matches = await db.validation_matches.find(
        match_filter,
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
    ).to_list(100000)

    if len(ai_matches) < 10:
        return {"status": "insufficient_data"}

    a_ids = {m["paper1_id"] for m in ai_matches} | {m["paper2_id"] for m in ai_matches}
    cp = [p for p in has_dual if p["id"] in a_ids]
    ca = [m for m in ai_matches if m["paper1_id"] in a_ids and m["paper2_id"] in a_ids]

    if len(cp) < 10:
        return {"status": "insufficient_data"}

    # Compute AI BT ranking
    a_lb = compute_leaderboard(cp, ca)
    a_rank = {e["id"]: e for e in a_lb}

    # Build score maps
    sig_scores = {p["id"]: p["sig_score"] for p in cp}
    str_scores = {p["id"]: p["str_score"] for p in cp}
    pids = sorted(a_rank.keys())

    ai_bt = [a_rank[pid]["score"] for pid in pids]
    sig_vals = [sig_scores[pid] for pid in pids]
    str_vals = [str_scores[pid] for pid in pids]

    _safe = lambda v: safe_round(v, 10)  # reuse shared safe_round

    # Correlations against significance
    sp_sig, sp_sig_p = scipy_stats.spearmanr(ai_bt, sig_vals)
    kt_sig, kt_sig_p = scipy_stats.kendalltau(ai_bt, sig_vals)
    pr_sig, pr_sig_p = scipy_stats.pearsonr(ai_bt, sig_vals)

    # Correlations against strength
    sp_str, sp_str_p = scipy_stats.spearmanr(ai_bt, str_vals)
    kt_str, kt_str_p = scipy_stats.kendalltau(ai_bt, str_vals)
    pr_str, pr_str_p = scipy_stats.pearsonr(ai_bt, str_vals)

    SIG_LABELS = {5: "landmark", 4: "fundamental", 3: "important", 2: "valuable", 1: "useful"}
    STR_LABELS = {6: "exceptional", 5: "compelling", 4: "convincing", 3: "solid", 2: "incomplete", 1: "inadequate"}

    comparison = sorted([{
        "id": pid,
        "title": next((p["title"] for p in cp if p["id"] == pid), "?"),
        "ai_rank": a_rank[pid]["rank"],
        "ai_score": a_rank[pid]["score"],
        "sig_score": sig_scores[pid],
        "sig_label": SIG_LABELS.get(sig_scores[pid], "?"),
        "str_score": str_scores[pid],
        "str_label": STR_LABELS.get(str_scores[pid], "?"),
    } for pid in pids], key=lambda x: x["ai_rank"])

    return {
        "status": "ok",
        "papers": len(cp),
        "ai_matches": len(ca),
        "significance_correlation": {
            "spearman_rho": round(_safe(sp_sig), 4),
            "spearman_p": round(_safe(sp_sig_p), 6),
            "kendall_tau": round(_safe(kt_sig), 4),
            "kendall_p": round(_safe(kt_sig_p), 6),
            "pearson_r": round(_safe(pr_sig), 4),
            "pearson_p": round(_safe(pr_sig_p), 6),
        },
        "strength_correlation": {
            "spearman_rho": round(_safe(sp_str), 4),
            "spearman_p": round(_safe(sp_str_p), 6),
            "kendall_tau": round(_safe(kt_str), 4),
            "kendall_p": round(_safe(kt_str_p), 6),
            "pearson_r": round(_safe(pr_str), 4),
            "pearson_p": round(_safe(pr_str_p), 6),
        },
        "comparison": comparison,
    }




@router.get("/paper-summaries")
async def get_paper_summaries(dataset_id: str = Query(...)):
    """Get AI impact summaries for all papers in a dataset."""
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "ai_impact_summary": 1, "ai_impact_summary_model": 1, "ai_impact_summary_words": 1},
    ).to_list(5000)
    result = []
    for p in papers:
        result.append({
            "id": p["id"],
            "title": p.get("title", ""),
            "abstract": p.get("abstract", "")[:500],
            "has_summary": bool(p.get("ai_impact_summary")),
            "summary": p.get("ai_impact_summary", ""),
            "summary_model": p.get("ai_impact_summary_model", {}),
            "summary_words": p.get("ai_impact_summary_words", 0),
        })
    return {"papers": sorted(result, key=lambda x: x["title"]), "total": len(result), "with_summary": sum(1 for p in result if p["has_summary"])}



# ─── Summarizer Comparison (Pairwise A/B Test) ─────────────────────────────

class SummarizerComparisonRequest(BaseModel):
    num_pairs: int = 200
    parallel: int = 8
    datasets: list = []  # empty = all ICLR + eLife datasets


@router.post("/summarizer-comparison/run", dependencies=[Depends(verify_admin)])
async def run_summarizer_comparison(body: SummarizerComparisonRequest):
    """Run pairwise A/B test: Opus 4.5 vs Opus 4.6 summaries across multiple datasets."""
    # Find all datasets with both summary versions
    target_ds = body.datasets or []
    if not target_ds:
        async for d in db.validation_datasets.find({}, {"_id": 0, "dataset_id": 1}):
            target_ds.append(d["dataset_id"])

    # Collect eligible pairs: papers with Opus 4.5 summaries AND clear human ground truth
    all_pairs = []
    _TIER_ORDER_EXT = {**TIER_ORDER, "short paper": 2}  # extend with MIDL-style tiers

    for ds_id in target_ds:
        papers = await db.validation_papers.find(
            {"dataset_id": ds_id, "ai_impact_summary_claude": {"$ne": None}},
            {"_id": 0},
        ).to_list(5000)
        if len(papers) < 2:
            continue

        paper_map = {p["id"]: p for p in papers}
        pids = list(paper_map.keys())

        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                p1, p2 = paper_map[pids[i]], paper_map[pids[j]]

                # Ground truth 1: Committee/tier decision (strongest)
                t1, t2 = norm_tier(p1.get("decision")), norm_tier(p2.get("decision"))
                has_tier_diff = t1 and t2 and t1 != t2 and _TIER_ORDER_EXT.get(t1, 99) != 99 and _TIER_ORDER_EXT.get(t2, 99) != 99

                # Ground truth 2: Reviewer score majority (need clear gap with multiple reviewers)
                s1, s2 = p1.get("h1_avg_rating", 0), p2.get("h1_avg_rating", 0)
                score_gap = abs(s1 - s2)
                n1, n2 = p1.get("h1_rating_count", 0), p2.get("h1_rating_count", 0)
                has_reviewer_majority = score_gap >= 0.5 and min(n1, n2) >= 2

                # Ground truth 3: eLife significance label difference
                sig1, sig2 = p1.get("sig_score"), p2.get("sig_score")
                has_sig_diff = sig1 is not None and sig2 is not None and sig1 != sig2

                # Require at least one clear ground truth signal
                if not (has_tier_diff or has_reviewer_majority or has_sig_diff):
                    continue

                # Determine human winner
                if has_tier_diff:
                    human_winner_id = p1["id"] if _TIER_ORDER_EXT[t1] < _TIER_ORDER_EXT[t2] else p2["id"]
                    ground_truth = "committee"
                elif has_reviewer_majority:
                    human_winner_id = p1["id"] if s1 > s2 else p2["id"]
                    ground_truth = "reviewer_majority"
                else:
                    human_winner_id = p1["id"] if sig1 > sig2 else p2["id"]
                    ground_truth = "editorial_assessment"

                all_pairs.append({
                    "dataset_id": ds_id,
                    "paper1_id": p1["id"], "paper2_id": p2["id"],
                    "human_winner_id": human_winner_id,
                    "score_gap": score_gap,
                    "has_tier_diff": has_tier_diff,
                    "ground_truth": ground_truth,
                })

    if not all_pairs:
        return {"status": "error", "message": "No eligible pairs found. Need datasets with Opus 4.5 summaries."}

    # Balance across datasets: take proportional samples from each
    from collections import defaultdict
    by_dataset = defaultdict(list)
    for p in all_pairs:
        by_dataset[p["dataset_id"]].append(p)
    
    # Shuffle within each dataset, then round-robin
    # Filter out already-completed pairs BEFORE selecting
    existing = set()
    async for doc in db.summarizer_comparisons.find({}, {"_id": 0, "paper1_id": 1, "paper2_id": 1}):
        existing.add((doc["paper1_id"], doc["paper2_id"]))
        existing.add((doc["paper2_id"], doc["paper1_id"]))

    by_dataset = defaultdict(list)
    for p in all_pairs:
        if (p["paper1_id"], p["paper2_id"]) not in existing:
            by_dataset[p["dataset_id"]].append(p)

    import random as _rnd
    for ds_pairs in by_dataset.values():
        _rnd.shuffle(ds_pairs)
    
    # Round-robin across datasets
    selected = []
    ds_keys = sorted(by_dataset.keys())
    if not ds_keys:
        return {"status": "no_new_pairs", "total_eligible": len(all_pairs), "already_done": len(existing) // 2}
    per_ds = max(1, body.num_pairs // len(ds_keys))
    for ds in ds_keys:
        selected.extend(by_dataset[ds][:per_ds])
    remaining = body.num_pairs - len(selected)
    if remaining > 0:
        used = set((p["paper1_id"], p["paper2_id"]) for p in selected)
        leftovers = [p for ds_pairs in by_dataset.values() for p in ds_pairs if (p["paper1_id"], p["paper2_id"]) not in used]
        _rnd.shuffle(leftovers)
        selected.extend(leftovers[:remaining])

    asyncio.create_task(_run_summarizer_comparison(selected, body.parallel))
    return {
        "status": "started",
        "total_eligible": len(all_pairs),
        "selected": len(selected),
        "new_to_run": len(selected),
        "already_done": len(existing) // 2,
        "datasets": list(set(p["dataset_id"] for p in selected)),
    }


async def _run_summarizer_comparison(pairs: list, parallel: int):
    """Background: Phase 1 = generate missing Opus 4.6 summaries in parallel, Phase 2 = run comparisons."""
    global _summarizer_comparison_running, _summarizer_comparison_cancel
    _summarizer_comparison_running = True
    _summarizer_comparison_cancel = False
    from services.llm import compare_papers, generate_precomparison_impact_summary

    # Phase 1: Pre-generate all missing Opus 4.6 summaries in parallel
    paper_ids_needed = set()
    for pair in pairs:
        paper_ids_needed.add((pair["dataset_id"], pair["paper1_id"]))
        paper_ids_needed.add((pair["dataset_id"], pair["paper2_id"]))

    sem_gen = asyncio.Semaphore(parallel)
    summaries_generated = 0

    async def _gen_one(ds_id, paper_id):
        nonlocal summaries_generated
        if _summarizer_comparison_cancel: return
        async with sem_gen:
            p = await db.validation_papers.find_one({"dataset_id": ds_id, "id": paper_id}, {"_id": 0})
            if not p or p.get("ai_impact_summary_opus46"):
                return
            model_info = {"provider": "anthropic", "model": "claude-opus-4-6"}
            result = await generate_precomparison_impact_summary(p, model_override=model_info)
            if result and result.get("summary"):
                await db.validation_papers.update_one(
                    {"dataset_id": ds_id, "id": paper_id},
                    {"$set": {"ai_impact_summary_opus46": result["summary"]}},
                )
                summaries_generated += 1

    gen_tasks = [_gen_one(ds_id, pid) for ds_id, pid in paper_ids_needed]
    logger.info(f"Summarizer comparison: generating Opus 4.6 summaries for up to {len(gen_tasks)} papers...")
    await asyncio.gather(*gen_tasks, return_exceptions=True)
    logger.info(f"Summarizer comparison: {summaries_generated} new summaries generated")

    # Phase 2: Run comparisons in parallel
    sem_cmp = asyncio.Semaphore(parallel)
    completed = 0

    async def _run_one(pair):
        nonlocal completed
        if _summarizer_comparison_cancel: return
        async with sem_cmp:
            ds_id = pair["dataset_id"]
            p1 = await db.validation_papers.find_one({"dataset_id": ds_id, "id": pair["paper1_id"]}, {"_id": 0})
            p2 = await db.validation_papers.find_one({"dataset_id": ds_id, "id": pair["paper2_id"]}, {"_id": 0})
            if not p1 or not p2:
                return

            p1_opus45 = p1.get("ai_impact_summary_claude") or p1.get("ai_impact_summary", "")
            p2_opus45 = p2.get("ai_impact_summary_claude") or p2.get("ai_impact_summary", "")
            p1_opus46 = p1.get("ai_impact_summary_opus46", "")
            p2_opus46 = p2.get("ai_impact_summary_opus46", "")

            from services.llm import _pick_round_robin_model
            judge_model = _pick_round_robin_model()

            results = {}
            for model_key, p1_sum, p2_sum in [("opus45", p1_opus45, p2_opus45), ("opus46", p1_opus46, p2_opus46)]:
                if not p1_sum or not p2_sum:
                    continue
                p1_copy = {**p1, "ai_impact_summary": p1_sum}
                p2_copy = {**p2, "ai_impact_summary": p2_sum}
                try:
                    result = await compare_papers(p1_copy, p2_copy, content_mode="abstract_plus_summary", model_override=judge_model)
                    if result and not result.get("failed"):
                        winner_label = result.get("winner")
                        winner_id = p1["id"] if winner_label == "paper1" else p2["id"] if winner_label == "paper2" else None
                        results[model_key] = {"winner_id": winner_id, "model_key": result.get("model_used", {}).get("model", ""), "reasoning": result.get("reasoning", "")[:500]}
                except Exception as e:
                    logger.warning(f"Summarizer comparison failed ({model_key}): {e}")

            if results:
                doc = {
                    "dataset_id": ds_id, "paper1_id": pair["paper1_id"], "paper2_id": pair["paper2_id"],
                    "human_winner_id": pair["human_winner_id"], "score_gap": pair["score_gap"],
                    "has_tier_diff": pair["has_tier_diff"], "ground_truth": pair.get("ground_truth", "unknown"),
                    "judge_model": judge_model.get("model", ""),
                    "results": results, "created_at": datetime.now(timezone.utc).isoformat(),
                }
                for mk, r in results.items():
                    doc[f"{mk}_correct"] = r["winner_id"] == pair["human_winner_id"]
                # Single reviewer baseline on these exact paper pairs
                if pair.get("ground_truth") in ("committee", "reviewer_majority"):
                    scores1, scores2 = p1.get("scores", []), p2.get("scores", [])
                    if scores1 and scores2:
                        sc, st = 0, 0
                        for r1 in scores1:
                            for r2 in scores2:
                                if r1 == r2: continue
                                st += 1
                                if (r1 > r2 and pair["human_winner_id"] == p1["id"]) or (r2 > r1 and pair["human_winner_id"] == p2["id"]):
                                    sc += 1
                        doc["single_reviewer_correct"] = sc
                        doc["single_reviewer_total"] = st
                elif pair.get("ground_truth") == "editorial_assessment":
                    # eLife: use both dimensions as independent opinions
                    # Ground truth is significance; check if strength AND significance individually agree
                    sig1, sig2 = p1.get("sig_score"), p2.get("sig_score")
                    str1, str2 = p1.get("str_score"), p2.get("str_score")
                    sc, st = 0, 0
                    # Strength dimension as independent reviewer
                    if str1 is not None and str2 is not None and str1 != str2:
                        st += 1
                        if (str1 > str2 and pair["human_winner_id"] == p1["id"]) or (str2 > str1 and pair["human_winner_id"] == p2["id"]):
                            sc += 1
                    # Significance dimension as independent reviewer (cross-check against itself)
                    if sig1 is not None and sig2 is not None and sig1 != sig2:
                        st += 1
                        if (sig1 > sig2 and pair["human_winner_id"] == p1["id"]) or (sig2 > sig1 and pair["human_winner_id"] == p2["id"]):
                            sc += 1
                    if st > 0:
                        doc["single_reviewer_correct"] = sc
                        doc["single_reviewer_total"] = st
                await db.summarizer_comparisons.update_one(
                    {"paper1_id": pair["paper1_id"], "paper2_id": pair["paper2_id"]},
                    {"$set": doc}, upsert=True,
                )
                completed += 1

    cmp_tasks = [_run_one(p) for p in pairs]
    await asyncio.gather(*cmp_tasks, return_exceptions=True)
    _summarizer_comparison_running = False
    logger.info(f"Summarizer comparison complete: {completed}/{len(pairs)}")



@router.get("/summarizer-comparison/results")
async def get_summarizer_comparison_results():
    """Get results of Opus 4.5 vs 4.6 summarizer A/B test."""
    docs = await db.summarizer_comparisons.find({}, {"_id": 0}).to_list(10000)
    if not docs:
        return {"status": "no_data", "total": 0}

    total = len(docs)
    opus45_correct = sum(1 for d in docs if d.get("opus45_correct"))
    opus46_correct = sum(1 for d in docs if d.get("opus46_correct"))
    both_correct = sum(1 for d in docs if d.get("opus45_correct") and d.get("opus46_correct"))
    neither_correct = sum(1 for d in docs if not d.get("opus45_correct") and not d.get("opus46_correct"))

    # By dataset
    from collections import defaultdict
    by_dataset = defaultdict(lambda: {"total": 0, "opus45": 0, "opus46": 0})
    for d in docs:
        ds = d.get("dataset_id", "?")
        by_dataset[ds]["total"] += 1
        if d.get("opus45_correct"):
            by_dataset[ds]["opus45"] += 1
        if d.get("opus46_correct"):
            by_dataset[ds]["opus46"] += 1

    # By tier-diff vs same-tier
    committee = [d for d in docs if d.get("ground_truth") == "committee"]
    reviewer_maj = [d for d in docs if d.get("ground_truth") == "reviewer_majority"]
    editorial = [d for d in docs if d.get("ground_truth") == "editorial_assessment"]

    def _gt_stats(subset):
        if not subset:
            return {"total": 0, "opus45": 0, "opus46": 0, "opus45_pct": 0, "opus46_pct": 0}
        t = len(subset)
        o45 = sum(1 for d in subset if d.get("opus45_correct"))
        o46 = sum(1 for d in subset if d.get("opus46_correct"))
        result = {"total": t, "opus45": o45, "opus46": o46,
                  "opus45_pct": round(o45/t*100, 1), "opus46_pct": round(o46/t*100, 1)}
        # Single reviewer baseline: average per-pair agreement rate
        # For each paper pair, what fraction of reviewer cross-pairs agree with the ground truth?
        pair_rates = []
        for d in subset:
            sr_c = d.get("single_reviewer_correct", 0)
            sr_t = d.get("single_reviewer_total", 0)
            if sr_t > 0:
                pair_rates.append(sr_c / sr_t)
        if pair_rates:
            result["single_reviewer_pct"] = round(sum(pair_rates) / len(pair_rates) * 100, 1)
            result["single_reviewer_paper_pairs"] = len(pair_rates)
        return result

    # By score gap buckets
    gap_buckets = {"small (<0.5)": [], "medium (0.5-1.5)": [], "large (>1.5)": []}
    for d in docs:
        gap = d.get("score_gap", 0)
        if gap < 0.5:
            gap_buckets["small (<0.5)"].append(d)
        elif gap < 1.5:
            gap_buckets["medium (0.5-1.5)"].append(d)
        else:
            gap_buckets["large (>1.5)"].append(d)

    return {
        "status": "ok",
        "total_pairs": total,
        "opus45_accuracy": round(opus45_correct / max(total, 1) * 100, 1),
        "opus46_accuracy": round(opus46_correct / max(total, 1) * 100, 1),
        "both_correct": both_correct,
        "neither_correct": neither_correct,
        "opus45_only": opus45_correct - both_correct,
        "opus46_only": opus46_correct - both_correct,
        "by_dataset": {ds: {
            "total": v["total"],
            "opus45_pct": round(v["opus45"] / max(v["total"], 1) * 100, 1),
            "opus46_pct": round(v["opus46"] / max(v["total"], 1) * 100, 1),
        } for ds, v in by_dataset.items()},
        "by_ground_truth": {
            "committee_decision": _gt_stats(committee),
            "reviewer_majority": _gt_stats(reviewer_maj),
            "editorial_assessment": _gt_stats(editorial),
        },
        "by_gap": {k: {
            "total": len(v),
            "opus45": sum(1 for d in v if d.get("opus45_correct")),
            "opus46": sum(1 for d in v if d.get("opus46_correct")),
            "human_pct": round(sum(d.get("single_reviewer_correct", 0) / d["single_reviewer_total"] for d in v if d.get("single_reviewer_total", 0) > 0) / max(sum(1 for d in v if d.get("single_reviewer_total", 0) > 0), 1) * 100, 1) if any(d.get("single_reviewer_total", 0) > 0 for d in v) else None,
        } for k, v in gap_buckets.items()},
    }


_summarizer_comparison_running = False
_summarizer_comparison_cancel = False

@router.get("/summarizer-comparison/status")
async def get_summarizer_comparison_status():
    """Get progress of summarizer comparison."""
    total = await db.summarizer_comparisons.count_documents({})
    return {"total_completed": total, "is_running": _summarizer_comparison_running}


@router.post("/summarizer-comparison/stop")
async def stop_summarizer_comparison():
    """Stop the running summarizer comparison."""
    global _summarizer_comparison_cancel
    _summarizer_comparison_cancel = True
    return {"status": "stopping"}



# ─── Tournament Replay (same pairs + same judges) ──────────────────────────

class ReplayTournamentRequest(BaseModel):
    dataset_id: str
    source_mode: str = "abstract_plus_summary"
    target_tag: str = "opus46"
    summary_field: str = "ai_impact_summary_opus46"
    max_matches_per_paper: int = 15
    parallel: int = 8


@router.post("/replay-tournament", dependencies=[Depends(verify_admin)])
async def replay_tournament(body: ReplayTournamentRequest):
    """Replay an existing tournament's matches with different summaries but same pairs and judges."""
    target_mode = f"{body.source_mode}:{body.target_tag}"

    # Get source matches (the Opus 4.5 tournament)
    source_matches = await db.validation_matches.find(
        {"dataset_id": body.dataset_id, "content_mode": body.source_mode, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "model_key": 1},
    ).to_list(100000)

    if not source_matches:
        return {"status": "error", "message": f"No source matches found for {body.dataset_id} / {body.source_mode}"}

    # Already completed target matches
    existing = set()
    async for doc in db.validation_matches.find(
        {"dataset_id": body.dataset_id, "content_mode": target_mode, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    ):
        existing.add((doc["paper1_id"], doc["paper2_id"]))

    # Filter: skip already done, cap at max_matches_per_paper
    papers = await db.validation_papers.find({"dataset_id": body.dataset_id}, {"_id": 0, "id": 1}).to_list(5000)
    n_papers = len(papers)
    max_total = n_papers * body.max_matches_per_paper
    match_counts = {p["id"]: 0 for p in papers}
    for (p1, p2) in existing:
        match_counts[p1] = match_counts.get(p1, 0) + 1
        match_counts[p2] = match_counts.get(p2, 0) + 1

    to_replay = []
    for m in source_matches:
        pair = (m["paper1_id"], m["paper2_id"])
        if pair in existing or (pair[1], pair[0]) in existing:
            continue
        if match_counts.get(m["paper1_id"], 0) >= body.max_matches_per_paper * 2:
            continue
        if match_counts.get(m["paper2_id"], 0) >= body.max_matches_per_paper * 2:
            continue
        to_replay.append({"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"], "judge_model": m.get("model_key", "")})
        match_counts[m["paper1_id"]] = match_counts.get(m["paper1_id"], 0) + 1
        match_counts[m["paper2_id"]] = match_counts.get(m["paper2_id"], 0) + 1
        if len(to_replay) >= max_total:
            break

    asyncio.create_task(_run_replay(body.dataset_id, to_replay, target_mode, body.summary_field, body.parallel))
    return {
        "status": "started",
        "dataset_id": body.dataset_id,
        "source_matches": len(source_matches),
        "already_done": len(existing),
        "to_replay": len(to_replay),
        "target_mode": target_mode,
        "max_per_paper": body.max_matches_per_paper,
    }


async def _run_replay(dataset_id: str, matches: list, target_mode: str, summary_field: str, parallel: int):
    """Replay matches with different summaries but pinned judge models."""
    from services.llm import compare_papers

    MODEL_MAP = {
        "gpt-5.2": {"provider": "openai", "model": "gpt-5.2"},
        "claude-opus-4-5-20251101": {"provider": "anthropic", "model": "claude-opus-4-5-20251101"},
        "gemini-3-pro-preview": {"provider": "google", "model": "gemini/gemini-3-pro-preview"},
    }

    sem = asyncio.Semaphore(parallel)
    completed = 0

    async def _run_one(match_info):
        nonlocal completed
        async with sem:
            p1 = await db.validation_papers.find_one({"dataset_id": dataset_id, "id": match_info["paper1_id"]}, {"_id": 0})
            p2 = await db.validation_papers.find_one({"dataset_id": dataset_id, "id": match_info["paper2_id"]}, {"_id": 0})
            if not p1 or not p2:
                return

            # Swap in the target summaries
            p1_sum = p1.get(summary_field, "")
            p2_sum = p2.get(summary_field, "")
            if not p1_sum or not p2_sum:
                return
            p1_copy = {**p1, "ai_impact_summary": p1_sum}
            p2_copy = {**p2, "ai_impact_summary": p2_sum}

            # Pin judge: use round-robin (source matches don't store judge model)
            from services.llm import _pick_round_robin_model
            judge_model = _pick_round_robin_model()

            try:
                result = await compare_papers(p1_copy, p2_copy, content_mode="abstract_plus_summary", model_override=judge_model)
                if result and not result.get("failed"):
                    # Convert winner ("paper1"/"paper2") to winner_id
                    winner_key = result.get("winner", "paper1")
                    winner_id = match_info["paper1_id"] if winner_key == "paper1" else match_info["paper2_id"]
                    result["id"] = str(uuid.uuid4())
                    result["dataset_id"] = dataset_id
                    result["content_mode"] = target_mode
                    result["paper1_id"] = match_info["paper1_id"]
                    result["paper2_id"] = match_info["paper2_id"]
                    result["winner_id"] = winner_id
                    result["completed"] = True
                    result["failed"] = False
                    result["replayed_from"] = "abstract_plus_summary"
                    result["pinned_judge"] = judge_model
                    # Remove _id if present
                    result.pop("_id", None)
                    await db.validation_matches.insert_one(result)
                    completed += 1
            except Exception as e:
                logger.warning(f"Replay failed: {e}")

    tasks = [_run_one(m) for m in matches]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Replay complete for {dataset_id}/{target_mode}: {completed}/{len(matches)}")
    invalidate_dataset_cache(dataset_id)



# ─── Targeted Pairwise Run ──────────────────────────────────────────────────

class TargetedPairwiseRequest(BaseModel):
    dataset_id: str
    content_mode: str  # "abstract", "extract", or "full_pdf"
    parallel: int = 30


@router.post("/run-targeted-pairwise", dependencies=[Depends(verify_admin)])
async def run_targeted_pairwise(body: TargetedPairwiseRequest):
    """Run evaluations for pairs with expert majority data that are missing in a given content mode."""
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    papers = await db.validation_papers.find({"dataset_id": body.dataset_id}, {"_id": 0}).to_list(5000)
    if not papers:
        return {"status": "error", "message": "No papers found."}

    # Build expert pair preferences to find pairs with expert majority
    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                expert_ratings[name][p["id"]] = ev["rating_value"]

    expert_pair_prefs = defaultdict(list)
    for exp, ratings in expert_ratings.items():
        pids = list(ratings.keys())
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                a, b = pids[i], pids[j]
                if ratings[a] != ratings[b]:
                    key = tuple(sorted([a, b]))
                    expert_pair_prefs[key].append((exp, a if ratings[a] > ratings[b] else b))

    # Pairs with expert preference (at least 1 reviewer with a discriminative opinion)
    # For datasets like ICLR where many reviewers overlap, we require 2+ votes (majority).
    # For datasets like F1000Prime where evaluator overlap is sparse, 1 vote is sufficient.
    target_pairs = set()
    for pair, votes in expert_pair_prefs.items():
        if len(votes) >= 2:
            c = Counter(w for _, w in votes)
            best, n = c.most_common(1)[0]
            if n > len(votes) / 2:
                target_pairs.add(pair)
        elif len(votes) == 1:
            # Single-evaluator preference — valid for sparse datasets like F1000Prime
            target_pairs.add(pair)

    # Find which pairs are already evaluated in this mode
    match_filter = {"dataset_id": body.dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(build_content_mode_filter(body.content_mode))
    existing = await db.validation_matches.find(match_filter, {"_id": 0, "paper1_id": 1, "paper2_id": 1}).to_list(100000)
    existing_pairs = {tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in existing}

    missing = target_pairs - existing_pairs
    if not missing:
        return {"status": "complete", "message": f"All {len(target_pairs)} expert-majority pairs already evaluated in {body.content_mode} mode.", "target_pairs": len(target_pairs), "missing": 0}

    asyncio.create_task(_run_targeted_pairwise(body.dataset_id, list(missing), body.content_mode, min(max(body.parallel, 1), 50)))
    return {"status": "started", "dataset_id": body.dataset_id, "content_mode": body.content_mode, "target_pairs": len(target_pairs), "missing": len(missing)}


async def _run_targeted_pairwise(dataset_id: str, pairs: list, content_mode: str, parallel: int):
    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": len(pairs), "current_pair": "Starting...", "started_at": _time.time()})

    abstract_only = content_mode == "abstract"
    try:
        papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
        lookup = {p["id"]: p for p in papers}
        prompt_config = DEFAULT_EVALUATION_PROMPT
        completed = 0

        sem = asyncio.Semaphore(parallel)

        async def _run_one(p1_orig, p2_orig):
            nonlocal completed
            if random.random() < 0.5:
                p1_id, p2_id = p2_orig, p1_orig
            else:
                p1_id, p2_id = p1_orig, p2_orig

            async with sem:
                result = await compare_papers(lookup[p1_id], lookup[p2_id], prompt_config, content_mode=content_mode)

            used_ext = content_mode == "extract" and bool(lookup[p1_id].get("full_text") and lookup[p2_id].get("full_text"))
            doc = {
                "id": str(uuid.uuid4()), "dataset_id": dataset_id,
                "paper1_id": p1_id, "paper2_id": p2_id,
                "used_extraction": used_ext,
                "abstract_only": abstract_only,
                "content_mode": content_mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if isinstance(result, Exception):
                doc.update({"completed": False, "failed": True, "error": str(result)[:200]})
            else:
                winner_key = result.get("winner", "paper1")
                doc.update({
                    "winner_id": p1_id if winner_key == "paper1" else p2_id,
                    "reasoning": result.get("reasoning", ""),
                    "model_used": result.get("model_used", {}),
                    "tokens": result.get("tokens", {}),
                    "completed": True, "failed": False,
                })
                completed += 1
            await db.validation_matches.insert_one(doc)
            state["completed_matches"] = completed

        all_tasks = [_run_one(p1, p2) for p1, p2 in pairs]
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Targeted pairwise task error: {r}")

        logger.info(f"Targeted pairwise [{dataset_id}] ({content_mode}): {completed}/{len(pairs)}")
    except Exception as e:
        logger.error(f"Targeted pairwise [{dataset_id}] error: {e}")
    finally:
        state["running"] = False
        invalidate_dataset_cache(dataset_id)



class CrossModeFillRequest(BaseModel):
    dataset_id: str
    source_mode: str  # mode to take pairs FROM
    target_mode: str  # mode to evaluate IN
    parallel: int = 30
    max_pairs: int = 0  # 0 = all missing


@router.post("/run-cross-mode-fill", dependencies=[Depends(verify_admin)])
async def run_cross_mode_fill(body: CrossModeFillRequest):
    """Evaluate pairs from one content mode in another mode, creating cross-format overlap."""
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    # Get source pairs
    src_filter = {"dataset_id": body.dataset_id, "completed": True, "failed": {"$ne": True}}
    src_filter.update(build_content_mode_filter(body.source_mode))
    src_matches = await db.validation_matches.find(src_filter, {"_id": 0, "paper1_id": 1, "paper2_id": 1}).to_list(100000)
    src_pairs = {tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in src_matches}

    # Get existing target pairs
    tgt_filter = {"dataset_id": body.dataset_id, "completed": True, "failed": {"$ne": True}}
    tgt_filter.update(build_content_mode_filter(body.target_mode))
    tgt_matches = await db.validation_matches.find(tgt_filter, {"_id": 0, "paper1_id": 1, "paper2_id": 1}).to_list(100000)
    tgt_pairs = {tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in tgt_matches}

    missing = list(src_pairs - tgt_pairs)
    if body.max_pairs > 0:
        missing = missing[:body.max_pairs]

    if not missing:
        return {"status": "complete", "message": f"All {len(src_pairs)} source pairs already exist in {body.target_mode}.", "overlap": len(src_pairs & tgt_pairs)}

    asyncio.create_task(_run_targeted_pairwise(body.dataset_id, missing, body.target_mode, min(max(body.parallel, 1), 50)))
    return {"status": "started", "dataset_id": body.dataset_id, "source_mode": body.source_mode, "target_mode": body.target_mode, "pairs_to_fill": len(missing), "already_overlap": len(src_pairs & tgt_pairs)}


# ─── Reset ─────────────────────────────────────────────────────────────────────

class ResetRequest(BaseModel):
    dataset_id: str


@router.post("/reset", dependencies=[Depends(verify_admin)])
async def reset_dataset(body: ResetRequest):
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "error", "message": "Cannot reset while tournament is running."}
    p = await db.validation_papers.delete_many({"dataset_id": body.dataset_id})
    m = await db.validation_matches.delete_many({"dataset_id": body.dataset_id})
    await db.validation_datasets.delete_one({"dataset_id": body.dataset_id})
    return {"status": "ok", "papers_deleted": p.deleted_count, "matches_deleted": m.deleted_count}



# ─── Seed ──────────────────────────────────────────────────────────────────────

@router.post("/seed", dependencies=[Depends(verify_admin)])
async def seed_validation_data():
    """Load pre-computed validation data from bundled JSON files."""
    from pathlib import Path
    seed_dir = Path(__file__).parent.parent / "data" / "validation_seed"

    if not seed_dir.exists():
        return {"status": "error", "message": "Seed data not found"}

    results = {}
    for coll_name in ["validation_datasets", "validation_papers", "validation_matches"]:
        path = seed_dir / f"{coll_name}.json"
        if not path.exists():
            results[coll_name] = "file missing"
            continue

        with open(path) as f:
            docs = json.load(f)

        if not docs:
            results[coll_name] = "empty"
            continue

        coll = db[coll_name]
        existing = await coll.count_documents({})
        if existing > 0:
            results[coll_name] = f"skipped ({existing} docs already exist)"
            continue

        await coll.insert_many(docs)
        results[coll_name] = f"inserted {len(docs)} docs"

    return {"status": "ok", "results": results}


# ─── Helpers ───────────────────────────────────────────────────────────────────


# ─── F1000Prime Alzheimer's Scraper ─────────────────────────────────────────

@router.post("/scrape-f1000", dependencies=[Depends(verify_admin)])
async def scrape_f1000(target: int = 75):
    """Scrape F1000Prime archive for Alzheimer's/neuroscience papers."""
    from services.f1000_scraper import run_scraper, get_state
    state = get_state()
    if state["running"]:
        return {"status": "already_running", **state}
    # Run in background
    asyncio.create_task(run_scraper(db, target_papers=target))
    return {"status": "started", "target_papers": target}


@router.get("/scrape-f1000/status")
async def scrape_f1000_status():
    """Get the current status of the F1000 scraper."""
    from services.f1000_scraper import get_state
    return get_state()


@router.post("/enrich-f1000", dependencies=[Depends(verify_admin)])
async def enrich_f1000():
    """Enrich F1000 papers with abstracts from Semantic Scholar."""
    from services.f1000_scraper import enrich_papers_from_semantic_scholar, get_state
    state = get_state()
    if state["running"]:
        return {"status": "already_running", **state}
    asyncio.create_task(enrich_papers_from_semantic_scholar(db))
    return {"status": "started"}


@router.post("/expand-f1000", dependencies=[Depends(verify_admin)])
async def expand_f1000(min_pairs: int = 100):
    """Expand F1000 dataset by graph-crawling related articles for more evaluator overlap."""
    from services.f1000_scraper import expand_dataset, get_state
    state = get_state()
    if state["running"]:
        return {"status": "already_running", **state}
    asyncio.create_task(expand_dataset(db, min_discriminative_pairs=min_pairs))
    return {"status": "started", "target_discriminative_pairs": min_pairs}


@router.post("/rescrape-f1000-evals", dependencies=[Depends(verify_admin)])
async def rescrape_f1000_evals():
    """Re-scrape ALL evaluations for existing F1000 papers (captures multi-evaluator articles)."""
    from services.f1000_rescrape import rescrape_all_evaluations
    asyncio.create_task(_run_rescrape(db))
    return {"status": "started"}


async def _run_rescrape(database):
    from services.f1000_rescrape import rescrape_all_evaluations
    result = await rescrape_all_evaluations(database)
    logger.info(f"F1000 rescrape complete: {result}")

