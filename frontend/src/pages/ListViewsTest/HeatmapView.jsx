import { useMemo, useState, useEffect, useRef } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown } from "lucide-react";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue, scoreColor, scoreTextColor,
} from "./_shared";

const PAGE_SIZE = 40;

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

  // Infinite scroll — render in pages of PAGE_SIZE on window scroll
  const [shown, setShown] = useState(PAGE_SIZE);
  const sentinelRef = useRef(null);

  useEffect(() => { setShown(PAGE_SIZE); }, [state.search, state.sortKey, state.sortDir, state.categories, state.metricMin, state.hidden, state.includeNulls, papers.length]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShown(prev => Math.min(prev + PAGE_SIZE, visible.length));
      }
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
    <TooltipProvider delayDuration={150}>
      <ListViewShell
        title="D — Heatmap Matrix"
        subtitle="Each row is a paper, each column a metric. Cell color = score (red → green). Hover any cell for value + reasoning. Click a column header to sort. Designed for spotting outliers and patterns across many papers."
      >
        <FilterBar state={state} setState={setState} papers={papers} showColumnToggle={true} />

        <div className="text-xs text-muted-foreground" data-testid="lv-count">
          {loading
            ? "Loading…"
            : `Showing ${rendered.length} of ${visible.length} filtered (n=${n} total)`}
        </div>

        <div className="border border-border rounded-lg bg-card" data-testid="lv-heatmap">
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-14 z-20 bg-card">
              <tr>
                <th className="text-left py-2 px-3 border-b border-border" style={{ width: 360 }}>
                  <button
                    onClick={() => setSort("title")}
                    className={`text-[10px] font-medium uppercase tracking-wider hover:text-foreground transition-colors inline-flex items-center gap-1 ${state.sortKey === "title" ? "text-foreground" : "text-muted-foreground"}`}
                    data-testid="lv-th-title"
                  >
                    Paper
                    {state.sortKey === "title" && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
                  </button>
                </th>
                {visibleMetrics.map(m => {
                  const active = state.sortKey === m.key;
                  return (
                    <th
                      key={m.key}
                      className="py-2 px-1 text-center border-b border-border"
                      style={{ width: 76 }}
                    >
                      <button
                        onClick={() => setSort(m.key)}
                        className="inline-flex items-center justify-center gap-1 text-[10px] px-1.5 py-0.5 rounded border w-full transition-all hover:brightness-110"
                        style={{
                          borderColor: m.color,
                          backgroundColor: active ? m.color : `${m.color}1f`,
                          color: active ? "#fff" : m.color,
                          fontWeight: active ? 600 : 500,
                        }}
                        title={`${m.label} — ${m.desc}`}
                        data-testid={`lv-th-${m.key}`}
                      >
                        <span className="truncate">{m.label}</span>
                        {active && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5 shrink-0" /> : <ArrowDown className="h-2.5 w-2.5 shrink-0" />)}
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rendered.map((p, i) => (
                <tr key={p.paper_id} data-testid={`lv-row-${i}`} className={i % 2 === 0 ? "bg-background" : "bg-secondary/10"}>
                  <td className="py-2 px-3 border-b border-border/30 align-middle" style={{ width: 360 }}>
                    <PaperCell paper={p} />
                  </td>
                  {visibleMetrics.map(m => {
                    const v = p[m.key];
                    const reason = m.reason ? p[`${m.key}_reason`] : null;
                    return (
                      <td key={m.key} className="p-0 border-b border-border/30" style={{ width: 76 }} data-testid={`cell-${i}-${m.key}`}>
                        <MetricValue metric={m} value={v} reason={reason}>
                          <div
                            className="w-full h-7 flex items-center justify-center font-mono text-[11px] tabular-nums cursor-default"
                            style={{
                              backgroundColor: scoreColor(v),
                              color: scoreTextColor(v),
                            }}
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
                <tr><td colSpan={1 + visibleMetrics.length} className="py-12 text-center text-muted-foreground">No papers match current filters.</td></tr>
              )}
            </tbody>
          </table>

          {/* Infinite-scroll sentinel */}
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

        <ColorRamp />
      </ListViewShell>
    </TooltipProvider>
  );
}

function PaperCell({ paper }) {
  const authors = formatAuthors(paper.authors);
  const date = formatPublished(paper.published);
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium leading-snug line-clamp-2" title={paper.title}>
        {paper.title}
      </div>
      <div className="flex items-center flex-wrap gap-x-1.5 gap-y-0.5 mt-1 text-[10px] text-muted-foreground">
        <span className="font-mono px-1 py-px rounded bg-secondary/70 text-muted-foreground" title={paper.category}>
          {paper.category || "—"}
        </span>
        {authors && <span className="truncate" title={(paper.authors || []).join(", ")}>{authors}</span>}
        {date && <>
          <span className="opacity-40">·</span>
          <span className="font-mono whitespace-nowrap">{date}</span>
        </>}
      </div>
    </div>
  );
}

function ColorRamp() {
  const stops = [1, 2, 3, 4, 5, 5.5, 6, 7, 8, 9, 10];
  return (
    <div className="text-[10px] text-muted-foreground flex items-center gap-2 border-t border-border/40 pt-3" data-testid="lv-color-ramp">
      <span>Color scale</span>
      <div className="flex">
        {stops.map(s => (
          <div key={s} className="w-5 h-3 flex items-center justify-center font-mono"
            style={{ backgroundColor: scoreColor(s), color: scoreTextColor(s) }}
            title={`Score ${s}`}
          />
        ))}
      </div>
      <span>1 (low) → 10 (high)</span>
    </div>
  );
}
