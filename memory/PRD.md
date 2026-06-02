# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain an AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments and single-item assessments, with validation experiments and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn/UI + Recharts
- **LLMs**: Claude Opus 4.5-4.8, GPT-5.2/5.4/5.5, Gemini 3 Pro, DeepSeek v4-Pro, Kimi K2.6
- **Scoring**: TrueSkill with quality-based matchmaking
- **Production DB**: MongoDB Atlas (remote)

## Latest Changes (Jun 2, 2026)

### Timeseries Statistics Redesign
- Replaced full-scan aggregation with incremental `daily_stats` collection
- First call: full backfill (~3s local, ~10-15s Atlas). Subsequent: only new days (~2s)
- Per-model pricing preserved via per-category indexed aggregation
- Removed stale `computation_cache` writes (was 677KB per save)
- Removed all `mode: {$exists: False}` from admin.py queries

### Admin User Behavior Charts
- 2×2 grid (DAU all/registered, Page Views, Visit Frequency) + side-by-side Category Popularity
- Aligned/Independent sort toggle for category comparison
- Visitor tracking middleware (IP hash, fire-and-forget)
- Privacy policy updated for Swiss nDSG compliance

### Frontend Performance
- By Category charts: top 10 + "Other" aggregation (reduces SVG from 27K to 6.6K elements)
- All chart data memoized with useMemo
- Playwright removed from requirements.txt (saves ~470MB / 15min per deploy)
- Warming-up bug fixed (stale setTimeout closure on category switch)

### Admin Settings
- `max_initial_backlog`: caps paper fetch for new categories (default: 200)

## DB Collections
- `papers`, `matches`, `rankings`, `users` (unchanged)
- `daily_stats`: {date, category, papers, matches, input_tokens, output_tokens, cost, summaries, summary_cost} — incremental timeseries cache
- `daily_visitors`: {date, all_ips[], auth_ips[], total_hits} — visitor tracking
- `category_views`: {date, category, views, auth_views}

## Known Issues
- TweetAPI returns 401 (external account limitation)
- `mode: {$exists: False}` still in leaderboard.py, ranking.py, scheduler.py (not blocking but should be cleaned)

## Pending
- P1: Extended prompt (5 categorical metrics)
- P1: Landing page merge from GitHub branch
- P1: SI source of truth consolidation
- P2: Semantic Search & "Papers Like This"
- P2: Clean remaining mode filters from non-admin files
- P2: Multiple Reviewer Personas, Live ChemRxiv Fetcher
