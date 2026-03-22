# Kurate.org — Scaling & Architecture Notes

## Memory Scaling (Updated Mar 22, 2026)

### Current State
- **Per-paper memory**: ~8.6KB (down from ~67KB — summaries excluded from cache via aggregation pipeline)
- **Per-match memory**: ~2.2KB  
- **Dedup**: Insert-time via unique `dedup_hash` index (no startup scan)
- **Safe limit**: ~50K papers in 8GB container (up from ~2-5K)

### Scaling Path to 100K+ Papers

**Why Options 1 & 2 alone don't reach 1M**: The real bottleneck isn't the refresh spike — it's the **steady-state cache** holding all papers, matches, match indices, and per-category leaderboard entries permanently in memory. At 1M papers + 30M matches, this alone is ~75GB regardless of how cleverly you refresh it.

| Approach | What it solves | Limit (8GB) | Limit (16GB) | Complexity | Effort |
|---|---|---|---|---|---|
| Current (post Mar 22 fixes) | Dedup + summaries out of memory | ~50K | ~100K | Done | Done |
| Option 1: Per-category streaming | Refresh 2x peak | ~100K | ~200K | Medium | ~1 weekend |
| Option 2: Incremental updates | Refresh O(1) per match | ~100K | ~200K | High | ~1 week |
| **Option 3: DB-backed leaderboard** | **Eliminates in-memory cache entirely** | **Unlimited** | **Unlimited** | **Medium-High** | **~1 week** |

#### Option 1: Per-Category Streaming Refresh (Target: 100-200K papers)
The current bottleneck is `_refresh_cache()` loading ALL papers + matches into memory simultaneously. At 50K+ papers this exceeds 8GB during the 2x peak (old + new cache coexist during swap).
- **Approach**: Stream papers and matches per-category instead of loading all at once. Only one category's data in memory at a time.
- **Complexity**: Medium. Requires restructuring `_refresh_cache` to iterate categories sequentially, each loading/computing/storing independently.
- **Estimated impact**: Reduces peak from O(total_papers) to O(max_category_papers). With largest category ~1K papers, this makes 100-200K total papers trivial.
- **Limitation**: Steady-state cache still grows linearly. Only buys 2-4x headroom.

#### Option 2: Incremental Cache Updates (Target: 200K+ papers)
Instead of recomputing ALL rankings on every data change, update only affected papers.
- **Approach**: When a new match arrives, update only the two papers' scores using online win-rate update. Periodic full recomputation as a consistency check.
- **Complexity**: High. Requires maintaining running scores in DB, careful concurrency handling, and a reconciliation mechanism.
- **Estimated impact**: Eliminates the 2x memory peak entirely. Cache refresh becomes O(1) per match instead of O(N) per data change.
- **Limitation**: Same as Option 1 — steady-state cache still linear. Hardest to get right (concurrency edge cases) for the least additional payoff over Option 1.

#### Option 3: DB-Backed Leaderboard — No In-Memory Cache (Target: 1M+ papers)
Store computed rankings in MongoDB. Serve requests via indexed queries. **This is what Chess.com, Lichess, etc. do for millions of rated players.**
- **Approach**:
  - Store one document per paper with `{score, rank, win_rate, wins, losses, comparisons}` in a `rankings` collection
  - Create compound index `{category: 1, rank: 1}` for instant sorted queries
  - Serve leaderboard requests with `find({category: X}).sort({rank: 1}).skip(offset).limit(50)` — O(1) memory
  - When a match completes: update only the 2 affected papers' scores in the `rankings` collection
  - Periodic full recomputation (e.g. daily) as a consistency check
- **Complexity**: Medium-High. Requires refactoring all leaderboard endpoints to query DB instead of cache, and changing the match completion hook.
- **Estimated impact**: Memory becomes O(1) — completely independent of paper count. 1M, 10M papers all work in 1GB.
- **Tradeoff**: ~5-20ms per leaderboard request (vs ~0ms from in-memory cache). Negligible for users but measurable.
- **Recommendation**: Implement this when approaching 30K papers. Not needed until then since current limit is ~50K.

**Practical timeline**: With NeurIPS, more ICLR topics, and other venues, expect ~10-20K papers within a year — well within the current 50K limit. Revisit at 30K.

### Sync Blocking in Admin Scrapers
- `pairwise.py`: 8× `requests.get()` + `time.sleep()` — blocks event loop during Qeios scraping
- `qeios.py`: 2× `requests.get()` + `time.sleep()` — blocks during Qeios fetch
- `validation_imports.py`: 10× `requests.get()` — blocks during OpenReview/eLife imports
- **Impact**: Admin-only, no public DoS risk. But freezes all HTTP requests while running.
- **Fix**: Replace `requests` with `httpx.AsyncClient` and `time.sleep` with `asyncio.sleep`

### Leaderboard Update Latency
- Current pipeline: comparison round completes → `notify_data_changed()` → 10s debounce → 1.8s refresh = **~12 seconds** until new results visible
- This is acceptable for the current use case (tournament results aren't time-critical)
- If real-time updates are needed, the debounce can be reduced or eliminated

## Cache Size Limits

| Cache | Max Entries | TTL | Eviction |
|---|---|---|---|
| `_cache` (leaderboard) | 1 (atomic swap) | Event-driven | Full replacement |
| `_tag_cache` | 100 | 20s | LRU |
| `_analysis_cache` | 500 | 1 hour | LRU |
| `_result_cache` | 2000 | 1 hour | LRU |
| `_admin_cache` | 50 | 5 min | LRU |
| `_datasets_cache` | 1 | 5 min | Full replacement |

## Background Task Architecture

| Task | Trigger | Blocking? |
|---|---|---|
| `_compare_loop` | Event-driven (wake_scheduler) | No — async LLM calls + thread pool BT |
| `_fetch_loop` | Sleep-until-due (configurable interval) | No — async HTTP |
| `_bg_cache_loop` | Event-driven (notify_data_changed) | 113ms burst (BSON deserialize) |
| `_bg_analysis_cache_loop` | Event-driven (notify_data_changed) | Thread pool for BT |
| `_bg_archive_loop` | Daily at 00:05 UTC | No |
| PDF parsing | Per-paper during fetch | No — thread pool (run_in_executor) |

## Startup Timeline (2K papers, 67K matches)

| Time | Event | Leaderboard available? |
|---|---|---|
| 0.1s | Precomputed JSON loaded | No |
| 2.3s | Leaderboard cache warmed | **Yes** |
| 3.8s | Validation cache pre-warmed | Yes |
| 14s | Extraction stats warmed | Yes |
| 99s | Analysis cache (model-correlation) | Yes (stale JSON until then) |
| 104s | Summary bias cache | Yes |

## Validation Methodology Notes

### Cross-Tier Pair Selection Bias (Fixed Mar 2026)
The matchmaking algorithm previously filtered to cross-tier pairs only (0% within-tier). Fixed — future runs sample from all pairs. See `/app/memory/AI_PIPELINE_METHODOLOGY.md` for details.

### Controlled Pairs vs Full Data
Two pages serve different purposes:
- **Human vs AI Benchmark**: Same pair set for both → fair head-to-head comparison
- **AI Ranking Quality**: Each method's full data → absolute ranking quality measure
