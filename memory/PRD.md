# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain an AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments and single-item assessments, with validation experiments and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn/UI + Recharts
- **LLMs**: Claude Opus 4.5-4.8, GPT-5.2/5.4/5.5, Gemini 3 Pro, DeepSeek v4-Pro, Kimi K2.6
- **Production DB**: MongoDB Atlas (BSON Date types, 30s read timeout)
- **Preview DB**: MongoDB localhost (string date types)

## What's Been Implemented

### OAI-PMH Migration (Jun 5, 2026)
- Fetched correct REST API dates for all 1,083 OAI papers with 2026 dates → `/app/oai_dates_results.jsonl`
- New migration script `/app/backend/scripts/fix_oai_dates.py` with Phase 1 (repair dates+versions) and Phase 2 (remove 1,956 ghost papers + all their matches/refs)
- Admin endpoint `POST /api/admin/fix-oai-dates?dry_run=true&phase=0|1|2`
- 6/6 pytest pass (`tests/test_oai_migration.py`)
- Endpoint verified via curl — correctly loads 1,083 corrections + 1,956 ghost IDs

### Admin Stats (SSOT, Jun 3)
- Scalable admin statistics with pre-aggregated `daily_stats` materialized views
- Durable drip seed, cursor pagination, exact reconciliation at scale
- ECharts canvas charts, BackfillBadge, SeedProgressBadge

### arXiv Pipeline (Jun 3)
- REST API with round-robin schedule (1 cat/tick, 24h cycle)
- Global throttle (3s), exponential backoff, per-category DB-persisted failure backoff
- arXiv Health indicator in Admin UI

### Other
- Archive dedup with unique index
- Logging consolidation
- System-vs-Category SSOT
- User behavior tracking
- Privacy policy (Swiss nDSG)

## Pending / Next
- **P0**: Deploy migration to production (Phase 1 → Phase 2 → rebuild daily_stats)
- **P1**: Add "last sealed / next reconcile check" timestamp to Admin UI
- **P1**: Extend prompt schema with 5 categorical metrics
- **P1**: SI source of truth consolidation
- **P2**: Semantic Search & "Papers Like This"
- **P2**: Live ChemRxiv Fetcher
- **P2**: Multiple Reviewer Personas
- **P2**: "Older" archive path inconsistency fix

## Known Issues
- TweetAPI returns 401 (external account limitation, blocked on user)
- `mode: {$exists: False}` still in leaderboard.py, ranking.py, scheduler.py

## Key Files
- `/app/oai_dates_results.jsonl` — 1,083 correct REST API dates
- `/app/oai_papers.json` — Full OAI paper inventory (3,039 papers)
- `/app/backend/scripts/fix_oai_dates.py` — Migration script
- `/app/backend/tests/test_oai_migration.py` — Migration tests
- `/app/backend/routers/admin.py` — Admin endpoint (line ~2758)
- `/app/backend/routers/admin2_stats.py` — SSOT stats
- `/app/backend/services/scheduler.py` — Fetch pipeline + scheduler
- `/app/backend/services/arxiv.py` — arXiv REST API client
