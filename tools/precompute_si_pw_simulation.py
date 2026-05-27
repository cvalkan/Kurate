"""Precompute SI vs PW simulation results using the exact same data pipeline as the live API."""
import asyncio, random, json, sys
sys.path.insert(0, '/app/backend')

import numpy as np
from scipy import stats
import trueskill
from dotenv import load_dotenv; load_dotenv('/app/backend/.env')
from core.config import db
from services.model_analysis import _compute_live_analysis_impl


async def main():
    # Run the EXACT same analysis pipeline as the live API
    result = await _compute_live_analysis_impl(None)
    si_data = result.get("si_data", {})

    # Extract the model_scores that the live pipeline computed
    # These are in _si_model_scores_export, but it gets popped. Re-extract from si_data.
    # The inter_model_si correlations tell us which paper sets were used.
    # But we need the actual scores. Let's re-extract from the same papers.

    # Load papers the same way the live pipeline does
    papers = await db.rankings.find(
        {}, {"_id": 0, "paper_id": 1, "si_ratings": 1}
    ).to_list(50000)

    si_model_scores = {}
    for mk in ("claude", "gpt", "gemini"):
        scores = {}
        for p in papers:
            si = (p.get("si_ratings") or {}).get(mk)
            if isinstance(si, dict) and si.get("score"):
                scores[p["paper_id"]] = float(si["score"])
        if scores:
            si_model_scores[mk] = scores

    # Enrich from summaries — same logic as _compute_live_analysis_impl
    import re
    SUMMARY_KEYS = {
        "claude": "anthropic:claude-opus-4-6:thinking",
        "gpt": "openai:gpt-5_2",
        "gemini": "gemini:gemini-3-pro-preview",
    }
    needed = set()
    for p in papers:
        for mk in SUMMARY_KEYS:
            if p["paper_id"] not in si_model_scores.get(mk, {}):
                needed.add(p["paper_id"])
    async for doc in db.papers.find(
        {"id": {"$in": list(needed)}, "summaries": {"$exists": True}},
        {"_id": 0, "id": 1, "summaries": 1},
    ):
        for mk, skey in SUMMARY_KEYS.items():
            if doc["id"] in si_model_scores.get(mk, {}):
                continue
            summary = (doc.get("summaries") or {}).get(skey, "")
            if not summary:
                continue
            match = re.search(r'```json\s*(\{.*?\})\s*```', summary[-800:], re.DOTALL)
            if not match:
                match = re.search(r'\{[^{}]*"score"[^{}]*\}', summary[-400:])
            if match:
                try:
                    txt = match.group(1) if match.lastindex else match.group()
                    score = json.loads(txt).get("score")
                    if score:
                        si_model_scores.setdefault(mk, {})[doc["id"]] = float(score)
                except:
                    pass

    # Verify: our SI correlations should match the live API's
    live_si = si_data.get("inter_model_si", {})
    print("Verification — SI correlations match live API:")
    for m1, m2 in [("claude", "gemini"), ("claude", "gpt"), ("gemini", "gpt")]:
        common = sorted(set(si_model_scores.get(m1, {}).keys()) & set(si_model_scores.get(m2, {}).keys()))
        if len(common) >= 10:
            rho, _ = stats.spearmanr(
                [si_model_scores[m1][p] for p in common],
                [si_model_scores[m2][p] for p in common],
            )
            live = live_si.get(f"{m1} vs {m2}", {}).get("spearman", "?")
            ours = round(float(rho), 3)
            match_ok = "OK" if ours == live else "MISMATCH"
            print(f"  {m1} vs {m2}: live={live} ours={ours} n={len(common)} {match_ok}")

    # Load PW pairs
    pw_pair_winners = {}
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1},
    ):
        mu = m.get("model_used", {})
        raw = f"{mu.get('provider', '')}/{mu.get('model', '')}"
        if "claude" in raw or "opus" in raw: mk = "claude"
        elif "gemini" in raw: mk = "gemini"
        elif "gpt" in raw: mk = "gpt"
        else: continue
        p1, p2 = m["paper1_id"], m["paper2_id"]
        pair = (p1, p2) if p1 < p2 else (p2, p1)
        pw_pair_winners.setdefault(mk, {})[pair] = 1 if m.get("winner_id") == pair[0] else -1

    # Run simulations
    env = trueskill.TrueSkill(draw_probability=0.0)

    def run_sim(paper_list, m1, m2, seed):
        rng = random.Random(seed)
        common = sorted(set(si_model_scores[m1].keys()) & set(si_model_scores[m2].keys()) & set(paper_list))
        si_rho, _ = stats.spearmanr(
            [si_model_scores[m1][p] for p in common],
            [si_model_scores[m2][p] for p in common],
        )
        entry = {"si_correlation": round(float(si_rho), 3), "n_papers": len(common), "simulated": []}
        for mpp in [15, 18, 30, 45, 60]:
            ts1 = {p: env.create_rating() for p in paper_list}
            ts2 = {p: env.create_rating() for p in paper_list}
            for ts, mk in [(ts1, m1), (ts2, m2)]:
                scores = si_model_scores[mk]
                for _ in range(len(paper_list) * mpp // 2):
                    a, b = rng.sample(paper_list, 2)
                    sa, sb = scores.get(a, 5), scores.get(b, 5)
                    if sa == sb: continue
                    w, l = (a, b) if sa > sb else (b, a)
                    nw, nl = env.rate_1vs1(ts[w], ts[l])
                    ts[w] = nw; ts[l] = nl
            rho, _ = stats.spearmanr([ts1[p].mu for p in paper_list], [ts2[p].mu for p in paper_list])
            entry["simulated"].append({"mpp": mpp, "correlation": round(float(rho), 3)})
            print(f"    @{mpp}: {rho:.3f}", flush=True)
        return entry

    output = {"full": [], "controlled": []}
    for m1, m2 in [("claude", "gemini"), ("claude", "gpt"), ("gemini", "gpt")]:
        m1s, m2s = si_model_scores.get(m1, {}), si_model_scores.get(m2, {})

        # FULL: all papers with SI from both
        full_papers = sorted(set(m1s.keys()) & set(m2s.keys()))
        print(f"\n{m1} vs {m2} FULL ({len(full_papers)} papers)", flush=True)
        e = run_sim(full_papers, m1, m2, seed=42)
        e["pair"] = f"{m1} vs {m2}"
        output["full"].append(e)

        # CONTROLLED: papers in shared PW pairs with SI from both
        shared = set(pw_pair_winners.get(m1, {}).keys()) & set(pw_pair_winners.get(m2, {}).keys())
        ctrl_set = set()
        for a, b in shared:
            if a in m1s and b in m1s and a in m2s and b in m2s:
                ctrl_set.add(a); ctrl_set.add(b)
        ctrl_papers = sorted(ctrl_set)
        print(f"{m1} vs {m2} CONTROLLED ({len(ctrl_papers)} papers)", flush=True)
        e = run_sim(ctrl_papers, m1, m2, seed=43)
        e["pair"] = f"{m1} vs {m2}"
        output["controlled"].append(e)

    with open("/app/backend/data/precomputed/si_pw_simulation_results.json", "w") as f:
        json.dump(output, f)
    print("\nDONE", flush=True)


asyncio.run(main())
