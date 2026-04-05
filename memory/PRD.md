# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, live analysis from rankings + cached OpenSkill
- **Frontend**: React, served as compiled build
- **Model Analysis**: Live WR/TS/SI computed on-the-fly from rankings (~200ms). OpenSkill cached in `analysis_store`, merged on read, refreshed via admin buttons.
- **Background**: Compare loop + fetch loop. Tournament matches update rankings incrementally.

## What's Been Implemented

### Session: Apr 5, 2026 (continued)

**Stall Banner Detection Fix:**
- Replaced unreliable `rankings.comparisons >= matchable_count - 1` check with DB-backed aggregation on `dedup_pair`
- Old method used rankings field that could be inflated by seeding priors or stale from incomplete `$inc` updates
- New method: single MongoDB aggregation counts actual unique opponents per paper from completed matches
- Added `all_pairs_exhausted` flag (true when every possible pair has been compared)
- Added `unique_pairs_played / max_possible_pairs` to progress response for visibility
- Frontend shows distinct messages for per-paper exhaustion vs full pair exhaustion

**Scheduler Diagnostics:**
- Added `/api/admin/scheduler-diagnostics` endpoint exposing compare loop health
- Tracks: last_cycle_at, last_cycle_unmet categories, per-category round results, loop_alive status
- Added `last_match_at` and `failed_matches_total` (direct DB query) to progress endpoint
- Frontend "Failed" card now shows actual DB count instead of stale cached value
- Frontend shows "Stalled" (amber) instead of "Running" when no new matches in 10+ minutes

**Architecture Decomposition Document:**
- Created `/app/memory/ARCHITECTURE_DECOMPOSITION.md` analyzing service separation options
- Recommended Option A (Role-Based Startup) as practical first step

### Session: Apr 5, 2026 (earlier)

**Incremental Model Analysis (Major Architecture Change):**
- Split `compute_model_analysis()` into `compute_live_analysis()` (fast, from rankings) + `compute_openskill_cache()` (heavy, from matches)
- Model Analysis page now loads in 0.07-0.23s (was 2+ min from cold cache)

**Scaling:**
- DB-backed pair dedup: `dedup_pair` field + compound index
- `_select_pairs` async with indexed DB queries — O(100) memory, scales to 100K+ papers

**Critical Fixes:**
- Restored `_select_pairs` (was accidentally deleted, blocked ALL matches)
- GPT-5.2 Model Correlation fix (MongoDB dot-in-key merge bug)

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- Investigate production scheduler stall: use new `/scheduler-diagnostics` endpoint to identify root cause
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Email notification system (Resend integration)
- Resolve circular import chain
- Migrate to httpOnly cookies

### P2
- Wire up AuthorClaimSection or remove
- Complete Gmail congrats flow or remove
- Refactor monolithic leaderboard.py and scheduler.py
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
