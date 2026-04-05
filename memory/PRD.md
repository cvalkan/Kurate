# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, precomputed JSON cache system, event-driven background tasks
- **Frontend**: React, served as compiled build
- **Caching**: analysis_store (MongoDB, cleared only via admin buttons), in-memory LRU for stats
- **Background**: Compare loop + fetch loop. Compare loop wakes on data change, fetch loop sleeps until due.

## What's Been Implemented

### Session: Apr 5, 2026

**Critical Fixes:**
- Restored `_select_pairs` function (accidentally deleted, blocked ALL tournament matches)
- Fixed GPT-5.2 missing from Model Correlation — MongoDB dot-in-key bug, normalizer now merges flat+nested keys
- Fixed "Average" tab crash — optional chaining + React error boundaries per section

**Admin Dashboard Overhaul:**
- Removed duplicate precomputed-cache code path in progress endpoint (single source of truth from DB)
- Fixed `_check_goals_met` false positive for new categories in summary phase
- Redesigned Paper Ingestion numbers: consistent X/Y downloaded, X/Y summarized
- Per-category fetch button state (no more global "Fetching..." across all tabs)
- Pair exhaustion amber notice for stalled tournaments
- Date/time on Recent Comparisons
- Title fallback to papers collection

**Model Analysis:**
- Full resolution SI bar charts (91 bins, 0.1 steps) for main and per-model
- SI model tab switching via client-side filtering (removed dead endpoint)
- "Refresh This Category" + "Refresh 'All Categories'" buttons in own section
- Cache clear logging (WARNING level)

**Scaling:**
- DB-backed pair dedup: `dedup_pair` field + compound index, `_select_pairs` async with indexed queries
- O(100) memory per round instead of O(all_matches). Scales to 100K+ papers.
- One-time migration backfills existing matches

**Code Quality:**
- Shared `get_matchable_paper_ids()` — single source of truth, replaces 3 duplicates
- Removed dead code: `_elo_ci`, `_get_admin_sessions`, `_find_truncated_summaries_sync`, unused imports
- Status endpoint match counts always from DB (removed scheduler cache shortcut)

**Safeguards:**
- Startup no longer drops analysis_store indexes or auto-clears cache
- Removed `_ANALYSIS_STORE_VERSION` auto-clear — only admin buttons can clear
- Confirmation removed from single-category refresh (safe), kept for full clear

### Prior Sessions
- Scheduler storm fix, match pruning, OpenSkill integration
- Dual-score architecture (TrueSkill + Win Rate incremental)
- DB-backed rankings, server-side pagination
- Memory optimizations, dark mode, benchmarks

## Key Files
- `/app/backend/services/scheduler.py` — Tournament loop, async `_select_pairs`, `get_matchable_paper_ids`, `dedup_pair`
- `/app/backend/services/model_analysis.py` — Unified analysis, dot-key normalizer with merge, per-model distributions
- `/app/backend/routers/admin.py` — Admin dashboard, progress (single path), cache clear with key param
- `/app/backend/server.py` — Startup (no cache wipe), `dedup_pair` migration, index-if-missing
- `/app/frontend/src/components/AdminOverview.jsx` — Redesigned numbers, refresh buttons, pair exhaustion
- `/app/frontend/src/pages/CorrelationPage.jsx` — Error boundaries per section

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
