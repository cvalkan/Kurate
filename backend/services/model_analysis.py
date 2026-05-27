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

from core.config import db, logger


_OPUS_MERGE = {
    "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
    "anthropic/claude-opus-4-6": "anthropic/claude-opus",
    "gemini/gemini-3.1-pro-preview": "gemini/gemini-3-pro-preview",
    "gemini/gemini-3_1-pro-preview": "gemini/gemini-3-pro-preview",
}
_SHORT_NAMES = {
    "anthropic/claude-opus": "Claude Opus",
    "gemini/gemini-3-pro-preview": "Gemini Pro",
    "gemini/gemini-3_1-pro-preview": "Gemini Pro",
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


# Merge model keys that should be treated as the same model
_MODEL_KEY_MERGE = {
    "gemini/gemini-3.1-pro-preview": "gemini/gemini-3-pro-preview",
    "gemini/gemini-3_1-pro-preview": "gemini/gemini-3-pro-preview",
}


def _normalize_model_key(mk: str) -> str:
    return _MODEL_KEY_MERGE.get(mk, mk)


def _extract_model_data(papers):
    """Extract per-model stats from rankings docs.
    Returns (model_paper_stats, model_paper_ts, model_paper_os, model_keys, model_wr)."""
    model_paper_stats = {}
    model_paper_ts = {}
    model_paper_os = {}
    for p in papers:
        ms = p.get("model_stats")
        if ms and isinstance(ms, dict):
            for mk, stats in ms.items():
                mk = _normalize_model_key(mk)
                if isinstance(stats, dict) and stats.get("total") is not None:
                    existing = model_paper_stats.setdefault(mk, {}).get(p["paper_id"])
                    if existing:
                        # Merge: sum wins/losses/total
                        existing["wins"] = existing.get("wins", 0) + stats.get("wins", 0)
                        existing["losses"] = existing.get("losses", 0) + stats.get("losses", 0)
                        existing["total"] = existing.get("total", 0) + stats.get("total", 0)
                    else:
                        model_paper_stats[mk][p["paper_id"]] = dict(stats)
        mts = p.get("model_ts")
        if mts and isinstance(mts, dict):
            for mk, ts_data in mts.items():
                mk = _normalize_model_key(mk)
                if isinstance(ts_data, dict) and ts_data.get("mu"):
                    # Keep the latest (higher mu wins in case of merge)
                    existing = model_paper_ts.setdefault(mk, {}).get(p["paper_id"])
                    if not existing or ts_data["mu"] > existing:
                        model_paper_ts[mk][p["paper_id"]] = ts_data["mu"]
        mos = p.get("model_os")
        if mos and isinstance(mos, dict):
            for mk, os_data in mos.items():
                mk = _normalize_model_key(mk)
                if isinstance(os_data, dict) and os_data.get("mu"):
                    existing = model_paper_os.setdefault(mk, {}).get(p["paper_id"])
                    if not existing or os_data["mu"] > existing:
                        model_paper_os[mk][p["paper_id"]] = os_data["mu"]

    model_keys = sorted(mk for mk in model_paper_stats
                        if sum(s.get("total", 0) for s in model_paper_stats[mk].values()) > 0)

    model_wr = {}
    for mk in model_keys:
        model_wr[mk] = {}
        for pid, s in model_paper_stats[mk].items():
            if s.get("total", 0) >= MIN_MATCHES:
                model_wr[mk][pid] = (s.get("wins", 0) + 0.5) / (s.get("total", 0) + 1.0)

    return model_paper_stats, model_paper_ts, model_paper_os, model_keys, model_wr


_live_analysis_cache = {}  # {cache_key: {"result": dict, "ts": float}}
_LIVE_ANALYSIS_TTL = 3600  # 1 hour safety net — in practice cache is refreshed event-driven by notify_data_changed
_live_analysis_dirty = False  # Set by notify_data_changed, consumed by background task


def mark_live_analysis_dirty():
    """Called when match data changes. Triggers background recompute of All Categories."""
    global _live_analysis_dirty
    _live_analysis_dirty = True


async def compute_live_analysis(category: Optional[str] = None):
    """Computes live analysis from rankings + merges cached OpenSkill data.
    Returns the complete, final response — no post-cache mutation needed.
    
    All Categories (category=None) is precomputed in background when data changes.
    Per-category results are cached with TTL after first request.
    """
    cache_key = category or "__all__"
    cached = _live_analysis_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _LIVE_ANALYSIS_TTL:
        return cached["result"]

    result = await _compute_live_analysis_impl(category)

    # Merge cached OpenSkill data into the live result BEFORE caching.
    # This way the cached result is complete — no mutation on read.
    cat_key = category or "__all__"
    os_doc = await db.analysis_store.find_one(
        {"_type": "openskill-cache", "key": cat_key}, {"_id": 0}
    )
    if os_doc:
        os_doc.pop("_type", None)
        os_doc.pop("key", None)
        result = merge_openskill_into_live(result, os_doc)

    _live_analysis_cache[cache_key] = {"result": result, "ts": time.time()}
    return result


async def _bg_refresh_all_categories():
    """Background task: recomputes All Categories analysis when data changes.
    Debounces by 10s to batch rapid match completions."""
    import asyncio
    global _live_analysis_dirty

    # Initial warm-up after startup
    await asyncio.sleep(30)
    try:
        result = await _compute_live_analysis_impl(None)
        os_doc = await db.analysis_store.find_one(
            {"_type": "openskill-cache", "key": "__all__"}, {"_id": 0}
        )
        if os_doc:
            os_doc.pop("_type", None)
            os_doc.pop("key", None)
            result = merge_openskill_into_live(result, os_doc)
        _live_analysis_cache["__all__"] = {"result": result, "ts": time.time()}
        logger.info("Background All Categories analysis cache warmed on startup")
    except Exception as e:
        logger.warning(f"Initial All Categories refresh failed: {e}")

    while True:
        # Wait for data to change (event-driven, no periodic refresh)
        while not _live_analysis_dirty:
            await asyncio.sleep(5)
        
        # Debounce: wait 10s for more changes to batch
        _live_analysis_dirty = False
        await asyncio.sleep(10)
        _live_analysis_dirty = False  # Clear any that arrived during debounce

        try:
            result = await _compute_live_analysis_impl(None)
            os_doc = await db.analysis_store.find_one(
                {"_type": "openskill-cache", "key": "__all__"}, {"_id": 0}
            )
            if os_doc:
                os_doc.pop("_type", None)
                os_doc.pop("key", None)
                result = merge_openskill_into_live(result, os_doc)
            _live_analysis_cache["__all__"] = {"result": result, "ts": time.time()}
            logger.info("Background All Categories analysis cache refreshed")
            # Also invalidate per-category caches (data changed)
            keys_to_remove = [k for k in _live_analysis_cache if k != "__all__"]
            for k in keys_to_remove:
                del _live_analysis_cache[k]
        except Exception as e:
            logger.warning(f"Background All Categories refresh failed: {e}")


async def _compute_live_analysis_impl(category: Optional[str] = None):
    """Actual computation — loads from DB."""
    t_start = time.perf_counter()

    query = {"category": category} if category else {}
    papers = []
    async for doc in db.rankings.find(query, {
        "_id": 0, "paper_id": 1, "title": 1, "category": 1,
        "ts_score": 1, "os_score": 1, "comparisons": 1, "wins": 1, "win_rate": 1,
        "model_stats": 1, "model_ts": 1, "model_os": 1, "si_ratings": 1,
    }):
        papers.append(doc)

    if len(papers) < 10:
        return {"status": "insufficient_data", "n_papers": len(papers)}

    paper_categories = {p["paper_id"]: p.get("category") for p in papers}
    model_paper_stats, model_paper_ts, model_paper_os, model_keys, model_wr = _extract_model_data(papers)

    # WR score = win_rate (actual wins/comparisons). Previously was regularized Wilson score,
    # but `score` field was overwritten by scoring simplification migration (score=ts_score).
    wr_scores = {p["paper_id"]: p["win_rate"] for p in papers if p.get("win_rate") is not None and p.get("comparisons", 0) >= 3}
    ts_scores = {p["paper_id"]: p["ts_score"] for p in papers if p.get("ts_score") is not None}
    os_scores = {p["paper_id"]: p["os_score"] for p in papers if p.get("os_score") is not None}

    # --- Model summaries ---
    model_summaries = []
    for mk in model_keys:
        total = sum(s.get("total", 0) for s in model_paper_stats[mk].values())
        model_summaries.append({
            "key": mk, "label": _short(mk), "short": _short(mk),
            "total_matches": total // 2, "papers_judged": len(model_paper_stats[mk]),  # total//2: each match involves 2 papers
        })

    # --- PW Inter-Model (WR + TS only, OS columns filled by merge) ---
    method_labels = {"reg_wr": "Reg WR", "trueskill": "TrueSkill",
                     "openskill": "OpenSkill"}

    model_rankings = {}
    model_avg_mpp = {}
    for mk in model_keys:
        mk_pids = [pid for pid, s in model_paper_stats[mk].items() if s.get("total", 0) >= MIN_MATCHES]
        if len(mk_pids) < 20:
            continue
        model_rankings[mk] = {
            "reg_wr": {pid: model_wr[mk][pid] for pid in mk_pids if pid in model_wr[mk]},
            "trueskill": model_paper_ts.get(mk, {}),
            "openskill": model_paper_os.get(mk, {}),
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
            for method in ["reg_wr", "trueskill", "openskill"]:
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
            "label": "Win Rate vs TrueSkill",
            "spearman_rho": round(float(sp_r), 6), "kendall_tau": round(float(kt_r), 6),
        })

    # WR vs OS (incremental) and TS vs OS (incremental)
    for pw_label, pw_key, pw_dict in [("Normalized Win-Rate", "win_rate", wr_scores), ("TrueSkill", "trueskill", ts_scores)]:
        shared_os = sorted(set(pw_dict.keys()) & set(os_scores.keys()))
        if len(shared_os) >= 10:
            sp_r, _ = scipy_stats.spearmanr([pw_dict[p] for p in shared_os], [os_scores[p] for p in shared_os])
            kt_r, _ = scipy_stats.kendalltau([pw_dict[p] for p in shared_os], [os_scores[p] for p in shared_os])
            if not np.isnan(sp_r):
                scoring_correlations.append({
                    "method1": pw_key, "method2": "openskill",
                    "label": f"{pw_label} vs OpenSkill",
                    "spearman_rho": round(float(sp_r), 6), "kendall_tau": round(float(kt_r), 6),
                })

    # --- WR/TS correlations + agreement ---
    correlations = {}
    ts_correlations = {}
    agreement = {}
    scatter_data = {}
    ts_scatter_data = {}
    os_scatter_data = {}
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
                ts_scatter_data[pair] = {
                    "x": [round(float(r), 1) for r in scipy_stats.rankdata(v1) / len(v1) * 100],
                    "y": [round(float(r), 1) for r in scipy_stats.rankdata(v2) / len(v2) * 100], "n": len(pp_ts)}
            os1, os2 = model_paper_os.get(m1, {}), model_paper_os.get(m2, {})
            pp_os = sorted(set(os1.keys()) & set(os2.keys()))
            if len(pp_os) >= 5:
                ov1, ov2 = [os1[p] for p in pp_os], [os2[p] for p in pp_os]
                os_scatter_data[pair] = {
                    "x": [round(float(r), 1) for r in scipy_stats.rankdata(ov1) / len(ov1) * 100],
                    "y": [round(float(r), 1) for r in scipy_stats.rankdata(ov2) / len(ov2) * 100], "n": len(pp_os)}

    common_papers = set(wr_scores.keys())
    for mk in model_keys:
        common_papers &= set(model_wr.get(mk, {}).keys())

    # --- SI Rating Stats ---
    si_result = _compute_si_stats(papers)

    # SI match-level agreement + controlled (using actual PW pairs)
    if si_result and si_result.get("_si_model_scores"):
        import scipy.stats as _sp
        import random as _rnd
        _rng = _rnd.Random(42)
        si_model_scores = si_result.pop("_si_model_scores")

        # Load PW match pairs for controlled comparison + PW pair-level agreement
        match_q = {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}
        if category:
            match_q["primary_category"] = category
        pw_pairs_for_si = {}  # {model_key: set of (pa, pb)}
        pw_pair_winners = {}  # {model_key: {(pa, pb): winner_direction}}
        async for m in db.matches.find(match_q, {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1}):
            mu = m.get("model_used", {})
            raw = f"{mu.get('provider','')}/{mu.get('model','')}"
            if "claude" in raw or "opus" in raw: mk = "claude"
            elif "gemini" in raw: mk = "gemini"
            elif "gpt" in raw: mk = "gpt"
            else: continue
            p1, p2 = m["paper1_id"], m["paper2_id"]
            pair = (p1, p2) if p1 < p2 else (p2, p1)
            pw_pairs_for_si.setdefault(mk, set()).add(pair)
            # Store winner direction (1 = first in sorted pair wins, -1 = second wins)
            winner = 1 if m.get("winner_id") == pair[0] else -1
            pw_pair_winners.setdefault(mk, {})[pair] = winner

        # PW pair-level match agreement (actual: when both models judged the same pair)
        pw_match_agreement = {}
        for i, m1 in enumerate(sorted(pw_pair_winners)):
            for j, m2 in enumerate(sorted(pw_pair_winners)):
                if j <= i: continue
                pair_key = f"{m1} vs {m2}"
                shared = set(pw_pair_winners[m1].keys()) & set(pw_pair_winners[m2].keys())
                if not shared: continue
                agree = sum(1 for p in shared if pw_pair_winners[m1][p] == pw_pair_winners[m2][p])
                total = len(shared)
                pw_match_agreement[pair_key] = {
                    "agree": agree, "disagree": total - agree, "total": total,
                    "rate": round(agree / total * 100, 1),
                }

        # Full SI match agreement (random pairs)
        si_match_full = {}
        for i, m1 in enumerate(sorted(si_model_scores)):
            for j, m2 in enumerate(sorted(si_model_scores)):
                if j <= i: continue
                pair_key = f"{m1} vs {m2}"
                common = sorted(set(si_model_scores[m1].keys()) & set(si_model_scores[m2].keys()))
                if len(common) < 20: continue
                max_pairs = min(100000, len(common) * (len(common) - 1) // 2)
                if len(common) <= 450:
                    from itertools import combinations
                    sampled = list(combinations(common, 2))
                else:
                    sampled, seen = [], set()
                    for _ in range(max_pairs * 3):
                        if len(sampled) >= max_pairs: break
                        a, b = _rng.sample(common, 2)
                        k = (a, b) if a < b else (b, a)
                        if k not in seen: seen.add(k); sampled.append(k)
                agree = total = 0
                for pa, pb in sampled:
                    s1a, s1b = si_model_scores[m1].get(pa), si_model_scores[m1].get(pb)
                    s2a, s2b = si_model_scores[m2].get(pa), si_model_scores[m2].get(pb)
                    if s1a is None or s1b is None or s2a is None or s2b is None: continue
                    if s1a == s1b or s2a == s2b: continue
                    total += 1
                    if (s1a > s1b) == (s2a > s2b): agree += 1
                if total > 0:
                    si_match_full[pair_key] = {"agree": agree, "disagree": total - agree, "total": total, "rate": round(agree / total * 100, 1)}
        si_result["si_match_agreement"] = si_match_full

        # Controlled SI match agreement: same pairs as PW Match Agreement
        # (pairs judged by BOTH models in PW, where both papers also have SI from both)
        si_match_ctrl = {}
        for i, m1 in enumerate(sorted(si_model_scores)):
            for j, m2 in enumerate(sorted(si_model_scores)):
                if j <= i: continue
                pair_key = f"{m1} vs {m2}"
                # Same pair set as PW Match Agreement: intersection of both models' PW pairs
                shared_pw_pairs = pw_pairs_for_si.get(m1, set()) & pw_pairs_for_si.get(m2, set())
                agree = total = 0
                for pa, pb in shared_pw_pairs:
                    s1a = si_model_scores[m1].get(pa)
                    s1b = si_model_scores[m1].get(pb)
                    s2a = si_model_scores[m2].get(pa)
                    s2b = si_model_scores[m2].get(pb)
                    if s1a is None or s1b is None or s2a is None or s2b is None: continue
                    if s1a == s1b or s2a == s2b: continue
                    total += 1
                    if (s1a > s1b) == (s2a > s2b): agree += 1
                if total > 0:
                    si_match_ctrl[pair_key] = {"agree": agree, "disagree": total - agree, "total": total, "rate": round(agree / total * 100, 1)}
        si_result["si_match_agreement_controlled"] = si_match_ctrl
        si_result["pw_match_agreement"] = pw_match_agreement

        # Controlled ranking correlation: papers appearing in PW pairs judged by both models
        controlled_corr = {}
        for i, m1 in enumerate(sorted(si_model_scores)):
            for j, m2 in enumerate(sorted(si_model_scores)):
                if j <= i: continue
                shared_pw = pw_pairs_for_si.get(m1, set()) & pw_pairs_for_si.get(m2, set())
                pw_paper_pool = set()
                for p1, p2 in shared_pw:
                    pw_paper_pool.add(p1); pw_paper_pool.add(p2)
                common = sorted(pw_paper_pool & set(si_model_scores[m1].keys()) & set(si_model_scores[m2].keys()))
                if len(common) >= 10:
                    v1 = [si_model_scores[m1][p] for p in common]
                    v2 = [si_model_scores[m2][p] for p in common]
                    rho, _ = _sp.spearmanr(v1, v2)
                    if not np.isnan(rho):
                        controlled_corr[f"{m1} vs {m2}"] = {"spearman": round(float(rho), 3), "n": len(common)}
        si_result["controlled_inter_model_si"] = controlled_corr
        del pw_pairs_for_si

    # --- PW vs SI (WR/TS only, OS empty) ---
    pw_vs_si = _compute_pw_vs_si(
        papers, wr_scores, ts_scores, {}, {}, {},
        model_rankings, {}, model_paper_stats, model_avg_mpp,
        category, paper_categories, os_incr=os_scores,
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
                        pr, _ = scipy_stats.pearsonr(v1, v2)
                        if not np.isnan(rho):
                            avg_correlations.setdefault(pair, []).append((float(rho), float(pr), len(common)))
                        med1, med2 = np.median(v1), np.median(v2)
                        agree = sum(1 for p in common if (model_wr[m1][p] >= med1) == (model_wr[m2][p] >= med2))
                        avg_agreement.setdefault(pair, []).append((agree, len(common)))
                    ts1, ts2 = model_paper_ts.get(m1, {}), model_paper_ts.get(m2, {})
                    common_ts = sorted(set(ts1.keys()) & set(ts2.keys()) & cat_pids)
                    if len(common_ts) >= 10:
                        v1 = [ts1[p] for p in common_ts]
                        v2 = [ts2[p] for p in common_ts]
                        rho, _ = scipy_stats.spearmanr(v1, v2)
                        pr, _ = scipy_stats.pearsonr(v1, v2)
                        if not np.isnan(rho):
                            avg_ts_correlations.setdefault(pair, []).append((float(rho), float(pr), len(common_ts)))
        for key in list(avg_correlations.keys()):
            data = avg_correlations[key]
            w = [n for _, _, n in data]
            avg_correlations[key] = {
                "spearman_r": round(float(np.average([r for r, _, _ in data], weights=w)), 3),
                "pearson_r": round(float(np.average([pr for _, pr, _ in data], weights=w)), 3),
                "n_papers": sum(w), "n_categories": len(data),
            }
        for key in list(avg_ts_correlations.keys()):
            data = avg_ts_correlations[key]
            w = [n for _, _, n in data]
            avg_ts_correlations[key] = {
                "spearman_r": round(float(np.average([r for r, _, _ in data], weights=w)), 3),
                "pearson_r": round(float(np.average([pr for _, pr, _ in data], weights=w)), 3),
                "n_papers": sum(w), "n_categories": len(data),
            }
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
    avg_scoring_correlations = []
    if not category and paper_categories:
        cats_in_data = set(c for c in paper_categories.values() if c)
        paper_by_cat = {}
        for p in papers:
            pc = paper_categories.get(p.get("paper_id") or p.get("id"))
            if pc:
                paper_by_cat.setdefault(pc, []).append(p)

        # Batch-load all OS caches upfront (reused across PW-vs-SI, Scoring Method, Inter-Model loops)
        _os_cache_by_cat = {}
        async for doc in db.analysis_store.find(
            {"_type": "openskill-cache", "key": {"$in": list(cats_in_data)}},
            {"_id": 0, "key": 1, "os_global": 1, "os_per_model": 1},
        ):
            _os_cache_by_cat[doc["key"]] = doc

        # --- Avg PW-vs-SI: per-category rho values, then weighted average ---
        _SI_LABELS = {"claude": "Claude Opus", "gpt": "GPT-5.2", "gemini": "Gemini Pro", "avg": "Average (all models)"}
        _SI_MKS = ("claude", "gpt", "gemini")
        avg_pm_accum = {}   # {si_mk: {pw_key: [(rho, tau, n), ...]}}
        avg_wm_accum = {}   # {si_mk: {method: [(rho, tau, n), ...]}}
        avg_ctrl_accum = {} # {si_mk: {pw_key: [(rho, tau, n), ...]}} — controlled (single-judge) per-category

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

            # Load cached OpenSkill scores for this category (pre-loaded above)
            cat_os_cache = _os_cache_by_cat.get(cat)
            cat_si = {}
            for mk in _SI_MKS:
                sm = {p["paper_id"]: _get_si_score_avg(p, mk) for p in cat_papers if _get_si_score_avg(p, mk)}
                if len(sm) >= 10:
                    cat_si[mk] = sm
            avg_si_cat = {p["paper_id"]: _get_si_score_avg(p) for p in cat_papers if _get_si_score_avg(p)}
            if len(avg_si_cat) >= 10:
                cat_si["avg"] = avg_si_cat

            # PW scores for this category
            cat_wr = {p["paper_id"]: p["win_rate"] for p in cat_papers if p.get("win_rate") is not None and p.get("comparisons", 0) >= 3}
            cat_ts = {p["paper_id"]: p["ts_score"] for p in cat_papers if p.get("ts_score")}
            cat_os_incr = {p["paper_id"]: p["os_score"] for p in cat_papers if p.get("os_score")}
            cat_pw = {"reg_wr": ("Reg WR", cat_wr), "trueskill": ("TrueSkill", cat_ts), "openskill": ("OpenSkill", cat_os_incr)}

            # Load cached OpenSkill scores for this category (batch pre-loaded)
            # Combined PW vs SI (WR, TS, OS)
            for si_mk, si_scores in cat_si.items():
                for pw_key, (pw_label, pw_scores) in cat_pw.items():
                    row = _corr_row(f"combined_{pw_key}", pw_label, pw_scores, si_scores)
                    if row:
                        avg_pm_accum.setdefault(si_mk, {}).setdefault(pw_key, []).append(
                            (row["spearman_rho"], row["kendall_tau"], row["n"]))

            # Within-model PW vs SI (also accumulates controlled rows)
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
                # Within-model OpenSkill — per-model incremental
                wm_os_incr = {}
                for p in cat_papers:
                    mos = p.get("model_os", {})
                    os_data = mos.get(mk_key) or mos.get(dot_key)
                    if isinstance(os_data, dict) and os_data.get("mu"):
                        wm_os_incr[p["paper_id"]] = os_data["mu"]
                row = _corr_row("within_os", "OpenSkill", wm_os_incr, si_scores)
                if row:
                    avg_wm_accum.setdefault(si_mk, {}).setdefault("within_os", []).append(
                        (row["spearman_rho"], row["kendall_tau"], row["n"]))

                # Controlled: single-judge stats correlated vs ALL SI models
                for si_target, si_target_scores in cat_si.items():
                    row_wr = _corr_row("ctrl_wr", "Reg WR", wm_wr, si_target_scores)
                    if row_wr:
                        avg_ctrl_accum.setdefault(si_target, {}).setdefault("reg_wr", []).append(
                            (row_wr["spearman_rho"], row_wr["kendall_tau"], row_wr["n"]))
                    row_ts = _corr_row("ctrl_ts", "TrueSkill", wm_ts, si_target_scores)
                    if row_ts:
                        avg_ctrl_accum.setdefault(si_target, {}).setdefault("trueskill", []).append(
                            (row_ts["spearman_rho"], row_ts["kendall_tau"], row_ts["n"]))
                    # Controlled OpenSkill
                    row_os_incr = _corr_row("ctrl_os", "OpenSkill", wm_os_incr, si_target_scores)
                    if row_os_incr:
                        avg_ctrl_accum.setdefault(si_target, {}).setdefault("openskill", []).append(
                            (row_os_incr["spearman_rho"], row_os_incr["kendall_tau"], row_os_incr["n"]))

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
            cat_wr_sm = {p["paper_id"]: p["win_rate"] for p in cat_papers_sm if p.get("win_rate") is not None}
            cat_ts_sm = {p["paper_id"]: p["ts_score"] for p in cat_papers_sm if p.get("ts_score")}
            # WR vs TS
            shared = sorted(set(cat_wr_sm.keys()) & set(cat_ts_sm.keys()))
            if len(shared) >= 10:
                sp_r, _ = scipy_stats.spearmanr([cat_wr_sm[p] for p in shared], [cat_ts_sm[p] for p in shared])
                kt_r, _ = scipy_stats.kendalltau([cat_wr_sm[p] for p in shared], [cat_ts_sm[p] for p in shared])
                if not np.isnan(sp_r):
                    avg_scoring_accum.setdefault("Normalized Win-Rate vs TrueSkill", []).append((float(sp_r), float(kt_r), len(shared)))
            # WR/TS vs OS (from batch pre-loaded cache)
            # WR/TS vs OS live (incremental)
            cat_os_sm = {p["paper_id"]: p["os_score"] for p in cat_papers_sm if p.get("os_score")}
            for pw_label, pw_dict in [("Normalized Win-Rate", cat_wr_sm), ("TrueSkill", cat_ts_sm)]:
                shared_os_live = sorted(set(pw_dict.keys()) & set(cat_os_sm.keys()))
                if len(shared_os_live) >= 10:
                    sp_r, _ = scipy_stats.spearmanr([pw_dict[p] for p in shared_os_live], [cat_os_sm[p] for p in shared_os_live])
                    kt_r, _ = scipy_stats.kendalltau([pw_dict[p] for p in shared_os_live], [cat_os_sm[p] for p in shared_os_live])
                    if not np.isnan(sp_r):
                        avg_scoring_accum.setdefault(f"{pw_label} vs OpenSkill", []).append((float(sp_r), float(kt_r), len(shared_os_live)))

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
        # Use the aggregate m/paper values (m/paper is a factual count, same in both modes)
        agg_pm = pw_vs_si.get("per_model", {}) if pw_vs_si else {}
        agg_wm = pw_vs_si.get("within_model", {}) if pw_vs_si else {}
        for si_mk, pw_data in avg_pm_accum.items():
            rows = []
            agg_rows = agg_pm.get(si_mk, {}).get("rows", [])
            agg_mpp_map = {r.get("method", r.get("label", "")): r.get("avg_mpp", 0) for r in agg_rows}
            # All methods in "All judges combined" share the same m/paper — use WR's value as default
            default_mpp = agg_mpp_map.get("combined_reg_wr", agg_mpp_map.get("Reg WR", 0))
            for pw_key, label in [("reg_wr", "Reg WR"), ("trueskill", "TrueSkill"),
                                   ("openskill", "OpenSkill")]:
                entries = pw_data.get(pw_key)
                if entries:
                    avg = _weighted_avg(entries)
                    if avg:
                        mpp = agg_mpp_map.get(f"combined_{pw_key}", default_mpp)
                        rows.append({"method": f"combined_{pw_key}", "label": label,
                                     "avg_mpp": mpp, **avg})
            avg_per_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "rows": rows, "controlled_rows": [], "n_matches": 0}

        # Build controlled rows from avg_ctrl_accum
        for si_mk, ctrl_data in avg_ctrl_accum.items():
            ctrl_rows = []
            agg_ctrl = agg_pm.get(si_mk, {}).get("controlled_rows", [])
            agg_ctrl_mpp = {r.get("label", ""): r.get("avg_mpp", 0) for r in agg_ctrl}
            default_ctrl_mpp = agg_ctrl_mpp.get("Reg WR", 0)
            for pw_key, label in [("reg_wr", "Reg WR"), ("trueskill", "TrueSkill"),
                                   ("openskill", "OpenSkill")]:
                entries = ctrl_data.get(pw_key)
                if entries:
                    avg = _weighted_avg(entries)
                    if avg:
                        mpp = agg_ctrl_mpp.get(label, default_ctrl_mpp)
                        ctrl_rows.append({"method": f"ctrl_{pw_key}", "label": label,
                                         "avg_mpp": mpp, **avg})
            if si_mk in avg_per_model:
                avg_per_model[si_mk]["controlled_rows"] = ctrl_rows

        avg_within_model = {}
        for si_mk, method_data in avg_wm_accum.items():
            wm_rows = []
            agg_wm_rows = agg_wm.get(si_mk, {}).get("rows", [])
            agg_wm_mpp = {r.get("method", r.get("label", "")): r.get("avg_mpp", 0) for r in agg_wm_rows}
            default_wm_mpp = agg_wm_mpp.get("within_wr", agg_wm_mpp.get("Win Rate", 0))
            for method_key, label in [("within_wr", "Win Rate"), ("within_ts", "TrueSkill"),
                                       ("within_os", "OpenSkill")]:
                entries = method_data.get(method_key)
                if entries:
                    avg = _weighted_avg(entries)
                    if avg:
                        mpp = agg_wm_mpp.get(method_key, default_wm_mpp)
                        wm_rows.append({"method": method_key, "label": label,
                                        "avg_mpp": mpp, **avg})
            avg_within_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "rows": wm_rows}

        avg_pw_vs_si = {"per_model": avg_per_model, "within_model": avg_within_model}

        # --- Avg InterModel: per-category rho values, then weighted average ---
        avg_im_accum = {}  # {pair: {method: [(rho, n), ...]}}
        for cat in cats_in_data:
            cat_pids = {pid for pid, c in paper_categories.items() if c == cat}
            # Load OS cache for this category (for inter-model OS correlations)
            # Load OS cache for this category (batch pre-loaded)
            cat_im_os_cache = _os_cache_by_cat.get(cat)
            for i, m1 in enumerate(model_keys):
                for j, m2 in enumerate(model_keys):
                    if i >= j or m1 not in model_rankings or m2 not in model_rankings:
                        continue
                    pair = f"{_short(m1)} vs {_short(m2)}"
                    for method in ["reg_wr", "trueskill", "openskill"]:
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

    # --- Score-Pairwise Coherence ---
    coherence = await _compute_score_pairwise_coherence(category)

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
        "pw_match_agreement": si_result.pop("pw_match_agreement", {}) if si_result else {},
        "avg_agreement": dict(sorted(avg_agreement.items())) if avg_agreement else None,
        "scatter_data": scatter_data,
        "ts_scatter_data": ts_scatter_data,
        "os_scatter_data": os_scatter_data,
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
        "score_pairwise_coherence": coherence,
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
        "_id": 0, "paper_id": 1, "category": 1, "ts_score": 1,
        "comparisons": 1, "wins": 1, "win_rate": 1, "model_stats": 1, "si_ratings": 1,
    }):
        papers.append(doc)

    if len(papers) < 10:
        return {"status": "insufficient_data"}

    paper_categories = {p["paper_id"]: p.get("category") for p in papers}
    model_paper_stats, _, _, model_keys, _ = _extract_model_data(papers)
    wr_scores = {p["paper_id"]: p["win_rate"] for p in papers if p.get("win_rate") is not None and p.get("comparisons", 0) >= 3}
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

    # Collect actual PW match pairs per model-pair for controlled SI comparison
    pw_pairs_by_model = {}  # {model_key: set of (sorted_pair_tuple)}
    for m in all_matches:
        mu = m.get("model_used", {})
        raw_key = mu.get("_merged_key") or f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
        mk = _OPUS_MERGE.get(raw_key, raw_key).replace(".", "_")
        p1, p2 = m["paper1_id"], m["paper2_id"]
        pair = (p1, p2) if p1 < p2 else (p2, p1)
        pw_pairs_by_model.setdefault(mk, set()).add(pair)

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

    del pw_pairs_by_model

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
    """Previously injected cached OpenSkill 1p/3p/10p data into live analysis.
    Now a no-op — incremental OpenSkill ('openskill') is computed live."""
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

    # Controlled variant computed in compute_live_analysis where model_wr is available
    controlled_inter_model_si = {}

    # Export model_scores for use by controlled computation later
    _si_model_scores_export = model_scores

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
        "controlled_inter_model_si": controlled_inter_model_si,
        "_si_model_scores": _si_model_scores_export,
        "model_comparison": model_comparison,
        "available_models": [{"id": mk, "count": c} for mk, c in model_counts.items() if c >= 5],
    }


def _compute_pw_vs_si(papers, wr_scores, ts_scores, os1, os3, os10,
                       model_rankings, model_os, model_paper_stats, model_avg_mpp,
                       category, paper_categories, os_incr=None):
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
        "openskill": ("OpenSkill", os_incr or {}),
    }

    # Combined PW vs SI per model
    per_model = {}
    for si_mk, si_scores in si_maps.items():
        rows = []
        for pw_key in ["reg_wr", "trueskill", "openskill"]:
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
        "openskill": ("OpenSkill", {}),
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

    # Controlled OS (live) from single model's per-model OS
    sub_os = {}
    for p in pw_papers:
        mos = p.get("model_os", {})
        _rng.shuffle(mk_keys)
        for mk_inner in mk_keys:
            mk_inner_dot = mk_inner.replace("_", ".")
            os_data = mos.get(mk_inner) or mos.get(mk_inner_dot)
            if isinstance(os_data, dict) and os_data.get("mu"):
                sub_os[p["paper_id"]] = os_data["mu"]
                break
    controlled_pw["openskill"] = ("OpenSkill", sub_os)

    within_mpp = {}
    for si_mk in si_maps:
        mk_key = _MODEL_KEY_MAP.get(si_mk)
        if mk_key:
            mpps = [model_paper_stats.get(mk_key, {}).get(p["paper_id"], {}).get("total", 0) for p in pw_papers]
            within_mpp[si_mk] = round(float(np.mean([m for m in mpps if m > 0])), 1) if any(m > 0 for m in mpps) else 0

    for si_mk, si_scores in si_maps.items():
        ctrl_rows = []
        for pw_key in ["reg_wr", "trueskill", "openskill"]:
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
        # OS (live) — per-model incremental OpenSkill
        wm_os = {}
        for p in pw_papers:
            mos = p.get("model_os", {})
            os_data = mos.get(mk_key) or mos.get(dot_key)
            if isinstance(os_data, dict) and os_data.get("mu"):
                wm_os[p["paper_id"]] = os_data["mu"]
        row = _corr_row("within_os", "OpenSkill", wm_os, si_scores)
        if row:
            row["avg_mpp"] = within_mpp.get(si_mk, 0)
            wm_rows.append(row)

        n_matches = sum(model_paper_stats.get(mk_key, {}).get(p["paper_id"], {}).get("total", 0) for p in pw_papers)
        within_model[si_mk] = {"label": _SI_LABELS.get(si_mk, si_mk), "n_matches": n_matches,
                                "avg_mpp": within_mpp.get(si_mk, 0), "rows": wm_rows}

    return {"per_model": per_model, "within_model": within_model}



# ---------- Score-Pairwise Coherence (TrustJudge-inspired) ----------
# For each judge model, check how well its own single-item score s(A)-s(B)
# predicts its pairwise choice A>B. Bins by |score gap| show that a more
# internally coherent model has fewer reversals as the gap grows.

_JUDGE_TO_SI = {
    "openai/gpt-5.2": "gpt",
    "openai/gpt-5_2": "gpt",
    "gemini/gemini-3.1-pro-preview": "gemini",
    "gemini/gemini-3-pro-preview": "gemini",
    "anthropic/claude-opus-4-6": "claude",
    "anthropic/claude-opus-4-5-20251101": "claude",
}
_SI_SHORT = {"claude": "Claude Opus", "gpt": "GPT-5.2", "gemini": "Gemini Pro"}
_GAP_BINS = [
    (0.0, 0.5, "0–0.5"),
    (0.5, 1.0, "0.5–1"),
    (1.0, 1.5, "1–1.5"),
    (1.5, 2.0, "1.5–2"),
    (2.0, 3.0, "2–3"),
    (3.0, 99.0, "3+"),
]


async def _compute_score_pairwise_coherence(category=None):
    """For each judge model, pair its pairwise wins with its SI scores.
    Return per-bin reversal rates showing how coherence improves with score gap."""

    # 1. Load SI ratings from rankings
    si_query = {"si_ratings": {"$exists": True, "$ne": {}}}
    if category:
        si_query["category"] = category
    si_map = {}  # {paper_id: {si_key: score}}
    async for doc in db.rankings.find(si_query, {"_id": 0, "paper_id": 1, "si_ratings": 1}):
        pid = doc["paper_id"]
        si = doc.get("si_ratings", {})
        for mk in ("claude", "gpt", "gemini"):
            r = si.get(mk)
            if isinstance(r, dict) and r.get("score"):
                si_map.setdefault(pid, {})[mk] = r["score"]

    if len(si_map) < 20:
        return None

    # 2. Load completed matches
    match_query = {
        "completed": True, "failed": {"$ne": True},
        "mode": {"$exists": False}, "winner_id": {"$exists": True},
    }
    if category:
        match_query["primary_category"] = category

    # Accumulate per-si-model: list of (abs_gap, agreed)
    model_data = {}  # {si_key: [(abs_gap, agreed_bool), ...]}

    async for m in db.matches.find(match_query, {
        "_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1,
    }):
        mu = m.get("model_used", {})
        raw_key = f"{mu.get('provider', '')}/{mu.get('model', '')}"
        si_key = _JUDGE_TO_SI.get(raw_key)
        if not si_key:
            continue

        p1, p2, winner = m["paper1_id"], m["paper2_id"], m["winner_id"]
        s1 = si_map.get(p1, {}).get(si_key)
        s2 = si_map.get(p2, {}).get(si_key)
        if s1 is None or s2 is None:
            continue

        gap = abs(s1 - s2)
        # Did the higher-scored paper win?
        if s1 > s2:
            agreed = winner == p1
        elif s2 > s1:
            agreed = winner == p2
        else:
            # Exact tie in SI scores — skip (no prediction possible)
            continue

        model_data.setdefault(si_key, []).append((gap, agreed))

    if not model_data:
        return None

    # 3. Build per-model bin summaries
    models = {}
    for si_key, pairs in sorted(model_data.items()):
        total = len(pairs)
        overall_agree = sum(1 for _, a in pairs if a)

        bins = []
        for gap_min, gap_max, label in _GAP_BINS:
            in_bin = [(g, a) for g, a in pairs if gap_min <= g < gap_max]
            n = len(in_bin)
            if n == 0:
                bins.append({"label": label, "gap_min": gap_min, "gap_max": gap_max,
                             "n": 0, "agreement_rate": None, "reversal_rate": None})
                continue
            agree = sum(1 for _, a in in_bin if a)
            bins.append({
                "label": label,
                "gap_min": gap_min,
                "gap_max": gap_max,
                "n": n,
                "agreement_rate": round(agree / n, 4),
                "reversal_rate": round(1 - agree / n, 4),
            })

        models[si_key] = {
            "label": _SI_SHORT.get(si_key, si_key),
            "total_pairs": total,
            "overall_agreement": round(overall_agree / total, 4) if total else 0,
            "bins": bins,
        }

    return {"status": "ok", "models": models}
