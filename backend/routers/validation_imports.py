"""
Validation Dataset Import Endpoints

Import handlers for ICLR, eLife, MIDL, PeerRead, and F1000 datasets.
Extracted from the main validation router for maintainability.
"""
import asyncio
import uuid
import json
import re
import io
import os
import time as _time
import requests
import numpy as np
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from pydantic import BaseModel

from core.config import db, logger
from core.auth import verify_admin
from services.llm import download_and_extract_pdf

router = APIRouter(prefix="/api/validation")

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
        if isinstance(s, np.ndarray):
            return s.astype(float).tolist()
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

