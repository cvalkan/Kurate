import { useMemo } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue,
} from "./_shared";

export default function SparklineView() {
  const { papers, loading, n } = useExtendedPapers();
  const [state, setState] = useListState("sparkline", { sortKey: "score", sortDir: "desc" });

  const visible = useMemo(() => {
    return applySort(applyFilters(papers, state), state);
  }, [papers, state]);

  const visibleMetrics = METRICS.filter(m => !state.hidden.has(m.key));

  return (
    <TooltipProvider delayDuration={150}>
      <ListViewShell
        title="C — Sparkline List"
        subtitle="Compact rows with inline mini bar-charts of all metrics per paper. Color-coded per dimension. Hover any bar to see the reasoning behind that metric."
      >
        <FilterBar state={state} setState={setState} papers={papers} showColumnToggle={true} />

        <div className="text-xs text-muted-foreground" data-testid="lv-count">
          {loading ? "Loading…" : `${visible.length} of ${papers.length} papers (n=${n})`}
        </div>

        {/* Top axis legend */}
        <div className="border border-border rounded-lg p-3 bg-card text-[10px] flex flex-wrap gap-3" data-testid="lv-legend">
          {visibleMetrics.map(m => (
            <span key={m.key} className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.color }} />
              <span style={{ color: m.color }}>{m.short}</span>
            </span>
          ))}
        </div>

        <div className="space-y-px" data-testid="lv-sparkline-list">
          {visible.map((p, i) => (
            <div
              key={p.paper_id}
              className={`grid items-center gap-3 px-3 py-2 rounded-md border border-border/40 ${i % 2 === 0 ? "bg-card" : "bg-secondary/20"} hover:border-accent/40 transition-colors`}
              style={{ gridTemplateColumns: "minmax(280px,1.5fr) 3.5rem 1fr" }}
              data-testid={`lv-row-${i}`}
            >
              <div className="min-w-0">
                <div className="text-xs font-medium truncate" title={p.title}>{p.title}</div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  <span className="font-mono">{p.category}</span>
                </div>
              </div>

              <div className="text-right font-mono text-sm tabular-nums" data-testid={`lv-score-${i}`}>
                {p.score != null ? p.score.toFixed(1) : "—"}
                <div className="text-[9px] text-muted-foreground uppercase tracking-wider">overall</div>
              </div>

              {/* Sparkline bars */}
              <div className="flex items-end gap-1 h-10">
                {visibleMetrics.map(m => {
                  const v = p[m.key];
                  const reason = m.reason ? p[`${m.key}_reason`] : null;
                  const h = v != null ? Math.max(2, (v / 10) * 40) : 2;
                  return (
                    <MetricValue key={m.key} metric={m} value={v} reason={reason || m.desc}>
                      <button
                        className="flex-1 min-w-[10px] flex flex-col items-center justify-end h-10 cursor-help group"
                        data-testid={`spark-${i}-${m.key}`}
                      >
                        <span
                          className="w-full rounded-sm transition-all group-hover:opacity-80"
                          style={{
                            height: `${h}px`,
                            backgroundColor: v != null ? m.color : "transparent",
                            border: v == null ? "1px dashed currentColor" : "none",
                            opacity: v != null ? 0.55 + 0.45 * (v / 10) : 0.3,
                          }}
                        />
                        <span className="text-[8px] font-mono mt-0.5 text-muted-foreground tabular-nums">
                          {v != null ? v.toFixed(1) : "—"}
                        </span>
                      </button>
                    </MetricValue>
                  );
                })}
              </div>
            </div>
          ))}
          {!loading && visible.length === 0 && (
            <div className="py-12 text-center text-muted-foreground text-sm">No papers match current filters.</div>
          )}
        </div>
      </ListViewShell>
    </TooltipProvider>
  );
}
