# Dead Code Audit — Kurate.org Backend (VERIFIED)
Generated: 2026-03-28
Codebase: ~37K lines across 90 Python files

Each item has been manually verified against the codebase. False positives
from the automated scan are marked and explained.

---

## 1. Write-Only MongoDB Collections

### `ranking_snapshots` — CONFIRMED DEAD

- **744 documents, 2.4 MB storage**
- Written after every comparison round by `_store_ranking_snapshot` (loads ALL matches + BT)
- The ONLY read is `find_one` to get the last round number for auto-increment (self-referential)
- No endpoint, no router, no frontend reads from it
- **Original intent**: round-over-round convergence tracking
- **What replaced it**: convergence chart (`/api/convergence`) replays match history directly
- **Memory cost per round**: ~17 MB match load + ~7 MB BT compute = ~24 MB × 6 cats = **~144 MB/cycle**
- **Action**: Remove `_store_ranking_snapshot` and caller at scheduler.py:1169. Drop collection.

### ~~`qeios_pairwise_extract`~~ — FALSE POSITIVE

- **Audit claimed**: no reads found
- **Reality**: IS read via `_get_ctx("extract")` → `ctx["collection"].find(...)` (qeios.py:220). The collection reference is passed through a variable, not used as `db.collection.find()` directly. The automated regex missed this.
- **Action**: Keep. Functional.

### `gmail_oauth_states` — FUNCTIONAL (not dead)

- Part of Gmail OAuth flow for congrats emails
- Write: congrats.py:133, Read: server.py:176, Delete: server.py:179
- **Action**: Keep.

---

## 2. Unused Functions in Hot-Path Files

All items manually verified — zero call sites across entire backend.

### `leaderboard.py` (3 dead functions, ~50 lines)

| Function | Line | Notes |
|---|---|---|
| `_apply_period_filter` | 54 | Replaced by `_build_period_filter` which returns MongoDB query |
| `_apply_search` | 593 | Search now done via MongoDB `$regex` in query, not post-filter |
| `_get_paper_si_rating` | 2192 | Inlined wherever needed; standalone function unused |

### `ranking.py` (2 dead functions, ~120 lines)

| Function | Line | Notes |
|---|---|---|
| `calculate_bt_confidence_intervals` | 135 | Legacy BT Fisher-information CIs. Not used after WR/TS switch |
| `compute_weighted_bt_async` | 128 | Async wrapper never called (the sync version `compute_weighted_bt` is used directly via `run_in_executor` in human_ai_benchmark) |

### `llm.py` (1 dead function, ~30 lines)

| Function | Line | Notes |
|---|---|---|
| `get_extraction_stats` | 504 | Admin uses `_compute_extraction_stats_impl` (admin.py:1787) which calls `extract_key_sections` directly, not this wrapper |

### `scheduler.py` (2 dead functions, ~13 lines)

| Function | Line | Notes |
|---|---|---|
| `_iter_cursor_batches` | 86 | Defined but `_collect_cursor_docs` used everywhere instead |
| `_re_escape` | 18 | Defined but never called |

**Total verified dead code: 8 functions, ~213 lines**

---

## 3. Legacy BT/Match-Loading Code in Production Hot Path

### CORRECTED memory estimates

The original audit overstated memory costs by using full-document sizes.
Actual costs use projected documents (~600 bytes/doc, not ~2.2 KB):

| Operation | Projection size | cs.RO actual | Was claimed |
|---|---|---|---|
| `_check_goals_met` match load | 3 fields | **~13 MB** | ~~48 MB~~ |
| `run_comparison_round` match load | 3 fields | **~13 MB** | ~~53 MB~~ |
| `_store_ranking_snapshot` match load + BT | 5 fields + numpy | **~24 MB** | ~~73 MB~~ |
| `_compute_convergence` match load + 40×BT | 6 fields + numpy | **~29 MB** | ~~73 MB~~ |

### Per-round match loading (fires after every comparison round)

| Caller | Actual cost (cs.RO) | Needed? | Notes |
|---|---|---|---|
| `_check_goals_met` | ~13 MB | **PARTIALLY** | Goals 1-2 (Wilson margins) → available from `rankings`. Goal 3 (pair existence) still needs match data, but could use 45 targeted queries instead of bulk load |
| `run_comparison_round` | ~13 MB | **PARTIALLY** | `paper_stats` → available from `rankings`. `compared_pairs` requires match scan (but only pair columns) |
| `_store_ranking_snapshot` | ~24 MB | **NO** | Dead code (see Area 1). Remove entirely |
| `_recompute_convergence_bg` | ~29 MB | **YES but over-frequent** | Fires after every round; convergence curve barely changes with 20-100 new matches. Rate-limit to every 10th round or 5% match growth |

### BT/leaderboard calls by context

| Context | Still needed? | Notes |
|---|---|---|
| Convergence chart | YES | Replays match history to show ranking stability curve |
| Tag-filtered local stats | YES | On-demand for tag filter with local recompute mode |
| Inter-model PW correlation (non-standard modes) | YES | Legacy match-based path for prediction/non-standard modes |
| Seed rankings (startup) | YES | One-time bootstrap |
| Ranking snapshot | **NO** | Dead code |
| Validation/benchmark pages | YES | But served from precomputed JSON, not computed live |
| Summary bias analysis | YES | Experimental analysis, not hot path |

### Corrected total eliminable memory per cycle

| Change | Savings per cycle (6 cats) |
|---|---|
| Remove `_store_ranking_snapshot` | ~144 MB |
| Rewrite `_check_goals_met` (use rankings + targeted pair queries) | ~78 MB |
| Rate-limit convergence to every 10th round | ~157 MB (90% reduction) |
| **Total** | **~379 MB transient allocs eliminated** |

(Down from the original inflated estimate of ~1.1 GB — still significant.)

---

## 4. Unused/Unreferenced API Endpoints (VERIFIED)

### FALSE POSITIVES from automated scan

The automated scan had major blind spots with:
1. **Parameterized URLs**: Frontend uses `${slug}`, `${paperId}` — literal string matching fails
2. **External callers**: Badge share pages, sitemap, OG images — called by crawlers, not SPA
3. **Dynamic routing**: React Router `:slug` param handles both `w5` and `m3` formats

**These were incorrectly flagged and are NOT dead:**

| Endpoint | Actual caller |
|---|---|
| `GET /api/papers/{paper_id}` | PaperPage.jsx:196 |
| `DELETE /api/bookmarks/{paper_id}` | BookmarkContext.jsx:40 |
| `GET /api/lists/public/{list_id}` | ReadingListPage.jsx:32 |
| `POST /api/lists/{list_id}/papers` | BookmarksPage.jsx:103 |
| `DELETE /api/lists/{list_id}/papers/{paper_id}` | (via same ReadingListPage flow) |
| `POST /api/lists/{list_id}/fork` | ReadingListPage.jsx:97 |
| `POST /api/lists/{list_id}/import-bookmarks` | ReadingListPage.jsx:75 |
| `POST /api/lists/{list_id}/import-to-list` | ReadingListPage.jsx:86 |
| `GET /api/lists/{list_id}/share` | ReadingListPage.jsx:51 (OG share page) |
| `GET /api/lists/{list_id}/image.png` | ReadingListPage.jsx:155 (download) |
| `GET /api/badge/.../share` | BadgePage.jsx:63 + social crawlers |
| `GET /api/badge/.../image.png` | BadgePage.jsx:65 + social crawlers |
| `GET /api/badge/paper/{paper_id}/badges` | PaperPage.jsx:206 |
| `GET /api/badge/{cat}/{year}/m{month}/{paper_id}` | BadgePage.jsx via `:slug` param |
| `GET /api/badge/{cat}/{year}/m{month}/{paper_id}/image.png` | Same dynamic routing |
| `GET /api/badge/{cat}/{year}/m{month}/{paper_id}/share` | Same dynamic routing |
| `GET /api/archive/{cat}/{year}/w{week}` | LeaderboardPage.jsx:233, ArchivePage.jsx:29 |
| `GET /api/archive/{cat}/{year}/m{month}` | LeaderboardPage.jsx:233, ArchivePage.jsx:30 |
| `GET /api/archive/{cat}/older` | LeaderboardPage.jsx:232 |
| `GET /api/archive/list` | ArchiveList.jsx:17 |
| `GET /api/sitemap.xml` | Search engine crawlers (expected) |
| `GET /api/congrats/gmail/auth-url` | Comment in BadgePage suggests planned use |
| `GET /api/validation/dataset-rankings/{dataset_id}` | Referenced in validation frontend flows |
| `POST /api/claim/{paper_id}` | AuthorClaimSection.jsx:55 (component exists but is never rendered — see note below) |

### CONFIRMED unused endpoints

**Admin escape hatches (functional but never triggered from UI):**

| Endpoint | Purpose | Risk to remove |
|---|---|---|
| `POST /api/admin/generate-summaries` | Manual summary trigger | LOW — automated in scheduler |
| `GET /api/admin/summary-gen-progress` | Polling for above | LOW |
| `POST /api/admin/dedup-papers` | Manual dedup | LOW — automated at startup |
| `POST /api/admin/regen-summaries` | Regen truncated summaries | LOW — one-time migration, auto-runs at startup |
| `GET /api/admin/regen-summaries/status` | Status for above | LOW |
| `GET /api/admin/background-tasks` | List bg tasks | MEDIUM — useful for debugging |
| `POST /api/admin/archive/snapshot` | Manual archive creation | MEDIUM — useful escape hatch |
| `POST /api/admin/archive/snapshot-all` | Snapshot all cats | MEDIUM |
| `POST /api/admin/archive/backfill` | Backfill historical archives | LOW — one-time use |

**Pairwise router endpoints (superseded by validation router):**

| Endpoint | Notes |
|---|---|
| `POST /api/pairwise/fetch-pairs` | Superseded by validation/import-* endpoints |
| `POST /api/pairwise/run-tournament` | Validation router has its own `/run-tournament` |
| `POST /api/pairwise/reset` | Data management — keep as escape hatch |

**One-time data import endpoints (data already imported):**

| Endpoint | Dataset |
|---|---|
| `POST /api/validation/import-iclr` | ICLR 2025 |
| `POST /api/validation/import-elife` | eLife |
| `POST /api/validation/import-midl` | MIDL |
| `POST /api/validation/import-uai` | UAI |
| `POST /api/validation/import-peerread` | PeerRead |
| `POST /api/validation/import-f1000` | F1000Research |
| `POST /api/validation/seed` | Seed validation data |
| `POST /api/validation/replay-tournament` | Replay tournament |
| `POST /api/validation/run-cross-mode-fill` | Cross-mode fill |

**F1000/ACMI one-time scraper endpoints:**

| Endpoint |
|---|
| `POST /api/validation/scrape-f1000` |
| `GET /api/validation/scrape-f1000/status` |
| `POST /api/validation/enrich-f1000` |
| `POST /api/validation/expand-f1000` |
| `POST /api/validation/rescrape-f1000-evals` |
| `POST /api/validation/acmi/scrape` |
| `GET /api/validation/acmi/scrape/status` |
| `GET /api/validation/acmi/stats` |

**Other confirmed unused:**

| Endpoint | Notes |
|---|---|
| `GET /api/badge/.../exists` | Not called by frontend or crawlers |
| `POST /api/validation/stop-tournament` | Frontend uses `/api/pairwise/stop-tournament` instead |
| `POST /api/congrats/gmail/send` | Gmail send feature not wired in frontend |
| `GET /api/congrats/gmail/status` | Same — Gmail OAuth flow incomplete in UI |
| `POST /api/qeios/pairwise-extract/stop` | Rarely-used admin control |
| `GET /api/qeios/paper-data/stats` | Rarely-used admin stats |
| `POST /api/scipost/reset` | One-time admin tool |
| `POST /api/summarizer-ab/queue-batch` | Manual queue trigger |

**Note: `AuthorClaimSection.jsx` is defined but never rendered.** The component exists with claim endpoints wired in, but it's never imported by any page. This means `POST /api/claim/{paper_id}`, `GET /api/claim/my-orcid`, `GET /api/claim/my-claims`, and `GET /api/claim/paper/{paper_id}` are technically reachable via API but have no UI path. The admin claim endpoints (`/api/claim/admin/*`) ARE used from AdminPage.jsx.

---

## Summary: Recommended Actions by Priority

### P0 — Memory savings (~380 MB transient allocs eliminated)

1. **Remove `_store_ranking_snapshot`** — dead code, ~144 MB/cycle saved
2. **Rewrite `_check_goals_met` to use `rankings` collection** — ~78 MB/cycle saved
3. **Rate-limit `_recompute_convergence_bg`** to every 10th round — ~157 MB/cycle saved

### P1 — Code cleanup (~213 lines)

4. Remove 8 verified dead functions from hot-path files
5. Optionally wire `AuthorClaimSection` into PaperPage, or remove it

### P2 — Endpoint hygiene (optional)

6. Gate one-time import/scraper endpoints behind admin-only flag (already gated, low priority)
7. Remove `badge_exists`, `validation/stop-tournament` (duplicated by pairwise version)
8. Complete Gmail congrats flow or remove the 3 unwired endpoints
