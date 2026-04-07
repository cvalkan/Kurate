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

**Always browser-test UI changes:** After ANY frontend code change, take a screenshot AFTER rebuilding (`yarn build`) to verify the change works. Do NOT trust that correct source code = working UI. Variable renames, stale references, and build issues are invisible without a browser test.

**Ghost matches (update_rankings_for_match):** If `find_one_and_update` returns `None` (no matching ranking doc), the `$inc` silently does nothing. Always check for `doc is None` and handle it.

**MongoDB `.to_list(None)` is dangerous:** Loading all documents without a limit can return millions of entries and crash the browser. Always use `.to_list(length=limit)` or server-side aggregation with downsampling.

**ORCID API:** The main v3.0 endpoints (`/person`, `/email`) do NOT expose verified email domains. Use the Record Summary API at `https://orcid.org/{id}/public-record.json`.

**Factual metrics must be consistent across view modes:** When adding an "Average" or alternative view, factual metrics like m/paper must not change — they're counts, not statistics.

**Admin fetch/summary pipeline:** The `run_fetch_cycle` now has 4 independent steps (ArXiv fetch → PDF download → summary gen → ranking insert). Each step runs even if a prior one fails. The `force=True` parameter must propagate through to `gen_one` to bypass pause checks.

**summary_coverage.with_summaries:** Must come from actual DB count of papers with non-empty summaries dict — NOT from `total_papers` (leaderboard/ranked count). These diverge when papers have summaries but aren't ranked yet.

## What's Been Implemented

### Session: Apr 7, 2026

**Admin Button Fixes:**
- Fixed `gen_one` in `_generate_paper_summaries` to respect `force=True` (bypasses pause check) — previously silently skipped ALL papers when system paused
- Made `run_fetch_cycle` resilient: 4 independent steps instead of one monolithic try/except. ArXiv 429 no longer kills PDF/summary/ranking work.
- Fixed `summary_coverage.with_summaries` to use actual DB count instead of ranked papers count
- Fixed `_run_fetch_in_background` to properly map error/partial/ok status
- Added per-step logging: `[category] Step N:` for fetch/PDF/summary/ranking steps
- Updated frontend toast to show detailed results (papers/PDFs/summaries/rankings counts)
- Added `GET /api/admin/unranked-papers` diagnostic endpoint
- Added logging for silent gen_one failures (stop flag, pause, paper not found)
- Step 4 (rankings insert) now always runs, not just when new_count > 0

### Session: Apr 5, 2026

**Ghost Match Root Cause Analysis & Fix:**
- Root cause: `update_rankings_for_match` used `find_one_and_update` WITHOUT `upsert`.
- Production audit: cs.SI had 278 ghost matches (27%), astro-ph.CO had ~178.
- Fix: `update_rankings_for_match` now creates ranking entry on-the-fly if missing.

**Stall Banner Detection (Materialized Counter):**
- Added `unique_opponents` field to rankings (O(1) stall check)

**Scheduler Auto-Restart:**
- Compare loop now auto-restarts on crash with exponential backoff (10s → 300s max)

**Correlation Page Scaling:**
- Reduced load time from 65s to 0.2s via event-driven background caching

**Cache Rebuild Optimization:**
- Removed dead progress logic, debounced refresh to 30s, cached goals check. Peak RAM dropped 66%.

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Email notification system (Resend integration)
- Resolve circular import chain
- Author Verification flow (ORCID Option E / Scholar URL Option B)
- Architecture Split: KURATE_ROLE env var

### P2
- Migrate to httpOnly cookies
- Wire up AuthorClaimSection or remove
- Complete Gmail congrats flow or remove
- Refactor monolithic leaderboard.py and scheduler.py
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
