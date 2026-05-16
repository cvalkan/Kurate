# TrueSkill Sigma Convergence — Action Plan

## Problem

The convergence system uses Wilson CI to decide when a paper has "enough matches." Wilson treats each match as a coin flip and ignores opponent quality. This creates two failure modes:

1. **False convergence**: A paper with 9-0 record against weak opponents gets Wilson ±15% ("almost converged") but TrueSkill sigma ~6.5 (massive uncertainty). Wilson says stop matching; TrueSkill says this paper's rank is unreliable.

2. **Wasted matches**: Papers that already have low sigma keep getting matched because Wilson margin hasn't tightened enough. Meanwhile, truly uncertain papers wait.

## Current State (empirical, from production data)

| Metric | General (wilson ≤ 15%) | Top-K (wilson ≤ 10%) |
|---|---|---|
| Papers passing | 4056 / 4102 (99%) | 536 / 4102 (13%) |
| Median matches | 40 | 144 |
| Median ts_sigma | 1.537 | 1.001 |
| Max ts_sigma | 6.375 | 4.403 |
| Score uncertainty (max) | ±120 pts | ±88 pts |

The max sigma values show Wilson is letting deeply uncertain papers pass.

## Sigma-to-Score Translation

Score = (mu - 3*sigma) * 10 + 1200. One sigma unit = 30 Elo points in the displayed score.

| ts_sigma | Score ±2σ | Meaning |
|---|---|---|
| 0.85 | ±17 pts | Floor (maximum info extracted) |
| 1.0 | ±20 pts | Very confident |
| 1.5 | ±30 pts | Good — distinguishable from ±50pt neighbors |
| 2.0 | ±40 pts | Acceptable — broadly positioned |
| 3.0 | ±60 pts | Weak — overlaps 3+ rank positions |
| 6.0 | ±120 pts | Unreliable — rank essentially random |

## Proposed Thresholds

| Tier | Current (Wilson) | Proposed (TrueSkill sigma) | Expected median matches |
|---|---|---|---|
| General | wilson_margin ≤ 15% | ts_sigma ≤ 2.0 | ~40 (same as current) |
| Top-K | wilson_margin ≤ 10% | ts_sigma ≤ 1.5 | ~50-60 (down from 144) |

**Rationale for general ≤ 2.0**: Papers with 40 matches typically have sigma 1.5-1.6, so they pass easily. But papers with 100% win rate and only 1-9 matches (sigma 6+) are correctly flagged as unconverged. Net: same match budget, no false convergence.

**Rationale for top-K ≤ 1.5**: The current Wilson ≤10% requires ~144 median matches — far more than needed. Sigma 1.3 is typical at 50 matches with diverse opponents. A threshold of 1.5 is achievable in ~50-60 matches if opponents are informative, freeing match budget for other papers. Score uncertainty ±30 pts is tight enough to distinguish adjacent top-K papers.

## Code Changes

### 1. Config defaults (`core/config.py`)

Add new settings alongside existing ones (backward compatible):

```python
"sigma_target_general": 2.0,   # ts_sigma threshold for general papers
"sigma_target_topk": 1.5,      # ts_sigma threshold for top-K papers
```

### 2. Convergence check (`services/scheduler.py::_check_goals_met_impl`)

Replace Wilson margin checks with sigma checks:

```python
# Goal 1: General papers sigma ≤ sigma_target_general
sigma_target_general = settings.get("sigma_target_general", 2.0)
for e in entries:
    if e["paper_id"] in top_k_ids:
        continue
    if e.get("ts_sigma", 25/3) > sigma_target_general:
        return False

# Goal 2: Top-K papers sigma ≤ sigma_target_topk  
sigma_target_topk = settings.get("sigma_target_topk", 1.5)
for e in entries[:min(top_k, len(entries))]:
    if e.get("ts_sigma", 25/3) > sigma_target_topk:
        return False
```

Requires loading `ts_sigma` in the rankings query (add to projection).

### 3. Pair selection urgency (`services/scheduler.py::_select_pairs`)

Replace Wilson-based urgency with sigma-based:

```python
# Current:
def urgency(pid):
    target = ci_target if pid in top_k_ids else ci_target_general
    return max(0, margins[pid] - target) if comparisons[pid] > 0 else 999

# Proposed:
def urgency(pid):
    target = sigma_target_topk if pid in top_k_ids else sigma_target_general
    sigma = sigmas.get(pid, 25/3)
    return max(0, sigma - target) if comparisons[pid] > 0 else 999
```

Requires passing `ts_sigma` from rankings into the stats dict.

### 4. Displayed CI column (`services/ranking.py` + frontend)

Change the "95% CI" column from Wilson margin to sigma-derived:

```python
# Instead of wilson_margin_pct(wins, comparisons)
# Display: round(ts_sigma * 2 * TS_SCALE, 0) as "±X pts"
# Or keep as percentage: round(ts_sigma / ts_mu * 100, 1) if ts_mu > 0
```

Decision: keep displaying as `±X%` for continuity, but derive from sigma:
`ci_display = round(ts_sigma * 2 * TS_SCALE / max(score, 1) * 100, 1)`

Or simpler: just display raw sigma, relabel column to "σ".

### 5. No matchmaking structure changes needed

The opponent selection heuristic (prefer score-proximate established opponents) is already TrueSkill-aligned: matching near your mu is what shrinks sigma fastest. The calibration ratio (50% established, 50% needy) also stays. Only the urgency metric changes.

## Rollout Plan

1. **Phase A — Parallel logging** (no behavior change): Log `ts_sigma` alongside `wilson_margin` in the compare loop diagnostics. Verify sigma distributions match the analysis above on live data. Deploy and monitor for 1 week.

2. **Phase B — Switch convergence** (behavior change): Swap `_check_goals_met` to use sigma thresholds. Keep Wilson as a secondary diagnostic. Unpause and observe: do categories converge at similar match counts? Are 100% WR papers now being matched further?

3. **Phase C — Switch pair selection urgency**: Change `_select_pairs` urgency to sigma-based. This changes which papers get matched first. Monitor for any regression in per-category match efficiency.

4. **Phase D — Update display**: Change the CI column to reflect sigma. Update admin progress panel labels.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Sigma doesn't decrease for some papers | Low — only if all opponents are extreme mismatches | Calibration ratio ensures 50% of pairings are against established (score-proximate) opponents |
| More total matches needed | Low — thresholds calibrated to current medians | Admin can adjust sigma_target_* in settings panel |
| Top-K threshold too tight | Medium — 1.5 may require more matches than 50 for some categories | Start with 2.0 for both tiers, tighten top-K later based on data |
| Order dependence of TrueSkill | Known issue — sigma path depends on match order | Already mitigated by the 3-pass shuffled computation in full reranks |

## Expected Outcome

Same total match volume. Higher confidence in rankings. No more false convergence of 100% WR papers with few matches. Top-K papers reach confidence faster (fewer wasted matches against distant opponents).
