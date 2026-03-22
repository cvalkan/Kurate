# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB > in-memory LRU), event-driven refresh
- **Background**: All loops event-driven (no polling). Compare loop wakes on data change, fetch loop sleeps until due.
- **Memory Management**: Startup tasks staggered sequentially, GC between heavy operations, large text fields stripped from cache after stats computation

## What's Been Implemented

### Session: Mar 22, 2026

**ICLR-OT Scoring:**
- Scored all 52 iclr-ot papers with Single-Item AI (Claude Opus 4.6 thinking)
- Scores: range 3.5–8.2, mean 6.65
- Now included in all benchmark endpoints (human-ai-benchmark, ai-ranking-quality, si-benchmark)

**DB-Backed Rankings (Phases 1+2 of Option 3):**
- Phase 1: Created `rankings` collection (2135 entries, 10 categories), 5 indexes, incremental update hooks in scheduler
- Phase 2: Migrated all 3 leaderboard serving paths (category, all-papers, tag-filtered) to DB queries
- Query latency: 0.7ms (category), 1.5ms (all papers), 3.4ms (search) — vs ~0ms from old cache
- 0 score mismatches with full recomputation after live match test
- Old in-memory cache still runs in parallel for non-leaderboard endpoints (tags, model-correlation, etc.)
- Root cause: Kubernetes OOM-killing the container when concurrent memory-intensive operations overlap
- Fix 1: `_startup_dedup` replaced with one-time hash backfill + unique index — no startup scan at all
- Fix 2: All background startup tasks now run sequentially with GC between each
- Fix 3: Summary stats now computed via MongoDB aggregation pipeline (zero summaries in Python memory)
- Fix 4: Leaderboard DB load excludes summaries entirely (87% per-paper reduction: 67KB → 8.6KB)
- Fix 5: GC calls after cache refresh, between fetch loop categories, between comparison batches
- Fix 6: Fetch cycle dedup uses `dedup_hash` index (16-byte hash vs full title+author strings)
- Result: Safe scaling from ~2-5K papers → ~50K papers in 8GB container (10-25x improvement)

**Admin Stats Bug Fix:**
- Fixed `admin.py` import of `_cache` from `leaderboard.py` — was using stale reference after cache swap
- Changed from `from routers.leaderboard import _cache as lb_cache` to `import routers.leaderboard as _lb_mod`
- Admin summary stats now correctly show live data (was silently returning 0)

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
- `collect_all()` replaces ALL 109 `.to_list(N>=5000)` — no truncation at any scale
- PDF parsing moved to thread pool (`run_in_executor`)
- Leaderboard data prep moved to thread pool
- All `compute_leaderboard` calls async (thread pool) across 30+ call sites
- Max event-loop block: 113ms (from 538ms)
- LRU eviction on all unbounded caches
- Compound index on `papers.categories + summaries`
- `/api/model-correlation` payload reduced 40% (865KB -> 523KB)
- Pre-warmed: `/datasets`, `si-rating-stats`, analysis cache at startup

**Renamed:** SP Score -> Gap Score across entire codebase

### Prior Sessions
- Production performance overhaul (static precomputation, event-driven caching)
- Dataset curation (UAI 2024, MIDL, PeerRead audits)
- Benchmark refinements (BT correlation, ceiling analysis, small-sample warnings)

## Key Files
- `/app/backend/server.py` — Startup, prewarming, staggered deferred tasks
- `/app/backend/services/scheduler.py` — Event-driven fetch/compare loops with GC
- `/app/backend/routers/leaderboard.py` — Cache refresh, summary stripping, analysis loops
- `/app/backend/routers/admin.py` — Admin panel, uses live cache reference
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
- ~~Score ICLR-OT with Single-Item AI~~ Done Mar 22, 2026 (52 papers, rho=0.66)
- Update Summarizer Report Section 2

### P2
- Incremental BT updates for 100K+ scale (see ROADMAP.md)
- Convert admin scraper sync requests to async httpx (see ROADMAP.md)
- Run AI pipeline on UAI dataset
- Consolidate MIDL experiment pipeline
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)
