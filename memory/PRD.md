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

### Admin Stats v2 — REBUILT at /admin2 (RESOLVED the Atlas timeout)
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
