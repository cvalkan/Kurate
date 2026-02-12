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
    """Import ICLR papers from the berenslab dataset, filtered by label/keyword."""
    import pandas as pd

    try:
        df = pd.read_parquet('/tmp/iclr-dataset/data/iclr25v2.parquet')
    except FileNotFoundError:
        return {"status": "error", "message": "ICLR dataset not found. Clone berenslab/iclr-dataset to /tmp/iclr-dataset/"}

    def parse_scores(s):
        if isinstance(s, np.ndarray): return s.astype(float).tolist()
        return []

    df['parsed_scores'] = df['scores'].apply(parse_scores)
    df['n_reviews'] = df['parsed_scores'].apply(len)
    df['avg_score'] = df['parsed_scores'].apply(lambda x: float(np.mean(x)) if x else 0)

    # Filter
    filtered = df[
        (df['year'].isin(body.years)) &
        (df['n_reviews'] >= body.min_reviews)
    ].copy()

    if body.label_filter:
        filtered = filtered[filtered['labels'] == body.label_filter]
    if body.keyword_filter:
        filtered = filtered[filtered['title'].str.contains(body.keyword_filter, case=False, na=False)]

    if len(filtered) == 0:
        return {"status": "error", "message": f"No papers match filters: label={body.label_filter}, keyword={body.keyword_filter}"}

    # Stratified sample by score
    bins = [0, 3, 4, 5, 5.5, 6, 7, 8, 11]
    filtered['score_bin'] = pd.cut(filtered['avg_score'], bins=bins)
    per_bin = max(body.max_papers // len(bins), 5)
    samples = []
    for _, group in filtered.groupby('score_bin', observed=True):
        samples.append(group.sample(min(len(group), per_bin), random_state=42))
    selected = pd.concat(samples)

    # Download PDFs and import
    imported = 0
    pdfs = 0
    for _, row in selected.iterrows():
        full_text = None
        try:
            r = requests.get(f"https://openreview.net/pdf?id={row['id']}", timeout=30, allow_redirects=True)
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(r.content))
                parts = [page.extract_text() or "" for page in reader.pages]
                text = " ".join(" ".join(parts).split()).encode("utf-8", errors="replace").decode("utf-8")
                if len(text) > 500:
                    full_text = text
                    pdfs += 1
        except Exception:
            pass

        evaluations = [{"rating_value": float(s), "evaluator": f"Reviewer_{j+1}", "source": "ICLR"} for j, s in enumerate(row['parsed_scores'])]

        doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": body.dataset_id,
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
            {"dataset_id": body.dataset_id, "openreview_id": row["id"]},
            {"$set": doc}, upsert=True
        )
        imported += 1
        _time.sleep(0.3)

    # Save dataset metadata
    await db.validation_datasets.update_one(
        {"dataset_id": body.dataset_id},
        {"$set": {
            "dataset_id": body.dataset_id,
            "name": body.name,
            "description": body.description,
            "source": f"ICLR {body.years} / {body.label_filter or body.keyword_filter}",
            "label_filter": body.label_filter,
            "keyword_filter": body.keyword_filter,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    return {"status": "ok", "dataset_id": body.dataset_id, "imported": imported, "pdfs": pdfs}


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



# ─── Tournament ────────────────────────────────────────────────────────────────

class TournamentRequest(BaseModel):
    dataset_id: str
    num_matches: int = 500
    parallel: int = 30


@router.post("/run-tournament", dependencies=[Depends(verify_admin)])
async def run_tournament(body: TournamentRequest):
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    count = await db.validation_papers.count_documents({"dataset_id": body.dataset_id})
    if count < 2:
        return {"status": "error", "message": "Need at least 2 papers. Import first."}

    asyncio.create_task(_run_tournament(body.dataset_id, min(max(body.num_matches, 1), 2000), min(max(body.parallel, 1), 50)))
    return {"status": "started", "dataset_id": body.dataset_id, "num_matches": body.num_matches}


async def _run_tournament(dataset_id: str, max_pairs: int, parallel: int):
    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": max_pairs, "current_pair": "Loading...", "started_at": _time.time()})

    try:
        papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
        lookup = {p["id"]: p for p in papers}
        pids = list(lookup.keys())

        existing = await db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
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
                               abstract_only=not (lookup[p1].get("full_text") and lookup[p2].get("full_text")))
                for p1, p2 in presented
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (p1_id, p2_id), result in zip(presented, results):
                used_ext = bool(lookup[p1_id].get("full_text") and lookup[p2_id].get("full_text"))
                doc = {
                    "id": str(uuid.uuid4()), "dataset_id": dataset_id,
                    "paper1_id": p1_id, "paper2_id": p2_id,
                    "used_extraction": used_ext,
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

        logger.info(f"Validation tournament [{dataset_id}]: {completed}/{len(pairs)}")
    except Exception as e:
        logger.error(f"Validation tournament [{dataset_id}] error: {e}")
    finally:
        state["running"] = False


# ─── Multi-Model Tournament ───────────────────────────────────────────────────

class MultiModelRequest(BaseModel):
    dataset_id: str
    parallel: int = 30
    max_pairs: int = 0  # 0 = all pairs


@router.post("/run-multimodel", dependencies=[Depends(verify_admin)])
async def run_multimodel_tournament(body: MultiModelRequest):
    """Re-run existing pairs with all 3 models so each pair has 3 verdicts."""
    state = _get_state(body.dataset_id)
    if state["running"]:
        return {"status": "already_running", **state}

    asyncio.create_task(_run_multimodel(body.dataset_id, min(max(body.parallel, 1), 50), body.max_pairs))
    return {"status": "started", "dataset_id": body.dataset_id, "max_pairs": body.max_pairs}


async def _run_multimodel(dataset_id: str, parallel: int, max_pairs: int = 0):
    from core.config import TOURNAMENT_MODELS

    state = _get_state(dataset_id)
    state.update({"running": True, "completed_matches": 0, "total_matches": 0, "current_pair": "Scanning...", "started_at": _time.time()})

    try:
        papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
        lookup = {p["id"]: p for p in papers}

        # Get all completed matches
        matches = await db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
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
                    abstract_only=not (lookup[p1].get("full_text") and lookup[p2].get("full_text")),
                    model_override=mi,
                )
                for p1, p2, mi in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for (p1_id, p2_id, mi), result in zip(tasks, results):
                used_ext = bool(lookup[p1_id].get("full_text") and lookup[p2_id].get("full_text"))
                doc = {
                    "id": str(uuid.uuid4()), "dataset_id": dataset_id,
                    "paper1_id": p1_id, "paper2_id": p2_id,
                    "used_extraction": used_ext,
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
async def get_multimodel_results(dataset_id: str = Query(...)):
    """Inter-model agreement + majority-vote vs expert analysis."""
    from core.config import TOURNAMENT_MODELS

    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
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
            if len(common) < 3:
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
    failed = await db.validation_matches.count_documents({"dataset_id": dataset_id, "failed": True})
    total_pairs = n * (n - 1) // 2 if n > 1 else 0
    with_text = await db.validation_papers.count_documents({"dataset_id": dataset_id, "full_text": {"$exists": True, "$ne": None, "$ne": ""}})

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

@router.get("/pairwise-results")
async def get_pairwise_results(dataset_id: str = Query(...)):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    ai_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
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
    if len(common) < 3:
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
    }


# ─── Results: IRT Direct Score ─────────────────────────────────────────────────

@router.get("/irt-results")
async def get_irt_results(dataset_id: str = Query(...)):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    ai_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
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
    if len(common) < 3:
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
async def get_agreement(dataset_id: str = Query(...)):
    papers = await db.validation_papers.find({"dataset_id": dataset_id}, {"_id": 0}).to_list(5000)
    ai_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)

    if not papers:
        return {"status": "no_data"}

    expert_ratings = defaultdict(dict)
    for p in papers:
        for ev in p.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name: expert_ratings[name][p["id"]] = ev["rating_value"]

    # Expert-expert pairwise agreement
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
        if len(votes) < 2: continue
        winners = [w for _, w in votes]
        for i in range(len(winners)):
            for j in range(i + 1, len(winners)):
                ee_total += 1
                if winners[i] == winners[j]: ee_agree += 1

    # AI vs individual expert
    ai_pair = {}
    for m in ai_matches:
        ai_pair[tuple(sorted([m["paper1_id"], m["paper2_id"]]))] = m["winner_id"]

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


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _interp(rho, p_val, n, method):
    strength = "strong" if abs(rho) >= 0.7 else "moderate" if abs(rho) >= 0.4 else "weak" if abs(rho) >= 0.2 else "negligible"
    direction = "positive" if rho > 0 else "negative"
    sig = "statistically significant" if p_val < 0.05 else "not statistically significant"
    return f"Using {method} ranking ({n} papers): Spearman ρ = {rho:.3f} ({strength} {direction}, {sig}, p = {p_val:.4f})."
