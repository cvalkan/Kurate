"""Run a self-contained pairwise tournament on the 138 Blockchain & AI Agents papers.

Uses the same methodology as the live system:
- Round-robin judge rotation (GPT-5.2, Claude Opus 4.6, Gemini 3 Pro)
- abstract_plus_summary content mode (Claude 4.6 Thinking summaries)
- Random positional flipping for bias mitigation
- Wilson CI convergence targeting

Stores results in `defi_matches` and `defi_rankings` (separate from live system).
"""
import asyncio, os, sys, time, uuid, secrets, hashlib
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')

from core.config import db, DEFAULT_EVALUATION_PROMPT, TOURNAMENT_MODELS
from services.llm import compare_papers
from services.ranking import wilson_margin_pct, compute_leaderboard_async
from datetime import datetime, timezone

SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
PARALLEL = 15
MATCHES_PER_PAPER = 8  # Target matches per paper for reasonable convergence
CI_TARGET = 15  # Wilson CI margin target (%)

async def run():
    # Load papers
    papers = []
    async for doc in db.defi_papers.find(
        {"group": "blockchain_ai_agents",
         f"summaries.{SUMMARY_KEY}": {"$exists": True}},
        {"_id": 0, "title": 1, "abstract": 1, "authors": 1,
         f"summaries.{SUMMARY_KEY}": 1, "ai_rating": 1,
         "openalex_id": 1, "doi": 1, "paper_id": 1, "publication_date": 1}
    ):
        pid = doc.get("paper_id") or doc.get("doi") or doc.get("openalex_id") or hashlib.md5(doc["title"].encode()).hexdigest()[:16]
        summary = (doc.get("summaries") or {}).get(SUMMARY_KEY, "")
        papers.append({
            "id": pid,
            "title": doc.get("title", ""),
            "abstract": doc.get("abstract", ""),
            "authors": doc.get("authors", []) if isinstance(doc.get("authors"), list) else [doc.get("authors", "")],
            "ai_impact_summary": summary,
            "ai_rating": doc.get("ai_rating"),
            "published": doc.get("publication_date"),
        })

    total_papers = len(papers)
    print(f"Tournament: {total_papers} papers, {PARALLEL}x parallel judges", flush=True)

    paper_lookup = {p["id"]: p for p in papers}
    paper_ids = [p["id"] for p in papers]

    # Load existing defi matches to resume if interrupted
    existing_pairs = set()
    async for m in db.defi_matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        existing_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    print(f"Existing completed matches: {len(existing_pairs)}", flush=True)

    # Build per-paper match counts from existing matches
    paper_matches = {pid: 0 for pid in paper_ids}
    for p1, p2 in existing_pairs:
        if p1 in paper_matches: paper_matches[p1] += 1
        if p2 in paper_matches: paper_matches[p2] += 1

    # Select pairs: prioritize papers with fewest matches
    import random
    random.seed(42)
    target_total = total_papers * MATCHES_PER_PAPER // 2
    needed = max(0, target_total - len(existing_pairs))
    print(f"Target: {target_total} total matches, need {needed} more", flush=True)

    pairs_to_run = []
    all_possible = []
    for i in range(len(paper_ids)):
        for j in range(i + 1, len(paper_ids)):
            pair = tuple(sorted([paper_ids[i], paper_ids[j]]))
            if pair not in existing_pairs:
                all_possible.append(pair)

    # Prioritize: sort by sum of match counts (papers with fewer matches first)
    all_possible.sort(key=lambda p: paper_matches.get(p[0], 0) + paper_matches.get(p[1], 0))
    pairs_to_run = all_possible[:needed]
    random.shuffle(pairs_to_run)  # Shuffle for fair judge distribution

    print(f"Pairs to run: {len(pairs_to_run)}", flush=True)

    # Run matches
    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    model_counter = len(existing_pairs)  # Continue round-robin from where we left off
    t0 = time.time()

    async def run_match(p1_id, p2_id):
        nonlocal completed, failed, model_counter

        # Random positional flip
        if secrets.randbelow(2):
            p1_id, p2_id = p2_id, p1_id

        p1 = paper_lookup[p1_id]
        p2 = paper_lookup[p2_id]

        # Round-robin judge
        model_info = TOURNAMENT_MODELS[model_counter % len(TOURNAMENT_MODELS)]
        model_counter += 1

        async with sem:
            try:
                result = await asyncio.wait_for(
                    compare_papers(p1, p2, DEFAULT_EVALUATION_PROMPT,
                                   content_mode="abstract_plus_summary",
                                   model_override=model_info),
                    timeout=120,
                )
            except Exception as e:
                result = e

            match_doc = {
                "id": str(uuid.uuid4()),
                "paper1_id": p1_id, "paper2_id": p2_id,
                "dedup_pair": tuple(sorted([p1_id, p2_id])),
                "content_mode": "abstract_plus_summary",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            if isinstance(result, Exception):
                match_doc.update({"completed": False, "failed": True, "error": str(result)[:200]})
                failed += 1
            else:
                winner_key = result.get("winner", "paper1")
                match_doc.update({
                    "winner_id": p1_id if winner_key == "paper1" else p2_id,
                    "reasoning": result.get("reasoning", ""),
                    "model_used": result.get("model_used", {}),
                    "tokens": result.get("tokens", {}),
                    "completed": True, "failed": False,
                })
                completed += 1

            await db.defi_matches.insert_one(match_doc)

            done = completed + failed
            if done % 25 == 0 or done == len(pairs_to_run):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(pairs_to_run) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(pairs_to_run)}] {completed} ok, {failed} fail ({rate:.1f}/s, ETA {eta:.0f}s)", flush=True)

    await asyncio.gather(*[run_match(p1, p2) for p1, p2 in pairs_to_run])
    elapsed = time.time() - t0
    print(f"\nMatches done in {elapsed:.0f}s: {completed} completed, {failed} failed", flush=True)

    # Compute rankings
    print("\nComputing rankings...", flush=True)
    all_matches = []
    async for m in db.defi_matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
    ):
        all_matches.append(m)

    leaderboard = await compute_leaderboard_async(papers, all_matches)

    # Store rankings in defi_rankings
    await db.defi_rankings.delete_many({})
    for entry in leaderboard:
        entry.pop("_id", None)
        await db.defi_rankings.insert_one(entry)

    # Compute gap scores (tournament rank percentile vs AI rating percentile)
    print("Computing gap scores...", flush=True)
    n = len(leaderboard)
    # Rank by tournament score
    sorted_by_score = sorted(leaderboard, key=lambda e: e.get("score", 0), reverse=True)
    tournament_pct = {}
    for i, e in enumerate(sorted_by_score):
        tournament_pct[e["id"]] = round((1 - i / max(n - 1, 1)) * 100, 1)

    # Rank by AI rating
    rated = [(p["id"], p["ai_rating"]) for p in papers if p.get("ai_rating")]
    sorted_by_rating = sorted(rated, key=lambda x: x[1], reverse=True)
    rating_pct = {}
    for i, (pid, _) in enumerate(sorted_by_rating):
        rating_pct[pid] = round((1 - i / max(len(sorted_by_rating) - 1, 1)) * 100, 1)

    # Gap = tournament_pct - rating_pct
    for entry in leaderboard:
        pid = entry["id"]
        t_pct = tournament_pct.get(pid)
        r_pct = rating_pct.get(pid)
        gap = round(t_pct - r_pct, 1) if t_pct is not None and r_pct is not None else None
        if gap is not None:
            await db.defi_rankings.update_one(
                {"id": pid},
                {"$set": {"gap_score": gap, "tournament_pct": t_pct, "rating_pct": r_pct}}
            )

    # Print top 10
    print(f"\n{'#':<4} {'Score':>6} {'Win%':>5} {'M':>3} {'Rating':>6} {'Gap':>5}  Title", flush=True)
    print("-" * 100, flush=True)
    for i, e in enumerate(sorted_by_score[:15]):
        pid = e["id"]
        p = paper_lookup.get(pid, {})
        gap = round(tournament_pct.get(pid, 0) - rating_pct.get(pid, 0), 1) if pid in rating_pct else "-"
        print(f"{i+1:<4} {e.get('score', 0):>6} {e.get('win_rate', 0):>4}% {e.get('comparisons', 0):>3} {p.get('ai_rating', '-'):>6} {gap:>5}  {p.get('title', '')[:60]}", flush=True)

    total_matches = await db.defi_matches.count_documents({"completed": True, "failed": {"$ne": True}})
    total_rankings = await db.defi_rankings.count_documents({})
    print(f"\n=== Summary ===", flush=True)
    print(f"Papers: {total_rankings}", flush=True)
    print(f"Matches: {total_matches}", flush=True)
    print(f"Avg matches/paper: {sum(e.get('comparisons', 0) for e in leaderboard) / max(len(leaderboard), 1):.1f}", flush=True)

asyncio.run(run())
