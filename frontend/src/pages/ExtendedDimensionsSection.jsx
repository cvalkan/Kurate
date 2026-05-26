import { useState, useEffect } from "react";
import axios from "axios";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const DIM_CONFIG = {
  difficulty: { color: "#8b5cf6", label: "Difficulty", desc: "Technical difficulty. 1 = accessible to undergrads, 5 = graduate-level, 10 = deep specialist expertise." },
  surprisingness: { color: "#ec4899", label: "Surprisingness", desc: "How unexpected are the results and conclusions. 1 = fully expected, 10 = overturns conventional assumptions." },
  reproducibility: { color: "#06b6d4", label: "Reproducibility", desc: "Could an independent researcher replicate the results from this paper alone? 1 = key details missing, 10 = fully specified with code/data." },
  translational_potential: { color: "#f97316", label: "Translational Potential", desc: "Proximity to real-world application. 1 = pure theory, 5 = clear applied potential, 10 = directly deployable." },
  evidence_strength: { color: "#14b8a6", label: "Evidence Strength", desc: "How well do proofs, experiments, ablations, and statistical analyses support the main claims? Distinct from rigor (methodology design)." },
  generalisability: { color: "#f43f5e", label: "Generalisability", desc: "How broadly do findings apply beyond the tested conditions? 1 = narrow results, 10 = broadly applicable across domains and scales." },
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
  const histograms = data?.exp3?.histograms;
  const papers = data?.exp3?.papers || [];
  const n = data?.exp3?.n || 0;
  const [expandedDim, setExpandedDim] = useState(null);

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

      {/* Individual dimension cards with fine-grained histograms */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {ext.map(dim => {
          const cfg = DIM_CONFIG[dim.name] || { color: "#666", label: dim.name, desc: "" };
          const bins = (histograms && histograms[dim.name]) || [];
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

              {/* Fine-grained distribution chart */}
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={bins} margin={{ top: 5, right: 5, bottom: 0, left: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.1} vertical={false} />
                  <XAxis
                    dataKey="bin" tick={{ fontSize: 9 }}
                    interval={1}
                    tickFormatter={v => parseFloat(v) % 1 === 0 ? v : ""}
                  />
                  <YAxis tick={{ fontSize: 9 }} width={20} allowDecimals={false} domain={[0, 'auto']} />
                  <RechartsTooltip
                    contentStyle={{ background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: "6px", fontSize: "11px" }}
                    formatter={(value) => [`${value} papers`, "Count"]}
                    labelFormatter={(label) => `Score: ${label}`}
                  />
                  <ReferenceLine x={dim.mean.toFixed(1)} stroke={cfg.color} strokeDasharray="4 4" strokeWidth={1.5} label={{ value: `μ=${dim.mean.toFixed(1)}`, position: "top", fontSize: 9, fill: cfg.color }} />
                  <Bar dataKey="count" fill={cfg.color} fillOpacity={0.75} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>

              {/* Histogram only - lists moved below */}
            </div>
          );
        })}
      </div>

      {/* Full-width ranked lists per dimension */}
      {ext.map(dim => {
        const cfg = DIM_CONFIG[dim.name] || { color: "#666", label: dim.name, desc: "" };
        const dimName = dim.name;
        const reasonKey = `${dimName}_reason`;
        const ranked = papers
          .filter(p => p.ratings?.[dimName] != null)
          .map(p => ({ ...p, val: p.ratings[dimName], reason: p.ratings[reasonKey] || "" }))
          .sort((a, b) => b.val - a.val);
        const isExpanded = expandedDim === dimName;
        const shown = isExpanded ? ranked : ranked.slice(0, 10);
        return (
          <div key={`list-${dimName}`} className="border border-border rounded-lg p-4 bg-card" data-testid={`list-${dimName}`}>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: cfg.color }} />
              <h3 className="text-sm font-medium">Papers Ranked by {cfg.label}</h3>
              <span className="text-[10px] text-muted-foreground">{ranked.length} papers</span>
            </div>
            <div className={`space-y-1 ${isExpanded ? "max-h-[600px] overflow-y-auto" : ""}`}>
              {shown.map((p, i) => (
                <div key={p.paper_id} className="flex items-start gap-2 py-1.5 border-b border-border/30 last:border-0">
                  <span className="text-[10px] font-mono text-muted-foreground w-5 shrink-0 text-right pt-0.5">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">{p.title}</span>
                      <span className="text-xs font-mono shrink-0 px-1.5 py-0.5 rounded" style={{ color: cfg.color, backgroundColor: `${cfg.color}15` }}>{p.val.toFixed(1)}</span>
                      <span className="text-[10px] text-muted-foreground shrink-0">{p.category}</span>
                    </div>
                    {p.reason && (
                      <div className="text-xs text-muted-foreground mt-0.5 leading-snug">
                        {p.reason}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {ranked.length > 10 && (
              <button
                className="text-xs text-accent hover:underline mt-2"
                onClick={() => setExpandedDim(isExpanded ? null : dimName)}
              >
                {isExpanded ? "Show top 10" : `Show all ${ranked.length} papers`}
              </button>
            )}
          </div>
        );
      })}

      {/* Methodology note */}
      <div className="text-xs text-muted-foreground border-t border-border pt-3">
        <p>
          <b>Methodology:</b> Extended prompt adds 6 new numerical dimensions to the existing 5-dimension impact assessment.
          Each dimension uses a 1.0-10.0 scale with a one-sentence justification. Dimensions support null for non-applicable cases
          (e.g., reproducibility for purely theoretical papers). Tested on {n} randomly sampled papers assessed by Claude Opus 4.6
          using full paper text. Histograms show the actual score distribution at 0.5-point granularity with mean indicated by dashed line.
          Surprisingness measures unexpected results (not novelty of approach). Reproducibility assesses methodological detail
          and code/data availability. Translational potential rates proximity to real-world deployment.
          Evidence strength measures how well claims are supported (distinct from rigor which rates methodology design).
          Generalisability assesses how broadly findings apply beyond tested conditions.
        </p>
      </div>
    </div>
  );
}

export default ExtendedDimensionsSection;
