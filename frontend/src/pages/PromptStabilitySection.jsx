import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, Legend,
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const EXP_COLORS = { exp1: "#3b82f6", exp2: "#f59e0b", exp3: "#10b981" };
const EXP_LABELS = { exp1: "Baseline (same prompt)", exp2: "+ Per-dim reasons", exp3: "+ Extended dimensions" };
const DIM_LABELS = { score: "Score", significance: "Significance", rigor: "Rigor", novelty: "Novelty", clarity: "Clarity" };

function PromptStabilitySection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/prompt-stability-results`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const shiftData = useMemo(() => {
    if (!data) return [];
    const dims = ["score", "significance", "rigor", "novelty", "clarity"];
    return dims.map(dim => {
      const entry = { dimension: DIM_LABELS[dim] || dim };
      for (const [exp, expData] of Object.entries(data)) {
        const d = expData.dimensions?.find(x => x.name === dim);
        if (d) entry[exp] = d.shift;
      }
      return entry;
    });
  }, [data]);

  const corrData = useMemo(() => {
    if (!data) return [];
    const dims = ["score", "significance", "rigor", "novelty", "clarity"];
    return dims.map(dim => {
      const entry = { dimension: DIM_LABELS[dim] || dim };
      for (const [exp, expData] of Object.entries(data)) {
        const d = expData.dimensions?.find(x => x.name === dim);
        if (d) entry[exp] = d.corr;
      }
      return entry;
    });
  }, [data]);

  const maeData = useMemo(() => {
    if (!data) return [];
    const dims = ["score", "significance", "rigor", "novelty", "clarity"];
    return dims.map(dim => {
      const entry = { dimension: DIM_LABELS[dim] || dim };
      for (const [exp, expData] of Object.entries(data)) {
        const d = expData.dimensions?.find(x => x.name === dim);
        if (d) entry[exp] = d.mae;
      }
      return entry;
    });
  }, [data]);

  if (loading) return <div className="text-sm text-muted-foreground py-8 text-center">Loading experiment results...</div>;
  if (!data || Object.keys(data).length === 0) return <div className="text-sm text-muted-foreground py-8 text-center">No experiment data available yet.</div>;

  const n = data.exp1?.n || 0;

  return (
    <div className="space-y-6" data-testid="prompt-stability">
      <div>
        <h2 className="text-lg font-semibold mb-1">Prompt Stability Experiment</h2>
        <p className="text-sm text-muted-foreground">
          Testing how stable Claude Opus 4.6's ratings are across prompt variants. Same {n} randomly sampled papers,
          same model, three prompt configurations. Comparing re-generated ratings against the original production summaries.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {Object.entries(data).map(([exp, expData]) => (
          <div key={exp} className="border border-border rounded-lg p-4 bg-card" data-testid={`summary-${exp}`}>
            <div className="flex items-center gap-2 mb-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: EXP_COLORS[exp] }} />
              <span className="text-sm font-medium">{EXP_LABELS[exp]}</span>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="text-xl font-semibold font-mono">{expData.overall?.corr}</div>
                <div className="text-[10px] text-muted-foreground">Correlation</div>
              </div>
              <div>
                <div className={`text-xl font-semibold font-mono ${expData.overall?.shift >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                  {expData.overall?.shift >= 0 ? "+" : ""}{expData.overall?.shift}
                </div>
                <div className="text-[10px] text-muted-foreground">Mean shift</div>
              </div>
              <div>
                <div className="text-xl font-semibold font-mono">{expData.overall?.mae}</div>
                <div className="text-[10px] text-muted-foreground">MAE</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Mean shift by dimension */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-medium mb-1">Mean Score Shift by Dimension</h3>
        <p className="text-xs text-muted-foreground mb-3">
          How much each dimension's average shifts relative to the original ratings. Zero = no change.
        </p>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={shiftData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis dataKey="dimension" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={[-0.5, 0.5]} tickFormatter={v => v >= 0 ? `+${v}` : v} />
            <RechartsTooltip contentStyle={{ background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: "8px", fontSize: "12px" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {Object.entries(EXP_COLORS).map(([exp, color]) => (
              data[exp] ? <Bar key={exp} dataKey={exp} fill={color} name={EXP_LABELS[exp]} radius={[3, 3, 0, 0]} /> : null
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Correlation by dimension */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-medium mb-1">Pearson Correlation by Dimension</h3>
        <p className="text-xs text-muted-foreground mb-3">
          How well the ranking order is preserved. 1.0 = perfect agreement, lower = more shuffling.
        </p>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={corrData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis dataKey="dimension" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={[0.9, 1.0]} />
            <RechartsTooltip contentStyle={{ background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: "8px", fontSize: "12px" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {Object.entries(EXP_COLORS).map(([exp, color]) => (
              data[exp] ? <Bar key={exp} dataKey={exp} fill={color} name={EXP_LABELS[exp]} radius={[3, 3, 0, 0]} /> : null
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* MAE by dimension */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-medium mb-1">Mean Absolute Error by Dimension</h3>
        <p className="text-xs text-muted-foreground mb-3">
          Average absolute difference between original and re-generated ratings. Lower = more stable.
        </p>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={maeData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis dataKey="dimension" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={[0, 0.6]} />
            <RechartsTooltip contentStyle={{ background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: "8px", fontSize: "12px" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {Object.entries(EXP_COLORS).map(([exp, color]) => (
              data[exp] ? <Bar key={exp} dataKey={exp} fill={color} name={EXP_LABELS[exp]} radius={[3, 3, 0, 0]} /> : null
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Methodology note */}
      <div className="text-xs text-muted-foreground border-t border-border pt-3">
        <p>
          <b>Methodology:</b> {n} papers randomly sampled from all active categories (minimum 10 pairwise comparisons).
          Each paper re-assessed by Claude Opus 4.6 using full paper text (same as production).
          Original ratings from the production summary pipeline serve as ground truth.
          Experiment 1 re-runs the exact production prompt. Experiment 2 adds one-sentence justifications per dimension.
          Experiment 3 adds 4 new dimensions (difficulty, surprisingness, reproducibility, translational potential)
          with null support and per-dimension reasoning. See the Extended Dimensions page for detailed results on the new metrics.
        </p>
      </div>
    </div>
  );
}

export default PromptStabilitySection;
