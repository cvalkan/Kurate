"""Unified model analysis endpoint.

Merges model-correlation, scoring-method-correlation, and si-rating-stats
into a single computation. Loads matches ONCE, computes OpenSkill ONCE,
shares across all tables. Cached as one document per category.
"""
import numpy as np
import time
from scipy import stats as scipy_stats
from collections import Counter, defaultdict
from typing import Optional

from core.config import db, logger


_OPUS_MERGE = {
    "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
    "anthropic/claude-opus-4-6": "anthropic/claude-opus",
}
_SHORT_NAMES = {
    "anthropic/claude-opus": "Claude Opus",
    "gemini/gemini-3-pro-preview": "Gemini 3 Pro",
    "openai/gpt-5.2": "GPT-5.2",
}
_MODEL_KEY_MAP = {
    "claude": "anthropic/claude-opus",
    "gpt": "openai/gpt-5.2",
    "gemini": "gemini/gemini-3-pro-preview",
}
MIN_MATCHES = 5


def _short(mk):
    return _SHORT_NAMES.get(mk, mk.split("/")[-1])


def _corr_row(method, label, scores_dict, si_dict):
    """Compute Spearman ρ and Kendall τ between PW scores and SI scores."""
    common = sorted(set(scores_dict.keys()) & set(si_dict.keys()))
    if len(common) < 10:
        return None
    v1 = [scores_dict[p] for p in common]
    v2 = [si_dict[p] for p in common]
    rho, _ = scipy_stats.spearmanr(v1, v2)
    tau, _ = scipy_stats.kendalltau(v1, v2)
    if np.isnan(rho):
        return None
    return {"method": method, "label": label,
            "spearman_rho": round(float(rho), 3), "kendall_tau": round(float(tau), 3),
            "n": len(common)}


async def compute_model_analysis(category: Optional[str] = None):
    """Single computation for all model analysis tables.

    1. Load rankings (WR, TS, model_stats, model_ts, si_ratings) — O(P)
    2. Load matches per-category for OpenSkill — O(M) total, bounded per category
    3. Compute all tables from shared data
    """
    from services.ranking import compute_openskill_tm_scores_async as compute_os
    from core.memlog import force_gc
    t_start = time.perf_counter()

    # ========== PHASE 1: Load rankings ==========
    query = {"category": category} if category else {}
    papers = []
    async for doc in db.rankings.find(query, {
        "_id": 0, "paper_id": 1, "title": 1, "category": 1,
        "score": 1, "ts_score": 1, "comparisons": 1,
        "model_stats": 1, "model_ts": 1, "si_ratings": 1,
    }):
        papers.append(doc)

    if len(papers) < 10:
        return {"status": "insufficient_data", "n_papers": len(papers)}

    paper_by_id = {p["paper_id"]: p for p in papers}
    paper_categories = {p["paper_id"]: p.get("category") for p in papers}

    # Extract per-model stats
    model_paper_stats = {}
    model_paper_ts = {}
    for p in papers:
        ms = p.get("model_stats")
        if ms and isinstance(ms, dict):
            for mk, stats in ms.items():
                if isinstance(stats, dict):
                    model_paper_stats.setdefault(mk, {})[p["paper_id"]] = stats
        mts = p.get("model_ts")
        if mts and isinstance(mts, dict):
            for mk, ts_data in mts.items():
                if isinstance(ts_data, dict) and ts_data.get("mu"):
                    model_paper_ts.setdefault(mk, {})[p["paper_id"]] = ts_data["mu"]

    model_keys = sorted(mk for mk in model_paper_stats
                        if sum(s.get("total", 0) for s in model_paper_stats[mk].values()) > 0)

    # Per-model win rates
    model_wr = {}
    for mk in model_keys:
        model_wr[mk] = {}
        for pid, s in model_paper_stats[mk].items():
            if s.get("total", 0) >= MIN_MATCHES:
                model_wr[mk][pid] = (s.get("wins", 0) + 0.5) / (s.get("total", 0) + 1.0)

    # Global WR/TS scores
    wr_scores = {p["paper_id"]: p["score"] for p in papers if p.get("score") is not None}
    ts_scores = {p["paper_id"]: p["ts_score"] for p in papers if p.get("ts_score") is not None}

    # ========== PHASE 2: Load matches & compute OpenSkill ==========
    cats = [category] if category else list(set(paper_categories.values()))
    cats = [c for c in cats if c]

    # Per-model matches (for inter-model and per-model-only tables)
    per_model_matches = {}
    # Global matches (for combined tables)
    all_matches = []

    for cat in cats:
        cat_q = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False},
                 "primary_category": cat}
        async for m in db.matches.find(cat_q, {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}):
            all_matches.append(m)
            mu = m.get("model_used", {})
            raw_key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
            mk = _OPUS_MERGE.get(raw_key, raw_key)
            per_model_matches.setdefault(mk, []).append(m)
        if not category:
            force_gc()

    # Strip model_used from all_matches to save memory (not needed for global OS)
    all_matches_slim = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"], "winner_id": m["winner_id"]}
                        for m in all_matches if m.get("winner_id")]

    all_pids = list(wr_scores.keys())

    # Global OpenSkill (shared by scoring-method + combined PW vs SI)
    os1_global = await compute_os(all_matches_slim, all_pids, passes=1)
    os3_global = await compute_os(all_matches_slim, all_pids, passes=3)
    os10_global = await compute_os(all_matches_slim, all_pids, passes=10)
    del all_matches_slim
    force_gc()

    # Per-model OpenSkill (shared by inter-model + per-model PW vs SI)
    model_os = {}  # {mk: {"os1": {}, "os3": {}, "os10": {}}}
    for mk in model_keys:
        mk_matches = per_model_matches.get(mk, [])
        if not mk_matches:
            continue
        mk_pids = [pid for pid, s in model_paper_stats[mk].items() if s.get("total", 0) >= MIN_MATCHES]
        if len(mk_pids) < 20:
            continue
        model_os[mk] = {
            "os1": await compute_os(mk_matches, mk_pids, passes=1),
            "os3": await compute_os(mk_matches, mk_pids, passes=3),
            "os10": await compute_os(mk_matches, mk_pids, passes=10),
        }
        per_model_matches.pop(mk, None)
        force_gc()

    del per_model_matches, all_matches
    force_gc()

    # ========== PHASE 3: Compute all tables ==========

    # --- 3a: Model summaries ---
    model_summaries = []
    for mk in model_keys:
        total = sum(s.get("total", 0) for s in model_paper_stats[mk].values())
        model_summaries.append({
            "key": mk, "label": _short(mk), "short": _short(mk),
            "total_matches": total, "papers_judged": len(model_paper_stats[mk]),
        })

    # --- 3b: PW Inter-Model (by scoring method) ---
    method_order = ["reg_wr", "trueskill", "openskill", "openskill3", "openskill10"]
    method_labels = {"reg_wr": "Reg WR", "trueskill": "TrueSkill",
                     "openskill": "OpenSkill 1p", "openskill3": "OpenSkill 3p", "openskill10": "OpenSkill 10p"}

    # Build per-model rankings dict (shared by inter-model + avg computation)
    model_rankings = {}
    model_avg_mpp = {}
    for mk in model_keys:
        mk_pids = [pid for pid, s in model_paper_stats[mk].items() if s.get("total", 0) >= MIN_MATCHES]
        if len(mk_pids) < 20:
            continue
        model_rankings[mk] = {
            "reg_wr": {pid: model_wr[mk][pid] for pid in mk_pids if pid in model_wr[mk]},
            "trueskill": model_paper_ts.get(mk, {}),
        }
        if mk in model_os:
            model_rankings[mk]["openskill"] = model_os[mk]["os1"]
            model_rankings[mk]["openskill3"] = model_os[mk]["os3"]
            model_rankings[mk]["openskill10"] = model_os[mk]["os10"]
        mpps = [model_paper_stats[mk][pid].get("total", 0) for pid in mk_pids]
        model_avg_mpp[mk] = round(float(np.mean(mpps)), 1) if mpps else 0

    pw_inter_model = []
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j or m1 not in model_rankings or m2 not in model_rankings:
                continue
            avg_mpp = round((model_avg_mpp.get(m1, 0) + model_avg_mpp.get(m2, 0)) / 2, 1)
            row = {"pair": f"{_short(m1)} vs {_short(m2)}", "methods": {}}
            for method in method_order:
                r1 = model_rankings[m1].get(method, {})
                r2 = model_rankings[m2].get(method, {})
                common = sorted(set(r1.keys()) & set(r2.keys()))
                if len(common) >= 10:
                    v1 = [r1[p] for p in common]
                    v2 = [r2[p] for p in common]
                    rho, _ = scipy_stats.spearmanr(v1, v2)
                    row["methods"][method] = {"rho": round(float(rho), 3), "n": len(common), "avg_mpp": avg_mpp}
            if row["methods"]:
                pw_inter_model.append(row)

    # --- 3c: Scoring Method Agreement ---
    shared_pids = sorted(set(wr_scores.keys()) & set(ts_scores.keys()))
    scoring_methods = {"win_rate": wr_scores, "trueskill": ts_scores}
    scoring_labels = {"win_rate": "Normalized Win-Rate", "trueskill": "TrueSkill"}
    scoring_keys = ["win_rate", "trueskill"]
    for key, scores, label in [("openskill", os1_global, "OpenSkill 1p"),
                                ("openskill3", os3_global, "OpenSkill 3p"),
                                ("openskill10", os10_global, "OpenSkill 10p")]:
        if scores:
            scoring_methods[key] = scores
            scoring_labels[key] = label
            scoring_keys.append(key)

    scoring_correlations = []
    for i in range(len(scoring_keys)):
        for j in range(i + 1, len(scoring_keys)):
            m1, m2 = scoring_keys[i], scoring_keys[j]
            v1 = [scoring_methods[m1].get(p, 0) for p in shared_pids if p in scoring_methods[m1] and p in scoring_methods[m2]]
            v2 = [scoring_methods[m2].get(p, 0) for p in shared_pids if p in scoring_methods[m1] and p in scoring_methods[m2]]
            if len(v1) >= 10:
                sp_r, _ = scipy_stats.spearmanr(v1, v2)
                kt_r, _ = scipy_stats.kendalltau(v1, v2)
                scoring_correlations.append({
                    "method1": m1, "method2": m2,
                    "label": f"{scoring_labels[m1]} vs {scoring_labels[m2]}",
                    "spearman_rho": round(float(sp_r), 6),
                    "kendall_tau": round(float(kt_r), 6),
                })

    # --- 3d: WR/TS pairwise correlations + agreement (existing tables) ---
    correlations = {}
    ts_correlations = {}
    agreement = {}
    scatter_data = {}
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j:
                continue
            pair = f"{m1} vs {m2}"
            pp = sorted(set(model_wr.get(m1, {}).keys()) & set(model_wr.get(m2, {}).keys()))
            if len(pp) >= 5:
                r1 = [model_wr[m1][p] for p in pp]
                r2 = [model_wr[m2][p] for p in pp]
                sp, sp_p = scipy_stats.spearmanr(r1, r2)
                pe, pe_p = scipy_stats.pearsonr(r1, r2)
                correlations[pair] = {"spearman_r": round(float(sp), 3), "pearson_r": round(float(pe), 3),
                                      "spearman_p": round(float(sp_p), 4), "pearson_p": round(float(pe_p), 4),
                                      "n_papers": len(pp)}
                med1, med2 = np.median(r1), np.median(r2)
                agree = sum(1 for p in pp if (model_wr[m1][p] >= med1) == (model_wr[m2][p] >= med2))
                agreement[pair] = {"agree": agree, "disagree": len(pp) - agree, "total": len(pp),
                                   "rate": round(agree / len(pp) * 100, 1)}
                scatter_data[pair] = {
                    "x": [round(model_wr[m1][p] * 100, 1) for p in pp],
                    "y": [round(model_wr[m2][p] * 100, 1) for p in pp], "n": len(pp)}

            ts1, ts2 = model_paper_ts.get(m1, {}), model_paper_ts.get(m2, {})
            pp_ts = sorted(set(ts1.keys()) & set(ts2.keys()))
            if len(pp_ts) >= 5:
                v1, v2 = [ts1[p] for p in pp_ts], [ts2[p] for p in pp_ts]
                sp, _ = scipy_stats.spearmanr(v1, v2)
                pe, _ = scipy_stats.pearsonr(v1, v2)
                ts_correlations[pair] = {"spearman_r": round(float(sp), 3), "pearson_r": round(float(pe), 3),
                                         "n_papers": len(pp_ts)}

    common_papers = set(wr_scores.keys())
    for mk in model_keys:
        common_papers &= set(model_wr.get(mk, {}).keys())

    # --- 3e: SI Rating Stats ---
    si_result = _compute_si_stats(papers)

    # --- 3f: PW vs SI ---
    pw_vs_si = _compute_pw_vs_si(
        papers, wr_scores, ts_scores, os1_global, os3_global, os10_global,
        model_rankings, model_os, model_paper_stats, model_avg_mpp,
        category, paper_categories,
    )

    # --- 3g: Per-category averages (for "All Categories" view) ---
    avg_correlations = {}
    avg_ts_correlations = {}
    avg_agreement = {}
    if not category and paper_categories:
        cats_in_data = set(c for c in paper_categories.values() if c)
        for cat in cats_in_data:
            cat_pids = {pid for pid, c in paper_categories.items() if c == cat}
            for i, m1 in enumerate(model_keys):
                for j, m2 in enumerate(model_keys):
                    if i >= j:
                        continue
                    pair = f"{m1} vs {m2}"
                    common = sorted(set(model_wr.get(m1, {}).keys()) & set(model_wr.get(m2, {}).keys()) & cat_pids)
                    if len(common) >= 10:
                        v1 = [model_wr[m1][p] for p in common]
                        v2 = [model_wr[m2][p] for p in common]
                        rho, _ = scipy_stats.spearmanr(v1, v2)
                        if not np.isnan(rho):
                            avg_correlations.setdefault(pair, []).append((float(rho), len(common)))
                    ts1, ts2 = model_paper_ts.get(m1, {}), model_paper_ts.get(m2, {})
                    common_ts = sorted(set(ts1.keys()) & set(ts2.keys()) & cat_pids)
                    if len(common_ts) >= 10:
                        v1 = [ts1[p] for p in common_ts]
                        v2 = [ts2[p] for p in common_ts]
                        rho, _ = scipy_stats.spearmanr(v1, v2)
                        if not np.isnan(rho):
                            avg_ts_correlations.setdefault(pair, []).append((float(rho), len(common_ts)))
        # Weighted averages
        for key in list(avg_correlations.keys()):
            data = avg_correlations[key]
            w = [n for _, n in data]
            avg_correlations[key] = {"spearman_r": round(float(np.average([r for r, _ in data], weights=w)), 3),
                                     "n_papers": sum(w), "n_categories": len(data)}
        for key in list(avg_ts_correlations.keys()):
            data = avg_ts_correlations[key]
            w = [n for _, n in data]
            avg_ts_correlations[key] = {"spearman_r": round(float(np.average([r for r, _ in data], weights=w)), 3),
                                        "n_papers": sum(w), "n_categories": len(data)}

    total_matches = sum(sum(s.get("total", 0) for s in model_paper_stats[mk].values()) for mk in model_keys) // 2
    t_compute = time.perf_counter() - t_start

    return {
        "status": "ok",
        # Model summaries
        "models": model_summaries,
        "method_labels": method_labels,
        "n_common_papers": len(common_papers),
        "total_matches": total_matches,
        "category": category,
        "compute_time_s": round(t_compute, 2),
        # Inter-model correlations
        "correlations": dict(sorted(correlations.items())),
        "ts_correlations": dict(sorted(ts_correlations.items())),
        "avg_correlations": dict(sorted(avg_correlations.items())),
        "avg_ts_correlations": dict(sorted(avg_ts_correlations.items())),
        "agreement": dict(sorted(agreement.items())),
        "scatter_data": scatter_data,
        # PW Inter-Model by scoring method
        "pw_inter_model": pw_inter_model,
        # Scoring Method Agreement
        "scoring_method": {
            "status": "ok",
            "correlations": scoring_correlations,
            "n_papers": len(shared_pids),
            "n_matches": total_matches,
            "compute_time_s": round(t_compute, 2),
        },
        # SI Rating Stats
        "si_data": si_result,
        # PW vs SI
        "pw_vs_si": pw_vs_si,
    }


def _compute_si_stats(papers):
    """Compute SI rating distributions and inter-model correlations from rankings data."""
    METRICS = ["score", "significance", "rigor", "novelty", "clarity"]
    SUB_METRICS = ["significance", "rigor", "novelty", "clarity"]

    def _get_si(p, mk=None):
        si = p.get("si_ratings", {})
        if not si:
            return None
        if mk:
            r = si.get(mk)
            return r if isinstance(r, dict) and r.get("score") else None
        ratings = [r for r in si.values() if isinstance(r, dict) and r.get("score")]
        if not ratings:
            return None
        avg = {}
        for f in METRICS:
            vals = [r[f] for r in ratings if r.get(f)]
            avg[f] = round(sum(vals) / len(vals), 1) if vals else 0
        return avg if avg.get("score") else None

    filtered = [p for p in papers if _get_si(p)]
    if len(filtered) < 5:
        return {"status": "insufficient_data", "total_papers": len(filtered)}

    for p in filtered:
        p["rating"] = _get_si(p)

    # Distributions
    arrays = {}
    for m in METRICS:
        arrays[m] = [p["rating"].get(m, 0) for p in filtered if p["rating"].get(m)]
    subscore_avgs = []
    for p in filtered:
        subs = [p["rating"].get(m) for m in SUB_METRICS if p["rating"].get(m)]
        if len(subs) >= 2:
            subscore_avgs.append(round(sum(subs) / len(subs), 2))
    arrays["subscore_avg"] = subscore_avgs

    bins = [round(1.0 + i * 0.5, 1) for i in range(19)]
    distributions = {}
    for m in METRICS + ["subscore_avg"]:
        vals = arrays.get(m, [])
        if not vals:
            continue
        hist = Counter()
        for v in vals:
            bucket = max(1.0, min(10.0, round(round(v * 2) / 2, 1)))
            hist[bucket] += 1
        distributions[m] = {
            "histogram": [{"bin": b, "count": hist.get(b, 0)} for b in bins],
            "mean": round(float(np.mean(vals)), 2),
            "median": round(float(np.median(vals)), 1),
            "std": round(float(np.std(vals, ddof=1)), 2) if len(vals) > 1 else 0,
            "n": len(vals),
        }

    # Inter-model SI correlation
    inter_model_si = {}
    model_scores = {}
    for mk in ("claude", "gpt", "gemini"):
        scores = {}
        for p in papers:
            si = p.get("si_ratings", {}).get(mk)
            if isinstance(si, dict) and si.get("score"):
                scores[p["paper_id"]] = si["score"]
        if len(scores) >= 10:
            model_scores[mk] = scores

    for i, m1 in enumerate(sorted(model_scores)):
        for j, m2 in enumerate(sorted(model_scores)):
            if j <= i:
                continue
            common = sorted(set(model_scores[m1].keys()) & set(model_scores[m2].keys()))
            if len(common) >= 10:
                v1 = [model_scores[m1][p] for p in common]
                v2 = [model_scores[m2][p] for p in common]
                rho, _ = scipy_stats.spearmanr(v1, v2)
                if not np.isnan(rho):
                    inter_model_si[f"{m1} vs {m2}"] = {"spearman": round(float(rho), 3), "n": len(common)}

    # Model comparison
    model_comparison = {}
    for mk in ("claude", "gpt", "gemini"):
        mk_ratings = [_get_si(p, mk) for p in papers if _get_si(p, mk)]
        if len(mk_ratings) < 10:
            continue
        mk_scores = [r["score"] for r in mk_ratings]
        model_comparison[mk] = {
            "n": len(mk_ratings),
            "mean": round(float(np.mean(mk_scores)), 2),
            "std": round(float(np.std(mk_scores, ddof=1)), 2) if len(mk_scores) > 1 else 0,
        }

    # Available models
    model_counts = {"claude": 0, "gpt": 0, "gemini": 0}
    for p in papers:
        si = p.get("si_ratings", {})
        for mk in ("claude", "gpt", "gemini"):
            if isinstance(si.get(mk), dict) and si[mk].get("score"):
                model_counts[mk] += 1

    return {
        "status": "ok",
        "total_papers": len(filtered),
        "distributions": distributions,
        "inter_model_si": inter_model_si,
        "model_comparison": model_comparison,
        "available_models": [{"id": mk, "count": c} for mk, c in model_counts.items() if c >= 5],
    }


def _compute_pw_vs_si(papers, wr_scores, ts_scores, os1, os3, os10,
                       model_rankings, model_os, model_paper_stats, model_avg_mpp,
                       category, paper_categories):
    """Compute PW vs SI tables (combined, controlled, per-model)."""
    pw_papers = [p for p in papers if p.get("comparisons", 0) >= 3]
    if len(pw_papers) < 20:
        return None

    # SI maps
    def _get_si_score(p, mk=None):
        si = p.get("si_ratings", {})
        if mk:
            r = si.get(mk)
            return r.get("score") if isinstance(r, dict) and r.get("score") else None
        ratings = [r for r in si.values() if isinstance(r, dict) and r.get("score")]
        if not ratings:
            return None
        return round(sum(r["score"] for r in ratings) / len(ratings), 1)

    si_maps = {}
    for mk in ("claude", "gpt", "gemini"):
        sm = {p["paper_id"]: _get_si_score(p, mk) for p in pw_papers if _get_si_score(p, mk)}
        if len(sm) >= 10:
            si_maps[mk] = sm
    avg_si = {p["paper_id"]: _get_si_score(p) for p in pw_papers if _get_si_score(p)}
    if len(avg_si) >= 10:
        si_maps["avg"] = avg_si

    if not si_maps:
        return None

    _SI_LABELS = {"claude": "Claude Opus", "gpt": "GPT-5.2", "gemini": "Gemini 3 Pro", "avg": "Average (all models)"}

    combined_pw = {
        "reg_wr": ("Reg WR", {p["paper_id"]: p["score"] for p in pw_papers if p.get("score")}),
        "trueskill": ("TrueSkill", {p["paper_id"]: p["ts_score"] for p in pw_papers if p.get("ts_score")}),
        "openskill": ("OpenSkill 1p", os1),
        "openskill3": ("OpenSkill 3p", os3),
        "openskill10": ("OpenSkill 10p", os10),
    }

    # Combined PW vs SI per model
    per_model = {}
    for si_mk, si_scores in si_maps.items():
        rows = []
        for pw_key in ["reg_wr", "trueskill", "openskill", "openskill3", "openskill10"]:
            pw_label, pw_scores = combined_pw[pw_key]
            row = _corr_row(f"combined_{pw_key}", pw_label, pw_scores, si_scores)
            if row:
                combined_mpp = round(float(np.mean([p.get("comparisons", 0) for p in pw_papers])), 1)
                row["avg_mpp"] = combined_mpp
                rows.append(row)
        per_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "rows": rows, "controlled_rows": [], "n_matches": 0}

    # Controlled PW vs SI (single random model)
    import random as _rng
    _rng.seed(42)
    mk_keys = sorted(_MODEL_KEY_MAP.values())
    sub_mk = _rng.choice(mk_keys)
    provider = sub_mk.split("/")[0]

    controlled_pw = {
        "reg_wr": ("Reg WR", {}), "trueskill": ("TrueSkill", {}),
        "openskill": ("OpenSkill 1p", {}), "openskill3": ("OpenSkill 3p", {}), "openskill10": ("OpenSkill 10p", {}),
    }
    # Controlled WR from single model's stats
    sub_wr = {}
    for p in pw_papers:
        ms = p.get("model_stats", {}).get(sub_mk)
        if isinstance(ms, dict) and ms.get("total", 0) >= MIN_MATCHES:
            sub_wr[p["paper_id"]] = (ms.get("wins", 0) + 0.5) / (ms.get("total", 0) + 1.0)
    controlled_pw["reg_wr"] = ("Reg WR", sub_wr)

    # Controlled TS from single model's TS
    sub_ts = {}
    for p in pw_papers:
        mts = p.get("model_ts", {})
        _rng.shuffle(mk_keys)
        for mk_inner in mk_keys:
            ts_data = mts.get(mk_inner)
            if isinstance(ts_data, dict) and ts_data.get("mu"):
                sub_ts[p["paper_id"]] = ts_data["mu"]
                break
    controlled_pw["trueskill"] = ("TrueSkill", sub_ts)

    # Controlled OpenSkill from model_os (already computed!)
    if sub_mk in model_os:
        controlled_pw["openskill"] = ("OpenSkill 1p", model_os[sub_mk]["os1"])
        controlled_pw["openskill3"] = ("OpenSkill 3p", model_os[sub_mk]["os3"])
        controlled_pw["openskill10"] = ("OpenSkill 10p", model_os[sub_mk]["os10"])

    within_mpp = {}
    for si_mk in si_maps:
        mk_key = _MODEL_KEY_MAP.get(si_mk)
        if mk_key:
            mpps = [model_paper_stats.get(mk_key, {}).get(p["paper_id"], {}).get("total", 0) for p in pw_papers]
            within_mpp[si_mk] = round(float(np.mean([m for m in mpps if m > 0])), 1) if any(m > 0 for m in mpps) else 0

    for si_mk, si_scores in si_maps.items():
        ctrl_rows = []
        for pw_key in ["reg_wr", "trueskill", "openskill", "openskill3", "openskill10"]:
            pw_label, pw_scores = controlled_pw[pw_key]
            row = _corr_row(f"ctrl_{pw_key}", pw_label, pw_scores, si_scores)
            if row:
                row["avg_mpp"] = within_mpp.get(si_mk, 0)
                ctrl_rows.append(row)
        if si_mk in per_model:
            per_model[si_mk]["controlled_rows"] = ctrl_rows

    # Per-model only (within-model)
    within_model = {}
    for si_mk, si_scores in si_maps.items():
        if si_mk == "avg":
            continue
        mk_key = _MODEL_KEY_MAP.get(si_mk)
        if not mk_key:
            continue
        wm_rows = []
        # Win Rate
        wm_wr = {}
        for p in pw_papers:
            ms = p.get("model_stats", {}).get(mk_key)
            if isinstance(ms, dict) and ms.get("total", 0) >= MIN_MATCHES:
                wm_wr[p["paper_id"]] = (ms.get("wins", 0) + 0.5) / (ms.get("total", 0) + 1.0)
        row = _corr_row("within_wr", "Win Rate", wm_wr, si_scores)
        if row:
            row["avg_mpp"] = within_mpp.get(si_mk, 0)
            wm_rows.append(row)
        # TrueSkill
        wm_ts = {p["paper_id"]: p.get("model_ts", {}).get(mk_key, {}).get("mu")
                 for p in pw_papers if isinstance(p.get("model_ts", {}).get(mk_key), dict) and p["model_ts"][mk_key].get("mu")}
        row = _corr_row("within_ts", "TrueSkill", wm_ts, si_scores)
        if row:
            row["avg_mpp"] = within_mpp.get(si_mk, 0)
            wm_rows.append(row)
        # OpenSkill (from pre-computed model_os)
        if mk_key in model_os:
            for os_key, os_label in [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                row = _corr_row(f"within_{os_key}", os_label, model_os[mk_key][os_key], si_scores)
                if row:
                    row["avg_mpp"] = within_mpp.get(si_mk, 0)
                    wm_rows.append(row)

        n_matches = sum(model_paper_stats.get(mk_key, {}).get(p["paper_id"], {}).get("total", 0) for p in pw_papers)
        within_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "n_matches": n_matches,
                                "avg_mpp": within_mpp.get(si_mk, 0), "rows": wm_rows}

    return {"per_model": per_model, "within_model": within_model}
