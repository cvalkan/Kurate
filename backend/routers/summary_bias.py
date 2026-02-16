"""
Summary Bias Experiment — Does the LLM that wrote the summary bias the judge?

Pipeline:
1. Generate AI impact summaries for papers in a category using all 3 LLMs
2. Run N random matches x 9 configurations (3 judges x 3 summary sources)
3. Analyze pairwise match-level agreement and bias patterns
"""
import asyncio
import uuid
import random
import time as _time
from datetime import datetime, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.config import db, logger, TOURNAMENT_MODELS, DEFAULT_EVALUATION_PROMPT
from core.auth import verify_admin
from services.llm import generate_precomparison_impact_summary, compare_papers
from services.ranking import compute_leaderboard

router = APIRouter(prefix="/api/summary-bias")

_state = {"phase": "idle", "progress": {}}

MODEL_SHORT = {
    "anthropic:claude-opus-4-5-20251101": "Claude Opus",
    "gemini:gemini-3-pro-preview": "Gemini 3",
    "openai:gpt-5.2": "GPT 5.2",
}


def _mk(m):
    return f"{m['provider']}:{m['model']}"


def _short(mk):
    return MODEL_SHORT.get(mk, mk.split(":")[1] if ":" in mk else mk)


# ─── Full Pipeline ───────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    category: str = "q-bio.BM"
    num_matches: int = 200
    parallel: int = 20


@router.post("/run-pipeline", dependencies=[Depends(verify_admin)])
async def run_pipeline(body: PipelineRequest):
    if _state["phase"] != "idle":
        return {"status": "already_running", "phase": _state["phase"], "progress": _state["progress"]}
    asyncio.create_task(_full_pipeline(body.category, body.num_matches, body.parallel))
    return {"status": "started", "category": body.category, "num_matches": body.num_matches}


async def _full_pipeline(category: str, num_matches: int, parallel: int):
    try:
        # Phase 1: Generate summaries
        await _do_generate_summaries(category, parallel)
        # Phase 2: Run experiment
        await _do_run_experiment(category, num_matches, parallel)
        # Phase 3: Run full-PDF baseline
        await _do_run_fullpdf_baseline(category, parallel)
    except Exception as e:
        logger.error(f"Summary bias pipeline error: {e}")
    finally:
        _state["phase"] = "idle"
        _state["progress"] = {}


# ─── Phase 1: Generate Summaries ─────────────────────────────────────────

async def _do_generate_summaries(category: str, parallel: int):
    _state["phase"] = "generating_summaries"

    papers = await db.papers.find(
        {"categories": category},
        {"_id": 0}
    ).to_list(500)

    total = len(papers) * len(TOURNAMENT_MODELS)
    completed = 0
    _state["progress"] = {"completed": 0, "total": total, "category": category}

    sem = asyncio.Semaphore(parallel)

    async def gen_one(paper, model_info):
        nonlocal completed
        mk = _mk(model_info)

        existing = await db.summary_bias_summaries.find_one(
            {"paper_id": paper["id"], "model_key": mk},
            {"_id": 0, "summary_text": 1}
        )
        if existing and existing.get("summary_text"):
            completed += 1
            _state["progress"]["completed"] = completed
            return

        async with sem:
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=model_info)
                if result:
                    await db.summary_bias_summaries.update_one(
                        {"paper_id": paper["id"], "model_key": mk},
                        {"$set": {
                            "paper_id": paper["id"],
                            "category": category,
                            "model_key": mk,
                            "provider": model_info["provider"],
                            "model": model_info["model"],
                            "summary_text": result["summary"],
                            "word_count": result.get("word_count", 0),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }},
                        upsert=True
                    )
                else:
                    logger.warning(f"Summary gen failed: {paper['title'][:40]} / {mk}")
            except Exception as e:
                logger.warning(f"Summary gen error: {paper['title'][:40]} / {mk}: {e}")

            completed += 1
            _state["progress"]["completed"] = completed
            if completed % 10 == 0:
                logger.info(f"Summary bias summaries: {completed}/{total}")

    tasks = [gen_one(p, m) for p in papers for m in TOURNAMENT_MODELS]
    await asyncio.gather(*tasks)
    logger.info(f"Summary bias: generated {completed} summaries for {len(papers)} papers")


# ─── Phase 2: Run Experiment ─────────────────────────────────────────────

async def _do_run_experiment(category: str, num_matches: int, parallel: int):
    _state["phase"] = "running_experiment"

    papers = await db.papers.find(
        {"categories": category},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1}
    ).to_list(500)
    paper_lookup = {p["id"]: p for p in papers}
    paper_ids = set(paper_lookup.keys())

    # Load all summaries into a lookup
    summaries_raw = await db.summary_bias_summaries.find(
        {"category": category},
        {"_id": 0, "paper_id": 1, "model_key": 1, "summary_text": 1}
    ).to_list(10000)
    sum_lookup = {(s["paper_id"], s["model_key"]): s["summary_text"] for s in summaries_raw}

    # Get existing matches for this category
    existing_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
    ).to_list(100000)

    # Filter to matches where both papers have all 3 summaries
    model_keys = [_mk(m) for m in TOURNAMENT_MODELS]
    valid = [
        m for m in existing_matches
        if m["paper1_id"] in paper_ids and m["paper2_id"] in paper_ids
        and all((m["paper1_id"], mk) in sum_lookup and (m["paper2_id"], mk) in sum_lookup for mk in model_keys)
    ]

    selected = random.sample(valid, min(num_matches, len(valid))) if len(valid) > num_matches else valid
    logger.info(f"Summary bias experiment: {len(selected)} matches selected from {len(valid)} valid")

    # Build all 9 configs
    configs = [(j, s) for j in TOURNAMENT_MODELS for s in TOURNAMENT_MODELS]
    total_work = len(selected) * len(configs)
    completed = 0
    _state["progress"] = {"completed": 0, "total": total_work, "category": category}

    # Check what's already done
    done_set = set()
    async for doc in db.summary_bias_matches.find(
        {"category": category, "completed": True},
        {"_id": 0, "original_match_id": 1, "judge_key": 1, "summary_key": 1}
    ):
        done_set.add((doc["original_match_id"], doc["judge_key"], doc["summary_key"]))

    experiment_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    sem = asyncio.Semaphore(parallel)
    prompt_config = DEFAULT_EVALUATION_PROMPT

    async def run_one(match, judge_model, summary_model):
        nonlocal completed
        jk = _mk(judge_model)
        sk = _mk(summary_model)

        if (match["id"], jk, sk) in done_set:
            completed += 1
            _state["progress"]["completed"] = completed
            return

        p1_id, p2_id = match["paper1_id"], match["paper2_id"]
        p1 = {**paper_lookup[p1_id], "ai_impact_summary": sum_lookup.get((p1_id, sk), "")}
        p2 = {**paper_lookup[p2_id], "ai_impact_summary": sum_lookup.get((p2_id, sk), "")}

        swapped = random.random() < 0.5
        pa, pb = (p2, p1) if swapped else (p1, p2)

        async with sem:
            doc = {
                "id": str(uuid.uuid4()),
                "experiment_id": experiment_id,
                "category": category,
                "original_match_id": match["id"],
                "paper1_id": p1_id,
                "paper2_id": p2_id,
                "original_winner_id": match["winner_id"],
                "judge_key": jk,
                "summary_key": sk,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                result = await compare_papers(
                    pa, pb, prompt_config,
                    content_mode="abstract_plus_summary",
                    model_override=judge_model,
                )
                winner_key = result.get("winner", "paper1")
                if swapped:
                    winner_id = p2_id if winner_key == "paper1" else p1_id
                else:
                    winner_id = p1_id if winner_key == "paper1" else p2_id

                doc.update({
                    "winner_id": winner_id,
                    "reasoning": result.get("reasoning", ""),
                    "completed": True,
                    "failed": False,
                })
            except Exception as e:
                doc.update({"winner_id": None, "completed": False, "failed": True, "error": str(e)[:200]})

            await db.summary_bias_matches.insert_one(doc)
            completed += 1
            _state["progress"]["completed"] = completed
            if completed % 100 == 0:
                logger.info(f"Summary bias experiment: {completed}/{total_work}")

    work = [(m, j, s) for m in selected for j, s in configs]
    random.shuffle(work)
    await asyncio.gather(*(run_one(m, j, s) for m, j, s in work))
    logger.info(f"Summary bias experiment complete: {completed}/{total_work}")


# ─── Phase 3: Full PDF Baseline ──────────────────────────────────────────

@router.post("/run-fullpdf-baseline", dependencies=[Depends(verify_admin)])
async def run_fullpdf_baseline(body: PipelineRequest):
    if _state["phase"] != "idle":
        return {"status": "already_running", "phase": _state["phase"], "progress": _state["progress"]}
    async def _standalone():
        try:
            await _do_run_fullpdf_baseline(body.category, body.parallel)
        finally:
            _state["phase"] = "idle"
            _state["progress"] = {}
    asyncio.create_task(_standalone())
    return {"status": "started", "category": body.category}


async def _do_run_fullpdf_baseline(category: str, parallel: int):
    _state["phase"] = "running_fullpdf"

    # Get the same matches used in the summary experiment
    distinct_ids = await db.summary_bias_matches.distinct(
        "original_match_id", {"category": category, "completed": True, "summary_key": {"$ne": "full_pdf"}}
    )
    if not distinct_ids:
        logger.warning("Summary bias fullpdf: no experiment matches found")
        _state["phase"] = "idle"
        _state["progress"] = {}
        return

    original_matches = await db.matches.find(
        {"id": {"$in": distinct_ids}},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
    ).to_list(1000)

    # Need full_text for full_pdf mode
    papers = await db.papers.find({"categories": category}, {"_id": 0}).to_list(500)
    paper_lookup = {p["id"]: p for p in papers}

    total_work = len(original_matches) * len(TOURNAMENT_MODELS)
    completed = 0
    _state["progress"] = {"completed": 0, "total": total_work, "category": category}

    done_set = set()
    async for doc in db.summary_bias_matches.find(
        {"category": category, "summary_key": "full_pdf", "completed": True},
        {"_id": 0, "original_match_id": 1, "judge_key": 1}
    ):
        done_set.add((doc["original_match_id"], doc["judge_key"]))

    sem = asyncio.Semaphore(parallel)
    prompt_config = DEFAULT_EVALUATION_PROMPT

    async def run_one(match, judge_model):
        nonlocal completed
        jk = _mk(judge_model)

        if (match["id"], jk) in done_set:
            completed += 1
            _state["progress"]["completed"] = completed
            return

        p1_id, p2_id = match["paper1_id"], match["paper2_id"]
        if p1_id not in paper_lookup or p2_id not in paper_lookup:
            completed += 1
            _state["progress"]["completed"] = completed
            return

        p1, p2 = paper_lookup[p1_id], paper_lookup[p2_id]
        swapped = random.random() < 0.5
        pa, pb = (p2, p1) if swapped else (p1, p2)

        async with sem:
            doc = {
                "id": str(uuid.uuid4()),
                "experiment_id": "fullpdf_baseline",
                "category": category,
                "original_match_id": match["id"],
                "paper1_id": p1_id,
                "paper2_id": p2_id,
                "original_winner_id": match["winner_id"],
                "judge_key": jk,
                "summary_key": "full_pdf",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                result = await compare_papers(
                    pa, pb, prompt_config,
                    content_mode="full_pdf",
                    model_override=judge_model,
                )
                winner_key = result.get("winner", "paper1")
                if swapped:
                    winner_id = p2_id if winner_key == "paper1" else p1_id
                else:
                    winner_id = p1_id if winner_key == "paper1" else p2_id
                doc.update({"winner_id": winner_id, "reasoning": result.get("reasoning", ""), "completed": True, "failed": False})
            except Exception as e:
                doc.update({"winner_id": None, "completed": False, "failed": True, "error": str(e)[:200]})

            await db.summary_bias_matches.insert_one(doc)
            completed += 1
            _state["progress"]["completed"] = completed
            if completed % 50 == 0:
                logger.info(f"Summary bias fullpdf: {completed}/{total_work}")

    work = [(m, j) for m in original_matches for j in TOURNAMENT_MODELS]
    random.shuffle(work)
    await asyncio.gather(*(run_one(m, j) for m, j in work))
    logger.info(f"Summary bias fullpdf baseline complete: {completed}/{total_work}")


# ─── Status ──────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(category: str = Query("q-bio.BM")):
    summaries = await db.summary_bias_summaries.count_documents({"category": category})
    matches_ok = await db.summary_bias_matches.count_documents({"category": category, "completed": True, "summary_key": {"$ne": "full_pdf"}})
    matches_fail = await db.summary_bias_matches.count_documents({"category": category, "failed": True, "summary_key": {"$ne": "full_pdf"}})
    fullpdf_ok = await db.summary_bias_matches.count_documents({"category": category, "completed": True, "summary_key": "full_pdf"})
    fullpdf_fail = await db.summary_bias_matches.count_documents({"category": category, "failed": True, "summary_key": "full_pdf"})

    pipeline = [
        {"$match": {"category": category}},
        {"$group": {"_id": "$model_key", "count": {"$sum": 1}}}
    ]
    per_model = {r["_id"]: r["count"] async for r in db.summary_bias_summaries.aggregate(pipeline)}

    return {
        "category": category,
        "summaries_generated": summaries,
        "summaries_per_model": per_model,
        "matches_completed": matches_ok,
        "matches_failed": matches_fail,
        "fullpdf_completed": fullpdf_ok,
        "fullpdf_failed": fullpdf_fail,
        "phase": _state["phase"],
        "progress": _state["progress"],
    }


# ─── Results ─────────────────────────────────────────────────────────────

@router.get("/results")
async def get_results(category: str = Query("q-bio.BM")):
    all_docs = await db.summary_bias_matches.find(
        {"category": category, "completed": True, "failed": {"$ne": True}},
        {"_id": 0}
    ).to_list(100000)

    # Separate summary experiment matches from full-pdf baseline
    matches = [m for m in all_docs if m.get("summary_key") != "full_pdf"]
    fullpdf_docs = [m for m in all_docs if m.get("summary_key") == "full_pdf"]

    if not matches:
        return {"status": "no_data"}

    # Group by original_match_id -> {config_key: winner_id}
    by_match = defaultdict(dict)
    original_winners = {}
    for m in matches:
        ck = f"{m['judge_key']}|{m['summary_key']}"
        by_match[m["original_match_id"]][ck] = m["winner_id"]
        if m["original_match_id"] not in original_winners:
            original_winners[m["original_match_id"]] = m.get("original_winner_id")

    config_keys = sorted({ck for configs in by_match.values() for ck in configs})
    full = {mid: c for mid, c in by_match.items() if len(c) >= len(config_keys)}

    if len(full) < 5:
        return {"status": "insufficient_data", "full_matches": len(full), "partial_matches": len(by_match)}

    n = len(full)
    judges = sorted({ck.split("|")[0] for ck in config_keys})
    summarizers = sorted({ck.split("|")[1] for ck in config_keys})

    # ── Full-PDF baseline: per-judge winners ──
    fullpdf_by_match = defaultdict(dict)  # original_match_id -> {judge_key: winner_id}
    for m in fullpdf_docs:
        fullpdf_by_match[m["original_match_id"]][m["judge_key"]] = m["winner_id"]

    has_fullpdf = len(fullpdf_by_match) > 0

    # Full-PDF majority vote (across 3 judges on full text)
    fullpdf_majority = {}
    for mid, jverdicts in fullpdf_by_match.items():
        if mid not in full:
            continue
        c = Counter(jverdicts.values())
        best, cnt = c.most_common(1)[0]
        if cnt > len(jverdicts) / 2:
            fullpdf_majority[mid] = best

    # ── Consensus (majority vote across all 9 summary configs) ──
    consensus = {}
    for mid, configs in full.items():
        c = Counter(configs.values())
        best, cnt = c.most_common(1)[0]
        if cnt > len(configs) / 2:
            consensus[mid] = best

    # ── Per-config: agreement with original + consensus + full-pdf ──
    vs_original = {}
    vs_consensus = {}
    vs_fullpdf_same_judge = {}  # Agreement with the SAME judge's full-PDF verdict
    vs_fullpdf_majority = {}   # Agreement with full-PDF majority vote
    for ck in config_keys:
        orig_agree = orig_total = cons_agree = cons_total = 0
        fp_same_agree = fp_same_total = fp_maj_agree = fp_maj_total = 0
        judge_key = ck.split("|")[0]
        for mid, configs in full.items():
            if ck not in configs:
                continue
            if mid in original_winners and original_winners[mid]:
                orig_total += 1
                if configs[ck] == original_winners[mid]:
                    orig_agree += 1
            if mid in consensus:
                cons_total += 1
                if configs[ck] == consensus[mid]:
                    cons_agree += 1
            # Same judge's full-PDF verdict
            if mid in fullpdf_by_match and judge_key in fullpdf_by_match[mid]:
                fp_same_total += 1
                if configs[ck] == fullpdf_by_match[mid][judge_key]:
                    fp_same_agree += 1
            # Full-PDF majority
            if mid in fullpdf_majority:
                fp_maj_total += 1
                if configs[ck] == fullpdf_majority[mid]:
                    fp_maj_agree += 1

        vs_original[ck] = round(orig_agree / max(orig_total, 1) * 100, 1)
        vs_consensus[ck] = round(cons_agree / max(cons_total, 1) * 100, 1)
        vs_fullpdf_same_judge[ck] = round(fp_same_agree / max(fp_same_total, 1) * 100, 1) if fp_same_total else None
        vs_fullpdf_majority[ck] = round(fp_maj_agree / max(fp_maj_total, 1) * 100, 1) if fp_maj_total else None

    # ── 3x3 grids ──
    def build_grid(data_map):
        return [[data_map.get(f"{j}|{s}", 0) for s in summarizers] for j in judges]

    grid_consensus = build_grid(vs_consensus)
    grid_original = build_grid(vs_original)
    grid_fullpdf_same = build_grid(vs_fullpdf_same_judge) if has_fullpdf else None
    grid_fullpdf_maj = build_grid(vs_fullpdf_majority) if has_fullpdf else None

    # ── Full-PDF per-judge stats ──
    fullpdf_stats = None
    if has_fullpdf:
        fullpdf_stats = {}
        for j in judges:
            jk = j
            # Agreement between this judge's full-PDF verdict and original extract verdict
            fp_vs_orig_agree = fp_vs_orig_total = 0
            for mid in full:
                if mid in fullpdf_by_match and jk in fullpdf_by_match[mid] and mid in original_winners and original_winners[mid]:
                    fp_vs_orig_total += 1
                    if fullpdf_by_match[mid][jk] == original_winners[mid]:
                        fp_vs_orig_agree += 1
            fullpdf_stats[_short(j)] = {
                "matches": sum(1 for mid in full if mid in fullpdf_by_match and jk in fullpdf_by_match[mid]),
                "vs_original": round(fp_vs_orig_agree / max(fp_vs_orig_total, 1) * 100, 1) if fp_vs_orig_total else None,
            }
        # Full-PDF inter-judge agreement
        fp_inter = []
        for i, j1 in enumerate(judges):
            for j2 in judges[i + 1:]:
                agree = total = 0
                for mid in full:
                    if mid in fullpdf_by_match and j1 in fullpdf_by_match[mid] and j2 in fullpdf_by_match[mid]:
                        total += 1
                        if fullpdf_by_match[mid][j1] == fullpdf_by_match[mid][j2]:
                            agree += 1
                if total:
                    fp_inter.append(round(agree / total * 100, 1))
        fullpdf_stats["_inter_judge_agreement"] = round(sum(fp_inter) / max(len(fp_inter), 1), 1) if fp_inter else None

    # ── Pairwise inter-config agreement ──
    pairwise = {}
    for i, c1 in enumerate(config_keys):
        for c2 in config_keys[i + 1:]:
            agree = sum(1 for configs in full.values() if configs.get(c1) == configs.get(c2))
            pairwise[f"{c1} vs {c2}"] = {"agree": agree, "total": n, "rate": round(agree / n * 100, 1)}

    # ── Self-bias: does a judge agree more with its own summaries? ──
    self_bias = {}
    for j in judges:
        own_ck = f"{j}|{j}"
        own_rate = vs_consensus.get(own_ck, 0)
        other_rates = [vs_consensus.get(f"{j}|{s}", 0) for s in summarizers if s != j]
        avg_other = round(sum(other_rates) / max(len(other_rates), 1), 1)
        self_bias[_short(j)] = {
            "own_summary_rate": own_rate,
            "other_summary_avg": avg_other,
            "bias": round(own_rate - avg_other, 1),
        }

    # ── Judge consistency: given same summary, how often do judges agree? ──
    judge_consistency = {}
    for s in summarizers:
        rates = []
        for i, j1 in enumerate(judges):
            for j2 in judges[i + 1:]:
                ck1, ck2 = f"{j1}|{s}", f"{j2}|{s}"
                agree = sum(1 for c in full.values() if c.get(ck1) == c.get(ck2))
                rates.append(round(agree / n * 100, 1))
        judge_consistency[_short(s)] = {
            "avg_agreement": round(sum(rates) / max(len(rates), 1), 1),
            "pairs": rates,
        }

    # ── Summary influence: given same judge, how often does summary choice change the outcome? ──
    summary_influence = {}
    for j in judges:
        rates = []
        for i, s1 in enumerate(summarizers):
            for s2 in summarizers[i + 1:]:
                ck1, ck2 = f"{j}|{s1}", f"{j}|{s2}"
                agree = sum(1 for c in full.values() if c.get(ck1) == c.get(ck2))
                rates.append(round(agree / n * 100, 1))
        summary_influence[_short(j)] = {
            "avg_consistency": round(sum(rates) / max(len(rates), 1), 1),
            "pairs": rates,
        }

    # ── Full agreement (all 9 configs agree) ──
    unanimous = sum(1 for c in full.values() if len(set(c.values())) == 1)

    return {
        "status": "ok",
        "category": category,
        "num_matches": n,
        "total_evaluations": len(matches),
        "judges": [_short(j) for j in judges],
        "summarizers": [_short(s) for s in summarizers],
        "judge_keys": judges,
        "summarizer_keys": summarizers,
        "grid_consensus": grid_consensus,
        "grid_original": grid_original,
        "grid_fullpdf_same_judge": grid_fullpdf_same,
        "grid_fullpdf_majority": grid_fullpdf_maj,
        "fullpdf_stats": fullpdf_stats,
        "fullpdf_matches": len(fullpdf_by_match),
        "self_bias": self_bias,
        "judge_consistency": judge_consistency,
        "summary_influence": summary_influence,
        "unanimous_matches": unanimous,
        "unanimous_rate": round(unanimous / n * 100, 1),
        "consensus_matches": len(consensus),
        "consensus_rate": round(len(consensus) / n * 100, 1),
    }


# ─── Convergence ─────────────────────────────────────────────────────────

@router.get("/convergence")
async def get_convergence(category: str = Query("q-bio.BM"), steps: int = Query(15)):
    """How fast does the summary-based tournament ranking converge?

    Compares against:
    1. Extract-based tournament ranking (from main matches, ~2000 matches) as ground truth
    2. Full-PDF baseline ranking (from 200 matches × 3 judges)
    3. Internal stability (ranking at N vs final ranking)
    """
    from scipy import stats as scipy_stats

    # Get papers
    papers = await db.papers.find({"categories": category}, {"_id": 0}).to_list(500)
    if not papers:
        return {"status": "no_data"}
    paper_lookup = {p["id"]: p for p in papers}
    paper_ids = set(paper_lookup.keys())

    # ── Reference 1: Extract-based ranking from main tournament ──
    main_matches = await db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "primary_category": category},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1}
    ).to_list(100000)
    extract_lb = compute_leaderboard(papers, main_matches)
    extract_rank = {e["id"]: e["rank"] for e in extract_lb}

    # ── Get summary-bias matches (consensus) ──
    all_docs = await db.summary_bias_matches.find(
        {"category": category, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "original_match_id": 1, "paper1_id": 1, "paper2_id": 1,
         "winner_id": 1, "judge_key": 1, "summary_key": 1, "created_at": 1}
    ).to_list(100000)

    summary_docs = [m for m in all_docs if m.get("summary_key") != "full_pdf"]
    fullpdf_docs = [m for m in all_docs if m.get("summary_key") == "full_pdf"]

    # ── Build random-single matches: for each match, pick 1 random verdict from the 9 configs ──
    # This is fair: 1 LLM call per match, random model diversity (like extract's round-robin)
    by_match_all = defaultdict(list)  # original_match_id -> list of (paper1_id, paper2_id, winner_id)
    for m in summary_docs:
        by_match_all[m["original_match_id"]].append({
            "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
            "winner_id": m["winner_id"],
        })

    random.seed(42)
    random_single_matches = []
    for mid, verdicts in by_match_all.items():
        pick = random.choice(verdicts)
        random_single_matches.append({
            "paper1_id": pick["paper1_id"], "paper2_id": pick["paper2_id"],
            "winner_id": pick["winner_id"], "completed": True, "failed": False,
        })
    random.shuffle(random_single_matches)

    # ── Reference 2: Full-PDF ranking (also random-single: pick 1 of 3 judges) ──
    fp_by_match = defaultdict(list)
    for m in fullpdf_docs:
        fp_by_match[m["original_match_id"]].append({
            "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
            "winner_id": m["winner_id"],
        })

    fullpdf_single_matches = []
    for mid, verdicts in fp_by_match.items():
        pick = random.choice(verdicts)
        fullpdf_single_matches.append({
            "paper1_id": pick["paper1_id"], "paper2_id": pick["paper2_id"],
            "winner_id": pick["winner_id"], "completed": True, "failed": False,
        })

    fullpdf_lb = compute_leaderboard(papers, fullpdf_single_matches) if fullpdf_single_matches else []
    fullpdf_rank = {e["id"]: e["rank"] for e in fullpdf_lb}

    # ── Final summary ranking (all random-single matches) ──
    final_lb = compute_leaderboard(papers, random_single_matches)
    final_rank = {e["id"]: e["rank"] for e in final_lb}

    # ── Convergence curve (random-single: 1 call per match) ──
    total = len(random_single_matches)
    if total < 10:
        return {"status": "insufficient_data", "random_single_matches": total}

    step_size = max(1, total // steps)
    x_values = list(range(step_size, total + 1, step_size))
    if x_values[-1] < total:
        x_values.append(total)

    curve = []
    for n_matches in x_values:
        subset = random_single_matches[:n_matches]
        sub_lb = compute_leaderboard(papers, subset)
        sub_rank = {e["id"]: e["rank"] for e in sub_lb}

        # Papers that have matches in this subset
        active = {m["paper1_id"] for m in subset} | {m["paper2_id"] for m in subset}
        active = active & paper_ids

        point = {"matches": n_matches, "papers_covered": len(active)}

        # Correlation with extract-based ranking
        common_ext = [pid for pid in active if pid in extract_rank and pid in sub_rank]
        if len(common_ext) >= 3:
            sp, _ = scipy_stats.spearmanr(
                [sub_rank[p] for p in common_ext],
                [extract_rank[p] for p in common_ext]
            )
            point["vs_extract_spearman"] = round(sp, 4) if not (sp != sp) else 0
        else:
            point["vs_extract_spearman"] = None

        # Correlation with full-PDF ranking
        if fullpdf_rank:
            common_fp = [pid for pid in active if pid in fullpdf_rank and pid in sub_rank]
            if len(common_fp) >= 3:
                sp, _ = scipy_stats.spearmanr(
                    [sub_rank[p] for p in common_fp],
                    [fullpdf_rank[p] for p in common_fp]
                )
                point["vs_fullpdf_spearman"] = round(sp, 4) if not (sp != sp) else 0
            else:
                point["vs_fullpdf_spearman"] = None

        # Internal stability (vs final ranking)
        common_final = [pid for pid in active if pid in final_rank and pid in sub_rank]
        if len(common_final) >= 3:
            sp, _ = scipy_stats.spearmanr(
                [sub_rank[p] for p in common_final],
                [final_rank[p] for p in common_final]
            )
            point["vs_final_spearman"] = round(sp, 4) if not (sp != sp) else 0
        else:
            point["vs_final_spearman"] = None

        # Avg matches per paper
        counts = defaultdict(int)
        for m in subset:
            counts[m["paper1_id"]] += 1
            counts[m["paper2_id"]] += 1
        active_counts = [counts[p] for p in active if counts[p] > 0]
        point["avg_matches_per_paper"] = round(sum(active_counts) / max(len(active_counts), 1), 1)
        point["llm_calls_per_paper"] = point["avg_matches_per_paper"]  # 1:1 for random-single

        curve.append(point)

    # ── Also compute per-config convergence (each of 9 configs separately) ──
    config_final_ranks = {}
    config_keys = sorted({f"{m['judge_key']}|{m['summary_key']}" for m in summary_docs})
    for ck in config_keys:
        ck_matches = [{
            "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
            "winner_id": m["winner_id"], "completed": True, "failed": False,
        } for m in summary_docs if f"{m['judge_key']}|{m['summary_key']}" == ck]
        ck_lb = compute_leaderboard(papers, ck_matches)
        config_final_ranks[ck] = {e["id"]: e["rank"] for e in ck_lb}

    # Correlation of each config's ranking with extract and full-PDF
    config_correlations = {}
    for ck, ranks in config_final_ranks.items():
        common_ext = [pid for pid in paper_ids if pid in extract_rank and pid in ranks]
        common_fp = [pid for pid in paper_ids if pid in fullpdf_rank and pid in ranks] if fullpdf_rank else []

        entry = {"label": f"{_short(ck.split('|')[0])} + {_short(ck.split('|')[1])} sum"}
        if len(common_ext) >= 3:
            sp, _ = scipy_stats.spearmanr([ranks[p] for p in common_ext], [extract_rank[p] for p in common_ext])
            entry["vs_extract"] = round(sp, 4) if not (sp != sp) else 0
        if len(common_fp) >= 3:
            sp, _ = scipy_stats.spearmanr([ranks[p] for p in common_fp], [fullpdf_rank[p] for p in common_fp])
            entry["vs_fullpdf"] = round(sp, 4) if not (sp != sp) else 0
        config_correlations[ck] = entry

    # ── Extract convergence curve (same x-axis: avg matches per paper) ──
    extract_curve = []
    if fullpdf_rank and main_matches:
        random.seed(42)
        shuffled_extract = list(main_matches)
        random.shuffle(shuffled_extract)

        # Use the same avg-matches-per-paper steps as the summary curve
        target_avgs = [p["avg_matches_per_paper"] for p in curve]
        # Also add higher steps up to the full extract dataset
        total_ext = len(shuffled_extract)
        full_counts = defaultdict(int)
        for m in shuffled_extract:
            if m["paper1_id"] in paper_ids:
                full_counts[m["paper1_id"]] += 1
            if m["paper2_id"] in paper_ids:
                full_counts[m["paper2_id"]] += 1
        max_ext_avg = sum(full_counts[p] for p in paper_ids if full_counts[p] > 0) / max(sum(1 for p in paper_ids if full_counts[p] > 0), 1)

        # Add steps beyond the summary range up to extract max
        extra_steps = [round(max_ext_avg * f) for f in [0.25, 0.5, 0.75, 1.0]]
        all_targets = sorted(set(target_avgs + extra_steps))

        for target_avg in all_targets:
            # Binary search for the number of matches that gives this avg
            lo, hi = 1, total_ext
            best_n = total_ext
            while lo <= hi:
                mid = (lo + hi) // 2
                counts = defaultdict(int)
                for m in shuffled_extract[:mid]:
                    if m["paper1_id"] in paper_ids:
                        counts[m["paper1_id"]] += 1
                    if m["paper2_id"] in paper_ids:
                        counts[m["paper2_id"]] += 1
                active_pids = [p for p in paper_ids if counts[p] > 0]
                if not active_pids:
                    lo = mid + 1
                    continue
                avg = sum(counts[p] for p in active_pids) / len(active_pids)
                if avg < target_avg:
                    lo = mid + 1
                else:
                    best_n = mid
                    hi = mid - 1

            subset = shuffled_extract[:best_n]
            sub_lb = compute_leaderboard(papers, subset)
            sub_rank = {e["id"]: e["rank"] for e in sub_lb}
            active = {m["paper1_id"] for m in subset if m["paper1_id"] in paper_ids} | {m["paper2_id"] for m in subset if m["paper2_id"] in paper_ids}

            counts = defaultdict(int)
            for m in subset:
                if m["paper1_id"] in paper_ids:
                    counts[m["paper1_id"]] += 1
                if m["paper2_id"] in paper_ids:
                    counts[m["paper2_id"]] += 1
            active_counts = [counts[p] for p in active if counts[p] > 0]
            actual_avg = round(sum(active_counts) / max(len(active_counts), 1), 1)

            common_fp = [pid for pid in active if pid in fullpdf_rank and pid in sub_rank]
            fp_rho = None
            if len(common_fp) >= 3:
                sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common_fp], [fullpdf_rank[p] for p in common_fp])
                fp_rho = round(sp, 4) if not (sp != sp) else 0

            extract_curve.append({
                "matches": best_n,
                "avg_matches_per_paper": actual_avg,
                "vs_fullpdf_spearman": fp_rho,
                "papers_covered": len(active),
            })

    # ── Per-summarizer convergence curves ──
    # For each summary model, take the 3-judge majority and build a convergence curve
    summarizer_keys = sorted({m["summary_key"] for m in summary_docs})
    summarizer_curves = {}
    for sk in summarizer_keys:
        # Get all matches judged using this summary model (3 judges)
        sk_by_match = defaultdict(list)
        sk_match_papers = {}
        for m in summary_docs:
            if m["summary_key"] == sk:
                sk_by_match[m["original_match_id"]].append(m["winner_id"])
                sk_match_papers[m["original_match_id"]] = (m["paper1_id"], m["paper2_id"])

        # Build majority-vote matches for this summarizer
        sk_consensus = []
        for mid, winners in sk_by_match.items():
            c = Counter(winners)
            best, cnt = c.most_common(1)[0]
            p1, p2 = sk_match_papers[mid]
            sk_consensus.append({
                "paper1_id": p1, "paper2_id": p2,
                "winner_id": best, "completed": True, "failed": False,
            })

        random.seed(42)
        random.shuffle(sk_consensus)

        sk_total = len(sk_consensus)
        sk_step = max(1, sk_total // steps)
        sk_x = list(range(sk_step, sk_total + 1, sk_step))
        if sk_x and sk_x[-1] < sk_total:
            sk_x.append(sk_total)

        sk_curve = []
        for n_m in sk_x:
            subset = sk_consensus[:n_m]
            sub_lb = compute_leaderboard(papers, subset)
            sub_rank = {e["id"]: e["rank"] for e in sub_lb}
            active = ({m["paper1_id"] for m in subset} | {m["paper2_id"] for m in subset}) & paper_ids

            counts = defaultdict(int)
            for m in subset:
                if m["paper1_id"] in paper_ids:
                    counts[m["paper1_id"]] += 1
                if m["paper2_id"] in paper_ids:
                    counts[m["paper2_id"]] += 1
            ac = [counts[p] for p in active if counts[p] > 0]
            avg_mpp = round(sum(ac) / max(len(ac), 1), 1)

            fp_rho = None
            if fullpdf_rank:
                common_fp = [pid for pid in active if pid in fullpdf_rank and pid in sub_rank]
                if len(common_fp) >= 3:
                    sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common_fp], [fullpdf_rank[p] for p in common_fp])
                    fp_rho = round(sp, 4) if not (sp != sp) else 0

            sk_curve.append({
                "matches": n_m,
                "avg_matches_per_paper": avg_mpp,
                "llm_calls_per_paper": round(avg_mpp * 3, 1),
                "vs_fullpdf_spearman": fp_rho,
            })

        summarizer_curves[_short(sk)] = sk_curve

    # ── Single-config curves (1 judge + 1 summarizer = 1 LLM call per match) ──
    single_config_curves = {}
    for sk in summarizer_keys:
        for jk in sorted({m["judge_key"] for m in summary_docs}):
            ck_matches = [{
                "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                "winner_id": m["winner_id"], "completed": True, "failed": False,
            } for m in summary_docs if m["judge_key"] == jk and m["summary_key"] == sk]

            if len(ck_matches) < 10:
                continue

            random.seed(42)
            random.shuffle(ck_matches)
            ck_total = len(ck_matches)
            ck_step = max(1, ck_total // steps)
            ck_x = list(range(ck_step, ck_total + 1, ck_step))
            if ck_x and ck_x[-1] < ck_total:
                ck_x.append(ck_total)

            ck_curve = []
            for n_m in ck_x:
                subset = ck_matches[:n_m]
                sub_lb = compute_leaderboard(papers, subset)
                sub_rank = {e["id"]: e["rank"] for e in sub_lb}
                active = ({m["paper1_id"] for m in subset} | {m["paper2_id"] for m in subset}) & paper_ids
                counts = defaultdict(int)
                for m in subset:
                    if m["paper1_id"] in paper_ids:
                        counts[m["paper1_id"]] += 1
                    if m["paper2_id"] in paper_ids:
                        counts[m["paper2_id"]] += 1
                ac = [counts[p] for p in active if counts[p] > 0]
                avg_mpp = round(sum(ac) / max(len(ac), 1), 1)
                fp_rho = None
                if fullpdf_rank:
                    common_fp = [pid for pid in active if pid in fullpdf_rank and pid in sub_rank]
                    if len(common_fp) >= 3:
                        sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common_fp], [fullpdf_rank[p] for p in common_fp])
                        fp_rho = round(sp, 4) if not (sp != sp) else 0
                ck_curve.append({
                    "matches": n_m,
                    "avg_matches_per_paper": avg_mpp,
                    "llm_calls_per_paper": avg_mpp,
                    "vs_fullpdf_spearman": fp_rho,
                })
            single_config_curves[f"{_short(jk)} + {_short(sk)} sum"] = ck_curve

    for p in extract_curve:
        p["llm_calls_per_paper"] = p["avg_matches_per_paper"]

    # ── Per-summarizer curves with random judge (1 call/match, fixed summarizer) ──
    summarizer_random_curves = {}
    for sk in summarizer_keys:
        # For each match, pick 1 random judge using this summarizer
        sk_by_match = defaultdict(list)
        for m in summary_docs:
            if m["summary_key"] == sk:
                sk_by_match[m["original_match_id"]].append({
                    "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                    "winner_id": m["winner_id"],
                })

        random.seed(42)
        sk_matches = []
        for mid, verdicts in sk_by_match.items():
            pick = random.choice(verdicts)
            sk_matches.append({
                "paper1_id": pick["paper1_id"], "paper2_id": pick["paper2_id"],
                "winner_id": pick["winner_id"], "completed": True, "failed": False,
            })
        random.shuffle(sk_matches)

        sk_total = len(sk_matches)
        sk_step = max(1, sk_total // steps)
        sk_x = list(range(sk_step, sk_total + 1, sk_step))
        if sk_x and sk_x[-1] < sk_total:
            sk_x.append(sk_total)

        sk_curve = []
        for n_m in sk_x:
            subset = sk_matches[:n_m]
            sub_lb = compute_leaderboard(papers, subset)
            sub_rank = {e["id"]: e["rank"] for e in sub_lb}
            active = ({m["paper1_id"] for m in subset} | {m["paper2_id"] for m in subset}) & paper_ids
            counts = defaultdict(int)
            for m in subset:
                if m["paper1_id"] in paper_ids:
                    counts[m["paper1_id"]] += 1
                if m["paper2_id"] in paper_ids:
                    counts[m["paper2_id"]] += 1
            ac = [counts[p] for p in active if counts[p] > 0]
            avg_mpp = round(sum(ac) / max(len(ac), 1), 1)

            fp_rho = None
            if fullpdf_rank:
                common_fp = [pid for pid in active if pid in fullpdf_rank and pid in sub_rank]
                if len(common_fp) >= 3:
                    sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common_fp], [fullpdf_rank[p] for p in common_fp])
                    fp_rho = round(sp, 4) if not (sp != sp) else 0

            sk_curve.append({
                "matches": n_m,
                "avg_matches_per_paper": avg_mpp,
                "llm_calls_per_paper": avg_mpp,
                "vs_fullpdf_spearman": fp_rho,
            })

        summarizer_random_curves[_short(sk)] = sk_curve

    # ── Per-judge curves with random summarizer (1 call/match, fixed judge) ──
    judge_keys = sorted({m["judge_key"] for m in summary_docs})
    judge_random_curves = {}
    for jk in judge_keys:
        jk_by_match = defaultdict(list)
        for m in summary_docs:
            if m["judge_key"] == jk:
                jk_by_match[m["original_match_id"]].append({
                    "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                    "winner_id": m["winner_id"],
                })

        random.seed(42)
        jk_matches = []
        for mid, verdicts in jk_by_match.items():
            pick = random.choice(verdicts)
            jk_matches.append({
                "paper1_id": pick["paper1_id"], "paper2_id": pick["paper2_id"],
                "winner_id": pick["winner_id"], "completed": True, "failed": False,
            })
        random.shuffle(jk_matches)

        jk_total = len(jk_matches)
        jk_step = max(1, jk_total // steps)
        jk_x = list(range(jk_step, jk_total + 1, jk_step))
        if jk_x and jk_x[-1] < jk_total:
            jk_x.append(jk_total)

        jk_curve = []
        for n_m in jk_x:
            subset = jk_matches[:n_m]
            sub_lb = compute_leaderboard(papers, subset)
            sub_rank = {e["id"]: e["rank"] for e in sub_lb}
            active = ({m["paper1_id"] for m in subset} | {m["paper2_id"] for m in subset}) & paper_ids
            counts = defaultdict(int)
            for m in subset:
                if m["paper1_id"] in paper_ids:
                    counts[m["paper1_id"]] += 1
                if m["paper2_id"] in paper_ids:
                    counts[m["paper2_id"]] += 1
            ac = [counts[p] for p in active if counts[p] > 0]
            avg_mpp = round(sum(ac) / max(len(ac), 1), 1)

            fp_rho = None
            if fullpdf_rank:
                common_fp = [pid for pid in active if pid in fullpdf_rank and pid in sub_rank]
                if len(common_fp) >= 3:
                    sp, _ = scipy_stats.spearmanr([sub_rank[p] for p in common_fp], [fullpdf_rank[p] for p in common_fp])
                    fp_rho = round(sp, 4) if not (sp != sp) else 0

            jk_curve.append({
                "matches": n_m,
                "avg_matches_per_paper": avg_mpp,
                "llm_calls_per_paper": avg_mpp,
                "vs_fullpdf_spearman": fp_rho,
            })

        judge_random_curves[_short(jk)] = jk_curve

    return {
        "status": "ok",
        "category": category,
        "total_summary_matches": total,
        "total_extract_matches": len(main_matches),
        "total_fullpdf_matches": len(fullpdf_single_matches),
        "papers": len(papers),
        "curve": curve,
        "extract_curve": extract_curve,
        "summarizer_curves": summarizer_curves,
        "summarizer_random_curves": summarizer_random_curves,
        "judge_random_curves": judge_random_curves,
        "single_config_curves": single_config_curves,
        "config_correlations": config_correlations,
    }
