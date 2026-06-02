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

### Admin Stats — Ongoing Production Issue
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
- P0: Admin2 stats rebuild (handoff to Opus 4.8)
- P1: Extended prompt (5 categorical metrics)
- P1: Landing page merge from GitHub branch
- P1: SI source of truth consolidation
- P2: Semantic Search & "Papers Like This"
- P2: Clean remaining mode filters from non-admin files
- P2: Multiple Reviewer Personas, Live ChemRxiv Fetcher
