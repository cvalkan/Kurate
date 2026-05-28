# Heatmap List-View Scaling Plan

Status: Phase 0–2 + polars vectorisation complete · Last updated: 2026-02-28

## Goal

Make `/test/list-views/heatmap` (and any production descendant) feel snappy at
100,000+ papers. "Snappy" = first paint ≤ 800 ms on broadband, any subsequent
filter/sort/scroll interaction ≤ 200 ms.

The scale test page at `/test/list-views/scale-test` is the truth machine —
every change must keep or improve those two numbers at N = 10k / 100k / 500k.

---

## Where we are now

After shipping Phase 0, all of Phase 1A/B, full Phase 2, and Option B
(polars vectorisation), this is the current state on the scale-test page.

| N           | First paint (server mode) | Filter / sort / search interaction | DOM size | Verdict |
|-------------|---------------------------|------------------------------------|----------|---------|
| 200         | ~250 ms                   | imperceptible                      | 16-32 rows | native |
| 10k         | ~350 ms                   | imperceptible                      | 16-32 rows | native |
| **100k**    | ~400 ms                   | 11 – 30 ms server + ~50 ms network = **80 ms perceived** | 16-32 rows | **native** |
| **200k**    | ~450 ms                   | 14 – 96 ms server + ~50 ms network = **~150 ms perceived** | 16-32 rows | **snappy** |
| **500k**    | ~600 ms                   | 25 – 137 ms server + ~80 ms network = **~220 ms perceived** | 16-32 rows | **snappy** |
| ~1M (est.)  | ~1 s                      | 200–400 ms server + network = **~500 ms perceived** | 16-32 rows | mild lag on sort |
| >1M         | needs indexed store       | needs indexed store                | – | Phase 5 territory |

For comparison, before any optimization at 100k client-side:

| | Before | After Phase 0–2 + polars |
|---|---|---|
| First paint at 100k | ~9 s | 0.4 s |
| Filter keystroke at 100k | growing 200–500 ms (jank) | 80 ms (server roundtrip) |
| Memory at 100k | 100k JS objects in browser | <250 rows ever in browser |
| Wire transfer at 100k | 117 MB | ~30 kB per page (40 rows) |
| Long-task count during filter at 100k | dozens | 0 |

---

## Tiered targets — updated

| Tier        | Corpus size      | Status / Strategy                                                                |
|-------------|------------------|----------------------------------------------------------------------------------|
| **A**       | up to ~5k        | ✅ Phase 1 client-side architecture handles this trivially                       |
| **B**       | 5k–30k           | ✅ Phase 1 client-side + virtualisation; production heatmap can stay client-side |
| **C**       | 30k–500k         | ✅ Phase 2 server endpoint with polars; current ceiling                          |
| **D**       | 500k–1M          | ⚠️  Works but threshold+sort approaches 300–500 ms perceived                    |
| **E**       | 1M+ or persistence-critical | ⛔ Phase 5: persist papers in Mongo with extended ratings as flat fields, compound indexes, push filter/sort/agg into Mongo |

---

## Completed phases

### ✅ Phase 0 — Instrumentation overlay

- `performance.mark` / `performance.measure` wrappers around `applyFilters`, `applySort`, histogram loop, render commit
- `PerformanceObserver({type: "longtask"})` surfaces main-thread tasks > 50 ms
- Overlay at `/test/list-views/scale-test` shows latest + max + count per phase
- "Copy trace" exports the full timeline + memory snapshot + UA as JSON
- Configurable debounce slider in the overlay (0–500 ms), persisted across reloads

### ✅ Phase 1A — Cheap client wins

- Search debounce (default 120 ms, configurable) collapses ~20 keystrokes into 1 commit
- Per-metric slider debounce (same plumbing) collapses ~20 drag events into 1 commit
- `filtered` / `visible` / `histograms` memos decoupled — sort changes no longer trigger filter/histogram recompute
- `React.memo` wraps `PaperCell` and `HeatmapRowCells`

### ✅ Phase 1B — Virtualisation

- `react-virtuoso` `TableVirtuoso` replaces the manual table + IntersectionObserver
- DOM stays at 16–32 rows regardless of total loaded
- Sticky header still works inside `overflow-x: auto` for mobile horizontal scroll
- `endReached` callback wires server-mode infinite scroll natively

### ✅ Phase 2 — Server-side paginated endpoint

- `/api/papers-list` accepts the full filter/sort/cursor spec
- Two data sources: `dataset=precomputed` (real 206 papers) and `dataset=synthetic` (cached by `n`/`seed`/`reasoning`)
- Per-metric thresholds via `min_<metric>` / `op_<metric>` raw query params
- Returns `rows / next_cursor / total / histograms / all_categories / dataset_size / timing_ms`
- Frontend hook `useServerPaperList(state, source)` with abort, page accumulation, stale-while-revalidate
- `HeatmapPage` accepts either `data` (client mode, legacy) or `serverSource` (server mode)
- FilterBar consumes `all_categories` in server mode so the tag list works at 100k without scanning rows
- Source toggle on `/test/list-views/scale-test` lets you flip Client ↔ Server live

### ✅ Option B — polars vectorisation

(Inserted instead of Phase 3/4/5 once it became clear the Python loop was the bottleneck.)

- `polars` 1.41.1 added to requirements
- `routers/papers_list.py` rewritten: DataFrame is built once per data-source key and cached; every filter/sort/histogram runs as a vectorised polars expression
- Same response schema; frontend untouched
- 200k filter+sort+histogram dropped from ~250 ms (Python loops) to **12–96 ms** (polars)
- `engine: "polars"` returned in the timing block for verification

---

## What we deliberately skipped, and why

| Originally planned | Skipped? | Reason |
|---|---|---|
| Phase 1 — Web Worker for filter/sort | Yes | With polars on the server, filter/sort is server-side and < 100 ms. The worker would only matter in client-only mode at 100k+, and we don't run that in production. |
| Phase 1 — Cap rendered metric columns to viewport | Yes | Virtualisation made it irrelevant. |
| Phase 3 — `$facet` aggregation for histograms | Deferred | Polars `np.histogram` per metric is already 1–28 ms across all tested scales. Re-evaluate when we move to Mongo. |
| Phase 4 — LRU cache + react-query | Deferred | At current latencies (60–250 ms perceived), the user-facing benefit is small. Re-evaluate when traffic grows or queries are demonstrably repeated. |

---

## What's still on the roadmap

### ⏭ Phase 5 — Persisted store with indexes (the long-term ceiling)

The current setup keeps the entire dataset as a polars DataFrame in process memory. That's fine up to ~1M papers, but:

- All data is re-built from the precomputed JSON / synthetic generator on startup. Production needs real extended ratings persisted.
- A single uvicorn process holds the DataFrame; horizontal scaling means warming N copies of it.
- Updates (new papers, re-summarisations) require recomputing the DataFrame or maintaining an out-of-band write path.

**When to trigger Phase 5:**

- Real corpus crosses ~500k extended-rated papers, **or**
- Extended ratings need to be persisted alongside the existing `papers` collection (i.e. shown in non-heatmap pages too), **or**
- We need to run multiple uvicorn workers / pods.

**What Phase 5 looks like:**

1. **Migrate extended ratings into Mongo**. Either as a sub-document on `papers` (`papers.heatmap = {score, significance, …, reasonings}`) or a parallel `extended_ratings` collection keyed by `paper_id`. Backed by a scheduler job that runs the prompt and persists.
2. **Compound indexes** mirroring the live tag-filter pipeline:
   - `(categories, score: -1, paper_id: 1)` for default sort
   - `(categories, published: -1)` for the date filter
   - One per remaining sortable metric — `(categories, <metric>: -1, paper_id: 1)` — partial-filter for the latest-version condition
   - `text` index on `(title, authors)` so search drops the regex
3. **Replace polars filter/sort with Mongo aggregations** in `papers_list.py`. Same endpoint contract, same response schema. Source switches per `dataset` parameter:
   - `dataset=mongo` → query the indexed collection
   - `dataset=synthetic` → polars stays for stress testing
   - `dataset=precomputed` → polars stays for the ICLR 206 demo
4. **`$facet` for histograms + total + page** in one aggregation — Phase 3 becomes free.
5. **LRU cache in front of the endpoint** (Phase 4) — `cachetools.TTLCache` keyed by `(filter_signature, sort, cursor)`, 60 s TTL. Real win on popular filter combinations.

**Expected outcome:**

| | After polars | After Phase 5 (Mongo + indexes) |
|---|---|---|
| 1M warm filter+sort | ~400 ms | ~30–80 ms |
| 10M warm filter+sort | (out of memory) | ~50–150 ms |
| Persistence | rebuilt on every restart | durable, incremental |
| Horizontal scaling | each worker holds full DF | shared store, stateless workers |

**Effort estimate:** 3–5 days plus a migration window for the rating persistence work.

---

## Open decisions

1. **When does the heatmap go public?** That changes when caching matters and how aggressively we need server-side rendering. (Phase 4 + a CDN-fronted route would be the path.)
2. **Are we extending the prompt-stability pipeline to all arXiv?** If yes, we cross 500k extended ratings within months and Phase 5 becomes mandatory. If no, polars handles us indefinitely.
3. **Two-sided threshold filters?** Today each metric is one-sided (`≥` or `≤`). Real ranges would double the index work in Phase 5. Probably defer until users ask.

---

## What NOT to do

- Don't ship Phase 3 ($facet) or Phase 4 (LRU cache) on top of the polars Python backend — wait for Phase 5 / Mongo where they actually pay off.
- Don't precompute the entire result-cross-product. Filter combinations are exponential; cache popular ones only.
- Don't add an OLAP store (Clickhouse, DuckDB) before Phase 5. Mongo on existing infra reaches ~10M docs comfortably.
- Don't ship Phase 5 without keyset pagination — skip+limit at offset 50k is a known footgun.
