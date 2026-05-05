# Scoring Simplification — Action Plan

## Goal
One canonical scoring method (TrueSkill) for the live system. Remove regularized win-rate scoring from the live pipeline. Preserve per-model TrueSkill and OpenSkill for the correlation page.

## Current State (per match, `update_rankings_for_match`)

| Step | What | DB writes | Used by |
|------|------|-----------|---------|
| 1 | Regularized WR score + per-model win stats | `score`, `ci`, `win_rate`, `model_stats.*` | `win_rate` displayed; `score`/`ci` not displayed |
| 2 | TrueSkill global | `ts_mu`, `ts_sigma` | Leaderboard score + rank |
| 3 | TrueSkill per-model | `model_ts.{key}.mu/sigma` | Correlation page |
| 4 | OpenSkill global | `os_mu`, `os_sigma` | Nothing displayed |
| 5 | OpenSkill per-model | `model_os.{key}.mu/sigma` | Correlation page |

And `rerank_category_light` (after each compare round):

| Computation | Used by | Status |
|-------------|---------|--------|
| `ts_score` from `ts_mu`/`ts_sigma` | Leaderboard score | Keep |
| `rank_wr` from WR score | Nothing | Remove |
| `rank_ts` from `ts_score` | Leaderboard rank | Keep → rename to `rank` |
| `os_score` from `os_mu`/`os_sigma` | Nothing displayed | Remove |
| `rank_os` from `os_score` | Nothing | Remove |
| `gap_wr` from WR percentile | Nothing | Remove |
| `gap_ts` from TS percentile → `gap_score` | Leaderboard gap | Keep |

## Changes

### Phase 1: `update_rankings_for_match` (per-match incremental)

**Step 1 — Simplify:**
- Keep: increment `wins`/`losses`/`comparisons`, compute `win_rate`, increment `model_stats.*`
- Remove: `compute_paper_score` call (regularized WR `score` + `ci` computation)
- `win_rate` is still needed (displayed in its own column), just compute it inline: `round(100 * wins / comparisons, 1)`

**Step 2 — Keep as-is:** TrueSkill global update

**Step 3 — Keep as-is:** TrueSkill per-model update (used by correlation page)

**Step 4 — Remove entirely:** OpenSkill global update (not displayed, per-model covers correlation page)

**Step 5 — Keep as-is:** OpenSkill per-model update (used by correlation page)

**Fix:** Log warning + queue repair on TrueSkill CAS failure (currently silent `pass`)

**Fix:** `unique_opponents` — query actual opponent set instead of blind increment

### Phase 2: `rerank_category_light` (post-round bulk rerank)

- Remove: `rank_wr`, `score` (WR) computation
- Remove: `os_score`, `os_sigma_map`, `rank_os` computation  
- Remove: `gap_wr` computation
- Remove: `_compute_gap_scores` function (dual WR/TS gap with `scipy.rankdata`) — replaced by single `_recompute_gap_scores` in scheduler (TS-only, index-based percentile)
- Rename: `rank_ts` → `rank` (TS is the canonical rank)
- **Fix:** Eliminate dual gap computation paths. Currently `_compute_gap_scores` (in `rerank_category_light`) and `_recompute_gap_scores` (in scheduler post-round) BOTH write `gap_score` with different methodologies (`scipy.rankdata` vs index-based percentile). Keep only `_recompute_gap_scores` as the single source.

### Phase 3: `insert_ranking_for_paper` (new paper entry)

- Remove: `score`, `ci` fields (WR-based)
- Keep: `ts_mu=25.0`, `ts_sigma=25/3`, `ts_score=1200`, `rank=0`
- Keep: `wins=0`, `losses=0`, `comparisons=0`, `win_rate=0`

### Phase 4: `seed_rankings` (full reseed from scratch)

- Replace `compute_leaderboard` (regularized WR) with `compute_leaderboard_trueskill`
- Single gap computation from TS percentiles

### Phase 5: Leaderboard API response

- Return `ts_score` as `score`, `rank_ts` as `rank`
- Stop returning `os_score`, `rank_wr`, `rank_os`, `gap_score_ts` 
- Compute CI server-side: `ci = round(1.96 * ts_sigma * TS_SCALE)`
- Keep returning `win_rate` (displayed in its own column)

### Phase 6: Frontend cleanup

- Remove `isTS`/`isOS` branching from `LeaderboardTable.jsx`
- `getScore` → `p.score` (server now returns TS score as `score`)
- `getRank` → `p.rank` (server now returns TS rank as `rank`)
- `getWilsonMargin` → `p.ci` (server computes CI)
- Remove `TS_SCALE` constant from frontend
- Remove `scoringMethod` state from `LeaderboardPage.jsx` (already hardcoded to "ts")

### Phase 7: Delete dead code

- `compute_paper_score` function (regularized WR incremental scoring)
- `_compute_ranks` function (dual WR/TS ranking)
- `_compute_gap_scores` function (dual WR/TS gap with `scipy.rankdata` — replaced by `_recompute_gap_scores`)
- `OS_SCALE` constant from live pipeline
- OpenSkill imports from `rerank_category_light`

### Bugs fixed by this plan

| Bug | Current behavior | Fix |
|-----|-----------------|-----|
| `unique_opponents` over-counted | Incremented by 1 on every match, even rematches | Query actual opponent set from DB |
| TrueSkill CAS failure swallowed | `except Exception: pass` — lost TS updates, no logging | Log warning + queue for repair |
| Dual gap computation paths | `_compute_gap_scores` (in rerank, uses `scipy.rankdata`) and `_recompute_gap_scores` (in scheduler, uses index-based percentile) both write `gap_score` with different methods | Single path: `_recompute_gap_scores` only |
| Regularized WR prior mismatch | `compute_paper_score` uses prior=0.5, `compute_leaderboard` uses prior=2.0 | Removed — `compute_paper_score` deleted |

## NOT touched (preserved for validation/analysis)

- `compute_leaderboard` (regularized WR) — used by validation experiments
- `compute_leaderboard_trueskill` — used by DeFi tournament script
- `compute_leaderboard_async` — used by judge comparison experiment
- OpenSkill model imports in validation/correlation code
- `model_ts` and `model_os` per-model data — used by correlation page

## User-facing impact

| Area | Impact | Severity |
|------|--------|----------|
| Leaderboard ranks | **No change** — already displaying TS ranks via `rank_ts` field | None |
| Leaderboard scores | **No change** — already displaying `ts_score` | None |
| CI column | Units change from Wilson % → TrueSkill score points (e.g., "15%" → "±42") | Medium — update tooltips |
| Archive discontinuity | Old archives store WR scores; new archives will store TS scores | Low — already exists from when TS was adopted |
| Correlation page | `os_score` currently read from rankings; after removal, compute inline from `os_mu`/`os_sigma` in `model_analysis.py` | Low — 2-line fix, same values |
| Validation/experiments | **No change** — standalone functions preserved | None |
| External API consumers | `score` field changes from WR to TS value; `rank` changes from WR to TS rank | Medium — document |
| Convergence goals | **No change** — Wilson CI for convergence is independent of display scoring | None |

## Correlation page fix

`model_analysis.py` reads `os_score` from rankings (lines 208, 455, 551). After removing `os_score` from `rerank_category_light`, compute it inline from `os_mu`/`os_sigma` (still maintained by Step 5):

```python
# Replace:
os_scores = {p["paper_id"]: p["os_score"] for p in papers if p.get("os_score") is not None}
# With:
os_scores = {p["paper_id"]: round((p.get("os_mu", 25) - 3 * p.get("os_sigma", 25/3)) * 15.0 + 1200)
             for p in papers if p.get("os_mu") is not None}
```

Same values, derived from raw mu/sigma instead of a pre-computed field.

## DB cleanup (optional, not blocking)

Old fields become dead data. Can be cleaned up later with:
```
db.rankings.updateMany({}, {$unset: {"os_score": "", "rank_wr": "", "rank_os": "", "gap_score_ts": ""}})
```

## Testing

After each phase, run the rating & gap test suite on preview. Verify:
1. Leaderboard renders correctly with scores, ranks, CI, gaps
2. Paper pages show correct scorecard
3. Correlation page still works
4. Convergence goals still function
5. No regression in match processing speed

## Estimated impact

- Per-match DB writes: ~10+ → ~6 (40% reduction)  
- `rerank_category_light` computations: 6 → 3 (50% reduction)
- Code removed: ~200 lines from ranking.py
- Response payload: ~30% smaller (fewer redundant fields)
