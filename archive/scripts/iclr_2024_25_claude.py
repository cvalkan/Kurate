"""Claude's judging accuracy on ICLR 2024/25 sub-topic datasets vs ICLR 2026.

Data in the DB: the `iclr-*` sub-topic datasets (iclr-codegen, iclr-llm, iclr-protein,
iclr-pdes, iclr-ot, iclr-fairness, iclr-molecules, iclr-optimization) are all
ICLR 2024 + 2025 papers (~50/50 mix each). `iclr-2026-validation` is the new
(still-running) 3,854-paper ICLR 2026 tournament.

For each dataset we compute per-model easy-pair accuracy (|Δ rating| ≥ 1.0)
and Spearman rho of model's TrueSkill rank vs h1_avg_rating.
"""
import asyncio
import os
from collections import defaultdict

import trueskill
from scipy.stats import spearmanr
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv()

ICLR_24_25 = ["iclr-codegen", "iclr-llm", "iclr-protein", "iclr-pdes",
              "iclr-ot", "iclr-fairness", "iclr-molecules", "iclr-optimization"]
MODELS_OF_INTEREST = ["claude-opus-4-6", "gemini-3-pro-preview",
                      "gpt-5.2", "gpt-5.4", "claude-opus-4-5-20251101"]


def ts_rank(pairs):
    env = trueskill.TrueSkill(draw_probability=0.0)
    r = defaultdict(env.create_rating)
    for w, l in pairs:
        nw, nl = env.rate_1vs1(r[w], r[l])
        r[w] = nw; r[l] = nl
    return {pid: rr.mu - 3 * rr.sigma for pid, rr in r.items()}


async def per_model(db, did):
    gt = {}
    async for p in db.validation_papers.find(
        {"dataset_id": did, "h1_avg_rating": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "h1_avg_rating": 1}
    ):
        try:
            gt[p["id"]] = float(p["h1_avg_rating"])
        except Exception:
            pass
    per = defaultdict(lambda: {"easy_n": 0, "easy_ok": 0, "hard_n": 0, "hard_ok": 0,
                                "pairs": []})
    async for m in db.validation_matches.find(
        {"dataset_id": did, "completed": True, "failed": {"$ne": True},
         "winner_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}
    ):
        model = (m.get("model_used") or {}).get("model", "?")
        p1, p2, w = m["paper1_id"], m["paper2_id"], m["winner_id"]
        loser = p2 if w == p1 else p1
        per[model]["pairs"].append((w, loser))
        r1, r2 = gt.get(p1), gt.get(p2)
        if r1 is None or r2 is None or r1 == r2:
            continue
        gap = abs(r1 - r2)
        better = p1 if r1 > r2 else p2
        correct = 1 if w == better else 0
        if gap >= 1.0:
            per[model]["easy_n"] += 1; per[model]["easy_ok"] += correct
        if gap < 0.5:
            per[model]["hard_n"] += 1; per[model]["hard_ok"] += correct
    # Compute spearman
    results = {}
    for model, d in per.items():
        rho = None
        if d["pairs"]:
            scores = ts_rank(d["pairs"])
            shared = sorted(set(scores) & set(gt))
            if len(shared) >= 30:
                xs = [scores[p] for p in shared]
                ys = [gt[p] for p in shared]
                rho, _ = spearmanr(xs, ys)
        results[model] = {
            "n_pairs": len(d["pairs"]),
            "easy_n": d["easy_n"], "easy_ok": d["easy_ok"],
            "hard_n": d["hard_n"], "hard_ok": d["hard_ok"],
            "rho": rho,
        }
    return results, len(gt)


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    try:
        # Per-dataset breakdown
        print(f"{'dataset':22} {'papers':>6} {'model':28} {'N':>6} {'easy acc':>9} {'hard acc':>9} {'Spearman':>9}")
        print("-" * 100)

        # Aggregated across all 8 ICLR 24/25 sub-datasets
        agg = defaultdict(lambda: {"easy_n": 0, "easy_ok": 0, "hard_n": 0, "hard_ok": 0,
                                     "rhos": [], "n_pairs": 0})
        total_gt = 0

        for did in ICLR_24_25:
            res, np_ = await per_model(db, did)
            total_gt += np_
            for model in MODELS_OF_INTEREST:
                if model not in res:
                    continue
                d = res[model]
                en, ek = d["easy_n"], d["easy_ok"]
                hn, hk = d["hard_n"], d["hard_ok"]
                ea = f"{100*ek/en:.2f}%" if en else "—"
                ha = f"{100*hk/hn:.2f}%" if hn else "—"
                rho = d["rho"]
                rho_s = f"{rho:+.4f}" if rho is not None else "—"
                print(f"{did:22} {np_:>6,} {model:28} {d['n_pairs']:>6,} {ea:>9} {ha:>9} {rho_s:>9}")
                agg[model]["easy_n"] += en; agg[model]["easy_ok"] += ek
                agg[model]["hard_n"] += hn; agg[model]["hard_ok"] += hk
                agg[model]["n_pairs"] += d["n_pairs"]
                if rho is not None:
                    agg[model]["rhos"].append(rho)

        # Aggregate row
        print("\n" + "=" * 100)
        print(f"\n{'ICLR 2024/25 AGGREGATE (8 sub-datasets, ~560 papers)':>60}")
        print(f"{'model':28} {'N matches':>10} {'easy acc':>9} {'hard acc':>9} {'median ρ':>9}")
        print("-" * 70)
        for model in MODELS_OF_INTEREST:
            a = agg[model]
            if a["n_pairs"] == 0:
                continue
            ea = f"{100*a['easy_ok']/a['easy_n']:.2f}%" if a["easy_n"] else "—"
            ha = f"{100*a['hard_ok']/a['hard_n']:.2f}%" if a["hard_n"] else "—"
            rhos = sorted(a["rhos"])
            median = rhos[len(rhos) // 2] if rhos else None
            rho_s = f"{median:+.4f}" if median is not None else "—"
            print(f"{model:28} {a['n_pairs']:>10,} {ea:>9} {ha:>9} {rho_s:>9}")

        # Compare to ICLR 2026
        print(f"\n{'ICLR 2026 (for comparison)':>60}")
        res, np_ = await per_model(db, "iclr-2026-validation")
        print(f"{'model':28} {'N matches':>10} {'easy acc':>9} {'hard acc':>9} {'Spearman':>9}")
        print("-" * 70)
        for model in MODELS_OF_INTEREST:
            if model not in res:
                continue
            d = res[model]
            en, ek = d["easy_n"], d["easy_ok"]
            hn, hk = d["hard_n"], d["hard_ok"]
            ea = f"{100*ek/en:.2f}%" if en else "—"
            ha = f"{100*hk/hn:.2f}%" if hn else "—"
            rho_s = f"{d['rho']:+.4f}" if d['rho'] is not None else "—"
            print(f"{model:28} {d['n_pairs']:>10,} {ea:>9} {ha:>9} {rho_s:>9}")
    finally:
        c.close()


if __name__ == "__main__":
    asyncio.run(main())
