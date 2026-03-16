# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build a benchmark comparing LLM judges to human experts for scientific paper evaluation. The system validates AI pairwise comparison, single-item scoring, and tournament ranking methods against multiple peer review datasets.

## Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React (CRA) + Shadcn/UI
- **Key routers**: `human_ai_benchmark.py`, `unified_benchmark.py`, `validation.py`, `validation_imports.py`
- **Key pages**: `HumanAIBenchmarkSection.jsx`, `UnifiedBenchmarkSection.jsx`, `ValidationHubPage.jsx`

## What's Been Implemented

### Core Benchmark Suite
- Human vs. AI Benchmark with coin-flip correction, LOO baselines, difficulty stratification
- PW vs SI comparison pages (Comparative GT + Standalone GT)
- Validation Summary Report with Human vs. AI section
- Comprehensive footnote system explaining all methodological nuances

### Datasets
- **ICLR** (8 topic subsets, 469 papers): Primary comparative GT
- **PeerRead ACL 2017** (80 papers): Secondary comparative GT
- **UAI 2024** (100 papers): Newly added, 3 tiers but weak score separation (53.9% AI-H)
- **eLife** (multiple subsets): Standalone GT
- **MIDL** (100 papers, reimported): Standalone GT (Oral/Poster only, no rejects)
- **Others**: Qeios, ResearchHub, AlphaXiv, F1000

### Methodological Refinements (This Session)
- Small-sample † warnings (n < 30) on difficulty metrics
- Filled table blanks: tier accuracy per difficulty, kappa per difficulty
- Discovered and documented positional reviewer identity limitation across all datasets
- Corrected "equal-weighted" footnote: it's per-dataset reweighting, not per-reviewer
- Added ICLR rating scale info (6 values: 1,3,5,6,8,10) to footnotes
- Generated comprehensive ICLR dataset quality report

### Data Pipeline
- UAI import endpoint (`/api/validation/import-uai`)
- UAI pipeline script (`scripts/run_uai_pipeline.py`)
- Improved MIDL import with stratified tier sampling and proper reject detection

## Prioritized Backlog

### P0
- Phase 3: Notification System (Resend email integration)

### P1
- Score ICLR-OT with single-item AI (0/52 papers)
- Update Summarizer Report Section 2 (use "full data" methodology)

### P2
- Expand ICLR topic coverage (CV, RL, NLP — currently 8/45 topics)
- Evaluate UAI benchmark value (near-random results may not be worth keeping)
- Consolidate MIDL experiment pipeline
- Add HTTP security headers
- Refactor monolithic `leaderboard.py`
- Explore NeurIPS as additional comparative GT source

## Key Technical Decisions
- Coin-flip correction is the "fair" standard for pairwise agreement
- LOO baselines control for circularity in committee comparisons
- All reviewer identities are positional (documented in footnotes)
- UAI composite scores derived from mean of 5 aspect ratings (1-4 scale)

## Known Issues
- Mobile Twitter/X unfurling fails (blocked on Cloudflare config)
- Decision label casing inconsistency in ICLR data (e.g., "Accept (Poster)" vs "Accept (poster)")
- UAI's near-random benchmark results (53.9%) raise questions about dataset utility
