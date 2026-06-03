# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain an AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments and single-item assessments, with validation experiments and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn/UI + Recharts
- **LLMs**: Claude Opus 4.5-4.8, GPT-5.2/5.4/5.5, Gemini 3 Pro, DeepSeek v4-Pro, Kimi K2.6
- **Production DB**: MongoDB Atlas (BSON Date types, 30s read timeout)
- **Preview DB**: MongoDB localhost (string date types)

## Latest Changes (Jun 3, 2026)

### FEATURE: arXiv rate-limit hardening — P0+P1+P2 (Jun 3)
- **P1 global throttle**: new `_throttle()` in `arxiv.py` (module-level `asyncio.Lock` + `_MIN_INTERVAL=3s`) gates EVERY arXiv request process-wide to ≥1 req/3s, replacing the scattered per-page/per-category sleeps (per-page 3s sleep removed). FIFO-fair so user-facing estimate/availability calls aren't starved. Fetching is leader-only so a per-process gate suffices.
- **P2 backoff**: 429/5xx now use exponential back-off (5/10/20s + jitter, cap 90s) and honor the `Retry-After` header; back-off sleeps happen OUTSIDE the throttle lock so a long cool-down never freezes the pipeline. `max_retries=3` (fail fast under persistent blocking; rely on P0).
- **P0 per-category failure backoff (DB-persisted)**: in `_fetch_loop_inner`, a failed fetch sets `fetch_backoff_until_<cat>` + `fetch_backoff_count_<cat>` in the `global` settings doc (exponential 15m→30m→1h→2h→cap 4h); the loop skips the category until that time. Stops never-fetched/failed cats (math.PR/OC) from retrying every loop pass and hammering arXiv. Survives restarts/deploys (DB-persisted). A successful fetch clears it (in `run_fetch_cycle`, so manual/force fetches clear it too); manual/force fetches bypass the gate entirely (they don't run through the loop).
- **Verified**: 5 unit tests (`tests/test_arxiv_ratelimit.py`: throttle spacing/FIFO, Retry-After parse + honor, backoff schedule) + 22 total pass; backend healthy. Live arXiv smoke confirmed correct exponential back-off AND that **arXiv is currently 429-blocking even preview's IP on the first request** → arXiv is hard rate-limiting the datacenter egress.
- **CAVEAT**: these fixes make us back off correctly (so we stop worsening the block and it can age out) but CANNOT force arXiv to accept a hard-blocked IP. If prod egress is IP-blocked, fetches may stay 429 until it clears; the durable fix for large backfills is the bulk Kaggle/S3 dataset route (live API for the daily delta only).
- **Needs redeploy** (along with the `matches.created_at` index fix).


- **Post-deploy prod check**: archive dedup ✅ (58 dup groups auto-removed by startup self-heal, 0 remain, unique index live, `/api/admin/archive/dedupe` works) and fetch logging ✅ (a real `fetch_failed` event confirmed **arXiv 429 rate-limit** is why math.PR/OC/cs.IT don't fetch — now visible in Logs tab). BUT the backfill STILL would not reconcile (ts frozen Jun-2, `daily=422838 < expected=568069`), and the leader threw intermittent 502s while running.
- **Confirmed root cause**: the `matches` collection has **NO `created_at` index on Atlas** — a `find().sort(created_at desc).limit(1)` took **4.5s** (COLLSCAN of 568k docs; would be ms with an index). The Jun-2 `$expr`→`$or` "IXSCAN" fix REQUIRES that index to exist; it never did on prod, so every chunk COLLSCANs 568k matches × ~100 chunks ≈ 50-min crawl with per-op timeouts → dropped chunks → partial `daily`. Preview has `created_at_1` (created elsewhere) which is why it always reconciled there. `ensure_indexes()` never created the matches index — it assumed it existed.
- **Fix**: `ensure_indexes()` now creates `db.matches.create_index([("created_at",1)], name="created_at_1")` (idempotent). On next deploy the leader builds it at admin2-loop startup → every backfill chunk becomes a true IXSCAN → reconciles in ~2 min. Verified on preview (idempotent, lint clean, 17/17 pytest).
- **🔴 Requires ONE more redeploy** to build the index on Atlas; then trigger `POST /api/admin2/backfill` → expect `reconciled:True` (daily==568069). The intermittent 502s will stop once the backfill is fast.


- **Status (prod, via read-only db-explorer)**: both categories are ACTIVE in `active_categories`, NOT paused, tournaments `active` — but `last_fetch_at_*` is NULL and 0 papers. `system_logs` shows their `fetch_cycle` running repeatedly (every few min) with `new=0` every time. Since `last_fetch_at` only advances on a clean fetch, this means **Step 1 (arXiv fetch) errors on every cycle** → 0 papers accumulate → never-fetched cats keep `should_fetch=True` and retry every loop pass (no backoff), hammering arXiv across 45 categories / 2h.
- **Root gap**: the Step-1 failure was logged ONLY as a backend `WARNING`, never written to `system_logs`, so the reason (likely arXiv 429 rate-limit) was invisible in the admin Logs tab.
- **Fix (logging)**: Step-1 failures now (1) classify rate-limit (`reason=rate_limit` when "429"/"rate" in error), (2) log at ERROR with category, (3) emit a `fetch_failed` event to `system_logs` (visible in admin Logs tab). The `fetch_cycle` event detail now appends `| ERRORS: …`. The fetch loop logs when `last_fetch_at` is NOT advanced. arXiv 429/5xx retries now include the category and a "rate-limited (429)" label; retry-exhaustion logs ERROR with category. Verified: a simulated 429 produces a `system_logs` `fetch_failed` event with `reason:rate_limit`. 17/17 pytest, lint clean (no new issues).
- **Recommended follow-ups (NOT yet done — pending confirmation from the new logs after deploy)**: if logs confirm rate-limit, (a) return partially-collected pages on 429 instead of discarding the whole fetch (lets categories start accumulating), and (b) add a failure backoff so never-fetched categories don't retry every loop pass and worsen rate-limiting.


- **Correction**: prior archive dedup DID exist — `_startup_dedup_archives()` in `server.py`, a ONE-TIME migration gated by a `dedup_archives_v1: done` settings flag (keyed incl. scoring_method, keep-oldest). Because it's one-time + flag-gated, it never re-ran, so it could NOT catch duplicates created afterward — exactly why the new dupes persisted.
- **Prod ground truth** (via read-only `/api/admin/db/leaderboard_archives/aggregate`): **58 duplicate groups** (Week 22 weekly + Month 5 monthly, many categories), all created `2026-06-01T00:05:00` ms apart with identical scoring_method/paper_count → a two-pod race on the daily archive run (not a scoring-method split).
- **Unification**: `_startup_dedup_archives()` now delegates to the single `ensure_archive_integrity()` (de-dupe keep-most-complete + UNIQUE index), dropping the stale one-time flag gate. One dedup code path, runs every startup on every pod (no-op once clean), guarantees the unique index after any deploy. The unique key omits scoring_method (intended model = one archive/period; method-migration is the separate `rerank_all_archives`); safe on prod since no period currently has mixed methods.
- **Backfill thoroughly tested (preview, via real API → lock/guard honored)**: (1) COLD rebuild after wiping `summary_keys` on all 10,637 papers + clearing summary stats → keys re-materialized, reconciled:True (275,497==275,497), summary_cost $3258.2889 == per-model panel; (2) idempotent across back-to-back runs (no drift); (3) `_ensure_summary_keys` idempotent (0 missing on 2nd run); (4) archive dedupe endpoint + unique index (0 dup groups). 17/17 pytest; lint clean.
- **Prod removal still needs redeploy** (db_explorer is read-only; deployed code has no surgical delete). After redeploy, startup auto-removes all 58 dup groups + builds the unique index; `/api/admin/archive/dedupe` available for on-demand confirmation.


- **`_run_backfill` robustness**: the match-reconciliation status is now committed BEFORE the summary/registration recompute (which is wrapped in its own try). Previously a failure in `_backfill_summary_costs` aborted the whole run → no status written → badge stale even when the match rebuild fully reconciled. Now a summary-pass failure degrades only summary freshness, never the committed match status.
- **`_backfill_summary_costs` simplified 3 paper scans → 2**: the old "total counts" (2b) + "untracked = total − tracked" (2c) passes merged into ONE scan over the lightweight `summary_keys` array that emits per (day,cat,model) a count + `tracked` flag (tracked = key ∈ summary_tokens). Total counts and untracked cost both derive from it; tracked cost still comes from 2a's real token sums. Proven IDENTICAL to the old 3-pass logic (cnt_by & by_model byte-equal; cost_by differs only by 1e-6 float-order noise inherent to unordered aggregation; grand total $3258.2889 unchanged). Removed dead `tracked_cnt`.
- **Shared date helper** `core/dates.py` (`mongo_day_expr`, `safe_day`): single source of truth for "what UTC day is this doc" (string vs BSON Date). `admin.py` chunk + `admin2_stats.py` now import it instead of re-defining the `$substrCP` expression / `_safe_day` (also cleared a pre-existing E731 lambda lint).
- **Admin endpoint** `POST /api/admin/archive/dedupe` → runs `ensure_archive_integrity()` (de-dupe + unique index), returns count removed. Use on prod post-redeploy to remove the duplicate on-demand and confirm.
- **DEFERRED (flagged, not changed): "older" archive inconsistency.** Frontend + `GET /archive/{cat}/older` both key off `period_type:"older"`, but Older archives are stored as `period_type:"weekly"/"monthly"` + `label:"Older"` (`year:0,week:0`) and actually render via the weekly/monthly fallback. The "older" branches are unreachable but removing them touches a user-facing feature + frontend and prod may hold legacy `period_type:"older"` docs → needs its own tested pass.
- **Verified (preview)**: live backfill reconciled:True (275,497==275,497); summary_cost $3258.2889 == per-model panel sum; 17/17 pytest (incl. new `test_archive_dedup`); lint clean.


- **Symptom**: duplicate "Week N" leaderboard archives reappeared (recurring).
- **Root cause**: `create_archive_snapshot` used a racy check-then-insert (pre-check `find_one` then `insert_one`) with NO unique index. On a rolling redeploy / brief two-leader window, two pods both run `run_archive_snapshots(catch_up=True)` for the SAME previous week → both pass the pre-check → both insert → duplicate. The existing E11000 try/except was dead code (no unique index to trigger it).
- **Fix**: new `ensure_archive_integrity()` (leaderboard.py) runs on the leader at `_bg_archive_loop` startup, BEFORE any new snapshot: (1) de-dupes by period key (category, period_type, year, week, month) keeping the most complete copy (most papers, tie-break newest), (2) creates a UNIQUE index `archive_period_unique` so duplicates can NEVER be inserted again (the E11000 catch now actually fires). Idempotent → self-heals prod on redeploy.
- **Verified (preview)**: unique index created & rejects duplicate inserts; 0 dup groups; regression test `tests/test_archive_dedup.py` (de-dupe keeps most-complete + index blocks re-insert); 17/17 pytest. Removes the existing prod dupes automatically on next redeploy.

### FIX: production backfill hang — papers chunk COLLSCAN (P0, the ACTUAL blocker)
- **Why the summary_keys fix alone didn't reconcile prod**: After redeploy, prod `daily_stats` stayed frozen (live total_matches stuck at 355,683; `backfill_status` ts frozen at Jun-2) → the leader's backfill was hanging mid-run, never reaching the summary cost pass. Diagnosed via the public API (no prod log access): a frozen materialized view means `_run_backfill` dies inside the chunk loop, BEFORE `_backfill_summary_costs`.
- **Root cause**: `_backfill_daily_stats_chunk` (admin.py) filtered PAPERS on a *computed* `_day`/`_day2` via `$expr` → COLLSCAN that re-FETCHED every paper's full doc (incl. the 3–100KB summaries TEXT) on EVERY one of ~100 chunks ≈ **~57GB of disk reads on Atlas** → hang/timeout. (PRD note 41c, now fatal at 16.5k-paper prod scale.)
- **Fix**: replaced the `$expr` computed-field filter with an index-eligible `$or` over raw `added_at`/`published` (string bound for preview + UTC-datetime bound for prod BSON Date) — exactly equivalent to the old day-substring range (verified identical counts) but **IXSCAN→FETCH** restricts reads to the papers in each chunk → each paper read at most once across the whole run (O(N), not O(chunks×N)). Added `published` index to `ensure_indexes` as a safety.
- **Verified (preview)**: new vs old papers-count per (day,cat) IDENTICAL; explain shows IXSCAN on `published_1`/`added_at_idx` (was COLLSCAN); full live `POST /api/admin2/backfill` → `reconciled:True` (275,497==275,497, 0 failed chunks, papers 10,657, summary_cost $3258.29, match_cost $2303.94); 16/16 pytest; lint clean.
- **REQUIRES REDEPLOY**: the version on prod still has the COLLSCAN. After redeploy the leader auto-rebuilds within ~1–2 min (pods restart → flags/lock reset); confirm the green Reconciled badge / `backfill_status.reconciled:True` on Atlas.


- **Symptom**: Production daily_stats drifted/stale ("not showing the last weeks"). The backfill hung on Atlas (30s read timeout) and died, so the materialized view stopped updating.
- **Root cause**: `_backfill_summary_costs()` ran `$objectToArray` over the full `papers.summaries` TEXT (~35KB/paper × 10.6k ≈ 370MB) **twice per run** (count pass 2b + untracked pass 2c). The huge text flowed through `$unwind`/`$group`, exploding the pipeline working set → Atlas OOM/timeout → backfill aborts. Preview (local Mongo, no timeout) always reconciled, hiding it. `summary_dates` could not substitute (61% of older papers have summaries but no dates entry).
- **Fix (additive, no data deleted)**: (1) New lightweight `summary_keys` array field (just model-key strings) maintained at write-time via `$addToSet` in `admin.py` + `scheduler.py` summary writers. (2) `_ensure_summary_keys()` — idempotent, bounded streaming `find()` migration materializes `summary_keys` for existing papers (one-time text read, flat memory, no aggregation OOM); called at the top of `_backfill_summary_costs`. (3) Passes 2b/2c rewired to read the tiny `$summary_keys` array instead of `$objectToArray($summaries)` — the summary TEXT is never read by any backfill again (incl. the 12h self-heal).
- **Verified (preview)**: old-vs-new per-model summary counts IDENTICAL (0 mismatch over full set); `_ensure_summary_keys` 7s/10.6k papers; `_backfill_summary_costs` 4.5s; summary_cost reconciles EXACTLY ($3258.29 == Σ model_summary_stats, 36,517 summaries); 16/16 pytest. **Live API `POST /api/admin2/backfill` → `backfill_status.reconciled:True`** (daily 275,497 == expected 275,497, 0 failed chunks). NOT yet on prod — user will redeploy + trigger once on Atlas to confirm green badge.



### FIX: production multi-pod backfill race + leader-only execution
- **Discovery (on prod)**: After redeploy, a forced `POST /backfill` completed with `failed_chunks:0` (IXSCAN fix eliminated Atlas timeouts ✅) but the guard flagged `reconciled:False` (daily 422,838 vs expected 568,069). Cause: the per-process `_ts_backfill_running` guard can't stop a cross-POD race — `POST /backfill` (LB-routed to any pod) ran concurrently with the leader's periodic loop, issuing conflicting per-day `$set`s.
- **Fix**: (1) Distributed MongoDB lease lock (`admin2_lock`) around `_run_backfill`/`_run_incremental_backfill` — only one pod rebuilds cluster-wide. (2) **Leader-only execution**: `_kick_backfill` no-ops on non-leaders; `POST /backfill` on a non-leader queues a `backfill_request` marker the leader honors within ~60s (loop now ticks 60s instead of 30min). `is_scheduler_leader()` added to scheduler. (3) Incremental recent-days self-heal (deletes+recomputes last 10 days; idempotent; doesn't touch all-time model totals). (4) Frontend `BackfillBadge` (green Reconciled / red Drift) wired to `backfill_status`.
- **Verified on preview**: leader gating works (`POST /backfill` → started:true,leader:true); reconciles 275,497 (`reconciled:True`); incremental idempotent; 28/28 pytest; lint clean; badge renders. NOT yet on prod — needs redeploy (then the leader auto-rebuilds cleanly).

### FIX: System-vs-Category divergence + cost-counting clarification (Jun 3)
- **System view now == Σ displayed (active) categories**, by construction. Root cause of divergence: matches and summaries were written to the `_total` bucket without an active-category filter (papers already filtered), so non-active categories (and racey data) inflated System above the category sum. Fix = write-path filter: `_process_match_doc` and both summary writers (chunk in admin.py + `_backfill_summary_costs` in admin2_stats.py) now skip non-active categories, so `_total` == Σ active-category docs for papers/matches/summaries/costs. (Read path left unchanged so per-category scoping + per-model panels stay consistent.)
- **Experimental/validation model costs are KEPT** (user reversed the earlier request to exclude them). The `is_experimental_summary` helper and all exclusion calls were removed; summary cost includes all 11 models again ($3,258).
- **Cost/paper = $0.522** (preview) is accurate, not miscounted: 25.8 matches/paper + ~3.4 model-summaries/paper at configured prices. Verified match token estimates (avg 1,889 in / 164 out) and per-model reconciliation. The gap to the user's $0.16 estimate is real spend, not a counting bug — revisit pricing if needed.
- **Verified (preview, live API)**: System matches/papers == Σcategories exactly; `summary.match_cost == Σmatch_models`, `summary.summary_cost == Σsummary_models`; reconciled:True; 28/28 pytest (transient mid-backfill snapshots aside). Needs redeploy for prod.

- Breakdown (preview clean): total $5,562 / 10,657 papers = $0.52/paper. Match $2,304 (25.9 matches/paper). Summary $3,258 = **3.43 model-summaries/paper** (each paper summarized by ~3 production models: claude-opus-4-6:thinking $1,530 + gemini $580 + gpt-5.2 $569 = $2,679, plus experimental models).
- Concrete mispricing bugs found: models NOT in `MODEL_PRICING` (deepseek-v4-pro, kimi-k2.6, claude-opus-4-7/4-8, gpt-5.5, and the non-model key `abstract_plus_summary`) default to the most expensive opus rate ($5/$25) → overcount (~$300 of $3,258). The $0.52→$0.16 gap, however, is dominated by whether all ~3 summaries/paper should be counted — a product decision pending user input.


### FIX: admin2 cold-rebuild match UNDERCOUNT on production (Atlas)
- **Symptom**: A cold-start reconciliation (clear admin2 collections + rebuild) reproduced summary_cost/summaries/registrations EXACTLY but matches differed (live $inc 275,497 → rebuild 209,458). Live $inc count == ground truth (`matches` completed&!failed) == 275,497, so the **backfill was undercounting** — a bug, not drift correction.
- **Root cause**: `_backfill_daily_stats_chunk` (in `routers/admin.py`) filtered matches on a *computed* `_day` field via `$expr` → forced a **COLLSCAN** (confirmed via explain). On Atlas (762K+ matches, 30s read timeout) chunks time out, get caught by `except`→logged warning→**silently skipped** → missing matches. Preview (local Mongo) never times out, so it reconciled there.
- **Fix**: Replaced the `$expr`-on-computed-substring filter with an index-eligible `$or` range on `created_at` (string bound for preview + UTC-datetime bound for prod BSON Date). Query is now **IXSCAN on `created_at_1`** → every chunk completes fast at any scale → no dropped chunks → exact reconciliation. Removed unused `date_range_filter` helper.
- **Verified**: explain IXSCAN (was COLLSCAN); cold rebuild (backend stopped to avoid cross-process race) deterministically gives daily_stats matches=275,497 == model_match_stats == ground truth, papers=10,657, summaries=36,517, costs reconcile; 16/16 pytest; live API via REACT_APP_BACKEND_URL returns total_matches 275,497 with match_models summing to it. Note: the variance seen mid-debug (257k/243k) was a TEST-ONLY cross-process race (standalone script + running scheduler both backfilling); prod has a single leader + in-process `_ts_backfill_running` guard, so no race.

### ADD: backfill completeness guard + failed-chunk retry (admin2)
- `_run_backfill` now builds the chunk ranges up front, and on any chunk exception does **one bounded retry** of only the failed ranges (instead of silently dropping them — the production undercount failure mode).
- **Completeness guard**: after persisting, compares the authoritative per-model match sum (`all_models`, immune to per-day `$set` overwrite) against the materialized `daily_stats` `_total` sum. Material divergence (>0.5%, tolerating live-`$inc` drift) or any failed chunk → logs an ERROR and writes a `daily_stats {_meta:"backfill_status"}` doc `{ts, expected_matches, daily_matches, failed_chunks, reconciled}`.
- Status is surfaced in `GET /api/admin2/stats-overview` as `backfill_status` (visible to monitoring/UI immediately, not hidden until the next ~12h self-heal). `_meta` docs are excluded from the read path (no `category` field).
- Verified: guard records `reconciled:true` (275,497==275,497, 0 failed chunks); lint clean; 28/28 pytest (admin2_stats + admin2_refactor); API exposes `backfill_status`.
- **Open honesty notes / follow-ups**: (a) NOT yet validated on Atlas — run `POST /api/admin2/backfill` post-deploy and check `backfill_status.reconciled`. (b) `_backfill_summary_costs` uses `$objectToArray` over `papers.summaries` (3–100KB text values) → wasteful memory on Atlas (uses allowDiskUse); should project keys before unwind. (c) papers/summaries chunk aggregations still use `$expr`-COLLSCAN (smaller, didn't time out) — apply same index-backed treatment for consistency. (d) P3: make periodic self-heal INCREMENTAL (last ~7 days only; past days are immutable) to drop the recurring O(N) full rebuild.



### Admin Stats consolidated into the dashboard "Statistics" tab (replaces old panel)
- The dashboard **Statistics** tab now renders the new scalable stats; the standalone `/admin2` route and "Stats v2" tab were **removed**. Old `/api/admin/timeseries` and `/api/admin/stats` endpoints **deleted** (Overview tab repointed to `/api/admin2/stats-overview`).
- **One source of truth**: a single backfill pass writes `daily_stats` + `model_match_stats` + `model_summary_stats`; the endpoint reads ONLY these (+ `daily_registrations`, `system_logs`). No leaderboard-cache dependency, no match/paper scans. Cards, panel headers, rows, and timeseries all reconcile by construction. Accurate pricing (real tracked tokens + per-model avg for untracked).
- **Large-data hardening**: added indexes — `daily_stats {category:1,date:1}` (read path now IXSCAN, was COLLSCAN), `model_match_stats {model:1}`, `model_summary_stats {model:1}`, `daily_registrations {date:1}`, `papers {added_at:1}`. Response cache (~45s). Precomputed user registrations (no users scan). Periodic leader-only `_admin2_stats_loop` (ensure_fresh every 30m, full self-heal ~12h) + `ensure_indexes` on startup.
- **Charts**: 4 time-series charts (Papers/Matches/Tokens/Cost, incl. stacked-by-category) switched to **ECharts canvas** (fast at scale). Memory chart moved to the **bottom** (full-width), Recharts animations disabled.
- Tested: 16/16 pytest (`tests/test_admin2_stats.py`), testing agent backend 28/28 + frontend 100% (iteration_66), endpoint ~0.27s.

### (prior) Admin Stats v2 rebuild
- New scalable admin statistics page at route `/admin2` (legacy `/admin/dashboard` Statistics tab untouched). Linked via a "Stats v2" tab next to "Statistics" in the admin dashboard.
- Backend: `routers/admin2_stats.py` — single endpoint `GET /api/admin2/stats-overview` reads ONLY from the pre-aggregated `daily_stats` materialized view + `model_match_stats` + leaderboard cache + small `users`/`system_logs` aggregations. Responds in ~0.35s; NEVER scans matches/papers. Also `POST /api/admin2/backfill` and `GET /api/admin2/memory?hours=`.
- Write-time O(1) `$inc` hooks in `scheduler.py` keep `daily_stats`/`model_match_stats` fresh on every match completion, paper add, and summary generation (with ACTUAL tokens).
- One-time bounded background backfill (`_run_backfill`, 7-day chunks, type-safe `$toString` for BSON Date vs string). Fixed the legacy resume bug that made per-model meta partial.
- ACCURATE cost pricing: real `summary_tokens`/match `tokens` where available, per-model tracked averages only for the ~24% untracked summaries. All three sources reconcile exactly: match_cost $2303.94 == match panel; summary_cost $3258.29 == summary panel.
- Frontend: `pages/Admin2StatsPage.jsx` — 5 summary cards, cost/paper-over-time, match/summary cost panels, memory chart (6h–7d), 2×2 timeseries grid (Cumulative/Daily × System/Category) + per-category table, user-registration chart, refresh.
- Tested: 16/16 pytest (`tests/test_admin2_stats.py`), testing agent frontend 100%, endpoint reconciliation verified.

### Admin Stats (legacy) — Ongoing Production Issue (superseded by /admin2)
- Statistics page shows empty/zero data on production despite working on preview
- Root cause: BSON Date vs string type mismatch between preview (strings) and production (Date objects)
- Multiple fix attempts: removed $strLenCP on text, added $toString wrappers, chunked backfill
- **Decision: Rebuild from scratch as /admin2 with principled architecture**
- Handoff document: `/app/memory/ADMIN2_STATS_REBUILD.md`

### Other Completed Work (Jun 1-2)
- 2×2+2 User Behavior Charts with visitor tracking middleware
- Privacy policy updated (Swiss nDSG)
- `max_initial_backlog` admin setting
- Warming-up bug fixed (stale setTimeout closure)
- Playwright + Selenium removed from requirements
- Tags endpoint fast fallback (rankings-only, no match scan)
- Leaderboard cache: parallel aggregations, removed $strLenCP on full_text
- Re-added 9 removed categories on production
- Spearman correlation analysis (Claude SI vs TrueSkill, 10K papers)

## Known Issues
- **Admin stats page broken on production** (empty data) — rebuild planned as /admin2
- TweetAPI returns 401 (external account limitation)
- `mode: {$exists: False}` still in leaderboard.py, ranking.py, scheduler.py

## Pending
- P0: Verify /admin2 on PRODUCTION (Atlas) — confirm no timeout & numbers populate (trigger POST /api/admin2/backfill once after deploy).
- P1: Extended prompt (5 categorical metrics)
- P1: Landing page merge from GitHub branch
- P1: SI source of truth consolidation
- P2: Semantic Search & "Papers Like This"
- P2: Clean remaining mode:{$exists:False} filters from leaderboard.py, ranking.py, scheduler.py
- P2: Multiple Reviewer Personas, Live ChemRxiv Fetcher
- P2 (optional): retire legacy /admin/dashboard Statistics tab once /admin2 validated on prod
