import { useState, useEffect } from "react";
import axios from "axios";
import { RotateCcw, Info, BarChart3 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const MODEL_COLORS = {
  "Claude Opus": "#8b5cf6", "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b",
};

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

export default function CycleAnalysisSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/cycle-analysis-all`, { timeout: 60000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(e => console.warn("Cycle analysis error:", e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Loading cycle analysis across all datasets...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No cycle data available.</div>;

  // Pooled per-model bar chart
  const pooledModels = Object.entries(data.pooled_per_model || {}).map(([name, v]) => ({ name, rate: v.rate, ...v }));
  pooledModels.push({ name: "Majority", ...data.pooled_majority });
  pooledModels.push({ name: "Unanimity", ...data.pooled_unanimity });

  // Per-dataset table sorted by all-pooled rate
  const datasets = Object.entries(data.by_dataset || {}).sort((a, b) => b[1].all_pooled.rate - a[1].all_pooled.rate);

  // Per-dataset chart: one grouped bar per dataset, bars for each model + majority + unanimity
  const modelNames = Object.keys(data.pooled_per_model || {});
  const dsChartData = datasets.map(([dsId, v]) => {
    const row = { name: v.name.replace("ICLR ", "").replace("eLife ", "e:").replace("PeerRead ", "PR:") };
    for (const mk of modelNames) {
      row[mk] = v.per_model?.[mk]?.rate ?? 0;
    }
    row["Majority"] = v.majority?.rate ?? 0;
    row["Unanimity"] = v.unanimity?.rate ?? 0;
    row["All Pooled"] = v.all_pooled?.rate ?? 0;
    return row;
  });

  const gapData = Object.entries(data.pooled_all?.by_gap || {}).map(([g, v]) => ({
    name: g === "close" ? "Close (≤1)" : g === "mid" ? "Medium (1-2)" : "Far (>2)",
    rate: v.rate, cycles: v.cycles, triples: v.triples,
  }));

  return (
    <div className="space-y-5" data-testid="cycle-analysis-all">
      {/* Experiment design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <RotateCcw className="h-4 w-4" /> Intransitive Cycle Analysis
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> How often do AI pairwise judgments form inconsistent loops (A beats B, B beats C, but C beats A)?</p>
          <p><strong>Method:</strong> For every triple of papers where all 3 pairwise comparisons exist, check if the preferences form a cycle. Report the cycle rate per model, majority vote (2/3+), and unanimity (3/3).</p>
          <p><strong>Why it matters:</strong> Cycles indicate the ranking is not fully transitive — Bradley-Terry assumes transitivity, so cycles add noise. Lower cycle rate = more coherent, trustworthy ranking.</p>
        </div>
      </div>

      {/* Pooled headline stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center" data-testid="cycle-pooled-stats">
        <div className="p-3 border border-border rounded">
          <div className="text-[10px] text-muted-foreground">Datasets</div>
          <div className="text-xl font-semibold font-mono">{data.datasets}</div>
        </div>
        <div className="p-3 border border-border rounded">
          <div className="text-[10px] text-muted-foreground">All-Pooled Cycle Rate</div>
          <div className="text-xl font-semibold font-mono text-amber-600">{data.pooled_all.rate}%</div>
          <div className="text-[10px] text-muted-foreground">{data.pooled_all.cycles.toLocaleString()}/{data.pooled_all.triples.toLocaleString()} triples</div>
        </div>
        <div className="p-3 border border-border rounded">
          <div className="text-[10px] text-muted-foreground">Majority Cycle Rate</div>
          <div className={`text-xl font-semibold font-mono ${data.pooled_majority.rate === 0 ? "text-green-600" : "text-amber-600"}`}>{data.pooled_majority.rate}%</div>
          <div className="text-[10px] text-muted-foreground">{data.pooled_majority.cycles}/{data.pooled_majority.triples} triples</div>
        </div>
        <div className="p-3 border border-border rounded">
          <div className="text-[10px] text-muted-foreground">Unanimity Cycle Rate</div>
          <div className={`text-xl font-semibold font-mono ${data.pooled_unanimity.rate === 0 ? "text-green-600" : "text-amber-600"}`}>{data.pooled_unanimity.rate}%</div>
          <div className="text-[10px] text-muted-foreground">{data.pooled_unanimity.cycles}/{data.pooled_unanimity.triples} triples</div>
        </div>
      </div>

      {/* Pooled per-model/ensemble bar chart */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-pooled-chart">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <BarChart3 className="h-3 w-3" /> Cycle Rate by Judge (Pooled Across {data.datasets} Datasets)
          </h3>
        </div>
        <div className="p-3">
          {(() => {
            const maxTriples = Math.max(...pooledModels.map(x => x.triples || 0), 1);
            const maxRate = Math.max(...pooledModels.map(x => x.rate), 0.5);
            return (
              <div className="space-y-2">
                {pooledModels.map(r => {
                  const isEnsemble = r.name === "Majority" || r.name === "Unanimity";
                  const color = MODEL_COLORS[r.name] || (r.name === "Majority" ? "#22c55e" : r.name === "Unanimity" ? "#06b6d4" : "#94a3b8");
                  const lowCoverage = !isEnsemble && r.triples < maxTriples * 0.15;
                  return (
                    <div key={r.name} className={`flex items-center gap-3 ${lowCoverage ? "opacity-50" : ""}`}>
                      <div className={`w-28 text-right text-[11px] ${isEnsemble ? "font-semibold" : "text-muted-foreground"}`}>{r.name}</div>
                      <div className="flex-1 flex items-center gap-2">
                        <div className="flex-1 h-5 bg-secondary/30 rounded-full overflow-hidden">
                          <div className="h-full rounded-full transition-all" style={{
                            width: `${Math.max((r.rate / (maxRate * 1.3)) * 100, r.rate > 0 ? 3 : 0)}%`,
                            backgroundColor: color,
                          }} />
                        </div>
                        <div className="w-52 text-[11px] font-mono flex items-center gap-1.5">
                          <span className={r.rate === 0 ? "text-green-600 font-semibold" : r.rate < 1 ? "text-amber-600" : "text-red-600"}>
                            {r.rate}%
                          </span>
                          <span className="text-muted-foreground">{r.cycles}/{r.triples}</span>
                          {lowCoverage && <span className="text-[9px] text-amber-500 font-sans" title="Low pair coverage — different pair population, not directly comparable">*</span>}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}
          {pooledModels.some(r => !["Majority", "Unanimity"].includes(r.name) && r.triples < Math.max(...pooledModels.map(x => x.triples || 0)) * 0.15) && (
            <div className="mt-2 text-[10px] text-amber-600 flex items-start gap-1">
              <span>*</span>
              <span>Low pair coverage — evaluated on a different (smaller) set of pairs than other models. Not directly comparable; the rate difference may reflect selection bias rather than model behavior.</span>
            </div>
          )}
        </div>
      </div>

      {/* Gap analysis */}
      {gapData.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-gap-analysis">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Cycle Rate by GT Score Gap (All Pooled)</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">Max score gap between papers in each triple. Closer papers = harder to rank = more cycles?</div>
          </div>
          <div className="p-3">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={gapData} barCategoryGap="30%">
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="rate" name="Cycle Rate" fill="#f59e0b" radius={[4, 4, 0, 0]}>
                  {gapData.map((_, i) => <Cell key={i} fill={["#f59e0b", "#3b82f6", "#22c55e"][i] || "#94a3b8"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Per-dataset table */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-by-dataset">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Cycle Rates by Dataset</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-background">
              <tr className="border-b border-border text-[10px]">
                <th className="text-left px-2 py-1.5 font-medium">Dataset</th>
                <th className="text-right px-1.5 py-1.5 font-medium">Pairs</th>
                {modelNames.map(mk => (
                  <th key={mk} className="text-right px-1.5 py-1.5 font-medium">{mk}</th>
                ))}
                <th className="text-right px-1.5 py-1.5 font-medium">Majority</th>
                <th className="text-right px-1.5 py-1.5 font-medium">Unanim.</th>
                <th className="text-right px-1.5 py-1.5 font-medium">All Pooled</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(([dsId, v]) => (
                <tr key={dsId} className="border-b border-border/30 hover:bg-secondary/10">
                  <td className="px-2 py-1 font-medium max-w-[180px] truncate" title={v.name}>{v.name}</td>
                  <td className="text-right px-1.5 py-1 font-mono text-muted-foreground">{v.total_pairs}</td>
                  {modelNames.map(mk => {
                    const r = v.per_model?.[mk]?.rate;
                    return (
                      <td key={mk} className="text-right px-1.5 py-1 font-mono">
                        {r != null ? (
                          <span className={r === 0 ? "text-green-600" : r < 2 ? "text-amber-600" : "text-red-600"}>
                            {r}%
                          </span>
                        ) : <span className="text-muted-foreground/40">—</span>}
                      </td>
                    );
                  })}
                  <td className="text-right px-1.5 py-1 font-mono">
                    <span className={v.majority.rate === 0 ? "text-green-600 font-semibold" : "text-amber-600"}>{v.majority.rate}%</span>
                  </td>
                  <td className="text-right px-1.5 py-1 font-mono">
                    <span className={v.unanimity.rate === 0 ? "text-green-600 font-semibold" : "text-amber-600"}>{v.unanimity.rate}%</span>
                  </td>
                  <td className="text-right px-1.5 py-1 font-mono">
                    <span className={v.all_pooled.rate < 2 ? "text-amber-600" : "text-red-600"}>{v.all_pooled.rate}%</span>
                  </td>
                </tr>
              ))}
              {/* Pooled row */}
              <tr className="border-t-2 border-border bg-secondary/10 font-semibold">
                <td className="px-2 py-1.5">Pooled ({data.datasets} datasets)</td>
                <td className="text-right px-1.5 py-1.5 font-mono">{data.pooled_all.pairs}</td>
                {modelNames.map(mk => {
                  const v = data.pooled_per_model[mk];
                  return (
                    <td key={mk} className="text-right px-1.5 py-1.5 font-mono">
                      <span className={v.rate < 1 ? "text-green-600" : "text-amber-600"}>{v.rate}%</span>
                    </td>
                  );
                })}
                <td className="text-right px-1.5 py-1.5 font-mono">
                  <span className={data.pooled_majority.rate < 0.1 ? "text-green-600" : "text-amber-600"}>{data.pooled_majority.rate}%</span>
                </td>
                <td className="text-right px-1.5 py-1.5 font-mono">
                  <span className="text-green-600">{data.pooled_unanimity.rate}%</span>
                </td>
                <td className="text-right px-1.5 py-1.5 font-mono text-amber-600">{data.pooled_all.rate}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="cycle-methodology">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Triple:</strong> Three papers (A, B, C) where all three pairwise comparisons have a verdict.</li>
          <li><strong>Cycle:</strong> A &gt; B, B &gt; C, but C &gt; A (or the reverse direction). Violates transitivity.</li>
          <li><strong>Per-model:</strong> Cycle rate using only that model's verdicts on 3-model pairs.</li>
          <li><strong>Majority:</strong> Winner per pair = the paper 2+ out of 3 models chose.</li>
          <li><strong>Unanimity:</strong> Only pairs where all 3 models agree. Pairs with disagreement dropped.</li>
          <li><strong>All pooled:</strong> Uses majority across all match data (not just 3-model pairs), including all content modes.</li>
          <li><strong>GT score gap:</strong> Maximum human-rating gap between any two papers in the triple.</li>
        </ul>
      </div>
    </div>
  );
}
