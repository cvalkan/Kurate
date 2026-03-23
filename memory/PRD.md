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

### Session: Mar 22, 2026 (Performance & Observability)

**Leaderboard Query Parallelization:**
- All 3 leaderboard endpoints (category, all-papers, tag-filtered) now use `asyncio.gather` for independent DB calls
- Reduced from ~7 sequential awaits to ~2 parallel batches
- Production `all_papers(recent)` dropped from 589ms → <200ms

**New Indexes:**
- `rankings.added_at_-1` — for unscoped "Most Recent" queries (all-papers view). Reduced anchor lookup from 8.6ms → 0.38ms
- `rankings.categories_score` — for tag-filtered views. Eliminated COLLSCAN on categories field

**Match Count Cache:**
- `_get_match_count(category)` caches match counts per category with 5-min TTL
- Invalidated via `notify_data_changed()` when new matches complete
- Eliminates 50-200ms COLLSCAN on 92K matches collection per request

**Enhanced Observability:**
- Slow query threshold lowered from 1.0s → 200ms with richer metadata (tags, entries, search, cursor)
- End-of-cycle logging for fetch cycles (start + done/failed with paper counts)
- End-of-cycle logging for comparison rounds (start + done with ok/fail counts)
- End-of-cycle logging for archive loop (archive snapshots + daily reconciliation)

**Memory Leak Fix in Fetch Cycles:**
- Root cause: `_generate_paper_summaries` loaded every paper's `full_text` (~55-80KB) + `summaries` (~28KB) just to check if summaries exist
- For cs.RO with ~1248 production papers: ~100MB loaded, 97% wasted on already-complete papers
- Fix: Two-phase approach — lightweight scan (id + summary keys only), then on-demand full load for papers needing generation
- Saves ~190MB per fetch rotation in production, preventing OOM kills every ~3 hours
- Added explicit GC after summary generation within each fetch cycle

### Session: Mar 22, 2026 (Earlier — Stability)

**ICLR-OT Scoring:**
- Scored all 52 iclr-ot papers with Single-Item AI (Claude Opus 4.6 thinking)
- Scores: range 3.5–8.2, mean 6.65

**DB-Backed Rankings (All 4 Phases Complete):**
- Phase 1: `rankings` collection (2135 entries, 10 categories), 5 indexes, incremental update hooks
- Phase 2: All leaderboard serving migrated to DB queries
- Phase 3: Removed in-memory leaderboard cache (~570MB freed)
- Phase 4: Daily reconciliation + manual endpoint
- Memory: O(1) regardless of paper count

**Admin Stats Bug Fix:**
- Fixed `admin.py` import of `_cache` from `leaderboard.py`

### Prior Sessions
- Production performance overhaul (static precomputation, event-driven caching)
- Dataset curation (UAI 2024, MIDL, PeerRead audits)
- Benchmark refinements (BT correlation, ceiling analysis, small-sample warnings)
- Dark mode, infinite scroll, GZip compression
- Methodology pages, cross-tier pair selection fix

## Key Files
- `/app/backend/server.py` — Startup, prewarming, staggered deferred tasks, index creation
- `/app/backend/services/scheduler.py` — Event-driven fetch/compare loops with GC, memory-optimized summary generation
- `/app/backend/routers/leaderboard.py` — DB-backed leaderboard serving, parallelized queries, match count cache, slow query logging
- `/app/backend/routers/admin.py` — Admin panel, system log endpoint
- `/app/backend/core/memlog.py` — Memory and performance logging to MongoDB
- `/app/frontend/src/pages/LeaderboardPage.jsx` — Main frontend page with infinite scroll
- `/app/memory/ROADMAP.md` — Scaling notes, known bottlenecks, architecture decisions

## Prioritized Backlog

### P0
- Monitor next production fetch rotation to confirm memory fix
- Phase 3: Notification System (Resend email integration)

### P1
- Run validation matches with corrected (unfiltered) pair selection
- Update Summarizer Report Section 2
- Run AI pipeline on UAI dataset

### P2
- Server-side sorting (sort_by/sort_dir params) for leaderboard API
- Virtual scrolling (react-window) for mobile performance at scale
- Hybrid page loading (200-row initial + background fetch)
- Convert admin scraper sync requests to async httpx
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)
