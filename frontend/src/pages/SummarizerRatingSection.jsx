import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const DIM_LABELS = {
  score: "Overall Score",
  significance: "Significance",
  rigor: "Rigor",
  novelty: "Novelty",
  clarity: "Clarity",
};

const DIM_COLORS = {
  score: "#3b82f6",
  significance: "#f59e0b",
  rigor: "#ef4444",
  novelty: "#8b5cf6",
  clarity: "#10b981",
};

function DistChart({ dim, stats, color, resolution }) {
  const hist = resolution === "quarter" ? stats.hist_quarter : stats.hist_half;
  if (!hist) return null;

  const data = [];
  for (let i = 0; i < hist.counts.length; i++) {
    const lo = hist.buckets[i];
    const hi = hist.buckets[i + 1];
    if (lo === undefined || hi === undefined) continue;
    data.push({
      bucket: `${lo.toFixed(resolution === "quarter" ? 2 : 1)}`,
      label: lo,
      count: hist.counts[i],
    });
  }

  return (
    <div className="border border-border rounded-lg p-3 bg-card" data-testid={`dist-${dim}`}>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-semibold" style={{ color }}>{DIM_LABELS[dim] || dim}</span>
        <span className="text-[10px] text-muted-foreground font-mono">
          {stats.mean} avg, {stats.median} med (n={stats.n.toLocaleString()})
        </span>
      </div>
      <div className="h-[140px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
            <XAxis
              dataKey="label" type="number"
              domain={[1, 10]} ticks={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
              tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))"
            />
            <YAxis tick={{ fontSize: 9 }} stroke="hsl(var(--muted-foreground))" width={30} />
            <ReferenceLine x={stats.mean} stroke={color} strokeDasharray="4 4" strokeWidth={1.5} />
            <Bar dataKey="count" fill={color} opacity={0.7} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function StatCard({ dim, stats, color }) {
  return (
    <div className="border border-border rounded-lg p-3 bg-card text-center" data-testid={`stat-${dim}`}>
      <div className="text-[10px] text-muted-foreground mb-1">{DIM_LABELS[dim] || dim}</div>
      <div className="text-2xl font-bold font-mono" style={{ color }}>{stats.mean}</div>
      <div className="text-[10px] text-muted-foreground mt-0.5">
        {"\u03C3"}={stats.std} | med={stats.median}
      </div>
    </div>
  );
}

export default function SummarizerRatingSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState(null);
  const [resolution, setResolution] = useState("half");

  useEffect(() => {
    axios.get(`${API}/api/validation/summarizer-rating-distributions`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const activeModel = useMemo(() => {
    if (!data) return null;
    if (!selectedModel) return null;
    return data.models.find(m => m.key === selectedModel);
  }, [data, selectedModel]);

  // Aggregate "All Models" by averaging histograms
  const allModelsAgg = useMemo(() => {
    if (!data || !data.models.length) return null;
    const dims = {};
    for (const dim of data.dimensions) {
      const allVals = [];
      for (const model of data.models) {
        const d = model.dims[dim];
        if (!d) continue;
        // Reconstruct values from histogram (approximate)
        const hist = resolution === "quarter" ? d.hist_quarter : d.hist_half;
        if (!hist) continue;
        for (let i = 0; i < hist.counts.length; i++) {
          const mid = (hist.buckets[i] + hist.buckets[i + 1]) / 2;
          for (let j = 0; j < hist.counts[i]; j++) allVals.push(mid);
        }
      }
      if (!allVals.length) continue;
      const mean = allVals.reduce((a, b) => a + b, 0) / allVals.length;
      const sorted = [...allVals].sort((a, b) => a - b);
      const median = sorted[Math.floor(sorted.length / 2)];
      const std = Math.sqrt(allVals.reduce((s, v) => s + (v - mean) ** 2, 0) / allVals.length);
      const buckets = resolution === "quarter"
        ? Array.from({ length: 37 }, (_, i) => Math.round((1 + i * 0.25) * 100) / 100)
        : Array.from({ length: 19 }, (_, i) => Math.round((1 + i * 0.5) * 10) / 10);
      const counts = new Array(buckets.length - 1).fill(0);
      for (const v of allVals) {
        for (let i = 0; i < counts.length; i++) {
          if (v >= buckets[i] && v < buckets[i + 1]) { counts[i]++; break; }
        }
      }
      dims[dim] = {
        mean: Math.round(mean * 100) / 100,
        median: Math.round(median * 10) / 10,
        std: Math.round(std * 100) / 100,
        n: allVals.length,
        [`hist_${resolution}`]: { buckets, counts },
      };
    }
    return { dims };
  }, [data, resolution]);

  if (loading) return <div className="space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-32 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;
  if (!data || data.models.length === 0) return <div className="text-center py-12 text-muted-foreground text-sm">No summarizer rating data available.</div>;

  const display = activeModel || allModelsAgg;
  const displayColor = activeModel ? activeModel.color : "#6b7280";
  const totalPapers = data.models.reduce((max, m) => Math.max(max, m.n), 0);

  return (
    <div className="space-y-6" data-testid="summarizer-ratings">
      <div>
        <h2 className="text-xl font-bold">Summarizer Rating Distributions</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Distribution of AI single-item ratings across {totalPapers.toLocaleString()} papers.
          Each paper receives a 1-10 score across 5 dimensions from a single LLM call.
        </p>
      </div>

      <hr className="border-border" />

      {/* Model selector */}
      <div className="flex items-center gap-1 p-1 bg-secondary/50 rounded-lg w-fit" data-testid="model-tabs">
        <button
          onClick={() => setSelectedModel(null)}
          className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${!selectedModel ? "bg-background shadow text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          All Models
        </button>
        {data.models.map(m => (
          <button
            key={m.key}
            onClick={() => setSelectedModel(m.key)}
            className={`px-3 py-1.5 rounded-md text-xs transition-colors ${selectedModel === m.key ? "bg-background shadow font-medium" : "text-muted-foreground hover:text-foreground"}`}
          >
            <span style={{ color: selectedModel === m.key ? m.color : undefined }}>
              {m.label}
            </span>
            <span className="ml-1 text-[10px] text-muted-foreground">({m.n.toLocaleString()})</span>
          </button>
        ))}
      </div>

      {/* Resolution toggle */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Score Distribution</h3>
        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={resolution === "quarter"}
            onChange={e => setResolution(e.target.checked ? "quarter" : "half")}
            className="rounded"
          />
          Full resolution (0.25 steps)
        </label>
      </div>

      {/* Distribution charts */}
      {display && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.dimensions.map(dim => {
            const stats = display.dims[dim];
            if (!stats) return null;
            return (
              <DistChart
                key={dim} dim={dim} stats={stats}
                color={activeModel ? displayColor : DIM_COLORS[dim]}
                resolution={resolution}
              />
            );
          })}
        </div>
      )}

      {/* Summary stat cards */}
      {display && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {data.dimensions.map(dim => {
            const stats = display.dims[dim];
            if (!stats) return null;
            return (
              <StatCard
                key={dim} dim={dim} stats={stats}
                color={activeModel ? displayColor : DIM_COLORS[dim]}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
