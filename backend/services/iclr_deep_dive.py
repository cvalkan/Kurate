"""
Deep Dive ICLR Experiment — Full Pipeline

1. Generate first-pass assessments with focus areas (JSON block) for all papers
2. Generate deep-dive assessments informed by focus areas (standalone style)
3. Replay the tournament using deep-dive assessments
4. Compute metrics + convergence data

All results stored in DB, resumable at each step.
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

EXPERIMENT_KEY = "iclr_deep_dive_experiment"
PROGRESS_KEY = "iclr_deep_dive_progress"
REPLAY_COLLECTION = "iclr_deep_dive_replays"
DATASET_ID = "iclr-codegen"
MODEL = {"provider": "anthropic", "model": "claude-opus-4-6"}
PARALLEL = 5

_BUDGET_KEYWORDS = ("budget", "balance", "insufficient", "credit", "quota")


def _make_keys(dataset_id: str) -> dict:
    """Generate DB keys for a given dataset experiment."""
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

async def _llm_call(system_msg: str, user_msg: str, label: str = "") -> str:
    """Single LLM call with timeout and budget retry."""
    for attempt in range(5):
        try:
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"iclr-dd-{uuid.uuid4()}",
                system_message=system_msg,
            ).with_model(MODEL["provider"], MODEL["model"])

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


# --- Step 2: First-pass assessments with focus areas ---

async def run_step2():
    """Generate first-pass assessments with focus area JSON for all papers."""
    papers = await db.validation_papers.find(
        {"dataset_id": DATASET_ID},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1},
    ).to_list(200)

    doc = await db.settings.find_one({"key": EXPERIMENT_KEY}, {"_id": 0})
    existing = set()
    if doc and doc.get("papers"):
        existing = {p["paper_id"] for p in doc["papers"] if p.get("step2_assessment")}

    todo = [p for p in papers if p["id"] not in existing]
    total = len(papers)
    done = total - len(todo)
    await _update_progress("step2", done, total)

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
                response = await _llm_call(STEP2_PROMPT["system"], prompt, label=f"step2:{title[:30]}")

                focus_areas = []
                m = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
                if m:
                    try:
                        focus_areas = json.loads(m.group(1)).get("focus_areas", [])
                    except json.JSONDecodeError:
                        pass
                if not focus_areas:
                    for line in reversed(response.split('\n')):
                        line = line.strip()
                        if line.startswith('{') and 'focus_areas' in line:
                            try:
                                focus_areas = json.loads(line).get("focus_areas", [])
                            except json.JSONDecodeError:
                                pass
                            break

                assessment = re.sub(r'```json\s*\{.*?\}\s*```', '', response, flags=re.DOTALL).strip() or response

                entry = {"paper_id": pid, "title": title, "step2_assessment": assessment, "focus_areas": focus_areas}

                # Upsert: update if exists, push if not
                res = await db.settings.update_one(
                    {"key": EXPERIMENT_KEY, "papers.paper_id": pid},
                    {"$set": {"papers.$.step2_assessment": assessment, "papers.$.focus_areas": focus_areas}},
                )
                if res.matched_count == 0:
                    await db.settings.update_one(
                        {"key": EXPERIMENT_KEY},
                        {"$push": {"papers": entry}},
                        upsert=True,
                    )
                counter["done"] += 1
                logger.info(f"Step 2: {counter['done']}/{total} — {title[:50]} ({len(focus_areas)} focus areas)")
            except Exception as e:
                counter["errors"] += 1
                counter["done"] += 1
                logger.warning(f"Step 2 failed: {title[:50]}: {e}")

            if counter["done"] % 3 == 0:
                await _update_progress("step2", counter["done"], total, errors=counter["errors"])

    await asyncio.gather(*[process_one(p) for p in todo])
    await _update_progress("step2", total, total, finished=True)
    logger.info(f"Step 2 complete: {total} papers")


# --- Step 3: Deep-dive assessments ---

async def run_step3():
    """Generate deep-dive assessments informed by step 2 focus areas."""
    doc = await db.settings.find_one({"key": EXPERIMENT_KEY}, {"_id": 0})
    if not doc or not doc.get("papers"):
        logger.error("Step 3: no step 2 data found")
        return

    papers_data = doc["papers"]
    paper_lookup = {}
    async for p in db.validation_papers.find(
        {"dataset_id": DATASET_ID},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1},
    ):
        paper_lookup[p["id"]] = p

    todo = [e for e in papers_data if e.get("step2_assessment") and not e.get("step3_assessment")]
    total = len(papers_data)
    done = total - len(todo)
    await _update_progress("step3", done, total)

    sem = asyncio.Semaphore(PARALLEL)
    counter = {"done": done, "errors": 0}

    async def process_one(entry):
        pid = entry["paper_id"]
        paper = paper_lookup.get(pid)
        if not paper:
            return

        title = entry["title"]
        full_text = paper.get("full_text", "")
        abstract = paper.get("abstract", "")
        content = f"Abstract: {abstract[:1500]}\n\nFull Paper Text:\n{full_text}" if full_text else f"Abstract: {abstract[:3000]}"
        focus_str = ", ".join(entry.get("focus_areas", []))

        system = STEP3_PROMPT["system"].format(focus_areas=focus_str)
        user = STEP3_PROMPT["user"].format(title=title, content=content, first_pass_assessment=entry["step2_assessment"])

        async with sem:
            try:
                response = await _llm_call(system, user, label=f"step3:{title[:30]}")
                await db.settings.update_one(
                    {"key": EXPERIMENT_KEY, "papers.paper_id": pid},
                    {"$set": {"papers.$.step3_assessment": response}},
                )
                counter["done"] += 1
                logger.info(f"Step 3: {counter['done']}/{total} — {title[:50]}")
            except Exception as e:
                counter["errors"] += 1
                counter["done"] += 1
                logger.warning(f"Step 3 failed: {title[:50]}: {e}")

            if counter["done"] % 3 == 0:
                await _update_progress("step3", counter["done"], total, errors=counter["errors"])

    await asyncio.gather(*[process_one(e) for e in todo])
    await _update_progress("step3", total, total, finished=True)
    logger.info(f"Step 3 complete: {total} papers")


# --- Step 4: Replay tournament ---

async def run_step4():
    """Replay matches using deep-dive assessments (step 3) and compute metrics."""
    doc = await db.settings.find_one({"key": EXPERIMENT_KEY}, {"_id": 0})
    if not doc or not doc.get("papers"):
        logger.error("Step 4: no experiment data")
        return

    # Build paper_id -> step3 assessment lookup
    dd_lookup = {}
    for entry in doc["papers"]:
        if entry.get("step3_assessment"):
            dd_lookup[entry["paper_id"]] = entry["step3_assessment"]

    logger.info(f"Step 4: {len(dd_lookup)} papers with deep-dive assessments")

    # Load original matches
    orig_matches = await db.validation_matches.find(
        {"dataset_id": DATASET_ID, "completed": True, "failed": {"$ne": True},
         "content_mode": "abstract_plus_summary"},
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
    ).to_list(50000)

    # Deduplicate by pair
    seen = set()
    matches = []
    for m in orig_matches:
        pair_key = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        matches.append(m)

    # Check which are already replayed
    existing_replays = set()
    async for r in db[REPLAY_COLLECTION].find({}, {"_id": 0, "original_match_id": 1}):
        existing_replays.add(r["original_match_id"])

    remaining = [m for m in matches if m["id"] not in existing_replays]

    # Load paper data
    paper_ids = set()
    for m in remaining:
        paper_ids.add(m["paper1_id"])
        paper_ids.add(m["paper2_id"])

    papers = {}
    async for p in db.validation_papers.find(
        {"id": {"$in": list(paper_ids)}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "decision": 1,
         "ai_impact_summary_claude": 1, "ai_impact_summary_opus46": 1, "ai_impact_summary": 1},
    ):
        papers[p["id"]] = p

    total = len(remaining)
    await _update_progress("step4", 0, total)

    from core.config import DEFAULT_EVALUATION_PROMPT

    sem = asyncio.Semaphore(PARALLEL)
    counter = {"done": 0, "errors": 0}

    async def replay_one(m):
        p1 = papers.get(m["paper1_id"])
        p2 = papers.get(m["paper2_id"])
        if not p1 or not p2:
            counter["done"] += 1
            return

        p1_summary = dd_lookup.get(p1["id"]) or p1.get("ai_impact_summary_claude") or p1.get("ai_impact_summary", "")
        p2_summary = dd_lookup.get(p2["id"]) or p2.get("ai_impact_summary_claude") or p2.get("ai_impact_summary", "")

        p1_abs = p1.get("abstract", "")[:1500]
        p2_abs = p2.get("abstract", "")[:1500]
        p1_content = f"Abstract: {p1_abs}\n\nAI Impact Assessment:\n{p1_summary}"
        p2_content = f"Abstract: {p2_abs}\n\nAI Impact Assessment:\n{p2_summary}"

        prompt = DEFAULT_EVALUATION_PROMPT["user_prompt"].format(
            paper1_title=p1["title"], paper1_content=p1_content,
            paper2_title=p2["title"], paper2_content=p2_content,
        )

        async with sem:
            try:
                response = await _llm_call(DEFAULT_EVALUATION_PROMPT["system_prompt"], prompt, label=f"replay:{m['id'][:12]}")

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
                    raise ValueError(f"Invalid winner: {result}")

                winner_id = p1["id"] if winner == "paper1" else p2["id"]

                d1 = _decision_tier(p1.get("decision", ""))
                d2 = _decision_tier(p2.get("decision", ""))
                if d1 >= 0 and d2 >= 0 and d1 != d2:
                    gt_winner = p1["id"] if d1 > d2 else p2["id"]
                    orig_agrees = m.get("winner_id") == gt_winner
                    replay_agrees = winner_id == gt_winner
                else:
                    gt_winner = None
                    orig_agrees = None
                    replay_agrees = None

                record = {
                    "id": str(uuid.uuid4()),
                    "original_match_id": m["id"],
                    "paper1_id": m["paper1_id"],
                    "paper2_id": m["paper2_id"],
                    "original_winner_id": m.get("winner_id"),
                    "replay_winner_id": winner_id,
                    "flipped": winner_id != m.get("winner_id"),
                    "reasoning": result.get("reasoning", ""),
                    "human_gt_winner": gt_winner,
                    "original_agrees_human": orig_agrees,
                    "replay_agrees_human": replay_agrees,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db[REPLAY_COLLECTION].insert_one(record)

            except Exception as e:
                counter["errors"] += 1
                logger.warning(f"Step 4 replay failed: {m['id'][:20]}: {e}")

            counter["done"] += 1
            if counter["done"] % 5 == 0:
                await _update_progress("step4", counter["done"], total, errors=counter["errors"])

    await asyncio.gather(*[replay_one(m) for m in remaining])

    # Compute final analysis
    analysis = await compute_analysis()
    await db.settings.update_one(
        {"key": EXPERIMENT_KEY},
        {"$set": {"analysis": analysis, "completed_at": datetime.now(timezone.utc).isoformat()}},
    )
    await _update_progress("step4", total, total, errors=counter["errors"], finished=True)
    logger.info(f"Step 4 complete: {counter['done']} replays, {counter['errors']} errors")


_TIER = {"accept (oral)": 4, "accept (spotlight)": 3, "accept (poster)": 2,
         "withdrawn": 1, "desk rejected": 0, "reject": 0}


def _decision_tier(decision: str) -> int:
    return _TIER.get(decision.lower().strip(), -1)


# --- Analysis ---

async def compute_analysis() -> dict:
    """Compute metrics comparing deep-dive replay vs original tournament."""
    replays = await db[REPLAY_COLLECTION].find({}, {"_id": 0}).to_list(100000)
    if not replays:
        return {}

    total = len(replays)
    flipped = sum(1 for r in replays if r["flipped"])

    # Human agreement
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

    # Flip directionality
    toward = sum(1 for r in with_gt if r["flipped"] and r.get("replay_agrees_human") and not r.get("original_agrees_human"))
    away = sum(1 for r in with_gt if r["flipped"] and not r.get("replay_agrees_human") and r.get("original_agrees_human"))
    analysis["flip_direction"] = {"toward_human": toward, "away_from_human": away, "net": toward - away}

    # Per-paper win rate shift (paper-level test)
    paper_stats = defaultdict(lambda: {"orig_wins": 0, "orig_total": 0, "dd_wins": 0, "dd_total": 0})
    for r in replays:
        for pid in [r["paper1_id"], r["paper2_id"]]:
            paper_stats[pid]["orig_total"] += 1
            paper_stats[pid]["dd_total"] += 1
            if r["original_winner_id"] == pid:
                paper_stats[pid]["orig_wins"] += 1
            if r["replay_winner_id"] == pid:
                paper_stats[pid]["dd_wins"] += 1

    wr_diffs = []
    paper_details = []
    title_lookup = {}
    pids = list(paper_stats.keys())
    async for p in db.validation_papers.find({"id": {"$in": pids}}, {"_id": 0, "id": 1, "title": 1, "decision": 1}):
        title_lookup[p["id"]] = {"title": p["title"], "decision": p.get("decision", "")}

    for pid, s in paper_stats.items():
        if s["orig_total"] < 2:
            continue
        orig_wr = s["orig_wins"] / s["orig_total"]
        dd_wr = s["dd_wins"] / s["dd_total"]
        diff = dd_wr - orig_wr
        wr_diffs.append(diff)
        info = title_lookup.get(pid, {})
        paper_details.append({
            "paper_id": pid,
            "title": info.get("title", pid),
            "decision": info.get("decision", ""),
            "orig_wr": round(orig_wr * 100, 1),
            "dd_wr": round(dd_wr * 100, 1),
            "diff": round(diff * 100, 1),
            "matches": s["orig_total"],
        })

    paper_details.sort(key=lambda x: abs(x["diff"]), reverse=True)

    paper_level = {
        "n_papers": len(wr_diffs),
        "paper_details": paper_details,
    }

    if len(wr_diffs) >= 5:
        import statistics
        paper_level["mean_wr_shift"] = round(statistics.mean(wr_diffs) * 100, 2)
        paper_level["median_wr_shift"] = round(statistics.median(wr_diffs) * 100, 2)
        paper_level["positive_shifts"] = sum(1 for d in wr_diffs if d > 0)
        paper_level["negative_shifts"] = sum(1 for d in wr_diffs if d < 0)

        # Wilcoxon signed-rank
        nonzero = [d for d in wr_diffs if d != 0]
        if len(nonzero) >= 5:
            abs_diffs = [(abs(d), 1 if d > 0 else -1) for d in nonzero]
            abs_diffs.sort(key=lambda x: x[0])
            ranks = []
            i = 0
            while i < len(abs_diffs):
                j = i
                while j < len(abs_diffs) and abs_diffs[j][0] == abs_diffs[i][0]:
                    j += 1
                avg_rank = (i + 1 + j) / 2
                for k in range(i, j):
                    ranks.append((avg_rank, abs_diffs[k][1]))
                i = j
            w_plus = sum(r for r, s in ranks if s > 0)
            w_minus = sum(r for r, s in ranks if s < 0)
            w_stat = min(w_plus, w_minus)
            n = len(nonzero)
            mean_w = n * (n + 1) / 4
            std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
            z = (w_stat - mean_w) / std_w if std_w > 0 else 0
            p_val = math.erfc(abs(z) / math.sqrt(2))
            paper_level["wilcoxon"] = {"w_plus": round(w_plus, 1), "w_minus": round(w_minus, 1),
                                        "n_nonzero": n, "p_value": round(p_val, 4), "significant": p_val < 0.05}

        # Permutation test
        observed = statistics.mean(wr_diffs)
        count_extreme = 0
        for _ in range(10000):
            perm = [d * random.choice([-1, 1]) for d in wr_diffs]
            if abs(sum(perm) / len(perm)) >= abs(observed):
                count_extreme += 1
        perm_p = count_extreme / 10000
        paper_level["permutation_test"] = {"observed_mean": round(observed * 100, 2),
                                            "p_value": round(perm_p, 4), "significant": perm_p < 0.05}

    analysis["paper_level"] = paper_level
    return analysis


# --- Progress helper ---

async def _update_progress(step: str, done: int, total: int, errors: int = 0, finished: bool = False):
    await db.settings.update_one(
        {"key": PROGRESS_KEY},
        {"$set": {"key": PROGRESS_KEY, "step": step, "done": done, "total": total,
                  "errors": errors, "running": not finished, "finished": finished}},
        upsert=True,
    )


# --- Main runner ---

async def run_full_pipeline():
    """Run the complete 4-step pipeline."""
    # Ensure experiment doc exists
    await db.settings.update_one(
        {"key": EXPERIMENT_KEY},
        {"$setOnInsert": {"key": EXPERIMENT_KEY, "dataset_id": DATASET_ID, "papers": [],
                          "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    logger.info("=== ICLR Deep Dive Pipeline: Step 2 (first-pass assessments) ===")
    await run_step2()

    logger.info("=== ICLR Deep Dive Pipeline: Step 3 (deep-dive assessments) ===")
    await run_step3()

    logger.info("=== ICLR Deep Dive Pipeline: Step 4 (tournament replay) ===")
    await run_step4()

    logger.info("=== ICLR Deep Dive Pipeline: COMPLETE ===")
