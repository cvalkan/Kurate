import { useState, useEffect } from "react";
import axios from "axios";
import { BarChart3, FlaskConical, ArrowUpDown } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function JudgeComparisonSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/judge-comparison/results`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;
  if (!data || data.status === "no_data") return <div className="text-center py-12 text-muted-foreground text-sm">Not enough multi-model data to compare judges. Need pairs evaluated by all 4 judges.</div>;

  const { judges, round_robin, majority_vote, total_pairs, n_datasets, cycle_correlation, per_dataset } = data;

  const allMethods = [
    ...judges.map(j => ({ ...j, type: "judge" })),
    { name: "Round-Robin (sim)", ...round_robin, type: "ensemble", cycle_rate: null },
    { name: "Majority Vote", ...majority_vote, type: "ensemble", cycle_rate: null },
  ].sort((a, b) => (b.avg_rho || 0) - (a.avg_rho || 0));

  const bestAcc = Math.max(...allMethods.map(m => m.accuracy || 0));
  const bestRho = Math.max(...allMethods.map(m => m.avg_rho || 0));

  return (
    <div className="space-y-6" data-testid="judge-comparison">
      <div className="border border-blue-200 rounded-lg p-4 bg-blue-50/30 text-xs text-blue-900 space-y-2">
        <h3 className="font-medium text-sm flex items-center gap-1.5"><FlaskConical className="h-3.5 w-3.5" /> Experiment Design</h3>
        <p>Using <strong>{total_pairs.toLocaleString()} pairs</strong> across <strong>{n_datasets} ICLR datasets</strong> where all 4 judge models (Opus 4.6, Opus 4.5, GPT-5.2, Gemini 3 Pro) evaluated the exact same pair with the same summarizer input (Opus 4.5 summaries).</p>
        <p>This controlled setup enables fair head-to-head comparison of judge accuracy, ranking correlation, and ensemble methods. Round-robin is simulated by randomly selecting one judge per pair (100 trials averaged). Majority vote uses the 4-judge consensus.</p>
      </div>

      {/* Main results table */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="judge-results-table">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5"><BarChart3 className="h-3 w-3" /> Judge Accuracy & Ranking Correlation</h3>
          <p className="text-[10px] text-muted-foreground mt-0.5">{total_pairs.toLocaleString()} identical pairs, all judges evaluated each pair</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-[10px]">
                <th className="text-left py-1.5 px-3 font-medium">Method</th>
                <th className="text-right py-1.5 px-2 font-medium">Cycle Rate</th>
                <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                <th className="text-right py-1.5 px-2 font-medium">Avg Spearman</th>
                <th className="text-right py-1.5 px-2 font-medium">Avg M/P</th>
                <th className="text-right py-1.5 px-2 font-medium">Pairs</th>
              </tr>
            </thead>
            <tbody>
              {allMethods.map(m => (
                <tr key={m.name} className={`border-b border-border/30 ${m.type === "ensemble" ? "bg-blue-50/20" : ""}`}>
                  <td className="py-1.5 px-3 font-medium">
                    {m.name}
                    {m.type === "ensemble" && <span className="ml-1 text-[9px] text-blue-600 font-normal">(ensemble)</span>}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">
                    {m.cycle_rate != null ? `${m.cycle_rate.toFixed(2)}%` : "—"}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono">
                    <span className={m.accuracy >= bestAcc - 0.1 ? "text-green-600 font-semibold" : ""}>{m.accuracy.toFixed(1)}%</span>
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono">
                    <span className={m.avg_rho >= bestRho - 0.001 ? "text-green-600 font-semibold" : ""}>{m.avg_rho.toFixed(3)}</span>
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{m.avg_mpp ?? "—"}</td>
                  <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{(m.total_pairs || total_pairs).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Correlation analysis */}
      {cycle_correlation && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium flex items-center gap-1.5"><ArrowUpDown className="h-3 w-3" /> Do Fewer Cycles Mean Higher Accuracy?</h3>
          </div>
          <div className="p-4 text-xs space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <div className="border border-border rounded p-3">
                <p className="text-muted-foreground text-[10px] mb-1">Cycle Rate vs Accuracy (Spearman)</p>
                <p className="text-lg font-mono font-medium">r = {cycle_correlation.acc_spearman_r.toFixed(3)}</p>
                <p className="text-muted-foreground text-[10px]">p = {cycle_correlation.acc_spearman_p.toFixed(3)}</p>
              </div>
              <div className="border border-border rounded p-3">
                <p className="text-muted-foreground text-[10px] mb-1">Cycle Rate vs Ranking Correlation (Spearman)</p>
                <p className="text-lg font-mono font-medium">r = {cycle_correlation.rho_spearman_r.toFixed(3)}</p>
                <p className="text-muted-foreground text-[10px]">p = {cycle_correlation.rho_spearman_p.toFixed(3)}</p>
              </div>
            </div>
            <div className="text-muted-foreground border-t border-border pt-3 space-y-1">
              <p><strong>Interpretation:</strong> With only n=4 judges, statistical significance is limited. The direction is consistent (lower cycles tend to correlate with higher accuracy) but Gemini breaks the monotonic pattern — it has fewer cycles than Opus 4.5 yet lower accuracy. This suggests cycle rate measures <em>self-consistency</em> rather than <em>correctness</em>.</p>
              <p>For <strong>summarizers</strong>, the correlation is perfect (r = -1.000): better summaries simultaneously reduce cycles AND improve accuracy. For <strong>judges</strong>, the relationship is weaker — a judge can be internally consistent but systematically biased.</p>
            </div>
          </div>
        </div>
      )}

      {/* Per-dataset breakdown */}
      {per_dataset && per_dataset.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Per-Dataset Breakdown</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-[10px]">
                  <th className="text-left py-1.5 px-3 font-medium">Dataset</th>
                  <th className="text-right py-1.5 px-2 font-medium">Pairs</th>
                  <th className="text-right py-1.5 px-2 font-medium">Opus 4.6</th>
                  <th className="text-right py-1.5 px-2 font-medium">Opus 4.5</th>
                  <th className="text-right py-1.5 px-2 font-medium">GPT-5.2</th>
                  <th className="text-right py-1.5 px-2 font-medium">Gemini</th>
                  <th className="text-right py-1.5 px-2 font-medium">RR (sim)</th>
                  <th className="text-right py-1.5 px-2 font-medium">Majority</th>
                </tr>
              </thead>
              <tbody>
                {per_dataset.map(ds => {
                  const vals = [ds.opus46_acc, ds.opus45_acc, ds.gpt52_acc, ds.gemini3pro_acc, ds.rr_acc, ds.mv_acc].filter(v => v != null);
                  const best = Math.max(...vals);
                  const Cell = ({ v }) => (
                    <td className="text-right py-1.5 px-2 font-mono">
                      {v != null ? <span className={v >= best - 0.1 ? "text-green-600 font-semibold" : ""}>{v.toFixed(1)}%</span> : "—"}
                    </td>
                  );
                  return (
                    <tr key={ds.dataset_id} className="border-b border-border/30">
                      <td className="py-1.5 px-3 font-medium">{ds.name}</td>
                      <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{ds.pairs}</td>
                      <Cell v={ds.opus46_acc} />
                      <Cell v={ds.opus45_acc} />
                      <Cell v={ds.gpt52_acc} />
                      <Cell v={ds.gemini3pro_acc} />
                      <Cell v={ds.rr_acc} />
                      <Cell v={ds.mv_acc} />
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Key takeaways */}
      <div className="border border-amber-200 rounded-lg p-4 bg-amber-50/30 text-xs space-y-2">
        <h3 className="font-medium text-sm text-amber-900">Key Takeaways</h3>
        <ul className="list-disc list-inside text-amber-900 space-y-1">
          <li><strong>Opus 4.6 is the best single judge</strong> — highest accuracy and ranking correlation</li>
          <li><strong>Round-robin dilutes quality</strong> — randomly mixing in weaker judges reduces accuracy by ~1.4pp vs Opus 4.6 alone, though ranking correlation (rho) is barely affected</li>
          <li><strong>Majority vote doesn't help rankings</strong> — higher accuracy than round-robin but slightly worse rho, because it compresses score differences</li>
          <li><strong>Cycle rate doesn't predict judge quality</strong> — Gemini has fewer cycles than Opus 4.5 but lower accuracy (consistent-but-wrong)</li>
        </ul>
      </div>
    </div>
  );
}
