import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, Cell,
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const DIM_CONFIG = {
  difficulty: { color: "#8b5cf6", label: "Difficulty", desc: "Technical difficulty. 1 = accessible to undergrads, 5 = graduate-level, 10 = deep specialist expertise." },
  surprisingness: { color: "#ec4899", label: "Surprisingness", desc: "How unexpected are the results and conclusions. 1 = fully expected, 10 = overturns conventional assumptions." },
  reproducibility: { color: "#06b6d4", label: "Reproducibility", desc: "Could an independent researcher replicate the results from this paper alone? 1 = key details missing, 10 = fully specified with code/data." },
  translational_potential: { color: "#f97316", label: "Translational Potential", desc: "Proximity to real-world application. 1 = pure theory, 5 = clear applied potential, 10 = directly deployable." },
};

function ExtendedDimensionsSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/prompt-stability-results`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const ext = data?.exp3?.extended;
  const n = data?.exp3?.n || 0;

  // Build per-dimension histogram data from the raw results
  const [rawRecords, setRawRecords] = useState([]);
  useEffect(() => {
    // Load individual paper results for histograms
    const path = "/app/memory/prompt_stability_exp3_extended.jsonl";
    // We'll use the precomputed summary data instead
  }, []);

  const histograms = useMemo(() => {
    if (!ext) return {};
    const result = {};
    for (const dim of ext) {
      // Create bins from 1-10
      const bins = [];
      for (let i = 1; i <= 10; i++) {
        bins.push({ bin: `${i}`, lo: i - 0.5, hi: i + 0.5, count: 0 });
      }
      // We don't have individual values in the precomputed data, 
      // so approximate from mean/std/min/max using normal distribution
      const { mean, std, n: count, min, max } = dim;
      // Simple approximation: distribute n papers across bins based on normal PDF
      const total = count;
      let assigned = 0;
      for (const bin of bins) {
        const mid = parseInt(bin.bin);
        if (mid < min || mid > max) { bin.count = 0; continue; }
        const z = (mid - mean) / (std || 1);
        const pdf = Math.exp(-0.5 * z * z);
        bin.count = Math.round(pdf * total * 0.4);
        assigned += bin.count;
      }
      // Adjust to match total
      const diff = total - assigned;
      const peakIdx = bins.findIndex(b => parseInt(b.bin) === Math.round(mean));
      if (peakIdx >= 0) bins[peakIdx].count += diff;
      
      result[dim.name] = bins;
    }
    return result;
  }, [ext]);

  if (loading) return <div className="text-sm text-muted-foreground py-8 text-center">Loading...</div>;
  if (!ext || ext.length === 0) return <div className="text-sm text-muted-foreground py-8 text-center">No extended dimension data available. Run Experiment 3 first.</div>;

  return (
    <div className="space-y-6" data-testid="extended-dimensions">
      <div>
        <h2 className="text-lg font-semibold mb-1">Extended Rating Dimensions</h2>
        <p className="text-sm text-muted-foreground">
          Four new dimensions extracted alongside the core 5 ratings using an extended summarization prompt.
          Each dimension includes a one-sentence justification and supports null for non-applicable cases.
          Tested on {n} randomly sampled papers using Claude Opus 4.6 with full paper text.
        </p>
      </div>

      {/* Overview bar chart */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-medium mb-1">Mean Scores Across New Dimensions</h3>
        <p className="text-xs text-muted-foreground mb-3">Scale: 1.0-10.0. Error bars show ±1 standard deviation.</p>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart
            data={ext.map(d => ({
              name: DIM_CONFIG[d.name]?.label || d.name,
              mean: d.mean,
              std: d.std,
              color: DIM_CONFIG[d.name]?.color || "#666",
            }))}
            margin={{ top: 5, right: 10, bottom: 5, left: 10 }}
          >
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={[0, 10]} />
            <RechartsTooltip
              contentStyle={{ background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: "8px", fontSize: "12px" }}
              formatter={(value, name, props) => {
                const d = props.payload;
                return [`${d.mean.toFixed(2)} ± ${d.std.toFixed(2)}`, "Mean ± Std"];
              }}
            />
            <Bar dataKey="mean" radius={[3, 3, 0, 0]}>
              {ext.map((d, i) => <Cell key={i} fill={DIM_CONFIG[d.name]?.color || "#666"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Individual dimension cards with histograms */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {ext.map(dim => {
          const cfg = DIM_CONFIG[dim.name] || { color: "#666", label: dim.name, desc: "" };
          const bins = histograms[dim.name] || [];
          return (
            <div key={dim.name} className="border border-border rounded-lg p-4 bg-card" data-testid={`dim-${dim.name}`}>
              <div className="flex items-center gap-2 mb-1">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: cfg.color }} />
                <h3 className="text-sm font-medium">{cfg.label}</h3>
                {dim.nulls > 0 && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{dim.nulls} N/A</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mb-3">{cfg.desc}</p>

              {/* Stats row */}
              <div className="flex gap-4 text-xs mb-3">
                <span>Mean: <b className="font-mono">{dim.mean.toFixed(2)}</b></span>
                <span>Std: <b className="font-mono">{dim.std.toFixed(2)}</b></span>
                <span>Range: <b className="font-mono">[{dim.min}, {dim.max}]</b></span>
                <span>n={dim.n}</span>
              </div>

              {/* Distribution chart */}
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={bins} margin={{ top: 0, right: 5, bottom: 0, left: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.1} vertical={false} />
                  <XAxis dataKey="bin" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} width={25} />
                  <Bar dataKey="count" fill={cfg.color} fillOpacity={0.7} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>

              {/* Sample reasons */}
              {dim.sample_reasons && dim.sample_reasons.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Sample justifications</div>
                  {dim.sample_reasons.slice(0, 3).map((reason, i) => (
                    <div key={i} className="text-xs text-muted-foreground italic pl-2 border-l-2 border-border">
                      "{reason.slice(0, 120)}{reason.length > 120 ? "..." : ""}"
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Methodology note */}
      <div className="text-xs text-muted-foreground border-t border-border pt-3">
        <p>
          <b>Methodology:</b> Extended prompt adds 4 new numerical dimensions to the existing 5-dimension impact assessment.
          Each dimension uses a 1.0-10.0 scale with a one-sentence justification. Dimensions support null for non-applicable cases
          (e.g., reproducibility for purely theoretical papers). Tested on {n} randomly sampled papers assessed by Claude Opus 4.6
          using full paper text. Distribution histograms are approximated from summary statistics.
          Surprisingness measures unexpected results (not novelty of approach). Reproducibility assesses methodological detail
          and code/data availability. Translational potential rates proximity to real-world deployment, standardized to 1-10 scale.
        </p>
      </div>
    </div>
  );
}

export default ExtendedDimensionsSection;
