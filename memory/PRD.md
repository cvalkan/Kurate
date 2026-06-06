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

### OAI-PMH Migration (Jun 5-6, 2026) — COMPLETE
- Phase 1: Fixed dates + versioned arxiv_ids for 1,083 papers ✅
- Phase 2: Removed 1,956 ghost papers + 24,842 matches ✅
- Phase 3: Recomputed TrueSkill for 25 affected categories ✅
- Correct REST API dates fetched → `/app/oai_dates_results.jsonl`
- Admin endpoint: `POST /api/admin/fix-oai-dates?dry_run=true&phase=0|1|2|3&category=`

### Code Audit & Cleanup (Jun 6, 2026)
- Archived 48 unused files to `/app/archive/` (36 scripts, 6 frontend components, 7 docs)
- Removed 27 stale `mode: {$exists: False}` filters
- Removed dead functions: `_backfill_daily_stats_chunk`, `_get/_set_admin_cached`, `estimate_category`, `_collect_cursor_docs`
- Cleaned 18 stale tournament docs via `POST /api/admin/cleanup-stale-tournaments`
- Fixed duplicate category names in fetch_cycle logs
- Fixed duplicate failure entries in AdminLogs frontend
- 429 → fail-fast (no retry) in arxiv.py

### Fetch Pipeline (Jun 3-6)
- REST API with round-robin schedule, now at 6h fetch interval
- Global 3s throttle, 429 fail-fast (no retry, waits for next cycle)
- Per-category backoff keys cleaned up on startup

### Admin Stats (SSOT, Jun 3)
- Scalable admin statistics with pre-aggregated daily_stats materialized views
- Durable drip seed, cursor pagination, exact reconciliation at scale

## Active Scripts
- `fix_oai_dates.py` — OAI migration (3 phases)
- `backfill_archive_scores.py` — Archive score backfill
- `backfill_model_openskill.py` — OpenSkill backfill  
- `within_label_match_pipeline.py` — Within-label matching

## Pending / Next
- Deploy latest changes (log dedup, 429 fix, archived files)
- P1: Extend prompt schema with 5 categorical metrics
- P1: SI source of truth consolidation
- P2: admin.py / scheduler.py file splits (structural refactor)
- P2: "Older" archive path inconsistency fix
- P2: Semantic Search & "Papers Like This"
- P2: Live ChemRxiv Fetcher, Multiple Reviewer Personas

## Known Issues
- TweetAPI returns 401 (external account limitation)
- Compound indexes on matches still include `mode` field (harmless, drop on Atlas if desired)
- `_ADMIN_CACHE_TTLS` / `_invalidate_admin_cache` still present but cache is never read/written (cosmetic)

## Key Files
- `/app/backend/routers/admin.py` — Admin endpoints (4,173 lines)
- `/app/backend/routers/admin2_stats.py` — SSOT stats
- `/app/backend/services/scheduler.py` — Fetch + compare pipeline (2,406 lines)
- `/app/backend/services/arxiv.py` — arXiv REST API client
- `/app/backend/scripts/fix_oai_dates.py` — Migration script
- `/app/archive/` — Archived unused scripts, components, docs
