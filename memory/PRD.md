# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB > in-memory LRU), event-driven refresh
- **Background**: All loops event-driven (no polling). Compare loop wakes on data change, fetch loop sleeps until due.

## What's Been Implemented

### Session: Mar 20, 2026

**Methodology:**
- Fixed cross-tier pair selection bias in matchmaking (was excluding within-tier pairs)
- Created "AI Ranking Quality" page — standalone ranking using full independent data
- Restructured sidebar: "Validation" section with 4 benchmark pages
- Clarified coin flip text, added methodology banners to benchmark pages
- Paper-level rankings table with 3 aggregation methods
- Updated AI_PIPELINE_METHODOLOGY.md with full documentation

**Performance & Scalability:**
- Compare loop: fully event-driven (zero DB queries when idle)
- Fetch loop: sleep-until-due (configurable `fetch_interval_hours`, default 6h)
- `parallel_categories` admin setting (default 2, configurable 1-10)
- `collect_all()` replaces ALL 109 `.to_list(N≥5000)` — no truncation at any scale
- PDF parsing moved to thread pool (`run_in_executor`)
- Leaderboard data prep moved to thread pool
- All `compute_leaderboard` calls async (thread pool) across 30+ call sites
- Max event-loop block: 113ms (from 538ms)
- LRU eviction on all unbounded caches
- Compound index on `papers.categories + summaries`
- `/api/model-correlation` payload reduced 40% (865KB → 523KB)
- Pre-warmed: `/datasets`, `si-rating-stats`, analysis cache at startup

**Renamed:** SP Score → Gap Score across entire codebase

### Prior Sessions
- Production performance overhaul (static precomputation, event-driven caching)
- Dataset curation (UAI 2024, MIDL, PeerRead audits)
- Benchmark refinements (BT correlation, ceiling analysis, small-sample warnings)

## Key Files
- `/app/backend/server.py` — Startup, prewarming, deferred tasks
- `/app/backend/services/scheduler.py` — Event-driven fetch/compare loops
- `/app/backend/routers/leaderboard.py` — Cache refresh, analysis, archive loops
- `/app/backend/routers/human_ai_benchmark.py` — Controlled benchmark + AI ranking quality
- `/app/backend/routers/validation_utils.py` — `collect_all()`, shared caches
- `/app/backend/services/precompute.py` — JSON precomputation
- `/app/frontend/src/pages/AIRankingQualitySection.jsx` — Standalone ranking quality UI
- `/app/memory/ROADMAP.md` — Scaling notes, known bottlenecks, architecture decisions
- `/app/memory/AI_PIPELINE_METHODOLOGY.md` — Full methodology documentation

## Prioritized Backlog

### P0
- Phase 3: Notification System (Resend email integration)

### P1
- Run validation matches with corrected (unfiltered) pair selection
- Score ICLR-OT with Single-Item AI
- Update Summarizer Report Section 2

### P2
- Incremental BT updates for 100K+ scale (see ROADMAP.md)
- Convert admin scraper sync requests to async httpx (see ROADMAP.md)
- Run AI pipeline on UAI dataset
- Consolidate MIDL experiment pipeline
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)
