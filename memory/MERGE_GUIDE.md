# Changes Since Fork (Jun 7, 2026) — Merge Guide

## Overview
This fork (starting from commit `1b7cb4ee`, Jun 7 18:30 UTC) implemented 3 changes across 4 production files. Everything else (OAI migration, code cleanup, archive, duplicate log fixes, dead code removal) was done in the PREVIOUS session and is already on the `main` branch.

---

## Changed Files (4 total)

| File | Lines changed |
|------|--------------|
| `backend/services/scheduler.py` | ~30 lines changed in `_fetch_loop_inner()` |
| `backend/routers/admin.py` | ~128 lines added (new endpoint) |
| `frontend/src/components/AdminLogs.jsx` | ~100 lines changed (Category Status UI + log filter) |
| `frontend/src/pages/AdminPage.jsx` | ~8 lines changed (new settings + default fix) |

---

## Change 1: 429 Global Cooldown + Configurable Delays

**Problem:** After a 429 from arXiv, the round-robin loop kept trying the next category every 10s — arXiv rate-limits the IP, not the category, so every subsequent call also 429'd. This created ~40 wasted calls per burst.

**Fix:** Dynamic `delay` variable replaces the hardcoded `await asyncio.sleep(10)`. On 429, the entire pipeline pauses for `fetch_fail_delay` seconds (default 300 = 5 min).

**File: `backend/services/scheduler.py`**
- Function `_fetch_loop_inner()` (~line 454):
  - Added `delay = 10` default before try block
  - Reads `fetch_success_delay` and `fetch_fail_delay` from admin settings
  - On success: `delay = success_delay`
  - On 429 (`_failure_reason == "rate_limit"`): `delay = fail_delay` + logs cooldown message
  - On other errors: `delay = success_delay`
  - On exception: `delay = 60`
  - `await asyncio.sleep(delay)` at end of loop (was hardcoded `10`)

**File: `frontend/src/pages/AdminPage.jsx`**
- Settings save list (~line 225): added `"fetch_success_delay"`, `"fetch_fail_delay"` to numeric parse loop
- Settings UI (~line 343): added two new parameter entries:
  - `fetch_success_delay`: label "Fetch Success Delay (sec)", default 10, range 5-120
  - `fetch_fail_delay`: label "Fetch 429 Cooldown (sec)", default 300, range 60-900
- Default display fix (~line 364): `displayValue` falls back to `dflt` instead of showing grey placeholder for unset settings: `editSettings[key] ?? dflt`

---

## Change 2: Category Status Dashboard

**Problem:** The old "arXiv Health" tab showed limited info and was drowned out by noise events.

**File: `backend/routers/admin.py`**
- New endpoint `GET /api/admin/category-status` (~line 2490, inserted after `arxiv_health`):
  - Batch-loads tournament docs, last fetch_cycle logs (aggregation), paper counts (rankings agg), match counts (matches agg)
  - Returns per category: `status`, `papers`, `matches`, `last_fetch_at`, `next_due`, `last_action`, `last_action_at`, `fetch_paused`, `tournament_paused`
  - Status values: `up_to_date`, `fetching`, `fetch_failed`, `overdue`, `fetch_paused`, `tournament_paused`, `never`
  - Returns `summary` object with counts per status

**File: `frontend/src/components/AdminLogs.jsx`**
- Tab label (~line 47): `"arXiv Health"` → `"Category Status"`
- `ArxivHealthTable` component (~line 495): completely rewritten:
  - Calls `/api/admin/category-status` instead of `/api/admin/arxiv-health`
  - Table columns: Status, Category, Papers, Matches, Last fetch, Next due, Last action
  - Color-coded status labels with `whitespace-nowrap`
  - Summary bar shows counts per status + cycle interval
- `fmtAgo()` function (~line 479): updated to handle future dates (prefix "in " instead of suffix " ago")

---

## Change 3: Fetch Cycle Log Filter

**Problem:** "Fetch cycle" filter showed 0 entries because 500 most recent `level: "event"` docs were dominated by 12K+ `slow_response` noise events.

**File: `frontend/src/components/AdminLogs.jsx`**
- System logs query (~line 170): when a specific event type is selected, the filter now includes the event name:
  ```js
  const eventFilter = { level: "event" };
  if (type === "fetch_cycle") eventFilter.event = "fetch_cycle";
  else if (type === "convergence") eventFilter.event = "convergence";
  else if (type === "archive") eventFilter.event = "archive_created";
  ```

---

## Non-file changes (DB operations done via admin API on production)
- Activated 7 paused tournaments (cond-mat.mtrl-sci, cs.SI, physics.chem-ph, q-bio.BM/GN/NC/PE)
- Cleaned 18 stale tournament docs via `POST /api/admin/cleanup-stale-tournaments`
- `fetch_interval_hours` changed from 24 → 6
