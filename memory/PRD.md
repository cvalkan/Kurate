# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB analysis_store > in-memory LRU), event-driven refresh
- **Background**: Compare loop + fetch loop. Compare loop wakes on data change, fetch loop sleeps until due.

## What's Been Implemented

### Session: Apr 5, 2026

**Model Correlation Page Fixes:**
- Fixed GPT-5.2 missing from Model Correlation — MongoDB dot-in-key bug (gpt-5.2 stored as nested path). Normalized broken nested data on read + escape dots in future writes
- Fixed SI bar charts stale — `/api/si-rating-stats` endpoint was deleted in previous cleanup. Added per-model distributions + raw_histogram (91 bins, 0.1 steps) to unified `/api/model-analysis` endpoint
- Fixed "Average" tab crash — pearson_r undefined in avg_correlations → toFixed() crash. Added optional chaining + React error boundaries per section
- Fixed Full Resolution toggle — raw_histogram was never computed for main distributions. Now included for all views
- Frontend SI section now filters data client-side instead of fetching deleted endpoint

**Scheduler + Admin Dashboard Fixes:**
- Restored `_select_pairs` function (accidentally deleted, blocking ALL tournament matches on production)
- Fixed `_check_goals_met` returning True when rankings empty but papers exist (new categories stuck in idle)
- Fixed progress endpoint returning `total_papers: 0, goals_met: true` during summary phase
- Fixed status endpoint `papers_total_fetched` always showing 0
- Added frontend "Generating summaries — X/Y papers ready" indicator for summary phase

### Session: Apr 1, 2026

**Scheduler Storm Bug Fix & Match Pruning:**
- Removed "Rule 3" from `_select_pairs`, fixed stored-score misalignment
- Built admin endpoints for pruning same-pair duplicates
- OpenSkill Integration (Thurstone-Mosteller 1/3/10-pass)
- Unified `/api/model-analysis` endpoint (consolidated 3 heavy endpoints)
- Dead code cleanup (~1,576 lines)

### Prior Sessions
- Dual-Score Incremental Architecture (TrueSkill + Win Rate)
- DB-Backed Rankings, server-side pagination
- Memory optimizations, WiredTiger cache cap
- Dark mode, Human vs AI Benchmarks
- Dataset curation, benchmark refinements

## Key Files
- `/app/backend/services/model_analysis.py` — Unified model analysis computation, per-model SI distributions, broken-key normalizer
- `/app/backend/services/scheduler.py` — Tournament loop, _select_pairs, _check_goals_met
- `/app/backend/services/ranking.py` — TrueSkill scoring, model_stats dot-escape fix
- `/app/backend/routers/admin.py` — Admin dashboard endpoints, progress/status
- `/app/frontend/src/pages/CorrelationPage.jsx` — Model Analysis page with error boundaries
- `/app/frontend/src/components/SiRatingSection.jsx` — SI distributions with client-side model filtering
- `/app/frontend/src/components/CorrelationSection.jsx` — Rank correlations with null-safe rendering

## Known Issues
- MongoDB dot-in-key: Existing production data has GPT model_stats stored as nested paths. Read-side normalizer handles this. A backfill would fix the underlying data.
- Materials Science (cond-mat.mtrl-sci): 4 top-10 papers stuck at ~11% CI because all 49 unique pairs exhausted. Will heal as new papers are added.

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Email notification system (Resend integration)
- Resolve circular import chain (`core/auth.py` → `admin.py` → `precompute.py`)
- Migrate from `localStorage` to `httpOnly` cookies for auth tokens

### P2
- Wire up `AuthorClaimSection` or remove orphaned component
- Complete Gmail congrats flow or remove unwired endpoints
- Refactor monolithic `leaderboard.py` and `scheduler.py`
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare config)
- Backfill GPT model_stats from nested to flat keys on production

### Backlog
- New validation datasets from OpenReview
- HTTP security headers
- UI for tracking summary generation failures
- Explore Typesense integration
