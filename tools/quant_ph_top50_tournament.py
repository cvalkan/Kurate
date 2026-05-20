"""Top-50 quant-ph isolated tournament.

Picks the 50 highest-rated quant-ph papers (by single-item ai_rating in the
rankings collection) and runs a fresh pairwise tournament among them with
~20 matches per paper (500 unique pairs). Uses production prompt + round-robin
model selection (gpt-5.2, claude-opus-4-6, gemini-3.1-pro-preview), same as
the live scheduler. After completion, computes TrueSkill rankings from just
these matches and compares to the live ranking.

Output: /app/memory/quant_ph_top50_isolated_tournament.json with full match
log + final ranking comparison.
"""
import asyncio
import json
import os
import random
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from services.llm import compare_papers  # noqa: E402
import trueskill  # noqa: E402


CATEGORY = "quant-ph"
TOP_N = 50
TARGET_MATCHES_PER_PAPER = 20  # → ~500 unique pairs
SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
PARALLEL = 6
OUT_PATH = Path("/app/memory/quant_ph_top50_isolated_tournament.json")
PROGRESS_PATH = Path("/app/memory/quant_ph_top50_progress.json")


async def fetch_top50(db):
    docs = await db.rankings.find(
        {"category": CATEGORY, "ai_rating": {"$exists": True, "$ne": None}},
        {"_id": 0, "paper_id": 1, "title": 1, "ai_rating": 1,
         "ts_score": 1, "ts_mu": 1, "ts_sigma": 1, "rank_ts": 1,
         "comparisons": 1, "wins": 1, "losses": 1, "win_rate": 1}
    ).sort("ai_rating", -1).limit(TOP_N).to_list(length=TOP_N)
    return docs


async def fetch_papers(db, ids):
    out = {}
    async for p in db.papers.find(
        {"id": {"$in": ids}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{SUMMARY_KEY}": 1}
    ):
        s = (p.get("summaries") or {}).get(SUMMARY_KEY) or ""
        out[p["id"]] = {
            "id": p["id"],
            "title": p["title"],
            "abstract": p.get("abstract", ""),
            "ai_impact_summary": s if isinstance(s, str) else "",
        }
    return out


def build_pairs(paper_ids, target_per_paper, seed=42):
    """Pick a random subset of pairs that gives each paper ~target_per_paper matches."""
    n = len(paper_ids)
    target_total = (n * target_per_paper) // 2  # each pair adds 2 paper-matches
    all_pairs = list(combinations(paper_ids, 2))
    rng = random.Random(seed)
    rng.shuffle(all_pairs)
    selected = all_pairs[:target_total]
    return selected


async def run_one(sem, idx, total, paper1, paper2, results, start_t):
    async with sem:
        try:
            res = await compare_papers(paper1, paper2, content_mode="abstract_plus_summary")
        except Exception as e:
            res = {"error": str(e), "model_used": getattr(e, "model_used", None)}
        results.append({
            "pair_idx": idx,
            "p1": paper1["id"], "p2": paper2["id"],
            "p1_title": paper1["title"], "p2_title": paper2["title"],
            "winner": res.get("winner"),
            "model": (res.get("model_used") or {}),
            "reasoning": (res.get("reasoning") or "")[:200],
            "error": res.get("error"),
        })
        if (idx + 1) % 25 == 0 or (idx + 1) == total:
            elapsed = time.time() - start_t
            rate = (idx + 1) / elapsed if elapsed else 0
            eta = (total - idx - 1) / rate if rate else 0
            wins = sum(1 for r in results if r["winner"] in ("paper1", "paper2"))
            errs = sum(1 for r in results if r.get("error"))
            print(f"  [{idx+1:4d}/{total}] ok={wins} err={errs} rate={rate:.2f}/s eta={eta/60:.1f}min", flush=True)
            # Live progress dump
            PROGRESS_PATH.write_text(json.dumps({
                "done": len(results), "total": total, "wins": wins, "errs": errs,
                "rate_per_sec": round(rate, 2), "eta_min": round(eta/60, 1),
                "elapsed_min": round(elapsed/60, 1),
            }))


def compute_trueskill_ranking(paper_ids, matches):
    """Run TrueSkill update from scratch over the supplied match list."""
    env = trueskill.TrueSkill(draw_probability=0.0)
    ratings = {pid: env.create_rating() for pid in paper_ids}
    wins = {pid: 0 for pid in paper_ids}
    losses = {pid: 0 for pid in paper_ids}
    games = {pid: 0 for pid in paper_ids}
    rng = random.Random(0)
    shuffled = matches[:]
    rng.shuffle(shuffled)
    for m in shuffled:
        if m.get("winner") not in ("paper1", "paper2"):
            continue
        winner = m["p1"] if m["winner"] == "paper1" else m["p2"]
        loser = m["p2"] if m["winner"] == "paper1" else m["p1"]
        rw, rl = ratings[winner], ratings[loser]
        rw, rl = trueskill.rate_1vs1(rw, rl, env=env)
        ratings[winner], ratings[loser] = rw, rl
        wins[winner] += 1
        losses[loser] += 1
        games[winner] += 1; games[loser] += 1
    # Project to a conservative score (mu - 3*sigma scaled like production)
    out = []
    for pid in paper_ids:
        r = ratings[pid]
        out.append({
            "paper_id": pid,
            "iso_mu": r.mu,
            "iso_sigma": r.sigma,
            "iso_score": r.mu - 3 * r.sigma,
            "iso_wins": wins[pid],
            "iso_losses": losses[pid],
            "iso_games": games[pid],
        })
    out.sort(key=lambda x: x["iso_score"], reverse=True)
    for i, x in enumerate(out):
        x["iso_rank"] = i + 1
    return out


def correlations(live, iso):
    """Spearman + Kendall on the two ranking lists keyed by paper_id."""
    from scipy.stats import spearmanr, kendalltau
    live_rank = {r["paper_id"]: r["rank_ts"] for r in live}
    iso_rank = {r["paper_id"]: r["iso_rank"] for r in iso}
    common = sorted(live_rank.keys() & iso_rank.keys())
    a = [live_rank[p] for p in common]
    b = [iso_rank[p] for p in common]
    sp = spearmanr(a, b)
    kt = kendalltau(a, b)
    return {
        "spearman_r": float(sp.correlation), "spearman_p": float(sp.pvalue),
        "kendall_tau": float(kt.correlation), "kendall_p": float(kt.pvalue),
        "n": len(common),
    }


def biggest_movers(live, iso, n=15):
    live_rank = {r["paper_id"]: r for r in live}
    iso_rank = {r["paper_id"]: r for r in iso}
    rows = []
    for pid in live_rank:
        if pid not in iso_rank:
            continue
        delta = live_rank[pid]["rank_ts"] - iso_rank[pid]["iso_rank"]  # positive = moved up in iso
        rows.append({
            "paper_id": pid,
            "title": live_rank[pid]["title"],
            "ai_rating": live_rank[pid]["ai_rating"],
            "live_rank": live_rank[pid]["rank_ts"],
            "iso_rank": iso_rank[pid]["iso_rank"],
            "delta_rank": delta,
            "live_ts_score": live_rank[pid]["ts_score"],
            "live_comparisons": live_rank[pid]["comparisons"],
            "iso_games": iso_rank[pid]["iso_games"],
            "iso_wins": iso_rank[pid]["iso_wins"],
            "iso_losses": iso_rank[pid]["iso_losses"],
            "iso_winrate": iso_rank[pid]["iso_wins"] / max(iso_rank[pid]["iso_games"], 1),
        })
    rows.sort(key=lambda x: abs(x["delta_rank"]), reverse=True)
    return rows[:n]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    print(f"Fetching top {TOP_N} quant-ph papers by ai_rating...")
    live = await fetch_top50(db)
    ids = [r["paper_id"] for r in live]
    print(f"  Got {len(live)}")

    print("Fetching paper content + Claude summaries...")
    papers_map = await fetch_papers(db, ids)
    missing_sum = [pid for pid in ids if not papers_map.get(pid, {}).get("ai_impact_summary")]
    print(f"  {len(papers_map)}/{len(ids)} have content; {len(missing_sum)} missing Claude summary")

    pairs = build_pairs(ids, TARGET_MATCHES_PER_PAPER)
    print(f"Built {len(pairs)} pairs → ≈{len(pairs)*2/len(ids):.1f} matches/paper")

    sem = asyncio.Semaphore(PARALLEL)
    results = []
    start_t = time.time()
    print(f"Running tournament with PARALLEL={PARALLEL}...")
    tasks = []
    for i, (a, b) in enumerate(pairs):
        # Randomize order to avoid positional bias
        if random.random() < 0.5:
            a, b = b, a
        tasks.append(run_one(sem, i, len(pairs), papers_map[a], papers_map[b], results, start_t))
    await asyncio.gather(*tasks)
    elapsed = time.time() - start_t
    print(f"Tournament done in {elapsed/60:.1f} min ({len(results)} matches)")

    iso_ranking = compute_trueskill_ranking(ids, results)
    corr = correlations(live, iso_ranking)
    movers = biggest_movers(live, iso_ranking, n=20)

    output = {
        "category": CATEGORY,
        "top_n": TOP_N,
        "target_matches_per_paper": TARGET_MATCHES_PER_PAPER,
        "total_pairs_planned": len(pairs),
        "matches_completed": sum(1 for r in results if r["winner"] in ("paper1","paper2")),
        "matches_failed": sum(1 for r in results if r.get("error")),
        "elapsed_minutes": round(elapsed/60, 2),
        "model_distribution": _model_counts(results),
        "correlations": corr,
        "biggest_movers": movers,
        "live_top10": [{
            "rank": r["rank_ts"], "ai_rating": r["ai_rating"], "ts_score": r["ts_score"],
            "comparisons": r["comparisons"], "title": r["title"]
        } for r in sorted(live, key=lambda x: x["rank_ts"])[:10]],
        "iso_top10": [{
            "iso_rank": r["iso_rank"], "iso_score": round(r["iso_score"], 2),
            "iso_mu": round(r["iso_mu"], 2), "iso_sigma": round(r["iso_sigma"], 2),
            "iso_wins": r["iso_wins"], "iso_losses": r["iso_losses"],
            "title": next((p["title"] for p in live if p["paper_id"] == r["paper_id"]), "?")
        } for r in iso_ranking[:10]],
        "raw_matches": results,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nSaved: {OUT_PATH}")
    print(f"Spearman ρ = {corr['spearman_r']:.3f}  (Kendall τ = {corr['kendall_tau']:.3f}, n={corr['n']})")
    print("\nBiggest movers (live_rank → iso_rank):")
    for m in movers[:10]:
        print(f"  {m['live_rank']:3d} → {m['iso_rank']:3d}  Δ={m['delta_rank']:+3d}  "
              f"si={m['ai_rating']:.1f}  iso wr={m['iso_winrate']:.2f} ({m['iso_wins']}/{m['iso_games']})  "
              f"{m['title'][:60]}")


def _model_counts(results):
    counts = {}
    for r in results:
        m = (r.get("model") or {}).get("model") or "?"
        counts[m] = counts.get(m, 0) + 1
    return counts


if __name__ == "__main__":
    asyncio.run(main())
