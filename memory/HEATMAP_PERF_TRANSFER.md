# Heatmap List-View Speed Optimisations — Transfer Guide

A complete recipe for porting the speed optimisations from this codebase into
another fork's list/table view. Each section can be applied independently; they
compose. Numbers below are measured in this codebase but the engineering pattern
transfers regardless of dataset.

---

## TL;DR — what to copy

| Change | Effort | Latency win at scale | Required deps |
|---|---|---|---|
| 1. Performance instrumentation overlay | ½ day | — (visibility, not perf) | none |
| 2. Search + slider debounces (configurable) | ½ day | 20× fewer filter passes during typing/drag | none |
| 3. Decoupled `filter` / `sort` / `histogram` memos | 1 hr | 3× fewer recomputes per state change | none |
| 4. `React.memo` on rows + cells | 1 hr | Cuts re-render cost when unrelated state changes | none |
| 5. Virtualised table (TableVirtuoso) | ½ day | DOM cost goes from O(N) to O(visible) | `react-virtuoso` |
| 6. Server-side paginated endpoint | 1–2 days | Wire payload 117 MB → 30 kB at 100k | none |
| 7. Polars vectorisation on the server | 1 day | 200k filter+sort+hist 250 ms → 30 ms | `polars` |
| 8. Stale-while-revalidate on server refetch | 1 hr | No flicker on filter change | none |

Apply in this order — earlier items don't depend on later ones, later ones depend on earlier ones being in place.

---

## 1. Performance instrumentation overlay

**Why first**: without measurement you'll optimise the wrong thing.

### What it does

- `performance.mark` / `performance.measure` wrappers around every hot function
- A `PerformanceObserver` subscribed to `measure` and `longtask` entries
- A live overlay that surfaces latest / max / count per phase + long-task sparkline
- "Copy trace" button exports the full timeline + memory + UA as JSON
- A configurable debounce slider that *every* debounce in the app reads from

### Files

```
src/.../PerfOverlay.jsx           # the overlay component
src/.../_shared.jsx               # withTiming, measureBlock, usePerfDebounce helpers
```

### Code: timing helpers

```js
// _shared.jsx
let _perfSeq = 0;
function withTiming(name, fn) {
  return function (...args) {
    if (typeof performance === "undefined" || !performance.mark) return fn.apply(this, args);
    const mark = `${name}-${++_perfSeq}`;
    try {
      performance.mark(mark);
      return fn.apply(this, args);
    } finally {
      try {
        performance.measure(name, mark);
        performance.clearMarks(mark);
      } catch (_) { /* observer detached */ }
    }
  };
}

export function measureBlock(name, fn) {
  if (typeof performance === "undefined" || !performance.mark) return fn();
  const mark = `${name}-${++_perfSeq}`;
  performance.mark(mark);
  try { return fn(); }
  finally {
    try {
      performance.measure(name, mark);
      performance.clearMarks(mark);
    } catch (_) { /* ignore */ }
  }
}

// Wrap the hot functions at module level so all callers are timed
function _applyFilters(papers, state) { /* ... */ }
export const applyFilters = withTiming("perf:filter", _applyFilters);

function _applySort(papers, state) { /* ... */ }
export const applySort = withTiming("perf:sort", _applySort);

// Wrap histogram-style loops inline
const histograms = useMemo(() => measureBlock("perf:histogram", () => {
  const out = {};
  visibleMetrics.forEach(m => { out[m.key] = computeMiniHistogram(filtered, m.key, 10); });
  return out;
}), [filtered, visibleMetrics]);

// Render commit via React.Profiler
<Profiler id="heatmap-render" onRender={(_id, _phase, actualDuration) => {
  if (typeof performance !== "undefined" && performance.mark) {
    try {
      const start = performance.now() - actualDuration;
      const mark = `perf:render-start-${start}`;
      performance.mark(mark, { startTime: start });
      performance.measure("perf:render", mark);
      performance.clearMarks(mark);
    } catch (_) { /* ignore */ }
  }
}}>
  {/* ...table... */}
</Profiler>
```

### Code: configurable debounce (subscribable across components, no context)

```js
// _shared.jsx
const PERF_DEBOUNCE_KEY = "perf:debounceMs";
const PERF_DEBOUNCE_EVENT = "perf-debounce-changed";
export const DEFAULT_DEBOUNCE_MS = 120;

export function usePerfDebounce() {
  const [ms, setMs] = useState(() => {
    try {
      const v = parseInt(localStorage.getItem(PERF_DEBOUNCE_KEY) || "", 10);
      return Number.isFinite(v) ? v : DEFAULT_DEBOUNCE_MS;
    } catch (_) { return DEFAULT_DEBOUNCE_MS; }
  });
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === PERF_DEBOUNCE_KEY && e.newValue != null) {
        const v = parseInt(e.newValue, 10);
        if (Number.isFinite(v)) setMs(v);
      }
    };
    const onCustom = (e) => {
      if (typeof e.detail === "number") setMs(e.detail);
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(PERF_DEBOUNCE_EVENT, onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(PERF_DEBOUNCE_EVENT, onCustom);
    };
  }, []);
  const setMsAndPersist = useCallback((next) => {
    const v = Math.max(0, Math.min(2000, Math.round(next)));
    setMs(v);
    try { localStorage.setItem(PERF_DEBOUNCE_KEY, String(v)); } catch (_) {}
    window.dispatchEvent(new CustomEvent(PERF_DEBOUNCE_EVENT, { detail: v }));
  }, []);
  return [ms, setMsAndPersist];
}
```

### Code: PerfOverlay (skeleton — copy the full file from `/app/frontend/src/pages/ListViewsTest/PerfOverlay.jsx`)

```jsx
const TRACKED = [
  { key: "data:fetch",     label: "Fetch" },
  { key: "data:parse",     label: "Parse" },
  { key: "data:flatten",   label: "Flatten" },
  { key: "perf:filter",    label: "Filter" },
  { key: "perf:sort",      label: "Sort" },
  { key: "perf:histogram", label: "Histogram" },
  { key: "perf:render",    label: "Render" },
];

export function PerfOverlay() {
  const [stats, setStats] = useState({});
  const [longTasks, setLongTasks] = useState([]);
  useEffect(() => {
    if (typeof PerformanceObserver === "undefined") return;
    const m = new PerformanceObserver((list) => {
      const updates = {};
      list.getEntries().forEach((e) => {
        if (!TRACKED.some(t => t.key === e.name)) return;
        (updates[e.name] = updates[e.name] || []).push(e.duration);
      });
      setStats(prev => {
        const next = { ...prev };
        for (const [k, durs] of Object.entries(updates)) {
          const last = durs[durs.length - 1];
          const p = next[k] || { last: 0, max: 0, count: 0 };
          next[k] = { last, max: Math.max(p.max, ...durs), count: p.count + durs.length };
        }
        return next;
      });
    });
    m.observe({ entryTypes: ["measure"] });
    let l = null;
    try {
      l = new PerformanceObserver((list) => {
        setLongTasks(prev => [...prev, ...list.getEntries().map(e => ({ d: e.duration }))].slice(-30));
      });
      l.observe({ type: "longtask", buffered: true });
    } catch (_) {}
    return () => { m.disconnect(); l?.disconnect(); };
  }, []);
  // ...render the stats grid + long-task sparkline + debounce slider...
}
```

The overlay is most useful mounted on a **scaling test page** (see Section 6 below) so you can validate every change without polluting production.

---

## 2. Search + slider debounces (use the configurable hook)

**Why**: A `<input type="range">` fires ~20 onChange events per slider drag; without a debounce each one triggers filter + sort + histogram + render.

**Pattern**: local draft state for the input, debounced commit to the canonical state.

```jsx
import { usePerfDebounce } from "./_shared";

export function FilterBar({ state, setState, ... }) {
  const [debounceMs] = usePerfDebounce();

  // --- Search debounce
  const [searchDraft, setSearchDraft] = useState(state.search);
  useEffect(() => { setSearchDraft(state.search); }, [state.search]);   // external reset
  useEffect(() => {
    if (searchDraft === state.search) return;
    if (debounceMs <= 0) { setState({ search: searchDraft }); return; }
    const id = setTimeout(() => setState({ search: searchDraft }), debounceMs);
    return () => clearTimeout(id);
  }, [searchDraft, debounceMs]);

  // --- Per-slider debounce (one draft object for all sliders together)
  const [thresholdDraft, setThresholdDraft] = useState(state.metricMin || {});
  useEffect(() => { setThresholdDraft(state.metricMin || {}); }, [state.metricMin]);
  useEffect(() => {
    const a = thresholdDraft, b = state.metricMin || {};
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    let differs = false;
    for (const k of keys) if (a[k] !== b[k]) { differs = true; break; }
    if (!differs) return;
    if (debounceMs <= 0) { setState({ metricMin: thresholdDraft }); return; }
    const id = setTimeout(() => setState({ metricMin: thresholdDraft }), debounceMs);
    return () => clearTimeout(id);
  }, [thresholdDraft, debounceMs]);

  return (
    <>
      <input value={searchDraft}
             onChange={e => setSearchDraft(e.target.value)} />
      {metrics.map(m => (
        <input type="range" min={0} max={10} step={0.5}
               value={thresholdDraft[m.key] ?? 0}
               onChange={e => setThresholdDraft(prev => ({ ...prev, [m.key]: +e.target.value }))} />
      ))}
    </>
  );
}
```

Discrete clicks (operator-flip buttons, category pills, mode toggles) commit immediately — only continuous/drag inputs need debouncing.

---

## 3. Decouple filter / sort / histogram memos

**Why**: Sorting doesn't change the filtered set, but if filter and sort share a memo, every sort click re-runs the filter pass. Same for histograms — they only depend on the filtered set, not the sorted one.

```js
// BEFORE — coupled, sorts re-run filter
const visible = useMemo(
  () => applySort(applyFilters(papers, state), state),
  [papers, state]
);
const histograms = useMemo(() => buildHistograms(visible, metrics), [visible, metrics]);

// AFTER — decoupled, sort changes only re-sort
const filtered = useMemo(() => applyFilters(papers, state), [
  papers,
  state.search,
  state.dateRange,
  state.categories,
  state.categoryMode,
  state.categoryLogic,
  state.metricMin,
  state.metricOp,
  state.includeNulls,
]);
const visible = useMemo(() => applySort(filtered, state), [
  filtered, state.sortKey, state.sortDir,
]);
const histograms = useMemo(() => buildHistograms(filtered, metrics), [filtered, metrics]);
```

Explicit deps (not `[papers, state]`) is what makes this work — without spelling them out, any state change invalidates the memo.

---

## 4. React.memo on rows and cells

**Why**: When unrelated state changes (e.g., header-mode toggle, debounce slider), every row's children re-evaluate. `memo` lets unchanged rows skip their entire subtree.

```jsx
function _PaperCell({ paper }) { /* ... */ }
const PaperCell = memo(_PaperCell);

function _Row({ paper, index, visibleMetrics }) { /* ... */ }
const Row = memo(_Row);
```

For `memo` to actually help: prop references must be stable. In particular:
- `visibleMetrics` should be wrapped in `useMemo` so it has stable identity until columns are hidden
- `paper` objects come from a stable source (don't rebuild them on every render)
- `index` will change on sort; that's unavoidable and memo helps less for sort interactions

---

## 5. Virtualised table

**Why**: At 1000+ rendered rows, every state change re-renders all rows. Virtualisation keeps the DOM at ~16-32 rows regardless of total.

### Install

```
yarn add react-virtuoso
```

### Pattern

```jsx
import { TableVirtuoso } from "react-virtuoso";

// Cells-only row component (no <tr> wrapper)
function _RowCells({ paper, index, visibleMetrics }) {
  return (
    <>
      <td>...</td>
      <td>...</td>
      {visibleMetrics.map(m => <td key={m.key}>...</td>)}
    </>
  );
}
const RowCells = memo(_RowCells);

// Stable references for the components map
const TableComponent = useMemo(() => ({ style, children, ...rest }) => (
  <table {...rest} className="..." style={style}>
    <colgroup>
      <col style={{ width: 78 }} />
      <col className="w-[260px] min-w-[230px] sm:w-auto" />
      {visibleMetrics.map(m => <col key={m.key} style={{ width: 56 }} />)}
    </colgroup>
    {children}
  </table>
), [visibleMetrics]);

const components = useMemo(() => ({
  Table: TableComponent,
  TableHead: forwardRef(function H({ children, ...p }, ref) {
    return <thead ref={ref} {...p} className="sticky top-0 z-20 bg-card">{children}</thead>;
  }),
  TableRow: forwardRef(function R({ children, ...p }, ref) {
    const idx = parseInt(p["data-index"], 10);
    const stripe = Number.isFinite(idx) && idx % 2 === 1 ? "bg-secondary/10" : "bg-background";
    return <tr ref={ref} {...p} className={stripe} style={{ height: 72 }}>{children}</tr>;
  }),
}), [TableComponent]);

const itemContent = useCallback((idx, paper) => (
  <RowCells paper={paper} index={idx} visibleMetrics={visibleMetrics} />
), [visibleMetrics]);

<TableVirtuoso
  useWindowScroll                              // <-- crucial: scrolls with the page, not internal
  data={visible}
  increaseViewportBy={{ top: 400, bottom: 800 }}
  components={components}
  fixedHeaderContent={() => (<tr>{/* headers */}</tr>)}
  itemContent={itemContent}
  computeItemKey={(_, p) => p.paper_id}         // stable identity across reorder
  endReached={serverLoadMore || undefined}      // optional: server-mode infinite scroll
/>
```

### Gotchas

- **Don't wrap in a fixed-height container** with `useWindowScroll` — virtuoso needs to measure against the viewport.
- **Sticky header with `position: sticky; top: 0`** works inside virtuoso's `<thead>` when `useWindowScroll` is on.
- **`overflow-x: auto` on the outer card** for mobile horizontal scrolling — virtuoso handles vertical, your container handles horizontal.
- **TableRow stripe** via `data-index` (which virtuoso always passes), not `:nth-child` (the latter shifts as virtuoso unmounts/remounts rows during scroll).
- **Use `forwardRef`** for `TableHead` and `TableRow` overrides — virtuoso refs them for measurement.

---

## 6. Server-side paginated endpoint

**Why**: At 100k+ papers, the full payload is 100+ MB and JSON.parse alone takes 700 ms. Server-side filtering caps the wire transfer per page at ~30 kB.

### Endpoint contract

```
GET /api/papers-list
  ?search=
  &date_range=newly|7d|30d|all
  &cats=cs.LG,cs.AI                      # comma-separated
  &cat_mode=any|primary|cross-listed
  &cat_logic=or|and
  &include_nulls=true|false
  &min_<metric>=N  &op_<metric>=gte|lte  # per-metric thresholds, raw query
  &sort_key=score
  &sort_dir=desc
  &offset=0
  &limit=40
  &include_histograms=true
  &include_categories=false              # only on page 1

→ {
  rows: [...up to limit rows in API shape...],
  next_cursor: "offset"|null,
  offset, limit, total,
  histograms: { metric: { counts:[10], n, mean, max } } | null,
  all_categories: [...] | null,
  dataset_size: N,
  engine: "polars" | "python",
  timing_ms: { load, filter, sort, histogram, total },
}
```

### Backend skeleton (FastAPI, polars version below in §7)

```python
@router.get("")
async def papers_list(
    request: Request,
    search: str = "", date_range: str = "all",
    cats: str = "", cat_mode: str = "any", cat_logic: str = "or",
    include_nulls: bool = True,
    sort_key: str = "score", sort_dir: str = "desc",
    offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=200),
    include_histograms: bool = True,
    include_categories: bool = False,
):
    # Per-metric thresholds are read off raw query params so the metric set can grow
    thresholds = {}
    qp = request.query_params
    for m in ALL_METRICS:
        thr = qp.get(f"min_{m}")
        if thr is None: continue
        try: thr = float(thr)
        except: continue
        op = qp.get(f"op_{m}") or "gte"
        thresholds[m] = (thr, op)

    df = load_dataframe()                                            # cached
    filtered = apply_filter(df, {...filter params, thresholds...})
    ordered  = apply_sort(filtered, sort_key, sort_dir)
    page     = ordered.slice(offset, limit)
    return {
        "rows": rows_to_api_shape(page),
        "next_cursor": str(offset + limit) if offset + limit < ordered.height else None,
        "offset": offset, "limit": limit, "total": ordered.height,
        "histograms": compute_histograms(filtered) if include_histograms else None,
        "all_categories": all_unique_cats(df) if include_categories else None,
        "dataset_size": df.height,
        "engine": "polars",
        "timing_ms": {...},
    }
```

### Frontend hook

```js
const PAGE_SIZE_SERVER = 40;

function buildQuery(state, source) {
  const p = new URLSearchParams();
  if (state.search) p.set("search", state.search);
  if (state.dateRange && state.dateRange !== "all") p.set("date_range", state.dateRange);
  if (state.categories?.size > 0) {
    p.set("cats", Array.from(state.categories).join(","));
    if (state.categoryMode !== "any") p.set("cat_mode", state.categoryMode);
    if (state.categoryLogic !== "or") p.set("cat_logic", state.categoryLogic);
  }
  if (state.includeNulls === false) p.set("include_nulls", "false");
  for (const [m, thr] of Object.entries(state.metricMin || {})) {
    if (thr == null) continue;
    const op = (state.metricOp || {})[m] || "gte";
    if (op === "gte" && thr === 0) continue;
    if (op === "lte" && (thr === 10 || thr === 0)) continue;
    p.set(`min_${m}`, String(thr));
    p.set(`op_${m}`, op);
  }
  if (state.sortKey) p.set("sort_key", state.sortKey);
  if (state.sortDir) p.set("sort_dir", state.sortDir);
  return p.toString();
}

export function useServerPaperList(state, source) {
  const [pages, setPages] = useState({});
  const [meta, setMeta]   = useState({ total: 0, histograms: {}, allCategories: [] });
  const [loading, setLoading] = useState(true);
  const abortRef = useRef(null);

  const sig = useMemo(() => buildQuery(state, source), [
    state.search, state.dateRange,
    state.categories, state.categoryMode, state.categoryLogic,
    state.metricMin, state.metricOp, state.includeNulls,
    state.sortKey, state.sortDir,
  ]);

  // First-page fetch on filter change
  useEffect(() => {
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    // Stale-while-revalidate: do NOT clear `pages` here.
    fetch(`/api/papers-list?${sig}&offset=0&limit=${PAGE_SIZE_SERVER}&include_categories=true`,
          { signal: ctrl.signal })
      .then(r => r.json())
      .then(d => {
        if (ctrl.signal.aborted) return;
        setPages({ 0: (d.rows || []).map(flattenPaper) });
        setMeta({
          total: d.total, histograms: d.histograms || {},
          allCategories: d.all_categories || [],
        });
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [sig]);

  // endReached -> load next page
  const loadMore = useCallback(async () => {
    const offsets = Object.keys(pages).map(Number).sort((a, b) => a - b);
    const next = offsets.length ? offsets.at(-1) + PAGE_SIZE_SERVER : 0;
    if (next >= meta.total || pages[next] !== undefined) return;
    const r = await fetch(`/api/papers-list?${sig}&offset=${next}&limit=${PAGE_SIZE_SERVER}&include_histograms=false`);
    const d = await r.json();
    setPages(prev => ({ ...prev, [next]: (d.rows || []).map(flattenPaper) }));
  }, [sig, pages, meta.total]);

  const rows = useMemo(() =>
    Object.keys(pages).map(Number).sort((a, b) => a - b).flatMap(k => pages[k]),
  [pages]);

  return { rows, total: meta.total, histograms: meta.histograms,
           allCategories: meta.allCategories, loading, loadMore };
}
```

---

## 7. Polars vectorisation on the server

**Why**: Per-row Python loops at 200k papers take ~250 ms even with cheap predicates. Polars columnar expressions do the same in 10–30 ms.

### Install

```
pip install polars
```

### Build the DataFrame once per dataset

```python
import polars as pl

_DF_CACHE = {}

def _papers_to_df(papers: list) -> pl.DataFrame:
    cols = {
        "paper_id": [p["paper_id"] for p in papers],
        "title":         [(p.get("title") or "") for p in papers],
        "_title_lower":  [(p.get("title") or "").lower() for p in papers],
        "category":      [p.get("category") or "" for p in papers],
        "categories":    [p.get("categories") or [] for p in papers],
        "authors":       [p.get("authors") or [] for p in papers],
        "_authors_lower":[[(a or "").lower() for a in (p.get("authors") or [])] for p in papers],
        "published":     [p.get("published") or "" for p in papers],
    }
    for m in ALL_METRICS:
        cols[m] = [(p.get("ratings") or {}).get(m) for p in papers]
    return pl.DataFrame(cols, schema_overrides={m: pl.Float64 for m in ALL_METRICS})

def get_df(key, loader_fn) -> pl.DataFrame:
    if key in _DF_CACHE: return _DF_CACHE[key]
    if len(_DF_CACHE) > 1: _DF_CACHE.clear()           # one dataset at a time
    df = _papers_to_df(loader_fn())
    _DF_CACHE[key] = df
    return df
```

### Vectorised filter

```python
def apply_filter(df, params):
    expr = pl.lit(True)

    q = (params.get("search") or "").strip().lower()
    if q:
        t = pl.col("_title_lower").str.contains(q, literal=True)
        a = pl.col("_authors_lower").list.eval(pl.element().str.contains(q, literal=True)).list.any()
        expr = expr & (t | a)

    cats = [c for c in (params.get("cats") or "").split(",") if c]
    if cats:
        mode  = params.get("cat_mode")  or "any"
        logic = params.get("cat_logic") or "or"
        if logic == "and" and len(cats) > 1:
            all_match = pl.lit(True)
            for c in cats:
                if mode == "primary":
                    all_match = all_match & (pl.col("category") == c)
                elif mode == "cross-listed":
                    all_match = all_match & pl.col("categories").list.contains(c) & (pl.col("category") != c)
                else:
                    all_match = all_match & pl.col("categories").list.contains(c)
            expr = expr & all_match
        else:
            if mode == "primary":
                cat_expr = pl.col("category").is_in(cats)
            elif mode == "cross-listed":
                in_sec = pl.col("categories").list.eval(pl.element().is_in(cats)).list.any()
                cat_expr = in_sec & pl.col("category").is_in(cats).not_()
            else:
                cat_expr = pl.col("categories").list.eval(pl.element().is_in(cats)).list.any()
            expr = expr & cat_expr

    include_nulls = params.get("include_nulls", True)
    for metric, (thr, op) in (params.get("thresholds") or {}).items():
        # No-op endpoints — never filter when the threshold can't restrict
        if op == "gte" and thr <= 0: continue
        if op == "lte" and (thr >= 10 or thr <= 0): continue
        col = pl.col(metric)
        comp = (col >= thr) if op == "gte" else (col <= thr)
        if include_nulls:
            expr = expr & (col.is_null() | comp)
        else:
            expr = expr & col.is_not_null() & comp

    return df.filter(expr)
```

### Vectorised sort and histogram

```python
def apply_sort(df, sort_key, sort_dir):
    descending = sort_dir == "desc"
    if sort_key == "title":
        return df.sort("_title_lower", descending=descending)
    if sort_key in ("category", "published"):
        return df.sort(sort_key, descending=descending, nulls_last=True)
    if sort_key in ALL_METRICS:
        # Nulls always last; stable tiebreaker
        return df.sort([sort_key, "paper_id"], descending=[descending, False], nulls_last=True)
    return df

import numpy as np
def compute_histograms(df, bins=10):
    out = {}
    for m in ALL_METRICS:
        arr = df[m].drop_nulls().to_numpy()
        if arr.size == 0:
            out[m] = {"counts": [0]*bins, "n": 0, "mean": None, "max": 1}
            continue
        counts, _ = np.histogram(arr, bins=bins, range=(1.0, 10.0))
        out[m] = {
            "counts": counts.astype(int).tolist(),
            "n": int(arr.size),
            "mean": float(arr.mean()),
            "max": int(counts.max()),
        }
    return out
```

### Slicing back to API shape

```python
OUTPUT_FIELDS = ["paper_id","title","category","categories","authors","published"] + ALL_METRICS

def rows_to_api_shape(df_page):
    rows = df_page.select(OUTPUT_FIELDS).to_dicts()
    out = []
    for r in rows:
        ratings = {m: r.get(m) for m in ALL_METRICS}
        out.append({
            "paper_id": r["paper_id"], "title": r["title"],
            "category": r["category"], "categories": r["categories"] or [],
            "authors": r["authors"] or [], "published": r["published"],
            "ratings": ratings,
        })
    return out
```

### Benchmarks (warm, our codebase)

| N       | Filter | Sort  | Histogram | Total |
|---------|-------:|------:|----------:|------:|
| 100k    |   3 ms | 17 ms |    7 ms   | 27 ms |
| 200k    |  13 ms | 33 ms |   28 ms   | 75 ms |
| 500k    |  31 ms | 22 ms |   28 ms   |~80 ms |

---

## 8. Stale-while-revalidate on server refetch

**Why**: Clearing the rows when a filter changes makes the list flash empty for 100–300 ms while the new page is in flight. Keep old rows visible, swap atomically.

```js
useEffect(() => {
  if (abortRef.current) abortRef.current.abort();
  const ctrl = new AbortController();
  abortRef.current = ctrl;
  setLoading(true);
  // ❌ DON'T: setPages({});   // causes flash
  fetch(url, { signal: ctrl.signal })
    .then(r => r.json())
    .then(d => {
      if (ctrl.signal.aborted) return;
      setPages({ 0: d.rows.map(flattenPaper) }); // ✅ atomic swap
      setLoading(false);
    });
  return () => ctrl.abort();
}, [sig]);
```

---

## Order of application

If you're porting only some of these, this is the order that gives you wins fastest without rework:

1. **Phase 0 instrumentation** (sections 1–2 above) — invest a day, every subsequent change is measurable.
2. **Phase 1A** (sections 2–4) — full week of latency wins, no new dependencies.
3. **Phase 1B virtualisation** (section 5) — adds `react-virtuoso`, removes the existing infinite-scroll plumbing.
4. **Phase 2 server endpoint** (sections 6 + 8) — biggest architectural change.
5. **Polars vectorisation** (section 7) — drops in under the existing endpoint without changing its contract.

Each tier is independently shippable. Tiers 3 and 4 are commutative; we did 3 first because it's cheaper.

---

## Customisation points

When porting, the things you'll have to adapt:

- **METRICS array shape**: This codebase has 11 numeric metrics with reason strings on 6 of them. Your data may have a different schema — the timing wrappers and virtualisation pattern don't care, but the polars DataFrame construction and the histogram loop expect numeric metrics.
- **`useListState` pattern**: We use a single state object with `search`, `categories`, `metricMin`, `metricOp`, `sortKey`, etc. Yours may be split differently — the only requirement is that filter-affecting deps can be enumerated separately from sort-affecting deps.
- **`flattenPaper` utility**: We flatten `paper.ratings.score` to top-level `paper.score` so the rest of the code doesn't care. Adapt to your shape.
- **`HoverTooltip` and `useIsHoverDevice`**: Optional but recommended — suppresses tooltips on touch devices so taps go to onClick instead of opening tooltips. Pattern is in `_shared.jsx`.

---

## What we explicitly did NOT do (and why)

- **Web Worker for filter/sort**: With polars on the server, the client never runs the heavy path. The worker would only help client-only mode.
- **`$facet` aggregation / `react-query` cache**: Polars made each query fast enough that caching has minimal user-facing benefit. Re-evaluate once you move to Mongo.
- **Mongo persistence + compound indexes**: Polars in-memory handles up to ~500k papers comfortably. Only worth the migration when you cross that or need durability.

---

## Source files in this codebase

For copy-paste reference:

- `/app/backend/routers/papers_list.py` — polars-backed endpoint
- `/app/backend/routers/scaling_test.py` — synthetic paper generator (handy for stress testing the new fork)
- `/app/frontend/src/pages/ListViewsTest/_shared.jsx` — `withTiming`, `measureBlock`, `usePerfDebounce`, `flattenPaper`, `useExtendedPapers`, `useServerPaperList`, `FilterBar`
- `/app/frontend/src/pages/ListViewsTest/PerfOverlay.jsx` — instrumentation overlay
- `/app/frontend/src/pages/ListViewsTest/HeatmapView.jsx` — the production list page (uses everything above)
- `/app/frontend/src/pages/ListViewsTest/ScaleTestPage.jsx` — scaling test harness with Client / Server toggle
