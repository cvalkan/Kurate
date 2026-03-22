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

---

## Option 3: DB-Backed Leaderboard — Detailed Implementation Plan

### Architecture Overview

Replace the in-memory `_cache` (which holds all papers, matches, leaderboard entries, and indices) with a `rankings` collection in MongoDB. Leaderboard requests become indexed DB queries. Rankings are updated incrementally when matches complete.

**Memory model**: O(1) — independent of paper count. A 1M-paper deployment uses the same ~220MB baseline as a 2K-paper deployment.

**Latency model**: ~5-20ms per leaderboard request (indexed query + sort + limit) vs ~0ms from in-memory cache. Imperceptible to users.

### New `rankings` Collection

```
{
  paper_id: "uuid",
  category: "cs.RO",           // primary category (indexed)
  rank: 1,                     // current rank within category (indexed)
  score: 1876,                 // regularized win-rate score
  ci: 130,                     // confidence interval
  wilson_margin: 1.2,
  win_rate: 98.9,
  wins: 347,
  losses: 4,
  comparisons: 351,
  
  // Denormalized paper metadata (for serving without joins)
  title: "...",
  authors: ["..."],
  arxiv_id: "...",
  link: "...",
  published: "2026-02-12T...",
  added_at: "2026-02-12T...",
  
  // Optional enrichments
  ai_rating: 7.6,
  gap_score: 1.5,
  community_likes: 42,
  
  updated_at: "2026-03-22T..."
}
```

**Indexes:**
- `{category: 1, rank: 1}` — primary leaderboard query
- `{category: 1, published: -1}` — period-filtered queries
- `{category: 1, added_at: -1}` — "most recent" filter
- `{paper_id: 1}` — lookup by paper ID (unique)
- `{category: 1, score: -1}` — for re-ranking after score updates

### Implementation Phases

#### Phase 1: Rankings Collection + Incremental Updates (~2-3 days)

**1a. Create `rankings` collection and seed from current data**
- New function `seed_rankings()`: for each category, run `compute_leaderboard()` once, insert results into `rankings`
- Add paper metadata (title, authors, etc.) to each ranking doc
- Create indexes
- This is a one-time migration, idempotent (upsert by paper_id)

**1b. Incremental update on match completion**
- In `scheduler.py::run_comparison_round`, after each match is saved:
  ```python
  async def update_rankings_for_match(category, winner_id, loser_id):
      # Update winner: wins+1, comparisons+1
      # Update loser: losses+1, comparisons+1
      # Recompute score for both using the formula:
      #   p_reg = (wins + 0.5) / (comparisons + 1.0)
      #   score = 400 * log10(p_reg / (1 - p_reg)) + 1200
      # Recompute CI and wilson_margin for both
  ```
- After all matches in a round complete, recompute ranks for the category:
  ```python
  async def rerank_category(category):
      # cursor = db.rankings.find({category}).sort({score: -1})
      # for rank, doc in enumerate(cursor, 1):
      #     db.rankings.update_one({paper_id: doc.paper_id}, {$set: {rank}})
  ```
- This is O(papers_in_category) per round, not O(all_papers)

**1c. Handle new papers**
- When a paper is inserted during fetch cycle, also insert a ranking doc with score=1200, rank=last, comparisons=0
- When a paper's enrichments change (ai_rating, community_likes), update the ranking doc

**Validation**: Run both old cache + new rankings in parallel. Compare outputs. Ensure identical results.

#### Phase 2: Migrate Leaderboard Serving to DB Queries (~2-3 days)

**2a. Primary category leaderboard** (the main endpoint, ~80% of traffic)
```python
@router.get("/leaderboard")
async def get_leaderboard(category, period, limit, offset, search):
    query = {"category": category}
    if period == "week":
        query["published"] = {"$gte": (now - 7d).isoformat()}
    elif period == "month":
        query["published"] = {"$gte": (now - 30d).isoformat()}
    elif period == "recent":
        query["added_at"] = {"$gte": (now - 48h).isoformat()}
    if search:
        query["title"] = {"$regex": search, "$options": "i"}
    
    total = await db.rankings.count_documents(query)
    entries = await db.rankings.find(query, {"_id": 0})
        .sort("rank", 1).skip(offset).limit(limit).to_list(limit)
    return {"leaderboard": entries, "total_in_period": total, ...}
```

**2b. "All papers" cross-category view**
- Option A: Add a virtual `category: "__all__"` ranking set, maintained alongside per-category rankings
- Option B: Query without category filter, sort by score. Since scores are comparable across categories (same formula), this works directly.
- Recommendation: Option B — no extra storage, just `db.rankings.find({}).sort({score: -1}).skip().limit()`

**2c. Tag-filtered leaderboard** (the complex case)
This currently re-computes `compute_leaderboard` for an ad-hoc paper subset. Two approaches:

- **Approach A (simple, good enough)**: Query rankings for papers matching the tags. Since rankings are pre-computed per primary category, the scores are already correct. Just filter and re-rank:
  ```python
  paper_ids = await db.papers.distinct("id", {"categories": {"$in": tags}})
  entries = await db.rankings.find({"paper_id": {"$in": paper_ids}}).sort("score", -1)
  # Re-number ranks 1..N
  ```
  This doesn't recompute BT scores scoped to the tag subset. But the current tag UI already shows "global" scores, so this is fine.

- **Approach B (exact, expensive)**: Compute BT scores for just the tag subset on-demand. Cache result for 20s. Only needed if the UX requires tag-scoped ranking rather than global ranking filtered by tag.
  
  **Recommendation**: Approach A. It's what users actually want (filter the leaderboard by topic), and it's O(1) memory.

**2d. Paper detail page**
- Already reads from DB (`db.papers.find_one`), no change needed.
- Ranking info (score, rank, wins) can come from `db.rankings.find_one({paper_id})`.

**2e. Admin panel stats**
- Failed match counts, PDF counts, storage stats: already use DB aggregation or simple counters. No change needed.
- Progress/convergence stats: currently computed from `_cache["_raw_matches"]`. Move to DB query scoped to category.

**Validation**: A/B test — serve 50% of traffic from DB, 50% from cache. Compare latency and correctness.

#### Phase 3: Remove In-Memory Cache (~1 day)

Once Phase 2 is validated:
- Remove `_refresh_cache()` entirely
- Remove `_bg_cache_loop`
- Remove `_raw_papers`, `_raw_matches`, `_match_index` from memory
- Keep lightweight caches: `_tags`, `_categories`, `_summary_stats` (these are tiny, <1MB)
- The `model-correlation` and `convergence` endpoints still need match data — move them to DB queries scoped by category (they already have `_compute_model_correlation` which can be refactored to query DB)
- The sitemap endpoint: query `db.rankings.distinct("paper_id")` instead of iterating `_raw_papers`

#### Phase 4: Consistency Reconciliation (~0.5 day)

- Daily background task: full recomputation of all rankings from matches (same as current `compute_leaderboard`)
- Compare with incremental rankings
- If drift detected (e.g., from a bug in incremental updates), overwrite with full recomputation
- Log any discrepancies for monitoring

### Migration Safety

- **Zero downtime**: Phases run in parallel with the existing cache. The cache continues serving until Phase 3.
- **Rollback**: If Phase 2 reveals issues, revert the endpoint to read from `_cache`. Rankings collection is append-only metadata; removing it is safe.
- **Data consistency**: The incremental formula is mathematically identical to the full recomputation (since win-rate score depends only on wins/comparisons, not opponent strength). Reconciliation in Phase 4 is a safety net, not a necessity.

### What Stays In Memory (Post-Migration)

| Data | Size | Why |
|---|---|---|
| `_tags` list | ~5KB | Tiny, rarely changes |
| `_categories` list | ~1KB | Static |
| `_summary_stats` | ~10KB | Computed via aggregation |
| `_rating_stats` | ~5KB | Computed from paper count |
| `_archives` list | ~20KB | Lightweight metadata |
| Analysis caches (LRU) | ~20MB (bounded) | model-correlation, convergence |
| **Total** | **~20MB** | **vs ~750MB+ today** |

### Estimated Latency Impact

| Endpoint | Current (cache) | After (DB) | Notes |
|---|---|---|---|
| `/leaderboard?category=X` | <1ms | ~5-10ms | Indexed sort + limit |
| `/leaderboard?tags=X,Y` | ~50ms (compute) | ~10-20ms | Filter + sort, no BT recompute |
| `/leaderboard?show_all` | <1ms | ~10-15ms | Full scan sort, still fast |
| `/papers/{id}` | ~5ms | ~5ms (unchanged) | Already DB-backed |
| `/model-correlation` | <1ms (cache) | ~50-100ms | Needs match scan per category |

### Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Incremental score drift | Low (formula is stateless) | Phase 4 daily reconciliation |
| Tag query latency spike | Medium (large tag sets) | Pre-compute popular tag combos, 20s cache |
| Rank recomputation blocking | Low | Batch updates, yield to event loop |
| Concurrent match + re-rank race | Medium | Per-category lock (already exists) |

### Total Effort Estimate

| Phase | Effort | Can ship independently? |
|---|---|---|
| Phase 1: Rankings collection + incremental | 2-3 days | Yes (runs alongside cache) |
| Phase 2: Migrate serving endpoints | 2-3 days | Yes (with feature flag) |
| Phase 3: Remove in-memory cache | 0.5-1 day | Yes (after Phase 2 validated) |
| Phase 4: Reconciliation | 0.5 day | Yes |
| **Total** | **~6-7 days** | Each phase is independently shippable |

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
