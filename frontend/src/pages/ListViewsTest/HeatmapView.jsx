import { useMemo, useState, useEffect, useRef } from "react";
import { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown, AlignLeft, BarChart3 } from "lucide-react";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue, scoreColor, scoreTextColor,
  computeMiniHistogram,
} from "./_shared";

const PAGE_SIZE = 40;
const METRIC_COL_WIDTH = 56;   // uniform width for every metric column
const DATE_COL_WIDTH = 78;     // dedicated Published column

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
  const { papers, loading, n } = useExtendedPapers();
  const [state, setState] = useListState("heatmap", { sortKey: "score", sortDir: "desc" });

  const visible = useMemo(() => applySort(applyFilters(papers, state), state), [papers, state]);
  const visibleMetrics = METRICS.filter(m => !state.hidden.has(m.key));
  const headerMode = state.headerMode || "labels";

  // Per-column distribution histograms (over the currently visible / filtered papers)
  const histograms = useMemo(() => {
    const out = {};
    visibleMetrics.forEach(m => { out[m.key] = computeMiniHistogram(visible, m.key, 10); });
    return out;
  }, [visible, visibleMetrics]);

  const [shown, setShown] = useState(PAGE_SIZE);
  const sentinelRef = useRef(null);

  useEffect(() => { setShown(PAGE_SIZE); }, [state.search, state.sortKey, state.sortDir, state.categories, state.metricMin, state.hidden, state.includeNulls, papers.length]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setShown(prev => Math.min(prev + PAGE_SIZE, visible.length));
    }, { rootMargin: "600px" });
    observer.observe(el);
    return () => observer.disconnect();
  }, [visible.length]);

  const rendered = visible.slice(0, shown);
  const hasMore = shown < visible.length;

  const setSort = (key) => setState(prev => ({
    ...prev,
    sortKey: key,
    sortDir: prev.sortKey === key ? (prev.sortDir === "asc" ? "desc" : "asc") : "desc",
  }));

  return (
    <TooltipProvider delayDuration={120} skipDelayDuration={0} disableHoverableContent>
      <ListViewShell
        title="D — Heatmap Matrix"
        subtitle="Each row is a paper, each column a metric. Cell color = score (red → green). Hover a cell for value + reasoning, hover a column header for the metric description. Click a header to sort."
      >
        <FilterBar state={state} setState={setState} papers={papers} showColumnToggle={true} />

        <div className="flex items-center justify-between gap-3" data-testid="lv-count-row">
          <div className="text-xs text-muted-foreground" data-testid="lv-count">
            {loading
              ? "Loading…"
              : `Showing ${rendered.length} of ${visible.length} filtered (${n} total)`}
          </div>
          <div className="flex items-center gap-3">
            {/* Header-mode toggle: text labels ↔ distribution charts */}
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

        <div className="border border-border rounded-lg bg-card" style={{ overflow: "clip" }} data-testid="lv-heatmap">
          <table className="w-full text-xs border-collapse table-fixed">
            <colgroup>
              <col style={{ width: DATE_COL_WIDTH }} />
              <col />
              {visibleMetrics.map(m => <col key={m.key} style={{ width: METRIC_COL_WIDTH }} />)}
            </colgroup>
            <thead className="sticky top-14 z-20 bg-card">
              <tr>
                <th className="text-left py-2 px-3 border-b border-border">
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
                <th className="text-left py-2 px-3 border-b border-border">
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
                    <th key={m.key} className="py-2 text-center border-b border-border">
                      <Tooltip>
                        <TooltipTrigger asChild>
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
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs bg-popover text-popover-foreground border border-border shadow-md">
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
                        </TooltipContent>
                      </Tooltip>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rendered.map((p, i) => (
                <tr key={p.paper_id} data-testid={`lv-row-${i}`} className={i % 2 === 0 ? "bg-background" : "bg-secondary/10"} style={{ height: 72 }}>
                  <td className="py-2 px-3 border-b border-border/30 align-top">
                    <span className="text-[11px] text-muted-foreground whitespace-nowrap leading-tight">{formatPublished(p.published) || "—"}</span>
                  </td>
                  <td className="py-2 px-3 border-b border-border/30 align-top">
                    <PaperCell paper={p} />
                  </td>
                  {visibleMetrics.map(m => {
                    const v = p[m.key];
                    const reason = m.reason ? p[`${m.key}_reason`] : null;
                    return (
                      <td key={m.key} className="p-0 border-b border-border/30" data-testid={`cell-${i}-${m.key}`}>
                        <MetricValue metric={m} value={v} reason={reason}>
                          <div
                            className="w-full h-7 flex items-center justify-center font-mono text-[11px] tabular-nums cursor-default"
                            style={{ backgroundColor: scoreColor(v), color: scoreTextColor(v) }}
                          >
                            {v != null ? v.toFixed(1) : <span className="text-muted-foreground opacity-50">—</span>}
                          </div>
                        </MetricValue>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {!loading && visible.length === 0 && (
                <tr><td colSpan={2 + visibleMetrics.length} className="py-12 text-center text-muted-foreground">No papers match current filters.</td></tr>
              )}
            </tbody>
          </table>

          {hasMore && (
            <div ref={sentinelRef} className="py-3 text-center text-[10px] text-muted-foreground" data-testid="lv-infinite-sentinel">
              Loading more papers… ({visible.length - shown} remaining)
            </div>
          )}
          {!hasMore && visible.length > PAGE_SIZE && (
            <div className="py-3 text-center text-[10px] text-muted-foreground">
              End of results · {visible.length} papers
            </div>
          )}
        </div>
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
  const h = 22;
  const barW = w / counts.length;
  return (
    <svg width={w} height={h} className="block" aria-hidden>
      {counts.map((c, i) => {
        const bh = (c / max) * (h - 3);
        return (
          <rect
            key={i}
            x={i * barW}
            y={h - bh}
            width={Math.max(1, barW - 0.5)}
            height={bh}
            fill={metric.color}
            opacity={active ? 0.9 : 0.6}
          />
        );
      })}
      {mean != null && (
        <line
          x1={((mean - 1) / 9) * w}
          x2={((mean - 1) / 9) * w}
          y1={0} y2={h}
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="2 1.5"
          opacity={0.6}
        />
      )}
    </svg>
  );
}


function PaperCell({ paper }) {
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
