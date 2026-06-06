"""Run CI-targeted pairwise tournament on DeFi papers.

Uses the same convergence logic as the live system:
- Wilson CI targets (10% top-K, 15% general)
- Smart pair selection (needy papers first, calibration ratio)
- Round-robin judge rotation
- Stores in defi_matches / defi_rankings (separate from live)
"""
import asyncio, os, sys, time, uuid, secrets, hashlib
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')

from core.config import db, DEFAULT_EVALUATION_PROMPT, TOURNAMENT_MODELS
from services.llm import compare_papers
from services.ranking import compute_leaderboard, wilson_margin_pct
from datetime import datetime, timezone

SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
PARALLEL = 15
CI_TARGET = 10       # Top-K CI margin target
CI_TARGET_GENERAL = 15  # General papers CI margin target
TOP_K = 10
MAX_PAIRS_PER_ROUND = 120
MAX_NEW_PER_PAPER = 5
MAX_ROUNDS = 50
CALIBRATION_RATIO = 50  # % of pairs that are needy-vs-established

async def load_papers():
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
            "id": pid, "title": doc.get("title", ""),
            "abstract": doc.get("abstract", ""),
            "authors": doc.get("authors", []) if isinstance(doc.get("authors"), list) else [doc.get("authors", "")],
            "ai_impact_summary": summary,
            "ai_rating": doc.get("ai_rating"),
            "published": doc.get("publication_date"),
        })
    return papers


async def load_stats(paper_ids):
    """Load per-paper stats from defi_matches."""
    stats = {pid: {"wins": 0, "losses": 0, "comparisons": 0, "score": 1200, "opponents": set()} for pid in paper_ids}
    async for m in db.defi_matches.find(
        {"completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1}
    ):
        p1, p2 = m["paper1_id"], m["paper2_id"]
        w = m["winner_id"]
        for pid in [p1, p2]:
            if pid in stats:
                stats[pid]["comparisons"] += 1
                if pid in [p1, p2]:
                    other = p2 if pid == p1 else p1
                    stats[pid]["opponents"].add(other)
        if w in stats:
            stats[w]["wins"] += 1
        loser = p2 if w == p1 else p1
        if loser in stats:
            stats[loser]["losses"] += 1
    return stats


def check_goals(stats, paper_ids, top_k_ids):
    """Check if convergence goals are met."""
    for pid in paper_ids:
        s = stats[pid]
        margin = wilson_margin_pct(s["wins"], s["comparisons"])
        target = CI_TARGET if pid in top_k_ids else CI_TARGET_GENERAL
        if margin > target:
            return False
    # Check top-K cross-matching
    for i, a in enumerate(list(top_k_ids)):
        for b in list(top_k_ids)[i+1:]:
            if b not in stats[a]["opponents"]:
                return False
    return True


def select_pairs(papers, stats, top_k_ids):
    """Select pairs using the same logic as the live system."""
    import random
    paper_ids = [p["id"] for p in papers]
    n = len(paper_ids)

    # Identify needy papers (CI > target)
    needy = []
    established = []
    for pid in paper_ids:
        s = stats[pid]
        margin = wilson_margin_pct(s["wins"], s["comparisons"])
        target = CI_TARGET if pid in top_k_ids else CI_TARGET_GENERAL
        if margin > target:
            needy.append(pid)
        else:
            established.append(pid)

    # Top-K cross-match pairs needed
    topk_pairs = []
    topk_list = list(top_k_ids)
    for i in range(len(topk_list)):
        for j in range(i+1, len(topk_list)):
            a, b = topk_list[i], topk_list[j]
            if b not in stats[a]["opponents"]:
                topk_pairs.append((a, b))

    pairs = []
    paper_new_count = {pid: 0 for pid in paper_ids}

    # Priority 1: Top-K cross-matches
    for a, b in topk_pairs[:MAX_PAIRS_PER_ROUND // 4]:
        if paper_new_count[a] < MAX_NEW_PER_PAPER and paper_new_count[b] < MAX_NEW_PER_PAPER:
            pairs.append((a, b))
            paper_new_count[a] += 1
            paper_new_count[b] += 1

    # Priority 2: Needy papers
    random.shuffle(needy)
    for pid in needy:
        if paper_new_count[pid] >= MAX_NEW_PER_PAPER:
            continue
        if len(pairs) >= MAX_PAIRS_PER_ROUND:
            break
        # Pick opponent: calibration_ratio% established, rest needy
        candidates = [c for c in paper_ids if c != pid and c not in stats[pid]["opponents"]]
        if not candidates:
            candidates = [c for c in paper_ids if c != pid]
        if not candidates:
            continue
        # Prefer established opponents for calibration
        est_candidates = [c for c in candidates if c in set(established)]
        if est_candidates and random.randint(1, 100) <= CALIBRATION_RATIO:
            opponent = random.choice(est_candidates)
        else:
            opponent = random.choice(candidates)
        if paper_new_count[opponent] < MAX_NEW_PER_PAPER:
            pairs.append((pid, opponent))
            paper_new_count[pid] += 1
            paper_new_count[opponent] += 1

    return pairs


async def run():
    papers = await load_papers()
    paper_lookup = {p["id"]: p for p in papers}
    paper_ids = [p["id"] for p in papers]
    n = len(papers)
    print(f"Tournament: {n} papers, CI targets: top-{TOP_K}={CI_TARGET}%, general={CI_TARGET_GENERAL}%", flush=True)
    print(f"Max {MAX_ROUNDS} rounds, {MAX_PAIRS_PER_ROUND} pairs/round, {PARALLEL}x parallel", flush=True)

    model_counter = 0
    total_completed = 0
    total_failed = 0
    t0 = time.time()

    for round_num in range(1, MAX_ROUNDS + 1):
        stats = await load_stats(paper_ids)

        # Compute current leaderboard for top-K identification
        matches_list = []
        async for m in db.defi_matches.find({"completed": True, "failed": {"$ne": True}}, {"_id": 0}):
            matches_list.append(m)
        if matches_list:
            lb = compute_leaderboard(papers, matches_list)
            sorted_lb = sorted(lb, key=lambda e: e.get("score", 0), reverse=True)
            top_k_ids = set(e["id"] for e in sorted_lb[:TOP_K])
        else:
            top_k_ids = set()

        # Check convergence
        if matches_list and check_goals(stats, paper_ids, top_k_ids):
            print(f"  Round {round_num}: ALL GOALS MET", flush=True)
            break

        pairs = select_pairs(papers, stats, top_k_ids)
        if not pairs:
            print(f"  Round {round_num}: no pairs needed", flush=True)
            break

        print(f"  Round {round_num}: {len(pairs)} pairs...", end="", flush=True)

        sem = asyncio.Semaphore(PARALLEL)
        round_ok = 0
        round_fail = 0

        async def run_match(p1_orig, p2_orig):
            nonlocal round_ok, round_fail, model_counter
            if secrets.randbelow(2):
                p1_id, p2_id = p2_orig, p1_orig
            else:
                p1_id, p2_id = p1_orig, p2_orig

            model_info = TOURNAMENT_MODELS[model_counter % len(TOURNAMENT_MODELS)]
            model_counter += 1

            async with sem:
                try:
                    result = await asyncio.wait_for(
                        compare_papers(paper_lookup[p1_id], paper_lookup[p2_id],
                                       DEFAULT_EVALUATION_PROMPT,
                                       content_mode="abstract_plus_summary",
                                       model_override=model_info),
                        timeout=120)
                except Exception as e:
                    result = e

                doc = {
                    "id": str(uuid.uuid4()),
                    "paper1_id": p1_id, "paper2_id": p2_id,
                    "content_mode": "abstract_plus_summary",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if isinstance(result, Exception):
                    doc.update({"completed": False, "failed": True, "error": str(result)[:200]})
                    round_fail += 1
                else:
                    winner_key = result.get("winner", "paper1")
                    doc.update({
                        "winner_id": p1_id if winner_key == "paper1" else p2_id,
                        "reasoning": result.get("reasoning", ""),
                        "model_used": result.get("model_used", {}),
                        "tokens": result.get("tokens", {}),
                        "completed": True, "failed": False,
                    })
                    round_ok += 1
                await db.defi_matches.insert_one(doc)

        await asyncio.gather(*[run_match(a, b) for a, b in pairs])
        total_completed += round_ok
        total_failed += round_fail
        elapsed = time.time() - t0
        print(f" {round_ok} ok, {round_fail} fail (total: {total_completed}, {elapsed:.0f}s)", flush=True)

    # Final rankings
    print("\nComputing final rankings...", flush=True)
    all_matches = []
    async for m in db.defi_matches.find({"completed": True, "failed": {"$ne": True}}, {"_id": 0}):
        all_matches.append(m)
    lb = compute_leaderboard(papers, all_matches)
    sorted_lb = sorted(lb, key=lambda e: e.get("score", 0), reverse=True)

    # Gap scores
    tournament_pct = {e["id"]: round((1 - i / max(len(sorted_lb) - 1, 1)) * 100, 1) for i, e in enumerate(sorted_lb)}
    rated = [(p["id"], p["ai_rating"]) for p in papers if p.get("ai_rating")]
    sorted_by_rating = sorted(rated, key=lambda x: x[1], reverse=True)
    rating_pct = {pid: round((1 - i / max(len(sorted_by_rating) - 1, 1)) * 100, 1) for i, (pid, _) in enumerate(sorted_by_rating)}

    # Store
    await db.defi_rankings.delete_many({})
    for e in sorted_lb:
        e.pop("_id", None)
        pid = e["id"]
        t_pct = tournament_pct.get(pid)
        r_pct = rating_pct.get(pid)
        if t_pct is not None and r_pct is not None:
            e["gap_score"] = round(t_pct - r_pct, 1)
        await db.defi_rankings.insert_one(e)

    # Update defi_papers
    for e in sorted_lb:
        pid = e["id"]
        query = {"paper_id": pid}
        exists = await db.defi_papers.find_one(query, {"_id": 1})
        if not exists:
            query = {"doi": pid}
            exists = await db.defi_papers.find_one(query, {"_id": 1})
        if not exists:
            query = {"openalex_id": pid}
            exists = await db.defi_papers.find_one(query, {"_id": 1})
        if exists:
            await db.defi_papers.update_one({"_id": exists["_id"]}, {"$set": {
                "tournament_score": e.get("score"),
                "tournament_win_rate": e.get("win_rate"),
                "tournament_comparisons": e.get("comparisons"),
                "tournament_wilson_margin": e.get("wilson_margin"),
                "tournament_rank": e.get("rank"),
                "gap_score": e.get("gap_score"),
            }})

    # Print results
    print(f"\n{'#':<4} {'Score':>6} {'Win%':>5} {'M':>4} {'CI':>5} {'Rtg':>4} {'Gap':>5}  Title", flush=True)
    print("-" * 105, flush=True)
    for i, e in enumerate(sorted_lb[:20]):
        p = paper_lookup.get(e["id"], {})
        gap = e.get("gap_score", "-")
        ci = e.get("wilson_margin", "-")
        print(f"{i+1:<4} {e.get('score', 0):>6} {e.get('win_rate', 0):>4}% {e.get('comparisons', 0):>4} {ci:>5} {str(p.get('ai_rating', '-')):>4} {gap:>5}  {p.get('title', '')[:55]}", flush=True)

    total_matches = await db.defi_matches.count_documents({"completed": True, "failed": {"$ne": True}})
    avg_comps = sum(e.get("comparisons", 0) for e in sorted_lb) / max(len(sorted_lb), 1)
    converged = sum(1 for e in sorted_lb if e.get("wilson_margin", 100) <= CI_TARGET_GENERAL)
    print(f"\nTotal matches: {total_matches}, Avg/paper: {avg_comps:.1f}, Converged: {converged}/{len(sorted_lb)}", flush=True)

asyncio.run(run())
