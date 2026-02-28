import { useState, useEffect } from "react";
import axios from "axios";
import { RotateCcw, Shuffle, Info, BarChart3, AlertCircle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
      <div className="font-medium mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill || p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono font-medium">{typeof p.value === "number" ? `${p.value}%` : p.value}</span>
        </div>
      ))}
    </div>
  );
}

const MODEL_COLORS = { "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b", "Opus 4.5": "#8b5cf6", "Opus 4.6": "#a78bfa" };
const FMT_COLORS = {
  "Abstract": "#ef4444", "Extract": "#f97316", "Full PDF": "#eab308",
  "AI Summary": "#22c55e", "Abs + Sum (4.5)": "#3b82f6", "Abs + Sum (4.6)": "#8b5cf6",
  "Deep Dive": "#06b6d4", "Abs + Sum (Thinking)": "#a78bfa",
};

function HBar({ label, rate, sub, maxRate, color = "#3b82f6" }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-48 text-right text-[11px] text-muted-foreground truncate" title={label}>{label}</div>
      <div className="flex-1 h-4 bg-secondary/30 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.max((rate / Math.max(maxRate * 1.2, 1)) * 100, rate > 0 ? 2 : 0)}%`, backgroundColor: color }} />
      </div>
      <div className="w-36 text-[11px] font-mono">
        <span className={rate < 10 ? "text-green-600" : rate < 18 ? "text-amber-600" : "text-red-600"}>{rate}%</span>
        {sub && <span className="text-muted-foreground ml-1">{sub}</span>}
      </div>
    </div>
  );
}

export default function ConsistencySection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/consistency-analysis`, { timeout: 120000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(e => console.warn("Consistency analysis error:", e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Computing consistency analysis across all datasets...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No data available.</div>;

  const vs = data.verdict_stability;
  const cc = data.condorcet_cycles;

  // Build heatmap data
  const hm = cc.heatmap;
  const hmModels = hm?.models || [];
  const hmFormats = hm?.formats || [];

  // Cross-format by model chart
  const cfByModel = Object.entries(vs.cross_format.by_model || {}).map(([mk, v]) => ({ name: mk, rate: v.rate, ...v }));
  // Cross-model by format chart  
  const cmByFmt = Object.entries(vs.cross_model.by_format || {}).sort((a, b) => b[1].rate - a[1].rate).map(([fmt, v]) => ({ name: fmt, rate: v.rate, ...v }));
  // Cycle by format - build grouped data with per-model breakdown from heatmap
  const cycByFmt = Object.entries(cc.by_format || {}).sort((a, b) => b[1].rate - a[1].rate).map(([fmt, v]) => ({ name: fmt, rate: v.rate, ...v }));

  // Per-model cycle rates by format (from heatmap cells)
  const cycByFmtGrouped = (hm?.formats || []).map(f => {
    const row = { name: f.label };
    let maxTriples = 0;
    for (const mk of hmModels) {
      const cell = hm.cells?.[`${mk}|${f.id}`];
      if (cell && cell.triples >= 100) {
        row[mk] = cell.rate;
        row[`${mk}_n`] = cell.triples;
        maxTriples = Math.max(maxTriples, cell.triples);
      }
    }
    // Mark low-coverage entries
    for (const mk of hmModels) {
      if (row[`${mk}_n`] && row[`${mk}_n`] < maxTriples * 0.15) {
        row[`${mk}_low`] = true;
      }
    }
    const fmtAll = cc.by_format?.[f.label];
    if (fmtAll) {
      row["All (pooled)"] = fmtAll.rate;
      row["All (pooled)_n"] = fmtAll.triples;
    }
    return row;
  }).filter(r => Object.keys(r).length > 2);

  return (
    <div className="space-y-6" data-testid="consistency-analysis">
      {/* Overview */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <RotateCcw className="h-4 w-4" /> Ranking Consistency Analysis
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p>Two types of inconsistency can undermine AI tournament rankings:</p>
          <p><strong>1. Verdict instability:</strong> The same pair of papers gets different winners when the judge model or input format changes. Measured as the <em>flip rate</em> — the fraction of same-pair evaluations that disagree.</p>
          <p><strong>2. Condorcet cycles:</strong> Three papers form an intransitive loop (A &gt; B &gt; C &gt; A). This violates the transitivity assumption of Bradley-Terry and injects noise into rankings. Measured per (model, format) context.</p>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">
          {data.total_matches.toLocaleString()} matches across {data.datasets} datasets.
        </div>
      </div>

      {/* ═══ SECTION 1: VERDICT STABILITY ═══ */}
      <div className="border-l-2 border-amber-400 pl-4">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
          <Shuffle className="h-4 w-4 text-amber-500" /> Verdict Stability — Same-Pair Flip Rates
        </h2>

        {/* Cross-format: which format pairs disagree most? */}
        <div className="space-y-4">
          <div className="border border-border rounded-lg overflow-hidden" data-testid="cross-format-flips">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Cross-Format Flips (same model, same pair, different input format)</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">How often does changing the input format flip the verdict?</div>
            </div>
            <div className="p-3 space-y-1.5">
              {Object.entries(vs.cross_format.by_format_pair || {}).slice(0, 12).map(([k, v]) => (
                <HBar key={k} label={k} rate={v.rate} sub={`${v.flips}/${v.total}`}
                  maxRate={Math.max(...Object.values(vs.cross_format.by_format_pair || {}).map(x => x.rate))} color="#f59e0b" />
              ))}
            </div>
          </div>

          {/* Cross-format: which model is most format-sensitive? */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="cross-format-by-model">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Format Sensitivity by Model</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">Which model changes its mind most when the input format changes?</div>
            </div>
            <div className="p-3">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={cfByModel} barCategoryGap="25%">
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="rate" name="Flip Rate" radius={[4, 4, 0, 0]}>
                    {cfByModel.map((e, i) => <Cell key={i} fill={MODEL_COLORS[e.name] || "#94a3b8"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Cross-model: which model pairs disagree most? */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="cross-model-flips">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Cross-Model Flips (same format, same pair, different model)</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">How often do two models disagree on the same pair under the same format?</div>
            </div>
            <div className="p-3 space-y-1.5">
              {Object.entries(vs.cross_model.by_model_pair || {}).map(([k, v]) => (
                <HBar key={k} label={k} rate={v.rate} sub={`${v.flips}/${v.total}`}
                  maxRate={Math.max(...Object.values(vs.cross_model.by_model_pair || {}).map(x => x.rate))} color="#8b5cf6" />
              ))}
            </div>
          </div>

          {/* Cross-model: which format has most model disagreement? */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="cross-model-by-format">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Model Disagreement by Format</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">Under which input format do models disagree most?</div>
            </div>
            <div className="p-3">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={cmByFmt} barCategoryGap="20%">
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-20} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="rate" name="Model Disagreement" radius={[4, 4, 0, 0]}>
                    {cmByFmt.map((e, i) => <Cell key={i} fill={FMT_COLORS[e.name] || "#94a3b8"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ SECTION 2: CONDORCET CYCLES ═══ */}
      <div className="border-l-2 border-red-400 pl-4">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
          <RotateCcw className="h-4 w-4 text-red-500" /> Condorcet Cycles — Ranking Intransitivity
        </h2>

        {/* Cycle rate by format */}
        <div className="space-y-4">
          <div className="border border-border rounded-lg overflow-hidden" data-testid="cycles-by-format">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Cycle Rate by Input Format &amp; Model</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">Each model's cycle rate within each format, plus the all-models-pooled rate. All computed within-dataset, then pooled across datasets.</div>
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
                          const nKey = `${p.dataKey}_n`;
                          const n = p.payload[nKey];
                          return (
                            <div key={i} className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full" style={{ background: p.fill }} />
                              <span className="text-muted-foreground">{p.name}:</span>
                              <span className="font-mono font-medium">{p.value}%</span>
                              {n && <span className="text-muted-foreground text-[9px]">({n.toLocaleString()} triples)</span>}
                            </div>
                          );
                        })}
                      </div>
                    );
                  }} />
                  {hmModels.map((mk, i) => (
                    <Bar key={mk} dataKey={mk} name={mk} fill={MODEL_COLORS[mk] || "#94a3b8"} radius={[2, 2, 0, 0]} />
                  ))}
                  <Bar dataKey="All (pooled)" name="All (pooled)" fill="#6b7280" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Heatmap: model x format */}
          {hmModels.length > 0 && hmFormats.length > 0 && (() => {
            // Find max triples per column to detect low-coverage cells
            const colMax = {};
            for (const f of hmFormats) {
              colMax[f.id] = Math.max(...hmModels.map(mk => hm.cells?.[`${mk}|${f.id}`]?.triples || 0), 1);
            }
            return (
            <div className="border border-border rounded-lg overflow-hidden" data-testid="cycle-heatmap">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium">Cycle Rate Heatmap — Model x Format</h3>
                <div className="text-[10px] text-muted-foreground mt-0.5">Each cell: cycle rate and triple count. Dimmed cells have &lt;15% of the column's max data — not directly comparable.</div>
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
                          if (!cell || cell.triples < 10) {
                            return <td key={f.id} className="px-2 py-2 text-center text-muted-foreground/30">—</td>;
                          }
                          const lowCoverage = cell.triples < colMax[f.id] * 0.15;
                          const intensity = Math.min(cell.rate / 5, 1);
                          const bg = lowCoverage ? "transparent" : `rgba(239, 68, 68, ${intensity * 0.2})`;
                          return (
                            <td key={f.id} className={`px-2 py-2 text-center font-mono ${lowCoverage ? "opacity-35" : ""}`} style={{ backgroundColor: bg }}>
                              <div className={cell.rate === 0 ? "text-green-600" : cell.rate < 2 ? "text-amber-600" : "text-red-600"}>
                                {cell.rate}%{lowCoverage && " *"}
                              </div>
                              <div className="text-[9px] text-muted-foreground font-normal">
                                {cell.cycles}/{cell.triples.toLocaleString()}
                              </div>
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
                  <div className="mt-2 text-[10px] text-amber-600">
                    * Low data volume — different pair population than other models in this column. Rate may reflect selection bias.
                  </div>
                )}
              </div>
            </div>
            );
          })()}
        </div>
      </div>

      {/* ═══ METHODOLOGY ═══ */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="consistency-methodology">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Verdict flip:</strong> Same paper pair, evaluated by the same model under two different formats (or same format by two different models) — how often does the winner change?</li>
          <li><strong>Condorcet cycle:</strong> Three papers (A, B, C) where A &gt; B, B &gt; C, but C &gt; A. Checked within each (model, format) context so all three judgments come from the same conditions.</li>
          <li><strong>Heatmap:</strong> Each cell is a single (model, format) combination with its own cycle rate. Only shown when &ge; 10 triples exist. Cells are independent — no mixing of models or formats.</li>
          <li><strong>Format labels:</strong> Abstract = abstract only; Extract = section extraction from PDF; Full PDF = full text; AI Summary = pre-generated impact assessment; Abs + Sum = abstract + AI summary.</li>
          <li><strong>Cross-format insight:</strong> Abstract and Extract have the highest model disagreement — more text does not always mean more agreement. AI Summary has the lowest inter-model disagreement.</li>
        </ul>
      </div>
    </div>
  );
}
