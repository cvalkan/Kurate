# Incremental Model Analysis — Implementation Plan

## Goal
Model Analysis pages update live after every match (WR, TrueSkill, SI data), while OpenSkill rows remain cached and refresh on-demand via admin button.

## Current State
- Single `compute_model_analysis()` function computes everything from scratch (~2 min for large categories)
- Result cached as one document in `analysis_store`
- Stale until manually refreshed

## Proposed Architecture

### Two computation functions

**`compute_live_analysis(category)` — ~50-200ms, no match loading**
```
Input: rankings collection only (indexed reads)
Output: {
  models,              # from rankings.model_stats
  correlations,        # Spearman(model_wr_A, model_wr_B) — from rankings
  ts_correlations,     # Spearman(model_ts_A, model_ts_B) — from rankings  
  agreement,           # median-split agreement — from rankings
  scatter_data,        # model WR scatter points — from rankings
  scoring_method,      # WR vs TS correlation — from rankings.score + ts_score
  si_data,             # distributions, histograms, per-model — from rankings.si_ratings
  pw_vs_si,            # WR/TS rows only — from rankings + si_ratings
  avg_correlations,    # per-category weighted averages — from rankings
}
```

**`compute_openskill_analysis(category)` — ~1-3 min, loads all matches**
```
Input: matches collection (full replay)
Output: {
  os_global: {os1, os3, os10},     # global OpenSkill scores
  os_per_model: {model: {os1, os3, os10}},  # per-model OpenSkill
}
```

### Endpoint change

```python
@router.get("/model-analysis")
async def get_model_analysis(category):
    # Always compute live (fast)
    live = await compute_live_analysis(category)
    
    # Merge cached OpenSkill if available
    os_doc = await db.analysis_store.find_one(
        {"_type": "openskill-cache", "key": cat_key}
    )
    if os_doc:
        live = merge_openskill_into_live(live, os_doc)
        live["openskill_updated_at"] = os_doc.get("computed_at")
    else:
        live["openskill_updated_at"] = None
    
    return live
```

### What changes for each section

| Section | Before | After |
|---|---|---|
| Model cards | Cached | Live (from rankings.model_stats) |
| Rank Correlations (WR) | Cached | Live |
| Rank Correlations (TS) | Cached | Live |
| Pairwise Agreement | Cached | Live |
| Win Rate Scatter | Cached | Live |
| Scoring Method (WR vs TS) | Cached | Live |
| SI Distributions | Cached | Live |
| PW vs SI (WR, TS rows) | Cached | Live |
| Per-category averages (WR, TS) | Cached | Live |
| PW Inter-Model (OS columns) | Cached | Cached (from openskill-cache) |
| Scoring Method (OS columns) | Cached | Cached |
| PW vs SI (OS rows) | Cached | Cached |

### Merge logic

The live computation returns all tables with WR+TS data filled in. OpenSkill columns/rows are left as `null`. If an `openskill-cache` document exists, the merge function injects:

1. `openskill`, `openskill3`, `openskill10` columns into `pw_inter_model` rows
2. `openskill`, `openskill3`, `openskill10` into `scoring_method` table
3. OS-based rows into `pw_vs_si.per_model[mk].rows` and `pw_vs_si.within_model[mk].rows`

### OpenSkill cache lifecycle

- **Populated by**: "Refresh This Category" / "Refresh 'All Categories'" admin buttons
- **Stored in**: `analysis_store` with `_type: "openskill-cache"`
- **Never auto-cleared**: Same safeguards as current analysis cache
- **Frontend hint**: Show "OpenSkill: updated X ago" timestamp, or "not yet computed" if null

### Frontend changes

Minimal:
- Add small "OpenSkill last updated: 2h ago" label near OS columns
- OS columns show "—" if no cached data yet (already handled by null-safe rendering)
- No separate loading state needed — the page loads instantly with live data

### Steps

1. **Extract `compute_live_analysis()`** from current `compute_model_analysis()`
   - Copy phases 1, 3a, 3b (WR/TS only), 3c (WR/TS only), 3d, 3e, 3f (WR/TS only), 3g
   - Skip phase 2 (match loading + OpenSkill computation)
   - Skip OS columns in all tables
   - ~200 lines, mostly copy-paste with OS parts removed

2. **Extract `compute_openskill_analysis()`**
   - Phase 2 from current function (load matches, compute OS)
   - Return just the OS score dicts
   - ~50 lines

3. **Write `merge_openskill_into_live()`**
   - Inject OS scores into the live result's tables
   - ~40 lines

4. **Update endpoint** to call live + merge cached OS
   - Remove `analysis_store` read for the main document
   - Keep `analysis_store` for OS cache only
   - ~20 lines

5. **Update admin refresh buttons**
   - "Refresh This Category" → recomputes OS for that category
   - "Refresh 'All Categories'" → recomputes OS for __all__
   - Same as today, just writes to `openskill-cache` instead of full analysis

6. **Add `openskill_updated_at` to frontend**
   - Small label showing when OS was last computed
   - ~5 lines

### Effort
- Backend: ~3-4 hours
- Frontend: ~30 min
- Testing: ~1 hour

### Risk
- Low: The live computation reads indexed data only — no new DB patterns
- The merge is additive (inject OS into live) — if OS cache is missing, everything still works, just without OS columns
- No migration needed — existing `analysis_store` docs can be ignored (they'll be replaced by the new OS-only docs on first refresh)

### Result
- Model Analysis page loads in <500ms (instead of "Loading..." or "warming up")
- Data is always current for WR, TrueSkill, SI metrics
- OpenSkill rows update on admin refresh (same as today, but everything else is live)
