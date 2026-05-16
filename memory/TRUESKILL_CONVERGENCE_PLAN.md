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

All thresholds expressed as **±Elo points** (= ts_sigma × 2 × TS_SCALE, where TS_SCALE=10).
This is the same unit displayed in the UI and on scorecards.

| Tier | Current (Wilson %) | Proposed (±Elo pts) | Raw sigma | Expected median matches |
|---|---|---|---|---|
| General | wilson_margin ≤ 15% | ±50 pts | σ ≤ 2.5 | ~38 (same as current) |
| Top-K | wilson_margin ≤ 10% | ±40 pts | σ ≤ 2.0 | ~40-45 (down from 144) |

**Rationale for ±50 pts (general)**: Papers with 30-40 matches typically have sigma 1.5-1.7 (±30-34 pts) — they pass easily. The threshold catches only the true outliers: papers with extreme win rates and <10 matches (sigma 3-7, ±60-140 pts) that Wilson falsely declares converged. Across 21 active categories, this adds only ~3.5% more matches to established categories.

**Rationale for ±40 pts (top-K)**: The current Wilson ≤10% requires ~144 median matches. At ±40 pts, top-10 papers (which typically span 200+ pts) are clearly distinguishable. Achievable in ~40-45 matches, freeing significant match budget.

### Production impact estimate (gen≤2.5, topk≤2.0)

| Category | Papers | Existing matches | Unmet papers | Additional matches | % increase |
|---|---|---|---|---|---|
| cs.RO | 2417 | 56,991 | 238 | ~3,056 | 5.4% |
| cs.GT | 411 | 11,546 | 89 | ~1,565 | 13.6% |
| cs.CR | 1331 | 35,716 | 59 | ~1,063 | 3.0% |
| cs.AI | 715 | 17,288 | 13 | ~144 | 0.8% |
| quant-ph | 1326 | 31,597 | 31 | ~351 | 1.1% |
| **All 21 cats** | | **284,765** | | **~12,158** | **4.3%** |

Excluding 3 new IACR categories (0 existing matches): ~10,094 additional matches (3.5%).
Estimated scheduler runtime to full convergence: 6-10 hours.

## Code Changes

### 1. Config defaults (`core/config.py`)

Add new settings alongside existing ones (backward compatible):

```python
"sigma_target_general": 2.5,   # raw ts_sigma threshold for general papers
"sigma_target_topk": 2.0,      # raw ts_sigma threshold for top-K papers
```

Config stores raw sigma (the native TrueSkill unit). The admin panel displays these as ±Elo points (sigma × 2 × TS_SCALE) for readability, and converts back on save (÷ 20).

### 2. Convergence check (`services/scheduler.py::_check_goals_met_impl`)

Replace Wilson margin checks with raw sigma checks:

```python
# Goal 1: General papers sigma ≤ 2.5
sigma_target_general = settings.get("sigma_target_general", 2.5)
for e in entries:
    if e["paper_id"] in top_k_ids:
        continue
    if e.get("ts_sigma", 25/3) > sigma_target_general:
        return False

# Goal 2: Top-K papers sigma ≤ 2.0
sigma_target_topk = settings.get("sigma_target_topk", 2.0)
for e in entries[:min(top_k, len(entries))]:
    if e.get("ts_sigma", 25/3) > sigma_target_topk:
        return False
```

Convergence uses raw sigma — no Elo conversion. This keeps thresholds independent of TS_SCALE.

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

Change the "95% CI" column from Wilson percentage to ±Elo points:

Backend: serve `ts_ci_elo = round(ts_sigma * 2 * TS_SCALE)` in the ranking response.

Frontend (`LeaderboardTable.jsx`): Display `±{ts_ci_elo}` instead of `±{wilson_margin}%`.
The column header stays "95% CI" but the tooltip updates to explain ±Elo points.
This matches the scorecard format users already see.

### 5. No matchmaking structure changes needed

The opponent selection heuristic (prefer score-proximate established opponents) is already TrueSkill-aligned: matching near your mu is what shrinks sigma fastest. The calibration ratio (50% established, 50% needy) also stays. Only the urgency metric changes.

## Rollout Plan

1. ~~**Phase A — Parallel logging**~~ SKIPPED — empirical analysis already validated sigma distributions.

2. **Phase B — Switch convergence + pair selection + display** (DONE): All three shipped together since thresholds are conservative (gen≤2.5, topk≤2.0) and the changes are tested end-to-end.

3. **Phase C — Monitor after unpause**: After deploying to production and unpausing, monitor:
   - Do categories converge at similar match counts?
   - Are 100% WR papers now being matched further?
   - Admin progress panel shows accurate ±Elo labels.

4. **Phase D — Tighten thresholds** (future): If ranking stability warrants it, tighten to gen≤2.0, topk≤1.5 via admin settings panel.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Sigma doesn't decrease for some papers | Low — only if all opponents are extreme mismatches | Calibration ratio ensures 50% of pairings are against established (score-proximate) opponents |
| More total matches needed | Low — thresholds calibrated to current medians | Admin can adjust sigma_target_* in settings panel |
| Top-K threshold too tight | Low — 2.0 is achievable in ~40-45 matches | Tighten to 1.5 later if ranking stability warrants it |
| Order dependence of TrueSkill | Known issue — sigma path depends on match order | Already mitigated by the 3-pass shuffled computation in full reranks |

## Expected Outcome

Same total match volume. Higher confidence in rankings. No more false convergence of 100% WR papers with few matches. Top-K papers reach confidence faster (fewer wasted matches against distant opponents).
