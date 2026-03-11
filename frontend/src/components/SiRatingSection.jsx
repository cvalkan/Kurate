import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { BarChart3, TrendingUp } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const METRIC_LABELS = {
  score: "Overall Score",
  significance: "Significance",
  rigor: "Rigor",
  novelty: "Novelty",
  clarity: "Clarity",
};

const METRIC_COLORS = {
  score: "#3b82f6",
  significance: "#f59e0b",
  rigor: "#ef4444",
  novelty: "#8b5cf6",
  clarity: "#22c55e",
};

const MODEL_TABS = [
  { id: null, label: "All Models" },
  { id: "claude", label: "Claude Opus" },
  { id: "gpt", label: "GPT-5.2" },
  { id: "gemini", label: "Gemini 3 Pro" },
];

function DistributionChart({ data, metric, color }) {
  if (!data?.histogram) return null;
  const maxCount = Math.max(...data.histogram.map(h => h.count), 1);
  const barW = 100 / data.histogram.length;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium" style={{ color }}>{METRIC_LABELS[metric]}</span>
        <span className="text-[10px] text-muted-foreground font-mono">
          {data.mean} avg, {data.median} med (n={data.n})
        </span>
      </div>
      <div className="relative h-20 border border-border rounded bg-secondary/10" data-testid={`si-dist-${metric}`}>
        <svg viewBox="0 0 100 50" preserveAspectRatio="none" className="w-full h-full">
          {data.histogram.map((h, i) => {
            const barH = (h.count / maxCount) * 45;
            return (
              <rect key={h.bin} x={i * barW + barW * 0.1} y={50 - barH}
                width={barW * 0.8} height={barH} fill={color} fillOpacity={0.7} rx={0.5}>
                <title>{h.bin}: {h.count} papers</title>
              </rect>
            );
          })}
          {data.mean && (
            <line x1={((data.mean - 1) / 9) * 100} y1={0} x2={((data.mean - 1) / 9) * 100} y2={50}
              stroke={color} strokeWidth={0.5} strokeDasharray="2 1" />
          )}
        </svg>
        <div className="absolute bottom-0 left-0 right-0 flex justify-between px-1">
          <span className="text-[8px] text-muted-foreground">1</span>
          <span className="text-[8px] text-muted-foreground">5</span>
          <span className="text-[8px] text-muted-foreground">10</span>
        </div>
      </div>
    </div>
  );
}

function CorrelationMatrix({ correlations }) {
  const metrics = ["score", "significance", "rigor", "novelty", "clarity"];
  const matrix = {};
  for (const [pair, data] of Object.entries(correlations)) {
    matrix[pair] = data.spearman;
  }
  const cellColor = (v) => {
    if (v >= 0.9) return "bg-green-100 text-green-800";
    if (v >= 0.8) return "bg-green-50 text-green-700";
    if (v >= 0.7) return "bg-amber-50 text-amber-700";
    if (v >= 0.5) return "bg-orange-50 text-orange-700";
    return "bg-red-50 text-red-700";
  };
  return (
    <div className="overflow-x-auto" data-testid="si-correlation-matrix">
      <table className="text-[10px] w-full">
        <thead>
          <tr>
            <th className="p-1"></th>
            {metrics.slice(1).map(m => (
              <th key={m} className="p-1 text-center text-muted-foreground font-medium">{METRIC_LABELS[m].slice(0, 3)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.slice(0, -1).map((m1, i) => (
            <tr key={m1}>
              <td className="p-1 font-medium text-muted-foreground">{METRIC_LABELS[m1].slice(0, 4)}</td>
              {metrics.slice(1).map((m2, j) => {
                if (j < i) return <td key={m2} className="p-1"></td>;
                const rho = matrix[`${m1} vs ${m2}`];
                if (rho === undefined) return <td key={m2} className="p-1 text-center text-muted-foreground">-</td>;
                return (
                  <td key={m2} className={`p-1 text-center font-mono font-medium rounded ${cellColor(rho)}`}>{rho.toFixed(2)}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InterModelSiHeatmap({ interModelSi }) {
  if (!interModelSi || Object.keys(interModelSi).length === 0) {
    return (
      <div className="text-center py-4 text-muted-foreground">
        <p className="text-[10px]">Per-model SI ratings needed.</p>
        <p className="text-[9px] mt-1">Generate ratings from all 3 models to see inter-model correlation.</p>
      </div>
    );
  }

  const modelOrder = ["claude", "gpt", "gemini"];
  const modelLabels = { claude: "Claude", gpt: "GPT-5.2", gemini: "Gemini" };
  const present = modelOrder.filter(mk =>
    Object.keys(interModelSi).some(k => k.includes(mk))
  );
  if (present.length < 2) present.push(...modelOrder.filter(m => !present.includes(m)).slice(0, 2 - present.length));
  const names = present.map(m => modelLabels[m] || m);
  const n = names.length;

  const matrix = Array.from({ length: n }, () => Array(n).fill(1));
  for (const [pair, stats] of Object.entries(interModelSi)) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (pair.includes(present[i]) && pair.includes(present[j])) {
          matrix[i][j] = stats.spearman;
          matrix[j][i] = stats.spearman;
        }
      }
    }
  }

  const cellSize = 56;
  const labelW = 60;
  const labelH = 20;
  const w = labelW + n * cellSize;
  const h = labelH + n * cellSize;
  const heatColor = (v) => {
    if (v >= 1) return "#dbeafe";
    if (v >= 0.8) return "#22c55e";
    if (v >= 0.7) return "#86efac";
    if (v >= 0.6) return "#fde68a";
    if (v >= 0.5) return "#fbbf24";
    return "#f87171";
  };

  return (
    <div data-testid="inter-model-si-heatmap">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-w-xs">
        {names.map((name, j) => (
          <text key={`col-${j}`} x={labelW + j * cellSize + cellSize / 2} y={labelH - 4}
            textAnchor="middle" className="text-[9px] fill-muted-foreground font-medium">{name}</text>
        ))}
        {names.map((name, i) => (
          <g key={`row-${i}`}>
            <text x={labelW - 4} y={labelH + i * cellSize + cellSize / 2 + 3}
              textAnchor="end" className="text-[9px] fill-muted-foreground font-medium">{name}</text>
            {names.map((_, j) => {
              const val = matrix[i][j];
              const isdiag = i === j;
              return (
                <g key={`cell-${i}-${j}`}>
                  <rect x={labelW + j * cellSize + 1} y={labelH + i * cellSize + 1}
                    width={cellSize - 2} height={cellSize - 2} rx={4}
                    fill={isdiag ? "#f1f5f9" : heatColor(val)} fillOpacity={isdiag ? 1 : 0.8} />
                  <text x={labelW + j * cellSize + cellSize / 2} y={labelH + i * cellSize + cellSize / 2 + 4}
                    textAnchor="middle"
                    className={`font-mono font-bold ${isdiag ? "text-[9px] fill-muted-foreground" : "text-[11px] fill-foreground"}`}>
                    {isdiag ? "1.00" : val.toFixed(2)}
                  </text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    </div>
  );
}

function CategoryBreakdown({ categories }) {
  if (!categories?.length) return null;
  const maxScore = Math.max(...categories.map(c => c.mean_score));
  const minScore = Math.min(...categories.map(c => c.mean_score));
  const range = maxScore - minScore || 1;

  return (
    <div className="space-y-1" data-testid="si-category-breakdown">
      {categories.slice(0, 8).map(c => (
        <div key={c.category} className="flex items-center gap-2 text-[10px]">
          <span className="w-20 font-mono text-muted-foreground truncate" title={c.category}>{c.category}</span>
          <div className="flex-1 h-3 bg-secondary/30 rounded overflow-hidden">
            <div className="h-full rounded" style={{
              width: `${((c.mean_score - minScore + range * 0.15) / (range * 1.15)) * 100}%`,
              backgroundColor: c.mean_score >= 6 ? "#22c55e" : c.mean_score >= 5 ? "#f59e0b" : "#ef4444",
              opacity: 0.6,
            }} />
          </div>
          <span className="font-mono w-16 text-right text-muted-foreground">{c.mean_score} ({c.count})</span>
        </div>
      ))}
    </div>
  );
}

export function SiRatingSection({ category }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState(null);
  const cacheRef = useRef({});

  const fetchData = useCallback(async () => {
    const cacheKey = `${category || "__all__"}:${selectedModel || "all"}`;
    if (cacheRef.current[cacheKey]) {
      setData(cacheRef.current[cacheKey]);
      setLoading(false);
    }
    try {
      const params = {};
      if (category) params.category = category;
      if (selectedModel) params.model = selectedModel;
      const res = await axios.get(`${API}/api/si-rating-stats`, { params });
      cacheRef.current[cacheKey] = res.data;
      setData(res.data);
    } catch (err) {
      console.error("SI rating stats error:", err);
    } finally {
      setLoading(false);
    }
  }, [category, selectedModel]);

  useEffect(() => {
    const cacheKey = `${category || "__all__"}:${selectedModel || "all"}`;
    if (!cacheRef.current[cacheKey]) setLoading(true);
    fetchData();
  }, [fetchData]);

  const metrics = useMemo(() => ["score", "significance", "rigor", "novelty", "clarity"], []);

  if (loading && !data) return <div className="h-40 bg-secondary/20 rounded-lg animate-pulse" />;

  const hasData = data?.status === "ok";
  const availableModels = data?.available_models || [];

  return (
    <div className="mb-10" data-testid="si-rating-section">
      <div className="mb-4 pb-2 border-b border-border">
        <h2 className="font-heading text-lg font-medium flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          Single-Item Rating Analysis
        </h2>
        <p className="text-xs text-muted-foreground">
          Distribution of AI single-item ratings{hasData ? ` across ${data.total_papers} papers` : ""}.
          Each paper receives a 1-10 score across 5 dimensions from a single LLM call.
        </p>
      </div>

      {/* Model toggle */}
      <div className="flex items-center gap-1 mb-5 p-1 bg-primary/5 rounded-lg" data-testid="si-model-toggle">
        {MODEL_TABS.map(tab => {
          const modelInfo = tab.id ? availableModels.find(m => m.id === tab.id) : null;
          const count = tab.id ? (modelInfo?.count || 0) : (data?.total_papers || 0);
          const isActive = selectedModel === tab.id;
          return (
            <button key={tab.id || "all"} onClick={() => setSelectedModel(tab.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                isActive ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
              } ${!tab.id || count > 0 ? "" : "opacity-40"}`}
              data-testid={`si-model-${tab.id || "all"}`}>
              {tab.label}
              {tab.id && <span className="ml-1 text-[9px] opacity-60">({count})</span>}
            </button>
          );
        })}
      </div>

      {!hasData ? (
        <div className="p-6 border border-border rounded-lg text-center text-muted-foreground">
          <BarChart3 className="h-6 w-6 mx-auto mb-2 opacity-30" />
          <p className="text-xs">
            {selectedModel
              ? `No SI ratings from ${MODEL_TABS.find(t => t.id === selectedModel)?.label || selectedModel} yet.`
              : `Not enough SI rating data yet (${data?.total_papers || 0} papers rated).`}
          </p>
        </div>
      ) : (
        <>
          {/* Distributions grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            {metrics.map(m => (
              data.distributions[m] && (
                <DistributionChart key={m} data={data.distributions[m]} metric={m} color={METRIC_COLORS[m]} />
              )
            ))}
          </div>

          {/* Stats summary row */}
          <div className="grid grid-cols-5 gap-2 mb-6">
            {metrics.map(m => {
              const d = data.distributions[m];
              if (!d) return null;
              return (
                <div key={m} className="p-2 border border-border rounded-lg text-center" data-testid={`si-stat-${m}`}>
                  <div className="text-[10px] text-muted-foreground mb-0.5">{METRIC_LABELS[m]}</div>
                  <div className="font-mono text-lg font-bold" style={{ color: METRIC_COLORS[m] }}>{d.mean}</div>
                  <div className="text-[9px] text-muted-foreground">&sigma;={d.std} | {d.min}-{d.max}</div>
                </div>
              );
            })}
          </div>

          {/* Bottom panels: inter-metric, inter-model SI, category */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Object.keys(data.metric_correlations).length > 0 && (
              <div className="p-3 border border-border rounded-lg">
                <h3 className="text-sm font-medium mb-2">Inter-Metric Correlation (Spearman)</h3>
                <p className="text-[10px] text-muted-foreground mb-2">
                  How correlated are the sub-scores? High correlation = the model struggles to differentiate dimensions.
                </p>
                <CorrelationMatrix correlations={data.metric_correlations} />
              </div>
            )}

            <div className="p-3 border border-border rounded-lg">
              <h3 className="text-sm font-medium mb-2">Inter-Model SI Correlation</h3>
              <p className="text-[10px] text-muted-foreground mb-2">
                Spearman rank correlation between the single-item rated ranked lists of the 3 models.
              </p>
              <InterModelSiHeatmap interModelSi={data.inter_model_si} />
            </div>

            {data.by_category?.length > 0 && (
              <div className="p-3 border border-border rounded-lg">
                <h3 className="text-sm font-medium mb-2">Mean Score by Category</h3>
                <p className="text-[10px] text-muted-foreground mb-2">
                  Average overall score per primary category. Bars show mean score.
                </p>
                <CategoryBreakdown categories={data.by_category} />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
