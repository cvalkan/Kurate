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

**Ghost Match Root Cause Analysis & Fix:**
- Root cause: `update_rankings_for_match` used `find_one_and_update` WITHOUT `upsert`. When the compare loop matched a paper before its ranking entry existed (race condition with fetch loop), the `$inc` silently did nothing. Match saved to DB but rankings never updated = ghost match.
- Production audit: cs.SI had 278 ghost matches (27%), astro-ph.CO had ~178. cs.DC had 20, cs.CR had 1. All others clean.
- Fix: `update_rankings_for_match` now creates the ranking entry on-the-fly (via `insert_ranking_for_paper`) if missing, then retries the increment. No more silent drops.
- Reconciled all drifted production categories. cs.SI Goal 1 went from 28/40 → 40/40 fully met. Cosmology fully converged.

**Stall Banner Detection (Materialized Counter):**
- Added `unique_opponents` field to rankings (O(1) stall check)
- v1 backfill had a bug (counted cross-tournament opponents from matches DB). v2 fix: set `unique_opponents = comparisons`.
- Per-paper stall check exact. `unique_pairs_played` (display) is a lower-bound approximation.

**Scheduler Auto-Restart:**
- Compare loop now auto-restarts on crash with exponential backoff (10s → 300s max)

**Scheduler Diagnostics:**
- `/api/admin/scheduler-diagnostics`: loop_alive, last_cycle_at, unmet categories, per-category results, crash info
- `/api/admin/diagnose-pairs`: per-paper diagnosis showing rankings comps vs DB opponents vs novel opponents available
- Progress endpoint: `last_match_at`, `failed_matches_total`, "Stalled" status indicator

**Architecture Decomposition Document:**
- `/app/memory/ARCHITECTURE_DECOMPOSITION.md`

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Email notification system (Resend integration)
- Resolve circular import chain
- Migrate to httpOnly cookies

### P2
- Wire up AuthorClaimSection or remove
- Complete Gmail congrats flow or remove
- Refactor monolithic leaderboard.py and scheduler.py
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
