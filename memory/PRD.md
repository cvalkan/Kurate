# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB > in-memory), event-driven refresh

## What's Been Implemented

### Session: Mar 20, 2026
- **Coin flip text clarification**: Updated "Is the coin flip conservative?" paragraph to clearly connect 73.5%/78.4% subset numbers to table's 50% assumption
- **Protein science CSV**: Regenerated with `human_individual_bt` column; documented structural coupling artifact (41% exact AI/H-Majority matches)
- **Paper-level rankings table**: Sortable per-paper view with 3 aggregation methods, highlighted coupling artifacts
- **Sidebar restructure**: Moved benchmark pages into dedicated "Judge Quality" section (separate from Experiments)
- **AI Ranking Quality page** (NEW): Standalone ranking quality using full independent data — AI BT from random matches vs comprehensive human ground truth. Per-dataset ρ with overlap percentages
- **BT Methodology clarification**: Human vs AI Benchmark uses controlled pairs (ρ=0.739); AI Ranking Quality uses full independent data (ρ=0.701)
- **Endpoint**: `/api/validation/ai-ranking-quality` — computes AI BT vs full human BT per dataset
- **Endpoint**: `/api/validation/dataset-rankings/{dataset_id}` — per-paper rankings with multiple aggregation methods

### Prior Sessions (summary)
- Production performance overhaul (static precomputation, event-driven caching)
- Dataset curation (UAI 2024, MIDL, PeerRead audits)
- Benchmark refinements (BT correlation, ceiling analysis, small-sample warnings)
- Bug fixes (badge fonts, data mismatches, UI crashes)
- Data export (CSV files for ICLR benchmark)

## Key Methodological Decisions
1. **Human vs AI Benchmark**: Uses CONTROLLED pairs (same pair set for AI and human) — fair head-to-head comparison
2. **AI Ranking Quality**: Uses FULL independent data — measures absolute ranking quality without sampling assumptions
3. **Thinking mode**: 1 judge per pair (round-robin across GPT-5.2, Claude Opus 4.6, Gemini 3 Pro)
4. **Validation data is STATIC**: Served from precomputed JSON files

## Prioritized Backlog

### P0
- Phase 3: Notification System (Resend email integration)

### P1
- Score ICLR-OT with Single-Item AI
- Update Summarizer Report Section 2 (use "full data" methodology)
- Run AI pipeline on UAI dataset

### P2
- Consolidate MIDL experiment pipeline
- Explore new validation datasets (NeurIPS, more ICLR topics)
- Add HTTP security headers
- Improve UI for tracking summary generation failures
- Continue refactoring leaderboard.py
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)

## Key Files
- `/app/backend/routers/human_ai_benchmark.py` — Main benchmark + AI ranking quality + dataset rankings endpoints
- `/app/frontend/src/pages/HumanAIBenchmarkSection.jsx` — Controlled benchmark UI + paper-level rankings
- `/app/frontend/src/pages/AIRankingQualitySection.jsx` — Standalone ranking quality UI
- `/app/frontend/src/pages/ValidationHubPage.jsx` — Sidebar navigation with Judge Quality section
- `/app/backend/data/precomputed/experiment_results.json` — Precomputed benchmark cache
- `/app/backend/data/protein_science_rankings.csv` — Export with 3 BT methods
