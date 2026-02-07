import asyncio
import uuid
import random
import math
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from core.config import db, logger, DEFAULT_SETTINGS
from core.auth import get_settings
from services.arxiv import fetch_arxiv_papers
from services.llm import download_and_extract_pdf, compare_papers
from services.ranking import calculate_confidence_interval

_scheduler_running = False
_processing_locks = {}  # Per-category locks

def _get_lock(category: str) -> asyncio.Lock:
    if category not in _processing_locks:
        _processing_locks[category] = asyncio.Lock()
    return _processing_locks[category]

# In-memory status for live UI updates
scheduler_status = {
    "last_fetch_at": None,
    "last_process_at": None,
    "is_fetching": False,
    "is_processing": False,
    "papers_in_db": 0,
    "matches_in_db": 0,
    "current_activity": "Idle",
    "next_fetch_at": None,
}


async def start_scheduler():
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True
    logger.info("Background scheduler started")
    asyncio.create_task(_scheduler_loop())


async def _scheduler_loop():
    global _scheduler_running
    await asyncio.sleep(5)

    while _scheduler_running:
        try:
            settings = await get_settings()
            interval_hours = settings.get("fetch_interval_hours", 24)
            is_paused = settings.get("paused", False)
            active_cats = settings.get("active_categories", ["cs.RO"])

            last_fetch = settings.get("last_fetch_at")
            should_fetch = False
            if not last_fetch:
                should_fetch = True
            else:
                last_dt = datetime.fromisoformat(last_fetch)
                if datetime.now(timezone.utc) - last_dt > timedelta(hours=interval_hours):
                    should_fetch = True

            if should_fetch:
                for cat in active_cats:
                    await run_fetch_cycle(category=cat)
                now_iso = datetime.now(timezone.utc).isoformat()
                await db.settings.update_one({"key": "global"}, {"$set": {"last_fetch_at": now_iso}}, upsert=True)
                scheduler_status["last_fetch_at"] = now_iso

            settings = await get_settings()
            last_fetch = settings.get("last_fetch_at")
            if last_fetch:
                last_dt = datetime.fromisoformat(last_fetch)
                scheduler_status["next_fetch_at"] = (last_dt + timedelta(hours=interval_hours)).isoformat()

            scheduler_status["papers_in_db"] = await db.papers.count_documents({})
            scheduler_status["matches_in_db"] = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}})

            if not is_paused:
                any_unmet = False
                for cat in active_cats:
                    if not await _check_goals_met(category=cat):
                        any_unmet = True
                        result = await run_comparison_round(category=cat)
                        if result.get("status") == "ok" and result.get("completed", 0) > 0:
                            break
                if any_unmet:
                    await asyncio.sleep(5)
                    continue
                else:
                    scheduler_status["current_activity"] = "Goals met — idle"
            else:
                scheduler_status["current_activity"] = "Paused"

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            scheduler_status["current_activity"] = f"Error: {str(e)[:100]}"

        await asyncio.sleep(300)


async def _check_goals_met(category: str = "cs.RO") -> bool:
    """Check if both ranking goals are satisfied for a category."""
    settings = await get_settings()
    min_matches = settings.get("min_matches_per_paper", 3)
    max_matches = settings.get("max_matches_per_paper", 150)
    top_k = settings.get("top_k_focus", 10)
    ci_target = settings.get("ci_target", 12)

    paper_ids = [p["id"] async for p in db.papers.find({"categories.0": category}, {"_id": 0, "id": 1})]
    if len(paper_ids) < 2:
        return True

    pid_set = set(paper_ids)
    paper_match_count = {pid: 0 for pid in paper_ids}
    paper_wins = {pid: 0 for pid in paper_ids}

    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set:
            paper_match_count[m["paper1_id"]] += 1
            paper_match_count[m["paper2_id"]] += 1
            w = m.get("winner_id")
            if w and w in paper_wins:
                paper_wins[w] += 1

    for c in paper_match_count.values():
        if c < min_matches:
            return False

    sorted_papers = sorted(
        paper_match_count.keys(),
        key=lambda pid: paper_wins.get(pid, 0) / max(paper_match_count.get(pid, 0), 1),
        reverse=True,
    )
    top_k_ids = sorted_papers[:min(top_k, len(sorted_papers))]
    for pid in top_k_ids:
        n = paper_match_count[pid]
        if n >= max_matches:
            continue  # Hit cap → considered converged
        w = paper_wins.get(pid, 0)
        from routers.admin import _wilson_margin
        margin_pct = _wilson_margin(w, n) * 100
        if margin_pct > ci_target:
            return False

    return True


def _compute_elo_ci(wins, comparisons):
    import math
    if comparisons < 2:
        return 999
    p = max(0.02, min(0.98, (wins + 0.5) / (comparisons + 1.0)))
    se_logit = 1.0 / math.sqrt((comparisons + 1.0) * p * (1.0 - p))
    se_elo = (400.0 / math.log(10)) * se_logit
    return 1.96 * se_elo


async def run_fetch_cycle(category: str = "cs.RO"):
    if scheduler_status["is_fetching"]:
        return {"status": "already_fetching"}

    scheduler_status["is_fetching"] = True
    scheduler_status["current_activity"] = f"Fetching {category} papers..."

    try:
        settings = await get_settings()
        max_papers = settings.get("max_papers_per_fetch", 50)

        raw_papers = await fetch_arxiv_papers(category=category, max_results=max_papers)
        logger.info(f"Fetched {len(raw_papers)} {category} papers from arXiv")

        new_count = 0
        for rp in raw_papers:
            exists = await db.papers.find_one({"arxiv_id": rp["arxiv_id"]}, {"_id": 0, "id": 1})
            if not exists:
                paper_doc = {
                    "id": str(uuid.uuid4()),
                    "arxiv_id": rp["arxiv_id"],
                    "title": rp["title"],
                    "authors": rp["authors"],
                    "abstract": rp["abstract"],
                    "categories": rp["categories"],
                    "published": rp["published"],
                    "link": rp["link"],
                    "pdf_link": rp.get("pdf_link"),
                    "full_text": None,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "needs_pdf": True,
                }
                await db.papers.insert_one(paper_doc)
                new_count += 1

        scheduler_status["current_activity"] = f"Fetched {new_count} new {category} papers"
        logger.info(f"Added {new_count} new {category} papers to DB")

        if new_count > 0:
            await _download_pending_pdfs()

        return {"status": "ok", "new_papers": new_count, "total_fetched": len(raw_papers)}

    except Exception as e:
        logger.error(f"Fetch cycle failed: {e}")
        scheduler_status["current_activity"] = f"Fetch failed: {str(e)[:100]}"
        return {"status": "error", "error": str(e)}
    finally:
        scheduler_status["is_fetching"] = False


async def _download_pending_pdfs():
    """Download PDFs for papers missing full_text. Shared by fetch and comparison cycles."""
    papers_needing_pdf = await db.papers.find(
        {"$or": [{"needs_pdf": True}, {"full_text": None}], "pdf_link": {"$ne": None}},
        {"_id": 0, "id": 1, "pdf_link": 1, "title": 1},
    ).to_list(200)

    if not papers_needing_pdf:
        return 0

    downloaded = 0
    for i, paper in enumerate(papers_needing_pdf):
        scheduler_status["current_activity"] = f"Downloading PDF {i+1}/{len(papers_needing_pdf)}: {paper['title'][:40]}..."
        try:
            full_text = await download_and_extract_pdf(paper["pdf_link"])
            if full_text:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"full_text": full_text, "needs_pdf": False}},
                )
                downloaded += 1
            else:
                await db.papers.update_one(
                    {"id": paper["id"]},
                    {"$set": {"needs_pdf": False}},
                )
        except Exception as e:
            logger.warning(f"PDF download failed for {paper['id']}: {e}")
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"needs_pdf": False}},
            )
        await asyncio.sleep(1)
    return downloaded


async def run_comparison_round(max_pairs_override=None, category: str = "cs.RO"):
    lock = _get_lock(category)
    if lock.locked():
        return {"status": "already_processing"}

    async with lock:
        scheduler_status["is_processing"] = True
        scheduler_status["current_activity"] = f"Comparing {category} papers..."

        try:
            settings = await get_settings()
            parallel_agents = min(max(settings.get("parallel_agents", 5), 1), 20)
            top_k_focus = settings.get("top_k_focus", 10)
            exploration_constant = settings.get("exploration_constant", 1.414)
            anchor_comparisons = settings.get("anchor_comparisons", 4)
            min_matches_per_paper = settings.get("min_matches_per_paper", 3)
            max_matches_per_paper = settings.get("max_matches_per_paper", 150)

            from core.config import DEFAULT_EVALUATION_PROMPT
            custom_prompt_doc = await db.settings.find_one({"key": "custom_prompt"}, {"_id": 0})
            if custom_prompt_doc:
                prompt_config = {
                    "system_prompt": custom_prompt_doc.get("system_prompt", DEFAULT_EVALUATION_PROMPT["system_prompt"]),
                    "user_prompt": custom_prompt_doc.get("user_prompt", DEFAULT_EVALUATION_PROMPT["user_prompt"]),
                }
            else:
                prompt_config = DEFAULT_EVALUATION_PROMPT

            all_papers = await db.papers.find(
                {"categories.0": category},
                {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                 "authors": 1, "arxiv_id": 1, "link": 1, "published": 1, "pdf_link": 1, "added_at": 1}
            ).to_list(5000)

            if len(all_papers) < 2:
                scheduler_status["current_activity"] = f"Not enough {category} papers"
                return {"status": "not_enough_papers"}

            # Download any missing PDFs
            papers_missing_text = sum(1 for p in all_papers if not p.get("full_text"))
            if papers_missing_text > 0:
                dl_count = await _download_pending_pdfs()
                if dl_count > 0:
                    all_papers = await db.papers.find(
                        {"categories.0": category},
                        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                         "authors": 1, "arxiv_id": 1, "link": 1, "published": 1, "pdf_link": 1, "added_at": 1}
                    ).to_list(5000)

            all_matches = await db.matches.find(
                {"completed": True, "failed": {"$ne": True}},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
            ).to_list(100000)

            paper_stats = {}
            for p in all_papers:
                paper_stats[p["id"]] = {"wins": 0, "losses": 0, "comparisons": 0}
            for m in all_matches:
                p1, p2, w = m["paper1_id"], m["paper2_id"], m.get("winner_id")
                if p1 in paper_stats:
                    paper_stats[p1]["comparisons"] += 1
                if p2 in paper_stats:
                    paper_stats[p2]["comparisons"] += 1
                if w and w in paper_stats:
                    paper_stats[w]["wins"] += 1
                loser = p2 if w == p1 else p1
                if loser in paper_stats:
                    paper_stats[loser]["losses"] += 1

            compared_pairs = set()
            for m in all_matches:
                compared_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

            # Generate as many useful pairs as the matchmaker finds
            if max_pairs_override:
                max_pairs = min(max_pairs_override, 500)
            else:
                max_pairs = min(100, len(all_papers) * 2)
            pairs = _select_adaptive_pairs(
                all_papers, paper_stats, compared_pairs,
                max_pairs, top_k_focus, exploration_constant, anchor_comparisons,
                min_matches_per_paper, max_matches_per_paper,
            )

            if not pairs:
                scheduler_status["current_activity"] = "No new pairs needed"
                return {"status": "no_pairs"}

            paper_lookup = {p["id"]: p for p in all_papers}
            completed = 0
            failed = 0
            total_matches = len(all_matches)

            for i in range(0, len(pairs), parallel_agents):
                batch = pairs[i:i + parallel_agents]
                tasks = []
                for p1_id, p2_id in batch:
                    tasks.append(compare_papers(paper_lookup[p1_id], paper_lookup[p2_id], prompt_config))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for (p1_id, p2_id), result in zip(batch, results):
                    match_doc = {
                        "id": str(uuid.uuid4()),
                        "paper1_id": p1_id,
                        "paper2_id": p2_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }

                    if isinstance(result, Exception):
                        match_doc["completed"] = False
                        match_doc["failed"] = True
                        match_doc["error"] = str(result)[:200]
                        match_doc["reasoning"] = f"Failed: {str(result)[:100]}"
                        failed += 1
                    else:
                        winner_key = result.get("winner", "paper1")
                        match_doc["winner_id"] = p1_id if winner_key == "paper1" else p2_id
                        match_doc["reasoning"] = result.get("reasoning", "")
                        match_doc["model_used"] = result.get("model_used", {})
                        match_doc["tokens"] = result.get("tokens", {})
                        match_doc["completed"] = True
                        match_doc["failed"] = False
                        completed += 1

                    await db.matches.insert_one(match_doc)

                scheduler_status["current_activity"] = f"Comparing... {total_matches + completed + failed} total matches"
                await asyncio.sleep(0.5)

            now_iso = datetime.now(timezone.utc).isoformat()
            scheduler_status["last_process_at"] = now_iso
            scheduler_status["current_activity"] = f"{total_matches + completed} total matches"
            logger.info(f"Comparison round: {completed} ok, {failed} failed")

            # Generate impact summaries for newly converged papers
            await _generate_pending_summaries()

            return {"status": "ok", "completed": completed, "failed": failed}

        except Exception as e:
            logger.error(f"Comparison round failed: {e}")
            scheduler_status["current_activity"] = f"Processing error: {str(e)[:100]}"
            return {"status": "error", "error": str(e)}
        finally:
            scheduler_status["is_processing"] = False


async def _generate_pending_summaries():
    """Generate impact summaries for converged papers that don't have one yet."""
    from services.llm import generate_impact_summary
    from routers.admin import _wilson_margin

    settings = await get_settings()
    ci_target = settings.get("ci_target", 12)
    max_matches = settings.get("max_matches_per_paper", 150)

    # Load summary prompt from DB
    summary_prompt_doc = await db.settings.find_one({"key": "summary_prompt"}, {"_id": 0})
    summary_prompt = summary_prompt_doc if summary_prompt_doc and summary_prompt_doc.get("system_prompt") else None

    # Find papers that are converged but have no summary
    # A paper is converged if Wilson margin ≤ target OR matches ≥ max cap
    all_papers = await db.papers.find(
        {"impact_summary": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "authors": 1},
    ).to_list(100)

    if not all_papers:
        # Also check papers with null summary
        all_papers = await db.papers.find(
            {"impact_summary": None},
            {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "authors": 1},
        ).to_list(100)

    if not all_papers:
        return

    # Get match counts
    paper_ids = [p["id"] for p in all_papers]
    paper_match_count = {pid: 0 for pid in paper_ids}
    paper_wins = {pid: 0 for pid in paper_ids}
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
    ):
        for pid in [m["paper1_id"], m["paper2_id"]]:
            if pid in paper_match_count:
                paper_match_count[pid] += 1
        w = m.get("winner_id")
        if w and w in paper_wins:
            paper_wins[w] += 1

    for paper in all_papers:
        pid = paper["id"]
        n = paper_match_count.get(pid, 0)
        w = paper_wins.get(pid, 0)

        if n < 3:
            continue  # Not enough data

        margin = float(_wilson_margin(w, n)) * 100
        is_converged = margin <= ci_target or n >= max_matches

        if not is_converged:
            continue

        # Get match logs for this paper
        matches = await db.matches.find(
            {"completed": True, "failed": {"$ne": True},
             "$or": [{"paper1_id": pid}, {"paper2_id": pid}]},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "reasoning": 1},
        ).to_list(500)

        # Get opponent titles
        opp_ids = set()
        for m in matches:
            opp_ids.add(m["paper2_id"] if m["paper1_id"] == pid else m["paper1_id"])
        opp_titles = {}
        async for o in db.papers.find({"id": {"$in": list(opp_ids)}}, {"_id": 0, "id": 1, "title": 1}):
            opp_titles[o["id"]] = o["title"]

        logs = []
        for m in matches:
            opp_id = m["paper2_id"] if m["paper1_id"] == pid else m["paper1_id"]
            logs.append({
                "won": m.get("winner_id") == pid,
                "opponent_title": opp_titles.get(opp_id, "Unknown"),
                "reasoning": m.get("reasoning", ""),
            })

        scheduler_status["current_activity"] = f"Generating summary: {paper['title'][:40]}..."
        logger.info(f"Generating impact summary for: {paper['title'][:50]}")

        summary = await generate_impact_summary(paper, logs, summary_prompt)
        if summary:
            await db.papers.update_one(
                {"id": pid},
                {"$set": {"impact_summary": summary, "summary_generated_at": datetime.now(timezone.utc).isoformat()}},
            )
            logger.info(f"Summary generated for {pid}")
        else:
            # Mark as attempted so we don't retry every round
            await db.papers.update_one(
                {"id": pid},
                {"$set": {"impact_summary": None, "summary_generated_at": datetime.now(timezone.utc).isoformat()}},
            )

        await asyncio.sleep(1)  # Rate limit



def _select_adaptive_pairs(
    papers: list, stats: dict, compared_pairs: set,
    max_pairs: int, top_k: int, exploration_c: float, anchor_n: int,
    min_matches: int = 3, max_matches: int = 150,
) -> List[tuple]:
    """
    Priority-ordered matchmaking:
    1. Bootstrap (all new) → random pairs
    2. Bring ALL papers to min_matches before anything else
    3. Only after min_matches is met for all: CI narrowing for top-K
    4. UCB exploration for remaining budget
    """
    pairs = []
    paper_ids = [p["id"] for p in papers]
    capped = {pid for pid in paper_ids if stats.get(pid, {}).get("comparisons", 0) >= max_matches}
    active_ids = [pid for pid in paper_ids if pid not in capped]

    new_papers = [pid for pid in active_ids if stats.get(pid, {}).get("comparisons", 0) == 0]
    under_min = [
        pid for pid in active_ids
        if 0 < stats.get(pid, {}).get("comparisons", 0) < min_matches
    ]
    ranked_papers = sorted(
        [pid for pid in active_ids if stats.get(pid, {}).get("comparisons", 0) > 0],
        key=lambda pid: stats[pid]["wins"] / max(stats[pid]["comparisons"], 1),
        reverse=True,
    )
    all_at_min = not new_papers and not under_min

    # --- Phase 1: Bootstrap (all papers are new) ---
    if not ranked_papers and new_papers:
        shuffled = list(new_papers)
        random.shuffle(shuffled)
        for i in range(len(shuffled)):
            for j in range(i + 1, len(shuffled)):
                if len(pairs) >= max_pairs:
                    break
                pair_key = tuple(sorted([shuffled[i], shuffled[j]]))
                if pair_key not in compared_pairs:
                    pairs.append((shuffled[i], shuffled[j]))
                    compared_pairs.add(pair_key)
            if len(pairs) >= max_pairs:
                break
        return pairs[:max_pairs]

    # --- Phase 2: New papers get anchor matches ---
    if new_papers and ranked_papers:
        n_ranked = len(ranked_papers)
        step = max(1, n_ranked // anchor_n) if n_ranked >= anchor_n else 1
        anchors = [ranked_papers[i] for i in range(0, n_ranked, step)][:anchor_n]
        for new_pid in new_papers:
            for anchor_pid in anchors:
                pair_key = tuple(sorted([new_pid, anchor_pid]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((new_pid, anchor_pid))
                    compared_pairs.add(pair_key)

    # --- Phase 3: Bring under-min papers up EVENLY ---
    # Sort by fewest matches first so the most neglected papers get priority
    if under_min and len(pairs) < max_pairs:
        under_min_sorted = sorted(under_min, key=lambda pid: stats.get(pid, {}).get("comparisons", 0))
        all_opponents = list(active_ids)
        for pid in under_min_sorted:
            if len(pairs) >= max_pairs:
                break
            needed = min_matches - stats.get(pid, {}).get("comparisons", 0)
            random.shuffle(all_opponents)
            added = 0
            for opp in all_opponents:
                if opp == pid:
                    continue
                pair_key = tuple(sorted([pid, opp]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((pid, opp))
                    compared_pairs.add(pair_key)
                    added += 1
                    if added >= needed:
                        break

    # --- Phase 4: Recent paper fairness (48h papers vs top-K) ---
    if all_at_min and len(pairs) < max_pairs and ranked_papers:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        top_k_papers = ranked_papers[:min(top_k, len(ranked_papers))]
        for p in papers:
            added = p.get("added_at")
            if not added or p["id"] in capped:
                continue
            try:
                if datetime.fromisoformat(added) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            for top_pid in top_k_papers:
                if p["id"] == top_pid:
                    continue
                pair_key = tuple(sorted([p["id"], top_pid]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((p["id"], top_pid))
                    compared_pairs.add(pair_key)

    # --- Phase 5: CI narrowing for top-K (ONLY after all papers have min_matches) ---
    if all_at_min and len(pairs) < max_pairs and len(ranked_papers) >= 2:
        top_k_papers = ranked_papers[:min(top_k, len(ranked_papers))]
        # Only give new unique opponents, no re-matches
        all_potential = [pid for pid in active_ids if pid not in set(top_k_papers)]
        random.shuffle(all_potential)

        for focus_pid in top_k_papers:
            if len(pairs) >= max_pairs:
                break
            for opp in all_potential + ranked_papers:
                if opp == focus_pid:
                    continue
                pair_key = tuple(sorted([focus_pid, opp]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((focus_pid, opp))
                    compared_pairs.add(pair_key)
                    break

    # --- Phase 6: UCB exploration (max 2 new matches per paper per round) ---
    if len(pairs) < max_pairs and len(ranked_papers) >= 2:
        total_comparisons = sum(s.get("comparisons", 0) for s in stats.values())
        ucb_scores = {}
        for pid in active_ids:
            s = stats.get(pid, {})
            comps = s.get("comparisons", 0)
            if comps == 0:
                ucb_scores[pid] = float("inf")
            else:
                ucb_scores[pid] = s.get("wins", 0) / comps + exploration_c * math.sqrt(math.log(total_comparisons + 1) / comps)

        candidates = sorted(active_ids, key=lambda pid: ucb_scores.get(pid, 0), reverse=True)
        round_count = {pid: 0 for pid in active_ids}
        max_per_paper = 2

        for p1 in candidates:
            if round_count[p1] >= max_per_paper:
                continue
            for p2 in candidates:
                if p1 >= p2 or round_count[p2] >= max_per_paper:
                    continue
                pair_key = tuple(sorted([p1, p2]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((p1, p2))
                    compared_pairs.add(pair_key)
                    round_count[p1] += 1
                    round_count[p2] += 1
                    break  # Move to next p1
            if len(pairs) >= max_pairs:
                break

    return pairs[:max_pairs]
