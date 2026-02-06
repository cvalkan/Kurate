import { useState, useEffect } from "react";
import axios from "axios";
import { Badge } from "@/components/ui/badge";
import { Bot, BarChart3, CheckCircle2, XCircle } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const MODEL_COLORS = {
  "gpt-5.2": { bg: "bg-green-50", text: "text-green-700", border: "border-green-200", dot: "#16a34a" },
  "claude-opus-4-5-20251101": { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200", dot: "#ea580c" },
  "gemini-3-pro-preview": { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", dot: "#2563eb" },
};

function getColor(model) {
  return MODEL_COLORS[model] || { bg: "bg-secondary", text: "text-foreground", border: "border-border", dot: "#64748b" };
}

function CorrelationCell({ value, label }) {
  const abs = Math.abs(value);
  const hue = abs > 0.8 ? "text-green-700 bg-green-50" : abs > 0.5 ? "text-amber-700 bg-amber-50" : "text-red-700 bg-red-50";
  return (
    <div className={`p-3 rounded-lg border border-border text-center ${hue}`} data-testid={`corr-${label}`}>
      <div className="font-mono text-lg font-bold">{value.toFixed(2)}</div>
      <div className="text-[10px] mt-0.5 opacity-70">Spearman r</div>
    </div>
  );
}

function ScatterPlot({ data, xModel, yModel, xColor, yColor }) {
  if (!data.length) return null;
  const w = 280, h = 280, pad = 35;

  return (
    <div className="border border-border rounded-lg p-3 bg-background">
      <div className="text-xs text-muted-foreground mb-2 text-center">
        <span className="font-mono" style={{ color: xColor }}>{xModel}</span>
        {" vs "}
        <span className="font-mono" style={{ color: yColor }}>{yModel}</span>
      </div>
      <svg width={w} height={h} className="mx-auto">
        {/* Grid */}
        <line x1={pad} y1={h - pad} x2={w - 5} y2={h - pad} stroke="#e2e8f0" />
        <line x1={pad} y1={5} x2={pad} y2={h - pad} stroke="#e2e8f0" />
        {[0, 25, 50, 75, 100].map(v => (
          <g key={v}>
            <text x={pad - 4} y={h - pad - (v / 100) * (h - pad - 5)} fontSize="8" fill="#94a3b8" textAnchor="end" dominantBaseline="middle">{v}</text>
            <text x={pad + (v / 100) * (w - pad - 5)} y={h - pad + 12} fontSize="8" fill="#94a3b8" textAnchor="middle">{v}</text>
            <line x1={pad} y1={h - pad - (v / 100) * (h - pad - 5)} x2={w - 5} y2={h - pad - (v / 100) * (h - pad - 5)} stroke="#f1f5f9" />
          </g>
        ))}
        {/* Diagonal */}
        <line x1={pad} y1={h - pad} x2={w - 5} y2={5} stroke="#cbd5e1" strokeDasharray="4 4" />
        {/* Points */}
        {data.map((d, i) => {
          const x = pad + (d.x / 100) * (w - pad - 5);
          const y = h - pad - (d.y / 100) * (h - pad - 5);
          return (
            <circle key={i} cx={x} cy={y} r={3.5} fill="#2563eb" fillOpacity={0.5} stroke="#2563eb" strokeWidth={0.5}>
              <title>{d.title}: {d.x}% vs {d.y}%</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}

export default function CorrelationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await axios.get(`${API}/api/model-correlation`);
        setData(res.data);
      } catch (err) {
        console.error("Failed to fetch correlation data:", err);
      } finally {
        setLoading(false);
      }
    };
    fetch();
  }, []);

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-5xl py-10">
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-secondary/30 rounded-lg animate-pulse" />)}
        </div>
      </div>
    );
  }

  if (!data || !data.models?.length) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-5xl py-10 text-center text-muted-foreground">
        <BarChart3 className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Not enough data for correlation analysis yet.</p>
      </div>
    );
  }

  const { models, correlations, agreement, scatter_data, n_common_papers } = data;
  const corrEntries = Object.entries(correlations);
  const agreeEntries = Object.entries(agreement);

  // Build scatter pairs
  const scatterPairs = [];
  for (let i = 0; i < models.length; i++) {
    for (let j = i + 1; j < models.length; j++) {
      const m1 = models[i].short;
      const m2 = models[j].short;
      const points = scatter_data.map(d => ({ x: d[m1] || 50, y: d[m2] || 50, title: d.title }));
      scatterPairs.push({ m1, m2, points, c1: getColor(m1).dot, c2: getColor(m2).dot });
    }
  }

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          Model Correlation
        </h1>
        <p className="text-muted-foreground text-sm max-w-2xl">
          How well do GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro agree on paper rankings?
          Analysis based on {n_common_papers} papers with sufficient data from all models.
        </p>
      </div>

      {/* Model Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-8" data-testid="model-cards">
        {models.map(m => {
          const c = getColor(m.short);
          return (
            <div key={m.key} className={`p-4 rounded-lg border ${c.border} ${c.bg}`}>
              <div className="flex items-center gap-2 mb-2">
                <Bot className={`h-4 w-4 ${c.text}`} />
                <span className={`font-mono text-sm font-medium ${c.text}`}>{m.short}</span>
              </div>
              <div className="text-xs text-muted-foreground">
                <span className="font-mono text-foreground">{m.total_matches}</span> matches &middot; <span className="font-mono text-foreground">{m.papers_judged}</span> papers judged
              </div>
            </div>
          );
        })}
      </div>

      {/* Rank Correlations */}
      {corrEntries.length > 0 && (
        <div className="mb-8" data-testid="correlations">
          <h2 className="font-heading text-lg font-medium mb-3">Rank Correlations</h2>
          <p className="text-xs text-muted-foreground mb-4">
            Spearman rank correlation of per-paper win rates between models. Values close to 1.0 indicate strong agreement on relative paper quality.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {corrEntries.map(([pair, stats]) => (
              <div key={pair} className="p-4 rounded-lg border border-border bg-secondary/20">
                <div className="text-xs text-muted-foreground mb-2">{pair.replace(" vs ", " ↔ ")}</div>
                <div className="flex items-center gap-4">
                  <div>
                    <div className={`font-mono text-2xl font-bold ${stats.spearman_r > 0.7 ? "text-green-600" : stats.spearman_r > 0.4 ? "text-amber-600" : "text-red-600"}`}>
                      {stats.spearman_r.toFixed(2)}
                    </div>
                    <div className="text-[10px] text-muted-foreground">Spearman r</div>
                  </div>
                  <div>
                    <div className="font-mono text-lg text-muted-foreground">{stats.pearson_r.toFixed(2)}</div>
                    <div className="text-[10px] text-muted-foreground">Pearson r</div>
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    p={stats.spearman_p < 0.001 ? "<0.001" : stats.spearman_p.toFixed(3)}<br />
                    n={stats.n_papers}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agreement Rates */}
      {agreeEntries.length > 0 && (
        <div className="mb-8" data-testid="agreement">
          <h2 className="font-heading text-lg font-medium mb-3">Pairwise Agreement</h2>
          <p className="text-xs text-muted-foreground mb-4">
            When two models judge the same paper pair, how often do they pick the same winner?
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {agreeEntries.map(([pair, stats]) => (
              <div key={pair} className="p-4 rounded-lg border border-border bg-secondary/20">
                <div className="text-xs text-muted-foreground mb-2">{pair.replace(" vs ", " ↔ ")}</div>
                <div className="flex items-center gap-3">
                  <div className="font-mono text-2xl font-bold text-foreground">{stats.rate}%</div>
                  <div className="flex-1 text-xs text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-600" />
                      {stats.agree} agree
                    </div>
                    <div className="flex items-center gap-1">
                      <XCircle className="h-3 w-3 text-red-500" />
                      {stats.disagree} disagree
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scatter Plots */}
      {scatterPairs.length > 0 && (
        <div data-testid="scatter-plots">
          <h2 className="font-heading text-lg font-medium mb-3">Win Rate Scatter Plots</h2>
          <p className="text-xs text-muted-foreground mb-4">
            Each dot is a paper. X/Y axes show win rate (%) as judged by each model. Points near the diagonal indicate agreement.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {scatterPairs.map(({ m1, m2, points, c1, c2 }) => (
              <ScatterPlot key={`${m1}-${m2}`} data={points} xModel={m1} yModel={m2} xColor={c1} yColor={c2} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
