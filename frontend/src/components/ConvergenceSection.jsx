import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { TrendingUp } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
const COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#22c55e"];
const METRICS = [
  { id: "spearman", label: "Spearman \u03C1" },
  { id: "kendall", label: "Kendall \u03C4" },
  { id: "pearson", label: "Pearson r" },
];

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
      <div className="font-medium mb-1">{label} avg matches/paper</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.stroke }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono font-medium">{p.value?.toFixed(3)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Multi-dataset convergence for validation tournaments.
 * Props: datasets = [{ dataset_id, name }]
 */
export function ValidationConvergence({ datasets }) {
  const [curves, setCurves] = useState({});
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("spearman");

  useEffect(() => {
    if (!datasets?.length) return;
    Promise.all(
      datasets.map(ds =>
        axios.get(`${API}/api/validation/convergence`, { params: { dataset_id: ds.dataset_id, content_mode: "extract", steps: 20 } }).catch(() => ({ data: {} }))
      )
    ).then(results => {
      const c = {};
      datasets.forEach((ds, i) => {
        if (results[i].data.status === "ok") c[ds.dataset_id] = { ...results[i].data, name: ds.name };
      });
      setCurves(c);
      setLoading(false);
    });
  }, [datasets]);

  if (loading || !Object.keys(curves).length) return null;
  return <ConvergenceChart curves={curves} metric={metric} setMetric={setMetric} />;
}

/**
 * Single-category convergence for the main (leaderboard) tournament.
 * Props: category = string | null
 */
export function LeaderboardConvergence({ category }) {
  const [curve, setCurve] = useState(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("spearman");

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

  const label = category ? curve.category : "All Categories";
  const curves = { all: { ...curve, name: label } };
  return <ConvergenceChart curves={curves} metric={metric} setMetric={setMetric} compact />;
}

/**
 * Shared chart renderer.
 */
function ConvergenceChart({ curves, metric, setMetric, compact = false }) {
  const dsIds = Object.keys(curves);

  // Build recharts data
  const allPoints = [];
  dsIds.forEach(did => {
    curves[did].curve.forEach(pt => {
      allPoints.push({ x: pt.avg_matches_per_paper, dataset: did, ...pt });
    });
  });

  const xValues = [...new Set(allPoints.map(p => p.x))].sort((a, b) => a - b);
  const chartData = xValues.map(x => {
    const row = { x };
    dsIds.forEach(did => {
      const pt = allPoints.find(p => p.x === x && p.dataset === did);
      if (pt) row[`${did}_${metric}`] = pt[metric];
    });
    return row;
  });

  return (
    <div className="space-y-3" data-testid="convergence-section">
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`${compact ? "text-sm" : "text-lg"} font-semibold flex items-center gap-2`}>
            <TrendingUp className="h-4 w-4" /> Ranking Convergence
          </h2>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            How many matches for stable rankings? Ground truth = final ranking with all matches.
          </p>
        </div>
        <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="convergence-metric-toggle">
          {METRICS.map(m => (
            <button key={m.id} onClick={() => setMetric(m.id)}
              className={`px-2 py-1 text-[11px] font-medium rounded transition-colors ${metric === m.id ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}
              data-testid={`convergence-metric-${m.id}`}>{m.label}</button>
          ))}
        </div>
      </div>

      <div className="border border-border rounded-lg p-3" data-testid="convergence-chart">
        <ResponsiveContainer width="100%" height={compact ? 220 : 280}>
          <LineChart data={chartData}>
            <XAxis dataKey="x" tick={{ fontSize: 10 }} label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 10 }} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} tickFormatter={v => v.toFixed(1)} label={{ value: METRICS.find(m => m.id === metric)?.label, angle: -90, position: "insideLeft", offset: 10, fontSize: 10 }} />
            <Tooltip content={<Tip />} />
            {dsIds.length > 1 && <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />}
            <ReferenceLine y={0.95} stroke="#22c55e" strokeDasharray="4 4" label={{ value: "0.95", position: "right", fontSize: 9, fill: "#22c55e" }} />
            {dsIds.map((did, i) => (
              <Line key={did} type="monotone" dataKey={`${did}_${metric}`} name={curves[did].name}
                stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Summary cards */}
      <div className={`grid gap-2 ${dsIds.length > 1 ? "grid-cols-1 md:grid-cols-3" : "grid-cols-1"}`}>
        {dsIds.map((did, i) => {
          const c = curves[did];
          const first95 = c.curve.find(pt => pt.spearman >= 0.95);
          return (
            <div key={did} className="border border-border rounded-lg p-2.5 text-[10px]" data-testid={`convergence-summary-${did}`}>
              <div className="font-medium text-xs mb-0.5" style={{ color: COLORS[i % COLORS.length] }}>{c.name}</div>
              <div className="text-muted-foreground">
                {c.total_papers} papers, {c.total_matches} matches &middot; {c.curve[c.curve.length - 1]?.avg_matches_per_paper} avg/paper
              </div>
              {first95 && <div className="font-medium text-foreground mt-0.5">Spearman &rho; &ge; 0.95 at ~{first95.avg_matches_per_paper} matches/paper</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ValidationConvergence;
