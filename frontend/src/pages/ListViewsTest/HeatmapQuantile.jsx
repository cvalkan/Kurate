import { useMemo, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown, X, Pin } from "lucide-react";
import {
  METRICS, useExtendedPapers, useListState, applyFilters, applySort,
  FilterBar, ListViewShell,
  viridisColor, viridisTextColor, computePercentileMap, computeMiniHistogram,
} from "./_shared";

/**
 * F — Quantile Heatmap (column-local color scale)
 * Improvements over D:
 *  - Each cell colored by its rank within its own column (percentile), not absolute value
 *    → outliers within each metric pop, even though most papers cluster 5-8
 *  - Viridis palette (perceptually uniform, colorblind safe)
 *  - Hover a column → other columns dim, plus a tiny histogram + median marker visible above
 *  - Click any cell → pinned side panel locks open with paper details + all reasonings
 *  - Tight, compact cells: more papers visible at once
 */
export default function HeatmapQuantile() {
  const { papers, loading, n } = useExtendedPapers();
  const [state, setState] = useListState("heatmap-quantile", { sortKey: "score", sortDir: "desc" });
  const [hoverCol, setHoverCol] = useState(null);
  const [pinned, setPinned] = useState(null); // { paper_id, metricKey }

  const visible = useMemo(() => applySort(applyFilters(papers, state), state), [papers, state]);
  const visibleMetrics = METRICS.filter(m => !state.hidden.has(m.key));

  // Compute percentile maps over the *visible* set so filters/sorts feel responsive.
  const pctMaps = useMemo(() => {
    const out = {};
    visibleMetrics.forEach(m => { out[m.key] = computePercentileMap(visible, m.key); });
    return out;
  }, [visible, visibleMetrics]);

  const histograms = useMemo(() => {
    const h = {};
    visibleMetrics.forEach(m => { h[m.key] = computeMiniHistogram(visible, m.key, 10); });
    return h;
  }, [visible, visibleMetrics]);

  const setSort = (key) => setState(prev => ({
    ...prev,
    sortKey: key,
    sortDir: prev.sortKey === key ? (prev.sortDir === "asc" ? "desc" : "asc") : "desc",
  }));

  const pinnedPaper = pinned ? visible.find(p => p.paper_id === pinned.paper_id) : null;

  return (
    <TooltipProvider delayDuration={120}>
      <ListViewShell
        title="F — Quantile Heatmap"
        subtitle="Each cell is colored by its rank within its own column — not by absolute value. Bright yellow = top of that metric, deep purple = bottom. Outliers pop even though most papers cluster 5-8. Click any cell to pin a detail panel."
      >
        <FilterBar state={state} setState={setState} papers={papers} showColumnToggle={true} />

        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground" data-testid="lv-count">
            {loading ? "Loading…" : `${visible.length} of ${papers.length} papers (n=${n})`}
          </div>
          <div className="text-[10px] text-muted-foreground">
            Color = percentile <em>within column</em>. Hover a column to focus it. Click a cell to pin.
          </div>
        </div>

        <div className="grid gap-3" style={{ gridTemplateColumns: pinnedPaper ? "minmax(0,1fr) 320px" : "1fr" }}>
          {/* Heatmap */}
          <div className="border border-border rounded-lg overflow-auto bg-card max-h-[80vh]" data-testid="lv-heatmap-quantile">
            <table className="w-full text-xs border-separate border-spacing-0">
              <thead className="sticky top-0 z-20 bg-card">
                {/* Mini histograms */}
                <tr>
                  <th className="sticky left-0 z-30 bg-card" />
                  <th className="bg-card" />
                  {visibleMetrics.map(m => (
                    <ColumnHistogram
                      key={m.key}
                      metric={m}
                      hist={histograms[m.key]}
                      dim={hoverCol != null && hoverCol !== m.key}
                    />
                  ))}
                </tr>
                {/* Sortable headers */}
                <tr className="bg-secondary/80 backdrop-blur">
                  <th className="sticky left-0 z-30 bg-secondary/80 backdrop-blur w-3" />
                  <ColHeader sortKey="title" state={state} onSort={setSort}
                    className="text-left pl-1 min-w-[240px] sticky left-3 z-20 bg-secondary/80 backdrop-blur">
                    Paper
                  </ColHeader>
                  {visibleMetrics.map(m => {
                    const dim = hoverCol != null && hoverCol !== m.key;
                    return (
                      <th key={m.key}
                        className="py-1.5 px-1 text-center border-b border-border"
                        style={{ minWidth: 50, opacity: dim ? 0.35 : 1, transition: "opacity 0.12s" }}
                        onMouseEnter={() => setHoverCol(m.key)}
                        onMouseLeave={() => setHoverCol(null)}
                      >
                        <button
                          onClick={() => setSort(m.key)}
                          className={`flex flex-col items-center gap-0.5 w-full transition-colors ${state.sortKey === m.key ? "" : "text-muted-foreground hover:text-foreground"}`}
                          style={state.sortKey === m.key ? { color: m.color } : undefined}
                          data-testid={`lv-th-${m.key}`}
                          title={m.desc}
                        >
                          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: m.color }} />
                          <span className="text-[10px] font-medium">{m.short}</span>
                          {state.sortKey === m.key && (state.sortDir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {visible.map((p, i) => (
                  <tr key={p.paper_id} data-testid={`lv-row-${i}`}
                    className={pinned?.paper_id === p.paper_id ? "ring-1 ring-accent" : ""}
                  >
                    <td className={`sticky left-0 z-10 ${i % 2 === 0 ? "bg-background" : "bg-secondary/10"} w-3 border-b border-border/30`} />
                    <td
                      className={`pl-1 pr-2 py-1 border-b border-border/30 sticky left-3 z-10 ${i % 2 === 0 ? "bg-background" : "bg-secondary/10"} ${pinned?.paper_id === p.paper_id ? "bg-accent/10" : ""}`}
                      style={{ maxWidth: 240 }}
                    >
                      <button
                        onClick={() => setPinned({ paper_id: p.paper_id, metricKey: "score" })}
                        className="text-left w-full hover:text-accent transition-colors"
                      >
                        <div className="text-[11px] font-medium leading-snug line-clamp-2" title={p.title}>{p.title}</div>
                        <div className="text-[9px] font-mono text-muted-foreground mt-0.5">{p.category}</div>
                      </button>
                    </td>
                    {visibleMetrics.map(m => {
                      const v = p[m.key];
                      const pct = pctMaps[m.key]?.get(p.paper_id);
                      const dim = hoverCol != null && hoverCol !== m.key;
                      const pinnedHere = pinned?.paper_id === p.paper_id && pinned?.metricKey === m.key;
                      return (
                        <td
                          key={m.key}
                          className="p-0 border-b border-border/30"
                          data-testid={`cell-${i}-${m.key}`}
                          onMouseEnter={() => setHoverCol(m.key)}
                          onMouseLeave={() => setHoverCol(null)}
                        >
                          <button
                            onClick={() => setPinned({ paper_id: p.paper_id, metricKey: m.key })}
                            className="w-full h-6 flex items-center justify-center font-mono text-[10px] tabular-nums cursor-pointer border-r border-border/20 transition-opacity"
                            style={{
                              backgroundColor: v != null ? viridisColor(pct ?? 0) : "transparent",
                              color: v != null ? viridisTextColor(pct ?? 0) : "var(--muted-foreground)",
                              opacity: dim ? 0.32 : 1,
                              outline: pinnedHere ? "2px solid hsl(var(--accent))" : "none",
                              outlineOffset: pinnedHere ? "-2px" : 0,
                            }}
                            title={v != null ? `${m.label}: ${v.toFixed(1)} (P${Math.round((pct ?? 0) * 100)})` : `${m.label}: N/A`}
                          >
                            {hoverCol === m.key && v != null ? v.toFixed(1) : v == null ? "·" : ""}
                          </button>
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

          {/* Pinned detail panel */}
          {pinnedPaper && (
            <PinnedPanel
              paper={pinnedPaper}
              metricKey={pinned.metricKey}
              pctMaps={pctMaps}
              onClose={() => setPinned(null)}
            />
          )}
        </div>

        <ColorRamp />
      </ListViewShell>
    </TooltipProvider>
  );
}

function PinnedPanel({ paper, metricKey, pctMaps, onClose }) {
  const focusMetric = METRICS.find(m => m.key === metricKey);
  return (
    <aside className="border border-accent/40 rounded-lg p-4 bg-card sticky top-4 self-start max-h-[80vh] overflow-auto" data-testid="lv-pinned-panel">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 text-[10px] text-accent uppercase tracking-wider font-medium">
          <Pin className="h-3 w-3" /> Pinned paper
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground" data-testid="lv-pin-close">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <h3 className="text-sm font-semibold leading-snug">{paper.title}</h3>
      <div className="text-[10px] font-mono text-muted-foreground mt-1">{paper.category}</div>

      {/* Focused metric callout */}
      {focusMetric && paper[focusMetric.key] != null && (
        <div className="mt-3 border-l-2 pl-3" style={{ borderColor: focusMetric.color }}>
          <div className="text-[10px] uppercase tracking-wider" style={{ color: focusMetric.color }}>
            {focusMetric.label}
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums">{paper[focusMetric.key].toFixed(1)}</span>
            <span className="text-[10px] text-muted-foreground">
              P{Math.round((pctMaps[focusMetric.key]?.get(paper.paper_id) ?? 0) * 100)} (column-local rank)
            </span>
          </div>
          {focusMetric.reason && paper[`${focusMetric.key}_reason`] && (
            <p className="text-[11px] text-muted-foreground leading-snug mt-1.5">{paper[`${focusMetric.key}_reason`]}</p>
          )}
          {!focusMetric.reason && (
            <p className="text-[11px] text-muted-foreground italic leading-snug mt-1.5">{focusMetric.desc}</p>
          )}
        </div>
      )}

      {/* All metrics summary */}
      <div className="mt-4 pt-3 border-t border-border space-y-1.5">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">All metrics</div>
        {METRICS.map(m => {
          const v = paper[m.key];
          const pct = pctMaps[m.key]?.get(paper.paper_id);
          if (v == null) {
            return (
              <div key={m.key} className="flex items-center gap-2 text-[10px] text-muted-foreground italic">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: m.color }} />
                <span className="w-20 truncate">{m.label}</span>
                <span>N/A</span>
              </div>
            );
          }
          return (
            <div key={m.key} className="flex items-center gap-2 text-[10px]">
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: m.color }} />
              <span className="w-20 truncate" title={m.label}>{m.label}</span>
              {/* Mini bar */}
              <div className="flex-1 h-2 bg-secondary/40 rounded overflow-hidden">
                <div
                  className="h-full"
                  style={{
                    width: `${(v / 10) * 100}%`,
                    backgroundColor: viridisColor(pct ?? 0),
                  }}
                />
              </div>
              <span className="font-mono tabular-nums w-8 text-right">{v.toFixed(1)}</span>
              <span className="font-mono tabular-nums w-8 text-right text-muted-foreground">P{Math.round((pct ?? 0) * 100)}</span>
            </div>
          );
        })}
      </div>

      {/* Extended reasonings */}
      <div className="mt-4 pt-3 border-t border-border space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Reasoning (extended dims)</div>
        {METRICS.filter(m => m.reason).map(m => {
          const r = paper[`${m.key}_reason`];
          const v = paper[m.key];
          if (!r) return null;
          return (
            <div key={m.key}>
              <div className="text-[10px] font-medium" style={{ color: m.color }}>
                {m.label} <span className="font-mono text-muted-foreground">· {v != null ? v.toFixed(1) : "—"}</span>
              </div>
              <p className="text-[11px] text-muted-foreground leading-snug">{r}</p>
            </div>
          );
        })}
      </div>
    </aside>
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

function ColumnHistogram({ metric, hist, dim }) {
  if (!hist || hist.n === 0) return <th className="p-0" style={{ minWidth: 50 }} />;
  const { counts, max, mean } = hist;
  const w = 50;
  const h = 22;
  const barW = w / counts.length;
  return (
    <th className="p-0 align-bottom" style={{ minWidth: 50, opacity: dim ? 0.25 : 1, transition: "opacity 0.12s" }}
      title={`Distribution of ${metric.label} (n=${hist.n}, mean=${mean?.toFixed(1)})`}
    >
      <svg width={w} height={h} className="block mx-auto">
        {counts.map((c, i) => {
          const bh = (c / max) * (h - 3);
          return (
            <rect
              key={i}
              x={i * barW}
              y={h - bh}
              width={Math.max(1, barW - 1)}
              height={bh}
              fill={metric.color}
              opacity={0.6}
            />
          );
        })}
        {mean != null && (
          <line
            x1={((mean - 1) / 9) * w}
            x2={((mean - 1) / 9) * w}
            y1={0} y2={h}
            stroke="hsl(var(--foreground))"
            strokeWidth={1}
            strokeDasharray="2 1"
            opacity={0.8}
          />
        )}
      </svg>
    </th>
  );
}

function ColorRamp() {
  const stops = [0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0];
  return (
    <div className="text-[10px] text-muted-foreground flex items-center gap-2 border-t border-border/40 pt-3" data-testid="lv-color-ramp">
      <span>Column-local percentile</span>
      <div className="flex border border-border/50 rounded overflow-hidden">
        {stops.map(s => (
          <div key={s} className="w-6 h-3.5 flex items-center justify-center font-mono"
            style={{ backgroundColor: viridisColor(s), color: viridisTextColor(s) }}
            title={`P${Math.round(s * 100)}`}
          >
            <span style={{ fontSize: 7 }}>{Math.round(s * 100)}</span>
          </div>
        ))}
      </div>
      <span>0 = bottom of column, 100 = top</span>
      <span className="mx-2">·</span>
      <span>Viridis palette (colorblind safe)</span>
    </div>
  );
}
