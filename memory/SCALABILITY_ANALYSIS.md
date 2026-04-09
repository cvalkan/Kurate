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

### ~~1. Leaderboard Cache Matches Aggregation — Event Loop Contention~~ ✅ FIXED (Apr 7, 2026)
**Was:** The matches `$group` aggregation in `_refresh_cache` scanned ALL matches (150K+) every refresh, taking 0.1s standalone but 8.7s under event loop contention with concurrent LLM calls. Caused a 2.5GB memory spike.

**Fix:** Replaced with incremental in-memory counters (`_incr_match_counts`, `_incr_failed_counts`). Seeded from DB once at startup via `_seed_match_counters()`. Bumped atomically per match via `bump_match_counter()` called from `run_comparison_round`. `_refresh_cache` now reads the counters in O(1) — no matches collection scan.

**Result:** `_refresh_cache` dropped from **13.2s → 0.3s** (43x faster). The 2.5GB memory spike scenario is eliminated.

**Memory cost:** ~3MB for 43K match counter strings. Scales linearly — 500K matches ≈ 37MB.

### ~~2. `_select_pairs` → `_get_compared_opponents` — One Query Per Needy Paper~~ ✅ FIXED (Apr 7, 2026)
**Was:** For each needy paper, `_get_compared_opponents` built a `pair_keys` array of all candidates and did a `$in` query against the `dedup_pair` index. With N needy papers, that was N separate DB queries.

**Fix:** Single query loads ALL `dedup_pair` strings for the category into an in-memory set at the start of `_select_pairs`. All pair-existence checks are then O(1) set lookups. The top-K cross-match check also uses the same set.

**Result:** DB queries in `_select_pairs` dropped from **N+1 → 1**. Verified with manual comparison round on preview (5 matches, 0 errors).

**Memory cost:** ~3MB for cs.RO (43K dedup_pair strings). Same scaling as #1.

### ~~2b. Goals Check Amplification — 14 Categories × Every Cycle~~ ✅ FIXED (Apr 8, 2026)
**Was:** `_check_goals_met` was called for all 14+ categories every compare loop cycle (every ~2-25s). Each call loaded all rankings + queried papers collection for matchability. Additionally, `update_tournament_stats` called `_check_goals_met` for ALL 17 tournament categories (including inactive ones) and ran `count_documents` on the matches collection per category — 34 DB queries per cycle just for stats.

**Root cause analysis:** Production memory grew from 490 MB (fresh restart) to 1,377 MB over hours. Logs showed `_check_goals` was the dominant memory amplifier: 14 categories checking goals simultaneously caused rankings data from multiple categories to stack in memory before GC. The 60s TTL cache expired for ALL categories simultaneously (populated at the same time → expired at the same time), causing periodic recomputation storms.

**Fix (three parts):**
1. **Two-tier cache TTL:** Goals MET (True) → cached indefinitely until explicitly invalidated. Goals NOT MET (False) → 60s TTL. Only data mutations (new matches, new papers, settings change) invalidate met categories.
2. **Snapshot-based staleness detection:** Each cache entry stores `{papers: N, matches: M}` at cache time. On read, compares against current counts — if they differ, the cache is stale even without explicit invalidation. Protects against future code paths that forget to call `invalidate_goals_cache()`. Zero overhead when counts match (two integer comparisons).
3. **`update_tournament_stats` decoupled from goals computation:** No longer calls `_check_goals_met` — reads cached result if available. Match counts read from incremental counters instead of 17 `count_documents` queries.

**Result:** Goals checks per cycle dropped from **10-14 → 0.04** (107 cycles, 4 checks total — only the single unmet category). Memory flat at **382 MB across 197 cycles** (was growing to 1,377 MB). DB queries per cycle from tournament stats dropped from **34+ → 0**.

**Safeguard:** If any future code path adds papers/matches without calling `invalidate_goals_cache()`, the snapshot mismatch fires a log warning and auto-invalidates: `Goals cache stale for cs.RO: papers 207→208, matches 9224→9225`.

### ~~2c. Rerank Memory Stacking — Sequential Reranks + Single-Pass + GC~~ ✅ FIXED (Apr 9, 2026)
**Was:** `rerank_category_light` ran inside concurrent comparison rounds (`asyncio.gather`), causing multiple reranks to overlap in memory. Each rerank loaded rankings twice (once for sorting, once for gap scores via `_refresh_derived_fields`). Community likes collection was scanned on every rerank. CPython/glibc held freed pages, so RSS never dropped after spikes. Production RSS grew to 2,465 MB during rerank storms.

**Fix (five parts):**
1. **Sequential reranks:** Moved reranks out of concurrent `run_comparison_round` via `skip_rerank` flag. Compare loop batch handler runs reranks one-at-a-time after all rounds complete.
2. **Single-pass rerank:** Merged `_refresh_derived_fields` into `rerank_category_light` — loads rankings ONCE, computes ranks + gap scores + writes in a single bulk operation (was 2 DB scans + 2 bulk writes).
3. **`force_gc()` after every rerank:** `gc.collect()` + `malloc_trim(0)` releases freed pages to OS between sequential reranks.
4. **Shared helpers:** Extracted `_compute_ts_elo`, `_compute_ranks`, `_compute_gap_scores`, `_extract_ai_rating` — both light and heavy rerank use identical logic. Heavy version now includes TrueSkill normalization (was missing).
5. **Removed community_likes:** Eliminated full `alphaxiv_likes` collection scan from every rerank (obsolete experiment).

**Result:** Production RSS dropped from **1,580 MB → 432 MB** (73% reduction). Stable across 800+ cycles with zero growth.

### ~~2d. Pair-Exhaustion Detection — Stalled Categories~~ ✅ FIXED (Apr 9, 2026)
**Was:** cs.SI (all pairs exhausted, 0 new matches possible) kept starting futile comparison rounds every cycle, loading paper summaries each time.

**Fix:** When `_select_pairs` returns 0 pairs, mark the category as pair-exhausted via `_mark_pair_exhausted()`. The compare loop skips exhausted categories until paper/match counts change (auto-invalidates on new data). Uses the same snapshot pattern as the goals cache.

**Result:** cs.SI stops cycling after the first 0-pair round. No memory waste from futile rounds.

### ~~2e. Obsolete SI Rating Backfill Removed~~ ✅ FIXED (Apr 9, 2026)
**Was:** Every startup loaded ALL papers' full summary text (~75 MB for 5,100 papers) to parse AI ratings — a one-time migration that was still running on every restart.

**Fix:** Removed. All papers now have `ai_ratings_by_model` populated during summary generation.

**Result:** Startup RSS spike reduced by ~90 MB.

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
| **`_refresh_cache`** | **Incremental counters, O(1) — no match scan** |
| **`_select_pairs` pair checks** | **In-memory dedup set, O(1) per pair** |
| **`_check_goals_met` (met cats)** | **Cached indefinitely with snapshot-based staleness detection** |
| **`update_tournament_stats`** | **Reads cached goals + incremental match counters — 0 DB queries** |
| **`rerank_category_light`** | **Single-pass, single bulk write, sequential execution with GC** |
| **Pair-exhausted categories** | **Skipped entirely until new data arrives** |

## DB Indexes (as of Apr 7, 2026)

### matches (150K+ docs)
- `pair_dedup_idx`: `(primary_category, dedup_pair)` — pair existence checks + dedup set loading
- `primary_category_1_completed_1_failed_1_mode_1` — filtered match counts (used by counter seed)
- `paper1_id_1`, `paper2_id_1` — per-paper match lookups
- `created_at_1` — recent matches

### rankings (5K+ docs)  
- `category_1_score_-1` — leaderboard sorting
- `category_1_comparisons_-1`, `category_1_ts_score_-1` — alternative sorts
- `paper_id_1` — single-paper lookups

### papers (5K+ docs)
- `categories_summaries` — matchable paper filtering
- `id_1`, `arxiv_id_1` — lookups

## Scaling Projections (updated Apr 8, 2026)

| Metric | Current | 10K papers | 50K papers | 100K papers |
|---|---|---|---|---|
| Rankings reads (indexed) | <1ms | <5ms | <10ms | <20ms |
| Matches per category | 43K | 200K | 1M | 5M |
| **`_refresh_cache`** | **0.3s** | **~0.5s** | **~1s** | **~2s** |
| `_check_goals_met` (met cats) | 0ms (cached indefinitely) | 0ms | 0ms | 0ms |
| `_check_goals_met` (unmet cats) | ~50ms (60s TTL) | ~100ms | ~200ms | ~500ms |
| **`_select_pairs` (50 needy)** | **<0.5s** | **<1s** | **<2s** | **<5s** |
| `update_tournament_stats` | 0ms (cached counters) | 0ms | 0ms | 0ms |
| `seed_rankings` (gap-fill) | <1s | <1s | <1s | <1s |
| `seed_rankings` (full, if needed) | ~2s | ~10s | ~50s | OOM |
| Startup memory spike | ~360MB | ~400MB | ~500MB | ~600MB |
| Steady-state memory | ~432MB | ~500MB | ~600MB | ~750MB |

**Production verified (Apr 9, 2026):** 15 categories, ~5,100 papers, 86K+ matches. RSS stable at 432 MB across 800+ compare loop cycles. Previous baseline was 1,580 MB.
