# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain an AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments and single-item assessments, with validation experiments and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn/UI + Recharts + ECharts
- **LLMs**: Claude Opus 4.5-4.8, GPT-5.2/5.4/5.5, Gemini 3 Pro, DeepSeek v4-Pro, Kimi K2.6
- **Production DB**: MongoDB Atlas (BSON Date types, 30s read timeout)
- **Preview DB**: MongoDB localhost (string date types)

## What's Been Implemented

### Cache Warming on Follower Pods (Jun 10, 2026) — COMPLETE
- Moved `warm_on_startup()` to follower startup path (followers serve HTTP traffic)
- Preview and production follower pods now pre-warm leaderboard caches on boot
- Updated `cache_warmer.py` docstring to reflect two-tier architecture (full warm on startup, selective per-category warm on data changes)

### Cache Invalidation Fix + Scroll Prefetch (Jun 10, 2026) — COMPLETE
- Root cause of "sometimes fast, sometimes laggy" scroll: `notify_data_changed()` was calling `.clear()` on the entire response cache (~187 entries) every time any category got new matches (~every 60s). Only ~9 entries were re-warmed, leaving the rest cold.
- Fix: Surgical invalidation — only clears affected category + show_all entries. Other 44 categories stay cached.
- Scheduler calls (hot path) pass `category` → surgical. Admin calls (rare) pass `None` → full clear.
- Restored IntersectionObserver rootMargin from 200px to 400px (matching old design) for smoother scroll prefetch.

### Rank Refactoring (Jun 11, 2026) — COMPLETE
- Eliminated stored `rank`, `rank_ts`, `rank_wr` fields from all write paths
- Eliminated `score` field writes (was always identical to `ts_score`)
- Removed dead `_compute_ranks()` function
- All rank displays now use dynamic position-based ranking:
  - Leaderboard: position in MongoDB sort results
  - Paper detail: `count_documents({ts_score: {$gt: X}}) + 1`
  - Badges: same dynamic count_documents
- Frontend loadMore renumbers entries client-side for continuous ranks across pages
- `rerank_category_light` still runs (computes ts_score, wilson_margin, os_score) but no longer writes rank/score fields
- Tested: 6/6 backend tests pass, frontend visual verification confirms continuous ranks

### Skip Counts on Pagination (Jun 10, 2026) — COMPLETE
- Root cause of 5-9s loadMore: every scroll page re-ran `count_documents({$in: [45 cats]})` on Atlas — 9 seconds per call. The frontend already has counts from page 1.
- Fix: When `offset > 0` or `cursor` is provided, skip all count_documents calls and return `-1` for totals. Applied to both show_all and per-category paths.
- Result: show_all page 2 via offset went from 9s → 276ms.

### Tournament Column in Category Status (Jun 10, 2026) — COMPLETE
- Added `compare_activity` field to `/api/admin/category-status` response (from scheduler's live `current_activity`)
- Added `compare_paused` field
- Frontend shows: Comparing… (blue), Converged (green), Paused (orange), Exhausted (amber), or the raw activity text

### New Homepage (Jun 7, 2026) — COMPLETE
- Merged new homepage design from `new_homepage` branch
- `"/"` now renders the new homepage (TopNav, HeroPanel, RecentRankings, etc.)
- Original LeaderboardPage moved to `/leaderboard`

### OAI-PMH Migration (Jun 5-6, 2026) — COMPLETE
- Fixed dates + versioned arxiv_ids for 1,083 papers
- Removed 1,956 ghost papers + 24,842 matches
- Recomputed TrueSkill for 25 affected categories

### Code Audit & Cleanup (Jun 6, 2026)
- Archived 48 unused files to `/app/archive/`
- Removed stale filters, dead functions, duplicate logs

### Fetch Pipeline (Jun 3-6)
- REST API with round-robin schedule, 6h fetch interval
- Global 3s throttle, 429 fail-fast

### Admin Stats (SSOT, Jun 3)
- Scalable admin statistics with pre-aggregated daily_stats materialized views

## Pending / Next
- P1: Extend prompt schema with 5 categorical metrics (paper_type, contribution_type, code_available, research_maturity, comparative_result)
- P1: SI source of truth consolidation
- P1: Handle 9 dormant categories (reactivate or purge?)
- P2: admin.py / scheduler.py file splits (structural refactor)
- P2: "Older" archive path inconsistency fix
- P2: Add "last sealed / next reconcile check" timestamp to Admin UI
- P2: Semantic Search & "Papers Like This"
- P2: Live ChemRxiv Fetcher, Multiple Reviewer Personas

## Known Issues
- TweetAPI returns 401 (external account limitation)
- X (Twitter) TweetAPI 504 errors (blocked on user external dashboard)
- Compound indexes on matches still include `mode` field (harmless)

## Key Files
- `/app/backend/routers/admin.py` — Admin endpoints (~4,260 lines)
- `/app/backend/routers/leaderboard.py` — Leaderboard API (keyset pagination, caching)
- `/app/backend/services/scheduler.py` — Fetch + compare pipeline (~2,420 lines)
- `/app/backend/services/cache_warmer.py` — Leaderboard cache pre-warming
- `/app/frontend/src/hooks/useLeaderboardData.js` — Centralized leaderboard state/API hook
- `/app/frontend/src/components/leaderboard/RankedTable.jsx` — Shared table with IntersectionObserver scroll
- `/app/frontend/src/components/site/TopNav.jsx` — Primary site navigation

## Important Notes
- **Preview vs Production**: Separate MongoDB databases. Code changes in preview require deployment to take effect on production.
- **Frontend Build**: Preview serves STATIC build (`npx serve -s build`). Source changes do NOT hot-reload. Must run `yarn build` + restart frontend after code changes.
- **Caching**: No TTLs. Cache cleared via `notify_data_changed()`, re-warmed via `trigger_warm_category()`.
- **Startup**: Preview pods boot as FOLLOWERS. Both leader and follower now run `warm_on_startup()`.
