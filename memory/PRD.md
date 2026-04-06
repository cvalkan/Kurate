# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, live analysis from rankings + cached OpenSkill
- **Frontend**: React, served as compiled build
- **Model Analysis**: Live WR/TS/SI computed on-the-fly from rankings (~200ms). OpenSkill cached in `analysis_store`, merged on read, refreshed via admin buttons.
- **Background**: Compare loop + fetch loop. Tournament matches update rankings incrementally.

## Agent Learnings (for future forks)

**Stale frontend builds:** This React app serves a COMPILED production bundle, not live source files. Hot reload works for development but does NOT rebuild the bundle. After modifying any frontend file (`src/components/*.jsx`, `src/pages/*.jsx`), you MUST run `cd /app/frontend && yarn build && sudo supervisorctl restart frontend` before testing via screenshots or browser tools. Symptoms of a stale build: code changes appear correct in the source files but the browser shows old behavior. The testing agent caught this after the main agent wasted multiple screenshot cycles debugging a non-existent React state bug.

**Always browser-test UI changes:** After ANY frontend code change, take a screenshot AFTER rebuilding (`yarn build`) to verify the change works. Do NOT trust that correct source code = working UI. Variable renames, stale references, and build issues are invisible without a browser test. In one case, renaming `mData` → `mDataAgg` left 3 stale references (`mData.label`, `wmData?.n_matches`, `wmData?.avg_mpp`) that only showed as "Section failed to render" errors in the browser — invisible in linting or code review.

**Ghost matches (update_rankings_for_match):** If `find_one_and_update` returns `None` (no matching ranking doc), the `$inc` silently does nothing. Always check for `doc is None` and handle it (create the ranking entry, then retry). This race condition between the fetch loop and compare loop caused 278 ghost matches on production.

**MongoDB `.to_list(None)` is dangerous:** Loading all documents without a limit can return millions of entries and crash the browser (17.5MB JSON response → "Maximum call stack size exceeded"). Always use `.to_list(length=limit)` or server-side aggregation with downsampling.

**ORCID API:** The main v3.0 endpoints (`/person`, `/email`) do NOT expose verified email domains. Use the Record Summary API at `https://orcid.org/{id}/public-record.json` — it has the `emailDomains` field. The v3.0 `/email` endpoint only returns emails the user made fully public (~6% of researchers).



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
