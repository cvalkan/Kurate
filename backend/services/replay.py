"""
Match Replay Pipeline — Deeper Dive Experiment Phase 2

Replays existing main-tournament matches under two conditions:
  1. Control: Same original summaries, re-run (measures LLM stochasticity)
  2. Treatment: Enhanced assessments where available, original otherwise

Each replay is saved to DB individually (resumable on restart).
Statistical analysis: McNemar's test, flip rates, directional consistency, rank shift.
"""
import asyncio
import uuid
import random
import math
from datetime import datetime, timezone
from collections import defaultdict, Counter
from core.config import db, logger

REPLAY_COLLECTION = "deeper_dive_replays"


async def _load_experiment_meta() -> dict:
    """Load deeper dive experiment results and build paper metadata."""
    experiment = await db.settings.find_one({"key": "deeper_dive_experiment"}, {"_id": 0})
    results = experiment.get("results", []) if experiment else []

    recommended_titles = set()
    enhanced_by_title = {}
    original_by_title = {}
    for r in results:
        if r.get("parse_ok") and r.get("deeper_dive_recommended"):
            recommended_titles.add(r["title"])
            if r.get("enhanced_assessment"):
                enhanced_by_title[r["title"]] = r["enhanced_assessment"]
            if r.get("original_assessment"):
                original_by_title[r["title"]] = r["original_assessment"]

    # Map titles to tournament paper IDs
    title_to_meta = {}
    async for p in db.papers.find(
        {"title": {"$in": list(recommended_titles)}},
        {"_id": 0, "id": 1, "title": 1},
    ):
        title_to_meta[p["id"]] = {
            "recommended": True,
            "has_enhanced": p["title"] in enhanced_by_title,
            "enhanced_assessment": enhanced_by_title.get(p["title"]),
            "original_assessment": original_by_title.get(p["title"]),
        }

    return {
        "paper_meta": title_to_meta,
        "recommended_ids": set(title_to_meta.keys()),
    }


async def select_replay_pairs(max_pairs: int = 200) -> dict:
    """Select main-tournament match pairs to replay, prioritizing pairs
    involving deeper-dive-recommended papers.

    Returns dict with pairs list, strata counts, and paper metadata.
    """
    meta = await _load_experiment_meta()
    rec_ids = meta["recommended_ids"]

    if not rec_ids:
        return {"pairs": [], "strata": {}, "paper_meta": {}}

    # Load already-replayed pair+condition combos to skip
    existing_replays = set()
    async for r in db[REPLAY_COLLECTION].find({}, {"_id": 0, "original_match_id": 1, "condition": 1}):
        existing_replays.add((r["original_match_id"], r["condition"]))

    # Find completed matches involving at least one recommended paper
    matches = await db.matches.find(
        {
            "completed": True, "failed": {"$ne": True},
            "mode": {"$exists": False},
            "$or": [
                {"paper1_id": {"$in": list(rec_ids)}},
                {"paper2_id": {"$in": list(rec_ids)}},
            ],
        },
        {"_id": 0, "id": 1, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
         "primary_category": 1, "model_used": 1},
    ).to_list(50000)

    # Deduplicate by paper pair (keep first match per unique pair)
    seen_pairs = set()
    pairs = []
    for m in matches:
        pair_key = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        p1_rec = m["paper1_id"] in rec_ids
        p2_rec = m["paper2_id"] in rec_ids
        if p1_rec and p2_rec:
            stratum = "both_enhanced"
        elif p1_rec or p2_rec:
            stratum = "one_enhanced"
        else:
            stratum = "neither"

        pairs.append({
            "paper1_id": m["paper1_id"],
            "paper2_id": m["paper2_id"],
            "original_winner_id": m.get("winner_id"),
            "original_match_id": m["id"],
            "category": m.get("primary_category", ""),
            "stratum": stratum,
        })

    # Prioritize: both_enhanced first, then one_enhanced, then neither (for control)
    priority = {"both_enhanced": 0, "one_enhanced": 1, "neither": 2}
    pairs.sort(key=lambda p: priority.get(p["stratum"], 9))

    # Filter out already-replayed pairs (both conditions done)
    pairs = [p for p in pairs
             if (p["original_match_id"], "control") not in existing_replays
             or (p["original_match_id"], "treatment") not in existing_replays]

    if max_pairs:
        pairs = pairs[:max_pairs]

    strata = Counter(p["stratum"] for p in pairs)
    return {"pairs": pairs, "strata": dict(strata), "paper_meta": meta["paper_meta"]}


async def run_replay_experiment(max_pairs: int = 200, parallel: int = 3):
    """Run the match replay experiment: control + treatment for each pair.

    Each replay result is saved to DB immediately (resumable).
    """
    selection = await select_replay_pairs(max_pairs=max_pairs)
    pairs = selection["pairs"]
    paper_meta = selection["paper_meta"]

    if not pairs:
        logger.info("Replay: no pairs to replay")
        await db.settings.update_one(
            {"key": "replay_progress"},
            {"$set": {"key": "replay_progress", "running": False, "done": 0, "total": 0, "message": "No pairs available"}},
            upsert=True,
        )
        return

    conditions = ["control", "treatment"]
    total = len(pairs) * len(conditions)
    logger.info(f"Replay starting: {len(pairs)} pairs × {len(conditions)} conditions = {total} replays. Strata: {selection['strata']}")

    await db.settings.update_one(
        {"key": "replay_progress"},
        {"$set": {"key": "replay_progress", "running": True, "done": 0, "total": total,
                  "errors": 0, "strata": selection["strata"]}},
        upsert=True,
    )

    # Load paper data for all selected pairs
    paper_ids = set()
    for p in pairs:
        paper_ids.add(p["paper1_id"])
        paper_ids.add(p["paper2_id"])

    papers = {}
    async for p in db.papers.find(
        {"id": {"$in": list(paper_ids)}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "summaries": 1},
    ):
        papers[p["id"]] = p

    # Check which replays are already done (for resumability)
    existing = set()
    async for r in db[REPLAY_COLLECTION].find({}, {"_id": 0, "original_match_id": 1, "condition": 1}):
        existing.add((r["original_match_id"], r["condition"]))

    from core.config import DEFAULT_EVALUATION_PROMPT

    done = 0
    errors = 0
    sem = asyncio.Semaphore(parallel)

    for pair in pairs:
        p1 = papers.get(pair["paper1_id"])
        p2 = papers.get(pair["paper2_id"])
        if not p1 or not p2:
            done += len(conditions)
            continue

        for condition in conditions:
            # Skip if already done
            if (pair["original_match_id"], condition) in existing:
                done += 1
                continue

            async with sem:
                try:
                    # Build paper dicts with appropriate summary
                    p1_summary = _get_summary(p1, paper_meta.get(p1["id"], {}), condition)
                    p2_summary = _get_summary(p2, paper_meta.get(p2["id"], {}), condition)

                    p1_input = {**p1, "ai_impact_summary": p1_summary}
                    p2_input = {**p2, "ai_impact_summary": p2_summary}

                    # Use a dedicated single-shot LLM call instead of compare_papers
                    # (compare_papers has internal retries that hang on budget errors)
                    result = await _replay_single_comparison(p1_input, p2_input, DEFAULT_EVALUATION_PROMPT)

                    winner_id = p1["id"] if result["winner"] == "paper1" else p2["id"]
                    flipped = winner_id != pair["original_winner_id"]

                    meta1 = paper_meta.get(p1["id"], {})
                    meta2 = paper_meta.get(p2["id"], {})

                    record = {
                        "id": str(uuid.uuid4()),
                        "original_match_id": pair["original_match_id"],
                        "paper1_id": pair["paper1_id"],
                        "paper2_id": pair["paper2_id"],
                        "category": pair["category"],
                        "stratum": pair["stratum"],
                        "condition": condition,
                        "original_winner_id": pair["original_winner_id"],
                        "replay_winner_id": winner_id,
                        "flipped": flipped,
                        "reasoning": result.get("reasoning", ""),
                        "model_used": result.get("model_used", {}),
                        "tokens": result.get("tokens", {}),
                        "p1_used_enhanced": condition == "treatment" and bool(meta1.get("enhanced_assessment")),
                        "p2_used_enhanced": condition == "treatment" and bool(meta2.get("enhanced_assessment")),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }

                    await db[REPLAY_COLLECTION].insert_one(record)

                except asyncio.TimeoutError:
                    errors += 1
                    logger.warning(f"Replay timeout [{condition}]: {pair['original_match_id']}")
                except Exception as e:
                    err_str = str(e).lower()
                    is_budget = any(kw in err_str for kw in ("budget", "balance", "insufficient", "credit", "quota"))
                    if is_budget:
                        logger.warning("Replay budget error, waiting 60s...")
                        await asyncio.sleep(60)
                        done -= 1  # Don't count this as done, will retry on next run
                        continue
                    errors += 1
                    logger.warning(f"Replay failed [{condition}]: {pair['original_match_id']}: {e}")

                done += 1
                if done % 10 == 0:
                    await db.settings.update_one(
                        {"key": "replay_progress"},
                        {"$set": {"done": done, "errors": errors}},
                    )

    # Save final analysis
    analysis = await compute_replay_analysis()
    await db.settings.update_one(
        {"key": "replay_results"},
        {"$set": {"key": "replay_results", "analysis": analysis,
                  "completed_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await db.settings.update_one(
        {"key": "replay_progress"},
        {"$set": {"running": False, "done": done, "errors": errors}},
    )
    logger.info(f"Replay complete: {done} replays, {errors} errors")


def _get_summary(paper: dict, meta: dict, condition: str) -> str:
    """Get the appropriate summary for a paper given the condition."""
    if condition == "treatment" and meta.get("enhanced_assessment"):
        return meta["enhanced_assessment"]
    # Original: use the best available summary from the paper's summaries dict
    summaries = paper.get("summaries", {})
    for key in ["anthropic:claude-opus-4-6", "anthropic:claude-opus-4-5-20251101"]:
        s = summaries.get(key, "")
        if isinstance(s, str) and len(s) > 50:
            return s
    # Fallback to any summary
    for v in summaries.values():
        if isinstance(v, str) and len(v) > 50:
            return v
    return paper.get("abstract", "")[:1500]


async def compute_replay_analysis() -> dict:
    """Compute statistical analysis from all replay results in DB."""
    results = await db[REPLAY_COLLECTION].find({}, {"_id": 0}).to_list(100000)

    control = [r for r in results if r["condition"] == "control"]
    treatment = [r for r in results if r["condition"] == "treatment"]

    analysis = {
        "total_replays": len(results),
        "control_count": len(control),
        "treatment_count": len(treatment),
    }

    # --- Flip rates ---
    c_flips = sum(1 for r in control if r["flipped"])
    t_flips = sum(1 for r in treatment if r["flipped"])

    analysis["flip_rates"] = {
        "control": round(c_flips / max(len(control), 1) * 100, 1),
        "treatment": round(t_flips / max(len(treatment), 1) * 100, 1),
        "control_flips": c_flips,
        "treatment_flips": t_flips,
        "net_effect": round(
            (t_flips / max(len(treatment), 1) - c_flips / max(len(control), 1)) * 100, 1
        ),
    }

    # --- Flip rates by stratum ---
    by_stratum = {}
    for stratum in ["both_enhanced", "one_enhanced", "neither"]:
        c = [r for r in control if r["stratum"] == stratum]
        t = [r for r in treatment if r["stratum"] == stratum]
        cf = sum(1 for r in c if r["flipped"])
        tf = sum(1 for r in t if r["flipped"])
        by_stratum[stratum] = {
            "control": {"total": len(c), "flips": cf, "rate": round(cf / max(len(c), 1) * 100, 1)},
            "treatment": {"total": len(t), "flips": tf, "rate": round(tf / max(len(t), 1) * 100, 1)},
        }
    analysis["by_stratum"] = by_stratum

    # --- McNemar's test (paired: same pair, control vs treatment) ---
    control_by_pair = {r["original_match_id"]: r["flipped"] for r in control}
    treatment_by_pair = {r["original_match_id"]: r["flipped"] for r in treatment}
    common = set(control_by_pair) & set(treatment_by_pair)

    a = sum(1 for p in common if control_by_pair[p] and treatment_by_pair[p])
    b = sum(1 for p in common if control_by_pair[p] and not treatment_by_pair[p])
    c_val = sum(1 for p in common if not control_by_pair[p] and treatment_by_pair[p])
    d = sum(1 for p in common if not control_by_pair[p] and not treatment_by_pair[p])

    mcnemar = {"pairs": len(common), "both_flip": a, "only_control": b, "only_treatment": c_val, "neither": d}
    if b + c_val > 0:
        chi2 = (abs(b - c_val) - 1) ** 2 / (b + c_val)
        p_value = math.erfc(math.sqrt(chi2 / 2))
        mcnemar.update({"chi2": round(chi2, 3), "p_value": round(p_value, 4), "significant": p_value < 0.05})
    else:
        mcnemar.update({"chi2": 0, "p_value": 1.0, "significant": False})
    analysis["mcnemar"] = mcnemar

    # --- Directional consistency per paper ---
    # For each recommended paper, track: how often does it win/lose differently in treatment?
    paper_shifts = defaultdict(lambda: {"treatment_wins_gained": 0, "treatment_wins_lost": 0, "total": 0})
    for r in treatment:
        if not r["flipped"]:
            continue
        # Which paper gained a win?
        if r["p1_used_enhanced"]:
            pid = r["paper1_id"]
            if r["replay_winner_id"] == pid and r["original_winner_id"] != pid:
                paper_shifts[pid]["treatment_wins_gained"] += 1
            elif r["replay_winner_id"] != pid and r["original_winner_id"] == pid:
                paper_shifts[pid]["treatment_wins_lost"] += 1
        if r["p2_used_enhanced"]:
            pid = r["paper2_id"]
            if r["replay_winner_id"] == pid and r["original_winner_id"] != pid:
                paper_shifts[pid]["treatment_wins_gained"] += 1
            elif r["replay_winner_id"] != pid and r["original_winner_id"] == pid:
                paper_shifts[pid]["treatment_wins_lost"] += 1

    # Enrich with paper titles
    shifted_ids = list(paper_shifts.keys())
    title_lookup = {}
    if shifted_ids:
        async for p in db.papers.find({"id": {"$in": shifted_ids}}, {"_id": 0, "id": 1, "title": 1}):
            title_lookup[p["id"]] = p["title"]

    paper_shift_list = []
    for pid, shifts in paper_shifts.items():
        net = shifts["treatment_wins_gained"] - shifts["treatment_wins_lost"]
        paper_shift_list.append({
            "paper_id": pid,
            "title": title_lookup.get(pid, pid),
            "wins_gained": shifts["treatment_wins_gained"],
            "wins_lost": shifts["treatment_wins_lost"],
            "net_shift": net,
        })
    paper_shift_list.sort(key=lambda x: abs(x["net_shift"]), reverse=True)
    analysis["paper_shifts"] = paper_shift_list[:20]

    # --- Paper-level statistical tests (correct unit of analysis) ---
    # Compute per-paper win-rate shift: treatment win-rate minus control win-rate
    # This properly accounts for the correlation structure (repeated papers across pairs)

    # Find all enhanced paper IDs, then compute win rates
    enhanced_pids = set()
    for r in treatment:
        if r.get("p1_used_enhanced"):
            enhanced_pids.add(r["paper1_id"])
        if r.get("p2_used_enhanced"):
            enhanced_pids.add(r["paper2_id"])

    paper_stats = {pid: {"ctrl_wins": 0, "ctrl_total": 0, "treat_wins": 0, "treat_total": 0} for pid in enhanced_pids}

    for r in control:
        for pid in [r["paper1_id"], r["paper2_id"]]:
            if pid in paper_stats:
                paper_stats[pid]["ctrl_total"] += 1
                if r["replay_winner_id"] == pid:
                    paper_stats[pid]["ctrl_wins"] += 1

    for r in treatment:
        for pid in [r["paper1_id"], r["paper2_id"]]:
            if pid in paper_stats:
                paper_stats[pid]["treat_total"] += 1
                if r["replay_winner_id"] == pid:
                    paper_stats[pid]["treat_wins"] += 1

    # Compute per-paper win-rate differences
    wr_diffs = []
    paper_wr_details = []
    for pid, s in paper_stats.items():
        if s["ctrl_total"] == 0 or s["treat_total"] == 0:
            continue
        ctrl_wr = s["ctrl_wins"] / s["ctrl_total"]
        treat_wr = s["treat_wins"] / s["treat_total"]
        diff = treat_wr - ctrl_wr
        wr_diffs.append(diff)
        paper_wr_details.append({
            "paper_id": pid,
            "title": title_lookup.get(pid, pid),
            "ctrl_wr": round(ctrl_wr * 100, 1),
            "treat_wr": round(treat_wr * 100, 1),
            "diff": round(diff * 100, 1),
            "ctrl_matches": s["ctrl_total"],
            "treat_matches": s["treat_total"],
        })

    paper_wr_details.sort(key=lambda x: abs(x["diff"]), reverse=True)

    paper_level = {
        "n_papers": len(wr_diffs),
        "paper_details": paper_wr_details,
    }

    if len(wr_diffs) >= 5:
        import statistics
        mean_diff = statistics.mean(wr_diffs)
        median_diff = statistics.median(wr_diffs)
        positive = sum(1 for d in wr_diffs if d > 0)
        negative = sum(1 for d in wr_diffs if d < 0)
        zero = sum(1 for d in wr_diffs if d == 0)

        paper_level["mean_wr_shift"] = round(mean_diff * 100, 2)
        paper_level["median_wr_shift"] = round(median_diff * 100, 2)
        paper_level["positive_shifts"] = positive
        paper_level["negative_shifts"] = negative
        paper_level["zero_shifts"] = zero

        # Wilcoxon signed-rank test (non-parametric, paired)
        # H0: median win-rate shift = 0
        nonzero_diffs = [d for d in wr_diffs if d != 0]
        if len(nonzero_diffs) >= 5:
            # Manual Wilcoxon: rank absolute values, sum ranks of positive diffs
            abs_diffs = [(abs(d), 1 if d > 0 else -1) for d in nonzero_diffs]
            abs_diffs.sort(key=lambda x: x[0])
            # Assign ranks (handle ties with average rank)
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
            n = len(nonzero_diffs)

            # Normal approximation for p-value (n >= 10 recommended, but usable for n >= 5)
            mean_w = n * (n + 1) / 4
            std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
            if std_w > 0:
                z = (w_stat - mean_w) / std_w
                wilcoxon_p = math.erfc(abs(z) / math.sqrt(2))  # two-tailed
            else:
                wilcoxon_p = 1.0

            paper_level["wilcoxon"] = {
                "w_plus": round(w_plus, 1),
                "w_minus": round(w_minus, 1),
                "w_stat": round(w_stat, 1),
                "n_nonzero": n,
                "p_value": round(wilcoxon_p, 4),
                "significant": wilcoxon_p < 0.05,
            }
        else:
            paper_level["wilcoxon"] = {"n_nonzero": len(nonzero_diffs), "p_value": None, "note": "Too few non-zero differences"}

        # Permutation test (exact for small N)
        # Shuffle enhanced/original labels within each paper and recompute mean shift
        import random
        observed_mean = mean_diff
        n_permutations = 10000
        count_extreme = 0
        for _ in range(n_permutations):
            perm_diffs = [d * random.choice([-1, 1]) for d in wr_diffs]
            perm_mean = sum(perm_diffs) / len(perm_diffs)
            if abs(perm_mean) >= abs(observed_mean):
                count_extreme += 1
        perm_p = count_extreme / n_permutations

        paper_level["permutation_test"] = {
            "observed_mean_shift": round(observed_mean * 100, 2),
            "n_permutations": n_permutations,
            "p_value": round(perm_p, 4),
            "significant": perm_p < 0.05,
        }

    analysis["paper_level"] = paper_level

    # --- Per-category breakdown ---
    by_category = {}
    for cat in set(r.get("category", "") for r in results):
        if not cat:
            continue
        cc = [r for r in control if r.get("category") == cat]
        tt = [r for r in treatment if r.get("category") == cat]
        by_category[cat] = {
            "control": {"total": len(cc), "flips": sum(1 for r in cc if r["flipped"])},
            "treatment": {"total": len(tt), "flips": sum(1 for r in tt if r["flipped"])},
        }
    analysis["by_category"] = by_category

    return analysis
