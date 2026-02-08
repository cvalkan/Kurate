import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
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

function ScatterPlot({ data, xModel, yModel, xColor, yColor }) {
  if (!data || data.length === 0) return null;
  const w = 240, h = 240, pad = 30;
  return (
    <div className="p-3 border border-border rounded-lg bg-secondary/10">
      <div className="text-[10px] text-center mb-1">
        <span style={{ color: xColor }} className="font-mono font-medium">{xModel}</span>
        {" vs "}
        <span style={{ color: yColor }} className="font-mono font-medium">{yModel}</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-w-[240px] mx-auto">
        <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="#e5e7eb" strokeWidth="1" />
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#e5e7eb" strokeWidth="1" />
        <line x1={pad} y1={h - pad} x2={w - pad} y2={pad} stroke="#e5e7eb" strokeWidth="0.5" strokeDasharray="4" />
        {[0, 25, 50, 75, 100].map(v => {
          const x = pad + (v / 100) * (w - 2 * pad);
          const y = h - pad - (v / 100) * (h - 2 * pad);
          return (<g key={v}>
            <text x={x} y={h - pad + 12} textAnchor="middle" className="text-[8px] fill-muted-foreground">{v}</text>
            <text x={pad - 5} y={y + 3} textAnchor="end" className="text-[8px] fill-muted-foreground">{v}</text>
          </g>);
        })}
        {data.map((d, i) => {
          const cx = pad + (d.x / 100) * (w - 2 * pad);
          const cy = h - pad - (d.y / 100) * (h - 2 * pad);
          return (
            <circle key={i} cx={cx} cy={cy} r={3.5} fill="#3b82f6" fillOpacity={0.5} stroke="#3b82f6" strokeWidth={0.5}>
              <title>{d.title}: {d.x}% vs {d.y}%</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}

function CorrelationSection({ sectionData, title, description }) {
  if (!sectionData || !sectionData.models?.length) {
    return (
      <div className="mb-10 p-6 border border-border rounded-lg text-center text-muted-foreground">
        <p className="text-sm font-medium mb-1">{title}</p>
        <p className="text-xs">No data available yet. Run matches to generate analysis.</p>
      </div>
    );
  }

  const { models, correlations, agreement, scatter_data, n_common_papers } = sectionData;
  const corrEntries = Object.entries(correlations);
  const agreeEntries = Object.entries(agreement);
  const scatterPairs = [];
  for (let i = 0; i < models.length; i++) {
    for (let j = i + 1; j < models.length; j++) {
      const m1 = models[i].short;
      const m2 = models[j].short;
      const points = (scatter_data || []).map(d => ({ x: d[m1] || 50, y: d[m2] || 50, title: d.title }));
      scatterPairs.push({ m1, m2, points, c1: getColor(m1).dot, c2: getColor(m2).dot });
    }
  }

  return (
    <div className="mb-10">
      <div className="mb-4 pb-2 border-b border-border">
        <h2 className="font-heading text-lg font-medium">{title}</h2>
        <p className="text-xs text-muted-foreground">{description} Based on {n_common_papers} papers.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        {models.map(m => {
          const c = getColor(m.short);
          return (
            <div key={m.key} className={`p-3 rounded-lg border ${c.border} ${c.bg}`}>
              <div className="flex items-center gap-2 mb-1">
                <Bot className={`h-3.5 w-3.5 ${c.text}`} />
                <span className={`font-mono text-xs font-medium ${c.text}`}>{m.short}</span>
              </div>
              <div className="text-[11px] text-muted-foreground">
                <span className="font-mono text-foreground">{m.total_matches}</span> matches
              </div>
            </div>
          );
        })}
      </div>

      {corrEntries.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-medium mb-2">Rank Correlations</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {corrEntries.map(([pair, stats]) => (
              <div key={pair} className="p-3 rounded-lg border border-border bg-secondary/20">
                <div className="text-[11px] text-muted-foreground mb-2">{pair.replace(" vs ", " ↔ ")}</div>
                <div className="flex items-center gap-3">
                  <div>
                    <div className={`font-mono text-xl font-bold ${stats.spearman_r > 0.7 ? "text-green-600" : stats.spearman_r > 0.4 ? "text-amber-600" : "text-red-600"}`}>
                      {stats.spearman_r.toFixed(2)}
                    </div>
                    <div className="text-[10px] text-muted-foreground">Spearman</div>
                  </div>
                  <div>
                    <div className="font-mono text-sm text-muted-foreground">{stats.pearson_r.toFixed(2)}</div>
                    <div className="text-[10px] text-muted-foreground">Pearson</div>
                  </div>
                  <div className="text-[10px] text-muted-foreground">n={stats.n_papers}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {agreeEntries.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-medium mb-2">Pairwise Agreement</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {agreeEntries.map(([pair, stats]) => {
              const clear = stats.clear_cut || {};
              const contested = stats.contested || {};
              return (
                <div key={pair} className="p-3 rounded-lg border border-border bg-secondary/20">
                  <div className="text-[11px] text-muted-foreground mb-2">{pair.replace(" vs ", " ↔ ")}</div>
                  <div className="flex items-center gap-3 mb-2">
                    <div className="font-mono text-xl font-bold">{stats.rate}%</div>
                    <div className="text-[11px] text-muted-foreground">
                      <div className="flex items-center gap-1"><CheckCircle2 className="h-2.5 w-2.5 text-green-600" />{stats.agree}</div>
                      <div className="flex items-center gap-1"><XCircle className="h-2.5 w-2.5 text-red-500" />{stats.disagree}</div>
                    </div>
                  </div>
                  {(clear.total > 0 || contested.total > 0) && (
                    <div className="border-t border-border/50 pt-1.5 space-y-0.5">
                      {clear.total > 0 && <div className="flex justify-between text-[10px]"><span className="text-muted-foreground">Clear-cut</span><span className="font-mono text-green-600">{clear.rate}% ({clear.agree}/{clear.total})</span></div>}
                      {contested.total > 0 && <div className="flex justify-between text-[10px]"><span className="text-muted-foreground">Contested</span><span className={`font-mono ${contested.rate >= 50 ? "text-amber-600" : "text-red-500"}`}>{contested.rate}% ({contested.agree}/{contested.total})</span></div>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {scatterPairs.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-2">Win Rate Scatter</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {scatterPairs.map(({ m1, m2, points, c1, c2 }, i) => (
              <ScatterPlot key={i} data={points} xModel={m1} yModel={m2} xColor={c1} yColor={c2} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function CorrelationPage() {
  const [data, setData] = useState(null);
  const [predAbsData, setPredAbsData] = useState(null);
  const [predFtData, setPredFtData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");

  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      const cats = res.data.categories || [];
      setCategories([{ id: "", name: "All Categories" }, ...cats]);
      setCategory("");
    }).catch(() => setCategory(""));
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const params = category ? { category } : {};
      const [stdRes, predAbsRes, predFtRes] = await Promise.all([
        axios.get(`${API}/api/model-correlation`, { params }),
        axios.get(`${API}/api/model-correlation`, { params: { ...params, mode: "prediction" } }),
        axios.get(`${API}/api/model-correlation`, { params: { ...params, mode: "prediction-fulltext" } }),
      ]);
      setData(stdRes.data);
      setPredAbsData(predAbsRes.data);
      setPredFtData(predFtRes.data);
    } catch (err) {
      console.error("Failed to fetch correlation data:", err);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

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

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          Model Correlation
        </h1>
        <p className="text-muted-foreground text-sm max-w-2xl">
          How well do GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro agree on paper rankings across different evaluation modes?
        </p>
      </div>

      {categories.length > 1 && (
        <div className="flex items-center gap-1 mb-6 p-1 bg-primary/5 rounded-lg w-fit" data-testid="corr-cat-tabs">
          {categories.map((c) => (
            <Button
              key={c.id}
              variant={category === c.id ? "default" : "ghost"}
              size="sm"
              onClick={() => { setCategory(c.id); setLoading(true); }}
              className="text-xs h-8"
            >
              {c.name}
            </Button>
          ))}
        </div>
      )}

      <CorrelationSection
        sectionData={data}
        title="Standard Tournament"
        description='Full-text evaluation: "Which paper has higher scientific impact?"'
      />

      <CorrelationSection
        sectionData={predAbsData}
        title="Prediction Tournament (Abstract Only)"
        description='Abstract-only: "Which paper would the scientific crowd consider more impactful?"'
      />

      <CorrelationSection
        sectionData={predFtData}
        title="Prediction Tournament (Full Text)"
        description='Full-text with prediction prompt: "Which paper would the crowd consider more impactful?"'
      />

      <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
        <span className="font-medium">Note:</span> Standard tournament uses adaptive matchmaking (biased toward contested pairs).
        Prediction tournaments use uniform random pairing for unbiased coverage.
      </div>
    </div>
  );
}
