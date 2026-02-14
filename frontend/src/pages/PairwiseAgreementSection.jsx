import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Scale, BarChart3, AlertCircle, Play, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, Legend } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const MODE_LABELS = { extract: "Extract", abstract: "Abstract", full_pdf: "Full PDF" };
const MODE_COLORS = { extract: "#3b82f6", abstract: "#8b5cf6", full_pdf: "#f59e0b" };

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
      <div className="font-medium mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill || p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono font-medium">{p.value}%</span>
        </div>
      ))}
    </div>
  );
}

export default function PairwiseAgreementSection({ datasetId, datasetName }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchData = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/cross-mode-agreement`, { params: { dataset_id: datasetId } });
      if (r.data.status === "ok") setData(r.data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [datasetId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div className="text-xs text-muted-foreground py-6 text-center">Loading agreement data...</div>;

  if (!data || data.common_pairs === 0) {
    return (
      <div className="space-y-4">
        <div className="border border-border rounded-lg p-8 text-center" data-testid="pw-agreement-empty">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground mb-2">No cross-mode pairwise data available yet.</p>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            Run tournaments in at least 2 content modes (Abstract, Extract, Full PDF) for this dataset under the Tournament section to enable head-to-head comparison.
          </p>
        </div>
        <MethodologyNote />
      </div>
    );
  }

  // Chart data for AI-Expert agreement
  const expertChartData = [
    { name: "Expert-Expert", ...Object.fromEntries(data.modes_compared.map(m => [m, data.expert_expert.rate])), isBaseline: true },
    ...data.modes_compared.map(mode => ({
      name: MODE_LABELS[mode],
      [mode]: data.by_mode[mode].ai_expert.rate,
    })),
  ];

  // Grouped bar chart data
  const groupedData = data.modes_compared.map(mode => ({
    name: MODE_LABELS[mode],
    "AI-Expert": data.by_mode[mode].ai_expert.rate,
    "AI-Majority": data.by_mode[mode].ai_majority.rate,
    mode,
  }));

  // Disagreement data for chart
  const disagreeData = data.mode_disagreements
    ? Object.entries(data.mode_disagreements).map(([key, d]) => ({
        name: key.split("_vs_").map(k => MODE_LABELS[k] || k).join(" vs "),
        "Same Pick": d.agree,
        "Different Pick": d.differ,
        pct: d.differ_pct,
      }))
    : [];

  return (
    <div className="space-y-5">
      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Common Pairs</div>
          <div className="font-semibold text-base">{data.common_pairs}</div>
        </div>
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Modes Compared</div>
          <div className="font-semibold text-base">{data.modes_compared.length}</div>
        </div>
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Expert-Expert</div>
          <div className="font-semibold text-base text-green-600">{data.expert_expert.rate}%</div>
          <div className="text-[10px] text-muted-foreground">{data.expert_expert.agree}/{data.expert_expert.total}</div>
        </div>
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Best AI-Expert</div>
          <div className="font-semibold text-base text-accent">
            {Math.max(...data.modes_compared.map(m => data.by_mode[m].ai_expert.rate))}%
          </div>
        </div>
      </div>

      {/* Agreement bar chart */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-agreement-chart">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <BarChart3 className="h-3 w-3" /> Agreement Rate by Content Mode
          </h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            Same {data.common_pairs} paper pairs evaluated with each content mode
          </div>
        </div>
        <div className="p-3">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={groupedData} barCategoryGap="25%">
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="AI-Expert" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              <Bar dataKey="AI-Majority" fill="#8b5cf6" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          {/* Expert-Expert baseline line label */}
          <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground justify-center">
            <span className="inline-block w-8 h-px bg-green-500" />
            Expert-Expert baseline: {data.expert_expert.rate}%
          </div>
        </div>
      </div>

      {/* Agreement table */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-agreement-table">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Scale className="h-3 w-3" /> Head-to-Head: {data.common_pairs} Pairs Across All Modes
          </h3>
        </div>
        <div className="p-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1.5 pr-3 text-muted-foreground font-medium">Content Mode</th>
                <th className="text-center py-1.5 px-3 text-muted-foreground font-medium">AI-Expert</th>
                <th className="text-center py-1.5 px-3 text-muted-foreground font-medium">AI-Majority</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border/50">
                <td className="py-1.5 pr-3 text-muted-foreground italic">Expert-Expert</td>
                <td className="text-center py-1.5 px-3 font-mono font-semibold text-green-600">{data.expert_expert.rate}%</td>
                <td className="text-center py-1.5 px-3 text-[10px] text-muted-foreground">baseline</td>
              </tr>
              {data.modes_compared.map(mode => {
                const stats = data.by_mode[mode];
                const best_ae = Math.max(...data.modes_compared.map(m => data.by_mode[m].ai_expert.rate));
                const best_am = Math.max(...data.modes_compared.map(m => data.by_mode[m].ai_majority.rate));
                const ae_color = stats.ai_expert.rate === best_ae ? "text-green-600 font-bold" : stats.ai_expert.rate >= data.expert_expert.rate * 0.9 ? "text-amber-600" : "text-red-500";
                const am_color = stats.ai_majority.rate === best_am ? "text-green-600 font-bold" : "text-amber-600";
                return (
                  <tr key={mode} className="border-b border-border/50 last:border-0">
                    <td className="py-1.5 pr-3 font-medium">{MODE_LABELS[mode]}</td>
                    <td className={`text-center py-1.5 px-3 font-mono font-semibold ${ae_color}`}>
                      {stats.ai_expert.rate}%
                      <span className="text-[9px] text-muted-foreground ml-1">({stats.ai_expert.agree}/{stats.ai_expert.total})</span>
                    </td>
                    <td className={`text-center py-1.5 px-3 font-mono font-semibold ${am_color}`}>
                      {stats.ai_majority.rate}%
                      <span className="text-[9px] text-muted-foreground ml-1">({stats.ai_majority.agree}/{stats.ai_majority.total})</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mode disagreement chart */}
      {disagreeData.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-disagreement-chart">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium flex items-center gap-1.5">
              <BarChart3 className="h-3 w-3" /> AI Pick Overlap Between Modes
            </h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              How often different content modes produce the same AI winner
            </div>
          </div>
          <div className="p-3">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={disagreeData} layout="vertical" barCategoryGap="20%">
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={120} />
                <Tooltip content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0]?.payload;
                  return (
                    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
                      <div className="font-medium mb-1">{d?.name}</div>
                      <div>Same: {d?.["Same Pick"]} &middot; Different: {d?.["Different Pick"]} ({d?.pct}%)</div>
                    </div>
                  );
                }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="Same Pick" stackId="a" fill="#22c55e" radius={[0, 0, 0, 0]} />
                <Bar dataKey="Different Pick" stackId="a" fill="#ef4444" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <MethodologyNote />
    </div>
  );
}

function MethodologyNote() {
  return (
    <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="pw-agreement-methodology">
      <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5">
        <Info className="h-3.5 w-3.5" /> Methodology
      </h3>
      <ul className="text-xs text-muted-foreground space-y-1">
        <li><strong>Apples-to-apples:</strong> Agreement rates are computed on the exact same set of paper pairs across all content modes.</li>
        <li><strong>AI-Expert:</strong> Fraction of pairwise comparisons where AI agrees with each individual human reviewer.</li>
        <li><strong>AI-Majority:</strong> Fraction where AI agrees with the majority vote of human reviewers (pairs with 2+ reviewers only).</li>
        <li><strong>Content modes:</strong> Extract (section-extracted text), Abstract (abstract only), Full PDF (complete paper text).</li>
        <li><strong>Goal:</strong> Determine which input format (abstract, extract, full PDF) gives AI the best agreement with human experts.</li>
      </ul>
    </div>
  );
}
