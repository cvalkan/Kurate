# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build a benchmark comparing LLM judges to human experts for scientific paper evaluation. The system validates AI pairwise comparison, single-item scoring, and tournament ranking methods against multiple peer review datasets.

## Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React (CRA) + Shadcn/UI
- **Key routers**: `human_ai_benchmark.py`, `unified_benchmark.py`, `validation.py`, `validation_imports.py`, `validation_experiments.py`
- **Key pages**: `HumanAIBenchmarkSection.jsx`, `UnifiedBenchmarkSection.jsx`, `ValidationHubPage.jsx`, `ValidationReportPage.jsx`
- **Caching**: 3-layer system (precomputed JSON files → MongoDB persistent cache → in-memory with TTL)
- **Font system**: Inter font bundled in `/app/backend/fonts/` with FONTCONFIG_FILE fallback for badge rendering

## What's Been Implemented

### This Session (March 2026)

**Dataset Work:**
- UAI 2024 imported (100 papers, 3 tiers, composite scores from 5 aspect ratings 1-4)
- UAI pipeline completed (100 thinking summaries, 3,529 matches, 100 SI scores)
- UAI found to have near-random discrimination (53.9% AI-H) due to coarse 1-4 scale
- UAI removed from COMPARATIVE_GT_DATASETS but kept as standalone dataset page
- MIDL reimported (100 papers, Oral/Poster only — no rejects accessible on OpenReview)
- PeerRead added to tournament sidebar
- ICLR Dataset Quality Report generated (`/app/memory/ICLR_DATASET_REPORT.md`)

**Benchmark Improvements:**
- Small-sample † warnings (n < 30) on difficulty metrics
- Filled all table blanks: tier accuracy per difficulty, kappa per difficulty, tier accuracy on ties-excluded row
- Per-dataset breakdown table restructured: 3 color-coded groups × 4 columns (Individual/Majority/Committee)
- Ranking Correlation table: color-coded rows (sky/amber/rose), conditional bold on winners, all Kendall tau values computed
- Key finding highlighted: AI outperforms single human expert at predicting committee decisions (0.761 vs 0.666)
- Inter-Rater Concordance section removed (redundant with main table)

**Methodological Findings:**
- Positional reviewer identity discovered across ALL datasets (ICLR, PeerRead, MIDL, UAI)
- "Equal-weighted" metric reframed as "per-dataset reweighting" (footnote 9 updated)
- UAI composite scores analyzed: no individual aspect rescues the low discrimination
- Signal-to-noise ratio identified as the key differentiator (ICLR 26% CoV vs UAI 7.3%)
- PeerRead anomalies documented (BT 0.434, 2-reviewer bias, no tiers)
- ICLR rating scale documented (6 values: 1,3,5,6,8,10) in footnote 6

**Performance Optimization:**
- 3-layer caching system: precomputed JSON → MongoDB persistent → in-memory TTL
- Consolidated startup prewarm (`_prewarm_all_experiment_caches`)
- All validation endpoints: <1s after startup (was 2.5-71s cold)
- Admin timeseries: MongoDB cached with 1-hour background refresh (was 71s every 30s)
- Leaderboard cache refresh: event loop yields prevent request stalls
- Missing precomputed experiments added to JSON file (summarizer-ab, judge-comparison, single-item-scoring)

**UI/UX:**
- Descriptions updated to remove stale "eLife Neuro" references
- Archive hidden in tag/filter mode
- "Most Recent" changed to use `added_at` (last 48h) instead of single latest published day
- Badge font: Inter installed via bundled fonts with FONTCONFIG_FILE fallback
- Unified benchmark: graceful fallback when SI data missing from DB (reads from precomputed cache)

**Bug Fixes:**
- Fixed empty tie% cell (missing dash) on ties-excluded row
- Fixed reading_lists.py f-string syntax error from font name quotes
- Fixed unified-benchmark `si_total == 0` causing entire endpoint to return `no_data`
- Fixed startup prewarm race conditions (two competing functions → one consolidated)
- Fixed precomputed JSON loader returning early with partial data

## Prioritized Backlog

### P0
- Phase 3: Notification System (Resend email integration)

### P1
- Score ICLR-OT with single-item AI (0/52 papers in DB, exists in precomputed cache)
- Update Summarizer Report Section 2 to use "full data" methodology
- Download berenslab iclr26v1 parquet and import ICLR 2026 topics

### P2
- Expand ICLR topic coverage (CV, RL, NLP — currently 8/45 topics)
- Run SI scoring pipeline on production DB (currently only in precomputed JSON)
- Consolidate MIDL experiment pipeline
- Add HTTP security headers
- Continue refactoring `leaderboard.py`

## Known Issues
- Mobile Twitter/X unfurling fails (blocked on Cloudflare config)
- Decision label casing inconsistency in ICLR data
- UAI near-random results (53.9%) — dataset may not be worth keeping long-term
- PeerRead BT correlation anomaly (0.434) — documented but not resolved
- Production SI data only in precomputed JSON, not in DB (unified benchmark uses fallback)
