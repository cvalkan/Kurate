import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { TrendingUp, AlertCircle } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const MODE_LABELS = { abstract: "Abstract", extract: "Extract", full_pdf: "Full PDF", ai_summary: "AI Summary", abstract_plus_summary: "Abstract + Summary" };
const DATASET_COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#22c55e"];

function CustomTooltip({ active, payload, label }) {
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

export default function ConvergenceSection({ datasets }) {
  const [curves, setCurves] = useState({});
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("spearman");

  const fetchAll = useCallback(async () => {
    if (!datasets?.length) return;
    try {
      const results = await Promise.all(
        datasets.map(ds =>
          axios.get(`${API}/api/validation/convergence`, {
            params: { dataset_id: ds.dataset_id, content_mode: "extract", steps: 20 },
          }).catch(() => ({ data: {} }))
        )
      );
      const newCurves = {};
      datasets.forEach((ds, i) => {
        if (results[i].data.status === "ok") {
          newCurves[ds.dataset_id] = { ...results[i].data, name: ds.name };
        }
      });
      setCurves(newCurves);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [datasets]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  if (loading) return <div className="text-xs text-muted-foreground py-4 text-center">Loading convergence data...</div>;
  if (!Object.keys(curves).length) return null;

  // Merge all curves into a unified chart dataset
  // Each dataset has different x-values, so we need to align them
  const dsIds = Object.keys(curves);

  // Build chart data: one entry per unique avg_matches_per_paper across all datasets
  const allPoints = [];
  dsIds.forEach((did, di) => {
    const c = curves[did];
    c.curve.forEach(pt => {
      allPoints.push({
        x: pt.avg_matches_per_paper,
        dataset: did,
        name: c.name,
        spearman: pt.spearman,
        kendall: pt.kendall,
        pearson: pt.pearson,
        matches: pt.matches,
        papers: pt.papers_covered,
      });
    });
  });

  // For recharts, we need rows keyed by x with columns per dataset
  const xValues = [...new Set(allPoints.map(p => p.x))].sort((a, b) => a - b);
  const chartData = xValues.map(x => {
    const row = { x };
    dsIds.forEach(did => {
      const pt = allPoints.find(p => p.x === x && p.dataset === did);
      if (pt) {
        row[`${did}_${metric}`] = pt[metric];
      }
    });
    return row;
  });

  const METRICS = [
    { id: "spearman", label: "Spearman \u03C1" },
    { id: "kendall", label: "Kendall \u03C4" },
    { id: "pearson", label: "Pearson r" },
  ];

  return (
    <div className="space-y-4" data-testid="convergence-section">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <TrendingUp className="h-4 w-4" /> Ranking Convergence
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            How many pairwise matches are needed for stable rankings? Ground truth = final ranking using all available matches.
          </p>
        </div>
        <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="convergence-metric-toggle">
          {METRICS.map(m => (
            <button
              key={m.id}
              onClick={() => setMetric(m.id)}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                metric === m.id ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"
              }`}
              data-testid={`convergence-metric-${m.id}`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="border border-border rounded-lg p-4" data-testid="convergence-chart">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <XAxis
              dataKey="x"
              tick={{ fontSize: 11 }}
              label={{ value: "Avg matches per paper", position: "insideBottom", offset: -5, fontSize: 11 }}
            />
            <YAxis
              domain={[0, 1]}
              tick={{ fontSize: 10 }}
              tickFormatter={v => v.toFixed(1)}
              label={{ value: METRICS.find(m => m.id === metric)?.label, angle: -90, position: "insideLeft", offset: 10, fontSize: 11 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
            <ReferenceLine y={0.95} stroke="#22c55e" strokeDasharray="4 4" label={{ value: "0.95", position: "right", fontSize: 10, fill: "#22c55e" }} />
            {dsIds.map((did, i) => (
              <Line
                key={did}
                type="monotone"
                dataKey={`${did}_${metric}`}
                name={curves[did].name}
                stroke={DATASET_COLORS[i % DATASET_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Summary stats per dataset */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {dsIds.map((did, i) => {
          const c = curves[did];
          const first95 = c.curve.find(pt => pt.spearman >= 0.95);
          return (
            <div key={did} className="border border-border rounded-lg p-3" data-testid={`convergence-summary-${did}`}>
              <div className="text-xs font-medium mb-1" style={{ color: DATASET_COLORS[i % DATASET_COLORS.length] }}>
                {c.name}
              </div>
              <div className="text-[10px] text-muted-foreground space-y-0.5">
                <div>{c.total_papers} papers, {c.total_matches} total matches</div>
                <div>Final: {c.curve[c.curve.length - 1]?.avg_matches_per_paper} avg matches/paper</div>
                {first95 && (
                  <div className="font-medium text-foreground">
                    Spearman \u03C1 {"\u2265"} 0.95 at ~{first95.avg_matches_per_paper} matches/paper
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="text-[10px] text-muted-foreground bg-secondary/10 border border-border/50 rounded px-3 py-2">
        Matches are added chronologically. At each point, a Bradley-Terry ranking is computed and correlated with the final (all-data) ranking. The 0.95 threshold (dashed green line) indicates when the ranking is effectively stable.
      </div>
    </div>
  );
}
