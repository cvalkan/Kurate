# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB > in-memory LRU), event-driven refresh
- **Background**: All loops event-driven (no polling). Compare loop wakes on data change, fetch loop sleeps until due.

## What's Been Implemented

### Session: Mar 25, 2026

**Model Analysis Dashboard Overhaul:**
- Replaced single `bt_vs_si` correlation box with multi-method PW-vs-SI comparison table
- Backend computes all 4 PW methods (Raw WR, Reg WR, BT, TrueSkill) vs averaged SI scores and per-model SI scores
- Added within-model PW vs SI correlations (Claude-only PW matches vs Claude SI, etc.)
- Added `pw_vs_claude_si` table: 8 rows comparing within-model and combined PW against Claude SI across all methods
- Added Inter-Model Agreement section with 3 side-by-side tables: PW Inter-Model, SI Inter-Model, PW vs Claude SI
- PW Inter-Model table shows per-model-pair correlations using all 4 scoring methods
- Removed SI Rating Calibration table from SiRatingSection
- TrueSkill confirmed as best PW estimator: Combined TrueSkill ρ=0.852 vs Claude SI

**Admin Ranking Method Switch:**
- Added `ranking_method` setting (reg_wr, bt, trueskill) to admin config
- Admin dropdown in Settings tab with tooltip
- Saving a new method triggers immediate full rerank of all categories via `/api/admin/rerank-all`
- `rerank_category_light` now checks the setting: reg_wr just re-sorts, bt/trueskill recomputes from all matches
- BT/TrueSkill scores normalized to Elo-like scale (mean 1200, sd 100) for consistent UI display

**Multi-Scoring Method Toggle (AI Ranking Quality):**
- Added scoring method toggle to AI Ranking Quality page: Normalized Win-Rate (default), Bradley-Terry, and TrueSkill
- Backend computes rankings with all 3 methods during precompute, stores in `by_method` field
- Frontend toggle switches all correlation metrics, summary cards, per-dataset table, and overlap table
- Bradley-Terry: MLE with regularization prior (prior_strength=2.0)
- TrueSkill: Microsoft TrueSkill Bayesian rating with 3-pass convergence, draw_probability=0

**Extended K% Overlap Tiers:**
- Added 40% and 50% tiers to the Top/Bottom K% Overlap table (previously 5%, 10%, 20%, 30%)
- Both AI Ranking Quality (filtered) and AI Ranking Quality (unfiltered) pages updated

**New Backend Functions:**
- `compute_bt_ranking_scores()` in `ranking.py` — thin wrapper around `calculate_bradley_terry`
- `compute_trueskill_ranking_scores()` in `ranking.py` — TrueSkill implementation with trueskill library

**Scoring Method Correlation (Model Analysis):**
- New `/api/scoring-method-correlation` endpoint computes Win-Rate vs BT vs TrueSkill on live tournament data
- Shows Spearman ρ and Kendall τ correlations, plus Top/Bottom K% agreement
- New `ScoringMethodSection` component on the Model Analysis page with loading spinner

**Global/Local Toggle Fix:**
- Fixed the global/local stats toggle on the tag-filtered leaderboard (was a no-op)
- Local mode now recomputes scores from only matches between papers in the filtered set
- Removed "(G)" suffix from column headers in global mode

### Session: Mar 23, 2026

**Performance & Observability:**
- Parallelized all 3 leaderboard endpoints (category, all-papers, tag-filtered) with asyncio.gather
- Match count cache with 5-min TTL, invalidated on data change
- New indexes: `rankings.added_at_-1`, `rankings.categories_score`
- Slow query threshold lowered from 1.0s to 200ms with per-column metadata
- End-of-cycle logging for fetch cycles, comparison rounds, archive/reconciliation
- Better error messages for failed fetch cycles (exception type shown)
- Fixed false-positive error logs (INFO with "FAILED" -> WARNING level)

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
- Updated all page descriptions explaining controlled pairs vs full data, and why rho values differ between pages
- Fixed hardcoded numbers in footnotes (PeerRead rho, ICLR range, tie rates)
- Added Pooled/Total aggregate row to AI Ranking Quality per-dataset table

**Data Integrity:**
- `rerank_category` now verifies win/loss counts via aggregation after every comparison round
- Paper detail endpoint auto-corrects stale rankings when viewed
- Fixed `collect_all` import in validation.py (was causing precompute failures)
- Fixed `async_track_mem` import in ranking.py
- Retry-and-repair-queue for incremental ranking updates
- Lightweight rank re-sorting after each comparison round

### Session: Mar 25, 2026 (continued)

**Opus 4.6 Thinking Accept/Reject Accuracy Test:**
- Built and ran single-item accept/reject prediction experiment following ReviewerToo (arXiv:2510.08867) methodology
- 100 ICLR 2025 papers (50 accept, 50 reject), 5-way categorical decisions grounded in ICLR 2025 Reviewer Guide
- Input: abstract + Opus 4.6 summary, Model: claude-opus-4-6 with thinking (budget_tokens=8000)
- **Binary accuracy: 76.0%** (96 papers completed, 4 budget-limited). Precision 72.5%, Recall 80.4%, F1 0.763
- **5-way accuracy: 62.5%** — model never predicts Oral/Spotlight, clusters to Poster/Reject
- Compared to paper's META agent (81.8%), human avg (83.9%), human top-1% (92.4%)
- Also computed pairwise cross-tier accuracy from existing data: **87.2%** (beats individual human reviewers at 82.9%)
- Key finding: pairwise comparison (87.2%) significantly easier than single-item absolute judgment (76.0%)
- Report: `/app/memory/OPUS46_ACCEPT_REJECT_REPORT.md`, data: `/app/tools/opus46_accept_reject_results.json`
- Script: `/app/tools/test_opus46_accept_reject.py`

**Dual-Score Incremental Architecture (Mar 25-26, 2026):**
- Replaced BT-dependent scoring with incremental TrueSkill + Win Rate dual-score system
- Each match now updates WR (O(1)), TrueSkill (O(1)), and per-model stats (O(1)) — no match history loading
- Rankings doc stores: `ts_mu`, `ts_sigma`, `ts_score`, `rank_wr`, `rank_ts`, `model_stats`
- All 3 Model Analysis endpoints now read from stored scores — zero match loading, <0.3s cold:
  - `scoring-method-correlation`: reads `score` + `ts_score` from rankings
  - `model-correlation`: reads `model_stats` + `model_ts` from rankings (single query)
  - `si-rating-stats`: reads `si_ratings` from rankings (moved from papers collection)
- Removed background analysis cache loop — endpoints fast enough without caching
- All endpoints pre-warmed by background refresh loop
- `rerank_category_light` simplified: just re-sorts from stored scores — no match loading
- Frontend WR/TrueSkill toggle on leaderboard (instant switch, no backend call)
- TrueSkill backfill removed from startup (admin triggers per-category via `/api/admin/backfill-trueskill`)
- BT preserved in validation/experiment pages only (untouched)

**Memory & Chart Fixes (Mar 25, 2026 continued):**
- Fixed gap_score=0 showing as "-" in leaderboard (falsy check bug in `leaderboard.py:694`)
- Fixed memory chart resolution switching: 7d/3d views now downsample via MongoDB `$dateTrunc` aggregation (30min/60min buckets) instead of truncating to most recent 3000 entries
- Optimized `_startup_seed_rankings`: now only reseeds categories with unranked papers instead of all 11 categories, saving ~200MB+ on restart
- Added `papers_total` tracking in scheduler to show "X fetched" vs "Y ready" in admin dashboard
- Improved admin status message: "Generating summaries (X/Y ready)" instead of "Insufficient papers"
- Added `minTickGap` to memory chart x-axis to prevent label overlap

### Prior Sessions
- DB-Backed Rankings (all 4 phases), production stability overhaul
- Dark mode, infinite scroll, GZip compression
- Dataset curation, benchmark refinements, methodology pages

## Key Files
- `/app/backend/routers/leaderboard.py` — Parallelized queries, match count cache, paper detail with auto-correction, PW-vs-SI multi-method correlations
- `/app/backend/routers/human_ai_benchmark.py` — Tie handling, multi-scoring methods, overlap tables, per-column tie fractions
- `/app/backend/services/ranking.py` — BT scores, TrueSkill scores, rerank_category with drift detection
- `/app/backend/services/scheduler.py` — Memory-optimized summary generation, end-of-cycle logging
- `/app/backend/services/precompute.py` — Precompute all experiment/validation/analysis caches
- `/app/frontend/src/pages/AIRankingQualitySection.jsx` — Scoring method toggle, 6-tier overlap table
- `/app/frontend/src/pages/HumanAIBenchmarkSection.jsx` — Per-column tie fractions, updated footnotes
- `/app/frontend/src/components/SiRatingSection.jsx` — PW-vs-SI multi-method comparison, per-model breakdown
- `/app/frontend/src/components/InterModelSection.jsx` — PW Inter-Model, SI Inter-Model tables
- `/app/frontend/src/pages/AdminPage.jsx` — Ranking Method dropdown, rerank-on-save

## Prioritized Backlog

### P0
- Monitor production memory with new architecture (repair queue + lightweight rank sorting)

### P1
- Phase 3: Notification System (Resend email integration)
- Update Summarizer Report Section 2
- Run AI summarization pipeline on UAI

### P2
- Server-side sorting (sort_by/sort_dir params) for leaderboard API
- Virtual scrolling (react-window) for mobile performance
- Hybrid page loading (200-row initial + background fetch)
- Convert admin scraper sync requests to async httpx
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)

### Backlog
- New validation datasets from OpenReview (NeurIPS, etc.)
- HTTP security headers
- UI for tracking summary generation failures
- Refactor monolithic leaderboard.py
- Explore Typesense integration
