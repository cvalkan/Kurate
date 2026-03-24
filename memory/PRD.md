# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB > in-memory LRU), event-driven refresh
- **Background**: All loops event-driven (no polling). Compare loop wakes on data change, fetch loop sleeps until due.

## What's Been Implemented

### Session: Mar 23, 2026

**Performance & Observability:**
- Parallelized all 3 leaderboard endpoints (category, all-papers, tag-filtered) with asyncio.gather
- Match count cache with 5-min TTL, invalidated on data change
- New indexes: `rankings.added_at_-1`, `rankings.categories_score`
- Slow query threshold lowered from 1.0s to 200ms with per-column metadata
- End-of-cycle logging for fetch cycles, comparison rounds, archive/reconciliation
- Better error messages for failed fetch cycles (exception type shown)
- Fixed false-positive error logs (INFO with "FAILED" → WARNING level)

**Memory Leak Fix:**
- Root cause: `_generate_paper_summaries` loaded every paper's full_text (~55-80KB) just to check if summaries exist
- Fix: Two-phase scan — lightweight projection first, on-demand full load for papers needing generation
- Result: Fetch rotation growth dropped from +651MB to +57MB. No more OOM crashes.

**Tie Handling Overhaul (Human vs AI Benchmark):**
- All-expert-tie pairs now included in coin-flip extended controlled set (+917 pairs on unfiltered)
- Committee tier ties (same-tier pairs like Poster-Poster) treated as coin flips in unfiltered benchmark
- Per-column tie fractions displayed in every table cell with footnote explaining 3 tie types
- Consistent cf_rate computed for all 6 columns (was missing for AI/H vs Committee)
- Filtered page correctly shows 0% tier ties (no same-tier pairs by design)
- "Ties excluded" row shows "0% ties" everywhere for debugging clarity
- Updated all page descriptions explaining controlled pairs vs full data, and why ρ values differ between pages
- Fixed hardcoded numbers in footnotes (PeerRead rho, ICLR range, tie rates)
- Added Pooled/Total aggregate row to AI Ranking Quality per-dataset table

**Data Integrity:**
- `rerank_category` now verifies win/loss counts via aggregation after every comparison round (catches silently failed incremental updates)
- Paper detail endpoint auto-corrects stale rankings when viewed
- Fixed `collect_all` import in validation.py (was causing precompute failures)
- Fixed `async_track_mem` import in ranking.py

### Prior Sessions
- DB-Backed Rankings (all 4 phases), production stability overhaul
- Dark mode, infinite scroll, GZip compression
- Dataset curation, benchmark refinements, methodology pages

## Key Files
- `/app/backend/routers/leaderboard.py` — Parallelized queries, match count cache, paper detail with auto-correction
- `/app/backend/routers/human_ai_benchmark.py` — Tie handling, coin-flip extended controlled set, per-column tie fractions
- `/app/backend/services/ranking.py` — rerank_category with drift detection, compute_paper_score
- `/app/backend/services/scheduler.py` — Memory-optimized summary generation, end-of-cycle logging
- `/app/backend/core/memlog.py` — WARNING level for FAILED events
- `/app/frontend/src/pages/HumanAIBenchmarkSection.jsx` — Per-column tie fractions, updated footnotes
- `/app/frontend/src/pages/AIRankingQualitySection.jsx` — Aggregate row, updated descriptions

## Prioritized Backlog

### P0
- Deploy rankings drift fix + paper detail auto-correct
- Trigger precompute after deploy

### P1
- Phase 3: Notification System (Resend email integration)
- Update Summarizer Report Section 2

### P2
- Server-side sorting (sort_by/sort_dir params) for leaderboard API
- Virtual scrolling (react-window) for mobile performance
- Hybrid page loading (200-row initial + background fetch)
- Convert admin scraper sync requests to async httpx
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)
