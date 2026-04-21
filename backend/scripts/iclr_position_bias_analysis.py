"""ICLR 2026 positional-bias analysis (no new LLM calls).

Runs four statistical tests on already-judged matches from:
  - dataset_id = "iclr-2026-validation"      (cross-label, ~58K pairs)
  - dataset_id = "iclr-2026-within-label"    (same-tier pairs, ~22K)

Tests:
  1. Position Consistency vs human-score-gap decile
       (per model × gap metric) — Spearman rank correlation.
       Falls back to an "accuracy-asymmetry-by-gap" test when per-pair
       dual-orderings are unavailable (the standard situation when each
       pair is judged exactly once per model).

  2. Inconsistency direction: primacy vs recency (per model, per gap bin).
       Requires both orderings by same model on same pair. Skipped
       with a clear note when data isn't available.

  4. Within-label vs cross-label comparison (two-proportion z-test on
     model agreement with the human decision tier).

 10. Temporal drift within the validation run — rolling pos1-rate and
     model agreement vs created_at, per model.

Usage:
    export MONGO_URL="mongodb://<prod-uri>"
    export DB_NAME="<prod-db>"
    cd /app/backend && python3 scripts/iclr_position_bias_analysis.py \\
        --out /app/memory/ICLR_POSITION_BIAS_REPORT.md
"""
import argparse
import asyncio
import math
import os
import statistics as pystats
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

try:
    import numpy as np
    import pandas as pd
    from scipy import stats as sp
except ImportError as e:
    print(f"Missing dependency: {e}. pip install pandas scipy numpy", file=sys.stderr)
    sys.exit(1)


VALIDATION_DS = "iclr-2026-validation"
WITHIN_LABEL_DS = "iclr-2026-within-label"

TIER_RANK = {
    "Oral": 1, "Spotlight": 2, "Poster": 3, "Highlight": 2,
    "Reject": 4, "Withdraw": 5, "Desk Reject": 5, "Desk Rejected": 5,
}


def load_dataset_from_jsonl(matches_path: Path, summaries_path: Path, dataset_id: str) -> pd.DataFrame:
    """Build the same dataframe shape from local ICLR JSONL files (no MongoDB).

    matches_path rows:
      {id_1, id_2, winner, model, flipped, reasoning, tokens_*, elapsed_s}
    summaries_path rows:
      {openreview_id, title, status, reviewer_scores, ai_rating, ...}
    """
    import json as _json
    import re as _re

    # Load paper metadata keyed by openreview_id
    papers: dict = {}
    with summaries_path.open() as f:
        for line in f:
            try:
                p = _json.loads(line)
            except Exception:
                continue
            oid = p.get("openreview_id")
            if not oid:
                continue
            scores_raw = p.get("reviewer_scores", "")
            scores: list = []
            if isinstance(scores_raw, str) and scores_raw:
                try:
                    scores = [float(x) for x in _json.loads(scores_raw)]
                except Exception:
                    # Fallback: extract numbers
                    scores = [float(x) for x in _re.findall(r"[0-9.]+", scores_raw)]
            elif isinstance(scores_raw, list):
                scores = [float(x) for x in scores_raw if isinstance(x, (int, float))]
            papers[oid] = {
                "decision": p.get("status"),
                "reviewer_scores": scores,
                "h1_avg_rating": (sum(scores) / len(scores)) if scores else None,
                "h1_rating_count": len(scores),
            }

    def _panel_sd(info):
        scores = info.get("reviewer_scores") or []
        if len(scores) < 2:
            return None
        return pystats.stdev(scores)

    records = []
    with matches_path.open() as f:
        for line in f:
            try:
                m = _json.loads(line)
            except Exception:
                continue
            id1, id2 = m.get("id_1"), m.get("id_2")
            if not id1 or not id2:
                continue
            flipped = bool(m.get("flipped", False))
            # Reconstruct prompt-position ordering:
            #   when flipped=True, the prompt presented id_2 first, id_1 second
            if flipped:
                paper1_id, paper2_id = id2, id1
            else:
                paper1_id, paper2_id = id1, id2
            p1 = papers.get(paper1_id) or {}
            p2 = papers.get(paper2_id) or {}
            records.append({
                "dataset_id": dataset_id,
                "created_at": None,  # not present in JSONL
                "model": (m.get("model") or "unknown").lower(),
                "paper1_id": paper1_id,
                "paper2_id": paper2_id,
                "winner_id": m.get("winner"),
                "flipped": flipped,
                "tier_1": p1.get("decision"),
                "tier_2": p2.get("decision"),
                "tier_rank_1": TIER_RANK.get(p1.get("decision"), None),
                "tier_rank_2": TIER_RANK.get(p2.get("decision"), None),
                "h1_avg_1": p1.get("h1_avg_rating"),
                "h1_avg_2": p2.get("h1_avg_rating"),
                "h1_n_1": p1.get("h1_rating_count", 0) or 0,
                "h1_n_2": p2.get("h1_rating_count", 0) or 0,
                "panel_sd_1": _panel_sd(p1),
                "panel_sd_2": _panel_sd(p2),
            })

    df = pd.DataFrame(records)
    if df.empty:
        return df
    df["pos1_wins"] = (df["winner_id"] == df["paper1_id"])
    df["unordered_key"] = df.apply(
        lambda r: "|".join(sorted([str(r.paper1_id), str(r.paper2_id)])), axis=1
    )
    df["score_gap"] = (df["h1_avg_1"] - df["h1_avg_2"]).abs()
    df["tier_gap"] = (df["tier_rank_1"] - df["tier_rank_2"]).abs()

    def _ai_correct(row):
        if pd.notnull(row.tier_rank_1) and pd.notnull(row.tier_rank_2) and row.tier_rank_1 != row.tier_rank_2:
            human_winner = row.paper1_id if row.tier_rank_1 < row.tier_rank_2 else row.paper2_id
            return row.winner_id == human_winner
        if (row.h1_n_1 >= 2 and row.h1_n_2 >= 2 and pd.notnull(row.h1_avg_1)
                and pd.notnull(row.h1_avg_2) and abs(row.h1_avg_1 - row.h1_avg_2) >= 0.5):
            human_winner = row.paper1_id if row.h1_avg_1 > row.h1_avg_2 else row.paper2_id
            return row.winner_id == human_winner
        return None
    df["ai_correct"] = df.apply(_ai_correct, axis=1)
    return df



def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return ((center - half) * 100, (center + half) * 100)


def two_prop_z(p1_succ: int, n1: int, p2_succ: int, n2: int) -> tuple[float, float]:
    """Two-proportion z-test. Returns (z, p-value)."""
    if n1 == 0 or n2 == 0:
        return (float("nan"), float("nan"))
    p1 = p1_succ / n1
    p2 = p2_succ / n2
    pp = (p1_succ + p2_succ) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    if se == 0:
        return (float("nan"), float("nan"))
    z = (p1 - p2) / se
    p_val = 2 * (1 - sp.norm.cdf(abs(z)))
    return (z, p_val)


async def load_dataset(db, dataset_id: str) -> pd.DataFrame:
    """Load matches + joined paper metadata into a single dataframe.

    Columns per row:
        dataset_id, created_at, model, content_mode,
        paper1_id, paper2_id, winner_id, flipped, tier_1, tier_2, tier_rank_1,
        tier_rank_2, h1_avg_1, h1_avg_2, h1_n_1, h1_n_2, panel_sd_1, panel_sd_2,
        pos1_wins, unordered_key
    """
    # Pull matches
    match_fields = {
        "_id": 0, "created_at": 1, "model_used": 1, "content_mode": 1,
        "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "flipped": 1,
    }
    cursor = db.matches.find(
        {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True}},
        match_fields,
    )
    rows = await cursor.to_list(length=None)
    if not rows:
        return pd.DataFrame()

    # Collect paper IDs, pull paper metadata once
    pids: set = set()
    for r in rows:
        pids.add(r["paper1_id"])
        pids.add(r["paper2_id"])
    paper_fields = {
        "_id": 0, "id": 1, "decision": 1,
        "h1_avg_rating": 1, "h1_rating_count": 1, "reviewer_scores": 1,
    }
    papers_cursor = db.papers.find({"id": {"$in": list(pids)}}, paper_fields)
    papers = {p["id"]: p async for p in papers_cursor}

    def _panel_sd(p):
        scores = p.get("reviewer_scores") or []
        scores = [float(s) for s in scores if isinstance(s, (int, float))]
        if len(scores) < 2:
            return None
        return pystats.stdev(scores)

    records = []
    for r in rows:
        p1 = papers.get(r["paper1_id"]) or {}
        p2 = papers.get(r["paper2_id"]) or {}
        tier1 = p1.get("decision")
        tier2 = p2.get("decision")
        mu = r.get("model_used") or {}
        model_key = (mu.get("model") or "unknown").lower()
        records.append({
            "dataset_id": dataset_id,
            "created_at": r.get("created_at"),
            "model": model_key,
            "paper1_id": r["paper1_id"],
            "paper2_id": r["paper2_id"],
            "winner_id": r.get("winner_id"),
            "flipped": bool(r.get("flipped", False)),
            "tier_1": tier1,
            "tier_2": tier2,
            "tier_rank_1": TIER_RANK.get(tier1, None),
            "tier_rank_2": TIER_RANK.get(tier2, None),
            "h1_avg_1": p1.get("h1_avg_rating"),
            "h1_avg_2": p2.get("h1_avg_rating"),
            "h1_n_1": p1.get("h1_rating_count", 0) or 0,
            "h1_n_2": p2.get("h1_rating_count", 0) or 0,
            "panel_sd_1": _panel_sd(p1),
            "panel_sd_2": _panel_sd(p2),
        })

    df = pd.DataFrame(records)
    if df.empty:
        return df
    df["pos1_wins"] = (df["winner_id"] == df["paper1_id"])
    # Unordered pair key for detecting duplicate orderings
    df["unordered_key"] = df.apply(
        lambda r: "|".join(sorted([str(r.paper1_id), str(r.paper2_id)])), axis=1
    )
    # score_gap (absolute, when both sides have scores)
    df["score_gap"] = (df["h1_avg_1"] - df["h1_avg_2"]).abs()
    # tier_gap — only when both tiers known
    df["tier_gap"] = (df["tier_rank_1"] - df["tier_rank_2"]).abs()
    # ai_correct (only on pairs with clear human signal)
    def _ai_correct(row):
        # Preferred signal: tier diff
        if pd.notnull(row.tier_rank_1) and pd.notnull(row.tier_rank_2) and row.tier_rank_1 != row.tier_rank_2:
            human_winner = row.paper1_id if row.tier_rank_1 < row.tier_rank_2 else row.paper2_id
            return row.winner_id == human_winner
        # Secondary: reviewer mean with panel ≥ 2 and gap ≥ 0.5
        if (row.h1_n_1 >= 2 and row.h1_n_2 >= 2 and pd.notnull(row.h1_avg_1)
                and pd.notnull(row.h1_avg_2) and abs(row.h1_avg_1 - row.h1_avg_2) >= 0.5):
            human_winner = row.paper1_id if row.h1_avg_1 > row.h1_avg_2 else row.paper2_id
            return row.winner_id == human_winner
        return None
    df["ai_correct"] = df.apply(_ai_correct, axis=1)
    return df


def test1_pc_by_gap_decile(df: pd.DataFrame, gap_col: str, lines: list):
    """Test 1: PC or accuracy-asymmetry by gap decile, per model."""
    lines.append(f"### By `{gap_col}`\n")

    # Detect whether we have dual-ordering coverage
    per_pair_model = df.groupby(["model", "unordered_key"])
    dual_cov = per_pair_model.filter(lambda g: g["flipped"].nunique() == 2 and len(g) >= 2)
    dual_frac = len(dual_cov) / len(df) if len(df) else 0
    lines.append(f"_Dual-ordering coverage: {dual_frac*100:.1f}% of rows_\n")

    if dual_frac > 0.10:
        # ── Native PC ──
        lines.append("**Native PC (fraction of pairs where both orderings agreed):**\n")
        agg = (dual_cov.groupby(["model", "unordered_key"])
               .agg(winners=("winner_id", lambda s: s.nunique() == 1),
                    gap=(gap_col, "mean"))
               .reset_index())
        agg = agg.dropna(subset=["gap"])
        if agg.empty:
            lines.append("_(insufficient ground truth for this gap metric)_\n")
            return
        for model, sub in agg.groupby("model"):
            if len(sub) < 30:
                continue
            sub = sub.copy()
            sub["decile"] = pd.qcut(sub["gap"], 10, labels=False, duplicates="drop")
            rows = []
            for d, ss in sub.groupby("decile"):
                pc = ss["winners"].mean()
                lo, hi = wilson_ci(int(ss["winners"].sum()), len(ss))
                rows.append((int(d), ss["gap"].mean(), pc * 100, lo, hi, len(ss)))
            rho, pval = sp.spearmanr([r[0] for r in rows], [r[2] for r in rows])
            lines.append(f"\n**{model}** — Spearman ρ = {rho:+.3f}, p = {pval:.3g}  _(n={len(sub)} pairs)_\n")
            lines.append("| Decile | Gap (mean) | PC %  | 95% CI       | n   |")
            lines.append("|--------|-----------|-------|--------------|-----|")
            for d, g, pc, lo, hi, n in rows:
                lines.append(f"| {d}      | {g:9.3f} | {pc:5.1f} | [{lo:5.1f}, {hi:5.1f}] | {n:3} |")
    else:
        # ── Accuracy-asymmetry fallback ──
        lines.append(
            "**Accuracy-asymmetry fallback** (dual orderings scarce).\n"
            "Measures: for pairs with clear human winner, is AI accuracy higher "
            "when human winner is in pos1 vs pos2? Gap = **2 × positional bias** in %.\n"
        )
        subdf = df.dropna(subset=[gap_col, "ai_correct"]).copy()
        if subdf.empty:
            lines.append("_(no usable rows for this gap metric)_\n")
            return
        # Determine which position held the human winner
        def _human_in_pos1(r):
            if gap_col == "tier_gap":
                if pd.isnull(r.tier_rank_1) or pd.isnull(r.tier_rank_2):
                    return None
                return r.tier_rank_1 < r.tier_rank_2
            if gap_col == "score_gap":
                if pd.isnull(r.h1_avg_1) or pd.isnull(r.h1_avg_2):
                    return None
                return r.h1_avg_1 > r.h1_avg_2
            return None
        subdf["human_in_pos1"] = subdf.apply(_human_in_pos1, axis=1)
        subdf = subdf.dropna(subset=["human_in_pos1"])
        subdf["human_in_pos1"] = subdf["human_in_pos1"].astype(bool)
        if subdf.empty:
            lines.append("_(no usable rows)_\n")
            return
        try:
            subdf["decile"] = pd.qcut(subdf[gap_col], 10, labels=False, duplicates="drop")
        except Exception:
            lines.append("_(could not form 10 gap bins — too few unique values)_\n")
            return

        for model, sub in subdf.groupby("model"):
            if len(sub) < 100:
                continue
            rows = []
            for d, ss in sub.groupby("decile"):
                pos1_hum = ss[ss["human_in_pos1"]]
                pos2_hum = ss[~ss["human_in_pos1"]]
                if len(pos1_hum) < 10 or len(pos2_hum) < 10:
                    continue
                acc_pos1 = pos1_hum["ai_correct"].mean() * 100
                acc_pos2 = pos2_hum["ai_correct"].mean() * 100
                asymm = acc_pos1 - acc_pos2
                z, pval = two_prop_z(int(pos1_hum["ai_correct"].sum()), len(pos1_hum),
                                     int(pos2_hum["ai_correct"].sum()), len(pos2_hum))
                rows.append((int(d), ss[gap_col].mean(), acc_pos1, acc_pos2, asymm, z, pval, len(ss)))
            if not rows:
                continue
            # Correlation of asymmetry magnitude vs gap (positive ρ would mean
            # bias SHRINKS with larger gap — literature prediction)
            rho, pspear = sp.spearmanr([r[0] for r in rows], [abs(r[4]) for r in rows])
            lines.append(f"\n**{model}** — Spearman ρ(decile, |asymmetry|) = {rho:+.3f}, p = {pspear:.3g}")
            lines.append("| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |")
            lines.append("|--------|-----|------------------|------------------|---------|----|----|")
            for d, g, a1, a2, asy, z, pv, _n in rows:
                lines.append(f"| {d}      | {g:5.3f} | {a1:5.1f}% | {a2:5.1f}% | {asy:+5.1f} | {z:+5.2f} | {pv:.3g} |")
    lines.append("")


def test2_inconsistency_direction(df: pd.DataFrame, lines: list):
    lines.append("## Test 2 — Inconsistency direction (primacy vs recency)\n")
    per_pair_model = df.groupby(["model", "unordered_key"])
    dual = per_pair_model.filter(lambda g: g["flipped"].nunique() == 2 and len(g) >= 2)
    if len(dual) < 50:
        lines.append(
            f"⚠️  **Only {len(dual)} dual-ordering rows available** — this test requires each pair "
            "to be judged by the SAME model in BOTH prompt orders. The validation pipeline judges each pair once per model, "
            "so this test cannot be run on the current dataset.\n\n"
            "**To enable:** rerun a sample (e.g., 500 pairs) a second time per model with random-flip. "
            "This is the controlled-AB-test pattern we used on live traffic.\n"
        )
        return

    # For each (model, unordered_key) with dual orderings, classify
    rows = []
    for (model, _), g in per_pair_model:
        if g["flipped"].nunique() < 2 or len(g) < 2:
            continue
        # Pick one ordering per flipped value (if multiple, take first)
        rec = {"model": model}
        for flipped_val, gg in g.groupby("flipped"):
            w = gg.iloc[0]["winner_id"]
            p1 = gg.iloc[0]["paper1_id"]
            pos1_wins = (w == p1)
            rec["ab" if not flipped_val else "ba"] = {"pos1_wins": pos1_wins, "winner": w}
        if "ab" in rec and "ba" in rec:
            consistent = rec["ab"]["winner"] == rec["ba"]["winner"]
            ab_p1 = rec["ab"]["pos1_wins"]
            ba_p1 = rec["ba"]["pos1_wins"]
            if not consistent:
                if ab_p1 and ba_p1:
                    direction = "primacy"
                elif (not ab_p1) and (not ba_p1):
                    direction = "recency"
                else:
                    direction = "random"
            else:
                direction = "consistent"
            rows.append((model, direction))

    ddf = pd.DataFrame(rows, columns=["model", "direction"])
    lines.append("| Model | Consistent | Primacy | Recency | Random | Total | Binomial p (primacy vs recency) |")
    lines.append("|-------|-----------:|--------:|--------:|-------:|------:|:--------------------------------|")
    for model, sub in ddf.groupby("model"):
        cc = (sub["direction"] == "consistent").sum()
        pr = (sub["direction"] == "primacy").sum()
        rc = (sub["direction"] == "recency").sum()
        rn = (sub["direction"] == "random").sum()
        n = len(sub)
        bp = sp.binomtest(pr, pr + rc, 0.5).pvalue if (pr + rc) > 0 else float("nan")
        lines.append(f"| {model} | {cc} | {pr} | {rc} | {rn} | {n} | {bp:.3g} |")
    lines.append("")


def test4_within_vs_cross(df_val: pd.DataFrame, df_wl: pd.DataFrame, lines: list):
    lines.append("## Test 4 — Within-label vs cross-label agreement\n")
    if df_val.empty or df_wl.empty:
        lines.append("_(one of the two datasets is missing or empty)_\n")
        return
    lines.append("Per-model `ai_correct` rate on pairs with clear human signal:\n")
    lines.append("| Model | Cross-label acc (n) | Within-label acc (n) | Δ (pp) | z | p |")
    lines.append("|-------|--------------------|----------------------|--------|----|----|")
    models = sorted(set(df_val["model"]) | set(df_wl["model"]))
    for m in models:
        sv = df_val[(df_val["model"] == m) & (df_val["ai_correct"].notnull())]
        sw = df_wl[(df_wl["model"] == m) & (df_wl["ai_correct"].notnull())]
        if len(sv) < 30 or len(sw) < 30:
            continue
        av = sv["ai_correct"].mean() * 100
        aw = sw["ai_correct"].mean() * 100
        z, p = two_prop_z(int(sv["ai_correct"].sum()), len(sv),
                          int(sw["ai_correct"].sum()), len(sw))
        lines.append(f"| {m} | {av:5.1f}% ({len(sv)}) | {aw:5.1f}% ({len(sw)}) | {av - aw:+5.1f} | {z:+5.2f} | {p:.3g} |")
    lines.append("")
    lines.append(
        "_Expected pattern: accuracy is lower on within-label pairs (same tier ⇒ harder). "
        "A larger drop for one model = more gap-sensitive judge. This parallels the "
        "Shi et al. 2025 'quality gap dominates position consistency' finding._\n"
    )


def test10_temporal_drift(df: pd.DataFrame, lines: list, dataset_name: str):
    lines.append(f"## Test 10 — Temporal drift within `{dataset_name}`\n")
    sub = df.dropna(subset=["created_at"]).copy()
    if sub.empty:
        lines.append("_(no created_at info)_\n")
        return
    sub = sub.sort_values("created_at").reset_index(drop=True)
    sub["pos1_wins_int"] = sub["pos1_wins"].astype(int)

    # Bucket into 10 equal-size time segments per model; test linear trend
    lines.append(
        "For each model we bucket matches by created_at into 10 equal-size chunks "
        "and compute pos1-rate per chunk. A systematic trend suggests the proxy "
        "serving GPT-5.x degraded under sustained load during the run.\n"
    )
    lines.append("| Model | Rows | Pos1 Q1 → Q10 | slope (pp / chunk) | z |")
    lines.append("|-------|-----:|---------------|-------------------:|---:|")
    for m, g in sub.groupby("model"):
        if len(g) < 200:
            continue
        g = g.reset_index(drop=True)
        n = len(g)
        # 10 equal-size buckets
        g["bucket"] = np.minimum(np.arange(n) * 10 // n, 9)
        per = g.groupby("bucket")["pos1_wins_int"].agg(["sum", "count"])
        per["rate"] = per["sum"] / per["count"]
        if len(per) < 3:
            continue
        xs = per.index.to_numpy(dtype=float)
        ys = per["rate"].to_numpy() * 100
        slope, intercept, rvalue, pvalue, se = sp.linregress(xs, ys)
        z = slope / se if se > 0 else float("nan")
        trace = " → ".join(f"{v:4.1f}" for v in ys[:10])
        lines.append(f"| {m} | {n} | {trace} | {slope:+.2f} | {z:+.2f} |")
    lines.append("")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/app/memory/ICLR_POSITION_BIAS_REPORT.md")
    ap.add_argument("--mongo-url", default=os.environ.get("MONGO_URL"))
    ap.add_argument("--db-name", default=os.environ.get("DB_NAME"))
    ap.add_argument("--jsonl-dir", default=None,
                    help="If given, load from JSONL files in this dir instead of MongoDB. "
                         "Expects validation_match_results.jsonl, within_label_match_results.jsonl, "
                         "and iclr_2026_summaries.jsonl.")
    args = ap.parse_args()

    use_jsonl = bool(args.jsonl_dir)

    if not use_jsonl and (not args.mongo_url or not args.db_name):
        print("Missing MONGO_URL or DB_NAME (or pass --jsonl-dir).", file=sys.stderr)
        sys.exit(2)

    lines: list = []
    lines.append("# ICLR 2026 Positional-Bias Analysis\n")
    if use_jsonl:
        lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()} — source: JSONL `{args.jsonl_dir}`_\n")
    else:
        lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()} — DB: `{args.db_name}`_\n")

    lines.append("## Dataset summary\n")
    if use_jsonl:
        base = Path(args.jsonl_dir)
        sums = base / "iclr_2026_summaries.jsonl"
        df_val = load_dataset_from_jsonl(
            base / "validation_match_results.jsonl", sums, VALIDATION_DS,
        )
        df_wl = load_dataset_from_jsonl(
            base / "within_label_match_results.jsonl", sums, WITHIN_LABEL_DS,
        )
        client = None
    else:
        client = AsyncIOMotorClient(args.mongo_url)
        db = client[args.db_name]
        df_val = await load_dataset(db, VALIDATION_DS)
        df_wl = await load_dataset(db, WITHIN_LABEL_DS)

    lines.append(f"- **{VALIDATION_DS}**: {len(df_val):,} completed matches")
    if not df_val.empty:
        lines.append(f"  - models: {df_val['model'].value_counts().to_dict()}")
        lines.append(f"  - pairs with tier ground-truth: {int(df_val['ai_correct'].notnull().sum()):,}")
    lines.append(f"- **{WITHIN_LABEL_DS}**: {len(df_wl):,} completed matches")
    if not df_wl.empty:
        lines.append(f"  - models: {df_wl['model'].value_counts().to_dict()}")
        lines.append(f"  - pairs with tier ground-truth: {int(df_wl['ai_correct'].notnull().sum()):,}")
    lines.append("")

    if df_val.empty and df_wl.empty:
        lines.append("⚠️  **No matches found in either dataset. Check MONGO_URL / DB_NAME.**\n")
    else:
        # Use the larger dataset for T1 + T10
        df_primary = df_val if len(df_val) >= len(df_wl) else df_wl
        ds_primary_name = VALIDATION_DS if len(df_val) >= len(df_wl) else WITHIN_LABEL_DS

        lines.append(f"## Test 1 — Position Consistency / Accuracy-asymmetry by gap decile  _(dataset: `{ds_primary_name}`)_\n")
        for col, label in [("score_gap", "|Δ reviewer mean|"),
                           ("tier_gap", "|Δ decision tier|")]:
            test1_pc_by_gap_decile(df_primary, col, lines)

        # Test 2 — dual-ordering only
        test2_inconsistency_direction(df_primary, lines)

        # Test 4 — two-dataset
        test4_within_vs_cross(df_val, df_wl, lines)

        # Test 10 — temporal
        test10_temporal_drift(df_primary, lines, ds_primary_name)

        # Also run Test 10 on the other dataset for completeness
        other = df_wl if ds_primary_name == VALIDATION_DS else df_val
        other_name = WITHIN_LABEL_DS if ds_primary_name == VALIDATION_DS else VALIDATION_DS
        if not other.empty:
            test10_temporal_drift(other, lines, other_name)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"Wrote report: {out_path}")
    print(f"  {len(lines)} lines, {sum(len(ln) for ln in lines)/1024:.1f} KB")
    if client is not None:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
