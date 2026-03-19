import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { TrendingUp } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

// Stable color assignments: same mode always gets the same color across all charts
const MODE_COLORS = {
  "abstract":                          "#22c55e",  // green
  "extract":                           "#f59e0b",  // amber
  "full_pdf":                          "#ef4444",  // red
  "ai_summary":                        "#06b6d4",  // cyan
  "abstract_plus_summary":             "#3b82f6",  // blue
  "abstract_plus_summary:opus46":      "#8b5cf6",  // purple
  "abstract_plus_summary:opus_thinking":"#a855f7",  // violet
  "abstract_plus_summary:gpt_thinking": "#ec4899",  // pink
  "abstract_plus_summary:gpt_summary":  "#f97316",  // orange
  "abstract_plus_summary:gemini_summary":"#14b8a6",  // teal
  "abstract_plus_summary:gemini_thinking":"#84cc16", // lime
};
const FALLBACK_COLORS = ["#6366f1", "#d946ef", "#0ea5e9", "#a3e635", "#fb923c", "#38bdf8"];
function getModeColor(modeId, fallbackIdx = 0) {
  return MODE_COLORS[modeId] || FALLBACK_COLORS[fallbackIdx % FALLBACK_COLORS.length];
}

const TOPK_COLORS = { top_3: "#ef4444", top_5: "#f59e0b", top_10: "#3b82f6", top_20: "#8b5cf6" };
const METRICS = [
  { id: "spearman", label: "Spearman \u03C1" },
  { id: "kendall", label: "Kendall \u03C4" },
  { id: "pearson", label: "Pearson r" },
];
const CONTENT_MODES = [
  { id: "abstract", label: "Abstract" },
  { id: "extract", label: "Abstract + Extract" },
  { id: "full_pdf", label: "Full PDF" },
  { id: "abstract_plus_summary", label: "Abstract + Summary" },
];

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
      <div className="font-medium mb-1">{label} matches/paper</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.stroke }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono font-medium">{typeof p.value === "number" ? (p.value > 1 ? `${p.value}%` : p.value.toFixed(3)) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

/** Multi-dataset convergence for validation tournaments. */
export function ValidationConvergence({ datasets }) {
  const [curves, setCurves] = useState({});
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("spearman");
  const [showTopK, setShowTopK] = useState(false);
  const [logScale, setLogScale] = useState(false);

  const dsKey = datasets?.map(d => d.dataset_id).join(",") || "";
  useEffect(() => {
    if (!datasets?.length) return;
    let cancelled = false;
    setLoading(true);
    // Single batch call per dataset — returns all modes at once
    Promise.all(
      datasets.map(ds =>
        axios.get(`${API}/api/validation/convergence-all`, { params: { dataset_id: ds.dataset_id } })
          .then(r => ({ dsId: ds.dataset_id, dsName: ds.name, data: r.data }))
          .catch(() => null)
      )
    ).then(results => {
      if (cancelled) return;
      const c = {};
      for (const r of results) {
        if (!r || r.data?.status !== "ok" || !r.data.modes) continue;
        for (const [modeId, modeData] of Object.entries(r.data.modes)) {
          if (!modeData.curve?.length) continue;
          const key = datasets.length === 1 ? modeId : `${r.dsId}__${modeId}`;
          const label = datasets.length === 1 ? modeData.name : `${r.dsName} (${modeData.name})`;
          c[key] = { ...modeData, name: label };
        }
      }
      setCurves(c);
      setLoading(false);
    }).catch(err => {
      if (cancelled) return;
      console.error("Convergence fetch error:", err);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [dsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="h-64 bg-secondary/20 rounded-lg animate-pulse" />;
  if (!Object.keys(curves).length) return (
    <div className="text-center py-12 text-muted-foreground">
      <TrendingUp className="h-8 w-8 mx-auto mb-2 opacity-30" />
      <p className="text-sm">No convergence data available yet.</p>
      <p className="text-xs mt-1">Run more tournament matches to generate convergence curves.</p>
    </div>
  );
  return <ConvergenceChart curves={curves} metric={metric} setMetric={setMetric} showTopK={showTopK} setShowTopK={setShowTopK} logScale={logScale} setLogScale={setLogScale} />;
}

/** Single-category convergence for leaderboard tournament. */
export function LeaderboardConvergence({ category }) {
  const [curve, setCurve] = useState(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("spearman");
  const [showTopK, setShowTopK] = useState(false);
  const [logScale, setLogScale] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const params = { steps: 20 };
    if (category) params.category = category;
    axios.get(`${API}/api/convergence`, { params }).then(r => {
      if (!cancelled && r.data.status === "ok") setCurve(r.data);
      if (!cancelled) setLoading(false);
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [category]);

  if (!curve) return loading ? <div className="h-64 bg-secondary/20 rounded-lg animate-pulse" /> : null;
  const label = category || "All Categories";
  return <ConvergenceChart curves={{ all: { ...curve, name: label } }} metric={metric} setMetric={setMetric} showTopK={showTopK} setShowTopK={setShowTopK} logScale={logScale} setLogScale={setLogScale} compact isLeaderboard />;
}

/** Shared chart renderer. */
function ConvergenceChart({ curves, metric, setMetric, showTopK, setShowTopK, logScale = false, setLogScale, compact = false, isLeaderboard = false }) {
  const dsIds = Object.keys(curves);

  // Determine available top-k values
  const topKValues = curves[dsIds[0]]?.top_k_values || [];
  const hasTopK = topKValues.length > 0 && curves[dsIds[0]]?.curve?.[0]?.[`top_${topKValues[0]}`] !== undefined;

  // Build correlation chart data (O(n) using Map lookup instead of O(n²) .find())
  const pointMap = new Map();
  dsIds.forEach(did => {
    curves[did].curve.forEach(pt => {
      const x = pt.avg_matches_per_paper;
      if (!pointMap.has(x)) pointMap.set(x, {});
      pointMap.get(x)[did] = pt;
    });
  });
  const xValues = [...pointMap.keys()].sort((a, b) => a - b);

  const corrChartData = xValues.map(x => {
    const row = { x };
    const pts = pointMap.get(x);
    dsIds.forEach(did => {
      if (pts[did]) row[`${did}_${metric}`] = pts[did][metric];
    });
    return row;
  });

  // Build top-k chart data
  const topkChartData = hasTopK ? xValues.map(x => {
    const row = { x };
    const pts = pointMap.get(x);
    dsIds.forEach(did => {
      if (pts[did]) topKValues.forEach(k => { if (pts[did][`top_${k}`] !== undefined) row[`${did}_top_${k}`] = pts[did][`top_${k}`]; });
    });
    return row;
  }) : [];

  // Check if any dataset has tier data
  const hasTiers = dsIds.some(did => curves[did]?.has_tiers);
  // Check if any dataset has dual-dimension data (significance + strength)
  const hasDual = dsIds.some(did => curves[did]?.has_dual);

  // Build tier correlation chart data
  const TIER_METRICS = [
    { id: "tier_spearman", label: "Tier Spearman ρ" },
    { id: "tier_kendall", label: "Tier Kendall τ" },
  ];
  const tierChartData = hasTiers ? xValues.map(x => {
    const row = { x };
    const pts = pointMap.get(x);
    dsIds.forEach(did => {
      if (pts[did]?.tier_spearman !== undefined) row[`${did}_tier_spearman`] = pts[did].tier_spearman;
      if (pts[did]?.tier_kendall !== undefined) row[`${did}_tier_kendall`] = pts[did].tier_kendall;
    });
    return row;
  }) : [];

  // Build dual-dimension chart data (significance + strength)
  const dualChartData = hasDual ? xValues.map(x => {
    const row = { x };
    const pts = pointMap.get(x);
    dsIds.forEach(did => {
      if (pts[did]?.sig_spearman !== undefined) row[`${did}_sig`] = pts[did].sig_spearman;
      if (pts[did]?.str_spearman !== undefined) row[`${did}_str`] = pts[did].str_spearman;
    });
    return row;
  }) : [];

  const maxX = Math.max(...xValues, 1);
  // Nice x-axis ticks
  const tickInterval = maxX > 60 ? 10 : maxX > 30 ? 5 : maxX > 15 ? 5 : 2;
  const linearTicks = [];
  for (let t = 0; t <= maxX + tickInterval; t += tickInterval) linearTicks.push(t);

  // Log scale: transform data and build log ticks
  const logCorrData = logScale ? corrChartData.map(row => ({ ...row, x: row.x > 0 ? Math.log10(row.x) : -0.3 })) : corrChartData;
  const logTopkData = logScale ? topkChartData.map(row => ({ ...row, x: row.x > 0 ? Math.log10(row.x) : -0.3 })) : topkChartData;
  const logTierData = logScale && tierChartData.length ? tierChartData.map(row => ({ ...row, x: row.x > 0 ? Math.log10(row.x) : -0.3 })) : tierChartData;
  const logDualData = logScale && dualChartData.length ? dualChartData.map(row => ({ ...row, x: row.x > 0 ? Math.log10(row.x) : -0.3 })) : dualChartData;

  // Log ticks: 1, 2, 5, 10, 20, 50, 100, 200...
  const logTickValues = [1, 2, 5, 10, 20, 50, 100, 200, 500].filter(v => v <= maxX * 1.1);
  const logTicks = logTickValues.map(v => Math.log10(v));
  const xTicks = logScale ? logTicks : linearTicks;
  const xDomain = logScale ? [0, Math.log10(maxX) * 1.05] : [0, "dataMax"];
  const xTickFmt = logScale ? (v => { const raw = Math.round(Math.pow(10, v)); return raw >= 1 ? raw : ""; }) : undefined;

  return (
    <div className="space-y-3" data-testid="convergence-section">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className={`${compact ? "text-sm" : "text-lg"} font-semibold flex items-center gap-2`}>
            <TrendingUp className="h-4 w-4" /> Ranking Convergence
          </h2>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            {isLeaderboard
              ? "How many matches for stable rankings? Convergence measured against final ranking at all matches."
              : "How many matches for stable rankings? Ground truth = human BT ranking from reviewer scores. For multi-dimension datasets (e.g., eLife), the aggregate is the average of per-dimension Spearman correlations (significance + strength)."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {hasTopK && (
            <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="convergence-view-toggle">
              <button onClick={() => setShowTopK(false)}
                className={`px-2 py-1 text-[11px] font-medium rounded transition-colors ${!showTopK ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
                Rank Correlation
              </button>
              <button onClick={() => setShowTopK(true)}
                className={`px-2 py-1 text-[11px] font-medium rounded transition-colors ${showTopK ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
                Top-{topKValues[0] || "K"} Overlap
              </button>
            </div>
          )}
          {!showTopK && (
            <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="convergence-metric-toggle">
              {METRICS.map(m => (
                <button key={m.id} onClick={() => setMetric(m.id)}
                  className={`px-2 py-1 text-[11px] font-medium rounded transition-colors ${metric === m.id ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}
                  data-testid={`convergence-metric-${m.id}`}>{m.label}</button>
              ))}
            </div>
          )}
          {setLogScale && (
            <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="convergence-scale-toggle">
              <button onClick={() => setLogScale(false)}
                className={`px-2 py-1 text-[11px] font-medium rounded transition-colors ${!logScale ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
                Linear
              </button>
              <button onClick={() => setLogScale(true)}
                className={`px-2 py-1 text-[11px] font-medium rounded transition-colors ${logScale ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
                Log
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Rank correlation chart */}
      {!showTopK && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-corr-chart">
          <ResponsiveContainer width="100%" height={compact ? 220 : 280}>
            <LineChart data={logCorrData}>
              <XAxis dataKey="x" type="number" domain={xDomain} ticks={xTicks} tick={{ fontSize: 10 }}
                tickFormatter={xTickFmt}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} tickFormatter={v => v.toFixed(1)}
                label={{ value: METRICS.find(m => m.id === metric)?.label, angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              {dsIds.length > 1 && <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />}
              {dsIds.length <= 1 && <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />}
              {isLeaderboard && metric === "spearman" && (
                <ReferenceLine y={0.95} stroke="#22c55e" strokeDasharray="4 4" label={{ value: "ρ = 0.95", position: "right", fontSize: 9, fill: "#22c55e" }} />
              )}
              {dsIds.map((did, i) => (
                <Line key={did} type="monotone" dataKey={`${did}_${metric}`} name={curves[did].name}
                  stroke={getModeColor(did, i)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Tier convergence chart — shown below rank correlation when tiers available */}
      {!showTopK && hasTiers && !isLeaderboard && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-tier-chart">
          <div className="mb-2">
            <h3 className="text-sm font-semibold">Tier Ranking Convergence</h3>
            <p className="text-[10px] text-muted-foreground">AI ranking correlation with ICLR acceptance tiers (Oral &gt; Spotlight &gt; Poster &gt; Reject)</p>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={logTierData}>
              <XAxis dataKey="x" type="number" domain={xDomain} ticks={xTicks} tick={{ fontSize: 10 }}
                tickFormatter={xTickFmt}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} tickFormatter={v => v.toFixed(1)}
                label={{ value: "Tier Spearman ρ", angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              {dsIds.map((did, i) => (
                <Line key={did} type="monotone" dataKey={`${did}_tier_spearman`} name={curves[did].name}
                  stroke={getModeColor(did, i)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Significance convergence */}
      {!showTopK && hasDual && !isLeaderboard && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-sig-chart">
          <div className="mb-2">
            <h3 className="text-sm font-semibold">Significance Ranking Convergence</h3>
            <p className="text-[10px] text-muted-foreground">AI BT ranking vs human BT ranking from significance preferences (useful → landmark)</p>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={logDualData}>
              <XAxis dataKey="x" type="number" domain={xDomain} ticks={xTicks} tick={{ fontSize: 10 }}
                tickFormatter={xTickFmt}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} tickFormatter={v => v.toFixed(1)}
                label={{ value: "Spearman ρ", angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              {dsIds.map((did, i) => (
                <Line key={`${did}_sig`} type="monotone" dataKey={`${did}_sig`}
                  name={curves[did].name}
                  stroke={getModeColor(did, i)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Strength convergence */}
      {!showTopK && hasDual && !isLeaderboard && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-str-chart">
          <div className="mb-2">
            <h3 className="text-sm font-semibold">Strength of Evidence Ranking Convergence</h3>
            <p className="text-[10px] text-muted-foreground">AI BT ranking vs human BT ranking from strength preferences (inadequate → exceptional)</p>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={logDualData}>
              <XAxis dataKey="x" type="number" domain={xDomain} ticks={xTicks} tick={{ fontSize: 10 }}
                tickFormatter={xTickFmt}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} tickFormatter={v => v.toFixed(1)}
                label={{ value: "Spearman ρ", angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              {dsIds.map((did, i) => (
                <Line key={`${did}_str`} type="monotone" dataKey={`${did}_str`}
                  name={curves[did].name}
                  stroke={getModeColor(did, i)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {showTopK && hasTopK && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-topk-chart">
          <ResponsiveContainer width="100%" height={compact ? 220 : 280}>
            <LineChart data={logTopkData}>
              <XAxis dataKey="x" type="number" domain={xDomain} ticks={xTicks} tick={{ fontSize: 10 }}
                tickFormatter={xTickFmt}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`}
                label={{ value: `Top-${topKValues[0]} overlap with ground truth`, angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              {dsIds.length > 1 && <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />}
              <ReferenceLine y={100} stroke="#22c55e" strokeDasharray="4 4" />
              {dsIds.map((did, i) => {
                const k = topKValues[0];
                return (
                  <Line key={did} type="monotone" dataKey={`${did}_top_${k}`}
                    name={dsIds.length > 1 ? `${curves[did].name}` : `Top ${k}`}
                    stroke={getModeColor(did, i)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Summary cards */}
      <div className={`grid gap-2 ${dsIds.length > 1 ? "grid-cols-1 md:grid-cols-3" : "grid-cols-1"}`}>
        {dsIds.map((did, i) => {
          const c = curves[did];
          const first95 = c.curve.find(pt => pt.spearman >= 0.95);
          const gc = c.graph_connectivity;
          return (
            <div key={did} className="border border-border rounded-lg p-2.5 text-[10px]" data-testid={`convergence-summary-${did}`}>
              <div className="font-medium text-xs mb-0.5" style={{ color: getModeColor(did, i) }}>{c.name}</div>
              <div className="text-muted-foreground">
                {c.total_papers} papers, {c.total_matches} AI matches{c.human_matches ? `, ${c.human_matches} human pairs` : ""}{c.human_evaluators ? `, ${c.human_evaluators} experts` : ""}
              </div>
              {gc && (
                <div className={`mt-0.5 ${gc.is_connected ? "text-green-600" : "text-amber-600"}`}>
                  {gc.is_connected
                    ? `Graph: fully connected (${gc.largest_component} papers)`
                    : `Graph: ${gc.components} disconnected components (largest: ${gc.largest_component})`
                  }
                </div>
              )}
              {first95 && <div className="font-medium text-foreground mt-0.5">Spearman &rho; &ge; 0.95 at ~{first95.avg_matches_per_paper} matches/paper</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ValidationConvergence;
