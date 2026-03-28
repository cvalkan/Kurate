# Dead Code Audit — Kurate.org Backend
Generated: 2026-03-28
Codebase: ~37K lines across 90 Python files

---

## 1. Write-Only MongoDB Collections

Collections written to but never read by any API endpoint.

### `ranking_snapshots` — CONFIRMED DEAD

- **744 documents, 2.4 MB storage**
- Written after every comparison round by `_store_ranking_snapshot` (loads ALL matches + runs BT)
- The ONLY read is `find_one` to get the last round number for auto-increment — self-referential
- No API endpoint, no frontend component, no router reads from it
- **Original intent**: track ranking stability round-over-round
- **What replaced it**: the convergence chart (`/api/convergence`) replays match history directly
- **Memory cost**: ~73 MB transient per round for cs.RO (22K match load + BT compute)
- **Action**: Remove `_store_ranking_snapshot` and stop writing. Collection can be dropped.

### `qeios_pairwise_extract` — POSSIBLY DEAD

- Written to by `qeios.py:588` (`insert_one`)
- Zero reads anywhere in the codebase
- Referenced in `qeios.py` router but only for writing
- Low priority: Qeios scraper runs rarely, minimal memory impact
- **Action**: Verify if this collection is consumed by an external tool. If not, remove writes.

### `gmail_oauth_states` — LOW RISK

- Written by `congrats.py:133`, read by `server.py:176`
- Part of Gmail OAuth flow for congrats emails
- Functional (OAuth state management) but the Gmail congrats flow may be underused
- **Action**: Keep. Functional.

---

## 2. Unused Functions in Hot-Path Files

Functions with zero call sites across the entire backend (excluding framework-invoked handlers).

### `leaderboard.py` (3 dead functions)

| Function | Line | Size | Purpose | Notes |
|---|---|---|---|---|
| `_apply_period_filter` | 54 | ~15 lines | Legacy period filter | Replaced by `_build_period_filter` which returns MongoDB query directly |
| `_apply_search` | 593 | ~10 lines | Legacy search filter | Search is now done via MongoDB `$regex` in the query, not post-filter |
| `_get_paper_si_rating` | 2192 | ~25 lines | Extract SI rating from paper | Inlined wherever needed; standalone function unused |

### `ranking.py` (2 dead functions)

| Function | Line | Size | Purpose | Notes |
|---|---|---|---|---|
| `calculate_bt_confidence_intervals` | 135 | ~115 lines | BT Fisher-information CIs | Legacy BT code. Not used after switch to incremental WR/TS |
| `compute_weighted_bt_async` | 128 | ~5 lines | Async wrapper for weighted BT | Only caller is `_compute_model_correlation_from_matches` which itself is only for non-standard modes |

### `llm.py` (1 dead function)

| Function | Line | Size | Purpose | Notes |
|---|---|---|---|---|
| `get_extraction_stats` | 504 | ~30 lines | Extraction stats for admin page | Was used by an admin endpoint that was removed |

### `scheduler.py` (2 dead functions)

| Function | Line | Size | Purpose | Notes |
|---|---|---|---|---|
| `_iter_cursor_batches` | 86 | ~10 lines | Batch cursor iteration | Defined but `_collect_cursor_docs` is used everywhere instead |
| `_re_escape` | 18 | ~3 lines | Regex escape for MongoDB | Never called |

**Total dead code in hot-path files: ~210 lines**

---

## 3. Legacy BT/Match-Loading Code Still Executing in Production Paths

The architecture moved to incremental TrueSkill + Win Rate with pre-stored scores in `rankings`. 
These are the **production hot-path** functions that still load full match history.

### Per-Round Match Loading (fires after every comparison round)

| Caller | What it loads | Memory cost (cs.RO) | Still needed? |
|---|---|---|---|
| `_check_goals_met` (scheduler.py:434) | ALL matches for category | ~48 MB | **NO** — Wilson margins are stored in `rankings` |
| `run_comparison_round` (scheduler.py:1026) | ALL matches for pair selection | ~53 MB | **YES** — needs match pairs to avoid repeats |
| `_store_ranking_snapshot` (scheduler.py:390) | ALL matches + BT compute | ~73 MB | **NO** — dead code (see Area 1) |
| `_compute_convergence` (leaderboard.py:2736) | ALL matches + BT × 40 steps | ~73 MB | **YES** but should be rate-limited (not per-round) |

### BT/Leaderboard Compute Calls by Category

| Context | File | Calls | Still needed? |
|---|---|---|---|
| **Convergence chart** | leaderboard.py:2776,2845 | `compute_leaderboard_async` ×40/call | YES — but rate-limit to every 10th round |
| **Tag-filtered local stats** | leaderboard.py:1067 | `compute_leaderboard` | YES — on-demand for tag filter with local mode |
| **Inter-model PW correlation** | leaderboard.py:1958,1961 | `compute_bt_ranking_scores`, `compute_trueskill_ranking_scores` | YES — but only for non-standard modes (legacy match-based path) |
| **Seed rankings** | ranking.py:558 | `compute_leaderboard` | YES — one-time at startup |
| **Ranking snapshot** | scheduler.py:415 | `compute_leaderboard_async` | **NO** — dead code |
| **Validation/benchmark pages** | validation.py, human_ai_benchmark.py, etc. | ~45 calls | YES — validation datasets use BT for human-vs-AI ranking comparison. These are **cached via precomputed JSON** and don't run in production hot path |
| **Summary bias analysis** | summary_bias.py | ~11 calls | YES — experimental analysis pages. Not hot path |

### Summary of Unnecessary Per-Round Match Loading

| Operation | Per-round cost | Can eliminate? |
|---|---|---|
| `_check_goals_met` | ~48 MB × 6 cats = 288 MB | YES → read from `rankings` collection |
| `_store_ranking_snapshot` | ~73 MB × 6 cats = 438 MB | YES → remove entirely (dead code) |
| `_recompute_convergence_bg` | ~73 MB × 6 cats = 438 MB | PARTIALLY → rate-limit to every 10th round |
| **Total eliminable** | **~1,100 MB transient allocs/cycle** | |

---

## 4. Unused/Unreferenced API Endpoints

### Likely Dead (no frontend reference, no known external caller)

These endpoints have no frontend reference and appear to be one-time admin tools
that were used during initial setup/migration and are no longer needed:

| Path | Purpose | Lines |
|---|---|---|
| `POST /api/admin/generate-summaries` | Manual summary generation trigger | admin.py:296 |
| `GET /api/admin/summary-gen-progress` | Summary gen progress polling | admin.py:432 |
| `POST /api/admin/dedup-papers` | Manual dedup trigger (automated at startup now) | admin.py:2166 |
| `POST /api/admin/regen-summaries` | Regenerate truncated summaries | admin.py:2335 |
| `GET /api/admin/regen-summaries/status` | Regen progress | admin.py:2329 |
| `GET /api/admin/background-tasks` | List background tasks | admin.py:2432 |
| `POST /api/admin/archive/snapshot` | Manual archive snapshot | admin.py:2457 |
| `POST /api/admin/archive/snapshot-all` | Snapshot all categories | admin.py:2472 |
| `POST /api/admin/archive/backfill` | Backfill historical archives | admin.py:2518 |
| `GET /api/badge/.../exists` | Badge existence check | badges.py:447 |
| `POST /api/pairwise/fetch-pairs` | Manual pairwise data fetch | pairwise.py:305 |
| `POST /api/pairwise/run-tournament` | Manual pairwise tournament | pairwise.py:613 |
| `POST /api/pairwise/reset` | Reset pairwise data | pairwise.py:837 |
| `POST /api/summarizer-ab/queue-batch` | Queue summarizer A/B test | validation_experiments.py:2287 |

### One-Time Import Endpoints (run once, never again)

These were used to import validation datasets. Data is already imported.
They remain functional but are never called in production:

| Path | Dataset | Lines |
|---|---|---|
| `POST /api/validation/import-iclr` | ICLR 2025 | validation_imports.py:39 |
| `POST /api/validation/import-elife` | eLife | validation_imports.py:191 |
| `POST /api/validation/import-midl` | MIDL | validation_imports.py:379 |
| `POST /api/validation/import-uai` | UAI | validation_imports.py:624 |
| `POST /api/validation/import-peerread` | PeerRead | validation_imports.py:869 |
| `POST /api/validation/import-f1000` | F1000Research | validation_imports.py:1004 |
| `POST /api/validation/seed` | Seed validation data | validation.py:4131 |
| `POST /api/validation/replay-tournament` | Replay tournament | validation.py:3831 |
| `POST /api/validation/run-cross-mode-fill` | Cross-mode fill | validation.py:4081 |

### F1000/ACMI Scraper Endpoints (one-time use)

| Path | Purpose | Lines |
|---|---|---|
| `POST /api/validation/scrape-f1000` | Scrape F1000 reviews | validation.py:4171 |
| `GET /api/validation/scrape-f1000/status` | Scrape status | validation.py:4183 |
| `POST /api/validation/enrich-f1000` | Enrich with PDFs | validation.py:4190 |
| `POST /api/validation/expand-f1000` | Expand dataset | validation.py:4201 |
| `POST /api/validation/rescrape-f1000-evals` | Rescrape evaluations | validation.py:4212 |
| `POST /api/validation/acmi/scrape` | ACMI scrape | validation.py:4920 |
| `GET /api/validation/acmi/scrape/status` | ACMI status | validation.py:4942 |
| `GET /api/validation/acmi/stats` | ACMI stats | validation.py:4948 |

### Qeios/SciPost Admin Endpoints (rarely used)

| Path | Purpose |
|---|---|
| `POST /api/qeios/pairwise-extract/stop` | Stop extraction |
| `GET /api/qeios/paper-data/stats` | Paper data stats |
| `POST /api/scipost/reset` | Reset SciPost data |

### Claim System Endpoints (feature built but incomplete frontend)

The claim/ORCID verification system has backend endpoints but several are
not wired to the frontend:

| Path | Purpose |
|---|---|
| `GET /api/claim/paper/{paper_id}` | Get paper claims |
| `GET /api/claim/my-orcid` | Get my ORCID verification |
| `GET /api/claim/my-claims` | Get my claims |

---

## Summary: Recommended Actions by Priority

### P0 — Immediate memory savings (~1.1 GB transient allocs eliminated)

1. **Remove `_store_ranking_snapshot`** and its caller in `run_comparison_round` line 1169
   - Dead code: writes to collection nobody reads
   - Saves: ~73 MB × 6 cats = 438 MB transient per cycle

2. **Rewrite `_check_goals_met` to use `rankings` collection**
   - Currently loads ALL matches; Wilson margins already stored in rankings
   - Saves: ~48 MB × 6 cats = 288 MB transient per cycle

3. **Rate-limit `_recompute_convergence_bg` to every 10th round**
   - Convergence curve barely changes with 20-100 new matches
   - Saves: ~73 MB × 6 cats × 90% = 394 MB transient per cycle

### P1 — Code cleanup (~210 lines)

4. Remove 8 dead functions from hot-path files
5. Remove `qeios_pairwise_extract` writes if collection is unused externally

### P2 — Endpoint cleanup (optional, reduces attack surface)

6. Consider gating one-time import endpoints behind a feature flag
7. Remove `badge_exists` endpoint if unused
8. Complete or remove incomplete claim/ORCID frontend wiring
