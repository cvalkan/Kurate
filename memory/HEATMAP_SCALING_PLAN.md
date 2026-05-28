# Heatmap List-View Scaling Plan

Status: planning · Owner: TBD · Last updated: 2026-02-28

## Goal

Make `/test/list-views/heatmap` (and any production descendant) feel snappy at
100,000+ papers. "Snappy" = first paint ≤ 800 ms on broadband, any subsequent
filter/sort/scroll interaction ≤ 200 ms.

The scale test page at `/test/list-views/scale-test` is the truth machine —
every change must keep or improve those two numbers at N = 10k / 50k / 100k.

---

## Baseline (measured against the scaling test env, current code)

| N       | Wire transfer | JSON.parse | Flatten | First paint | Filter latency (search keystroke) | Sort latency |
|---------|--------------|-----------|---------|-------------|----------------------------------|--------------|
| 200     | <300 ms      | <5 ms     | <2 ms   | <500 ms     | imperceptible                    | imperceptible |
| 1k      | ~250 ms      | ~10 ms    | ~5 ms   | ~600 ms     | imperceptible                    | imperceptible |
| 10k     | 713 ms       | 67 ms     | 48 ms   | ~1.1 s      | ~50–80 ms                        | ~30 ms       |
| 50k     | 3.5 s        | ~350 ms   | ~250 ms | ~4.5 s      | ~300 ms / keystroke (painful)    | ~150 ms      |
| 100k    | 6.7 s        | ~700 ms   | ~500 ms | ~9 s        | ~700 ms / keystroke (unusable)   | ~350 ms      |

Notes:
- Everything is client-side today. There is no server-side filter or sort for this view.
- Payload is ~1.17 kB/paper (with reasoning text). Without reasoning it would be ~0.4 kB/paper.

---

## Tiered targets

| Tier        | Corpus size      | Strategy                                                       |
|-------------|------------------|----------------------------------------------------------------|
| **A**       | up to ~5k        | Current architecture (full payload, client filter/sort)        |
| **B**       | 5k–30k           | Add client-side perf wins; payload still full but loaded smart |
| **C**       | 30k–100k         | Server owns filter + sort + paging; client renders ≤ 200 rows  |
| **D**       | 100k+ and growth | Add caching, denormalized read model, full-text index          |

When we cross 3k–5k in production data we should start shipping Tier B work.
That gives us headroom before the next inflection point.

---

## Phase 0 — Instrumentation (do this before any optimization)

Without numbers we will optimize the wrong things.

1. **Performance markers in the heatmap** — wrap each phase in `performance.mark`/`performance.measure`:
   - `data:fetch`, `data:parse`, `data:flatten`, `filter`, `sort`, `histogram`, `render`
   - Already done for fetch/parse/flatten in `ScaleTestPage`. Extend to `applyFilters`, `applySort`, `computeMiniHistogram`, and the React commit.
2. **Long-task observer** — `PerformanceObserver({ type: "longtask" })` reports any main-thread task > 50 ms. Surface a small badge in the scaling page.
3. **Server-side slow-query log already exists** (`core/memlog.log_event("slow_query", ...)`). Make sure every new server endpoint emits one.

Output: a single overlay panel on the scale test page that shows live numbers, plus a button to copy the trace as JSON.

Effort: ~half a day. Unblocks everything else.

---

## Phase 1 — Client-side wins (no API changes)

Cheap, ship before the server work. Combined effect: filter/sort latency at 30k drops from ~250 ms to <50 ms.

| Change                                                                                                                                  | Expected impact                                              |
|-----------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|
| Debounce the search input (~120 ms)                                                                                                     | Removes the per-keystroke filter pass at 50k+                |
| Move `applyFilters` + `applySort` into a Web Worker via Comlink                                                                         | Filter and sort no longer block the main thread              |
| Memoize histograms by `(filteredIds_hash, metric_key)` so sort-only state changes don’t recompute                                       | Cuts redundant O(n) work on every sort flip                  |
| Virtualize the rendered table with `react-virtuoso` (replaces the current `.slice(0, shown)` pattern)                                    | Constant DOM footprint regardless of total row count         |
| Memoize per-row `formatAuthors` / `formatPublished` (they re-run on every render today)                                                 | ~5 ms saved per render at 100k                               |
| Move the per-paper `categories` Set creation to `useExtendedPapers` (compute once, not on every filter pass)                            | ~10 ms saved per filter at 50k                               |
| Cap rendered metric columns to the visible viewport (no point laying out the off-screen ones if `overflow-x: auto`)                     | Marginal but helps on mobile                                 |

Risk: virtualisation interacts with the sticky thead and the `overflow-x: auto` container. Verify it scrolls cleanly on both axes before merging.

---

## Phase 2 — Paginated server endpoint (the keystone change)

Once we ship this, the payload no longer scales with N.

### Endpoint

```
GET /api/papers/list
    ?search=
    &authors=                                  # optional, separate from title
    &cats=cs.LG,cs.AI                          # comma-separated
    &cat_mode=any|primary|cross-listed
    &cat_logic=or|and
    &date_from=2025-06-01&date_to=             # ISO; omit for unbounded
    &min[reproducibility]=7&op[reproducibility]=gte
    &min[score]=5&op[score]=gte
    &include_nulls=true|false
    &sort=score|published|...
    &dir=asc|desc
    &cursor=<opaque>                           # keyset pagination
    &limit=40                                  # cap 200
    &fields=core                               # "core" omits *_reason strings; "full" includes them
→ {
    rows: [...up to 40 papers...],
    next_cursor: "..."|null,
    total: 17483                                # optional; can be computed lazily
  }
```

### Mongo shape

Source the data from the `papers` collection (or a denormalized read model — see Phase 5). Each doc carries the flat ratings + arrays of authors / categories.

### Indexes to add (one-off migration)

These mirror what's already on the legacy leaderboard but extended for tag arrays:

- `(categories, score: -1, _id: -1)`             ← default sort
- `(categories, published: -1, _id: -1)`         ← "newly added"
- `(categories, ai_ratings.score: -1, _id: -1)`  ← if ratings live on a sub-field
- `(categories, ai_ratings.reproducibility: -1)`, ditto for each extended dim that the user might sort by
- Partial-filter variants with `{ is_latest_version: { $ne: false } }` as `partialFilterExpression`
- A `text` index on `(title, authors)` for substring search

Keyset pagination uses `_id` as the tiebreaker so cursors are stable.

### Filter mapping

| User filter | Mongo `$match` clause |
|---|---|
| `cats` + `cat_mode = any`           | `{ categories: { $in: cats } }` |
| `cats` + `cat_mode = primary`       | `{ category: { $in: cats } }` |
| `cats` + `cat_mode = cross-listed`  | `{ categories: { $in: cats }, category: { $nin: cats } }` |
| `cat_logic = and`                   | `{ categories: { $all: cats } }` (combined with mode-specific clause) |
| `min[x] = v, op = gte`              | `{ "ratings.x": { $gte: v } }` plus null handling |
| `include_nulls = false` + threshold | drop the `$or null` branch on that field |
| `date_from / date_to`               | `{ published: { $gte/lte: "..." } }` (ISO string) |
| `search` (title)                    | Phase 2: `{ title: { $regex: ..., $options: "i" } }`; Phase 5: `$text` |

### Backend `total` count strategy

Computing the exact total on every request is the single most expensive piece. Three sensible behaviours:

- **Default**: return `total: null` and let the UI show "many results". Cursor handles paging.
- **Cheap estimate**: `collMod` / `collStats` for unfiltered; `$count` on cached aggregates per popular `cats` combo.
- **Exact**: only when the result set is small enough to be useful (e.g., when at least one filter narrows the set). Run `$count` in parallel with the first page, return as a follow-up.

### Frontend changes

- Replace `useExtendedPapers()` with `usePaperList(filters, cursor)` that issues fetches per page.
- `applyFilters` / `applySort` become no-ops (or stay for the scaling test page only).
- Infinite scroll calls `fetch(next_cursor)` instead of `slice`.
- Filter state changes blow away the cursor and refetch page 1.

### Expected impact at 100k papers

| Metric | Today | After Phase 2 |
|---|---|---|
| First payload | ~117 MB | ~50 kB |
| First paint | ~9 s | ~400 ms |
| Search keystroke roundtrip | ~700 ms (CPU) | ~80 ms (network) — and now debounce-able |
| Memory | 100k JS objects pinned | <250 objects ever live |

---

## Phase 3 — Server-side histograms

The chart-mode column headers need a distribution per metric across the **current filter**, not the current page.

Two viable approaches:

1. **`$facet` aggregation alongside the paged query**:
   ```js
   db.papers.aggregate([
     { $match: <filter> },
     { $facet: {
         page:       [ { $sort: ... }, { $limit: 40 }, { $project: ... } ],
         histograms: [ { $bucket: { groupBy: "$ratings.score", boundaries: [1,2,3,...,11], default: null } }, ... ],
         total:      [ { $count: "n" } ],
     } }
   ])
   ```
   One round-trip, one filter pass on the server. Expensive only when the filter set is large.

2. **Precomputed histogram cache** per `(category_set, date_window)` warmed by the scheduler every N minutes. Trades freshness for cost.

Approach (1) is enough below ~500k papers. Above that, layer (2) on top.

---

## Phase 4 — Caching layer

Once the endpoint exists, parking a small LRU cache in front of it is a 50-line change.

- **Server-side**: `(filter_signature, sort, cursor, limit)` → response, TTL 30–120 s. In-process `cachetools.TTLCache` is fine; Redis once we have multiple FastAPI workers.
- **Client-side**: `react-query` / `SWR` with `staleTime: 30s` so navigating back-and-forth between filter states is instant.

This is where the "popular tag page" speedup comes from. Real-world load patterns are heavy-tailed — caching the top ~50 filter combinations covers most traffic.

---

## Phase 5 — Long-term structural work

Pick these up after Phase 4 if production data crosses ~250k papers.

### Denormalized read model

Today, `papers.ai_ratings_by_model` is a nested map keyed by model name. For the heatmap we always read the same model's flat metrics. Move them to top-level fields (`heatmap.score`, `heatmap.reproducibility`, ...) on the `papers` collection — populated by the scheduler when a new summary arrives. Lets the indexes above stay simple and small.

### Full-text search

Drop the regex search. Either:
- Mongo `$text` index on `(title, authors)` — free, good enough for substring search up to a few million docs.
- Or Meilisearch / Typesense for relevance, highlighting, and typo tolerance.

### Streaming JSON

For exports / "view all" workflows: stream the response as NDJSON so the UI can start rendering while the body is still arriving. Useful for analytics dashboards but not the heatmap.

### Server-side rendering for SEO

Out of scope here but already on the P1 backlog. Once the paged endpoint exists, an SSR pass that pre-renders the first 40 rows for a given tag becomes trivial.

---

## Suggested rollout sequence

| Week | What ships                                                                                                   | Cumulative effect                                |
|------|--------------------------------------------------------------------------------------------------------------|--------------------------------------------------|
| 1    | Phase 0 (instrumentation) + 2 of Phase 1 (debounce + virtuoso)                                               | 5k–10k feels native again                        |
| 2    | Rest of Phase 1 (worker + memoization)                                                                       | 30k tolerable on desktop                         |
| 3–4  | Phase 2 endpoint + indexes; ship behind a feature flag                                                       | 100k visible on the dogfood URL                  |
| 5    | Phase 3 histograms + Phase 4 server LRU                                                                      | Filter changes at 100k feel ≤ 300 ms             |
| 6+   | Phase 5 as needed                                                                                            | We don't think about scale again until 500k      |

---

## Open questions / decisions to make

1. **Is the heatmap a public page eventually?** That changes the caching tier (CDN-cacheable GET vs authenticated). My read: yes, it's coming.
2. **Do we need exact totals?** "About X papers match" is fine for most users; exact counts are expensive at scale.
3. **Should the threshold filters be per-metric `$gte/$lte` ranges, or do we expose a more powerful query (e.g., "between 6 and 8")?** The current UI only supports a one-sided threshold per metric. Two-sided would double Mongo's index work — not free.
4. **Reasoning strings**: 6 strings × ~150 chars each = 900 B/paper. They dominate the payload. Should we ship them only on row-expand instead of in the list? (Phase 2 makes this trivial — `fields=core` vs `fields=full`.)

---

## What NOT to do

- Don't pre-compute and store the entire result-cross-product. Filter combinations are exponential; cache the popular ones only.
- Don't add an OLAP store (Clickhouse, DuckDB) before exhausting Mongo aggregations. Mongo on the existing infra will carry us to ~1M docs comfortably.
- Don't ship server-side filtering without keyset pagination. Skip + limit at offset 50k is a known footgun.
- Don't optimize the histogram path until the table path is paged. It's downstream.
