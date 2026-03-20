# Kurate.org — Scaling & Architecture Notes

## Known Scaling Bottlenecks

### Event Loop Blocking During Leaderboard Refresh
- **Current**: Max 113ms burst with 2K papers + 67K matches (Motor BSON deserialization)
- **At 100K+ papers**: Expected ~500ms burst (proportional to data volume)
- **Fix if needed**: Switch to incremental BT updates instead of full recomputation. The BT algorithm supports online updates (adding one match updates two paper scores) without recomputing all rankings from scratch. This requires:
  - Maintaining running BT scores in the database
  - Updating only affected papers when a new match arrives
  - Periodic full recomputation as a consistency check
- **Architecture change**: Move from "recompute everything on data change" to "incremental update + periodic full reconciliation"

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
