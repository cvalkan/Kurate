import { useMemo } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown } from "lucide-react";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue, scoreColor, scoreTextColor,
} from "./_shared";

export default function HeatmapView() {
  const { papers, loading, n } = useExtendedPapers();
  const [state, setState] = useListState("heatmap", { sortKey: "score", sortDir: "desc" });

  const visible = useMemo(() => applySort(applyFilters(papers, state), state), [papers, state]);
  const visibleMetrics = METRICS.filter(m => !state.hidden.has(m.key));

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
          {loading ? "Loading…" : `${visible.length} of ${papers.length} papers (n=${n})`}
        </div>

        <div className="border border-border rounded-lg overflow-auto bg-card max-h-[80vh]" data-testid="lv-heatmap">
          <table className="w-full text-xs border-separate border-spacing-0">
            <thead className="sticky top-0 z-20 bg-secondary/80 backdrop-blur">
              <tr>
                <ColHeader sortKey="title" state={state} onSort={setSort}
                  className="text-left pl-3 min-w-[280px] sticky left-0 z-30 bg-secondary/80 backdrop-blur">
                  Paper
                </ColHeader>
                <ColHeader sortKey="category" state={state} onSort={setSort} className="text-left px-2">
                  Cat
                </ColHeader>
                {visibleMetrics.map(m => (
                  <th key={m.key} className="py-2 px-1 text-center border-b border-border" style={{ minWidth: 70 }}>
                    <button
                      onClick={() => setSort(m.key)}
                      className={`flex flex-col items-center gap-0.5 w-full hover:text-foreground transition-colors ${state.sortKey === m.key ? "text-foreground" : "text-muted-foreground"}`}
                      data-testid={`lv-th-${m.key}`}
                    >
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.color }} />
                      <span className="text-[10px] font-medium" style={{ color: state.sortKey === m.key ? m.color : "inherit" }}>
                        {m.short}
                      </span>
                      {state.sortKey === m.key && (
                        state.sortDir === "asc"
                          ? <ArrowUp className="h-2.5 w-2.5" />
                          : <ArrowDown className="h-2.5 w-2.5" />
                      )}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((p, i) => (
                <tr key={p.paper_id} data-testid={`lv-row-${i}`}>
                  <td
                    className={`pl-3 pr-2 py-1.5 border-b border-border/30 sticky left-0 z-10 ${i % 2 === 0 ? "bg-background" : "bg-secondary/10"}`}
                    style={{ maxWidth: 280 }}
                  >
                    <div className="text-xs font-medium leading-snug line-clamp-2" title={p.title}>{p.title}</div>
                  </td>
                  <td className={`px-2 py-1 border-b border-border/30 ${i % 2 === 0 ? "bg-background" : "bg-secondary/10"}`}>
                    <span className="font-mono text-[10px] px-1 py-0.5 rounded bg-secondary text-muted-foreground">{p.category || "—"}</span>
                  </td>
                  {visibleMetrics.map(m => {
                    const v = p[m.key];
                    const reason = m.reason ? p[`${m.key}_reason`] : null;
                    return (
                      <td key={m.key} className="p-0 border-b border-border/30" data-testid={`cell-${i}-${m.key}`}>
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
                <tr><td colSpan={2 + visibleMetrics.length} className="py-12 text-center text-muted-foreground">No papers match current filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <ColorRamp />
      </ListViewShell>
    </TooltipProvider>
  );
}

function ColHeader({ children, sortKey, state, onSort, className = "" }) {
  const active = state.sortKey === sortKey;
  return (
    <th className={`py-2 text-[10px] font-medium uppercase tracking-wider border-b border-border ${className}`}>
      <button
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-0.5 hover:text-foreground transition-colors ${active ? "text-foreground" : "text-muted-foreground"}`}
        data-testid={`lv-th-${sortKey}`}
      >
        {children}
        {active && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
      </button>
    </th>
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
