# HANDOVER — Stats-Page Backfill, arXiv Backoff, and Production Logs

**Audience:** the next (more capable) engineering agent.
**Author:** prior agent (E1 fork). **Date:** 2026-06-03.
**App:** kurate.org — academic-paper ranking platform (React + FastAPI + MongoDB Atlas).

This document is the single source of truth for three intertwined, long-running
problem areas. Read it fully before touching code. Sections:

1. Environment & how to observe production (you have NO shell access to prod)
2. The Stats-Page / `daily_stats` backfill saga (the big one)
3. arXiv timeouts & backoff logic
4. Production logging / duplicate-entry analysis
5. Exact pending fixes, file map, and verification commands
6. Open questions / decisions awaiting the user

---

## 1. ENVIRONMENT & HOW TO OBSERVE PRODUCTION

There are TWO environments:

| | Preview (dev) | Production (deployed) |
|---|---|---|
| URL | `https://analytics-fix-32.preview.emergentagent.com` (this is `REACT_APP_BACKEND_URL`) | `https://kurate.org` |
| Access | full shell + filesystem + can edit/restart | **public HTTP API only — NO shell, NO logs, NO filesystem** |
| Mongo | local/preview Mongo | **MongoDB Atlas** (separate DB) |
| Deploy | hot-reload (backend) / `yarn build`+restart (frontend, STATIC serve) | user redeploys manually |

**CRITICAL prod constraint:** Atlas/egress enforces a **~30s read timeout** that
you CANNOT change. Raising the driver `socketTimeoutMS` does NOT help (the limit
is in the egress/Atlas network layer, not the client). Any single MongoDB read
that runs >30s dies with `NetworkTimeout: ... read operation timed out`.

**You cannot fetch prod runtime logs.** The `deployment_agent` tool only returns
a static deployment-readiness scan (tried twice — it does NOT return runtime
logs). The ONLY way to observe production is the app's own admin API:

```bash
# Admin password (from /app/memory/test_credentials.md):
PASS=papersumo2025

# 1) Log in to PROD and get a token (LB round-robins across pods):
PTOK=$(curl -s -X POST https://kurate.org/api/admin/login \
  -H 'Content-Type: application/json' -d '{"password":"papersumo2025"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 2) Stats / seed state:
curl -s https://kurate.org/api/admin2/stats-overview -H "X-Admin-Token: $PTOK"
#    → look at: .seed_progress {status,done,total,pending,failed,last_error},
#               .backfill_status {reconciled,daily_matches,expected_matches,error},
#               .summary.total_matches

# 3) arXiv health per category:
curl -s https://kurate.org/api/admin/arxiv-health -H "X-Admin-Token: $PTOK"
#    → .categories[] {status, last_fetch_at, backoff_count, cooldown_seconds, last_error_reason}

# 4) System logs (events, NOT raw stdout — only what log_event() persisted):
curl -s "https://kurate.org/api/admin/system-logs?event=fetch_failed,fetch_cycle&hours=48&limit=400" \
  -H "X-Admin-Token: $PTOK"
```

**Leader/pod model:** multiple pods run; ONE is scheduler-leader (Mongo lease).
Only the leader runs the background loops (`_fetch_loop`, `_compare_loop`,
`_admin2_stats_loop`, etc.). The LB sends your HTTP request to a random pod, so:
- `POST /api/admin2/backfill` on a **non-leader** → queues a request doc
  (`admin2_lock {_id:"backfill_request"}`) for the leader loop to consume.
- on the **leader** → calls `_kick_backfill()` → `start_seed()` directly.
- To force-hit the leader, POST repeatedly until the response has `"leader":true`.

---

## 2. THE STATS-PAGE / `daily_stats` BACKFILL SAGA

### 2.1 The problem
The admin Statistics page reads a pre-aggregated materialized view
`daily_stats` (per-day, per-category buckets). On prod the **match count is stuck
at a stale ~422,838** while the true count is **~568,069** (`expected_matches`).
The one-time historical backfill that should correct this **kept dying on the
Atlas 30s timeout**, leaving `backfill_status.reconciled = false` with
`error: "NetworkTimeout: ... read operation timed out"`.

`daily_stats` schema (per doc):
```
{date:"YYYY-MM-DD", category:"cs.LG"|"_total", matches, input_tokens,
 output_tokens, cost, papers, summaries, summary_cost}
```
Plus meta docs in the SAME collection: `{_meta:"backfill_status"}`,
`{_meta:"model_stats"}`, and (new) `{_meta:"seed_progress"}`.
Per-model rollups live in `model_match_stats` / `model_summary_stats`.
Steady-state freshness is maintained by write-time `$inc` hooks
(`record_match_daily_stat` / `record_paper_daily_stat` / `record_summary_daily_stat`)
that own TODAY's bucket.

### 2.2 Attempts that FAILED (do not repeat these)
1. **Single full-collection aggregation** over all ~568k matches → NetworkTimeout.
2. **Dedicated Mongo client with high `socketTimeoutMS`** → still NetworkTimeout
   (the 30s limit is external egress, not the driver — proven repeatedly).
3. **Per-category loop, accumulate-in-memory, write-once** (index-backed per
   category, each <4s) → STILL failed on prod. **Root insight:** it was ONE long
   background job holding all progress in memory; any interruption (timeout, pod
   restart, deploy rollover, cancelled task) lost everything and froze the
   status. Smaller chunks never helped because all chunks ran inside a single
   invocation with no durable progress.

### 2.3 The current architecture: DURABLE DRIP SEED (implemented this session)
File: `/app/backend/routers/admin2_stats.py` (+ driver in `services/scheduler.py`).
Fully REPLACES the old `_run_backfill`. Design:

- **Progress is a DB doc**, `daily_stats {_meta:"seed_progress"}`:
  ```
  {status:"running"|"finalizing"|"reconciled"|"drift"|"completed_with_failures",
   pending:[cat,...], done:[cat,...], failed:[cat,...], total,
   model_avg:[{mk,in,out}], window_start, window_end,
   started_at, updated_at, finished_at, last_category, last_error, reason}
  ```
- **One category sealed per scheduler tick** (`seed_tick()`): aggregates that
  ONE category's matches+papers+summaries into its `(day,cat)` buckets, writes
  its per-category model totals to a temp collection `daily_stats_seed_models`
  (`_id="m|<cat>"` / `"s|<cat>"`), then moves it `pending→done`. Mid-category
  interruption just retries that one un-`done` category next tick — nothing
  sealed is lost. **Idempotent** (clears+`$set`s its own buckets; temp `$set`).
  After `_SEED_MAX_ATTEMPTS=3` a stuck category → `failed` so the seed still
  finalizes.
- **In-category chunking (growth-proof):** when a category's completed-match
  count > `_SEED_MATCH_CHUNK_THRESHOLD=50000`, its match aggregation is
  sub-divided into `_id` month-windows (`_build_match_windows`, open-ended
  first/last ranges → Σ windows == count, no drop/dup; a month boundary never
  splits a UTC day). Smaller categories use one fast scan.
- **Final pass** (`_seed_finalize`, runs when `pending` empties): computes
  `_total` per day from the SMALL `daily_stats` collection (NEVER `matches`),
  per-model rows from the temp collection, registrations, reconciliation badge;
  drops the temp collection. Cannot time out.
- **Driver:** `scheduler._admin2_stats_loop` — while a seed is `running` it calls
  `seed_tick()` every ~2s; otherwise it consumes manual requests / runs
  `reconcile_check` (~1h) / `ensure_fresh` (~30m). `start_seed()` is the single
  funnel (called by manual `POST /backfill`, cold start, drift).
- **Observability:** `stats-overview` exposes `seed_progress`. Frontend
  `AdminStatistics.jsx` has `SeedProgressBadge` ("Seeding · X/N categories" +
  bar) and a manual **Rebuild** button (`data-testid="rebuild-stats-btn"`).

### 2.4 PROVEN on PREVIEW
- Live seed reconciled **EXACTLY**: `daily=275,497 == expected=275,497`,
  match_cost `$2303.94`, summary_cost `$3258.29`, 6 match models + 11 summary
  models. **cs.RO (52,874) was split into 5 `_id` month-windows** on real data.
- Tests (`/app/backend/tests/`): `test_admin2_drip_seed.py` (4: resume-after-
  restart, idempotent reprocessing, forced cross-month chunking reconciles
  exactly, full-drain reconciles) + `test_admin2_rebuild_hardened.py` (3) + 28
  others → **35 pass**.

### 2.5 PROD FAILURE after deploy — and the fix (THIS is the key live issue)
The user deployed the drip seed. **It did NOT start on prod.** Observed via the
prod admin API: `seed_progress = None`, `backfill_status` still the stale
422,838/568,069 with the old NetworkTimeout error, even after force-hitting the
leader (`POST /backfill` → `{"leader":true,"started":true}`) — yet
`seed_progress` was NEVER written.

**Root cause (a flaw I introduced):** `start_seed()` performed heavy GLOBAL Atlas
reads — `_compute_model_avg()` (aggregation over the whole `papers` collection)
and `_ensure_summary_keys()` — BEFORE writing the `seed_progress` checkpoint. On
prod those reads NetworkTimeout, so `start_seed` threw before the seed became
durable. The per-category WORK was durable, but INIT/FINALIZE/DRIFT paths still
touched big collections. (`started:true` only means `_kick_backfill` scheduled
the task; the awaited `start_seed` then died.)

**FIX implemented this session in PREVIEW (NOT yet deployed to prod):**
- `start_seed()` now writes the `seed_progress` checkpoint FIRST (durable +
  crawling immediately). Model averages + summary-key migration are deferred to a
  **non-blocking** best-effort `_seed_enrich()` task; if they time out the seed
  still seals every category and untracked summaries fall back to global
  `AVG_IN/AVG_OUT` (match counts/costs unaffected). `_id` window probes use
  `max_time_ms=8000`.
- `_compute_model_avg()` `maxTimeMS` lowered 60000→20000 (fail-fast under the 30s
  egress, clean error instead of a hang).
- `_seed_finalize()` reconcile count is now bounded (`maxTimeMS=20000`) and
  best-effort: Σ daily is authoritative after a clean seal; `expected` defaults
  to `daily` if the count times out.
- `reconcile_check()` now KICKS a seed on the CHEAP signal "no reconciled seal
  yet" (cold/failed/stale `backfill_status.reconciled != true`) WITHOUT counting
  `matches` — that count was the very read that NetworkTimeouts and prevented the
  auto-kick. Only once reconciled does it run a bounded drift cross-check
  (skipped gracefully if slow).
- Preview tests re-run after the fix: drip + hardened suites pass.

**ACTION REQUIRED:** user must REDEPLOY for this fix to reach prod. On the next
deploy, the leader's first `reconcile_check` should kick `start_seed("auto_reseed")`
within ~1–2 min (no matches count needed); `seed_progress` should appear as
`running` and crawl one category per tick; then the green Reconciled badge with
`daily_matches ≈ 568,069`. If it still stalls, see §6 open questions.

### 2.6 Residual risk on prod
- `_compute_model_avg` will likely keep timing out on prod (large `papers`),
  so untracked-summary pricing uses the fallback average → `summary_cost`
  slightly approximate. Match counts (the headline 422k→568k fix) are unaffected.
  If exact summary cost matters, redesign `_compute_model_avg` to be per-category
  or sampled (currently it's a single global papers scan).
- Per-category match aggregations carry `maxTimeMS=60000` (> 30s egress). With
  windowing each window is small, so fine; but if a single category is huge AND
  unwindowed (count ≤ 50k threshold but slow), it could time out and that
  category would land in `failed`. Consider lowering the chunk threshold or the
  per-aggregation maxTimeMS if `failed` categories appear on prod.

---

## 3. arXiv TIMEOUTS & BACKOFF LOGIC

File: `/app/backend/services/arxiv.py` (fetch + throttle + backoff),
`/app/backend/services/scheduler.py` (`_fetch_loop` + DB-persisted per-category
backoff in `settings`).

### 3.1 What exists (and works)
- **Global throttle** `_MIN_INTERVAL = 3.0s` between ANY two arXiv requests in a
  process (`_throttle()` under a lock). Matches arXiv's documented ≥3s rule. ✅
- **Per-request retry** with exponential backoff honoring `Retry-After` on
  429/5xx (`_parse_retry_after`, `_BASE_BACKOFF=5.0`, jitter), sleep OUTSIDE the
  throttle lock.
- **DB-persisted per-category backoff** in `settings`: `fetch_backoff_until_<cat>`
  / `fetch_backoff_count_<cat>`, schedule 15m→30m→1h→2h→cap (≈4h). The fetch loop
  skips a category while it's cooling down. ✅
- Surfaced via `GET /api/admin/arxiv-health` (status: healthy / cooling_down).

### 3.2 PRODUCTION reality — ROOT-CAUSE classification (kurate.org admin API, 72h)
**181 `fetch_failed` events. The single `reason` field is MISLEADING — classify by
the actual error `detail` string:**

| Root cause (from `detail`) | Count | What it really is |
|---|---|---|
| `ARXIV_429` (`429` + `export.arxiv.org`) | 116 (64%) | genuine arXiv rate-limiting |
| `HTTP_TIMEOUT` (bare `ReadTimeout`) | 53 (29%) | the **arXiv HTTP** call timed out at 30s (arXiv slow/unresponsive) |
| **`ATLAS_MONGO_TIMEOUT`** (`...mongodb.net:27017: The read operation timed out`) | **10 (5.5%)** | **a MongoDB ATLAS read inside the fetch cycle timed out — NOT arXiv at all** |
| OTHER | 2 | misc |

The code labels these as `reason`: `rate_limit`=118, `fetch_error`=63. **The
`fetch_error` bucket conflates TWO unrelated causes** — arXiv HTTP ReadTimeouts
(53) AND Atlas Mongo read timeouts (10). My earlier handover wrongly called the
whole `fetch_error` bucket "arXiv slow"; that was incorrect.

- Backoff IS firing correctly (~11 categories `cooling_down`, `backoff_count`→4,
  ~2h cooldowns; not hammering). ✅
- Successful cycles exist (`hep-ph ok=true`) → partial throttling, not total.
- **`math.OC` / `math.PR` (NEVER fetched, stuck at 0 papers):** their failures are
  a MIX — `math.OC`: 7×429 + 1×Atlas-timeout; `math.PR`: 5×429 + 2×HTTP-timeout +
  1×Atlas-timeout. So the user's hypothesis is **correct for the specific rows in
  the screenshot** (their two most-recent failures at 21:37–21:38 were Atlas
  read timeouts: `customer-apps-shard-00-02.o0opyp.mongodb.net:27017: The read
  operation timed out`), even though arXiv 429 is still the majority cause for
  those categories over the full window.

### 3.3 TWO independent root causes (don't conflate them)

**Cause A — arXiv 429 rate-limiting (116, the majority).** `arxiv.py` (~line 116)
creates `httpx.AsyncClient()` with **NO `User-Agent`** → default `python-httpx/x.y`.
arXiv aggressively 429s generic UAs from datacenter IPs. **Verified live:** same
pod + descriptive UA → **HTTP 200 in 0.4s**. The 3s pacing is already correct.
The 53 HTTP ReadTimeouts are also arXiv-side (arXiv slow); a descriptive UA + a
slightly larger timeout should reduce both.

**Cause B — Atlas read timeout inside the fetch cycle (10, mislabeled as arXiv).**
NEW FINDING, confirmed by reading the code. On EVERY fetch cycle, before storing
papers, `scheduler.py:1128-1144` runs an **UNBOUNDED GLOBAL scan of the whole
`papers` collection**:
```python
async for doc in db.papers.find(
    {"arxiv_id_base": {"$exists": True}, "is_latest_version": {"$ne": False}},
    {"_id":0, "arxiv_id":1, "arxiv_id_base":1, "current_version":1, "id":1}):
    existing_bases[doc["arxiv_id_base"]] = {...}   # loads EVERY arXiv paper into a dict
```
`$exists`+`$ne` are non-selective → this streams ~the entire (100k+ on prod)
`papers` collection into memory **once per category per cycle**. When Atlas is
slow, this cursor iteration exceeds the 30s read limit → `NetworkTimeout` → caught
by the broad STEP-1 `try/except` (scheduler.py:1239-1254) and **mislabeled**
`"ArXiv/source fetch failed (fetch_error)"`. A SECOND scan at line 1146
(`{"categories.0": category}`, and `{}` = whole collection for `chemrxiv.*`) has
the same risk. This is the SAME anti-pattern as the stats bug: an unbounded global
read that times out on Atlas. It is intermittent (10/181) because it only trips
when Atlas latency is high, but it's a real, independent bug — and it's why some
"arXiv" failures are actually database failures.

**Why it only surfaced recently (not "there all along"):**
- The `existing_bases` global scan + `arxiv_id_base`/`is_latest_version` fields
  were introduced **2026-04-18 → 05-05** by the version-aware revision refactor
  (git: `-S "existing_bases"`/`"is_latest_version"`). Before that, dedup used only
  the category-scoped scan at line 1146. So it's ~7 weeks old, not original.
- The filter is **non-selective — it matches ~49% of `papers`** (5,231/10,674 on
  preview) and streams those docs into a dict every cycle/category. Time scales
  with collection size: preview (~10k) finishes <20s; prod (100k+) crosses the
  30s Atlas ceiling. The code didn't change — the DATA grew past the cliff.
- Intermittency (10/181) = it sits right on the 30s boundary, tipping over only
  under concurrent Atlas load — including from the failed stats backfills hammering
  the SAME cluster in the same window. The two issues fed each other.
- There IS an `arxiv_id_base_1` index, but it can't help a query matching half the
  collection. Binding the query to `$in` on the ≤2000 just-fetched bases makes it
  selective → uses that index → constant-time regardless of collection size.

### 3.4 FIXES

**For Cause A (arXiv 429) — ✅ IMPLEMENTED (Jun 3):**
1. Set descriptive `User-Agent: kurate.org/1.0 (+https://kurate.org; mailto:admin@kurate.org)` on all `httpx.AsyncClient` calls in `arxiv.py`.
2. Bumped timeout 30→45s to cut HTTP ReadTimeouts.

**For Cause B (Atlas timeout in fetch) — ✅ IMPLEMENTED (Jun 3):**
1. Replaced the global `existing_bases` scan (scheduler.py) with a BOUNDED `$in` query keyed by bases extracted from just-fetched `raw_papers`. Added `max_time_ms=20000`.
2. Fixed chemrxiv `{}` unbounded scan → now always category-scoped (`{"categories.0": category}`). Added `max_time_ms=20000`.
3. **Fixed mislabeling** in the exception handler — MongoDB timeouts now classified as `reason="db_timeout"` (distinct from `rate_limit`/`fetch_error`).
- Expected after deploy: `rate_limit` failures drop sharply (UA), `db_timeout` failures disappear (bounded query), and `math.OC`/`math.PR` finally ingest.

---

## 4. PRODUCTION LOGGING / DUPLICATE-ENTRY ANALYSIS

Logging schema: `/app/backend/core/memlog.py` (`log_event`/`log_event_nowait`
write to `system_logs`). The user reports "many entries are still duplicated."
(Analyzed on PREVIEW — same code as prod.)

### 4.1 Findings
- **MAIN culprit — `convergence` event spam:** 322 of 345 non-mem events in 6h
  are `convergence` ("All goals met for N categories"), **median gap exactly
  60s**. `scheduler.py:782` logs it on EVERY compare-loop cycle while goals stay
  met, not just on transition. This is almost certainly the perceived "duplicates".
- **`[ADMIN2] durable seed started (kick)` double-fires** (same millisecond):
  `_kick_backfill()` does `asyncio.ensure_future(_kick())` and two concurrent
  `stats-overview` polls both pass the "not running" guard → two `start_seed`s
  race. Also `?force=true` kicks a seed on every refresh.
- **Schema inconsistency:** 61 `convergence` events have `pod_id=null /
  pod_role=null` — that `log_event` path isn't attaching pod metadata.

### 4.2 Proposed logging fixes (awaiting user choice a/b/c)
- (a) convergence → log only on the TRANSITION into "all goals met" (removes ~95%
  of volume). **Highest impact.**
- (b) make `_kick_backfill` atomic (dedupe concurrent kicks) and stop
  `?force=true` from re-seeding (force should only refresh the read).
- (c) ensure `log_event` always attaches `pod_id`/`pod_role`.
- (d) clear the `zz.regress` test-residue backoff keys from `settings`.

---

## 5. FILE MAP, DATA MODELS, VERIFICATION

### Key files
| File | What |
|---|---|
| `backend/routers/admin2_stats.py` | Durable drip seed: `start_seed`, `seed_tick`, `_seed_one_category`, `_seed_summary_for_category`, `_seed_finalize`, `_compute_model_avg`, `_seed_enrich`, `_build_match_windows`, `reconcile_check`, `ensure_fresh`, `_run_backfill`, `_kick_backfill`, `GET /stats-overview`, `POST /backfill`. SSOT for stats. |
| `backend/services/scheduler.py` | Leader election, `_fetch_loop`(+inner ~455), `_compare_loop` (convergence log ~782), `_admin2_stats_loop` (drip driver), per-category arXiv backoff. |
| `backend/services/arxiv.py` | arXiv fetch (~116 missing UA), `_throttle`, `_MIN_INTERVAL`, retry/backoff. |
| `backend/core/memlog.py` | `log_event` schema. |
| `backend/core/config.py` | `db`, `MONGO_URL`, `DB_NAME`. |
| `frontend/src/components/AdminStatistics.jsx` | `SeedProgressBadge`, `BackfillBadge`, `triggerRebuild`, Rebuild button. (STATIC build: `cd /app/frontend && yarn build` then `sudo supervisorctl restart frontend`.) |
| `backend/tests/test_admin2_drip_seed.py`, `test_admin2_rebuild_hardened.py`, `test_admin2_stats.py`, `test_admin2_refactor.py` | Regression suites. |

### Data models / collections
- `matches`: `{_id, id, created_at, primary_category, completed, failed, model_used:{provider,model}, tokens:{input_est,output_est}}`. Index `primary_category_1_completed_1_failed_1`. ~568k on prod.
- `papers`: `{_id, added_at, categories:[...], summary_tokens:{mk:{input,output}}, summaries:{mk:text}, summary_keys:[mk]}`.
- `daily_stats`: per-(day,category) buckets + meta docs (`backfill_status`, `seed_progress`, `model_stats`).
- `daily_stats_seed_models`: TEMP per-category model contributions during a seed (dropped at finalize).
- `model_match_stats` / `model_summary_stats`: per-model rollups.
- `settings {key:"global"}`: `active_categories`, `paused`, `fetch_interval_hours`, `fetch_backoff_until_<cat>`, `fetch_backoff_count_<cat>`, `last_fetch_at_*`.
- `admin2_lock`: distributed lease + `{_id:"backfill_request"}` queue marker.
- `system_logs`: `{ts, level, event/label, detail, category, success, reason, pod_id, pod_role}` (7-day TTL).

### Verification commands
```bash
# Backend regression (preview):
cd /app/backend && python -m pytest tests/test_admin2_drip_seed.py \
  tests/test_admin2_rebuild_hardened.py tests/test_admin2_stats.py \
  tests/test_admin2_refactor.py -q

# Live seed on preview (kick + watch crawl):
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)
TOK=$(curl -s -X POST "$API/api/admin/login" -H 'Content-Type: application/json' \
  -d '{"password":"papersumo2025"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -X POST "$API/api/admin2/backfill" -H "X-Admin-Token: $TOK"
curl -s "$API/api/admin2/stats-overview" -H "X-Admin-Token: $TOK" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('seed_progress'));print(d.get('backfill_status'))"

# Live arXiv reachability from a pod (proves UA hypothesis):
python3 -c "import httpx;r=httpx.get('https://export.arxiv.org/api/query?search_query=cat:cs.RO&max_results=2',timeout=30,follow_redirects=True,headers={'User-Agent':'kurate.org/1.0 (mailto:test@kurate.org)'});print(r.status_code)"
```

### Admin credentials
`/app/memory/test_credentials.md` → admin password `papersumo2025` (no email).

---

## 6. OPEN QUESTIONS / DECISIONS AWAITING THE USER

1. **arXiv fix — two parts** (see §3.4):
   - Cause A (429s): need a **contact email** for the descriptive `User-Agent`.
   - Cause B (Atlas timeout mislabeled as arXiv): bound the global `papers` scan
     in the fetch path (`scheduler.py:1129`/`1146`) + add `max_time_ms` +
     reclassify Mongo timeouts as `reason="db_timeout"`. Confirm go-ahead.
2. **Logging fixes scope** — which of (a)/(b)/(c)/(d) in §4.2 (recommend: all).
3. **Redeploy** — the §2.5 stats robustness fix is already in preview but MUST be
   redeployed to fix prod. Decide whether to bundle §3.4 (A+B) + §4.2 into one
   redeploy.

### If the prod seed STILL doesn't start after redeploying §2.5
Diagnose in this order (all via the prod admin API + reasoning, since no logs):
- Is the leader loop alive? `stats-overview` responding fast ≠ background loop
  alive. Force-hit the leader with `POST /backfill` (`"leader":true`) and re-poll
  `seed_progress` after ~5s — if it appears `running`, the loop is alive.
- If `seed_progress` appears but never advances (`done` stuck at 0): the leader
  `_admin2_stats_loop` is wedged. Check whether `ensure_indexes()` at loop start
  is hanging on the big `matches` collection (it runs once before the while loop;
  consider making it best-effort/bounded too).
- If `seed_progress` never appears even on the leader: some other awaited call in
  `start_seed` is still blocking before the checkpoint write — re-audit that the
  checkpoint `update_one` truly runs first (it now does in preview code).
- Consider adding a tiny **leader-liveness heartbeat** to `seed_progress`
  (`loop_tick_at`) so prod observability shows the loop is alive without logs.

### Strategic note for a more capable model
Every failure in this saga traces to ONE principle: **on prod, no single
MongoDB operation may exceed ~30s, and no critical state transition may depend on
such an operation succeeding.** The durable drip seed embodies this for the
per-category WORK; the §2.5 fix extends it to INIT/FINALIZE/DRIFT. When adding
ANY new feature that reads `matches`/`papers` in bulk, assume it WILL time out on
prod and make it (a) bounded (`maxTimeMS` < 30s), (b) chunked/durable, and (c)
best-effort with a safe fallback. The arXiv issue is the mirror image on the
egress side: external services throttle datacenter IPs — always send a
descriptive User-Agent and pace requests.
