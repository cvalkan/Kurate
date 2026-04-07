# Scalability Analysis & Fixes
*Last updated: April 7, 2026*

## Current Scale

| Metric | Value |
|---|---|
| Active categories | 14 |
| Total papers (rankings) | 4,935 |
| Largest category (cs.RO) | 1,677 papers |
| Total matches | 142,456 |
| Largest category matches (cs.RO) | 41,983 |
| Max possible pairs (cs.RO) | 1,405,326 |
| Steady-state memory | ~750-850MB |
| Memory limit | 2,048MB |

## Production Memory Spike (Apr 7, 2026)

**Observed:** 2,524MB spike at 04:09 UTC (exceeded 2GB limit) during normal operation (no deploy).

**Root cause:** Concurrent execution of `_refresh_cache` (scanning 142K matches) + `_check_goals_met` (loading rankings for 14 categories) + comparison round data in memory. The event loop contention caused the matches aggregation (normally 0.1s standalone) to take 8.7s, holding data in memory far longer than necessary.

**Timeline:**
```
04:06:50  785MB — comparison_round done → triggers notify_data_changed()
04:07:00  -----   _refresh_cache starts (scans 142K matches)
04:07:39 1125MB — _check_goals_met loads rankings concurrently  
04:08:57 2007MB — both still running, data accumulating
04:09:25 2524MB — PEAK (exceeded limit)
04:10:03 1178MB — cache refresh completes, memory drops
```

## Fixes Applied

### Fix #1: Gap-Fill Startup (replaces full reseed)
**Before:** Every deploy that detected 1 new paper triggered `seed_rankings` for the entire category — loading ALL matches into memory (42K matches for cs.RO = ~50MB) and recomputing all scores.

**After:** Compares paper IDs vs ranking IDs. Creates blank entries only for missing papers via `insert_ranking_for_paper`. No match loading. Falls back to full reseed only if >20% of papers are unranked (catastrophic recovery) or rankings collection is empty (cold start).

**Why this is safe:** The ghost match fix (Apr 5) ensures `update_rankings_for_match` auto-creates ranking entries on first match. Rankings can't fall out of sync anymore, so the full reseed's purpose (fixing drift) is no longer needed under normal operation.

**Impact:** Eliminates ~50MB memory spike per deploy for cs.RO. Larger categories would save more.

**Status:** Implemented, tested with simulated missing paper. ✅

### Fix #2: Leaderboard Cache Optimization
**Before:** `_refresh_cache` ran after every comparison round (10s debounce) and computed:
- Failed match scan (all matches)
- **Per-category progress for 14 categories** (loading all rankings + N² cross-match queries = ~630 DB queries)
- PDF/storage stats aggregation
- Summary stats, tags, rating stats, archives

Total: ~9.5s per refresh, triggered every ~12s during active matching.

**After:**
1. **Removed dead `_progress` computation** — was loading all rankings for 14 categories every refresh. The result was stored in cache but **never read by any endpoint** (the dedicated `/api/admin/progress` endpoint computes fresh per-request). Saves ~5s and significant memory.
2. **Increased debounce from 10s to 30s** — remaining cache data (tags, PDF stats, failed counts) is slow-changing. Reduces refresh frequency by 3x.

**Impact:** Cache refreshes run ~3x less often and do ~50% less work. Reduces the probability of concurrent overlap with the compare loop.

**Status:** Implemented, verified no consumers of `_progress` cache. All endpoints return 200. ✅

### Fix #3: Goals Check Cached 60s
**Before:** `_check_goals_met` loaded all rankings for each of 14 categories on every scheduler cycle (~every 60s). That's 14 DB queries × ~500ms each = ~7s of DB reads per minute, holding rankings data in memory concurrently with `_refresh_cache`.

**After:** Results cached per-category for 60s with explicit invalidation:
- Invalidated when matches complete (`run_comparison_round` → `invalidate_goals_cache(category)`)
- Invalidated when new papers fetched (`run_fetch_cycle` → `invalidate_goals_cache(category)`)
- Worst case of stale "not met": 1 extra no-op cycle (no LLM cost — `_select_pairs` independently validates pairs)

**Impact:** 
- Fresh call: 517ms → Cached call: 0.0ms
- Saves ~7s of DB reads per minute during steady state
- Reduces concurrent memory load (no rankings data held during cache refresh)

**Status:** Implemented, verified cache hit/miss/invalidation behavior. ✅

## Remaining Bottlenecks (by priority)

### 1. Leaderboard Cache Matches Aggregation — Event Loop Contention
**What:** The matches `$group` aggregation in `_refresh_cache` takes 0.1s standalone but 8.7s when running concurrently with the scheduler's LLM calls. This is an async I/O scheduling issue — MongoDB queries queue behind long-running LLM HTTP calls.

**Current mitigation:** 30s debounce reduces overlap frequency. Dead progress computation removed.

**Future fix:** Run the cache refresh in a separate thread (not the async event loop) to avoid contention with LLM calls. Or maintain match counts incrementally (bump a counter on each new match).

**Scales to:** Current scale is fine with debounce. Would need incremental counters at 500K+ matches.

### 2. `_select_pairs` → `_get_compared_opponents` — One Query Per Needy Paper
**What:** For each needy paper, builds a `pair_keys` array of all candidates and does a `$in` query. With 10K papers, each `pair_keys` has 10K entries.

**Current state:** Fine at current scale (<50 needy papers per cycle for mature categories).

**Future fix:** Batch into a single aggregation query. The `pair_dedup_idx` index supports this.

**Scales to:** Breaks at ~1K+ needy papers (fresh large categories).

### 3. `seed_rankings` Full Match Load — Catastrophic Recovery Path
**What:** The gap-fill fallback (>20% unranked) still loads ALL matches via `collect_all`. For cs.RO: 42K matches in memory.

**Current state:** Rarely triggered (only on catastrophic data loss).

**Future fix:** Use MongoDB aggregation pipeline instead of Python-side `compute_leaderboard`.

**Scales to:** Would fail at 500K+ matches per category (OOM).

### 4. `reconcile_rankings` — N Papers × 1 Query Each
**What:** Manual admin tool. For each paper, runs `count_documents` + `find` query. cs.RO: 3,354 queries.

**Current state:** Manual tool, runs rarely. Acceptable.

**Future fix:** Single aggregation to compute per-paper match counts.

### 5. PDF/Storage Stats — `$strLenCP` on Full Text
**What:** `_refresh_cache` computes `$strLenCP` on `full_text` field for every paper. MongoDB reads the entire field to count characters.

**Current state:** Fast enough (~0.1s on preview) because MongoDB caches frequently accessed data.

**Future fix:** Store `full_text_chars` as a field on the paper document, updated on PDF download.

## What Scales Well (no changes needed)

| Component | Why it scales |
|---|---|
| `dedup_pair` lookups | Compound index, O(1) per pair |
| Rankings reads (leaderboard) | Compound indexes on `(category, score)` etc. |
| Match inserts | Single `insert_one`, no contention |
| Model analysis live path | Reads from rankings only, no matches |
| Progress endpoint | Per-request from rankings (indexed) |
| `update_rankings_for_match` | Single `find_one_and_update` with index |
| Ghost match prevention | Auto-creates ranking on first match, no drift |

## DB Indexes (as of Apr 7, 2026)

### matches (142K docs)
- `pair_dedup_idx`: `(primary_category, dedup_pair)` — pair existence checks
- `primary_category_1_completed_1_failed_1_mode_1` — filtered match counts
- `paper1_id_1`, `paper2_id_1` — per-paper match lookups
- `created_at_1` — recent matches

### rankings (4,935 docs)  
- `category_1_score_-1` — leaderboard sorting
- `category_1_comparisons_-1`, `category_1_ts_score_-1` — alternative sorts
- `paper_id_1` — single-paper lookups

### papers (5K+ docs)
- `categories_summaries` — matchable paper filtering
- `id_1`, `arxiv_id_1` — lookups

## Scaling Projections

| Metric | Current | 10K papers | 50K papers | 100K papers |
|---|---|---|---|---|
| Rankings reads (indexed) | <1ms | <5ms | <10ms | <20ms |
| Matches per category | 42K | 200K | 1M | 5M |
| `_refresh_cache` | 9s | ~15s | ~60s | OOM without incremental |
| `_check_goals_met` (cached) | 0ms | 0ms | 0ms | 0ms |
| `_select_pairs` (50 needy) | <1s | <2s | <5s | <10s |
| `seed_rankings` (gap-fill) | <1s | <1s | <1s | <1s |
| `seed_rankings` (full, if needed) | ~2s | ~10s | ~50s | OOM |
| Startup memory spike | ~360MB | ~400MB | ~500MB | ~600MB |
| Steady-state memory | ~800MB | ~900MB | ~1.2GB | needs fixes |
