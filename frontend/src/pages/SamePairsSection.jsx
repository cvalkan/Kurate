import { useState, useEffect } from "react";
import axios from "axios";
import { Shuffle, Info, BarChart3, RotateCcw } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const MODEL_COLORS = { "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b", "Opus 4.5": "#8b5cf6", "Opus 4.6": "#a78bfa" };
const FMT_COLORS = {
  "Abstract": "#ef4444", "Extract": "#f97316", "Full PDF": "#eab308",
  "AI Summary": "#22c55e", "Abs + Sum (4.5)": "#3b82f6", "Abs + Sum (4.6)": "#8b5cf6",
  "Deep Dive": "#06b6d4",
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

export default function SamePairsSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/consistency-analysis`, { timeout: 120000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(e => console.warn(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Computing same-pair analysis across all datasets...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No data available.</div>;

  const vs = data.verdict_stability;

  const cfByModel = Object.entries(vs.cross_format.by_model || {}).map(([mk, v]) => ({ name: mk, rate: v.rate, ...v }));
  const cmByFmt = Object.entries(vs.cross_model.by_format || {}).sort((a, b) => b[1].rate - a[1].rate).map(([fmt, v]) => ({ name: fmt, rate: v.rate, ...v }));

  return (
    <div className="space-y-5" data-testid="same-pairs-analysis">
      {/* Intro */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Shuffle className="h-4 w-4" /> Same-Pair Analysis
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Scope:</strong> Only paper pairs that were evaluated under multiple conditions (different models and/or input formats). This enables controlled comparisons — same pair, different treatment.</p>
          <p><strong>Verdict flip:</strong> The same pair gets a different winner when the judge model or input format changes. A high flip rate means the verdict depends heavily on context, not just paper quality.</p>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">{data.total_matches.toLocaleString()} matches across {data.datasets} datasets.</div>
      </div>

      {/* Cross-format flips */}
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

      {/* Format sensitivity by model */}
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

      {/* Cross-model flips */}
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

      {/* Model disagreement by format */}
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

      {/* ── Same-Pair Condorcet Cycles ── */}
      {vs.same_pair_cycles && (() => {
        const spc = vs.same_pair_cycles;
        const spcHm = spc.heatmap;
        const spcModels = spcHm?.models || [];
        const spcFormats = spcHm?.formats || [];
        const spcByFmt = Object.entries(spc.by_format || {}).sort((a, b) => b[1].rate - a[1].rate);
        if (!spcByFmt.length && !Object.keys(spcHm?.cells || {}).length) return null;

        const colMax = {};
        for (const f of spcFormats) {
          colMax[f.id] = Math.max(...spcModels.map(mk => spcHm.cells?.[`${mk}|${f.id}`]?.triples || 0), 1);
        }

        return (
          <>
            <div className="border-t border-border pt-4 mt-2">
              <h3 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                <RotateCcw className="h-4 w-4 text-red-500" /> Same-Pair Condorcet Cycles
              </h3>
              <div className="text-xs text-muted-foreground mb-3">
                Cycle rates computed <strong>only on pairs that were evaluated under multiple conditions</strong>. Same triples as the flip analysis above — do they also form intransitive loops within each (model, format) context?
              </div>
            </div>

            {/* Heatmap */}
            {spcModels.length > 0 && spcFormats.length > 0 && (
              <div className="border border-border rounded-lg overflow-hidden" data-testid="same-pair-cycle-heatmap">
                <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                  <h3 className="text-xs font-medium">Same-Pair Cycle Heatmap — Model x Format</h3>
                  <div className="text-[10px] text-muted-foreground mt-0.5">Restricted to pairs evaluated in 2+ contexts. Compare with All Pairs heatmap to see if multi-evaluated pairs are more or less cycle-prone.</div>
                </div>
                <div className="p-3 overflow-x-auto">
                  <table className="text-[11px]">
                    <thead>
                      <tr>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">Model</th>
                        {spcFormats.map(f => (
                          <th key={f.id} className="px-2 py-1.5 text-center font-medium text-muted-foreground min-w-[100px]">{f.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {spcModels.map(mk => (
                        <tr key={mk} className="border-t border-border/30">
                          <td className="px-2 py-2 font-medium">{mk}</td>
                          {spcFormats.map(f => {
                            const cell = spcHm.cells?.[`${mk}|${f.id}`];
                            if (!cell || cell.triples < 10) return <td key={f.id} className="px-2 py-2 text-center text-muted-foreground/30">—</td>;
                            const low = cell.triples < colMax[f.id] * 0.15;
                            const intensity = Math.min(cell.rate / 5, 1);
                            const bg = low ? "transparent" : `rgba(239, 68, 68, ${intensity * 0.2})`;
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
                </div>
              </div>
            )}

            {/* By format summary */}
            {spcByFmt.length > 0 && (
              <div className="border border-border rounded-lg overflow-hidden" data-testid="same-pair-cycles-by-format">
                <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                  <h3 className="text-xs font-medium">Same-Pair Cycle Rate by Format (all models pooled)</h3>
                </div>
                <div className="p-3 space-y-1.5">
                  {spcByFmt.map(([fmt, v]) => (
                    <HBar key={fmt} label={fmt} rate={v.rate} sub={`${v.cycles}/${v.triples.toLocaleString()}`}
                      maxRate={Math.max(...spcByFmt.map(x => x[1].rate), 1)} color="#ef4444" />
                  ))}
                </div>
              </div>
            )}
          </>
        );
      })()}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Same-pair requirement:</strong> Every data point comes from a paper pair evaluated at least twice under different conditions.</li>
          <li><strong>Cross-format flip:</strong> Same model judges the same pair under two formats — how often does the winner change?</li>
          <li><strong>Cross-model flip:</strong> Two models judge the same pair under the same format — how often do they disagree?</li>
          <li><strong>Core formats:</strong> Abstract, Extract, Full PDF, AI Summary, Abs+Sum (4.5), Abs+Sum (4.6), Deep Dive.</li>
        </ul>
      </div>
    </div>
  );
}
