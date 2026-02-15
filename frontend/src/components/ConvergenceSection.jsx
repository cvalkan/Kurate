import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { TrendingUp } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
const COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#22c55e", "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#6366f1"];
const TOPK_COLORS = { top_3: "#ef4444", top_5: "#f59e0b", top_10: "#3b82f6", top_20: "#8b5cf6" };
const METRICS = [
  { id: "spearman", label: "Spearman \u03C1" },
  { id: "kendall", label: "Kendall \u03C4" },
  { id: "pearson", label: "Pearson r" },
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

  const CONTENT_MODES = [
    { id: "abstract", label: "Abstract" },
    { id: "extract", label: "Extract" },
    { id: "full_pdf", label: "Full PDF" },
    { id: "abstract_plus_summary", label: "Abstract + Summary" },
  ];

  useEffect(() => {
    if (!datasets?.length) return;
    // For each dataset, fetch convergence for ALL content modes
    const fetches = [];
    datasets.forEach(ds => {
      CONTENT_MODES.forEach(mode => {
        fetches.push(
          axios.get(`${API}/api/validation/convergence`, {
            params: { dataset_id: ds.dataset_id, content_mode: mode.id, steps: 20 }
          }).then(r => ({ dsId: ds.dataset_id, dsName: ds.name, mode: mode.id, modeLabel: mode.label, data: r.data }))
            .catch(() => null)
        );
      });
    });
    Promise.all(fetches).then(results => {
      const c = {};
      for (const r of results) {
        if (!r || r.data.status !== "ok" || !r.data.curve?.length) continue;
        const key = datasets.length === 1 ? r.mode : `${r.dsId}__${r.mode}`;
        const label = datasets.length === 1 ? r.modeLabel : `${r.dsName} (${r.modeLabel})`;
        c[key] = { ...r.data, name: label };
      }
      setCurves(c);
      setLoading(false);
    });
  }, [datasets]);

  if (loading || !Object.keys(curves).length) return null;
  return <ConvergenceChart curves={curves} metric={metric} setMetric={setMetric} showTopK={showTopK} setShowTopK={setShowTopK} />;
}

/** Single-category convergence for leaderboard tournament. */
export function LeaderboardConvergence({ category }) {
  const [curve, setCurve] = useState(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("spearman");
  const [showTopK, setShowTopK] = useState(false);

  useEffect(() => {
    setLoading(true);
    const params = { steps: 20 };
    if (category) params.category = category;
    axios.get(`${API}/api/convergence`, { params }).then(r => {
      if (r.data.status === "ok") setCurve(r.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [category]);

  if (loading || !curve) return null;
  const label = category || "All Categories";
  return <ConvergenceChart curves={{ all: { ...curve, name: label } }} metric={metric} setMetric={setMetric} showTopK={showTopK} setShowTopK={setShowTopK} compact />;
}

/** Shared chart renderer. */
function ConvergenceChart({ curves, metric, setMetric, showTopK, setShowTopK, compact = false }) {
  const dsIds = Object.keys(curves);

  // Determine available top-k values
  const topKValues = curves[dsIds[0]]?.top_k_values || [];
  const hasTopK = topKValues.length > 0 && curves[dsIds[0]]?.curve?.[0]?.[`top_${topKValues[0]}`] !== undefined;

  // Build correlation chart data
  const allPoints = [];
  dsIds.forEach(did => { curves[did].curve.forEach(pt => { allPoints.push({ x: pt.avg_matches_per_paper, dataset: did, ...pt }); }); });
  const xValues = [...new Set(allPoints.map(p => p.x))].sort((a, b) => a - b);

  const corrChartData = xValues.map(x => {
    const row = { x };
    dsIds.forEach(did => {
      const pt = allPoints.find(p => p.x === x && p.dataset === did);
      if (pt) row[`${did}_${metric}`] = pt[metric];
    });
    return row;
  });

  // Build top-k chart data
  const topkChartData = hasTopK ? xValues.map(x => {
    const row = { x };
    dsIds.forEach(did => {
      const pt = allPoints.find(p => p.x === x && p.dataset === did);
      if (pt) topKValues.forEach(k => { if (pt[`top_${k}`] !== undefined) row[`${did}_top_${k}`] = pt[`top_${k}`]; });
    });
    return row;
  }) : [];

  const maxX = Math.max(...xValues, 1);
  // Nice x-axis ticks: 0, 5, 10, 15... or 0, 10, 20... depending on range
  const tickInterval = maxX > 60 ? 10 : maxX > 30 ? 5 : maxX > 15 ? 5 : 2;
  const xTicks = [];
  for (let t = 0; t <= maxX + tickInterval; t += tickInterval) xTicks.push(t);

  return (
    <div className="space-y-3" data-testid="convergence-section">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className={`${compact ? "text-sm" : "text-lg"} font-semibold flex items-center gap-2`}>
            <TrendingUp className="h-4 w-4" /> Ranking Convergence
          </h2>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            How many matches for stable rankings? Ground truth = human expert pairwise preferences.
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
                Top-K Overlap
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
        </div>
      </div>

      {/* Rank correlation chart */}
      {!showTopK && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-corr-chart">
          <ResponsiveContainer width="100%" height={compact ? 220 : 280}>
            <LineChart data={corrChartData}>
              <XAxis dataKey="x" type="number" domain={[0, "dataMax"]} ticks={xTicks} tick={{ fontSize: 10 }}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} tickFormatter={v => v.toFixed(1)}
                label={{ value: METRICS.find(m => m.id === metric)?.label, angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              {dsIds.length > 1 && <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />}
              {dsIds.length <= 1 && <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />}
              {dsIds.map((did, i) => (
                <Line key={did} type="monotone" dataKey={`${did}_${metric}`} name={curves[did].name}
                  stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Top-K overlap chart */}
      {showTopK && hasTopK && (
        <div className="border border-border rounded-lg p-3" data-testid="convergence-topk-chart">
          <ResponsiveContainer width="100%" height={compact ? 220 : 280}>
            <LineChart data={topkChartData}>
              <XAxis dataKey="x" type="number" domain={[0, "dataMax"]} ticks={xTicks} tick={{ fontSize: 10 }}
                label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`}
                label={{ value: "Top-K overlap with ground truth", angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              <ReferenceLine y={100} stroke="#22c55e" strokeDasharray="4 4" />
              {dsIds.length === 1 ? (
                // Single dataset: show each k as a separate line
                topKValues.map(k => (
                  <Line key={k} type="monotone" dataKey={`${dsIds[0]}_top_${k}`} name={`Top ${k}`}
                    stroke={TOPK_COLORS[`top_${k}`] || "#94a3b8"} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
                ))
              ) : (
                // Multi dataset: show top-5 (or first available) per dataset
                dsIds.map((did, i) => {
                  const k = topKValues.find(v => v === 5) || topKValues[0];
                  return (
                    <Line key={did} type="monotone" dataKey={`${did}_top_${k}`} name={`${curves[did].name} (top ${k})`}
                      stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
                  );
                })
              )}
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
              <div className="font-medium text-xs mb-0.5" style={{ color: COLORS[i % COLORS.length] }}>{c.name}</div>
              <div className="text-muted-foreground">
                {c.total_papers} papers, {c.total_matches} AI matches{c.human_matches ? `, ${c.human_matches} human pairs` : ""}
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
