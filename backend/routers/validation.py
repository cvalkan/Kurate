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

router = APIRouter(prefix="/api/validation")

# In-memory tournament state per dataset
_tournament_states = {}  # dataset_id -> {running, completed, total, ...}


def _get_state(dataset_id: str) -> dict:
    if dataset_id not in _tournament_states:
        _tournament_states[dataset_id] = {
            "running": False, "completed_matches": 0,
            "total_matches": 0, "current_pair": "", "started_at": None,
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
    content_mode: Optional[str] = None  # "abstract", "extract", "full_pdf"


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

    asyncio.create_task(_run_tournament(body.dataset_id, min(max(body.num_matches, 1), 2000), min(max(body.parallel, 1), 50), content_mode=content_mode))
    return {"status": "started", "dataset_id": body.dataset_id, "num_matches": body.num_matches, "content_mode": content_mode}


async def _run_tournament(dataset_id: str, max_pairs: int, parallel: int, content_mode: str = "extract"):
    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": max_pairs, "current_pair": "Loading...", "started_at": _time.time()})

    abstract_only = content_mode == "abstract"

    try:
        papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
        lookup = {p["id"]: p for p in papers}
        pids = list(lookup.keys())

        # Dedup: only check matches of the same mode
        match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
        if content_mode == "abstract":
            match_filter["abstract_only"] = True
        elif content_mode == "full_pdf":
            match_filter["content_mode"] = "full_pdf"
        else:
            match_filter["abstract_only"] = {"$ne": True}
            match_filter["content_mode"] = {"$ne": "full_pdf"}

        existing = await db.validation_matches.find(
            match_filter,
            {"_id": 0, "paper1_id": 1, "paper2_id": 1},
        ).to_list(100000)
        compared = {tuple(sorted([m["paper1_id"], m["paper2_id"]])) for m in existing}

        pairs = []
        attempts = 0
        while len(pairs) < max_pairs and attempts < max_pairs * 20:
            p1, p2 = random.sample(pids, 2)
            key = tuple(sorted([p1, p2]))
            if key not in compared:
                pairs.append((p1, p2))
                compared.add(key)
            attempts += 1

        state["total_matches"] = len(pairs)
        prompt_config = DEFAULT_EVALUATION_PROMPT
        completed = 0

        for i in range(0, len(pairs), parallel):
            batch = pairs[i:i + parallel]
            presented = [(p2, p1) if random.random() < 0.5 else (p1, p2) for p1, p2 in batch]
            state["current_pair"] = f"Batch {i // parallel + 1}"

            tasks = [
                compare_papers(lookup[p1], lookup[p2], prompt_config,
                               content_mode=content_mode)
                for p1, p2 in presented
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (p1_id, p2_id), result in zip(presented, results):
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
            await asyncio.sleep(0.2)

        logger.info(f"Validation tournament [{dataset_id}] ({content_mode}): {completed}/{len(pairs)}")
    except Exception as e:
        logger.error(f"Validation tournament [{dataset_id}] error: {e}")
    finally:
        state["running"] = False


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
        match_filter.update(_build_content_mode_filter(content_mode))

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


# ─── Multi-Model Analysis ─────────────────────────────────────────────────────

@router.get("/multimodel-results")
async def get_multimodel_results(dataset_id: str = Query(...), content_mode: Optional[str] = Query(None)):
    """Inter-model agreement + majority-vote vs expert analysis."""
    from core.config import TOURNAMENT_MODELS

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(_build_content_mode_filter(content_mode))

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


# ─── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(dataset_id: str = Query(...)):
    n = await db.validation_papers.count_documents({"dataset_id": dataset_id})
    m = await db.validation_matches.count_documents({"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}})
    m_ext = await db.validation_matches.count_documents({"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}, "used_extraction": True})
    m_abs_only = await db.validation_matches.count_documents({"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}, "abstract_only": True})
    failed = await db.validation_matches.count_documents({"dataset_id": dataset_id, "failed": True})
    total_pairs = n * (n - 1) // 2 if n > 1 else 0
    with_text = await db.validation_papers.count_documents({"dataset_id": dataset_id, "full_text": {"$exists": True, "$nin": [None, ""]}})

    # Match distribution
    avg_m = min_m = max_m = 0
    if m > 0:
        agg = await db.validation_matches.aggregate([
            {"$match": {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}},
            {"$group": {"_id": None, "p1s": {"$push": "$paper1_id"}, "p2s": {"$push": "$paper2_id"}}},
        ]).to_list(1)
        if agg:
            counts = Counter(agg[0]["p1s"] + agg[0]["p2s"])
            avg_m = round(sum(counts.values()) / max(len(counts), 1), 1)
            min_m = min(counts.values())
            max_m = max(counts.values())

    state = _get_state(dataset_id)
    meta = await db.validation_datasets.find_one({"dataset_id": dataset_id}, {"_id": 0}) or {}

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
        "tournament_running": state["running"],
        "tournament_progress": state,
    }


# ─── Results: Pairwise BT ─────────────────────────────────────────────────────

def _build_content_mode_filter(content_mode: Optional[str] = None, abstract_only: Optional[bool] = None) -> dict:
    """Build a MongoDB match filter for content_mode, with backward compatibility."""
    if content_mode == "full_pdf":
        return {"content_mode": "full_pdf"}
    elif content_mode == "ai_summary":
        return {"content_mode": "ai_summary"}
    elif content_mode == "abstract_plus_summary":
        return {"content_mode": "abstract_plus_summary"}
    elif content_mode == "abstract_plus_impact":
        return {"content_mode": "abstract_plus_impact"}
    elif content_mode == "abstract" or abstract_only is True:
        return {"abstract_only": True}
    elif content_mode == "extract" or abstract_only is False:
        return {"abstract_only": {"$ne": True}, "content_mode": {"$nin": ["full_pdf", "ai_summary", "abstract_plus_summary", "abstract_plus_impact"]}}
    return {}


@router.get("/pairwise-results")
async def get_pairwise_results(dataset_id: str = Query(...), abstract_only: Optional[bool] = Query(None), content_mode: Optional[str] = Query(None)):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(_build_content_mode_filter(content_mode, abstract_only))

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
    TIER_ORDER = {"oral": 0, "spotlight": 1, "poster": 2, "reject": 3, "withdrawn": 4, "desk rejected": 4}
    def _norm_tier(d):
        if not d: return None
        dl = d.lower().strip()
        for t in TIER_ORDER:
            if t in dl: return t
        return None

    paper_tiers = {}
    for p in papers:
        t = _norm_tier(p.get("decision"))
        if t and t in ("oral", "spotlight", "poster", "reject"):
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
                "spearman_rho": round(t_sp, 4), "spearman_p_value": round(t_sp_p, 6),
                "kendall_tau": round(t_kt, 4), "kendall_p_value": round(t_kt_p, 6),
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
            "spearman_rho": round(sp, 4), "spearman_p_value": round(sp_p, 6),
            "kendall_tau": round(kt, 4), "kendall_p_value": round(kt_p, 6),
            "pearson_r": round(pr, 4), "pearson_p_value": round(pr_p, 6),
        },
        "interpretation": _interp(sp, sp_p, len(cp), "pairwise BT"),
        "comparison": comparison,
        "tier_metrics": tier_metrics,
    }



# ─── Convergence Analysis ──────────────────────────────────────────────────────

@router.get("/convergence")
async def get_convergence(dataset_id: str = Query(...), content_mode: Optional[str] = Query(None), steps: int = Query(20)):
    """Analyze how AI ranking correlation with HUMAN ground truth improves as more matches are added.
    
    Uses human expert pairwise preferences (derived from review scores) as ground truth.
    Subsamples AI matches to measure convergence toward human ranking.
    """
    settings = await get_settings()
    top_k_focus = settings.get("top_k_focus", 10)

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    if not papers:
        return {"status": "no_data"}

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(_build_content_mode_filter(content_mode))

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

    # Compute max avg matches per paper
    total = len(all_matches)
    full_counts = defaultdict(int)
    for m in all_matches:
        if m["paper1_id"] in pid_set: full_counts[m["paper1_id"]] += 1
        if m["paper2_id"] in pid_set: full_counts[m["paper2_id"]] += 1
    max_avg = sum(full_counts[pid] for pid in paper_ids if full_counts[pid] > 0) / max(sum(1 for pid in paper_ids if full_counts[pid] > 0), 1)

    # Generate match-count targets for the curve
    # Phase 1: Absolute match counts for the very start (every 3 matches up to 50)
    # Phase 2: Average-per-paper targets for the rest
    absolute_targets = list(range(3, min(51, total + 1), 3))  # 3, 6, 9, 12, ... 48
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

    curve = []
    seen_match_counts = set()

    # Add baseline point at 0 matches (all papers at default score → random ranking → ρ≈0)
    curve.append({
        "matches": 0,
        "avg_matches_per_paper": 0,
        "papers_covered": 0,
        "spearman": 0, "kendall": 0, "pearson": 0,
        **{f"top_{k}": round(k / len(paper_ids) * 100, 1) if paper_ids else 0 for k in top_k_values},
    })

    # Phase 1: absolute match count targets
    for n_matches in absolute_targets:
        if n_matches > total:
            break
        subset = all_matches[:n_matches]
        paper_match_count = defaultdict(int)
        for m in subset:
            if m["paper1_id"] in pid_set: paper_match_count[m["paper1_id"]] += 1
            if m["paper2_id"] in pid_set: paper_match_count[m["paper2_id"]] += 1
        papers_with_matches = [pid for pid in paper_ids if paper_match_count[pid] > 0]
        if len(papers_with_matches) < 2:
            continue
        avg_matches = sum(paper_match_count[pid] for pid in papers_with_matches) / len(papers_with_matches)

        # Compute BT ranking on ALL papers (papers with 0 matches get default score)
        sub_lb = compute_leaderboard(papers, subset)
        sub_rank = {e["id"]: e["rank"] for e in sub_lb}

        # Correlate ALL papers (not just matched ones) against ground truth
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

        curve.append({
            "matches": n_matches,
            "avg_matches_per_paper": round(avg_matches, 1),
            "papers_covered": len(papers_with_matches),
            "spearman": round(sp, 4) if not np.isnan(sp) else 0,
            "kendall": round(kt, 4) if not np.isnan(kt) else 0,
            "pearson": round(pr, 4) if not np.isnan(pr) else 0,
            **{f"top_{k}": topk.get(f"top_{k}", 0) for k in top_k_values},
        })
        seen_match_counts.add(n_matches)

    # Phase 2: avg-per-paper targets (skip if already covered by phase 1)
    for target_avg in avg_targets:
        lo, hi = 1, total
        best_n = total
        while lo <= hi:
            mid = (lo + hi) // 2
            counts = defaultdict(int)
            for m in all_matches[:mid]:
                if m["paper1_id"] in pid_set: counts[m["paper1_id"]] += 1
                if m["paper2_id"] in pid_set: counts[m["paper2_id"]] += 1
            active = [pid for pid in paper_ids if counts[pid] > 0]
            if not active:
                lo = mid + 1
                continue
            avg = sum(counts[pid] for pid in active) / len(active)
            if avg < target_avg:
                lo = mid + 1
            else:
                best_n = mid
                hi = mid - 1

        subset = all_matches[:best_n]
        if best_n in seen_match_counts:
            continue
        seen_match_counts.add(best_n)
        paper_match_count = defaultdict(int)
        for m in subset:
            if m["paper1_id"] in pid_set: paper_match_count[m["paper1_id"]] += 1
            if m["paper2_id"] in pid_set: paper_match_count[m["paper2_id"]] += 1

        papers_with_matches = [pid for pid in paper_ids if paper_match_count[pid] > 0]
        if len(papers_with_matches) < 2:
            continue

        avg_matches = sum(paper_match_count[pid] for pid in papers_with_matches) / len(papers_with_matches)

        sub_lb = compute_leaderboard(papers, subset)
        sub_rank = {e["id"]: e["rank"] for e in sub_lb}

        # Correlate ALL papers against ground truth
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

        point = {
            "matches": best_n,
            "avg_matches_per_paper": round(avg_matches, 1),
            "papers_covered": len(papers_with_matches),
            "spearman": round(sp, 4) if not np.isnan(sp) else 0,
            "kendall": round(kt, 4) if not np.isnan(kt) else 0,
            "pearson": round(pr, 4) if not np.isnan(pr) else 0,
        }
        point.update(topk)
        curve.append(point)

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
        "top_k_values": top_k_values,
        "curve": curve,
        "graph_connectivity": {
            "components": len(h_components),
            "largest_component": h_largest_component,
            "component_sizes": h_component_sizes[:10],
            "is_connected": len(h_components) == 1,
        },
    }



# ─── Results: IRT Direct Score ─────────────────────────────────────────────────

@router.get("/irt-results")
async def get_irt_results(dataset_id: str = Query(...), abstract_only: Optional[bool] = Query(None), content_mode: Optional[str] = Query(None)):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(_build_content_mode_filter(content_mode, abstract_only))

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
        "interpretation": _interp(sp_irt, sp_irt_p, len(cp), "IRT score"),
        "comparison": comparison,
    }


# ─── Agreement Analysis ────────────────────────────────────────────────────────

@router.get("/agreement-analysis")
async def get_agreement(dataset_id: str = Query(...), abstract_only: Optional[bool] = Query(None), content_mode: Optional[str] = Query(None)):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)

    match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
    match_filter.update(_build_content_mode_filter(content_mode, abstract_only))

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

    # Expert-expert pairwise agreement — filtered to pairs where AI has data
    ai_pair = {}
    for m in ai_matches:
        ai_pair[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m["winner_id"]

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
    """
    Compute AI-expert agreement on the EXACT SAME set of paper pairs across
    all available content modes, enabling apples-to-apples comparison.
    """
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
    modes = ["abstract", "extract", "full_pdf", "ai_summary", "abstract_plus_summary"]
    mode_ai_pairs = {}
    mode_model_pairs = {}  # mode -> model_key -> {pair: winner}
    for mode in modes:
        match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
        match_filter.update(_build_content_mode_filter(mode))
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

    # Find common pairs using only modes with substantial data.
    # A mode must have at least 50% of the largest mode's pairs to be "core".
    max_pairs = max(len(mode_ai_pairs[m]) for m in available_modes)
    core_modes = [m for m in available_modes if len(mode_ai_pairs[m]) >= max_pairs * 0.5]
    overlay_modes = [m for m in available_modes if m not in core_modes]

    if len(core_modes) < 2:
        return {"status": "insufficient_modes", "available": available_modes}

    common_pairs = set.intersection(*[set(mode_ai_pairs[m].keys()) for m in core_modes])

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
    # For datasets with ICLR-style decisions (Oral/Spotlight/Poster/Reject)
    TIER_ORDER = {"oral": 0, "spotlight": 1, "poster": 2, "reject": 3, "withdrawn": 4, "desk rejected": 4}

    def _normalize_tier(decision):
        if not decision:
            return None
        d = decision.lower().strip()
        for tier_key in TIER_ORDER:
            if tier_key in d:
                return tier_key
        return None

    paper_tiers = {}
    for p in papers:
        tier = _normalize_tier(p.get("decision"))
        if tier and tier in ("oral", "spotlight", "poster", "reject"):
            paper_tiers[p["id"]] = tier

    tier_analysis = {}
    if len(paper_tiers) >= 5:
        for mode in modes_with_results:
            ai_map = mode_ai_pairs.get(mode, {})
            tier_paper_ids = set(paper_tiers.keys())

            # Fetch matches for this mode to build BT ranking
            mode_match_filter = {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}}
            mode_match_filter.update(_build_content_mode_filter(mode))
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
    match_filter.update(_build_content_mode_filter(body.content_mode))
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

        for i in range(0, len(pairs), parallel):
            batch = pairs[i:i + parallel]
            presented = [(p2, p1) if random.random() < 0.5 else (p1, p2) for p1, p2 in batch]
            state["current_pair"] = f"Batch {i // parallel + 1}/{(len(pairs) + parallel - 1) // parallel}"

            tasks = [
                compare_papers(lookup[p1], lookup[p2], prompt_config, content_mode=content_mode)
                for p1, p2 in presented
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (p1_id, p2_id), result in zip(presented, results):
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
            await asyncio.sleep(0.2)

        logger.info(f"Targeted pairwise [{dataset_id}] ({content_mode}): {completed}/{len(pairs)}")
    except Exception as e:
        logger.error(f"Targeted pairwise [{dataset_id}] error: {e}")
    finally:
        state["running"] = False



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

def _interp(rho, p_val, n, method):
    strength = "strong" if abs(rho) >= 0.7 else "moderate" if abs(rho) >= 0.4 else "weak" if abs(rho) >= 0.2 else "negligible"
    direction = "positive" if rho > 0 else "negative"
    sig = "statistically significant" if p_val < 0.05 else "not statistically significant"
    return f"Using {method} ranking ({n} papers): Spearman ρ = {rho:.3f} ({strength} {direction}, {sig}, p = {p_val:.4f})."


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

