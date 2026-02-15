"""
Qeios Synced Pairwise Comparison — Abstract vs Extract head-to-head.

Fetches reviewer pairs from Qeios/Crossref, evaluates each pair in both
abstract-only and full-text modes using all 3 models, stores results in
separate collections for direct comparison.
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
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List

from core.config import db, logger, DEFAULT_EVALUATION_PROMPT, TOURNAMENT_MODELS
from core.auth import verify_admin
from services.llm import compare_papers, generate_precomparison_impact_summary

router = APIRouter(prefix="/api/qeios")

CROSSREF_HEADERS = {"User-Agent": "PaperSumo/1.0 (mailto:test@example.com)"}
_crossref_cache = {"data": None, "ts": 0, "ttl": 300}

_pw_abs_state = {"fetching": False, "running": False, "progress": {}}
_pw_ext_state = {"fetching": False, "running": False, "progress": {}}
_pw_summary_state = {"fetching": False, "running": False, "progress": {}}


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            return await resp.text()
    except Exception:
        return ""


def _parse_qeios_html(html: str) -> dict:
    result = {}
    pub_idx = html.find('publication = {')
    if pub_idx < 0:
        return result
    pub_chunk = html[pub_idx:]

    idx = pub_chunk.find('"domain_name"')
    if idx >= 0:
        m = re.search(r':\s*"([^"]+)"', pub_chunk[idx + 13:idx + 100])
        if m:
            result["domain"] = m.group(1)

    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)+)"', pub_chunk[:500])
    if m:
        raw = m.group(1).replace('\\"', '"').replace('\\/', '/')
        result["title"] = re.sub(r'<[^>]+>', '', raw).strip()

    idx = pub_chunk.find('"abstract"')
    if idx >= 0:
        m = re.search(r':\s*"((?:[^"\\]|\\.)+)"', pub_chunk[idx + 10:idx + 10000])
        if m:
            raw = m.group(1).replace('\\"', '"').replace('\\/', '/')
            result["abstract"] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw)).strip()

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
    m = re.search(r'"borne_rating"\s*:\s*(\d+(?:\.\d+)?)', html)
    return float(m.group(1)) if m else None


async def _fetch_pair_data(session: aiohttp.ClientSession, reviewer: str, papers: list) -> Optional[dict]:
    """Fetch all data for a single pair asynchronously."""
    try:
        pair_papers = random.sample(papers, min(2, len(papers)))
        if len(pair_papers) < 2:
            return None

        rating_urls = [f"https://www.qeios.com/read/{doi.split('/')[-1].upper()}" for _, doi in pair_papers]
        rating_htmls = await asyncio.gather(*[_fetch_url(session, url) for url in rating_urls])

        ratings = []
        for (paper_doi, review_doi), html in zip(pair_papers, rating_htmls):
            rating = _parse_rating_html(html)
            if rating is not None:
                ratings.append((paper_doi, review_doi, rating))

        if len(ratings) < 2 or ratings[0][2] == ratings[1][2]:
            return None

        human_winner = "paper1" if ratings[0][2] > ratings[1][2] else "paper2"

        paper_urls = [f"https://www.qeios.com/read/{doi.split('/')[-1].upper()}" for doi, _, _ in ratings]
        paper_htmls = await asyncio.gather(*[_fetch_url(session, url) for url in paper_urls])

        paper_data = []
        for (paper_doi, review_doi, rating), html in zip(ratings, paper_htmls):
            page = _parse_qeios_html(html)
            if not page.get("title") or not page.get("abstract"):
                return None
            paper_data.append({
                "doi": paper_doi,
                "qeios_id": paper_doi.split("/")[-1].upper(),
                "title": page.get("title", ""),
                "abstract": page.get("abstract", ""),
                "full_text": page.get("full_text"),
                "domain": page.get("domain", "Unknown"),
                "rating": rating,
            })

        if len(paper_data) < 2:
            return None

        # Both papers must have full text for synced comparison
        if not paper_data[0].get("full_text") or not paper_data[1].get("full_text"):
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
        logger.debug(f"Qeios fetch error for {reviewer}: {e}")
        return None


# ─── Status / Results / Stop ───────────────────────────────────────────────────

def _get_ctx(mode: str):
    if mode == "extract":
        return {"state": _pw_ext_state, "collection": db.qeios_pairwise_extract}
    return {"state": _pw_abs_state, "collection": db.qeios_pairwise_abstract}


@router.get("/pairwise/status")
async def pw_abs_status():
    return await _pw_status("abstract")


@router.get("/pairwise-extract/status")
async def pw_ext_status():
    return await _pw_status("extract")


async def _pw_status(mode: str):
    ctx = _get_ctx(mode)
    coll = ctx["collection"]
    total = await coll.count_documents({})
    completed = await coll.count_documents({"ai_completed": True})
    failed = await coll.count_documents({"ai_failed": True})

    domain_counts = {}
    async for r in coll.aggregate([{"$group": {"_id": "$domain", "count": {"$sum": 1}}}]):
        domain_counts[r["_id"] or "Unknown"] = r["count"]

    return {
        "total_pairs": total,
        "ai_completed": completed,
        "ai_failed": failed,
        "ai_pending": total - completed - failed,
        "by_domain": domain_counts,
        "fetching": ctx["state"]["fetching"],
        "running": ctx["state"]["running"],
        "progress": ctx["state"]["progress"],
        "mode": mode,
    }


@router.get("/pairwise/results")
async def pw_abs_results():
    return await _pw_results("abstract")


@router.get("/pairwise-extract/results")
async def pw_ext_results():
    return await _pw_results("extract")


async def _pw_results(mode: str):
    ctx = _get_ctx(mode)
    pairs = await ctx["collection"].find({"ai_completed": True}, {"_id": 0}).to_list(10000)
    if not pairs:
        return {"status": "no_data", "total": 0, "mode": mode}

    total = len(pairs)

    def _rate(a, t):
        return round(a / max(t, 1) * 100, 1)

    # Per-domain stats (with per-model + per-gap breakdown, like SciPost by_dimension)
    domain_stats = defaultdict(lambda: {
        "maj_agree": 0, "maj_total": 0,
        "models": defaultdict(lambda: {"agree": 0, "total": 0}),
        "gaps": defaultdict(lambda: {"agree": 0, "total": 0}),
    })
    overall_models = defaultdict(lambda: {"agree": 0, "total": 0})

    for p in pairs:
        d = p.get("domain") or "Unknown"
        hw = p.get("human_winner")
        for mk, res in p.get("ai_results", {}).items():
            if res.get("winner"):
                domain_stats[d]["models"][mk]["total"] += 1
                overall_models[mk]["total"] += 1
                if res["winner"] == hw:
                    domain_stats[d]["models"][mk]["agree"] += 1
                    overall_models[mk]["agree"] += 1
        if p.get("ai_majority"):
            domain_stats[d]["maj_total"] += 1
            if p["ai_majority"] == hw:
                domain_stats[d]["maj_agree"] += 1
        gap = p.get("score_gap", abs(p.get("human_score1", 0) - p.get("human_score2", 0)))
        gap_label = "small" if gap <= 1 else "medium" if gap <= 2 else "large"
        if p.get("ai_majority"):
            domain_stats[d]["gaps"][gap_label]["total"] += 1
            if p["ai_majority"] == hw:
                domain_stats[d]["gaps"][gap_label]["agree"] += 1

    # Build structured by_domain (mirrors SciPost by_dimension)
    by_domain = {}
    for d, s in sorted(domain_stats.items(), key=lambda x: -x[1]["maj_total"]):
        by_domain[d] = {
            "majority": {"agree": s["maj_agree"], "total": s["maj_total"], "rate": _rate(s["maj_agree"], s["maj_total"])},
            "by_model": {mk: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for mk, v in s["models"].items()},
            "by_gap": {g: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for g, v in sorted(s["gaps"].items())},
        }

    # Overall majority
    maj_agree = sum(s["maj_agree"] for s in domain_stats.values())
    maj_total = sum(s["maj_total"] for s in domain_stats.values())

    # Overall score gap (aggregated)
    gap_totals = defaultdict(lambda: {"agree": 0, "total": 0})
    for s in domain_stats.values():
        for g, v in s["gaps"].items():
            gap_totals[g]["agree"] += v["agree"]
            gap_totals[g]["total"] += v["total"]

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
        "paper1_title": p["paper1"]["title"][:55] if isinstance(p.get("paper1"), dict) else "",
        "paper2_title": p["paper2"]["title"][:55] if isinstance(p.get("paper2"), dict) else "",
        "domain": p.get("domain", "?"),
        "human_winner": p.get("human_winner"),
        "human_score1": p.get("human_score1"),
        "human_score2": p.get("human_score2"),
        "ai_majority": p.get("ai_majority"),
        "majority_agree": p.get("ai_majority") == p.get("human_winner") if p.get("ai_majority") else None,
        "models_agree": sum(1 for v in p.get("ai_results", {}).values() if v.get("winner") == p["human_winner"]),
        "models_total": sum(1 for v in p.get("ai_results", {}).values() if v.get("winner")),
        "score_gap": p.get("score_gap", 0),
    } for p in pairs[:80]]

    return {
        "status": "ok",
        "mode": mode,
        "total_pairs": total,
        "overall_majority": {"agree": maj_agree, "total": maj_total, "rate": _rate(maj_agree, maj_total)},
        "by_model_overall": {mk: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for mk, v in overall_models.items()},
        "by_domain": by_domain,
        "by_gap": {g: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for g, v in sorted(gap_totals.items())},
        "inter_model": {k: {"agree": v["agree"], "total": v["total"], "rate": _rate(v["agree"], v["total"])} for k, v in inter_model.items()},
        "samples": samples,
        "prompts": {
            "system_prompt": DEFAULT_EVALUATION_PROMPT["system_prompt"],
            "user_prompt": DEFAULT_EVALUATION_PROMPT["user_prompt"],
            "content_note": "Abstract mode uses abstract only. Extract mode uses full body text with section extraction (intro/method/results/conclusion).",
        },
    }


@router.post("/pairwise/stop", dependencies=[Depends(verify_admin)])
async def pw_stop():
    return await _stop()


@router.post("/pairwise-extract/stop", dependencies=[Depends(verify_admin)])
async def pw_ext_stop():
    return await _stop()


async def _stop():
    for st in (_pw_abs_state, _pw_ext_state):
        st["running"] = False
        st["fetching"] = False
    return {"status": "stopped", "mode": "synced"}


# ─── Synced Fetch & Run ───────────────────────────────────────────────────────

class SyncedFetchRequest(BaseModel):
    num_pairs: int = 30
    parallel_agents: int = 5


@router.post("/pairwise/fetch-and-run", dependencies=[Depends(verify_admin)])
async def pw_fetch_and_run(body: SyncedFetchRequest):
    if _pw_abs_state["fetching"] or _pw_abs_state["running"] or _pw_ext_state["fetching"] or _pw_ext_state["running"]:
        return {"status": "already_running"}

    asyncio.create_task(_synced_run(body.num_pairs, body.parallel_agents))
    return {
        "status": "started",
        "num_pairs": body.num_pairs,
        "parallel_agents": body.parallel_agents,
        "mode": "synced",
    }


async def _synced_run(num_pairs: int, parallel_agents: int):
    for st in (_pw_abs_state, _pw_ext_state):
        st["fetching"] = True
        st["running"] = True
        st["progress"] = {
            "phase": "scanning",
            "pairs_fetched": 0,
            "pairs_done": 0,
            "pairs_in_flight": 0,
            "target": num_pairs,
            "parallel_agents": parallel_agents,
        }
    counter = {"n": 0, "in_flight": 0}

    def _set_progress(key, value):
        _pw_abs_state["progress"][key] = value
        _pw_ext_state["progress"][key] = value

    def _is_running():
        return _pw_abs_state["running"] and _pw_ext_state["running"]

    try:
        # Phase 1: Scan Crossref for reviewers
        now = _time.time()
        if _crossref_cache["data"] and (now - _crossref_cache["ts"]) < _crossref_cache["ttl"]:
            logger.info("Qeios synced: using cached Crossref data")
            eligible = _crossref_cache["data"]
        else:
            logger.info("Qeios synced: scanning Crossref...")
            reviewer_reviews = defaultdict(list)
            total_reviews = 0
            cursor = "*"

            for page in range(15):
                try:
                    r = requests.get(
                        f"https://api.crossref.org/works?filter=type:peer-review&query.publisher-name=Qeios&rows=1000&cursor={cursor}",
                        headers=CROSSREF_HEADERS, timeout=20,
                    )
                    d = r.json()
                    items = d.get("message", {}).get("items", [])
                    cursor = d.get("message", {}).get("next-cursor", "")
                    total_reviews += len(items)
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
                    _time.sleep(0.3)
                except Exception:
                    break

            eligible = {r: ps for r, ps in reviewer_reviews.items() if len(ps) >= 2}
            _crossref_cache["data"] = eligible
            _crossref_cache["ts"] = now
            logger.info(f"Qeios synced: {total_reviews} reviews, {len(eligible)} eligible reviewers")

        # Dedup: exclude reviewers already in DB
        existing_reviewers = set()
        async for doc in db.qeios_pairwise_abstract.find({}, {"_id": 0, "reviewer": 1}):
            existing_reviewers.add(doc["reviewer"])

        reviewers = [(r, ps) for r, ps in eligible.items() if r not in existing_reviewers]
        random.shuffle(reviewers)
        logger.info(f"Qeios synced: {len(reviewers)} new reviewers available (excluded {len(existing_reviewers)} existing)")

        # Phase 2: Fetch pair data
        _set_progress("phase", "fetching")
        _pw_abs_state["fetching"] = True
        _pw_ext_state["fetching"] = True

        valid_pairs = []
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(reviewers), 10):
                if len(valid_pairs) >= num_pairs or not _is_running():
                    break
                batch = reviewers[i:i + 10]
                coros = [_fetch_pair_data(session, r, ps) for r, ps in batch]
                results = await asyncio.gather(*coros)
                for pair in results:
                    if pair and len(valid_pairs) < num_pairs:
                        valid_pairs.append(pair)
                _set_progress("pairs_fetched", len(valid_pairs))
                await asyncio.sleep(0.3)

        if not valid_pairs:
            logger.warning("Qeios synced: no valid pairs found")
            return

        _set_progress("phase", "evaluating")
        _set_progress("target", len(valid_pairs))
        _pw_abs_state["fetching"] = False
        _pw_ext_state["fetching"] = False

        logger.info(f"Qeios synced: {len(valid_pairs)} pairs ready, {parallel_agents} parallel agents")

        # Phase 3: Evaluate all pairs in parallel
        semaphore = asyncio.Semaphore(parallel_agents)
        prompt_config = DEFAULT_EVALUATION_PROMPT

        async def _evaluate_one(pair_data: dict):
            if not _is_running():
                return
            async with semaphore:
                if not _is_running():
                    return

                counter["in_flight"] += 1
                _set_progress("pairs_in_flight", counter["in_flight"])

                pair_id = str(uuid.uuid4())
                reviewer = pair_data["reviewer"]
                p1 = pair_data["paper1"]
                p2 = pair_data["paper2"]

                p1_dict = {
                    "title": p1["title"], "abstract": p1["abstract"],
                    "full_text": p1.get("full_text"),
                    "categories": [p1.get("domain", "Unknown")],
                }
                p2_dict = {
                    "title": p2["title"], "abstract": p2["abstract"],
                    "full_text": p2.get("full_text"),
                    "categories": [p2.get("domain", "Unknown")],
                }

                # Build model tasks with random swap
                model_tasks = []
                for mi in TOURNAMENT_MODELS:
                    swapped = random.random() < 0.5
                    model_tasks.append((mi, swapped))

                async def _eval_mode(abstract_only: bool):
                    coros = []
                    for mi, swapped in model_tasks:
                        a, b = (p2_dict, p1_dict) if swapped else (p1_dict, p2_dict)
                        coros.append(compare_papers(
                            a, b, prompt_config,
                            abstract_only=abstract_only,
                            model_override=mi,
                        ))
                    responses = await asyncio.gather(*coros, return_exceptions=True)

                    ai_results = {}
                    for (mi, swapped), resp in zip(model_tasks, responses):
                        mk = f"{mi['provider']}:{mi['model']}"
                        if isinstance(resp, Exception):
                            ai_results[mk] = {"winner": None, "error": str(resp)[:100]}
                        else:
                            w = resp.get("winner", "paper1")
                            if swapped:
                                w = "paper2" if w == "paper1" else "paper1"
                            ai_results[mk] = {"winner": w, "reasoning": resp.get("reasoning", "")}

                    votes = [v["winner"] for v in ai_results.values() if v.get("winner")]
                    majority = None
                    if votes:
                        c = Counter(votes)
                        best, n = c.most_common(1)[0]
                        if n > len(votes) / 2:
                            majority = best
                    return ai_results, majority

                # Run BOTH abstract and extract in parallel
                (ai_ext, maj_ext), (ai_abs, maj_abs) = await asyncio.gather(
                    _eval_mode(abstract_only=False),
                    _eval_mode(abstract_only=True),
                )

                hw = pair_data["human_winner"]
                s1 = pair_data["human_score1"]
                s2 = pair_data["human_score2"]

                p1_doc = {
                    "doi": p1.get("doi", ""),
                    "qeios_id": p1.get("qeios_id", ""),
                    "title": p1["title"][:200],
                    "abstract": p1["abstract"][:500],
                    "has_full_text": bool(p1.get("full_text")),
                    "full_text_chars": len(p1.get("full_text", "")),
                    "rating": p1["rating"],
                }
                p2_doc = {
                    "doi": p2.get("doi", ""),
                    "qeios_id": p2.get("qeios_id", ""),
                    "title": p2["title"][:200],
                    "abstract": p2["abstract"][:500],
                    "has_full_text": bool(p2.get("full_text")),
                    "full_text_chars": len(p2.get("full_text", "")),
                    "rating": p2["rating"],
                }

                base_doc = {
                    "pair_id": pair_id,
                    "pair_key": reviewer,
                    "source": "qeios",
                    "reviewer": reviewer,
                    "domain": pair_data["domain"],
                    "paper1": p1_doc,
                    "paper2": p2_doc,
                    "human_winner": hw,
                    "human_score1": s1,
                    "human_score2": s2,
                    "score_gap": round(abs(s1 - s2), 2),
                    "ai_completed": True,
                    "ai_failed": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

                doc_abs = {**base_doc, "id": str(uuid.uuid4()), "content_mode": "abstract", "ai_results": ai_abs, "ai_majority": maj_abs}
                doc_ext = {**base_doc, "id": str(uuid.uuid4()), "content_mode": "extract", "ai_results": ai_ext, "ai_majority": maj_ext}

                await db.qeios_pairwise_abstract.insert_one(doc_abs)
                await db.qeios_pairwise_extract.insert_one(doc_ext)

                counter["n"] += 1
                counter["in_flight"] -= 1
                _set_progress("pairs_done", counter["n"])
                _set_progress("pairs_in_flight", counter["in_flight"])

                agrees = sum(1 for v in ai_ext.values() if v.get("winner") == hw)
                logger.info(f"Qeios pw [synced] [{counter['n']}/{len(valid_pairs)}] {pair_data['domain'][:15]}: {agrees}/3 agree | gap={abs(s1-s2):.1f} | {reviewer[:20]}")

        coros = [_evaluate_one(p) for p in valid_pairs]
        await asyncio.gather(*coros)

        logger.info(f"Qeios synced complete: {counter['n']} pairs")
    except Exception as e:
        logger.error(f"Qeios synced error: {e}")
    finally:
        for st in (_pw_abs_state, _pw_ext_state):
            st["fetching"] = False
            st["running"] = False
