import { useMemo } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown } from "lucide-react";
import {
  METRICS, METRIC_BY_KEY, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue, scoreColor, scoreTextColor,
} from "./_shared";

export default function TableView() {
  const { papers, loading, n } = useExtendedPapers();
  const [state, setState] = useListState("table", { sortKey: "score", sortDir: "desc" });

  const visible = useMemo(() => {
    const filtered = applyFilters(papers, state);
    return applySort(filtered, state);
  }, [papers, state]);

  const visibleMetrics = METRICS.filter(m => !state.hidden.has(m.key));

  const setSort = (key) => setState(prev => ({
    ...prev,
    sortKey: key,
    sortDir: prev.sortKey === key ? (prev.sortDir === "asc" ? "desc" : "asc") : "desc",
  }));

  return (
    <TooltipProvider delayDuration={200}>
      <ListViewShell
        title="A — Dense Sortable Table"
        subtitle="One row per paper, one column per directly-extracted metric. Cells colored by value (red → grey → green). Hover any extended-metric cell for the model's one-sentence reasoning."
      >
        <FilterBar state={state} setState={setState} papers={papers} showColumnToggle={true} />

        <div className="text-xs text-muted-foreground" data-testid="lv-count">
          {loading ? "Loading…" : `${visible.length} of ${papers.length} papers (n=${n})`}
        </div>

        <div className="border border-border rounded-lg overflow-x-auto bg-card" data-testid="lv-table">
          <table className="text-xs w-full border-collapse">
            <thead className="bg-secondary/60 sticky top-0 z-10">
              <tr>
                <Th sortKey="title" state={state} onSort={setSort} className="text-left pl-3 min-w-[280px]">Paper</Th>
                <Th sortKey="category" state={state} onSort={setSort} className="text-left">Cat</Th>
                {visibleMetrics.map(m => (
                  <Th key={m.key} sortKey={m.key} state={state} onSort={setSort} className="text-right">
                    <span className="inline-flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: m.color }} />
                      {m.short}
                    </span>
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((p, i) => (
                <tr key={p.paper_id} className={`border-t border-border/40 ${i % 2 === 0 ? "bg-background" : "bg-secondary/10"}`} data-testid={`lv-row-${i}`}>
                  <td className="pl-3 py-1.5 pr-3">
                    <div className="font-medium leading-snug" title={p.title}>{p.title}</div>
                  </td>
                  <td className="py-1.5 px-2">
                    <span className="font-mono text-[10px] px-1 py-0.5 rounded bg-secondary text-muted-foreground">{p.category || "—"}</span>
                  </td>
                  {visibleMetrics.map(m => {
                    const value = p[m.key];
                    const reason = m.reason ? p[`${m.key}_reason`] : null;
                    return (
                      <td key={m.key} className="py-0.5 px-1 text-right" data-testid={`cell-${i}-${m.key}`}>
                        <MetricValue metric={m} value={value} reason={reason}>
                          <span
                            className="inline-block min-w-[2.4rem] font-mono text-right px-1.5 py-0.5 rounded cursor-default tabular-nums"
                            style={{
                              backgroundColor: scoreColor(value),
                              color: scoreTextColor(value),
                            }}
                          >
                            {value != null ? value.toFixed(1) : "—"}
                          </span>
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

        <Legend />
      </ListViewShell>
    </TooltipProvider>
  );
}

function Th({ children, sortKey, state, onSort, className = "" }) {
  const active = state.sortKey === sortKey;
  return (
    <th className={`py-2 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground select-none ${className}`}>
      <button
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-0.5 hover:text-foreground transition-colors ${active ? "text-foreground" : ""}`}
        data-testid={`lv-th-${sortKey}`}
      >
        {children}
        {active && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
      </button>
    </th>
  );
}

function Legend() {
  return (
    <div className="text-[10px] text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 border-t border-border/40 pt-3">
      <span>Cell color: <span className="px-1 rounded" style={{ backgroundColor: scoreColor(2), color: scoreTextColor(2) }}>low</span> <span className="px-1 rounded" style={{ backgroundColor: scoreColor(5.5) }}>mid</span> <span className="px-1 rounded" style={{ backgroundColor: scoreColor(9), color: scoreTextColor(9) }}>high</span></span>
      <span>Hover an extended-metric cell (Difficulty → Generalisability) to see the model's reasoning.</span>
    </div>
  );
  // METRIC_BY_KEY kept for future use
  // eslint-disable-next-line no-unused-vars
  const _ = METRIC_BY_KEY;
}
