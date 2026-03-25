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
  subscore_avg: "Subscore Average",
};

const METRIC_COLORS = {
  score: "#3b82f6",
  significance: "#f59e0b",
  rigor: "#ef4444",
  novelty: "#8b5cf6",
  clarity: "#22c55e",
  subscore_avg: "#6366f1",
};

const MODEL_TABS = [
  { id: null, label: "All Models" },
  { id: "claude", label: "Claude Opus" },
  { id: "gpt", label: "GPT-5.2" },
  { id: "gemini", label: "Gemini 3 Pro" },
];

function DistributionChart({ data, metric, color, showRaw }) {
  const histData = showRaw && data?.raw_histogram ? data.raw_histogram : data?.histogram;
  if (!histData) return null;
  const display = histData;
  const maxCount = Math.max(...display.map(h => h.count), 1);
  const barW = 100 / display.length;

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
          {display.map((h, i) => {
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
    if (v >= 1.0) return "bg-secondary/30 text-muted-foreground";
    if (v >= 0.9) return "bg-green-100 text-green-800";
    if (v >= 0.8) return "bg-green-50 text-green-700";
    if (v >= 0.7) return "bg-amber-50 text-amber-700";
    if (v >= 0.5) return "bg-orange-50 text-orange-700";
    return "bg-red-50 text-red-700";
  };
  const getVal = (m1, m2) => {
    if (m1 === m2) return 1.0;
    return matrix[`${m1} vs ${m2}`] ?? matrix[`${m2} vs ${m1}`] ?? null;
  };
  return (
    <div className="overflow-x-auto" data-testid="si-correlation-matrix">
      <table className="text-[10px] w-full">
        <thead>
          <tr>
            <th className="p-1"></th>
            {metrics.map(m => (
              <th key={m} className="p-1 text-center text-muted-foreground font-medium">{METRIC_LABELS[m].slice(0, 3)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((m1) => (
            <tr key={m1}>
              <td className="p-1 font-medium text-muted-foreground">{METRIC_LABELS[m1].slice(0, 4)}</td>
              {metrics.map((m2) => {
                const val = getVal(m1, m2);
                if (val === null) return <td key={m2} className="p-1 text-center text-muted-foreground">-</td>;
                return (
                  <td key={m2} className={`p-1 text-center font-mono font-medium rounded ${cellColor(val)}`}>{val.toFixed(2)}</td>
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
  const [showRawDist, setShowRawDist] = useState(false);
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

  const metrics = useMemo(() => ["score", "subscore_avg", "significance", "rigor", "novelty", "clarity"], []);

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
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground">Score Distribution</span>
            <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground cursor-pointer">
              <input type="checkbox" checked={showRawDist} onChange={e => setShowRawDist(e.target.checked)}
                className="rounded border-border h-3 w-3" />
              Full resolution (0.1 steps)
            </label>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            {metrics.map(m => (
              data.distributions[m] && (
                <DistributionChart key={m} data={data.distributions[m]} metric={m} color={METRIC_COLORS[m]} showRaw={showRawDist} />
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

          {/* Model comparison: SI Rating Calibration */}
          {data.model_comparison && Object.keys(data.model_comparison).length >= 2 && (
            <div className="mt-4 p-3 border border-border rounded-lg" data-testid="si-model-comparison">
              <h3 className="text-sm font-medium mb-1">SI Rating Calibration</h3>
              <p className="text-[10px] text-muted-foreground mb-3">
                Each model uses a different scale for its 1–10 ratings — different means, spreads, and ranges.
                This miscalibration means raw SI scores are <em>not comparable across models</em>. Pairwise tournament rankings avoid this problem entirely.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-[10px]" style={{ tableLayout: "fixed" }}>
                  <colgroup>
                    <col />
                    <col style={{ width: "55px" }} />
                    <col style={{ width: "55px" }} />
                    <col style={{ width: "50px" }} />
                    <col style={{ width: "65px" }} />
                    <col style={{ width: "80px" }} />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-1 pr-1">Model</th>
                      <th className="text-right py-1 px-1">Mean</th>
                      <th className="text-right py-1 px-1">{"\u03C3"}</th>
                      <th className="text-right py-1 px-1">Range</th>
                      <th className="text-right py-1 px-1">Avg Inter-{"\u03C1"}</th>
                      <th className="text-right py-1 px-1">Papers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.model_comparison)
                      .sort((a, b) => b[1].std - a[1].std)
                      .map(([mk, s]) => {
                        const labels = { claude: "Claude Opus", gpt: "GPT-5.2", gemini: "Gemini 3 Pro" };
                        return (
                          <tr key={mk} className="border-b border-border/20">
                            <td className="py-0.5 pr-1 font-medium">{labels[mk] || mk}</td>
                            <td className="text-right py-0.5 px-1 font-mono">{s.mean}</td>
                            <td className="text-right py-0.5 px-1 font-mono font-bold">{s.std}</td>
                            <td className="text-right py-0.5 px-1 font-mono">{s.min}-{s.max}</td>
                            <td className="text-right py-0.5 px-1 font-mono">{s.avg_inter_metric_rho ?? "—"}</td>
                            <td className="text-right py-0.5 px-1 font-mono text-muted-foreground">{s.n}</td>
                          </tr>
                        );
                    })}
                  </tbody>
                </table>
              </div>
              {(() => {
                const entries = Object.entries(data.model_comparison);
                if (entries.length < 2) return null;
                const sorted = entries.sort((a, b) => b[1].std - a[1].std);
                const widest = sorted[0];
                const narrowest = sorted[sorted.length - 1];
                const labels = { claude: "Claude", gpt: "GPT-5.2", gemini: "Gemini" };
                const wName = labels[widest[0]] || widest[0];
                const nName = labels[narrowest[0]] || narrowest[0];
                return (
                  <div className="mt-2 text-[10px] text-muted-foreground border-t border-border/30 pt-2 space-y-1">
                    <p>
                      <strong>Calibration gap:</strong> {wName} scores have a mean of {widest[1].mean} ({"\u03C3"}={widest[1].std}),
                      while {nName} averages {narrowest[1].mean} ({"\u03C3"}={narrowest[1].std}).
                      {Math.abs(widest[1].mean - narrowest[1].mean) >= 0.1 && ` The ${Math.abs(widest[1].mean - narrowest[1].mean).toFixed(1)}-point mean difference alone would shift rankings if raw SI scores were pooled.`}
                    </p>
                    <p>
                      <strong>Implication:</strong> Averaging SI scores across models without normalizing conflates model biases with paper quality.
                      The pairwise tournament bypasses this entirely — each comparison is model-internal, so calibration differences are irrelevant.
                    </p>
                  </div>
                );
              })()}
            </div>
          )}

          {/* Pairwise Ranking vs SI Score — multi-method comparison */}
          {data.pw_vs_si && data.pw_vs_si.overall?.length > 0 && (
            <div className="mt-6 space-y-4" data-testid="pw-vs-si-section">
              <div className="pb-2 border-b border-border">
                <h3 className="text-sm font-semibold">Pairwise Tournament vs Single-Item Ranking</h3>
                <p className="text-[10px] text-muted-foreground mt-0.5 max-w-2xl">
                  How well does the pairwise tournament ranking (from {data.pw_vs_si.n_matches?.toLocaleString()} head-to-head matches) agree
                  with averaged single-item scores? TrueSkill is the most robust PW estimator — it produces the most stable rankings from sparse match data.
                </p>
              </div>

              {/* Overall comparison table */}
              <div className="border border-border rounded-lg overflow-hidden">
                <div className="px-3 py-1.5 bg-emerald-500/5 border-b border-border">
                  <span className="text-[10px] font-semibold text-muted-foreground">
                    PW Method vs Averaged SI Score
                  </span>
                </div>
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground bg-secondary/5">
                      <th className="py-1.5 px-3 text-left font-medium">PW Estimator</th>
                      <th className="py-1.5 px-3 text-right font-medium">Spearman {"\u03C1"}</th>
                      <th className="py-1.5 px-3 text-right font-medium">Kendall {"\u03C4"}</th>
                      <th className="py-1.5 px-3 text-right font-medium">Pearson r</th>
                      <th className="py-1.5 px-3 text-right font-medium">n</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.pw_vs_si.overall.map((row, i) => {
                      const isBest = data.pw_vs_si.overall.length > 1 &&
                        row.spearman_rho === Math.max(...data.pw_vs_si.overall.map(r => r.spearman_rho));
                      return (
                        <tr key={row.method} className={`border-b border-border/20 ${isBest ? "bg-emerald-500/[0.06]" : ""}`}>
                          <td className="py-1.5 px-3 font-medium">
                            {row.label}
                            {isBest && <span className="ml-1.5 text-[9px] text-emerald-600 font-semibold">BEST</span>}
                          </td>
                          <td className={`py-1.5 px-3 text-right font-mono font-semibold ${isBest ? "text-emerald-700" : ""}`}>
                            {row.spearman_rho.toFixed(4)}
                          </td>
                          <td className="py-1.5 px-3 text-right font-mono">{row.kendall_tau.toFixed(4)}</td>
                          <td className="py-1.5 px-3 text-right font-mono">{row.pearson_r.toFixed(4)}</td>
                          <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{row.n}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Per-model PW vs SI */}
              {Object.keys(data.pw_vs_si.per_model || {}).length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-muted-foreground mb-2">Per-Model Breakdown</h4>
                  <p className="text-[10px] text-muted-foreground mb-3 max-w-2xl">
                    PW ranking correlated against each model's individual SI scores.
                    Differences reveal which models' direct ratings best agree with the tournament consensus.
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {["claude", "gpt", "gemini"].map(mk => {
                      const mData = data.pw_vs_si.per_model[mk];
                      if (!mData) return null;
                      const bestRow = mData.rows.reduce((best, r) =>
                        r.spearman_rho > (best?.spearman_rho || -1) ? r : best, null);
                      return (
                        <div key={mk} className="border border-border rounded-lg overflow-hidden" data-testid={`pw-vs-si-${mk}`}>
                          <div className="px-3 py-1.5 bg-secondary/10 border-b border-border">
                            <span className="text-[10px] font-semibold">{mData.label} SI</span>
                          </div>
                          <table className="w-full text-[10px]">
                            <thead>
                              <tr className="border-b border-border/50 text-muted-foreground">
                                <th className="py-1 px-2 text-left font-medium">PW Method</th>
                                <th className="py-1 px-2 text-right font-medium">{"\u03C1"}</th>
                                <th className="py-1 px-2 text-right font-medium">{"\u03C4"}</th>
                                <th className="py-1 px-2 text-right font-medium">n</th>
                              </tr>
                            </thead>
                            <tbody>
                              {mData.rows.map(row => (
                                <tr key={row.method} className={`border-b border-border/10 ${row.method === bestRow?.method ? "bg-emerald-500/[0.04]" : ""}`}>
                                  <td className="py-1 px-2 font-medium">{row.label.replace("Normalized ", "")}</td>
                                  <td className="py-1 px-2 text-right font-mono font-semibold">{row.spearman_rho.toFixed(3)}</td>
                                  <td className="py-1 px-2 text-right font-mono">{row.kendall_tau.toFixed(3)}</td>
                                  <td className="py-1 px-2 text-right font-mono text-muted-foreground">{row.n}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Legacy fallback for old bt_vs_si data */}
          {!data.pw_vs_si && data.bt_vs_si && (
            <div className="mt-4 p-3 border border-emerald-200 bg-emerald-500/5 rounded-lg" data-testid="bt-vs-si-section">
              <h3 className="text-sm font-medium mb-1">Pairwise Tournament vs Single-Item Ranking</h3>
              <p className="text-[10px] text-muted-foreground mb-3">
                Correlation between the ranking from pairwise tournament matches and the ranking from single-item scores.
              </p>
              <div className="flex items-center gap-4">
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold text-emerald-700">{data.bt_vs_si.spearman_rho}</div>
                  <div className="text-[9px] text-muted-foreground">Spearman {"\u03C1"}</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold text-emerald-600">{data.bt_vs_si.kendall_tau}</div>
                  <div className="text-[9px] text-muted-foreground">Kendall {"\u03C4"}</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold text-emerald-600">{data.bt_vs_si.pearson_r}</div>
                  <div className="text-[9px] text-muted-foreground">Pearson r</div>
                </div>
                <div className="text-[10px] text-muted-foreground ml-2">
                  n = {data.bt_vs_si.n} papers
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
