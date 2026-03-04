import { useState, useEffect } from "react";
import axios from "axios";
import { RotateCcw, Info, BarChart3 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const MODEL_COLORS = { "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b", "Opus 4.5": "#8b5cf6", "Opus 4.6": "#a78bfa" };
const FMT_COLORS = {
  "Abstract": "#ef4444", "Extract": "#f97316", "Full PDF": "#eab308",
  "AI Summary": "#22c55e", "Abs + Sum (4.5)": "#3b82f6", "Abs + Sum (4.6)": "#8b5cf6",
  "Deep Dive": "#06b6d4",
};

const GAP_COLORS = { "Close (<=1)": "#f59e0b", "Medium (1-2)": "#3b82f6", "Far (>2)": "#22c55e" };

export default function AllPairsSection() {
  const [consistency, setConsistency] = useState(null);
  const [aggregate, setAggregate] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/api/validation/consistency-analysis`, { timeout: 120000 }).catch(() => ({ data: {} })),
      axios.get(`${API}/api/validation/cycle-analysis-all`, { timeout: 120000 }).catch(() => ({ data: {} })),
    ]).then(([c, a]) => {
      if (c.data.status === "ok") setConsistency(c.data);
      if (a.data.status === "ok") setAggregate(a.data);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Computing all-pairs analysis across all datasets...</div>;
  if (!consistency && !aggregate) return <div className="text-xs text-muted-foreground text-center py-8">No data available.</div>;

  const cc = consistency?.condorcet_cycles;
  const hm = cc?.heatmap;
  const hmModels = hm?.models || [];
  const hmFormats = hm?.formats || [];

  // Per-model cycle rates by format (grouped bar)
  const cycByFmtGrouped = (hmFormats || []).map(f => {
    const row = { name: f.label };
    let maxTriples = 0;
    for (const mk of hmModels) {
      const cell = hm?.cells?.[`${mk}|${f.id}`];
      if (cell && cell.triples >= 100) {
        row[mk] = cell.rate;
        row[`${mk}_n`] = cell.triples;
        maxTriples = Math.max(maxTriples, cell.triples);
      }
    }
    const fmtAll = cc?.by_format?.[f.label];
    if (fmtAll) {
      row["All (pooled)"] = fmtAll.rate;
      row["All (pooled)_n"] = fmtAll.triples;
    }
    return row;
  }).filter(r => Object.keys(r).length > 2);

  // Aggregate data
  const agg = aggregate;
  const aggModels = agg ? Object.keys(agg.pooled_per_model || {}) : [];
  const datasets = agg ? Object.entries(agg.by_dataset || {}).sort((a, b) => b[1].all_pooled.rate - a[1].all_pooled.rate) : [];

  // Pooled bar data
  const pooledBars = [];
  if (agg) {
    for (const [mk, v] of Object.entries(agg.pooled_per_model || {})) pooledBars.push({ name: mk, ...v });
    pooledBars.push({ name: "Majority", ...agg.pooled_majority });
    pooledBars.push({ name: "Unanimity", ...agg.pooled_unanimity });
  }

  // Gap data
  const gapData = agg ? Object.entries(agg.pooled_all?.by_gap || {}).map(([g, v]) => ({
    name: g === "close" ? "Close (<=1)" : g === "mid" ? "Medium (1-2)" : "Far (>2)",
    rate: v.rate, cycles: v.cycles, triples: v.triples,
  })) : [];

  return (
    <div className="space-y-5" data-testid="all-pairs-analysis">
      {/* Intro */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <RotateCcw className="h-4 w-4" /> All-Pairs Analysis
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Scope:</strong> All match data — every pairwise judgment across all models, formats, and datasets. Maximum statistical power for detecting ranking intransitivity.</p>
          <p><strong>Condorcet cycle:</strong> Three papers (A, B, C) where A &gt; B, B &gt; C, but C &gt; A. Violations of transitivity that inject noise into Bradley-Terry rankings.</p>
        </div>
        {agg && <div className="mt-2 text-[10px] text-muted-foreground">{agg.pooled_all.pairs.toLocaleString()} unique pairs, {agg.pooled_all.triples.toLocaleString()} triples across {agg.datasets} datasets.</div>}
      </div>

      {/* Grouped bar: cycle rate by format × model */}
      {cycByFmtGrouped.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="cycles-by-format-model">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Cycle Rate by Input Format & Model</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">Each model's cycle rate within each format. Hover for triple counts.</div>
          </div>
          <div className="p-3">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={cycByFmtGrouped} barCategoryGap="15%" barGap={1}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-20} textAnchor="end" height={55} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                <Tooltip content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  return (
                    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs max-w-xs">
                      <div className="font-medium mb-1">{label}</div>
                      {payload.map((p, i) => {
                        const n = p.payload[`${p.dataKey}_n`];
                        return (
                          <div key={i} className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full" style={{ background: p.fill }} />
                            <span className="text-muted-foreground">{p.name}:</span>
                            <span className="font-mono font-medium">{p.value}%</span>
                            {n && <span className="text-muted-foreground text-[9px]">({n.toLocaleString()})</span>}
                          </div>
                        );
                      })}
                    </div>
                  );
                }} />
                {hmModels.map(mk => (
                  <Bar key={mk} dataKey={mk} name={mk} fill={MODEL_COLORS[mk] || "#94a3b8"} radius={[2, 2, 0, 0]} />
                ))}
                <Bar dataKey="All (pooled)" name="All (pooled)" fill="#6b7280" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Heatmap: model × format */}
      {hmModels.length > 0 && hmFormats.length > 0 && (() => {
        const colMax = {};
        for (const f of hmFormats) {
          colMax[f.id] = Math.max(...hmModels.map(mk => hm.cells?.[`${mk}|${f.id}`]?.triples || 0), 1);
        }
        return (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-heatmap">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Cycle Rate Heatmap — Model x Format</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">Each cell: cycle rate and triple count. Dimmed = &lt;15% of column max data.</div>
            </div>
            <div className="p-3 overflow-x-auto">
              <table className="text-[11px]">
                <thead>
                  <tr>
                    <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">Model</th>
                    {hmFormats.map(f => (
                      <th key={f.id} className="px-2 py-1.5 text-center font-medium text-muted-foreground min-w-[100px]">{f.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {hmModels.map(mk => (
                    <tr key={mk} className="border-t border-border/30">
                      <td className="px-2 py-2 font-medium">{mk}</td>
                      {hmFormats.map(f => {
                        const cell = hm.cells?.[`${mk}|${f.id}`];
                        if (!cell || cell.triples < 10) return <td key={f.id} className="px-2 py-2 text-center text-muted-foreground/30">—</td>;
                        const low = cell.triples < colMax[f.id] * 0.15;
                        const bg = low ? "transparent" : `rgba(239, 68, 68, ${Math.min(cell.rate / 5, 1) * 0.2})`;
                        return (
                          <td key={f.id} className={`px-2 py-2 text-center font-mono ${low ? "opacity-35" : ""}`} style={{ backgroundColor: bg }}>
                            <div className={cell.rate === 0 ? "text-green-600" : cell.rate < 2 ? "text-amber-600" : "text-red-600"}>
                              {cell.rate}%{low && " *"}
                            </div>
                            <div className="text-[9px] text-muted-foreground font-normal">{cell.cycles}/{cell.triples.toLocaleString()}</div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              {hmModels.some(mk => hmFormats.some(f => {
                const cell = hm.cells?.[`${mk}|${f.id}`];
                return cell && cell.triples >= 10 && cell.triples < colMax[f.id] * 0.15;
              })) && (
                <div className="mt-2 text-[10px] text-amber-600">* Low data — different pair population, not directly comparable.</div>
              )}
              <div className="mt-2 text-[10px] text-muted-foreground border-t border-border/30 pt-2">
                <strong>Reading the heatmap:</strong> Compare cells within each <em>column</em> (same format, different models) for fair model comparisons. Comparing across columns mixes input format effects. Cross-model comparisons across rows are only valid within the same column.
              </div>
            </div>
          </div>
        );
      })()}

      {/* Aggregate: pooled per-model + ensemble bars */}
      {pooledBars.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-pooled-bars">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium flex items-center gap-1.5">
              <BarChart3 className="h-3 w-3" /> Aggregate Cycle Rate by Judge (All Formats Pooled)
            </h3>
            <div className="text-[10px] text-amber-600 mt-0.5">Caution: pools across formats — models with data in different formats are not directly comparable. Use the heatmap above for fair comparisons.</div>
          </div>
          <div className="p-3 space-y-2">
            {(() => {
              const maxRate = Math.max(...pooledBars.map(x => x.rate), 0.5);
              const maxTriples = Math.max(...pooledBars.map(x => x.triples || 0), 1);
              return pooledBars.map(r => {
                const isEnsemble = r.name === "Majority" || r.name === "Unanimity";
                const color = MODEL_COLORS[r.name] || (r.name === "Majority" ? "#22c55e" : r.name === "Unanimity" ? "#06b6d4" : "#94a3b8");
                const low = !isEnsemble && (r.triples || 0) < maxTriples * 0.15;
                return (
                  <div key={r.name} className={`flex items-center gap-3 ${low ? "opacity-35" : ""}`}>
                    <div className={`w-28 text-right text-[11px] ${isEnsemble ? "font-semibold" : "text-muted-foreground"}`}>{r.name}</div>
                    <div className="flex-1 flex items-center gap-2">
                      <div className="flex-1 h-5 bg-secondary/30 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.max((r.rate / (maxRate * 1.3)) * 100, r.rate > 0 ? 3 : 0)}%`, backgroundColor: color }} />
                      </div>
                      <div className="w-52 text-[11px] font-mono">
                        <span className={r.rate === 0 ? "text-green-600 font-semibold" : r.rate < 1 ? "text-amber-600" : "text-red-600"}>{r.rate}%</span>
                        <span className="text-muted-foreground ml-1.5">{r.cycles}/{r.triples?.toLocaleString()}</span>
                        {low && <span className="text-[9px] text-amber-500 ml-1">*</span>}
                      </div>
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        </div>
      )}

      {/* Gap analysis */}
      {gapData.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-gap">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Cycle Rate by GT Score Gap</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">Max score gap between papers in each triple. Close papers = harder to rank = more cycles.</div>
          </div>
          <div className="p-3">
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={gapData} barCategoryGap="30%">
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                <Tooltip content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0];
                  return (
                    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
                      <div className="font-medium">{label}</div>
                      <div className="font-mono">{p.value}% ({p.payload.cycles}/{p.payload.triples.toLocaleString()})</div>
                    </div>
                  );
                }} />
                <Bar dataKey="rate" name="Cycle Rate" radius={[4, 4, 0, 0]}>
                  {gapData.map((e, i) => <Cell key={i} fill={GAP_COLORS[e.name] || "#94a3b8"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Per-dataset table */}
      {datasets.length > 0 && (
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
                  {aggModels.map(mk => <th key={mk} className="text-right px-1.5 py-1.5 font-medium">{mk}</th>)}
                  <th className="text-right px-1.5 py-1.5 font-medium">Majority</th>
                  <th className="text-right px-1.5 py-1.5 font-medium">Unanim.</th>
                  <th className="text-right px-1.5 py-1.5 font-medium">All</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map(([dsId, v]) => {
                  const maxP = Math.max(...aggModels.map(mk => v.per_model?.[mk]?.pairs || 0), 1);
                  return (
                    <tr key={dsId} className="border-b border-border/30 hover:bg-secondary/10">
                      <td className="px-2 py-1 font-medium max-w-[180px] truncate" title={v.name}>{v.name}</td>
                      <td className="text-right px-1.5 py-1 font-mono text-muted-foreground">{v.total_pairs}</td>
                      {aggModels.map(mk => {
                        const m = v.per_model?.[mk];
                        const low = m && m.pairs > 0 && m.pairs < maxP * 0.15;
                        return (
                          <td key={mk} className={`text-right px-1.5 py-1 font-mono ${low ? "opacity-40" : ""}`}
                              title={m ? `${m.pairs} pairs, ${m.triples} triples` : ""}>
                            {m ? <span className={m.rate === 0 ? "text-green-600" : m.rate < 2 ? "text-amber-600" : "text-red-600"}>{m.rate}%</span>
                               : <span className="text-muted-foreground/40">—</span>}
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
                  );
                })}
                {agg && (
                  <tr className="border-t-2 border-border bg-secondary/10 font-semibold">
                    <td className="px-2 py-1.5">Pooled ({agg.datasets})</td>
                    <td className="text-right px-1.5 py-1.5 font-mono">{agg.pooled_all.pairs}</td>
                    {aggModels.map(mk => {
                      const v = agg.pooled_per_model[mk];
                      return <td key={mk} className="text-right px-1.5 py-1.5 font-mono"><span className={v.rate < 1 ? "text-green-600" : "text-amber-600"}>{v.rate}%</span></td>;
                    })}
                    <td className="text-right px-1.5 py-1.5 font-mono"><span className={agg.pooled_majority.rate < 0.1 ? "text-green-600" : "text-amber-600"}>{agg.pooled_majority.rate}%</span></td>
                    <td className="text-right px-1.5 py-1.5 font-mono"><span className="text-green-600">{agg.pooled_unanimity.rate}%</span></td>
                    <td className="text-right px-1.5 py-1.5 font-mono text-amber-600">{agg.pooled_all.rate}%</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Same-Pair Cycle Analysis ── */}
      {consistency?.verdict_stability?.normalized_comparison && Object.keys(consistency.verdict_stability.normalized_comparison).length >= 2 && (() => {
        const vs = consistency.verdict_stability;
        const nc = vs.normalized_comparison;
        const models = Object.entries(nc).sort((a, b) => a[1].adjusted_rate - b[1].adjusted_rate);
        const maxRate = Math.max(...models.map(([, v]) => v.adjusted_rate), 0.5);
        const sharedTriples = models[0]?.[1]?.triples || 0;

        return (
          <div className="border-2 border-blue-200 rounded-lg overflow-hidden bg-blue-50/10" data-testid="same-pair-cycles">
            <div className="px-3 py-2 bg-blue-100/30 border-b border-blue-200">
              <h3 className="text-xs font-medium flex items-center gap-1.5 text-blue-900">
                <RotateCcw className="h-3.5 w-3.5" /> Same-Pair Cycle Rates — Adjusted for Input Format + Summarizer
              </h3>
              <div className="text-[10px] text-blue-700 mt-0.5">
                <strong>Controlled comparison:</strong> All models on the same {sharedTriples.toLocaleString()} triples (pairs evaluated by multiple models). <strong>Adjusted rate</strong> compensates for each model's input mix. Unlike the tables above, this analysis restricts to pairs with overlapping judgments for a fair comparison.
              </div>
            </div>
            <div className="p-3">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border text-[10px]">
                    <th className="text-left py-1.5 pr-3 font-medium">Model</th>
                    <th className="text-right py-1.5 px-2 font-medium">Cycles</th>
                    <th className="text-right py-1.5 px-2 font-medium">Triples</th>
                    <th className="text-right py-1.5 px-2 font-medium">Raw Rate</th>
                    <th className="text-right py-1.5 px-2 font-medium">Adj. Factor</th>
                    <th className="text-right py-1.5 px-2 font-medium">Adjusted Rate</th>
                    <th className="text-left py-1.5 px-2 font-medium">Raw 95% CI</th>
                    <th className="py-1.5 px-2 font-medium w-1/5"></th>
                  </tr>
                </thead>
                <tbody>
                  {models.map(([mk, v]) => {
                    const color = MODEL_COLORS[mk] || "#94a3b8";
                    return (
                      <tr key={mk} className="border-b border-border/30">
                        <td className="py-2 pr-3 font-medium">{mk}</td>
                        <td className="text-right py-2 px-2 font-mono">{v.cycles}</td>
                        <td className="text-right py-2 px-2 font-mono text-muted-foreground">{v.triples.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 font-mono text-muted-foreground">{v.raw_rate}%</td>
                        <td className="text-right py-2 px-2 font-mono text-muted-foreground text-[10px]">{v.adjustment_factor}x</td>
                        <td className="text-right py-2 px-2 font-mono">
                          <span className={v.adjusted_rate < 0.5 ? "text-green-600 font-semibold" : v.adjusted_rate < 2 ? "text-amber-600" : "text-red-600"}>
                            {v.adjusted_rate}%
                          </span>
                        </td>
                        <td className="py-2 px-2 font-mono text-[10px] text-muted-foreground">[{v.ci[0]}%, {v.ci[1]}%]</td>
                        <td className="py-2 px-2">
                          <div className="h-3 bg-secondary/30 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${Math.max((v.adjusted_rate / (maxRate * 1.3)) * 100, v.adjusted_rate > 0 ? 3 : 0)}%`, backgroundColor: color }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {consistency?.verdict_stability?.judge_summarizer && Object.keys(consistency.verdict_stability.judge_summarizer).length > 0 && (() => {
        const js = consistency.verdict_stability.judge_summarizer;
        const allEntries = Object.values(js).filter(v => typeof v === "object" && v.triples > 0);
        const judges = [...new Set(allEntries.map(v => v.judge))].sort();
        const summarizers = [...new Set(allEntries.map(v => v.summarizer))].sort();
        const maxRate = Math.max(...allEntries.map(v => v.rate), 0.5);

        return (
          <div className="border-2 border-blue-200 rounded-lg overflow-hidden bg-blue-50/10" data-testid="same-pair-judge-summarizer">
            <div className="px-3 py-2 bg-blue-100/30 border-b border-blue-200">
              <h3 className="text-xs font-medium flex items-center gap-1.5 text-blue-900">
                <BarChart3 className="h-3.5 w-3.5" /> Same-Pair: Judge × Summarizer Cycle Breakdown
              </h3>
              <div className="text-[10px] text-blue-700 mt-0.5">
                <strong>Controlled comparison:</strong> Disentangles the judge effect from the summarizer effect. Compare rows <em>within</em> a judge (same judge, different summarizer) to isolate the summarizer effect. Compare rows <em>across</em> judges with the same summarizer to isolate the judge effect.
              </div>
            </div>
            <div className="p-3 overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border text-[10px]">
                    <th className="text-left py-1.5 pr-2 font-medium">Judge Model</th>
                    <th className="text-left py-1.5 px-2 font-medium">Summarizer</th>
                    <th className="text-right py-1.5 px-2 font-medium">Pairs</th>
                    <th className="text-right py-1.5 px-2 font-medium">Cycles/Triples</th>
                    <th className="text-right py-1.5 px-2 font-medium">Rate</th>
                    <th className="py-1.5 px-2 w-1/5"></th>
                  </tr>
                </thead>
                <tbody>
                  {judges.map((judge, ji) => {
                    const rows = summarizers
                      .map(s => js[`${judge}|${s}`])
                      .filter(v => v && v.triples > 0)
                      .sort((a, b) => b.triples - a.triples);
                    if (!rows.length) return null;
                    const color = MODEL_COLORS[judge] || "#94a3b8";
                    return rows.map((r, ri) => (
                      <tr key={`${judge}-${r.summarizer}`} className={`border-b border-border/30 ${ji > 0 && ri === 0 ? "border-t border-border" : ""} ${r.is_self ? "bg-blue-50/50" : ""}`}>
                        {ri === 0 && <td className="py-1.5 pr-2 font-medium" rowSpan={rows.length}>{judge}</td>}
                        <td className="py-1.5 px-2 text-muted-foreground">
                          {r.summarizer}
                          {r.is_self && <span className="ml-1 text-[9px] text-blue-500 font-medium">SELF</span>}
                        </td>
                        <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{r.pairs.toLocaleString()}</td>
                        <td className="text-right py-1.5 px-2 font-mono text-[10px] text-muted-foreground">{r.cycles}/{r.triples.toLocaleString()}</td>
                        <td className="text-right py-1.5 px-2 font-mono">
                          <span className={r.rate < 0.5 ? "text-green-600 font-semibold" : r.rate < 1.5 ? "text-amber-600" : "text-red-600"}>
                            {r.rate}%
                          </span>
                        </td>
                        <td className="py-1.5 px-2">
                          <div className="h-2.5 bg-secondary/30 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${Math.max((r.rate / (maxRate * 1.2)) * 100, r.rate > 0 ? 2 : 0)}%`, backgroundColor: color }} />
                          </div>
                        </td>
                      </tr>
                    ));
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Scope:</strong> ALL match data — no same-pair restriction. Every pairwise judgment contributes.</li>
          <li><strong>Per (model, format):</strong> Cycle rate using only that model's judgments under that format. Three judgments in each triple come from the same context.</li>
          <li><strong>All (pooled):</strong> Per pair, take majority vote across all models and formats. Maximum data, but mixes contexts.</li>
          <li><strong>Majority/Unanimity:</strong> Computed on 3-model pairs only (pairs where all 3 judge families evaluated the pair).</li>
          <li><strong>Per-dataset table:</strong> Same analysis per dataset. Dimmed cells = low pair coverage (&lt;15% of column max).</li>
        </ul>
      </div>
    </div>
  );
}
