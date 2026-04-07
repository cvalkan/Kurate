> **Superseded:** See [/app/memory/SCALABILITY_ANALYSIS.md] for the current unified analysis (Apr 7, 2026).

# Leaderboard at 100K+ Papers: Deep Dive Analysis & Action Plan

## Current State (2K papers)

| Metric | Value |
|---|---|
| Per-entry JSON size | 563 bytes |
| cs.RO response (977 papers) | 451KB, 220ms |
| All papers response (2135) | 1016KB, 335ms |
| Category top-200 query | 1.4ms (indexed) |
| Sort by non-indexed field | 2.6ms |
| count_documents | 0.7ms |
| Progressive render | 100 entries initial, +100 on scroll |

## Projected at 100K Papers

| Metric | At 100K | Problem? |
|---|---|---|
| Single category response (10K limit) | ~5.5MB | Slow on mobile 3G (10s+) |
| All papers response | **54MB** | Browser OOM on mobile |
| Sort by non-indexed field | ~250ms (100× current) | Acceptable with index |
| count_documents | ~70ms (100× current) | Acceptable |
| Client-side sort on 10K entries | ~100ms JS | Acceptable |
| Client-side sort on 100K entries | **~5s JS** | Unusable |
| DOM nodes at 10K rendered | Jank on mobile | Needs virtual scroll |
| JS heap for 10K entries | ~15MB | OK on desktop, tight on mobile |
| JS heap for 100K entries | **~150MB** | Browser tab crash |

## Breaking Points by Interaction

### 1. Initial Page Load (Category, All Time)
**Current**: Loads all 977 entries in one 451KB response. Works fine.
**At 100K**: PAGE_SIZE=10000 loads 10K entries (5.5MB). Desktop OK (2-3s). Mobile 3G: 10s+. Mobile RAM: 15MB for the data alone.
**At 100K if PAGE_SIZE=100K**: 54MB response. Browser tab crash.

**Verdict**: ❌ Breaks on mobile at 10K+ per category.

### 2. Scrolling Down
**Current**: Progressive render (100 → 200 → 300...). All data in memory, instant expansion.
**At 100K with PAGE_SIZE=10000**: Scroll through 10K entries with progressive render. DOM nodes accumulate. At 5K+ nodes, mobile stutters. At 10K nodes, mobile freezes.

**Verdict**: ❌ Breaks on mobile at 5K+ rendered nodes.

### 3. Scrolling UP (Back to Top)
**Current**: All data in memory. Scroll up shows already-rendered entries. Instant.
**At 100K with cursor pagination**: If we reduce PAGE_SIZE to 200, user scrolls down through pages 1-10, then scrolls back up. Pages 1-5 are still in memory (appended to the leaderboard array). Works fine.
**Problem**: If user scrolls to page 50, the leaderboard array has 10K entries in memory. Scrolling up requires traversing 10K DOM nodes (if all rendered) or re-rendering from the virtual scroll buffer.

**Verdict**: ⚠️ Works but accumulates memory. Needs virtual scrolling.

### 4. Sorting by Column (e.g., Win %, Title, Published)
**Current**: Client-side sort on the full array. At 977 entries, instant.
**At 100K**: Client-side sort only applies to loaded entries. If 200 loaded, user sorts by title and sees alphabetical order of 200 entries, NOT all 100K. This is confusing — "top by title" should be the globally first-alphabetical paper, not the top-ranked paper whose title happens to start with 'A'.

**Verdict**: ❌ Wrong results. Needs server-side sorting.

### 5. Switching Period (Week → Month → All Time)
**Current**: Each switch triggers a new API call. Fast because all periods have <1K entries.
**At 100K**: "All Time" has 100K entries (huge). "Week" has ~500 (small). Switching to "All Time" downloads 5.5MB. Switching back to "Week" downloads 50KB. The transitions are asymmetric.

**Verdict**: ⚠️ Slow transition TO large periods. Not broken but laggy.

### 6. Tag Filtering
**Current**: Queries rankings by categories, returns all matching. At 400 entries, instant.
**At 100K**: Tags like "cs.AI" might match 30K papers. Loading all 30K = 16MB response.

**Verdict**: ❌ Same as category view — breaks on mobile at 10K+.

### 7. Search
**Current**: Regex search on server, returns matching entries. At 343 results, instant.
**At 100K**: Regex is O(N) — scans all 100K documents. With text index, it's O(log N). Results typically <1K. Fast.

**Verdict**: ✅ Fine with text index (already added).

### 8. Mobile vs Desktop
**Desktop**: 8-16GB RAM, broadband. Can handle 10K entries in memory, 5MB responses, 2K DOM nodes.
**Mobile**: 2-4GB RAM (shared), 3G-5G. Struggles with >1K DOM nodes, >2MB responses, >30MB JS heap.

## Architecture Changes Needed

### Tier 1: Required for 10K+ (Do Now)

#### A. Virtual Scrolling
Replace progressive DOM rendering with virtual scroll. Only render ~30 visible rows + 10 buffer rows. Regardless of how many entries are loaded (1K, 10K, 100K), the DOM always has ~40 rows.

**Library**: `react-window` (7KB gzipped, battle-tested) or `@tanstack/react-virtual`
**Impact**: Eliminates mobile jank. DOM nodes: 40 (constant) instead of N (linear).
**Effort**: 1-2 days. Replace `LeaderboardTable` rendering loop with `VariableSizeList`.

#### B. Server-Side Sorting
Add `sort_by` and `sort_dir` params to the `/api/leaderboard` endpoint. Backend sorts using MongoDB indexes.

**Indexes needed**: `{category: 1, win_rate: -1}`, `{category: 1, comparisons: -1}`, `{category: 1, published: -1}`, `{category: 1, title: 1}`
**Frontend**: When user clicks a column header, send `sort_by=win_rate&sort_dir=desc` to the API. Reset the loaded entries and cursor.
**Impact**: Sorting is always correct (global sort, not loaded-page sort). O(1) memory on server (index scan).
**Effort**: 1 day backend, 0.5 day frontend.

#### C. Adaptive Page Size
Detect device capability and adjust PAGE_SIZE:
- Desktop: 500 entries per page (~275KB)
- Mobile: 100 entries per page (~55KB)

**Detection**: `navigator.connection?.effectiveType` for network speed, `navigator.deviceMemory` for RAM, or simply use viewport width as proxy.
**Impact**: Mobile loads 55KB instead of 5.5MB. Instant first paint.
**Effort**: 0.5 day.

### Tier 2: Required for 50K+ (Do When Approaching 30K)

#### D. Bidirectional Cursor
Current cursor only goes forward. Need `prev_cursor` for scrolling back after jumping to a deep position (e.g., via URL param `?start_rank=5000`).

**Implementation**: Return `{next_cursor, prev_cursor}` in responses. Frontend maintains a page stack.
**Effort**: 1 day.

#### E. Estimated Counts
Replace `count_documents(query)` with cached counts or `estimated_document_count()` where exact count isn't critical (e.g., "~100K papers" in header).

**Impact**: Eliminates O(N) count query on every page load.
**Effort**: 0.5 day.

#### F. Response Compression
Enable gzip/brotli for API responses. A 275KB JSON response compresses to ~40KB.

**Implementation**: Add `GZipMiddleware` to FastAPI.
**Impact**: 5-7× smaller responses over the wire.
**Effort**: 10 minutes.

### Tier 3: Required for 100K+ (Future)

#### G. Windowed Data Loading (Replace Accumulation)
Current approach accumulates pages: page 1 (100) → page 1+2 (200) → page 1+2+3 (300)... At 100K, scrolling to rank 50K means 50K entries in JS memory.

**Fix**: Discard off-screen pages. Only keep current page ± 1 buffer page in memory. Virtual scroll handles the rendering.
**Implementation**: Replace leaderboard array accumulation with a sparse map: `{pageNum: entries[]}`. Evict pages that are 3+ pages away from viewport.
**Impact**: Memory is O(page_size × 3) regardless of how deep the user scrolls.
**Effort**: 2 days.

#### H. Search-as-you-type with Debounced Server Queries
Current search sends regex to server on each keystroke (debounced 300ms). At 100K, regex scan takes ~50ms (acceptable). But results could be 5K+ entries.

**Fix**: Server returns max 200 search results. Frontend shows "200 of 5,234 results — refine your search".
**Effort**: 0.5 day.

## Priority Matrix

| Change | Scale | Effort | UX Impact | Priority |
|---|---|---|---|---|
| **A. Virtual scrolling** | 5K+ | 1-2 days | Eliminates mobile jank | **P0** |
| **B. Server-side sorting** | 5K+ | 1.5 days | Correct sort results | **P0** |
| **C. Adaptive page size** | 10K+ | 0.5 day | Fast mobile loads | **P0** |
| **F. Response compression** | Any | 10 min | Smaller payloads | **P0** |
| **D. Bidirectional cursor** | 50K+ | 1 day | Scroll-back support | P1 |
| **E. Estimated counts** | 50K+ | 0.5 day | Faster page loads | P1 |
| **G. Windowed data loading** | 100K+ | 2 days | Bounded memory | P2 |
| **H. Search result limits** | 100K+ | 0.5 day | Prevent huge results | P2 |

## Implementation Order

**Phase 1 (Now, 4 days total)**:
1. Response compression (F) — 10 minutes, instant win
2. Server-side sorting (B) — 1.5 days, backend indexes + API params + frontend wiring
3. Adaptive page size (C) — 0.5 day, frontend detection + PAGE_SIZE logic
4. Virtual scrolling (A) — 1-2 days, replace LeaderboardTable render with react-window

**Phase 2 (At 30K papers)**:
5. Bidirectional cursor (D)
6. Estimated counts (E)

**Phase 3 (At 100K papers)**:
7. Windowed data loading (G)
8. Search result limits (H)

## Summary

At current scale (2K), everything works smoothly. The critical threshold is **5-10K papers per category** where:
- Mobile first-paint becomes slow (>2s)
- Client-side sorting gives wrong results
- DOM accumulation causes jank

Phase 1 (virtual scroll + server sort + adaptive pages + compression) handles up to **50K papers per category** comfortably. Phase 2-3 extends to 100K+.
