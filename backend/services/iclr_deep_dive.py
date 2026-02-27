"""
Deep Dive Validation Experiment — Parameterized Pipeline

1. Generate first-pass assessments with focus areas (JSON block) for all papers
2. Generate deep-dive assessments informed by focus areas (standalone style)
3. Replay the tournament using deep-dive assessments (same pairs + same judge models)
4. Compute metrics + convergence data

All results stored in DB, resumable at each step. Parameterized by dataset_id and source_mode.
"""
import asyncio
import uuid
import json
import re
import random
import math
from datetime import datetime, timezone
from collections import defaultdict, Counter
from core.config import db, logger, EMERGENT_LLM_KEY
from emergentintegrations.llm.chat import LlmChat, UserMessage

ASSESSMENT_MODEL = {"provider": "anthropic", "model": "claude-opus-4-6"}
PARALLEL = 5
_BUDGET_KEYWORDS = ("budget", "balance", "insufficient", "credit", "quota")


def _keys(dataset_id: str) -> dict:
    slug = dataset_id.replace("-", "_")
    return {
        "experiment": f"deep_dive_{slug}",
        "progress": f"deep_dive_{slug}_progress",
        "replays": f"deep_dive_{slug}_replays",
    }


# --- Prompts ---

STEP2_PROMPT = {
    "system": """You are a scientific impact analyst. Write a detailed scientific impact assessment of a research paper (up to 1000 words). Structure around:

1. **Core Contribution**: Main novelty, what problem it solves and how
2. **Methodological Rigor**: Soundness of approach, experiments/proofs
3. **Potential Impact**: Real-world applications, breadth of influence
4. **Timeliness & Relevance**: Current bottleneck or emerging need addressed
5. **Strengths & Limitations**: Key strengths and notable weaknesses

Be specific and analytical — avoid generic praise.

After your assessment, on a new line, output EXACTLY one JSON block with aspects that warrant particularly careful scrutiny in a thorough review:

```json
{"focus_areas": ["area1", "area2", ...]}
```

List specific aspects where careful analysis could reveal important nuances — such as proof correctness, evaluation methodology gaps, statistical significance of claims, hidden assumptions, or potential confounds.""",

    "user": """Write a scientific impact assessment for the following paper:

**Title:** {title}

**Content:**
{content}

Write your impact assessment (up to 1000 words), then the focus areas JSON block:""",
}

STEP3_PROMPT = {
    "system": """You are a scientific impact analyst. Write a detailed scientific impact assessment of a research paper (up to 1200 words). Structure around:

1. **Core Contribution**: Main novelty, what problem it solves and how
2. **Methodological Rigor**: Soundness of approach, experiments/proofs
3. **Potential Impact**: Real-world applications, breadth of influence
4. **Timeliness & Relevance**: Current bottleneck or emerging need addressed
5. **Strengths & Limitations**: Key strengths and notable weaknesses

Be specific and analytical. Pay particular attention to: {focus_areas}

Your assessment should give enough detail for another evaluator to judge this paper's impact without reading the full text.""",

    "user": """Write a scientific impact assessment for the following paper.

**Title:** {title}

**Content:**
{content}

For context, here are preliminary notes on this paper:
{first_pass_assessment}

Write your complete, standalone impact assessment (up to 1200 words):""",
}


# --- LLM Helper ---

async def _llm_call(system_msg: str, user_msg: str, label: str = "",
                     model_override: dict = None) -> str:
    """Single LLM call with timeout and budget retry. Never gives up on budget errors."""
    model = model_override or ASSESSMENT_MODEL
    attempt = 0
    while True:
        try:
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"dd-{uuid.uuid4()}",
                system_message=system_msg,
            ).with_model(model["provider"], model["model"])

            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: asyncio.run(chat.send_message(UserMessage(text=user_msg))),
                ),
                timeout=120,
            )
            return response.strip() if isinstance(response, str) else str(response)
        except asyncio.TimeoutError:
            attempt += 1
            if attempt > 10:
                raise Exception(f"LLM timeout after {attempt} attempts ({label})")
            logger.warning(f"Timeout ({label}), attempt {attempt}")
            await asyncio.sleep(5)
        except Exception as e:
            if any(kw in str(e).lower() for kw in _BUDGET_KEYWORDS):
                wait = min(60 * (2 ** min(attempt, 4)), 600)  # 60s, 120s, 240s, 480s, cap at 600s
                attempt += 1
                logger.warning(f"Budget error ({label}), waiting {wait}s (attempt {attempt})")
                await asyncio.sleep(wait)
            else:
                raise


async def _update_progress(keys: dict, step: str, done: int, total: int, errors: int = 0, finished: bool = False):
    await db.settings.update_one(
        {"key": keys["progress"]},
        {"$set": {"key": keys["progress"], "step": step, "done": done, "total": total,
                  "errors": errors, "running": not finished, "finished": finished}},
        upsert=True,
    )


# --- Step 2: First-pass assessments ---

async def run_step2(dataset_id: str):
    keys = _keys(dataset_id)
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1},
    ).to_list(500)

    doc = await db.settings.find_one({"key": keys["experiment"]}, {"_id": 0})
    existing = set()
    if doc and doc.get("papers"):
        existing = {p["paper_id"] for p in doc["papers"] if p.get("step2_assessment")}

    todo = [p for p in papers if p["id"] not in existing]
    total = len(papers)
    done = total - len(todo)
    await _update_progress(keys, "step2", done, total)

    sem = asyncio.Semaphore(PARALLEL)
    counter = {"done": done, "errors": 0}

    async def process_one(paper):
        pid = paper["id"]
        title = paper["title"]
        full_text = paper.get("full_text", "")
        abstract = paper.get("abstract", "")
        content = f"Abstract: {abstract[:1500]}\n\nFull Paper Text:\n{full_text}" if full_text else f"Abstract: {abstract[:3000]}"
        prompt = STEP2_PROMPT["user"].format(title=title, content=content)

        async with sem:
            try:
                response = await _llm_call(STEP2_PROMPT["system"], prompt, label=f"s2:{title[:25]}")
                focus_areas = []
                m = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
                if m:
                    try: focus_areas = json.loads(m.group(1)).get("focus_areas", [])
                    except json.JSONDecodeError: pass
                if not focus_areas:
                    for line in reversed(response.split('\n')):
                        line = line.strip()
                        if line.startswith('{') and 'focus_areas' in line:
                            try: focus_areas = json.loads(line).get("focus_areas", [])
                            except json.JSONDecodeError: pass
                            break
                assessment = re.sub(r'```json\s*\{.*?\}\s*```', '', response, flags=re.DOTALL).strip() or response
                entry = {"paper_id": pid, "title": title, "step2_assessment": assessment, "focus_areas": focus_areas}
                res = await db.settings.update_one(
                    {"key": keys["experiment"], "papers.paper_id": pid},
                    {"$set": {"papers.$.step2_assessment": assessment, "papers.$.focus_areas": focus_areas}},
                )
                if res.matched_count == 0:
                    await db.settings.update_one({"key": keys["experiment"]}, {"$push": {"papers": entry}}, upsert=True)
                counter["done"] += 1
                logger.info(f"Step 2: {counter['done']}/{total} — {title[:40]} ({len(focus_areas)} areas)")
            except Exception as e:
                counter["errors"] += 1; counter["done"] += 1
                logger.warning(f"Step 2 failed: {title[:40]}: {e}")
            if counter["done"] % 3 == 0:
                await _update_progress(keys, "step2", counter["done"], total, counter["errors"])

    await asyncio.gather(*[process_one(p) for p in todo])
    await _update_progress(keys, "step2", total, total, finished=True)


# --- Step 3: Deep-dive assessments ---

async def run_step3(dataset_id: str):
    keys = _keys(dataset_id)
    doc = await db.settings.find_one({"key": keys["experiment"]}, {"_id": 0})
    if not doc or not doc.get("papers"):
        return

    papers_data = doc["papers"]
    paper_lookup = {}
    async for p in db.validation_papers.find(
        {"dataset_id": dataset_id}, {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1},
    ):
        paper_lookup[p["id"]] = p

    todo = [e for e in papers_data if e.get("step2_assessment") and not e.get("step3_assessment")]
    total = len(papers_data)
    done = total - len(todo)
    await _update_progress(keys, "step3", done, total)

    sem = asyncio.Semaphore(PARALLEL)
    counter = {"done": done, "errors": 0}

    async def process_one(entry):
        pid = entry["paper_id"]
        paper = paper_lookup.get(pid)
        if not paper: return
        title = entry["title"]
        full_text = paper.get("full_text", "")
        abstract = paper.get("abstract", "")
        content = f"Abstract: {abstract[:1500]}\n\nFull Paper Text:\n{full_text}" if full_text else f"Abstract: {abstract[:3000]}"
        focus_str = ", ".join(entry.get("focus_areas", []))
        system = STEP3_PROMPT["system"].format(focus_areas=focus_str)
        user = STEP3_PROMPT["user"].format(title=title, content=content, first_pass_assessment=entry["step2_assessment"])

        async with sem:
            try:
                response = await _llm_call(system, user, label=f"s3:{title[:25]}")
                await db.settings.update_one(
                    {"key": keys["experiment"], "papers.paper_id": pid},
                    {"$set": {"papers.$.step3_assessment": response}},
                )
                counter["done"] += 1
                logger.info(f"Step 3: {counter['done']}/{total} — {title[:40]}")
            except Exception as e:
                counter["errors"] += 1; counter["done"] += 1
                logger.warning(f"Step 3 failed: {title[:40]}: {e}")
            if counter["done"] % 3 == 0:
                await _update_progress(keys, "step3", counter["done"], total, counter["errors"])

    await asyncio.gather(*[process_one(e) for e in todo])
    await _update_progress(keys, "step3", total, total, finished=True)


# --- Step 4: Replay tournament (same pairs + same judge model) ---

async def run_step4(dataset_id: str, source_mode: str = "abstract_plus_summary:opus46"):
    """Replay matches using deep-dive assessments. Reuses exact pairs and judge models."""
    keys = _keys(dataset_id)
    doc = await db.settings.find_one({"key": keys["experiment"]}, {"_id": 0})
    if not doc or not doc.get("papers"):
        return

    dd_lookup = {e["paper_id"]: e["step3_assessment"] for e in doc["papers"] if e.get("step3_assessment")}
    logger.info(f"Step 4: {len(dd_lookup)} deep-dive assessments for {dataset_id}")

    # Load ALL original matches (not deduplicated — replay every single one)
    orig_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}, "content_mode": source_mode},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
    ).to_list(50000)

    # Check already replayed
    existing = set()
    async for r in db[keys["replays"]].find({}, {"_id": 0, "original_match_id": 1}):
        existing.add(r["original_match_id"])

    remaining = [m for m in orig_matches if m["id"] not in existing]

    # Load paper data (include evaluations for eLife-style GT)
    paper_ids = set()
    for m in remaining:
        paper_ids.add(m["paper1_id"]); paper_ids.add(m["paper2_id"])
    papers = {}
    async for p in db.validation_papers.find(
        {"id": {"$in": list(paper_ids)}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "decision": 1, "evaluations": 1},
    ):
        papers[p["id"]] = p

    # Build average expert rating per paper (for eLife-style GT)
    paper_avg_rating = {}
    for pid, p in papers.items():
        evals = p.get("evaluations", [])
        ratings = [ev["rating_value"] for ev in evals if ev.get("rating_value")]
        if ratings:
            paper_avg_rating[pid] = sum(ratings) / len(ratings)

    total = len(remaining)
    await _update_progress(keys, "step4", 0, total)

    from core.config import DEFAULT_EVALUATION_PROMPT
    sem = asyncio.Semaphore(PARALLEL)
    counter = {"done": 0, "errors": 0}

    async def replay_one(m):
        p1 = papers.get(m["paper1_id"])
        p2 = papers.get(m["paper2_id"])
        if not p1 or not p2:
            counter["done"] += 1; return

        p1_sum = dd_lookup.get(p1["id"], "")
        p2_sum = dd_lookup.get(p2["id"], "")
        if not p1_sum or not p2_sum:
            counter["done"] += 1; return

        p1_content = f"Abstract: {p1.get('abstract','')[:1500]}\n\nAI Impact Assessment:\n{p1_sum}"
        p2_content = f"Abstract: {p2.get('abstract','')[:1500]}\n\nAI Impact Assessment:\n{p2_sum}"
        prompt = DEFAULT_EVALUATION_PROMPT["user_prompt"].format(
            paper1_title=p1["title"], paper1_content=p1_content,
            paper2_title=p2["title"], paper2_content=p2_content,
        )

        # Use the SAME judge model as the original match
        judge_model = m.get("model_used", ASSESSMENT_MODEL)

        async with sem:
            try:
                response = await _llm_call(
                    DEFAULT_EVALUATION_PROMPT["system_prompt"], prompt,
                    label=f"s4:{m['id'][:10]}", model_override=judge_model,
                )
                resp_text = response
                if resp_text.startswith("```"):
                    parts = resp_text.split("```")
                    if len(parts) >= 2: resp_text = parts[1].lstrip("json").strip()
                if not resp_text.startswith("{"):
                    jm = re.search(r'\{[^{}]*"winner"[^{}]*\}', resp_text, re.DOTALL)
                    if jm: resp_text = jm.group()
                    else: raise ValueError(f"No JSON: {resp_text[:100]}")

                result = json.loads(resp_text)
                winner = result.get("winner")
                if winner not in ("paper1", "paper2"):
                    raise ValueError(f"Invalid: {result}")

                winner_id = p1["id"] if winner == "paper1" else p2["id"]
                
                # Ground truth: ICLR tiers OR eLife average expert rating
                gt_winner = orig_agrees = replay_agrees = None
                d1 = _decision_tier(p1.get("decision", ""))
                d2 = _decision_tier(p2.get("decision", ""))
                if d1 >= 0 and d2 >= 0 and d1 != d2:
                    gt_winner = p1["id"] if d1 > d2 else p2["id"]
                elif p1["id"] in paper_avg_rating and p2["id"] in paper_avg_rating:
                    r1, r2 = paper_avg_rating[p1["id"]], paper_avg_rating[p2["id"]]
                    if r1 != r2:
                        gt_winner = p1["id"] if r1 > r2 else p2["id"]
                if gt_winner:
                    orig_agrees = m.get("winner_id") == gt_winner
                    replay_agrees = winner_id == gt_winner

                replay_id = str(uuid.uuid4())
                replay_doc = {
                    "id": replay_id,
                    "original_match_id": m["id"],
                    "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                    "original_winner_id": m.get("winner_id"),
                    "replay_winner_id": winner_id,
                    "flipped": winner_id != m.get("winner_id"),
                    "reasoning": result.get("reasoning", ""),
                    "model_used": judge_model,
                    "human_gt_winner": gt_winner,
                    "original_agrees_human": orig_agrees,
                    "replay_agrees_human": replay_agrees,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db[keys["replays"]].insert_one(replay_doc)

                # Also insert as validation_match for live convergence chart
                await db.validation_matches.insert_one({
                    "id": replay_id, "dataset_id": dataset_id,
                    "paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
                    "winner_id": winner_id, "content_mode": "deep_dive",
                    "completed": True, "failed": False, "abstract_only": False,
                    "used_extraction": False, "reasoning": result.get("reasoning", ""),
                    "model_used": judge_model, "tokens": {},
                    "created_at": replay_doc["created_at"],
                })
            except Exception as e:
                counter["errors"] += 1
                logger.warning(f"Step 4 failed: {m['id'][:15]}: {e}")
            counter["done"] += 1
            if counter["done"] % 5 == 0:
                await _update_progress(keys, "step4", counter["done"], total, counter["errors"])

    await asyncio.gather(*[replay_one(m) for m in remaining])

    await _update_progress(keys, "step4", total, total, errors=counter["errors"], finished=True)
    logger.info(f"Step 4 complete: {counter['done']} replays, {counter['errors']} errors")


async def _insert_as_validation_matches(keys: dict, dataset_id: str):
    """Copy replay results into validation_matches with content_mode='deep_dive' for convergence."""
    existing = await db.validation_matches.count_documents({"dataset_id": dataset_id, "content_mode": "deep_dive"})
    if existing > 0:
        logger.info(f"Convergence: already have {existing} deep_dive matches for {dataset_id}, skipping")
        return
    replays = await db[keys["replays"]].find({}, {"_id": 0}).to_list(100000)
    docs = [{
        "id": r["id"], "dataset_id": dataset_id,
        "paper1_id": r["paper1_id"], "paper2_id": r["paper2_id"],
        "winner_id": r["replay_winner_id"],
        "content_mode": "deep_dive",
        "completed": True, "failed": False, "abstract_only": False, "used_extraction": False,
        "reasoning": r.get("reasoning", ""),
        "model_used": r.get("model_used", {}),
        "tokens": {}, "created_at": r.get("created_at", datetime.now(timezone.utc).isoformat()),
    } for r in replays]
    if docs:
        await db.validation_matches.insert_many(docs)
        logger.info(f"Inserted {len(docs)} deep_dive validation_matches for {dataset_id}")


_TIER = {"accept (oral)": 4, "oral": 4, "accept (spotlight)": 3, "spotlight": 3,
         "accept (poster)": 2, "poster": 2, "withdrawn": 1, "desk rejected": 0, "reject": 0}


def _decision_tier(decision: str) -> int:
    return _TIER.get(decision.lower().strip(), -1)


# --- Analysis ---

async def compute_analysis(dataset_id: str) -> dict:
    """Compute analysis by comparing baseline vs deep_dive validation_matches."""
    # Load both baseline and deep_dive matches
    baseline_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "content_mode": "abstract_plus_summary"},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)
    dd_matches = await db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "content_mode": "deep_dive"},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ).to_list(100000)

    if not baseline_matches and not dd_matches:
        return {}

    def _pair_key(m):
        return tuple(sorted([m["paper1_id"], m["paper2_id"]]))

    baseline_by_pair = {_pair_key(m): m for m in baseline_matches}
    dd_by_pair = {_pair_key(m): m for m in dd_matches}

    # Load paper GT
    paper_ids = set()
    for m in baseline_matches + dd_matches:
        paper_ids.add(m["paper1_id"]); paper_ids.add(m["paper2_id"])

    paper_gt = {}
    async for p in db.validation_papers.find(
        {"id": {"$in": list(paper_ids)}, "dataset_id": dataset_id},
        {"_id": 0, "id": 1, "decision": 1, "evaluations": 1, "composite_score": 1},
    ):
        gt = {}
        tier = _decision_tier(p.get("decision", ""))
        if tier >= 0:
            gt["composite"] = tier
        evals = p.get("evaluations", [])
        if evals:
            if p.get("composite_score"):
                gt["composite"] = p["composite_score"]
            else:
                ratings = [ev["rating_value"] for ev in evals if ev.get("rating_value")]
                if ratings:
                    gt.setdefault("composite", sum(ratings) / len(ratings))
            for dim, field in [("rigour", "rigour_score"), ("presentation", "presentation_score"), ("conclusions", "conclusions_score")]:
                vals = [ev[field] for ev in evals if ev.get(field)]
                if vals:
                    gt[dim] = sum(vals) / len(vals)
        if gt:
            paper_gt[p["id"]] = gt

    gt_dimensions = set()
    for g in paper_gt.values():
        gt_dimensions.update(g.keys())

    # Per-dimension pairwise agreement for both modes
    dimension_agreement = {}
    for dim in gt_dimensions:
        bl_agree, dd_agree, bl_total, dd_total = 0, 0, 0, 0
        for m in baseline_matches:
            g1 = paper_gt.get(m["paper1_id"], {}).get(dim)
            g2 = paper_gt.get(m["paper2_id"], {}).get(dim)
            if g1 is None or g2 is None or g1 == g2: continue
            gt_winner = m["paper1_id"] if g1 > g2 else m["paper2_id"]
            bl_total += 1
            if m["winner_id"] == gt_winner: bl_agree += 1
        for m in dd_matches:
            g1 = paper_gt.get(m["paper1_id"], {}).get(dim)
            g2 = paper_gt.get(m["paper2_id"], {}).get(dim)
            if g1 is None or g2 is None or g1 == g2: continue
            gt_winner = m["paper1_id"] if g1 > g2 else m["paper2_id"]
            dd_total += 1
            if m["winner_id"] == gt_winner: dd_agree += 1
        if bl_total > 0 or dd_total > 0:
            bl_pct = round(bl_agree / max(bl_total, 1) * 100, 1)
            dd_pct = round(dd_agree / max(dd_total, 1) * 100, 1)
            dimension_agreement[dim] = {
                "pairs": max(bl_total, dd_total),
                "baseline_agreement": bl_pct,
                "deep_dive_agreement": dd_pct,
                "lift": round(dd_pct - bl_pct, 1),
            }

    bl_comp = dimension_agreement.get("composite", {}).get("baseline_agreement", 0)
    dd_comp = dimension_agreement.get("composite", {}).get("deep_dive_agreement", 0)
    comp_pairs = dimension_agreement.get("composite", {}).get("pairs", 0)

    common_pairs = set(baseline_by_pair.keys()) & set(dd_by_pair.keys())
    flipped = sum(1 for pk in common_pairs if baseline_by_pair[pk]["winner_id"] != dd_by_pair[pk]["winner_id"])

    analysis = {
        "total_matches": {"baseline": len(baseline_matches), "deep_dive": len(dd_matches)},
        "flipped": flipped,
        "flip_rate": round(flipped / max(len(common_pairs), 1) * 100, 1),
        "common_pairs": len(common_pairs),
        "human_agreement": {
            "pairs_with_gt": comp_pairs,
            "original": bl_comp,
            "deep_dive": dd_comp,
            "lift": round(dd_comp - bl_comp, 1),
        },
        "dimension_agreement": dimension_agreement,
    }

    # McNemar
    a = b = c = d_val = 0
    for pk in common_pairs:
        bl_m, dd_m = baseline_by_pair[pk], dd_by_pair[pk]
        g1 = paper_gt.get(bl_m["paper1_id"], {}).get("composite")
        g2 = paper_gt.get(bl_m["paper2_id"], {}).get("composite")
        if g1 is None or g2 is None or g1 == g2: continue
        gt_winner = bl_m["paper1_id"] if g1 > g2 else bl_m["paper2_id"]
        bl_ok = bl_m["winner_id"] == gt_winner
        dd_ok = dd_m["winner_id"] == gt_winner
        if bl_ok and dd_ok: a += 1
        elif bl_ok and not dd_ok: b += 1
        elif not bl_ok and dd_ok: c += 1
        else: d_val += 1
    mcnemar = {"pairs": a + b + c + d_val, "both_agree": a, "only_baseline": b, "only_deepdive": c, "neither": d_val}
    if b + c > 0:
        chi2 = (abs(b - c) - 1)**2 / (b + c)
        p_val = math.erfc(math.sqrt(chi2 / 2))
        mcnemar.update({"chi2": round(chi2, 3), "p_value": round(p_val, 4), "significant": p_val < 0.05})
    else:
        mcnemar.update({"chi2": 0, "p_value": 1.0, "significant": False})
    analysis["mcnemar"] = mcnemar

    # Flip direction
    toward_h, away_h = 0, 0
    for pk in common_pairs:
        bl_m, dd_m = baseline_by_pair[pk], dd_by_pair[pk]
        if bl_m["winner_id"] == dd_m["winner_id"]: continue
        g1 = paper_gt.get(bl_m["paper1_id"], {}).get("composite")
        g2 = paper_gt.get(bl_m["paper2_id"], {}).get("composite")
        if g1 is None or g2 is None or g1 == g2: continue
        gt_winner = bl_m["paper1_id"] if g1 > g2 else bl_m["paper2_id"]
        if dd_m["winner_id"] == gt_winner and bl_m["winner_id"] != gt_winner: toward_h += 1
        elif bl_m["winner_id"] == gt_winner and dd_m["winner_id"] != gt_winner: away_h += 1
    analysis["flip_direction"] = {"toward_human": toward_h, "away_from_human": away_h, "net": toward_h - away_h}

    # Paper-level win rate shifts
    paper_stats = defaultdict(lambda: {"bl_wins": 0, "bl_total": 0, "dd_wins": 0, "dd_total": 0})
    for m in baseline_matches:
        for pid in [m["paper1_id"], m["paper2_id"]]:
            paper_stats[pid]["bl_total"] += 1
            if m["winner_id"] == pid: paper_stats[pid]["bl_wins"] += 1
    for m in dd_matches:
        for pid in [m["paper1_id"], m["paper2_id"]]:
            paper_stats[pid]["dd_total"] += 1
            if m["winner_id"] == pid: paper_stats[pid]["dd_wins"] += 1

    wr_diffs = []
    paper_details = []
    title_lookup = {}
    async for p in db.validation_papers.find({"id": {"$in": list(paper_stats.keys())}}, {"_id": 0, "id": 1, "title": 1, "decision": 1}):
        title_lookup[p["id"]] = {"title": p["title"], "decision": p.get("decision", "")}
    for pid, s in paper_stats.items():
        if s["bl_total"] < 2 or s["dd_total"] < 2: continue
        bl_wr = s["bl_wins"] / s["bl_total"]
        dd_wr = s["dd_wins"] / s["dd_total"]
        diff = dd_wr - bl_wr
        wr_diffs.append(diff)
        info = title_lookup.get(pid, {})
        paper_details.append({"paper_id": pid, "title": info.get("title", pid), "decision": info.get("decision", ""),
                              "orig_wr": round(bl_wr * 100, 1), "dd_wr": round(dd_wr * 100, 1),
                              "diff": round(diff * 100, 1), "matches": s["bl_total"]})
    paper_details.sort(key=lambda x: abs(x["diff"]), reverse=True)
    analysis["paper_level"] = {"n_papers": len(wr_diffs), "paper_details": paper_details}

    if len(wr_diffs) >= 5:
        import statistics
        analysis["paper_level"]["mean_wr_shift"] = round(statistics.mean(wr_diffs) * 100, 2)
        analysis["paper_level"]["median_wr_shift"] = round(statistics.median(wr_diffs) * 100, 2)
        analysis["paper_level"]["positive_shifts"] = sum(1 for d in wr_diffs if d > 0)
        analysis["paper_level"]["negative_shifts"] = sum(1 for d in wr_diffs if d < 0)

    return analysis

async def compute_convergence_by_dimension(dataset_id: str, steps: int = 10) -> dict:
    """Compute ranking convergence against each GT dimension separately.
    Uses Bradley-Terry ranking (same as main convergence). Cached in DB.
    """
    keys = _keys(dataset_id)
    cache_key = f"{keys['experiment']}_convergence"

    # Check cache
    cached = await db.settings.find_one({"key": cache_key}, {"_id": 0})
    if cached and cached.get("data"):
        # Refresh if match count changed
        current_count = await db.validation_matches.count_documents(
            {"dataset_id": dataset_id, "completed": True, "content_mode": {"$in": ["abstract_plus_summary", "deep_dive"]}}
        )
        if cached.get("match_count") == current_count:
            return cached["data"]

    result = await _compute_convergence_by_dimension_impl(dataset_id, steps)

    match_count = sum(d.get("total_matches", 0) for d in result.get("curves", {}).values())
    await db.settings.update_one(
        {"key": cache_key},
        {"$set": {"key": cache_key, "data": result, "match_count": match_count}},
        upsert=True,
    )
    return result


async def _compute_convergence_by_dimension_impl(dataset_id: str, steps: int = 10) -> dict:
    """Compute ranking convergence against each GT dimension separately.
    
    For each content_mode (baseline, deep_dive), builds Bradley-Terry rankings
    at increasing match counts and computes Spearman correlation against
    4 ground truth dimensions: composite, rigour, presentation, conclusions.
    """
    # Load all matches
    matches_by_mode = defaultdict(list)
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
         "content_mode": {"$in": ["abstract_plus_summary", "deep_dive"]}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "content_mode": 1, "created_at": 1},
    ):
        matches_by_mode[m["content_mode"]].append(m)

    if not any(matches_by_mode.values()):
        return {}

    # Load paper GT scores for all 4 dimensions
    paper_ids = set()
    for matches in matches_by_mode.values():
        for m in matches:
            paper_ids.add(m["paper1_id"])
            paper_ids.add(m["paper2_id"])

    paper_gt = {}
    async for p in db.validation_papers.find(
        {"id": {"$in": list(paper_ids)}, "dataset_id": dataset_id},
        {"_id": 0, "id": 1, "evaluations": 1, "composite_score": 1, "decision": 1},
    ):
        gt = {}
        # ICLR tiers
        tier = _decision_tier(p.get("decision", ""))
        if tier >= 0:
            gt["composite"] = tier
        # Evaluation-based scores
        evals = p.get("evaluations", [])
        if evals:
            if p.get("composite_score"):
                gt["composite"] = p["composite_score"]
            else:
                ratings = [ev["rating_value"] for ev in evals if ev.get("rating_value")]
                if ratings:
                    gt.setdefault("composite", sum(ratings) / len(ratings))
            for dim, field in [("rigour", "rigour_score"), ("presentation", "presentation_score"), ("conclusions", "conclusions_score")]:
                vals = [ev[field] for ev in evals if ev.get(field)]
                if vals:
                    gt[dim] = sum(vals) / len(vals)
        if gt:
            paper_gt[p["id"]] = gt

    # Determine which GT dimensions exist
    all_dims = set()
    for g in paper_gt.values():
        all_dims.update(g.keys())

    # For each mode, compute convergence curves
    mode_labels = {"abstract_plus_summary": "Baseline (1-pass)", "deep_dive": "Deep Dive (2-pass)"}
    result = {"dimensions": sorted(all_dims), "curves": {}}

    for mode, matches in matches_by_mode.items():
        if not matches:
            continue
        # Sort by created_at
        matches.sort(key=lambda m: m.get("created_at", ""))

        # Compute at each step using Bradley-Terry ranking (via background computation)
        from services.ranking import compute_leaderboard_async
        curve_points = []
        step_sizes = set()
        for step_i in range(1, steps + 1):
            n = max(20, int(len(matches) * step_i / steps))
            if n in step_sizes:
                continue
            step_sizes.add(n)
            subset = matches[:n]

            covered_ids = set()
            for m in subset:
                covered_ids.add(m["paper1_id"]); covered_ids.add(m["paper2_id"])
            if len(covered_ids) < 5:
                continue

            paper_stubs = [{"id": pid, "title": ""} for pid in covered_ids]
            try:
                lb = await compute_leaderboard_async(paper_stubs, subset)
            except Exception:
                continue

            ai_rank = {e["id"]: e["rank"] for e in lb}

            # Compute Spearman against each GT dimension
            dim_correlations = {}
            for dim in all_dims:
                common = [pid for pid in covered_ids if pid in ai_rank and pid in paper_gt and dim in paper_gt[pid]]
                if len(common) < 5:
                    continue
                gt_sorted = sorted(common, key=lambda p: -paper_gt[p][dim])
                gt_rank = {pid: i for i, pid in enumerate(gt_sorted)}

                n_common = len(common)
                d_sq = sum((ai_rank[pid] - gt_rank[pid]) ** 2 for pid in common)
                rho = 1 - (6 * d_sq) / (n_common * (n_common ** 2 - 1))
                dim_correlations[dim] = round(rho, 4)

            avg_matches = n / max(len(covered_ids), 1)
            curve_points.append({
                "avg_matches_per_paper": round(avg_matches, 1),
                "n_matches": n,
                "papers_covered": len(covered_ids),
                "correlations": dim_correlations,
            })

        result["curves"][mode] = {
            "name": mode_labels.get(mode, mode),
            "total_matches": len(matches),
            "points": curve_points,
        }

    return result


# --- Main runner ---

async def run_full_pipeline(dataset_id: str = "iclr-codegen",
                             source_mode: str = "abstract_plus_summary:opus46"):
    """Run the complete pipeline for a dataset."""
    keys = _keys(dataset_id)

    await db.settings.update_one(
        {"key": keys["experiment"]},
        {"$setOnInsert": {"key": keys["experiment"], "dataset_id": dataset_id, "papers": [],
                          "source_mode": source_mode,
                          "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    logger.info(f"=== Deep Dive Pipeline: {dataset_id} (source: {source_mode}) ===")

    logger.info("--- Step 2: First-pass assessments ---")
    await run_step2(dataset_id)

    logger.info("--- Step 3: Deep-dive assessments ---")
    await run_step3(dataset_id)

    logger.info("--- Step 4: Tournament replay (same pairs + judges) ---")
    await run_step4(dataset_id, source_mode)

    logger.info(f"=== Deep Dive Pipeline COMPLETE: {dataset_id} ===")


async def run_fresh_tournament(dataset_id: str):
    """For datasets with no existing matches: generate round-robin pairs and run
    BOTH a baseline tournament (step2 summaries) and a deep-dive tournament (step3 summaries).
    Both use the same pairs and same judge model for direct comparison."""
    keys = _keys(dataset_id)
    doc = await db.settings.find_one({"key": keys["experiment"]}, {"_id": 0})
    if not doc or not doc.get("papers"):
        logger.error(f"Fresh tournament: no papers for {dataset_id}")
        return

    papers_data = doc["papers"]
    s2_lookup = {e["paper_id"]: e["step2_assessment"] for e in papers_data if e.get("step2_assessment")}
    s3_lookup = {e["paper_id"]: e["step3_assessment"] for e in papers_data if e.get("step3_assessment")}

    paper_ids = list(s2_lookup.keys() & s3_lookup.keys())
    logger.info(f"Fresh tournament: {len(paper_ids)} papers with both assessments")

    # Load paper data
    papers = {}
    async for p in db.validation_papers.find(
        {"id": {"$in": paper_ids}, "dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "evaluations": 1, "composite_score": 1},
    ):
        papers[p["id"]] = p

    # Generate round-robin pairs (random subset — full round-robin for 100 papers = 4,950 pairs)
    import itertools
    all_pairs = list(itertools.combinations(list(papers.keys()), 2))
    random.shuffle(all_pairs)
    # Use all pairs — with 100 papers that's 4,950 pairs × 2 conditions = 9,900 matches
    # But to keep costs reasonable, limit to ~1,000 pairs (enough for convergence)
    max_pairs = min(len(all_pairs), 1000)
    pairs = all_pairs[:max_pairs]
    logger.info(f"Fresh tournament: {len(pairs)} pairs selected")

    # Check already completed
    existing_baseline = set()
    existing_dd = set()
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": {"$in": ["abstract_plus_summary", "deep_dive"]}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "content_mode": 1},
    ):
        key = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if m["content_mode"] == "abstract_plus_summary":
            existing_baseline.add(key)
        else:
            existing_dd.add(key)

    from core.config import DEFAULT_EVALUATION_PROMPT
    sem = asyncio.Semaphore(PARALLEL)

    # Run both conditions for each pair
    remaining = []
    for p1_id, p2_id in pairs:
        pair_key = tuple(sorted([p1_id, p2_id]))
        needs_baseline = pair_key not in existing_baseline
        needs_dd = pair_key not in existing_dd
        if needs_baseline or needs_dd:
            remaining.append((p1_id, p2_id, needs_baseline, needs_dd))

    total = sum(int(nb) + int(nd) for _, _, nb, nd in remaining)
    counter = {"done": 0, "errors": 0}
    await _update_progress(keys, "step4_fresh", 0, total)

    async def run_pair(p1_id, p2_id, do_baseline, do_dd):
        p1 = papers.get(p1_id)
        p2 = papers.get(p2_id)
        if not p1 or not p2:
            return

        # Pick ONE random judge model for both conditions (same pair = same judge)
        from core.config import TOURNAMENT_MODELS
        judge = random.choice(TOURNAMENT_MODELS)

        for mode, do_it, summary_lookup in [
            ("abstract_plus_summary", do_baseline, s2_lookup),
            ("deep_dive", do_dd, s3_lookup),
        ]:
            if not do_it:
                continue

            s1 = summary_lookup.get(p1_id, "")
            s2_text = summary_lookup.get(p2_id, "")
            if not s1 or not s2_text:
                counter["done"] += 1
                continue

            p1_content = f"Abstract: {p1.get('abstract','')[:1500]}\n\nAI Impact Assessment:\n{s1}"
            p2_content = f"Abstract: {p2.get('abstract','')[:1500]}\n\nAI Impact Assessment:\n{s2_text}"
            prompt = DEFAULT_EVALUATION_PROMPT["user_prompt"].format(
                paper1_title=p1["title"], paper1_content=p1_content,
                paper2_title=p2["title"], paper2_content=p2_content,
            )

            async with sem:
                try:
                    response = await _llm_call(
                        DEFAULT_EVALUATION_PROMPT["system_prompt"], prompt,
                        label=f"fresh:{mode[:5]}:{p1_id[:8]}",
                        model_override=judge,
                    )
                    resp_text = response
                    if resp_text.startswith("```"):
                        parts = resp_text.split("```")
                        if len(parts) >= 2:
                            resp_text = parts[1].lstrip("json").strip()
                    if not resp_text.startswith("{"):
                        jm = re.search(r'\{[^{}]*"winner"[^{}]*\}', resp_text, re.DOTALL)
                        if jm:
                            resp_text = jm.group()
                        else:
                            raise ValueError(f"No JSON: {resp_text[:100]}")

                    result = json.loads(resp_text)
                    winner = result.get("winner")
                    if winner not in ("paper1", "paper2"):
                        raise ValueError(f"Invalid: {result}")
                    winner_id = p1_id if winner == "paper1" else p2_id

                    match_doc = {
                        "id": str(uuid.uuid4()),
                        "dataset_id": dataset_id,
                        "paper1_id": p1_id, "paper2_id": p2_id,
                        "winner_id": winner_id,
                        "content_mode": mode,
                        "completed": True, "failed": False,
                        "abstract_only": False, "used_extraction": False,
                        "reasoning": result.get("reasoning", ""),
                        "model_used": judge,
                        "tokens": {},
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await db.validation_matches.insert_one(match_doc)

                    # Also store in replays collection for deep_dive mode
                    if mode == "deep_dive":
                        await db[keys["replays"]].insert_one({
                            **match_doc,
                            "original_match_id": None,
                            "original_winner_id": None,
                            "replay_winner_id": winner_id,
                            "flipped": False,
                        })

                except Exception as e:
                    counter["errors"] += 1
                    logger.warning(f"Fresh tournament failed [{mode}]: {e}")

                counter["done"] += 1
                if counter["done"] % 10 == 0:
                    await _update_progress(keys, "step4_fresh", counter["done"], total, counter["errors"])

    await asyncio.gather(*[run_pair(p1, p2, nb, nd) for p1, p2, nb, nd in remaining])
    await _update_progress(keys, "step4_fresh", total, total, errors=counter["errors"], finished=True)
    logger.info(f"Fresh tournament complete: {counter['done']} matches, {counter['errors']} errors")


async def run_full_pipeline_fresh(dataset_id: str):
    """Full pipeline for datasets without existing matches."""
    keys = _keys(dataset_id)
    await db.settings.update_one(
        {"key": keys["experiment"]},
        {"$setOnInsert": {"key": keys["experiment"], "dataset_id": dataset_id, "papers": [],
                          "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    logger.info(f"=== Fresh Deep Dive Pipeline: {dataset_id} ===")
    await run_step2(dataset_id)
    await run_step3(dataset_id)
    await run_fresh_tournament(dataset_id)
    logger.info(f"=== Fresh Pipeline COMPLETE: {dataset_id} ===")
