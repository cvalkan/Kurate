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
    """Single LLM call with timeout and budget retry."""
    model = model_override or ASSESSMENT_MODEL
    for attempt in range(5):
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
            logger.warning(f"Timeout ({label}), attempt {attempt+1}")
            await asyncio.sleep(5)
        except Exception as e:
            if any(kw in str(e).lower() for kw in _BUDGET_KEYWORDS):
                wait = 30 * (2 ** attempt)
                logger.warning(f"Budget error ({label}), waiting {wait}s")
                await asyncio.sleep(wait)
            else:
                raise
    raise Exception(f"LLM failed after retries ({label})")


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

    # Insert replays as validation_matches for convergence chart
    await _insert_as_validation_matches(keys, dataset_id)

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
    keys = _keys(dataset_id)
    replays = await db[keys["replays"]].find({}, {"_id": 0}).to_list(100000)
    if not replays:
        return {}

    # Load paper data for GT computation (handles both ICLR tiers and eLife ratings)
    paper_ids = set()
    for r in replays:
        paper_ids.add(r["paper1_id"]); paper_ids.add(r["paper2_id"])
    paper_gt = {}  # pid -> tier or avg_rating
    async for p in db.validation_papers.find(
        {"id": {"$in": list(paper_ids)}},
        {"_id": 0, "id": 1, "decision": 1, "evaluations": 1},
    ):
        tier = _decision_tier(p.get("decision", ""))
        if tier >= 0:
            paper_gt[p["id"]] = ("tier", tier)
        else:
            evals = p.get("evaluations", [])
            ratings = [ev["rating_value"] for ev in evals if ev.get("rating_value")]
            if ratings:
                paper_gt[p["id"]] = ("rating", sum(ratings) / len(ratings))

    # Recompute GT for each replay
    for r in replays:
        gt1 = paper_gt.get(r["paper1_id"])
        gt2 = paper_gt.get(r["paper2_id"])
        if gt1 and gt2 and gt1[0] == gt2[0] and gt1[1] != gt2[1]:
            gt_winner = r["paper1_id"] if gt1[1] > gt2[1] else r["paper2_id"]
            r["human_gt_winner"] = gt_winner
            r["original_agrees_human"] = r["original_winner_id"] == gt_winner
            r["replay_agrees_human"] = r["replay_winner_id"] == gt_winner

    total = len(replays)
    flipped = sum(1 for r in replays if r["flipped"])
    with_gt = [r for r in replays if r.get("human_gt_winner")]
    orig_agree = sum(1 for r in with_gt if r.get("original_agrees_human"))
    replay_agree = sum(1 for r in with_gt if r.get("replay_agrees_human"))

    analysis = {
        "total_replays": total,
        "flipped": flipped,
        "flip_rate": round(flipped / max(total, 1) * 100, 1),
        "human_agreement": {
            "pairs_with_gt": len(with_gt),
            "original": round(orig_agree / max(len(with_gt), 1) * 100, 1),
            "deep_dive": round(replay_agree / max(len(with_gt), 1) * 100, 1),
            "lift": round((replay_agree - orig_agree) / max(len(with_gt), 1) * 100, 1),
        },
    }

    # McNemar on human agreement
    a = b = c = d = 0
    for r in with_gt:
        oa = r.get("original_agrees_human")
        ra = r.get("replay_agrees_human")
        if oa and ra: a += 1
        elif oa and not ra: b += 1
        elif not oa and ra: c += 1
        else: d += 1
    mcnemar = {"pairs": len(with_gt), "both_agree": a, "only_original": b, "only_deepdive": c, "neither": d}
    if b + c > 0:
        chi2 = (abs(b - c) - 1)**2 / (b + c)
        p_val = math.erfc(math.sqrt(chi2 / 2))
        mcnemar.update({"chi2": round(chi2, 3), "p_value": round(p_val, 4), "significant": p_val < 0.05})
    else:
        mcnemar.update({"chi2": 0, "p_value": 1.0, "significant": False})
    analysis["mcnemar"] = mcnemar

    # Flip direction
    toward = sum(1 for r in with_gt if r["flipped"] and r.get("replay_agrees_human") and not r.get("original_agrees_human"))
    away = sum(1 for r in with_gt if r["flipped"] and not r.get("replay_agrees_human") and r.get("original_agrees_human"))
    analysis["flip_direction"] = {"toward_human": toward, "away_from_human": away, "net": toward - away}

    # Paper-level win rate shifts
    paper_stats = defaultdict(lambda: {"orig_wins": 0, "orig_total": 0, "dd_wins": 0, "dd_total": 0})
    for r in replays:
        for pid in [r["paper1_id"], r["paper2_id"]]:
            paper_stats[pid]["orig_total"] += 1
            paper_stats[pid]["dd_total"] += 1
            if r["original_winner_id"] == pid: paper_stats[pid]["orig_wins"] += 1
            if r["replay_winner_id"] == pid: paper_stats[pid]["dd_wins"] += 1

    wr_diffs = []
    paper_details = []
    title_lookup = {}
    async for p in db.validation_papers.find({"id": {"$in": list(paper_stats.keys())}}, {"_id": 0, "id": 1, "title": 1, "decision": 1}):
        title_lookup[p["id"]] = {"title": p["title"], "decision": p.get("decision", "")}
    for pid, s in paper_stats.items():
        if s["orig_total"] < 2: continue
        orig_wr = s["orig_wins"] / s["orig_total"]
        dd_wr = s["dd_wins"] / s["dd_total"]
        diff = dd_wr - orig_wr
        wr_diffs.append(diff)
        info = title_lookup.get(pid, {})
        paper_details.append({"paper_id": pid, "title": info.get("title", pid), "decision": info.get("decision", ""),
                              "orig_wr": round(orig_wr * 100, 1), "dd_wr": round(dd_wr * 100, 1),
                              "diff": round(diff * 100, 1), "matches": s["orig_total"]})
    paper_details.sort(key=lambda x: abs(x["diff"]), reverse=True)
    analysis["paper_level"] = {"n_papers": len(wr_diffs), "paper_details": paper_details}

    if len(wr_diffs) >= 5:
        import statistics
        analysis["paper_level"]["mean_wr_shift"] = round(statistics.mean(wr_diffs) * 100, 2)
        analysis["paper_level"]["median_wr_shift"] = round(statistics.median(wr_diffs) * 100, 2)
        analysis["paper_level"]["positive_shifts"] = sum(1 for d in wr_diffs if d > 0)
        analysis["paper_level"]["negative_shifts"] = sum(1 for d in wr_diffs if d < 0)

    return analysis


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
