# Changes Since Last Fork — Merge Guide

## Overview
This fork implemented: OAI-PMH migration (3 phases), code audit/cleanup, arXiv fetch pipeline hardening, and a new Category Status admin dashboard.

---

## Change 1: 429 Global Cooldown + Configurable Delays

**Problem:** arXiv 429 rate limits caused a feedback loop — the round-robin fetch loop kept retrying failed categories every 10s, hammering arXiv with ~40 wasted calls per burst.

**Fix:** Three-tier delay system:
- `fetch_success_delay` (default 10s): pause between successful fetches
- `fetch_fail_delay` (default 300s): global pause after a 429 — stops ALL fetching, not just the failed category  
- `fetch_interval_hours` (existing, set to 6): full cycle interval

Also: 429 → immediate fail in arxiv.py (no 3x retry on rate limits, only retry on 5xx/timeouts).

**Files:**
- `backend/services/scheduler.py` — `_fetch_loop_inner()` (~line 454): replaced hardcoded `await asyncio.sleep(10)` with dynamic `delay` variable set to `success_delay` or `fail_delay` based on result. Reads both from admin settings.
- `backend/services/arxiv.py` — `fetch_arxiv_papers()` retry loop (~line 88): 429 now raises immediately instead of retrying. Only 5xx/timeouts get 3x retry.
- `frontend/src/pages/AdminPage.jsx` — Settings tab (~line 343): added `fetch_success_delay` and `fetch_fail_delay` as editable admin parameters with help text.
- `frontend/src/pages/AdminPage.jsx` — (~line 225): added both keys to the numeric parse list for save.

---

## Change 2: Category Status Dashboard

**Problem:** The old "arXiv Health" tab showed limited info (just healthy/error/never) and the data was often stale.

**Fix:** New `/api/admin/category-status` endpoint + complete UI replacement.

**Backend:**
- `backend/routers/admin.py` — new endpoint `category_status()` (~line 2490 area, after `arxiv_health`): batch-loads tournament docs, last fetch_cycle logs (via aggregation), paper counts (from rankings), match counts (from matches). Returns per-category: status, papers, matches, last_fetch_at, next_due, last_action, fetch_paused, tournament_paused.
- Status logic: `up_to_date` / `fetching` / `fetch_failed` / `overdue` / `fetch_paused` / `tournament_paused` / `never`

**Frontend:**
- `frontend/src/components/AdminLogs.jsx` — `ArxivHealthTable` component (~line 495): completely rewritten. Now calls `/api/admin/category-status`. Shows table with: Status, Category, Papers, Matches, Last fetch, Next due, Last action. Color-coded status labels. Tab renamed from "arXiv Health" to "Category Status".
- `frontend/src/components/AdminLogs.jsx` — `fmtAgo()` (~line 479): updated to handle future dates (shows "in 3h" for next_due).
- `frontend/src/components/AdminLogs.jsx` — tab label (~line 47): changed `"arXiv Health"` → `"Category Status"`.

---

## Change 3: Fetch Cycle Log Filter Fix

**Problem:** "Fetch cycle" filter in Logs tab showed 0 entries because the query fetched 500 most recent `level: "event"` docs, which were dominated by 12K+ `slow_response` noise events.

**Fix:**
- `frontend/src/components/AdminLogs.jsx` — system_logs query (~line 170): when a specific event type is selected (fetch_cycle, convergence, archive), the query now includes `event: "fetch_cycle"` in the filter, not just `level: "event"`. This returns 500 most recent fetch_cycle events specifically.

---

## Change 4: Duplicate Log Fixes

**Fetch cycle category duplication:**
- `backend/services/scheduler.py` — `run_fetch_cycle()` detail string (~line 1329): removed `{category}: ` prefix from the detail string. The frontend already prepends category from the `category` field.

**Failure log deduplication:**
- `frontend/src/components/AdminLogs.jsx` — after merging results (~line 189): added dedup logic that removes failed `llm_usage` entries when a matching `llm_error_logs` entry exists (same timestamp + paper).

---

## Change 5: OAI-PMH Migration Script (3 Phases)

**Files:**
- `backend/scripts/fix_oai_dates.py` — complete rewrite. Three phases:
  - Phase 1: Fix dates + versioning for 1,083 papers using `/app/oai_dates_results.jsonl`
  - Phase 2: Remove 1,956 ghost papers + matches + cleanup refs
  - Phase 3: Replay TrueSkill from scratch for 25 affected categories
  - New: `_affected_categories()`, `_phase3_recompute()`, per-category Phase 3 support
- `backend/routers/admin.py` — endpoint `fix_oai_dates` (~line 2493): updated to accept `category` param for per-category Phase 3
- `backend/routers/admin.py` — new endpoint `cleanup_stale_tournaments` (~line 2502)
- `backend/tests/test_oai_migration.py` — 9 tests covering all phases

---

## Change 6: Code Audit Cleanup

**Dead code removed:**
- `backend/routers/admin.py`: removed `_get_admin_cached`, `_set_admin_cached` (dead cache helpers), `_invalidate_admin_cache` + all 13 call sites (no-op cache invalidation), `_backfill_daily_stats_chunk` (123 lines, superseded by drip seed), `estimate_category` (89 lines, unused)
- `backend/services/scheduler.py`: removed `_collect_cursor_docs` (unused helper)
- `backend/routers/leaderboard.py`, `backend/services/ranking.py`, `backend/services/scheduler.py`, `backend/services/model_analysis.py`, `backend/services/replay.py`: removed 27 stale `"mode": {"$exists": False}` query filters

**Archived (moved to `/app/archive/`, not deleted):**
- `archive/scripts/` — 36 unused scripts
- `archive/frontend/components/` — 3 unused components
- `archive/frontend/pages/` — 3 unused pages
- `archive/docs/` — 7 stale root docs/logs

**Frontend default display fix:**
- `frontend/src/pages/AdminPage.jsx` (~line 364): `displayValue` now falls back to `dflt` instead of showing grey placeholder for unset settings.

---

## Files Changed (production-relevant only)

| File | What changed |
|------|-------------|
| `backend/services/scheduler.py` | 429 cooldown, duplicate log fix, removed dead code |
| `backend/services/arxiv.py` | 429 fail-fast (no retry on rate limit) |
| `backend/routers/admin.py` | Category status endpoint, migration endpoints, removed dead code |
| `backend/routers/leaderboard.py` | Removed mode filters |
| `backend/services/ranking.py` | Removed mode filters |
| `backend/services/model_analysis.py` | Removed mode filters |
| `backend/services/replay.py` | Removed mode filters |
| `backend/scripts/fix_oai_dates.py` | Complete rewrite (3-phase migration) |
| `backend/tests/test_oai_migration.py` | 9 migration tests |
| `frontend/src/components/AdminLogs.jsx` | Category Status UI, log filter fix, dedup fix |
| `frontend/src/pages/AdminPage.jsx` | Fetch delay settings, default display fix |
| `memory/PRD.md` | Updated |
