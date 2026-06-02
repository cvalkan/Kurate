# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain an AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments and single-item assessments, with validation experiments and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn/UI + Recharts
- **LLMs**: Claude Opus 4.5-4.8, GPT-5.2/5.4/5.5, Gemini 3 Pro, DeepSeek v4-Pro, Kimi K2.6
- **Production DB**: MongoDB Atlas (BSON Date types, 30s read timeout)
- **Preview DB**: MongoDB localhost (string date types)

## Latest Changes (Jun 2, 2026)

### FIX: production multi-pod backfill race + leader-only execution
- **Discovery (on prod)**: After redeploy, a forced `POST /backfill` completed with `failed_chunks:0` (IXSCAN fix eliminated Atlas timeouts ✅) but the guard flagged `reconciled:False` (daily 422,838 vs expected 568,069). Cause: the per-process `_ts_backfill_running` guard can't stop a cross-POD race — `POST /backfill` (LB-routed to any pod) ran concurrently with the leader's periodic loop, issuing conflicting per-day `$set`s.
- **Fix**: (1) Distributed MongoDB lease lock (`admin2_lock`) around `_run_backfill`/`_run_incremental_backfill` — only one pod rebuilds cluster-wide. (2) **Leader-only execution**: `_kick_backfill` no-ops on non-leaders; `POST /backfill` on a non-leader queues a `backfill_request` marker the leader honors within ~60s (loop now ticks 60s instead of 30min). `is_scheduler_leader()` added to scheduler. (3) Incremental recent-days self-heal (deletes+recomputes last 10 days; idempotent; doesn't touch all-time model totals). (4) Frontend `BackfillBadge` (green Reconciled / red Drift) wired to `backfill_status`.
- **Verified on preview**: leader gating works (`POST /backfill` → started:true,leader:true); reconciles 275,497 (`reconciled:True`); incremental idempotent; 28/28 pytest; lint clean; badge renders. NOT yet on prod — needs redeploy (then the leader auto-rebuilds cleanly).

### INVESTIGATION: cost/paper ($0.52 preview / $0.40 prod) vs expected $0.16
- Breakdown (preview clean): total $5,562 / 10,657 papers = $0.52/paper. Match $2,304 (25.9 matches/paper). Summary $3,258 = **3.43 model-summaries/paper** (each paper summarized by ~3 production models: claude-opus-4-6:thinking $1,530 + gemini $580 + gpt-5.2 $569 = $2,679, plus experimental models).
- Concrete mispricing bugs found: models NOT in `MODEL_PRICING` (deepseek-v4-pro, kimi-k2.6, claude-opus-4-7/4-8, gpt-5.5, and the non-model key `abstract_plus_summary`) default to the most expensive opus rate ($5/$25) → overcount (~$300 of $3,258). The $0.52→$0.16 gap, however, is dominated by whether all ~3 summaries/paper should be counted — a product decision pending user input.


### FIX: admin2 cold-rebuild match UNDERCOUNT on production (Atlas)
- **Symptom**: A cold-start reconciliation (clear admin2 collections + rebuild) reproduced summary_cost/summaries/registrations EXACTLY but matches differed (live $inc 275,497 → rebuild 209,458). Live $inc count == ground truth (`matches` completed&!failed) == 275,497, so the **backfill was undercounting** — a bug, not drift correction.
- **Root cause**: `_backfill_daily_stats_chunk` (in `routers/admin.py`) filtered matches on a *computed* `_day` field via `$expr` → forced a **COLLSCAN** (confirmed via explain). On Atlas (762K+ matches, 30s read timeout) chunks time out, get caught by `except`→logged warning→**silently skipped** → missing matches. Preview (local Mongo) never times out, so it reconciled there.
- **Fix**: Replaced the `$expr`-on-computed-substring filter with an index-eligible `$or` range on `created_at` (string bound for preview + UTC-datetime bound for prod BSON Date). Query is now **IXSCAN on `created_at_1`** → every chunk completes fast at any scale → no dropped chunks → exact reconciliation. Removed unused `date_range_filter` helper.
- **Verified**: explain IXSCAN (was COLLSCAN); cold rebuild (backend stopped to avoid cross-process race) deterministically gives daily_stats matches=275,497 == model_match_stats == ground truth, papers=10,657, summaries=36,517, costs reconcile; 16/16 pytest; live API via REACT_APP_BACKEND_URL returns total_matches 275,497 with match_models summing to it. Note: the variance seen mid-debug (257k/243k) was a TEST-ONLY cross-process race (standalone script + running scheduler both backfilling); prod has a single leader + in-process `_ts_backfill_running` guard, so no race.

### ADD: backfill completeness guard + failed-chunk retry (admin2)
- `_run_backfill` now builds the chunk ranges up front, and on any chunk exception does **one bounded retry** of only the failed ranges (instead of silently dropping them — the production undercount failure mode).
- **Completeness guard**: after persisting, compares the authoritative per-model match sum (`all_models`, immune to per-day `$set` overwrite) against the materialized `daily_stats` `_total` sum. Material divergence (>0.5%, tolerating live-`$inc` drift) or any failed chunk → logs an ERROR and writes a `daily_stats {_meta:"backfill_status"}` doc `{ts, expected_matches, daily_matches, failed_chunks, reconciled}`.
- Status is surfaced in `GET /api/admin2/stats-overview` as `backfill_status` (visible to monitoring/UI immediately, not hidden until the next ~12h self-heal). `_meta` docs are excluded from the read path (no `category` field).
- Verified: guard records `reconciled:true` (275,497==275,497, 0 failed chunks); lint clean; 28/28 pytest (admin2_stats + admin2_refactor); API exposes `backfill_status`.
- **Open honesty notes / follow-ups**: (a) NOT yet validated on Atlas — run `POST /api/admin2/backfill` post-deploy and check `backfill_status.reconciled`. (b) `_backfill_summary_costs` uses `$objectToArray` over `papers.summaries` (3–100KB text values) → wasteful memory on Atlas (uses allowDiskUse); should project keys before unwind. (c) papers/summaries chunk aggregations still use `$expr`-COLLSCAN (smaller, didn't time out) — apply same index-backed treatment for consistency. (d) P3: make periodic self-heal INCREMENTAL (last ~7 days only; past days are immutable) to drop the recurring O(N) full rebuild.



### Admin Stats consolidated into the dashboard "Statistics" tab (replaces old panel)
- The dashboard **Statistics** tab now renders the new scalable stats; the standalone `/admin2` route and "Stats v2" tab were **removed**. Old `/api/admin/timeseries` and `/api/admin/stats` endpoints **deleted** (Overview tab repointed to `/api/admin2/stats-overview`).
- **One source of truth**: a single backfill pass writes `daily_stats` + `model_match_stats` + `model_summary_stats`; the endpoint reads ONLY these (+ `daily_registrations`, `system_logs`). No leaderboard-cache dependency, no match/paper scans. Cards, panel headers, rows, and timeseries all reconcile by construction. Accurate pricing (real tracked tokens + per-model avg for untracked).
- **Large-data hardening**: added indexes — `daily_stats {category:1,date:1}` (read path now IXSCAN, was COLLSCAN), `model_match_stats {model:1}`, `model_summary_stats {model:1}`, `daily_registrations {date:1}`, `papers {added_at:1}`. Response cache (~45s). Precomputed user registrations (no users scan). Periodic leader-only `_admin2_stats_loop` (ensure_fresh every 30m, full self-heal ~12h) + `ensure_indexes` on startup.
- **Charts**: 4 time-series charts (Papers/Matches/Tokens/Cost, incl. stacked-by-category) switched to **ECharts canvas** (fast at scale). Memory chart moved to the **bottom** (full-width), Recharts animations disabled.
- Tested: 16/16 pytest (`tests/test_admin2_stats.py`), testing agent backend 28/28 + frontend 100% (iteration_66), endpoint ~0.27s.

### (prior) Admin Stats v2 rebuild
- New scalable admin statistics page at route `/admin2` (legacy `/admin/dashboard` Statistics tab untouched). Linked via a "Stats v2" tab next to "Statistics" in the admin dashboard.
- Backend: `routers/admin2_stats.py` — single endpoint `GET /api/admin2/stats-overview` reads ONLY from the pre-aggregated `daily_stats` materialized view + `model_match_stats` + leaderboard cache + small `users`/`system_logs` aggregations. Responds in ~0.35s; NEVER scans matches/papers. Also `POST /api/admin2/backfill` and `GET /api/admin2/memory?hours=`.
- Write-time O(1) `$inc` hooks in `scheduler.py` keep `daily_stats`/`model_match_stats` fresh on every match completion, paper add, and summary generation (with ACTUAL tokens).
- One-time bounded background backfill (`_run_backfill`, 7-day chunks, type-safe `$toString` for BSON Date vs string). Fixed the legacy resume bug that made per-model meta partial.
- ACCURATE cost pricing: real `summary_tokens`/match `tokens` where available, per-model tracked averages only for the ~24% untracked summaries. All three sources reconcile exactly: match_cost $2303.94 == match panel; summary_cost $3258.29 == summary panel.
- Frontend: `pages/Admin2StatsPage.jsx` — 5 summary cards, cost/paper-over-time, match/summary cost panels, memory chart (6h–7d), 2×2 timeseries grid (Cumulative/Daily × System/Category) + per-category table, user-registration chart, refresh.
- Tested: 16/16 pytest (`tests/test_admin2_stats.py`), testing agent frontend 100%, endpoint reconciliation verified.

### Admin Stats (legacy) — Ongoing Production Issue (superseded by /admin2)
- Statistics page shows empty/zero data on production despite working on preview
- Root cause: BSON Date vs string type mismatch between preview (strings) and production (Date objects)
- Multiple fix attempts: removed $strLenCP on text, added $toString wrappers, chunked backfill
- **Decision: Rebuild from scratch as /admin2 with principled architecture**
- Handoff document: `/app/memory/ADMIN2_STATS_REBUILD.md`

### Other Completed Work (Jun 1-2)
- 2×2+2 User Behavior Charts with visitor tracking middleware
- Privacy policy updated (Swiss nDSG)
- `max_initial_backlog` admin setting
- Warming-up bug fixed (stale setTimeout closure)
- Playwright + Selenium removed from requirements
- Tags endpoint fast fallback (rankings-only, no match scan)
- Leaderboard cache: parallel aggregations, removed $strLenCP on full_text
- Re-added 9 removed categories on production
- Spearman correlation analysis (Claude SI vs TrueSkill, 10K papers)

## Known Issues
- **Admin stats page broken on production** (empty data) — rebuild planned as /admin2
- TweetAPI returns 401 (external account limitation)
- `mode: {$exists: False}` still in leaderboard.py, ranking.py, scheduler.py

## Pending
- P0: Verify /admin2 on PRODUCTION (Atlas) — confirm no timeout & numbers populate (trigger POST /api/admin2/backfill once after deploy).
- P1: Extended prompt (5 categorical metrics)
- P1: Landing page merge from GitHub branch
- P1: SI source of truth consolidation
- P2: Semantic Search & "Papers Like This"
- P2: Clean remaining mode:{$exists:False} filters from leaderboard.py, ranking.py, scheduler.py
- P2: Multiple Reviewer Personas, Live ChemRxiv Fetcher
- P2 (optional): retire legacy /admin/dashboard Statistics tab once /admin2 validated on prod
