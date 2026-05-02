import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine, Tooltip } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const DIM_LABELS = {
  score: "Overall Score",
  subscore_avg: "Subscore Average",
  significance: "Significance",
  rigor: "Rigor",
  novelty: "Novelty",
  clarity: "Clarity",
};

const DIM_COLORS = {
  score: "#3b82f6",
  subscore_avg: "#6366f1",
  significance: "#f59e0b",
  rigor: "#ef4444",
  novelty: "#8b5cf6",
  clarity: "#10b981",
};

const RESOLUTIONS = [
  { value: 0.1, label: "0.1" },
  { value: 0.25, label: "0.25" },
  { value: 0.5, label: "0.5" },
  { value: 1.0, label: "1.0" },
];

function buildHist(values, step) {
  const lo = 1, hi = 10;
  const buckets = [];
  for (let b = lo; b < hi + step / 2; b = Math.round((b + step) * 100) / 100) buckets.push(b);
  const counts = new Array(buckets.length - 1).fill(0);
  for (const v of values) {
    for (let i = 0; i < counts.length; i++) {
      if (v >= buckets[i] && v < buckets[i + 1]) { counts[i]++; break; }
      if (i === counts.length - 1 && v >= buckets[i]) { counts[i]++; break; }
    }
  }
  return buckets.map((b, i) => i < counts.length ? { bucket: b, count: counts[i] } : null).filter(Boolean);
}

function DistChart({ dim, rawValues, stats, color, step }) {
  const data = useMemo(() => buildHist(rawValues, step), [rawValues, step]);

  return (
    <div className="border border-border rounded-lg p-3 bg-card" data-testid={`dist-${dim}`}>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-semibold" style={{ color }}>{DIM_LABELS[dim] || dim}</span>
        <span className="text-[10px] text-muted-foreground font-mono">
          {stats.mean} avg, {stats.median} med, {"\u03C3"}={stats.std} (n={stats.n.toLocaleString()})
        </span>
      </div>
      <div className="h-[140px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
            <XAxis
              dataKey="bucket" type="number"
              domain={[1, 10]} ticks={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
              tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))"
            />
            <YAxis tick={{ fontSize: 9 }} stroke="hsl(var(--muted-foreground))" width={30} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                return (
                  <div className="rounded border border-border bg-popover p-1.5 shadow text-[10px]">
                    <span className="font-mono">{d.bucket.toFixed(step < 0.5 ? 2 : 1)}: {d.count}</span>
                  </div>
                );
              }}
            />
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
  const [step, setStep] = useState(0.5);

  useEffect(() => {
    axios.get(`${API}/api/validation/summarizer-rating-distributions`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const activeModel = useMemo(() => {
    if (!data || !selectedModel) return null;
    return data.models.find(m => m.key === selectedModel);
  }, [data, selectedModel]);

  if (loading) return <div className="space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-32 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;
  if (!data || !data.models?.length) return <div className="text-center py-12 text-muted-foreground text-sm">No summarizer rating data available.</div>;

  const display = activeModel;
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

      {/* Model selector */}
      <div className="flex items-center gap-1 p-1 bg-secondary/50 rounded-lg w-fit flex-wrap" data-testid="model-tabs">
        {data.models.map(m => (
          <button
            key={m.key}
            onClick={() => setSelectedModel(selectedModel === m.key ? null : m.key)}
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
        <h3 className="text-sm font-medium">
          {display ? `${display.label} — Per-Dimension Distributions` : "Select a model above"}
        </h3>
        {display && (
          <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
            {RESOLUTIONS.map(r => (
              <button
                key={r.value}
                onClick={() => setStep(r.value)}
                className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${step === r.value ? "bg-background shadow text-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
              >
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Distribution charts */}
      {display && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.dimensions.map(dim => {
              const stats = display.dims[dim];
              if (!stats) return null;
              return (
                <DistChart
                  key={dim} dim={dim}
                  rawValues={stats.raw || []}
                  stats={stats}
                  color={displayColor}
                  step={step}
                />
              );
            })}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {data.dimensions.map(dim => {
              const stats = display.dims[dim];
              if (!stats) return null;
              return <StatCard key={dim} dim={dim} stats={stats} color={displayColor} />;
            })}
          </div>
        </>
      )}
    </div>
  );
}
