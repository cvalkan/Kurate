# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, live analysis from rankings + cached OpenSkill
- **Frontend**: React, served as compiled build
- **Model Analysis**: Live WR/TS/SI computed on-the-fly from rankings (~200ms). OpenSkill cached in `analysis_store`, merged on read, refreshed via admin buttons.
- **Background**: Compare loop + fetch loop. Tournament matches update rankings incrementally.

## What's Been Implemented

### Session: Apr 5, 2026 (this fork)

**Stall Banner Detection — Materialized Counter Approach:**
- Added `unique_opponents` field to rankings documents (O(1) stall check, no aggregation)
- Incremented atomically in `update_rankings_for_match` alongside `comparisons`
- Initialized correctly in both `insert_ranking_for_paper` (0) and `seed_rankings` (computed from matches)
- Startup backfill migration (`_startup_backfill_unique_opponents`) populates field for existing rankings
- `reconcile_rankings` now also verifies and fixes `unique_opponents` drift
- Progress endpoint uses per-paper `unique_opponents >= matchable_count - 1` — exact for stall detection
- `unique_pairs_played` (display metric) computed as `sum(unique_opponents) // 2` — lower bound, no aggregation
- `all_pairs_exhausted` flag when all possible pairs have been played

**Scheduler Auto-Restart:**
- Compare loop now auto-restarts on crash with exponential backoff (10s → 300s max)
- Crash details stored in diagnostics: error message, traceback, timestamp, restart count
- Previously: single unhandled exception killed the loop permanently while UI still showed "Running"

**Scheduler Diagnostics:**
- New `/api/admin/scheduler-diagnostics` endpoint: loop_alive, last_cycle_at, last_cycle_unmet, per-category round results, last_crash info
- Progress endpoint adds: `last_match_at` (timestamp), `failed_matches_total` (direct DB query)
- Frontend: "Failed" card shows real DB count; status shows "Stalled" (amber) when no matches in 10+ min

**Architecture Decomposition Document:**
- Created `/app/memory/ARCHITECTURE_DECOMPOSITION.md`

### Previous Sessions

**Incremental Model Analysis, DB-backed dedup, dotted key fix, admin dashboard overhaul** — see CHANGELOG.md

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- Investigate production scheduler stall using new diagnostics
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Email notification system (Resend integration)
- Resolve circular import chain
- Migrate to httpOnly cookies

### P2
- Wire up AuthorClaimSection or remove
- Complete Gmail congrats flow or remove
- Refactor monolithic leaderboard.py and scheduler.py
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
- Remove unused BT code from `calculate_bradley_terry` if benchmarks no longer need it
