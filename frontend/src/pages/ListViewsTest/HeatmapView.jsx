import { useMemo, useState, useEffect, useRef, useCallback, Profiler, memo, forwardRef } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown, AlignLeft, BarChart3 } from "lucide-react";
import { TableVirtuoso } from "react-virtuoso";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue, scoreColor, scoreTextColor,
  computeMiniHistogram, HoverTooltip, measureBlock, useServerPaperList,
} from "./_shared";

const METRIC_COL_WIDTH = 56;
const DATE_COL_WIDTH = 78;

function formatPublished(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

function formatAuthors(authors) {
  if (!authors || authors.length === 0) return null;
  if (authors.length <= 2) return authors.join(", ");
  return `${authors[0]}, ${authors[1]} +${authors.length - 2}`;
}

export default function HeatmapView() {
  const data = useExtendedPapers();
  return <HeatmapPage data={data} listStateKey="heatmap" />;
}

/**
 * Reusable heatmap page that takes its data as a prop.
 * Used by the production heatmap and by the scaling test environment.
 *
 * @param data           { papers, loading, n, error? }
 * @param listStateKey   localStorage key for filter/sort state
 * @param headerExtras   optional React node rendered above the filter bar (used by scaling test for controls)
 * @param titleOverride  optional alternative page title
 * @param subtitleOverride optional alternative subtitle
 */
export function HeatmapPage({ data, serverSource, listStateKey = "heatmap", headerExtras = null, titleOverride, subtitleOverride }) {
  const isServer = !!serverSource;
  // Default-fill data for client mode so destructuring is safe
  const { papers = [], loading: clientLoading = false, n: clientTotal = 0 } = data || {};

  const [state, setState] = useListState(listStateKey, { sortKey: "score", sortDir: "desc" });

  // --- Client-side computations (always run for client mode; cheap no-ops if serverSource set)
  const filtered = useMemo(() => isServer ? [] : applyFilters(papers, state), [
    isServer, papers,
    state.search, state.dateRange,
    state.categories, state.categoryMode, state.categoryLogic,
    state.metricMin, state.metricOp, state.includeNulls,
  ]);
  const clientVisible = useMemo(() => isServer ? [] : applySort(filtered, state), [
    isServer, filtered, state.sortKey, state.sortDir,
  ]);
  const visibleMetrics = useMemo(() => METRICS.filter(m => !state.hidden.has(m.key)), [state.hidden]);
  const clientHistograms = useMemo(() => isServer ? {} : measureBlock("perf:histogram", () => {
    const out = {};
    visibleMetrics.forEach(m => { out[m.key] = computeMiniHistogram(filtered, m.key, 10); });
    return out;
  }), [isServer, filtered, visibleMetrics]);

  // --- Server-side data path
  const server = useServerPaperList(state, isServer ? serverSource : null);

  // --- Pick the active provider
  const rows = isServer ? server.rows : clientVisible;
  const total = isServer ? server.total : clientVisible.length;
  const histograms = isServer ? (server.histograms || {}) : clientHistograms;
  const datasetSize = isServer ? server.datasetSize : (clientTotal || papers.length);
  const loading = isServer ? server.loading : clientLoading;
  const serverLoadMore = isServer ? server.loadMore : null;
  const serverTiming = isServer ? server.serverTiming : null;
  const headerMode = state.headerMode || "labels";

  // Items passed to TableVirtuoso. In server mode `rows` is the accumulated server pages.
  const visible = rows;

  // For FilterBar's category list — in server mode the dataset can be huge, so we synthesize
  // pseudo-papers from the server-returned category list (FilterBar only iterates them for tags).
  const serverFilterBarPapers = useMemo(() =>
    server.allCategories.map(c => ({ category: c, categories: [c] })),
  [server.allCategories]);
  const filterBarPapers = isServer ? serverFilterBarPapers : papers;

  const setSort = useCallback((key) => setState(prev => ({
    ...prev,
    sortKey: key,
    sortDir: prev.sortKey === key ? (prev.sortDir === "asc" ? "desc" : "asc") : "desc",
  })), [setState]);

  // Stable per-row renderer for TableVirtuoso. Memoised externally; identity stays the same
  // until visibleMetrics changes (which it does on column show/hide).
  const itemContent = useCallback((index, paper) => (
    <HeatmapRowCells paper={paper} index={index} visibleMetrics={visibleMetrics} />
  ), [visibleMetrics]);

  // Custom Table component so we can inject <colgroup> and the rounded card styling.
  const TableComponent = useMemo(() => {
    const Comp = ({ style, children, ...rest }) => (
      <table {...rest} className="w-full text-xs border-collapse table-fixed" style={style}>
        <colgroup>
          <col style={{ width: DATE_COL_WIDTH }} />
          <col className="w-[260px] min-w-[230px] sm:w-auto sm:min-w-[340px]" />
          {visibleMetrics.map(m => <col key={m.key} style={{ width: METRIC_COL_WIDTH }} />)}
        </colgroup>
        {children}
      </table>
    );
    return Comp;
  }, [visibleMetrics]);

  const virtuosoComponents = useMemo(() => ({
    Table: TableComponent,
    TableHead: forwardRef(function TableHeadComp({ children, ...props }, ref) {
      return (
        <thead ref={ref} {...props} className="sticky top-0 z-20 bg-card">
          {children}
        </thead>
      );
    }),
    TableRow: forwardRef(function TableRowComp({ children, ...props }, ref) {
      const idx = parseInt(props["data-index"], 10);
      const stripe = Number.isFinite(idx) && idx % 2 === 1 ? "bg-secondary/10" : "bg-background";
      return (
        <tr ref={ref} {...props} className={stripe} style={{ height: 72 }} data-testid={`lv-row-${Number.isFinite(idx) ? idx : ""}`}>
          {children}
        </tr>
      );
    }),
    EmptyPlaceholder: () => (
      <tbody>
        <tr><td colSpan={2 + visibleMetrics.length} className="py-12 text-center text-muted-foreground">
          {loading ? "Loading…" : "No papers match current filters."}
        </td></tr>
      </tbody>
    ),
  }), [TableComponent, visibleMetrics, loading]);

  const fixedHeaderContent = useCallback(() => (
    <tr>
      <th className="text-left py-2 px-3 border-b border-border bg-card">
        <button
          onClick={() => setSort("published")}
          className={`text-[10px] font-medium hover:text-foreground transition-colors inline-flex items-center gap-1 ${state.sortKey === "published" ? "text-foreground" : "text-muted-foreground"}`}
          data-testid="lv-th-published"
          title="Sort by publication date"
        >
          Published
          {state.sortKey === "published" && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
        </button>
      </th>
      <th className="text-left py-2 px-3 border-b border-border bg-card">
        <button
          onClick={() => setSort("title")}
          className={`text-[10px] font-medium hover:text-foreground transition-colors inline-flex items-center gap-1 ${state.sortKey === "title" ? "text-foreground" : "text-muted-foreground"}`}
          data-testid="lv-th-title"
        >
          Paper
          {state.sortKey === "title" && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
        </button>
      </th>
      {visibleMetrics.map(m => {
        const active = state.sortKey === m.key;
        return (
          <th key={m.key} className="py-2 text-center border-b border-border bg-card">
            <HoverTooltip
              content={
                <div className="space-y-1">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.color }} />
                    <span className="text-[11px] font-medium">{m.label}</span>
                  </div>
                  <p className="text-[11px] leading-snug">{m.desc}</p>
                  {headerMode === "charts" && histograms[m.key] && histograms[m.key].n > 0 && (
                    <p className="text-[10px] text-muted-foreground">
                      Distribution across {histograms[m.key].n} visible papers · mean {histograms[m.key].mean?.toFixed(1)}
                    </p>
                  )}
                </div>
              }
            >
              <button
                onClick={() => setSort(m.key)}
                className={`inline-flex items-center justify-center text-[10px] font-medium w-full transition-colors hover:text-foreground tabular-nums ${active ? "text-foreground" : "text-muted-foreground"}`}
                data-testid={`lv-th-${m.key}`}
              >
                {headerMode === "charts" ? (
                  <MiniColumnChart metric={m} hist={histograms[m.key]} active={active} />
                ) : (
                  <>
                    <span className="truncate">{m.short}</span>
                    {active && (state.sortDir === "asc" ? <ArrowUp className="h-2 w-2 shrink-0 ml-px" /> : <ArrowDown className="h-2 w-2 shrink-0 ml-px" />)}
                  </>
                )}
              </button>
            </HoverTooltip>
          </th>
        );
      })}
    </tr>
  ), [state.sortKey, state.sortDir, visibleMetrics, headerMode, histograms, setSort]);

  return (
    <TooltipProvider delayDuration={120} skipDelayDuration={0} disableHoverableContent>
      <ListViewShell
        title={titleOverride ?? "D — Heatmap Matrix"}
        subtitle={subtitleOverride ?? "Each row is a paper, each column a metric. Cell color = score (red → green). Hover a cell for value + reasoning, hover a column header for the metric description. Click a header to sort."}
      >
        {headerExtras}
        <FilterBar state={state} setState={setState} papers={filterBarPapers} showColumnToggle={true} />

        <div className="flex flex-wrap items-center justify-between gap-3" data-testid="lv-count-row">
          <div className="text-xs text-muted-foreground" data-testid="lv-count">
            {loading
              ? "Loading…"
              : isServer
                ? `${total.toLocaleString()} filtered (${datasetSize.toLocaleString()} total) · server-paged · ${rows.length} loaded${serverTiming ? ` · last query ${serverTiming.total}ms` : ""}`
                : `${total.toLocaleString()} filtered (${datasetSize.toLocaleString()} total) · virtualized`}
          </div>
          <div className="flex items-center gap-3">
            <div className="inline-flex rounded-md border border-border overflow-hidden" data-testid="lv-header-mode">
              <button
                onClick={() => setState({ headerMode: "labels" })}
                className={`p-1 transition-colors ${headerMode === "labels" ? "bg-accent text-accent-foreground" : "bg-background hover:bg-secondary text-muted-foreground"}`}
                title="Show metric names in column headers"
                data-testid="lv-header-mode-labels"
              >
                <AlignLeft className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setState({ headerMode: "charts" })}
                className={`p-1 transition-colors ${headerMode === "charts" ? "bg-accent text-accent-foreground" : "bg-background hover:bg-secondary text-muted-foreground"}`}
                title="Show distribution histograms in column headers"
                data-testid="lv-header-mode-charts"
              >
                <BarChart3 className="h-3.5 w-3.5" />
              </button>
            </div>
            <ColorRamp />
          </div>
        </div>

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
          <div className="border border-border rounded-lg bg-card" style={{ overflowX: "auto" }} data-testid="lv-heatmap">
            <TableVirtuoso
              useWindowScroll
              data={visible}
              increaseViewportBy={{ top: 400, bottom: 800 }}
              endReached={serverLoadMore || undefined}
              components={virtuosoComponents}
              fixedHeaderContent={fixedHeaderContent}
              itemContent={itemContent}
              computeItemKey={(_, p) => p.paper_id}
            />
          </div>
        </Profiler>
      </ListViewShell>
    </TooltipProvider>
  );
}

function MiniColumnChart({ metric, hist, active }) {
  if (!hist || hist.n === 0) {
    return <span className="text-[10px] text-muted-foreground">—</span>;
  }
  const { counts, max, mean } = hist;
  const w = 48;
  const h = 22;        // back to compact height now that axis labels are gone
  const chartH = 20;   // histogram bars region height
  const barW = w / counts.length;
  const xForScore = (s) => ((s - 1) / 9) * w;
  return (
    <svg width={w} height={h} className="block" aria-hidden>
      {/* Histogram bars (top region) */}
      {counts.map((c, i) => {
        const bh = (c / max) * (chartH - 2);
        return (
          <rect
            key={i}
            x={i * barW}
            y={chartH - bh}
            width={Math.max(1, barW - 0.5)}
            height={bh}
            fill={metric.color}
            opacity={active ? 0.9 : 0.6}
          />
        );
      })}
      {/* Baseline rule at the bottom — provides axis orientation without numbers */}
      <line x1={0} x2={w} y1={chartH + 0.5} y2={chartH + 0.5} stroke="currentColor" strokeWidth={1} opacity={0.4} />
    </svg>
  );
}


function _PaperCell({ paper }) {
  const authors = formatAuthors(paper.authors);
  const cats = paper.categories && paper.categories.length > 0 ? paper.categories : (paper.category ? [paper.category] : []);
  const primary = paper.category || cats[0];
  return (
    <div className="min-w-0">
      <div
        className="text-xs font-medium leading-tight line-clamp-2 min-h-[2em]"
        title={paper.title}
      >
        {paper.title}
      </div>
      <div className="flex items-center flex-nowrap gap-1.5 mt-1 overflow-hidden">
        {authors && (
          <span className="text-[11px] text-muted-foreground truncate shrink min-w-0" title={(paper.authors || []).join(", ")}>
            {authors}
          </span>
        )}
        <div className="flex items-center gap-1 shrink-0">
          {cats.map(cat => {
            const isPrimary = cat === primary;
            return (
              <span
                key={cat}
                className="font-mono text-[9px] leading-none px-1 py-0.5 rounded border whitespace-nowrap"
                style={isPrimary
                  ? { borderColor: "hsl(var(--accent))", color: "hsl(var(--accent))", backgroundColor: "hsl(var(--accent) / 0.10)" }
                  : { borderColor: "hsl(var(--border))", color: "hsl(var(--muted-foreground))", backgroundColor: "hsl(var(--secondary) / 0.4)" }}
                title={isPrimary ? `Primary category: ${cat}` : `Cross-listed: ${cat}`}
              >
                {cat}
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}
const PaperCell = memo(_PaperCell);

function _HeatmapRowCells({ paper, index, visibleMetrics }) {
  return (
    <>
      <td className="py-2 px-3 border-b border-border/30 align-top">
        <span className="text-[11px] text-muted-foreground whitespace-nowrap leading-tight">
          {formatPublished(paper.published) || "—"}
        </span>
      </td>
      <td className="py-2 px-3 border-b border-border/30 align-top">
        <PaperCell paper={paper} />
      </td>
      {visibleMetrics.map(m => {
        const v = paper[m.key];
        const reason = m.reason ? paper[`${m.key}_reason`] : null;
        return (
          <td key={m.key} className="p-0 border-b border-border/30" data-testid={`cell-${index}-${m.key}`}>
            <MetricValue metric={m} value={v} reason={reason}>
              <div
                className="w-full h-7 flex items-center justify-center text-[11px] font-medium tabular-nums cursor-default"
                style={{ backgroundColor: scoreColor(v), color: scoreTextColor(v) }}
              >
                {v != null ? v.toFixed(1) : <span className="text-muted-foreground opacity-50">—</span>}
              </div>
            </MetricValue>
          </td>
        );
      })}
    </>
  );
}
const HeatmapRowCells = memo(_HeatmapRowCells);

function ColorRamp() {
  const stops = [1, 2, 3, 4, 5, 5.5, 6, 7, 8, 9, 10];
  return (
    <div className="text-[10px] text-muted-foreground inline-flex items-center gap-1.5 shrink-0" data-testid="lv-color-ramp">
      <span>1</span>
      <div className="inline-flex border border-border/40 rounded-sm overflow-hidden">
        {stops.map(s => (
          <div key={s} className="w-3 h-3"
            style={{ backgroundColor: scoreColor(s) }}
            title={`Score ${s}`}
          />
        ))}
      </div>
      <span>10</span>
      <span className="ml-1">cell score</span>
    </div>
  );
}
