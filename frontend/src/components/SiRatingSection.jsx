import { useState, useEffect, useMemo } from "react";
import { BarChart3, TrendingUp } from "lucide-react";

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
          <span className="text-[10px] text-muted-foreground">1</span>
          <span className="text-[10px] text-muted-foreground">5</span>
          <span className="text-[10px] text-muted-foreground">10</span>
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

export function SiRatingSection({ category, hidePwVsSi = false, siData: propData }) {
  const [data, setData] = useState(propData || null);
  const [showRawDist, setShowRawDist] = useState(false);
  const [loading, setLoading] = useState(!propData);
  const [selectedModel, setSelectedModel] = useState(null);

  // Use prop data when available (from unified endpoint), fallback to own fetch
  useEffect(() => {
    if (propData) {
      setData(propData);
      setLoading(false);
    }
  }, [propData]);

  // When model tab changes, use per_model_distributions from unified data
  useEffect(() => {
    if (!propData) return;
    if (!selectedModel) {
      // "All Models" — use the original propData distributions
      setData(propData);
    } else {
      // Per-model — use per_model_distributions if available
      const perModel = propData.per_model_distributions?.[selectedModel];
      if (perModel) {
        setData({ ...propData, distributions: perModel, total_papers: perModel[Object.keys(perModel)[0]]?.n || 0 });
      }
    }
  }, [selectedModel, propData]);

  const metrics = useMemo(() => ["score", "subscore_avg", "significance", "rigor", "novelty", "clarity"], []);

  if (loading && !data) return <div className="h-40 bg-secondary/20 rounded-lg animate-pulse" />;

  const hasData = data?.status === "ok";
  const availableModels = data?.available_models || [];

  return (
    <div className="mb-10" data-testid="si-rating-section">
      <div className="mb-4 pb-2 border-b border-border">
        <h2 className="font-heading text-lg font-medium flex items-center gap-2">
          <a href="#si-rating" className="flex items-center gap-2 hover:text-accent transition-colors">
          <TrendingUp className="h-4 w-4" />
          Single-Item Rating Analysis
          </a>
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
              {tab.id && <span className="ml-1 text-[10px] opacity-60">({count})</span>}
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
                  <div className="text-[10px] text-muted-foreground">&sigma;={d.std} | {d.min}-{d.max}</div>
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

          {/* Pairwise Tournament vs Single-Item Ranking */}
          {!hidePwVsSi && data.pw_vs_si && Object.keys(data.pw_vs_si.per_model || {}).length > 0 && (
            <div className="mt-6 space-y-4" data-testid="pw-vs-si-section">
              <div className="pb-2 border-b border-border">
                <h3 className="text-sm font-semibold">Pairwise Tournament vs Single-Item Ranking</h3>
                <p className="text-[10px] text-muted-foreground mt-0.5 max-w-2xl">
                  PW ranking correlated against each model's individual SI scores.
                  "Combined" uses all models' matches ({data.pw_vs_si.n_matches?.toLocaleString()}); "Within" uses only that model's own matches.
                </p>
              </div>

              {/* Per-model PW vs SI — combined + within-model */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {["claude", "gpt", "gemini"].map(mk => {
                  const mData = data.pw_vs_si.per_model[mk];
                  if (!mData) return null;
                  const wmData = data.pw_vs_si.within_model?.[mk];
                  const combinedRows = (mData.rows || []).filter(r => r.method !== "raw_wr");
                  const withinRows = (wmData?.rows || []).filter(r => r.method !== "raw_wr");
                  const allRhos = [...combinedRows, ...withinRows].map(r => r.spearman_rho);
                  const bestRho = allRhos.length > 0 ? Math.max(...allRhos) : null;
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
                          {combinedRows.length > 0 && (
                            <tr><td colSpan={4} className="py-0.5 px-2 text-[10px] text-muted-foreground bg-secondary/5 font-medium">Combined PW</td></tr>
                          )}
                          {combinedRows.map(row => (
                            <tr key={`c-${row.method}`} className={`border-b border-border/10 ${row.spearman_rho === bestRho ? "bg-emerald-500/[0.04]" : ""}`}>
                              <td className="py-1 px-2 font-medium">{row.label}</td>
                              <td className={`py-1 px-2 text-right font-mono ${row.spearman_rho === bestRho ? "font-bold text-emerald-700" : "font-semibold"}`}>{row.spearman_rho.toFixed(3)}</td>
                              <td className="py-1 px-2 text-right font-mono">{row.kendall_tau.toFixed(3)}</td>
                              <td className="py-1 px-2 text-right font-mono text-muted-foreground">{row.n}</td>
                            </tr>
                          ))}
                          {withinRows.length > 0 && (
                            <tr><td colSpan={4} className="py-0.5 px-2 text-[10px] text-muted-foreground bg-secondary/5 font-medium">
                              {mData.label.split(" ")[0]}-only PW
                              {wmData?.n_matches ? <span className="ml-1 font-normal">({wmData.n_matches.toLocaleString()} matches)</span> : ""}
                            </td></tr>
                          )}
                          {withinRows.map(row => (
                            <tr key={`w-${row.method}`} className={`border-b border-border/10 ${row.spearman_rho === bestRho ? "bg-emerald-500/[0.04]" : ""}`}>
                              <td className="py-1 px-2 font-medium">{row.label}</td>
                              <td className={`py-1 px-2 text-right font-mono ${row.spearman_rho === bestRho ? "font-bold text-emerald-700" : "font-semibold"}`}>{row.spearman_rho.toFixed(3)}</td>
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
                  <div className="text-[10px] text-muted-foreground">Spearman {"\u03C1"}</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold text-emerald-600">{data.bt_vs_si.kendall_tau}</div>
                  <div className="text-[10px] text-muted-foreground">Kendall {"\u03C4"}</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold text-emerald-600">{data.bt_vs_si.pearson_r}</div>
                  <div className="text-[10px] text-muted-foreground">Pearson r</div>
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
