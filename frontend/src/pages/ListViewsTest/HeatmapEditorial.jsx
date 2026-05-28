import { useMemo, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown, ChevronDown, ChevronRight, Hash, EyeOff } from "lucide-react";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell, MetricValue,
  metricHueColor, metricHueTextColor, computeMiniHistogram,
} from "./_shared";

const CORE_KEYS = ["score", "significance", "rigor", "novelty", "clarity"];

/**
 * E — Editorial Heatmap
 * Improvements over D:
 *  - Visual grouping: Core (5) | divider | Extended (6)
 *  - Per-metric brand-color hue scaling intensity by value (not red/green for all)
 *  - Numberless cells by default — toggle to show values; hover/tap for tooltip
 *  - Click a row to expand inline reasoning for all extended metrics for that paper
 *  - Per-column distribution sparkline strip with mean marker above each column
 */
export default function HeatmapEditorial() {
  const { papers, loading, n } = useExtendedPapers();
  const [state, setState] = useListState("heatmap-editorial", { sortKey: "score", sortDir: "desc" });
  const [showNumbers, setShowNumbers] = useState(false);
  const [expanded, setExpanded] = useState(() => new Set());

  const visible = useMemo(() => applySort(applyFilters(papers, state), state), [papers, state]);
  const visibleMetrics = METRICS.filter(m => !state.hidden.has(m.key));
  const coreMetrics = visibleMetrics.filter(m => CORE_KEYS.includes(m.key));
  const extendedMetrics = visibleMetrics.filter(m => !CORE_KEYS.includes(m.key));

  const histograms = useMemo(() => {
    const h = {};
    visibleMetrics.forEach(m => { h[m.key] = computeMiniHistogram(visible, m.key, 8); });
    return h;
  }, [visible, visibleMetrics]);

  const setSort = (key) => setState(prev => ({
    ...prev,
    sortKey: key,
    sortDir: prev.sortKey === key ? (prev.sortDir === "asc" ? "desc" : "asc") : "desc",
  }));

  const toggleRow = (id) => setExpanded(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return (
    <TooltipProvider delayDuration={120}>
      <ListViewShell
        title="E — Editorial Heatmap"
        subtitle="Each metric uses its own hue (intensity = score), with a hard visual break between the 5 core dimensions and the 6 extended dimensions. Click any row to expand all of that paper's reasonings inline. The strip above each column shows the distribution across visible papers."
      >
        <FilterBar state={state} setState={setState} papers={papers} showColumnToggle={true} />

        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground" data-testid="lv-count">
            {loading ? "Loading…" : `${visible.length} of ${papers.length} papers (n=${n})`}
          </div>
          <button
            onClick={() => setShowNumbers(v => !v)}
            className="inline-flex items-center gap-1 text-[11px] py-1 px-2 rounded border border-border bg-background hover:bg-secondary"
            data-testid="lv-toggle-numbers"
          >
            {showNumbers ? <EyeOff className="h-3 w-3" /> : <Hash className="h-3 w-3" />}
            {showNumbers ? "Hide values" : "Show values"}
          </button>
        </div>

        <div className="border border-border rounded-lg overflow-auto bg-card max-h-[80vh]" data-testid="lv-heatmap-editorial">
          <table className="w-full text-xs border-separate border-spacing-0">
            <thead className="sticky top-0 z-20 bg-card">
              {/* Distribution sparkline row */}
              <tr>
                <th className="bg-card sticky left-0 z-30" />
                <th className="bg-card" />
                {coreMetrics.map(m => (
                  <ColumnSpark key={m.key} metric={m} hist={histograms[m.key]} />
                ))}
                {extendedMetrics.length > 0 && <th className="bg-card border-l-2 border-accent/30" style={{ width: 6 }} />}
                {extendedMetrics.map(m => (
                  <ColumnSpark key={m.key} metric={m} hist={histograms[m.key]} />
                ))}
              </tr>
              {/* Group headers */}
              <tr className="bg-secondary/40">
                <th className="sticky left-0 z-30 bg-secondary/80 backdrop-blur" />
                <th className="bg-secondary/80 backdrop-blur" />
                <th colSpan={coreMetrics.length} className="px-1 py-1 text-[9px] font-mono uppercase tracking-wider text-muted-foreground text-center border-b border-border">
                  Core (5)
                </th>
                {extendedMetrics.length > 0 && <th className="bg-card border-l-2 border-accent/30" style={{ width: 6 }} />}
                <th colSpan={extendedMetrics.length} className="px-1 py-1 text-[9px] font-mono uppercase tracking-wider text-accent text-center border-b border-border">
                  Extended (6) — hover or click for reasoning
                </th>
              </tr>
              {/* Sortable header row */}
              <tr className="bg-secondary/80 backdrop-blur">
                <th className="sticky left-0 z-30 bg-secondary/80 backdrop-blur w-6" />
                <ColHeader sortKey="title" state={state} onSort={setSort}
                  className="text-left pl-1 min-w-[260px] sticky left-6 z-20 bg-secondary/80 backdrop-blur">
                  Paper
                </ColHeader>
                {coreMetrics.map(m => (
                  <MetricColHeader key={m.key} metric={m} state={state} onSort={setSort} />
                ))}
                {extendedMetrics.length > 0 && <th className="bg-card border-l-2 border-accent/30" style={{ width: 6 }} />}
                {extendedMetrics.map(m => (
                  <MetricColHeader key={m.key} metric={m} state={state} onSort={setSort} />
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((p, i) => {
                const isOpen = expanded.has(p.paper_id);
                const stripeBg = i % 2 === 0 ? "bg-background" : "bg-secondary/10";
                return (
                  <RowGroup
                    key={p.paper_id}
                    paper={p}
                    rowIdx={i}
                    isOpen={isOpen}
                    onToggle={() => toggleRow(p.paper_id)}
                    coreMetrics={coreMetrics}
                    extendedMetrics={extendedMetrics}
                    showNumbers={showNumbers}
                    stripeBg={stripeBg}
                  />
                );
              })}
              {!loading && visible.length === 0 && (
                <tr><td colSpan={3 + visibleMetrics.length} className="py-12 text-center text-muted-foreground">No papers match current filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <Legend showNumbers={showNumbers} />
      </ListViewShell>
    </TooltipProvider>
  );
}

function RowGroup({ paper, rowIdx, isOpen, onToggle, coreMetrics, extendedMetrics, showNumbers, stripeBg }) {
  return (
    <>
      <tr className={`hover:bg-accent/5 transition-colors ${stripeBg}`} data-testid={`lv-row-${rowIdx}`}>
        <td className={`sticky left-0 z-10 ${stripeBg} pl-1 w-6 border-b border-border/30`}>
          <button onClick={onToggle} className="w-5 h-5 inline-flex items-center justify-center rounded hover:bg-secondary" data-testid={`lv-row-toggle-${rowIdx}`}>
            {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
          </button>
        </td>
        <td className={`pr-2 py-1 border-b border-border/30 sticky left-6 z-10 ${stripeBg}`} style={{ maxWidth: 260 }}>
          <button onClick={onToggle} className="text-left w-full">
            <div className="text-xs font-medium leading-snug line-clamp-2" title={paper.title}>{paper.title}</div>
            <div className="text-[9px] font-mono text-muted-foreground mt-0.5">{paper.category}</div>
          </button>
        </td>
        {coreMetrics.map(m => <Cell key={m.key} metric={m} paper={paper} showNumbers={showNumbers} rowIdx={rowIdx} />)}
        {extendedMetrics.length > 0 && <td className="border-l-2 border-accent/30 border-b border-border/30" style={{ width: 6 }} />}
        {extendedMetrics.map(m => <Cell key={m.key} metric={m} paper={paper} showNumbers={showNumbers} rowIdx={rowIdx} />)}
      </tr>
      {isOpen && (
        <tr className="bg-accent/[0.04]">
          <td className="sticky left-0 z-10 bg-accent/[0.06] border-b border-border" />
          <td colSpan={2 + coreMetrics.length + (extendedMetrics.length > 0 ? 1 : 0) + extendedMetrics.length} className="px-4 py-3 border-b border-border" data-testid={`lv-row-detail-${rowIdx}`}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2">
              {extendedMetrics.filter(m => m.reason).map(m => {
                const v = paper[m.key];
                const r = paper[`${m.key}_reason`];
                if (v == null && !r) return null;
                return (
                  <div key={m.key} className="flex gap-2 items-start">
                    <span className="shrink-0 w-2 h-2 rounded-full mt-1.5" style={{ backgroundColor: m.color }} />
                    <div className="min-w-0">
                      <div className="text-[10px] font-medium" style={{ color: m.color }}>
                        {m.label} <span className="font-mono text-foreground">· {v != null ? v.toFixed(1) : "—"}</span>
                      </div>
                      <div className="text-[11px] text-muted-foreground leading-snug mt-0.5">{r || <i>No reasoning recorded.</i>}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Cell({ metric, paper, showNumbers, rowIdx }) {
  const v = paper[metric.key];
  const reason = metric.reason ? paper[`${metric.key}_reason`] : null;
  const bg = metricHueColor(metric, v);
  const fg = metricHueTextColor(metric, v);
  return (
    <td className="p-0 border-b border-border/30" data-testid={`cell-${rowIdx}-${metric.key}`}>
      <MetricValue metric={metric} value={v} reason={reason}>
        <div
          className="w-full h-7 flex items-center justify-center font-mono text-[10.5px] tabular-nums cursor-default border-r border-border/20"
          style={{ backgroundColor: bg, color: fg, minWidth: 52 }}
        >
          {showNumbers ? (v != null ? v.toFixed(1) : "·") : ""}
        </div>
      </MetricValue>
    </td>
  );
}

function MetricColHeader({ metric, state, onSort }) {
  const active = state.sortKey === metric.key;
  return (
    <th className="py-1.5 px-1 text-center border-b border-border" style={{ minWidth: 56 }}>
      <button
        onClick={() => onSort(metric.key)}
        className={`flex flex-col items-center gap-0.5 w-full transition-colors ${active ? "" : "text-muted-foreground hover:text-foreground"}`}
        style={active ? { color: metric.color } : undefined}
        data-testid={`lv-th-${metric.key}`}
        title={metric.desc}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: metric.color }} />
        <span className="text-[10px] font-medium">{metric.short}</span>
        {active && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
      </button>
    </th>
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

function ColumnSpark({ metric, hist }) {
  if (!hist || hist.n === 0) return <th className="p-0" />;
  const { counts, max, mean } = hist;
  const w = 56;
  const h = 24;
  const barW = w / counts.length;
  return (
    <th className="p-0 align-bottom" style={{ minWidth: 56 }} title={`Distribution of ${metric.label} across visible papers (mean ${mean?.toFixed(1)})`}>
      <svg width={w} height={h} className="block mx-auto">
        {counts.map((c, i) => {
          const bh = (c / max) * (h - 4);
          return (
            <rect
              key={i}
              x={i * barW + 1}
              y={h - bh}
              width={barW - 2}
              height={bh}
              fill={metric.color}
              opacity={0.55}
            />
          );
        })}
        {mean != null && (
          <line
            x1={((mean - 1) / 9) * w}
            x2={((mean - 1) / 9) * w}
            y1={2} y2={h}
            stroke={metric.color}
            strokeWidth={1.5}
            strokeDasharray="2 1"
          />
        )}
      </svg>
    </th>
  );
}

function Legend({ showNumbers }) {
  return (
    <div className="text-[10px] text-muted-foreground border-t border-border/40 pt-3 space-y-1" data-testid="lv-legend">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>Each column uses its metric's own hue — pale = low, saturated = high.</span>
        <span>The sparkline above each column shows the distribution across visible papers (dashed line = mean).</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>{showNumbers ? "Numbers shown." : "Numbers hidden — toggle the button above to reveal them."}</span>
        <span>Click any row to expand its full reasoning. Hover an extended-metric cell for a quick tooltip.</span>
      </div>
    </div>
  );
}
