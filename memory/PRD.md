# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: Multi-layer (precomputed JSON > MongoDB > in-memory LRU), event-driven refresh
- **Background**: All loops event-driven (no polling). Compare loop wakes on data change, fetch loop sleeps until due.

## What's Been Implemented

### Session: Apr 5, 2026

**Bug Fix: Admin Dashboard Wrong Numbers for New Categories:**
- Fixed `_check_goals_met` in scheduler.py returning True when rankings empty but papers exist (new categories in summary phase)
- Fixed progress endpoint (`/api/admin/progress`) returning `total_papers: 0, goals_met: true` during summary phase. Now falls back to papers collection with `phase: "summaries"` indicator
- Fixed status endpoint `papers_total_fetched` always showing `0` — now falls back to `db.papers.count_documents`
- Added frontend "Generating summaries — X/Y papers ready" indicator for categories in summary phase

### Session: Apr 1, 2026

**Scheduler Storm Bug Fix & Match Pruning:**
- Removed "Rule 3" from `_select_pairs` which caused infinite repeat-match generation storms
- Built admin endpoints to prune same-pair duplicates and cap per-paper matches
- Added `/health` endpoint, fixed `analysis_store` DuplicateKey index issue
- Human vs AI SE Benchmark alignment (6,833 pairs, 42.9% tie rate)
- OpenSkill Integration (Thurstone-Mosteller 1-pass, 3-pass, 10-pass)
- Unified `/api/model-analysis` endpoint (consolidated 3 heavy endpoints)
- Admin cache removal, 10s/15s auto-polling on React Admin components
- Dead code cleanup (~1,576 lines of deprecated endpoints)

### Session: Mar 25-28, 2026

**Model Analysis & Dual-Score Architecture:**
- Multi-method PW-vs-SI comparison tables
- Incremental TrueSkill + Win Rate dual-score system
- BT/TrueSkill scores normalized to Elo-like scale
- Memory chart resolution fixes
- Dead code audit & removal (8 functions, 313 lines)
- `malloc_trim(0)` force_gc optimization

### Prior Sessions
- DB-Backed Rankings (all 4 phases), production stability overhaul
- Dark mode, infinite scroll, GZip compression
- Dataset curation, benchmark refinements, methodology pages
- Opus 4.6 accept/reject experiment (76% binary accuracy)

## Key Files
- `/app/backend/routers/admin.py` — Admin dashboard endpoints, progress/status
- `/app/backend/routers/leaderboard.py` — Parallelized queries, paper detail
- `/app/backend/services/scheduler.py` — Core tournament loop, summary generation
- `/app/backend/services/ranking.py` — TrueSkill & OpenSkill scoring
- `/app/backend/services/model_analysis.py` — Unified analysis computation
- `/app/frontend/src/components/AdminOverview.jsx` — Per-category admin dashboard

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

### Backlog
- New validation datasets from OpenReview
- HTTP security headers
- UI for tracking summary generation failures
- Explore Typesense integration
