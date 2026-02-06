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
_processing_lock = asyncio.Lock()

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
    await asyncio.sleep(5)  # Wait for app startup

    while _scheduler_running:
        try:
            settings = await get_settings()
            interval_hours = settings.get("fetch_interval_hours", 24)
            auto_process = settings.get("auto_process", True)

            # Check if we need to fetch
            last_fetch = settings.get("last_fetch_at")
            should_fetch = False

            if not last_fetch:
                should_fetch = True
            else:
                last_dt = datetime.fromisoformat(last_fetch)
                if datetime.now(timezone.utc) - last_dt > timedelta(hours=interval_hours):
                    should_fetch = True

            if should_fetch:
                await run_fetch_cycle()

            if auto_process:
                await run_comparison_round()

            # Update next fetch time
            settings = await get_settings()
            last_fetch = settings.get("last_fetch_at")
            if last_fetch:
                last_dt = datetime.fromisoformat(last_fetch)
                scheduler_status["next_fetch_at"] = (last_dt + timedelta(hours=interval_hours)).isoformat()

            # Update counts
            scheduler_status["papers_in_db"] = await db.papers.count_documents({})
            scheduler_status["matches_in_db"] = await db.matches.count_documents({"completed": True, "failed": {"$ne": True}})

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            scheduler_status["current_activity"] = f"Error: {str(e)[:100]}"

        await asyncio.sleep(300)  # Check every 5 minutes


async def run_fetch_cycle():
    if scheduler_status["is_fetching"]:
        return {"status": "already_fetching"}

    scheduler_status["is_fetching"] = True
    scheduler_status["current_activity"] = "Fetching new papers from arXiv..."

    try:
        settings = await get_settings()
        max_papers = settings.get("max_papers_per_fetch", 50)

        raw_papers = await fetch_arxiv_papers(category="cs.RO", max_results=max_papers)
        logger.info(f"Fetched {len(raw_papers)} papers from arXiv")

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

        now_iso = datetime.now(timezone.utc).isoformat()
        await db.settings.update_one(
            {"key": "global"},
            {"$set": {"last_fetch_at": now_iso}},
            upsert=True,
        )
        scheduler_status["last_fetch_at"] = now_iso
        scheduler_status["current_activity"] = f"Fetched {new_count} new papers"
        logger.info(f"Added {new_count} new papers to DB")

        # Download PDFs for new papers (only if not already downloaded in this run)
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
    papers_needing_pdf = await db.papers.find(
        {"needs_pdf": True, "pdf_link": {"$ne": None}},
        {"_id": 0, "id": 1, "pdf_link": 1, "title": 1},
    ).to_list(100)

    for i, paper in enumerate(papers_needing_pdf):
        scheduler_status["current_activity"] = f"Downloading PDF {i+1}/{len(papers_needing_pdf)}: {paper['title'][:40]}..."
        try:
            full_text = await download_and_extract_pdf(paper["pdf_link"])
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"full_text": full_text, "needs_pdf": False}},
            )
        except Exception as e:
            logger.warning(f"PDF download failed for {paper['id']}: {e}")
            await db.papers.update_one(
                {"id": paper["id"]},
                {"$set": {"needs_pdf": False}},
            )
        await asyncio.sleep(1)  # Rate limit PDF downloads


async def run_comparison_round():
    if _processing_lock.locked():
        return {"status": "already_processing"}

    async with _processing_lock:
        scheduler_status["is_processing"] = True
        scheduler_status["current_activity"] = "Running comparison round..."

        try:
            settings = await get_settings()
            comparisons_per_round = settings.get("comparisons_per_round", 20)
            top_k_focus = settings.get("top_k_focus", 10)
            exploration_constant = settings.get("exploration_constant", 1.414)
            anchor_comparisons = settings.get("anchor_comparisons", 4)
            min_matches_per_paper = settings.get("min_matches_per_paper", 3)

            # Load evaluation prompt (custom from DB if exists, else default)
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
                {}, {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1,
                     "authors": 1, "arxiv_id": 1, "link": 1, "published": 1, "pdf_link": 1}
            ).to_list(5000)

            if len(all_papers) < 2:
                scheduler_status["current_activity"] = "Not enough papers for comparisons"
                return {"status": "not_enough_papers"}

            # Download PDFs for any papers still missing full text
            papers_needing_pdf = [p for p in all_papers if not p.get("full_text") and p.get("pdf_link")]
            if papers_needing_pdf:
                scheduler_status["current_activity"] = f"Downloading {len(papers_needing_pdf)} PDFs..."
                for i, paper in enumerate(papers_needing_pdf):
                    scheduler_status["current_activity"] = f"Downloading PDF {i+1}/{len(papers_needing_pdf)}..."
                    try:
                        full_text = await download_and_extract_pdf(paper["pdf_link"])
                        if full_text:
                            paper["full_text"] = full_text
                            await db.papers.update_one(
                                {"id": paper["id"]},
                                {"$set": {"full_text": full_text, "needs_pdf": False}},
                            )
                    except Exception as e:
                        logger.warning(f"PDF download failed for {paper['id']}: {e}")
                    await asyncio.sleep(1)

            # Get all completed matches
            all_matches = await db.matches.find(
                {"completed": True, "failed": {"$ne": True}},
                {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "completed": 1, "failed": 1},
            ).to_list(100000)

            # Build stats
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

            # Generate match pairs using adaptive matchmaking
            pairs = _select_adaptive_pairs(
                all_papers, paper_stats, compared_pairs,
                comparisons_per_round, top_k_focus, exploration_constant, anchor_comparisons,
                min_matches_per_paper,
            )

            if not pairs:
                scheduler_status["current_activity"] = "No new pairs to compare"
                return {"status": "no_pairs"}

            paper_lookup = {p["id"]: p for p in all_papers}
            completed = 0
            failed = 0

            # Run comparisons in small parallel batches
            batch_size = 3
            for i in range(0, len(pairs), batch_size):
                batch = pairs[i:i + batch_size]
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
                        match_doc["completed"] = True
                        match_doc["failed"] = False
                        completed += 1

                    await db.matches.insert_one(match_doc)

                scheduler_status["current_activity"] = f"Comparing: {completed + failed}/{len(pairs)} done"
                await asyncio.sleep(0.5)

            now_iso = datetime.now(timezone.utc).isoformat()
            scheduler_status["last_process_at"] = now_iso
            scheduler_status["current_activity"] = f"Round complete: {completed} comparisons ({failed} failed)"
            logger.info(f"Comparison round: {completed} ok, {failed} failed")

            return {"status": "ok", "completed": completed, "failed": failed}

        except Exception as e:
            logger.error(f"Comparison round failed: {e}")
            scheduler_status["current_activity"] = f"Processing error: {str(e)[:100]}"
            return {"status": "error", "error": str(e)}
        finally:
            scheduler_status["is_processing"] = False


def _select_adaptive_pairs(
    papers: list, stats: dict, compared_pairs: set,
    max_pairs: int, top_k: int, exploration_c: float, anchor_n: int,
    min_matches: int = 3,
) -> List[tuple]:
    """
    Adaptive matchmaking:
    1. Papers below min_matches get priority
    2. New papers (0 comparisons) get matched against anchor papers for calibration
    3. UCB-based selection focuses on top-K boundary
    4. Periodically re-compare top papers for calibration
    """
    pairs = []
    paper_ids = [p["id"] for p in papers]

    # Separate new vs existing papers
    new_papers = [pid for pid in paper_ids if stats.get(pid, {}).get("comparisons", 0) == 0]
    under_min = [
        pid for pid in paper_ids
        if 0 < stats.get(pid, {}).get("comparisons", 0) < min_matches
    ]
    ranked_papers = sorted(
        [pid for pid in paper_ids if stats.get(pid, {}).get("comparisons", 0) > 0],
        key=lambda pid: stats[pid]["wins"] / max(stats[pid]["comparisons"], 1),
        reverse=True,
    )

    # Bootstrap: if ALL papers are new, do random pairwise comparisons
    if not ranked_papers and new_papers:
        shuffled = list(new_papers)
        random.shuffle(shuffled)
        for i in range(0, len(shuffled) - 1, 2):
            if len(pairs) >= max_pairs:
                break
            pair_key = tuple(sorted([shuffled[i], shuffled[i + 1]]))
            if pair_key not in compared_pairs:
                pairs.append((shuffled[i], shuffled[i + 1]))
                compared_pairs.add(pair_key)
        # Also add some cross-pairs for broader coverage
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

    # Phase 1: Calibrate new papers against anchors
    if new_papers and ranked_papers:
        # Pick anchor papers spread across the ranking
        n_ranked = len(ranked_papers)
        anchor_indices = []
        if n_ranked >= anchor_n:
            step = max(1, n_ranked // anchor_n)
            anchor_indices = list(range(0, n_ranked, step))[:anchor_n]
        else:
            anchor_indices = list(range(n_ranked))

        anchors = [ranked_papers[i] for i in anchor_indices]

        for new_pid in new_papers:
            for anchor_pid in anchors:
                pair_key = tuple(sorted([new_pid, anchor_pid]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((new_pid, anchor_pid))
                    compared_pairs.add(pair_key)

    # Phase 1b: Bring under-min papers up to minimum matches
    if under_min and ranked_papers and len(pairs) < max_pairs:
        for pid in under_min:
            needed = min_matches - stats.get(pid, {}).get("comparisons", 0)
            opponents = [r for r in ranked_papers if r != pid]
            random.shuffle(opponents)
            for opp in opponents[:needed]:
                pair_key = tuple(sorted([pid, opp]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((pid, opp))
                    compared_pairs.add(pair_key)

    # Phase 2: UCB-based selection focusing on top-K boundary
    if len(pairs) < max_pairs and len(ranked_papers) >= 2:
        total_comparisons = sum(s.get("comparisons", 0) for s in stats.values())

        # Papers near top-K boundary get priority
        boundary_start = max(0, top_k - 3)
        boundary_end = min(len(ranked_papers), top_k + 5)
        boundary_papers = set(ranked_papers[boundary_start:boundary_end])

        # Top papers that need more comparisons
        top_papers = set(ranked_papers[:top_k])
        priority_papers = boundary_papers | {
            p for p in top_papers
            if stats.get(p, {}).get("comparisons", 0) < 6
        }

        # UCB scores
        ucb_scores = {}
        for pid in paper_ids:
            s = stats.get(pid, {})
            wins = s.get("wins", 0)
            comps = s.get("comparisons", 0)
            if comps == 0:
                ucb_scores[pid] = float("inf")
            else:
                win_rate = wins / comps
                exploration = exploration_c * math.sqrt(math.log(total_comparisons + 1) / comps)
                ucb_scores[pid] = win_rate + exploration

        # Generate pairs prioritizing boundary papers
        all_candidates = sorted(paper_ids, key=lambda pid: ucb_scores.get(pid, 0), reverse=True)

        for p1 in priority_papers:
            for p2 in all_candidates:
                if p1 == p2:
                    continue
                pair_key = tuple(sorted([p1, p2]))
                if pair_key not in compared_pairs and len(pairs) < max_pairs:
                    pairs.append((p1, p2))
                    compared_pairs.add(pair_key)
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break

    # Phase 3: Re-calibration of top papers (if we still have budget)
    if len(pairs) < max_pairs and len(ranked_papers) >= 4:
        top_for_recal = ranked_papers[:min(top_k, len(ranked_papers))]
        random.shuffle(top_for_recal)
        for i in range(len(top_for_recal)):
            for j in range(i + 1, len(top_for_recal)):
                pair_key = tuple(sorted([top_for_recal[i], top_for_recal[j]]))
                # Allow re-comparison for calibration (don't check compared_pairs)
                if len(pairs) < max_pairs:
                    pairs.append((top_for_recal[i], top_for_recal[j]))
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break

    return pairs[:max_pairs]
