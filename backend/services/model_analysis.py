"""Unified model analysis endpoint.

Merges model-correlation, scoring-method-correlation, and si-rating-stats
into a single computation. Loads matches ONCE, computes OpenSkill ONCE,
shares across all tables. Cached as one document per category.
"""
import numpy as np
import time
from scipy import stats as scipy_stats
from collections import Counter
from typing import Optional

from core.config import db


_OPUS_MERGE = {
    "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
    "anthropic/claude-opus-4-6": "anthropic/claude-opus",
}
_SHORT_NAMES = {
    "anthropic/claude-opus": "Claude Opus",
    "gemini/gemini-3-pro-preview": "Gemini 3 Pro",
    "openai/gpt-5_2": "GPT-5.2",
}
_MODEL_KEY_MAP = {
    "claude": "anthropic/claude-opus",
    "gpt": "openai/gpt-5_2",
    "gemini": "gemini/gemini-3-pro-preview",
}
MIN_MATCHES = 5


def _short(mk):
    return _SHORT_NAMES.get(mk, mk.split("/")[-1])


def _safe_float(v, default=0.0):
    """Sanitize float for JSON — replace NaN/inf with default."""
    if v is None or np.isnan(v) or np.isinf(v):
        return default
    return float(v)


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


def _extract_model_data(papers):
    """Extract per-model stats from rankings docs.
    After the fix_dotted_model_keys migration, all keys are clean (no dots).
    Returns (model_paper_stats, model_paper_ts, model_keys, model_wr)."""
    model_paper_stats = {}
    model_paper_ts = {}
    for p in papers:
        ms = p.get("model_stats")
        if ms and isinstance(ms, dict):
            for mk, stats in ms.items():
                if isinstance(stats, dict) and stats.get("total") is not None:
                    model_paper_stats.setdefault(mk, {})[p["paper_id"]] = stats
        mts = p.get("model_ts")
        if mts and isinstance(mts, dict):
            for mk, ts_data in mts.items():
                if isinstance(ts_data, dict) and ts_data.get("mu"):
                    model_paper_ts.setdefault(mk, {})[p["paper_id"]] = ts_data["mu"]

    model_keys = sorted(mk for mk in model_paper_stats
                        if sum(s.get("total", 0) for s in model_paper_stats[mk].values()) > 0)

    model_wr = {}
    for mk in model_keys:
        model_wr[mk] = {}
        for pid, s in model_paper_stats[mk].items():
            if s.get("total", 0) >= MIN_MATCHES:
                model_wr[mk][pid] = (s.get("wins", 0) + 0.5) / (s.get("total", 0) + 1.0)

    return model_paper_stats, model_paper_ts, model_keys, model_wr


async def compute_live_analysis(category: Optional[str] = None):
    """Fast live computation from rankings only — no match loading, no OpenSkill.
    Returns all tables with WR/TS data. OpenSkill columns left empty for merge."""
    t_start = time.perf_counter()

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

    paper_categories = {p["paper_id"]: p.get("category") for p in papers}
    model_paper_stats, model_paper_ts, model_keys, model_wr = _extract_model_data(papers)

    wr_scores = {p["paper_id"]: p["score"] for p in papers if p.get("score") is not None}
    ts_scores = {p["paper_id"]: p["ts_score"] for p in papers if p.get("ts_score") is not None}

    # --- Model summaries ---
    model_summaries = []
    for mk in model_keys:
        total = sum(s.get("total", 0) for s in model_paper_stats[mk].values())
        model_summaries.append({
            "key": mk, "label": _short(mk), "short": _short(mk),
            "total_matches": total, "papers_judged": len(model_paper_stats[mk]),
        })

    # --- PW Inter-Model (WR + TS only, OS columns filled by merge) ---
    method_labels = {"reg_wr": "Reg WR", "trueskill": "TrueSkill",
                     "openskill": "OpenSkill 1p", "openskill1": "OpenSkill 1p",
                     "openskill3": "OpenSkill 3p", "openskill10": "OpenSkill 10p"}

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
        mpps = [model_paper_stats[mk][pid].get("total", 0) for pid in mk_pids]
        model_avg_mpp[mk] = round(float(np.mean(mpps)), 1) if mpps else 0

    pw_inter_model = []
    for i, m1 in enumerate(model_keys):
        for j, m2 in enumerate(model_keys):
            if i >= j or m1 not in model_rankings or m2 not in model_rankings:
                continue
            avg_mpp = round((model_avg_mpp.get(m1, 0) + model_avg_mpp.get(m2, 0)) / 2, 1)
            row = {"pair": f"{_short(m1)} vs {_short(m2)}", "methods": {}}
            for method in ["reg_wr", "trueskill"]:
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

    # --- Scoring Method (WR vs TS only) ---
    shared_pids = sorted(set(wr_scores.keys()) & set(ts_scores.keys()))
    scoring_correlations = []
    if len(shared_pids) >= 10:
        v1 = [wr_scores[p] for p in shared_pids]
        v2 = [ts_scores[p] for p in shared_pids]
        sp_r, _ = scipy_stats.spearmanr(v1, v2)
        kt_r, _ = scipy_stats.kendalltau(v1, v2)
        scoring_correlations.append({
            "method1": "win_rate", "method2": "trueskill",
            "label": "Normalized Win-Rate vs TrueSkill",
            "spearman_rho": round(float(sp_r), 6), "kendall_tau": round(float(kt_r), 6),
        })

    # --- WR/TS correlations + agreement ---
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

    # --- SI Rating Stats ---
    si_result = _compute_si_stats(papers)

    # --- PW vs SI (WR/TS only, OS empty) ---
    pw_vs_si = _compute_pw_vs_si(
        papers, wr_scores, ts_scores, {}, {}, {},
        model_rankings, {}, model_paper_stats, model_avg_mpp,
        category, paper_categories,
    )

    # --- Per-category averages ---
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
                        med1, med2 = np.median(v1), np.median(v2)
                        agree = sum(1 for p in common if (model_wr[m1][p] >= med1) == (model_wr[m2][p] >= med2))
                        avg_agreement.setdefault(pair, []).append((agree, len(common)))
                    ts1, ts2 = model_paper_ts.get(m1, {}), model_paper_ts.get(m2, {})
                    common_ts = sorted(set(ts1.keys()) & set(ts2.keys()) & cat_pids)
                    if len(common_ts) >= 10:
                        v1 = [ts1[p] for p in common_ts]
                        v2 = [ts2[p] for p in common_ts]
                        rho, _ = scipy_stats.spearmanr(v1, v2)
                        if not np.isnan(rho):
                            avg_ts_correlations.setdefault(pair, []).append((float(rho), len(common_ts)))
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
        for key in list(avg_agreement.keys()):
            data = avg_agreement[key]
            total_agree = sum(a for a, _ in data)
            total_n = sum(n for _, n in data)
            avg_agreement[key] = {"agree": total_agree, "disagree": total_n - total_agree,
                                  "total": total_n, "rate": round(total_agree / total_n * 100, 1),
                                  "n_categories": len(data)}

    # --- Per-category averaged PW-vs-SI and InterModel tables ---
    avg_pw_vs_si = None
    avg_pw_inter_model = []
    if not category and paper_categories:
        cats_in_data = set(c for c in paper_categories.values() if c)
        paper_by_cat = {}
        for p in papers:
            pc = paper_categories.get(p.get("paper_id") or p.get("id"))
            if pc:
                paper_by_cat.setdefault(pc, []).append(p)

        # --- Avg PW-vs-SI: per-category rho values, then weighted average ---
        _SI_LABELS = {"claude": "Claude Opus", "gpt": "GPT-5.2", "gemini": "Gemini 3 Pro", "avg": "Average (all models)"}
        _SI_MKS = ("claude", "gpt", "gemini")
        avg_pm_accum = {}   # {si_mk: {pw_key: [(rho, tau, n), ...]}}
        avg_wm_accum = {}   # {si_mk: {method: [(rho, tau, n), ...]}}

        def _get_si_score_avg(p, mk=None):
            si = p.get("si_ratings", {})
            if mk:
                r = si.get(mk)
                return r.get("score") if isinstance(r, dict) and r.get("score") else None
            ratings = [r for r in si.values() if isinstance(r, dict) and r.get("score")]
            return round(sum(r["score"] for r in ratings) / len(ratings), 1) if ratings else None

        for cat in cats_in_data:
            cat_papers = [p for p in paper_by_cat.get(cat, []) if p.get("comparisons", 0) >= 3]
            if len(cat_papers) < 10:
                continue

            # Build SI maps for this category
            cat_si = {}
            for mk in _SI_MKS:
                sm = {p["paper_id"]: _get_si_score_avg(p, mk) for p in cat_papers if _get_si_score_avg(p, mk)}
                if len(sm) >= 10:
                    cat_si[mk] = sm
            avg_si_cat = {p["paper_id"]: _get_si_score_avg(p) for p in cat_papers if _get_si_score_avg(p)}
            if len(avg_si_cat) >= 10:
                cat_si["avg"] = avg_si_cat

            # PW scores for this category
            cat_wr = {p["paper_id"]: p["score"] for p in cat_papers if p.get("score")}
            cat_ts = {p["paper_id"]: p["ts_score"] for p in cat_papers if p.get("ts_score")}
            cat_pw = {"reg_wr": ("Reg WR", cat_wr), "trueskill": ("TrueSkill", cat_ts)}

            # Load cached OpenSkill scores for this category
            cat_os_cache = await db.analysis_store.find_one(
                {"_type": "openskill-cache", "key": cat},
                {"_id": 0, "os_global": 1, "os_per_model": 1},
            )
            cat_os = {}
            if cat_os_cache and cat_os_cache.get("os_global"):
                osg = cat_os_cache["os_global"]
                for os_key, os_label in [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                    scores = osg.get(os_key, {})
                    if len(scores) >= 10:
                        cat_os[os_key] = (os_label, scores)

            # Combined PW vs SI (WR, TS, OS)
            for si_mk, si_scores in cat_si.items():
                for pw_key, (pw_label, pw_scores) in cat_pw.items():
                    row = _corr_row(f"combined_{pw_key}", pw_label, pw_scores, si_scores)
                    if row:
                        avg_pm_accum.setdefault(si_mk, {}).setdefault(pw_key, []).append(
                            (row["spearman_rho"], row["kendall_tau"], row["n"]))
                # OpenSkill vs SI
                for os_key, (os_label, os_scores) in cat_os.items():
                    row = _corr_row(f"combined_{os_key}", os_label, os_scores, si_scores)
                    if row:
                        avg_pm_accum.setdefault(si_mk, {}).setdefault(os_key, []).append(
                            (row["spearman_rho"], row["kendall_tau"], row["n"]))

            # Within-model PW vs SI
            for si_mk, si_scores in cat_si.items():
                if si_mk == "avg":
                    continue
                mk_key = _MODEL_KEY_MAP.get(si_mk)
                if not mk_key:
                    continue
                # Within-model WR
                wm_wr = {}
                dot_key = mk_key.replace("_", ".")
                for p in cat_papers:
                    ms_data = p.get("model_stats", {})
                    ms = ms_data.get(mk_key) or ms_data.get(dot_key)
                    if isinstance(ms, dict) and ms.get("total", 0) >= MIN_MATCHES:
                        wm_wr[p["paper_id"]] = (ms.get("wins", 0) + 0.5) / (ms.get("total", 0) + 1.0)
                row = _corr_row("within_wr", "Win Rate", wm_wr, si_scores)
                if row:
                    avg_wm_accum.setdefault(si_mk, {}).setdefault("within_wr", []).append(
                        (row["spearman_rho"], row["kendall_tau"], row["n"]))
                # Within-model TS
                wm_ts = {}
                for p in cat_papers:
                    mts = p.get("model_ts", {})
                    ts_data = mts.get(mk_key) or mts.get(dot_key)
                    if isinstance(ts_data, dict) and ts_data.get("mu"):
                        wm_ts[p["paper_id"]] = ts_data["mu"]
                row = _corr_row("within_ts", "TrueSkill", wm_ts, si_scores)
                if row:
                    avg_wm_accum.setdefault(si_mk, {}).setdefault("within_ts", []).append(
                        (row["spearman_rho"], row["kendall_tau"], row["n"]))
                # Within-model OS (from per-model OS cache for this category)
                if cat_os_cache:
                    os_per_model = cat_os_cache.get("os_per_model", {}).get(mk_key, {})
                    for os_key, os_label in [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                        os_scores = os_per_model.get(os_key, {})
                        if len(os_scores) >= 10:
                            row = _corr_row(f"within_{os_key}", os_label, os_scores, si_scores)
                            if row:
                                avg_wm_accum.setdefault(si_mk, {}).setdefault(f"within_{os_key}", []).append(
                                    (row["spearman_rho"], row["kendall_tau"], row["n"]))

        # Aggregate per-category values into weighted averages
        def _weighted_avg(entries):
            if not entries:
                return None
            weights = [n for _, _, n in entries]
            rho = round(float(np.average([r for r, _, _ in entries], weights=weights)), 3)
            tau = round(float(np.average([t for _, t, _ in entries], weights=weights)), 3)
            return {"spearman_rho": rho, "kendall_tau": tau, "n": sum(weights), "n_categories": len(entries)}

        # --- Avg Scoring Method (WR vs TS, WR vs OS, TS vs OS) per-category ---
        avg_scoring_accum = {}  # {label: [(rho, tau, n), ...]}
        for cat in cats_in_data:
            cat_papers_sm = [p for p in paper_by_cat.get(cat, []) if p.get("comparisons", 0) >= 3]
            if len(cat_papers_sm) < 10:
                continue
            cat_wr_sm = {p["paper_id"]: p["score"] for p in cat_papers_sm if p.get("score")}
            cat_ts_sm = {p["paper_id"]: p["ts_score"] for p in cat_papers_sm if p.get("ts_score")}
            # WR vs TS
            shared = sorted(set(cat_wr_sm.keys()) & set(cat_ts_sm.keys()))
            if len(shared) >= 10:
                sp_r, _ = scipy_stats.spearmanr([cat_wr_sm[p] for p in shared], [cat_ts_sm[p] for p in shared])
                kt_r, _ = scipy_stats.kendalltau([cat_wr_sm[p] for p in shared], [cat_ts_sm[p] for p in shared])
                if not np.isnan(sp_r):
                    avg_scoring_accum.setdefault("Normalized Win-Rate vs TrueSkill", []).append((float(sp_r), float(kt_r), len(shared)))
            # WR/TS vs OS (from cache)
            cat_sm_os_cache = await db.analysis_store.find_one(
                {"_type": "openskill-cache", "key": cat}, {"_id": 0, "os_global": 1})
            if cat_sm_os_cache and cat_sm_os_cache.get("os_global"):
                osg = cat_sm_os_cache["os_global"]
                for os_key, os_label in [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                    os_scores = osg.get(os_key, {})
                    for pw_name, pw_label, pw_dict in [("win_rate", "Normalized Win-Rate", cat_wr_sm), ("trueskill", "TrueSkill", cat_ts_sm)]:
                        shared_os = sorted(set(pw_dict.keys()) & set(os_scores.keys()))
                        if len(shared_os) >= 10:
                            sp_r, _ = scipy_stats.spearmanr([pw_dict[p] for p in shared_os], [os_scores[p] for p in shared_os])
                            kt_r, _ = scipy_stats.kendalltau([pw_dict[p] for p in shared_os], [os_scores[p] for p in shared_os])
                            if not np.isnan(sp_r):
                                label = f"{pw_label} vs {os_label}"
                                avg_scoring_accum.setdefault(label, []).append((float(sp_r), float(kt_r), len(shared_os)))
                    # OS vs OS
                    for os_key2, os_label2 in [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                        if os_key >= os_key2:
                            continue
                        os2 = osg.get(os_key2, {})
                        shared_os2 = sorted(set(os_scores.keys()) & set(os2.keys()))
                        if len(shared_os2) >= 10:
                            sp_r, _ = scipy_stats.spearmanr([os_scores[p] for p in shared_os2], [os2[p] for p in shared_os2])
                            kt_r, _ = scipy_stats.kendalltau([os_scores[p] for p in shared_os2], [os2[p] for p in shared_os2])
                            if not np.isnan(sp_r):
                                avg_scoring_accum.setdefault(f"{os_label} vs {os_label2}", []).append((float(sp_r), float(kt_r), len(shared_os2)))

        avg_scoring_correlations = []
        for label, entries in avg_scoring_accum.items():
            avg = _weighted_avg(entries)
            if avg:
                parts = label.split(" vs ")
                m1 = parts[0].lower().replace("normalized ", "").replace("-", "_").replace(" ", "_")
                m2 = parts[1].lower().replace(" ", "").replace("openskill", "openskill")
                avg_scoring_correlations.append({
                    "method1": m1, "method2": m2,
                    "label": label, **avg,
                })

        avg_per_model = {}
        for si_mk, pw_data in avg_pm_accum.items():
            rows = []
            for pw_key, label in [("reg_wr", "Reg WR"), ("trueskill", "TrueSkill"),
                                   ("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                entries = pw_data.get(pw_key)
                if entries:
                    avg = _weighted_avg(entries)
                    if avg:
                        combined_mpp = round(float(np.mean([p.get("comparisons", 0) for p in papers if p.get("comparisons", 0) >= 3])), 1)
                        rows.append({"method": f"combined_{pw_key}", "label": label,
                                     "avg_mpp": combined_mpp, **avg})
            avg_per_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "rows": rows, "controlled_rows": [], "n_matches": 0}

        avg_within_model = {}
        for si_mk, method_data in avg_wm_accum.items():
            wm_rows = []
            for method_key, label in [("within_wr", "Win Rate"), ("within_ts", "TrueSkill"),
                                       ("within_os1", "OpenSkill 1p"), ("within_os3", "OpenSkill 3p"), ("within_os10", "OpenSkill 10p")]:
                entries = method_data.get(method_key)
                if entries:
                    avg = _weighted_avg(entries)
                    if avg:
                        mk_key = _MODEL_KEY_MAP.get(si_mk)
                        mpps = [model_paper_stats.get(mk_key, {}).get(p["paper_id"], {}).get("total", 0) for p in papers]
                        wm_mpp = round(float(np.mean([m for m in mpps if m > 0])), 1) if any(m > 0 for m in mpps) else 0
                        wm_rows.append({"method": method_key, "label": label,
                                        "avg_mpp": wm_mpp, **avg})
            avg_within_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "rows": wm_rows}

        avg_pw_vs_si = {"per_model": avg_per_model, "within_model": avg_within_model}

        # --- Avg InterModel: per-category rho values, then weighted average ---
        avg_im_accum = {}  # {pair: {method: [(rho, n), ...]}}
        for cat in cats_in_data:
            cat_pids = {pid for pid, c in paper_categories.items() if c == cat}
            # Load OS cache for this category (for inter-model OS correlations)
            cat_im_os_cache = await db.analysis_store.find_one(
                {"_type": "openskill-cache", "key": cat},
                {"_id": 0, "os_per_model": 1},
            )
            for i, m1 in enumerate(model_keys):
                for j, m2 in enumerate(model_keys):
                    if i >= j or m1 not in model_rankings or m2 not in model_rankings:
                        continue
                    pair = f"{_short(m1)} vs {_short(m2)}"
                    for method in ["reg_wr", "trueskill"]:
                        r1 = model_rankings[m1].get(method, {})
                        r2 = model_rankings[m2].get(method, {})
                        common = sorted(set(r1.keys()) & set(r2.keys()) & cat_pids)
                        if len(common) >= 10:
                            v1 = [r1[p] for p in common]
                            v2 = [r2[p] for p in common]
                            rho, _ = scipy_stats.spearmanr(v1, v2)
                            if not np.isnan(rho):
                                avg_im_accum.setdefault(pair, {}).setdefault(method, []).append(
                                    (float(rho), len(common)))
                    # OS inter-model from per-model cache
                    if cat_im_os_cache and cat_im_os_cache.get("os_per_model"):
                        opm = cat_im_os_cache["os_per_model"]
                        os_m1 = opm.get(m1, {})
                        os_m2 = opm.get(m2, {})
                        for os_key in ["os1", "os3", "os10"]:
                            s1 = os_m1.get(os_key, {})
                            s2 = os_m2.get(os_key, {})
                            common = sorted(set(s1.keys()) & set(s2.keys()) & cat_pids)
                            if len(common) >= 10:
                                v1 = [s1[p] for p in common]
                                v2 = [s2[p] for p in common]
                                rho, _ = scipy_stats.spearmanr(v1, v2)
                                if not np.isnan(rho):
                                    method_name = {"os1": "openskill1", "os3": "openskill3", "os10": "openskill10"}[os_key]
                                    avg_im_accum.setdefault(pair, {}).setdefault(method_name, []).append(
                                        (float(rho), len(common)))

        for pair, methods in avg_im_accum.items():
            row = {"pair": pair, "methods": {}}
            for method, entries in methods.items():
                if entries:
                    weights = [n for _, n in entries]
                    rho = round(float(np.average([r for r, _ in entries], weights=weights)), 3)
                    avg_mpp = round((model_avg_mpp.get(model_keys[0], 0) + model_avg_mpp.get(model_keys[1], 0)) / 2, 1) if len(model_keys) >= 2 else 0
                    row["methods"][method] = {"rho": rho, "n": sum(weights), "avg_mpp": avg_mpp, "n_categories": len(entries)}
            if row["methods"]:
                avg_pw_inter_model.append(row)

    total_matches = sum(sum(s.get("total", 0) for s in model_paper_stats[mk].values()) for mk in model_keys) // 2
    t_compute = time.perf_counter() - t_start

    return {
        "status": "ok",
        "models": model_summaries,
        "method_labels": method_labels,
        "n_common_papers": len(common_papers),
        "total_matches": total_matches,
        "category": category,
        "compute_time_s": round(t_compute, 2),
        "correlations": dict(sorted(correlations.items())),
        "ts_correlations": dict(sorted(ts_correlations.items())),
        "avg_correlations": dict(sorted(avg_correlations.items())),
        "avg_ts_correlations": dict(sorted(avg_ts_correlations.items())),
        "agreement": dict(sorted(agreement.items())),
        "avg_agreement": dict(sorted(avg_agreement.items())) if avg_agreement else None,
        "scatter_data": scatter_data,
        "pw_inter_model": pw_inter_model,
        "avg_pw_inter_model": avg_pw_inter_model if avg_pw_inter_model else None,
        "scoring_method": {
            "status": "ok",
            "correlations": scoring_correlations,
            "avg_correlations": avg_scoring_correlations if avg_scoring_correlations else None,
            "n_papers": len(shared_pids),
            "n_matches": total_matches,
        },
        "si_data": si_result,
        "pw_vs_si": pw_vs_si,
        "avg_pw_vs_si": avg_pw_vs_si,
        "openskill_updated_at": None,
    }


async def compute_openskill_cache(category: Optional[str] = None):
    """Heavy computation: loads all matches, computes OpenSkill 1/3/10 pass.
    Result cached in analysis_store, merged into live results on read."""
    from services.ranking import compute_openskill_tm_scores_async as compute_os
    from core.memlog import force_gc
    from datetime import datetime, timezone
    t_start = time.perf_counter()

    query = {"category": category} if category else {}
    papers = []
    async for doc in db.rankings.find(query, {
        "_id": 0, "paper_id": 1, "category": 1, "score": 1, "ts_score": 1,
        "comparisons": 1, "model_stats": 1, "si_ratings": 1,
    }):
        papers.append(doc)

    if len(papers) < 10:
        return {"status": "insufficient_data"}

    paper_categories = {p["paper_id"]: p.get("category") for p in papers}
    model_paper_stats, _, model_keys, _ = _extract_model_data(papers)
    wr_scores = {p["paper_id"]: p["score"] for p in papers if p.get("score") is not None}
    ts_scores = {p["paper_id"]: p["ts_score"] for p in papers if p.get("ts_score") is not None}

    cats = [category] if category else list(set(c for c in paper_categories.values() if c))
    per_model_matches = {}
    all_matches = []

    for cat in cats:
        cat_q = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False},
                 "primary_category": cat}
        async for m in db.matches.find(cat_q, {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}):
            all_matches.append(m)
            mu = m.get("model_used", {})
            raw_key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
            mk = _OPUS_MERGE.get(raw_key, raw_key).replace(".", "_")
            per_model_matches.setdefault(mk, []).append(m)
        if not category:
            force_gc()

    all_matches_slim = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"], "winner_id": m["winner_id"]}
                        for m in all_matches if m.get("winner_id")]
    all_pids = list(wr_scores.keys())

    os1_global = await compute_os(all_matches_slim, all_pids, passes=1)
    os3_global = await compute_os(all_matches_slim, all_pids, passes=3)
    os10_global = await compute_os(all_matches_slim, all_pids, passes=10)
    del all_matches_slim
    force_gc()

    model_os = {}
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

    # Pre-compute OS vs WR/TS scoring method correlations (stored in cache for merge)
    scoring_os_correlations = []
    shared_pids = sorted(set(wr_scores.keys()) & set(os1_global.keys()) if os1_global else set())
    if len(shared_pids) >= 10:
        for os_key, os_scores, os_label in [("openskill", os1_global, "OpenSkill 1p"),
                                             ("openskill3", os3_global, "OpenSkill 3p"),
                                             ("openskill10", os10_global, "OpenSkill 10p")]:
            if not os_scores:
                continue
            for other_key, other_scores, other_label in [("win_rate", wr_scores, "Normalized Win-Rate"),
                                                          ("trueskill", ts_scores, "TrueSkill")]:
                common = sorted(set(os_scores.keys()) & set(other_scores.keys()))
                if len(common) >= 10:
                    v1 = [os_scores[p] for p in common]
                    v2 = [other_scores[p] for p in common]
                    sp_r, _ = scipy_stats.spearmanr(v1, v2)
                    kt_r, _ = scipy_stats.kendalltau(v1, v2)
                    if not np.isnan(sp_r):
                        scoring_os_correlations.append({
                            "method1": other_key, "method2": os_key,
                            "label": f"{other_label} vs {os_label}",
                            "spearman_rho": round(_safe_float(sp_r), 6),
                            "kendall_tau": round(_safe_float(kt_r), 6),
                        })

    # OS vs OS correlations (1p vs 3p, 1p vs 10p, 3p vs 10p)
    os_variants = [("openskill", os1_global, "OpenSkill 1p"),
                   ("openskill3", os3_global, "OpenSkill 3p"),
                   ("openskill10", os10_global, "OpenSkill 10p")]
    for i in range(len(os_variants)):
        for j in range(i + 1, len(os_variants)):
            k1, s1, l1 = os_variants[i]
            k2, s2, l2 = os_variants[j]
            if not s1 or not s2:
                continue
            common = sorted(set(s1.keys()) & set(s2.keys()))
            if len(common) >= 10:
                v1 = [s1[p] for p in common]
                v2 = [s2[p] for p in common]
                sp_r, _ = scipy_stats.spearmanr(v1, v2)
                kt_r, _ = scipy_stats.kendalltau(v1, v2)
                if not np.isnan(sp_r):
                    scoring_os_correlations.append({
                        "method1": k1, "method2": k2,
                        "label": f"{l1} vs {l2}",
                        "spearman_rho": round(_safe_float(sp_r), 6),
                        "kendall_tau": round(_safe_float(kt_r), 6),
                    })

    # Pre-compute PW vs SI OpenSkill rows (combined + per-model)
    # These get injected into the live pw_vs_si tables by the merge function
    pw_papers = [p for p in papers if p.get("comparisons", 0) >= 3]
    def _get_si_score(p, mk=None):
        si = p.get("si_ratings", {})
        if mk:
            r = si.get(mk)
            return r.get("score") if isinstance(r, dict) and r.get("score") else None
        ratings = [r for r in si.values() if isinstance(r, dict) and r.get("score")]
        return round(sum(r["score"] for r in ratings) / len(ratings), 1) if ratings else None

    pw_vs_si_os_rows = {}  # {si_mk: [rows]}
    si_map_keys = ["claude", "gpt", "gemini", "avg"]
    for si_mk in si_map_keys:
        si_scores = {}
        for p in pw_papers:
            s = _get_si_score(p, si_mk if si_mk != "avg" else None)
            if s:
                si_scores[p["paper_id"]] = s
        if len(si_scores) < 10:
            continue
        rows = []
        combined_mpp = round(float(np.mean([p.get("comparisons", 0) for p in pw_papers])), 1) if pw_papers else 0
        for os_key, os_scores, os_label in [("openskill", os1_global, "OpenSkill 1p"),
                                             ("openskill3", os3_global, "OpenSkill 3p"),
                                             ("openskill10", os10_global, "OpenSkill 10p")]:
            if not os_scores:
                continue
            row = _corr_row(f"combined_{os_key}", os_label, os_scores, si_scores)
            if row:
                row["avg_mpp"] = combined_mpp
                rows.append(row)
        pw_vs_si_os_rows[si_mk] = {"combined": rows}

        # Within-model OS rows
        mk_key = _MODEL_KEY_MAP.get(si_mk)
        if mk_key and mk_key in model_os:
            within_rows = []
            within_mpp_vals = [model_paper_stats.get(mk_key, {}).get(p["paper_id"], {}).get("total", 0) for p in pw_papers]
            within_mpp = round(float(np.mean([m for m in within_mpp_vals if m > 0])), 1) if any(m > 0 for m in within_mpp_vals) else 0
            for os_key, os_label in [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]:
                os_scores_mk = model_os[mk_key].get(os_key, {})
                row = _corr_row(f"within_{os_key}", os_label, os_scores_mk, si_scores)
                if row:
                    row["avg_mpp"] = within_mpp
                    within_rows.append(row)
            pw_vs_si_os_rows[si_mk]["within"] = within_rows

    # Sanitize OS scores (remove NaN/inf values that break JSON/MongoDB)
    def _clean_os(scores):
        return {k: _safe_float(v) for k, v in scores.items() if not np.isnan(v) and not np.isinf(v)} if scores else {}

    return {
        "status": "ok",
        "os_global": {"os1": _clean_os(os1_global), "os3": _clean_os(os3_global), "os10": _clean_os(os10_global)},
        "os_per_model": {mk: {k: _clean_os(v) for k, v in data.items()} for mk, data in model_os.items()},
        "scoring_os_correlations": scoring_os_correlations,
        "pw_vs_si_os_rows": pw_vs_si_os_rows,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "compute_time_s": round(time.perf_counter() - t_start, 2),
    }


def merge_openskill_into_live(live: dict, os_cache: dict) -> dict:
    """Inject cached OpenSkill data into live analysis result."""
    if not os_cache or os_cache.get("status") != "ok":
        return live

    model_os = os_cache.get("os_per_model", {})

    # Inject OS columns into pw_inter_model rows
    for row in live.get("pw_inter_model", []):
        pair_parts = row["pair"].split(" vs ")
        if len(pair_parts) != 2:
            continue
        # Find model keys from short names
        m1_key = next((k for k, v in _SHORT_NAMES.items() if v == pair_parts[0]), None)
        m2_key = next((k for k, v in _SHORT_NAMES.items() if v == pair_parts[1]), None)
        if not m1_key or not m2_key:
            continue
        for os_key, os_data in [("openskill1", "os1"), ("openskill3", "os3"), ("openskill10", "os10")]:
            r1 = model_os.get(m1_key, {}).get(os_data, {})
            r2 = model_os.get(m2_key, {}).get(os_data, {})
            common = sorted(set(r1.keys()) & set(r2.keys()))
            if len(common) >= 10:
                v1 = [r1[p] for p in common]
                v2 = [r2[p] for p in common]
                rho, _ = scipy_stats.spearmanr(v1, v2)
                avg_mpp = row["methods"].get("reg_wr", {}).get("avg_mpp", 0)
                row["methods"][os_key] = {"rho": round(float(rho), 3), "n": len(common), "avg_mpp": avg_mpp}

    # Inject OS into scoring_method correlations (pre-computed in cache)
    sm = live.get("scoring_method", {})
    sm_corrs = sm.get("correlations", [])
    for row in os_cache.get("scoring_os_correlations", []):
        sm_corrs.append(row)

    # Ensure OS-vs-OS pairs exist (they may be missing from older caches)
    os_global = os_cache.get("os_global", {})
    existing_labels = {r.get("label") for r in sm_corrs}
    os_variants = [("os1", "OpenSkill 1p"), ("os3", "OpenSkill 3p"), ("os10", "OpenSkill 10p")]
    for i in range(len(os_variants)):
        for j in range(i + 1, len(os_variants)):
            k1, l1 = os_variants[i]
            k2, l2 = os_variants[j]
            label = f"{l1} vs {l2}"
            if label in existing_labels:
                continue
            s1 = os_global.get(k1, {})
            s2 = os_global.get(k2, {})
            common = sorted(set(s1.keys()) & set(s2.keys()))
            if len(common) >= 10:
                v1 = [s1[p] for p in common]
                v2 = [s2[p] for p in common]
                sp_r, _ = scipy_stats.spearmanr(v1, v2)
                kt_r, _ = scipy_stats.kendalltau(v1, v2)
                if not np.isnan(sp_r):
                    sm_corrs.append({
                        "method1": k1, "method2": k2,
                        "label": label,
                        "spearman_rho": round(float(sp_r), 6),
                        "kendall_tau": round(float(kt_r), 6),
                    })

    # Inject OS rows into pw_vs_si (pre-computed in cache)
    pw_vs_si = live.get("pw_vs_si")
    pw_vs_si_os = os_cache.get("pw_vs_si_os_rows", {})
    if pw_vs_si and pw_vs_si_os:
        for si_mk, os_data in pw_vs_si_os.items():
            pm = pw_vs_si.get("per_model", {}).get(si_mk)
            if pm:
                # Add combined OS rows to per_model rows
                for row in os_data.get("combined", []):
                    pm["rows"].append(row)
                # Add within-model OS rows to controlled_rows (NOT combined — controlled must use single-model data)
                for row in os_data.get("within", []):
                    pm["controlled_rows"].append(row)
            wm = pw_vs_si.get("within_model", {}).get(si_mk)
            if wm:
                for row in os_data.get("within", []):
                    wm["rows"].append(row)

    live["openskill_updated_at"] = os_cache.get("computed_at")
    return live


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
    raw_bins = [round(1.0 + i * 0.1, 1) for i in range(91)]
    distributions = {}
    for m in METRICS + ["subscore_avg"]:
        vals = arrays.get(m, [])
        if not vals:
            continue
        hist = Counter()
        raw_hist = Counter()
        for v in vals:
            bucket = max(1.0, min(10.0, round(round(v * 2) / 2, 1)))
            hist[bucket] += 1
            raw_bucket = max(1.0, min(10.0, round(v, 1)))
            raw_hist[raw_bucket] += 1
        distributions[m] = {
            "histogram": [{"bin": b, "count": hist.get(b, 0)} for b in bins],
            "raw_histogram": [{"bin": b, "count": raw_hist.get(b, 0)} for b in raw_bins],
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

    # Metric correlations (between SI sub-metrics)
    metric_correlations = {}
    for i, m1 in enumerate(METRICS):
        for j, m2 in enumerate(METRICS):
            if j <= i:
                continue
            v1 = arrays.get(m1, [])
            v2 = arrays.get(m2, [])
            n = min(len(v1), len(v2))
            if n < 5:
                continue
            rho, p_val = scipy_stats.spearmanr(v1[:n], v2[:n])
            if not np.isnan(rho):
                metric_correlations[f"{m1} vs {m2}"] = {
                    "spearman": round(float(rho), 3),
                    "p_value": round(float(p_val), 4) if p_val >= 0.0001 else 0.0,
                    "n": n,
                }

    # Available models
    model_counts = {"claude": 0, "gpt": 0, "gemini": 0}
    for p in papers:
        si = p.get("si_ratings", {})
        for mk in ("claude", "gpt", "gemini"):
            if isinstance(si.get(mk), dict) and si[mk].get("score"):
                model_counts[mk] += 1

    # Per-model distributions (for model tab switching in frontend)
    per_model_distributions = {}
    for mk in ("claude", "gpt", "gemini"):
        mk_papers = [p for p in papers if _get_si(p, mk)]
        if len(mk_papers) < 5:
            continue
        mk_arrays = {}
        for m in METRICS:
            mk_arrays[m] = [_get_si(p, mk).get(m, 0) for p in mk_papers if _get_si(p, mk).get(m)]
        mk_sub_avgs = []
        for p in mk_papers:
            r = _get_si(p, mk)
            subs = [r.get(m) for m in SUB_METRICS if r.get(m)]
            if len(subs) >= 2:
                mk_sub_avgs.append(round(sum(subs) / len(subs), 2))
        mk_arrays["subscore_avg"] = mk_sub_avgs

        mk_dists = {}
        for m in METRICS + ["subscore_avg"]:
            vals = mk_arrays.get(m, [])
            if not vals:
                continue
            hist = Counter()
            raw_hist = Counter()
            for v in vals:
                bucket = max(1.0, min(10.0, round(round(v * 2) / 2, 1)))
                hist[bucket] += 1
                raw_bucket = max(1.0, min(10.0, round(v, 1)))
                raw_hist[raw_bucket] += 1
            mk_dists[m] = {
                "histogram": [{"bin": b, "count": hist.get(b, 0)} for b in bins],
                "raw_histogram": [{"bin": b, "count": raw_hist.get(b, 0)} for b in raw_bins],
                "mean": round(float(np.mean(vals)), 2),
                "median": round(float(np.median(vals)), 1),
                "std": round(float(np.std(vals, ddof=1)), 2) if len(vals) > 1 else 0,
                "n": len(vals),
            }
        per_model_distributions[mk] = mk_dists

    return {
        "status": "ok",
        "total_papers": len(filtered),
        "distributions": distributions,
        "per_model_distributions": per_model_distributions,
        "metric_correlations": metric_correlations,
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
    sub_mk.split("/")[0]

    controlled_pw = {
        "reg_wr": ("Reg WR", {}), "trueskill": ("TrueSkill", {}),
        "openskill": ("OpenSkill 1p", {}), "openskill3": ("OpenSkill 3p", {}), "openskill10": ("OpenSkill 10p", {}),
    }
    # Controlled WR from single model's stats
    sub_wr = {}
    sub_mk_dot = sub_mk.replace("_", ".")  # check both variants
    for p in pw_papers:
        ms_data = p.get("model_stats", {})
        ms = ms_data.get(sub_mk) or ms_data.get(sub_mk_dot)
        if isinstance(ms, dict) and ms.get("total", 0) >= MIN_MATCHES:
            sub_wr[p["paper_id"]] = (ms.get("wins", 0) + 0.5) / (ms.get("total", 0) + 1.0)
    controlled_pw["reg_wr"] = ("Reg WR", sub_wr)

    # Controlled TS from single model's TS
    sub_ts = {}
    for p in pw_papers:
        mts = p.get("model_ts", {})
        _rng.shuffle(mk_keys)
        for mk_inner in mk_keys:
            mk_inner_dot = mk_inner.replace("_", ".")
            ts_data = mts.get(mk_inner) or mts.get(mk_inner_dot)
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
        # Win Rate — check both dot and underscore variants of model key
        wm_wr = {}
        dot_key = mk_key.replace("_", ".")  # also check original dotted key in raw data
        for p in pw_papers:
            ms_data = p.get("model_stats", {})
            ms = ms_data.get(mk_key) or ms_data.get(dot_key)
            if isinstance(ms, dict) and ms.get("total", 0) >= MIN_MATCHES:
                wm_wr[p["paper_id"]] = (ms.get("wins", 0) + 0.5) / (ms.get("total", 0) + 1.0)
        row = _corr_row("within_wr", "Win Rate", wm_wr, si_scores)
        if row:
            row["avg_mpp"] = within_mpp.get(si_mk, 0)
            wm_rows.append(row)
        # TrueSkill — check both variants
        wm_ts = {}
        for p in pw_papers:
            mts = p.get("model_ts", {})
            ts_data = mts.get(mk_key) or mts.get(dot_key)
            if isinstance(ts_data, dict) and ts_data.get("mu"):
                wm_ts[p["paper_id"]] = ts_data["mu"]
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
