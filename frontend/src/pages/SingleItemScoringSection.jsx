import { useState, useEffect } from "react";
import axios from "axios";
import { Info, Scale, Zap } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function SingleItemScoringSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/single-item-scoring/results`, { timeout: 30000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Loading single-item scoring results...</div>;
  if (!data || !data.datasets?.length) return <div className="text-xs text-muted-foreground text-center py-8">No single-item scoring data yet. Run the experiment from the admin panel.</div>;

  return (
    <div className="space-y-5" data-testid="single-item-scoring">
      {/* Description */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Scale className="h-4 w-4" /> Single-Item Scoring vs Pairwise Tournament
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Can a single LLM call per paper ("rate this 1-10") rank papers as well as a full pairwise tournament (hundreds of comparisons)?</p>
          <p><strong>Method:</strong> Opus 4.6 Thinking reads each paper's abstract + AI impact summary and assigns an overall score (1-10) plus sub-scores for significance, rigor, novelty, and clarity. Papers are ranked by this score and compared against human ground truth.</p>
          <p><strong>Why it matters:</strong> If single-item scoring achieves similar accuracy to pairwise comparison, the tournament approach (which costs N² LLM calls) may be unnecessary. If pairwise is significantly better, it justifies the cost.</p>
        </div>
      </div>

      {data.datasets.map(ds => (
        <div key={ds.dataset_id} className="space-y-4">
          {/* Key comparison */}
          <div className="border-2 border-blue-200 rounded-lg p-4 bg-blue-50/30" data-testid="sis-comparison">
            <h3 className="text-xs font-semibold text-blue-900 mb-3">{ds.name}: Head-to-Head Comparison</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="border border-blue-200 rounded-lg p-3 text-center">
                <div className="flex items-center justify-center gap-1.5 mb-1">
                  <Zap className="h-3.5 w-3.5 text-amber-500" />
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Single-Item</span>
                </div>
                <div className="text-2xl font-mono font-bold text-blue-900">{ds.single_item_accuracy}%</div>
                <div className="text-[10px] text-muted-foreground">{ds.papers_scored} LLM calls</div>
                <div className="text-[10px] text-muted-foreground">{ds.single_item_pairs} implied pairs</div>
              </div>
              <div className="border border-blue-200 rounded-lg p-3 text-center">
                <div className="flex items-center justify-center gap-1.5 mb-1">
                  <Scale className="h-3.5 w-3.5 text-violet-500" />
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Pairwise Tournament</span>
                </div>
                <div className="text-2xl font-mono font-bold text-blue-900">{ds.pairwise_accuracy}%</div>
                <div className="text-[10px] text-muted-foreground">{ds.pairwise_matches} LLM calls</div>
                <div className="text-[10px] text-muted-foreground">direct comparisons</div>
              </div>
            </div>
            <div className="mt-3 text-[10px] text-blue-800/70 text-center">
              Cost ratio: <strong>{ds.cost_ratio}</strong>
            </div>
          </div>

          {/* Correlation stats */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="sis-correlation">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Correlation with Human Ground Truth</h3>
            </div>
            <div className="p-3">
              <div className="grid grid-cols-3 gap-3 text-center">
                {[
                  ["Spearman ρ", ds.correlation.spearman_rho],
                  ["Kendall τ", ds.correlation.kendall_tau],
                  ["Pearson r", ds.correlation.pearson_r],
                ].map(([label, val]) => (
                  <div key={label} className="border border-border/50 rounded-lg p-2">
                    <div className="text-[10px] text-muted-foreground">{label}</div>
                    <div className="text-lg font-mono font-semibold">{val != null ? val.toFixed(4) : "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Score distribution */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="sis-distribution">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">AI Score Distribution</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">How Opus 4.6 Thinking distributed its 1-10 scores across {ds.papers_scored} papers</div>
            </div>
            <div className="p-3">
              <div className="flex items-end gap-1 h-20">
                {[1,2,3,4,5,6,7,8,9,10].map(s => {
                  const count = ds.score_distribution[s] || 0;
                  const maxCount = Math.max(...Object.values(ds.score_distribution), 1);
                  const height = count > 0 ? Math.max(8, (count / maxCount) * 100) : 0;
                  return (
                    <div key={s} className="flex-1 flex flex-col items-center gap-0.5">
                      <span className="text-[9px] text-muted-foreground">{count || ""}</span>
                      <div className="w-full bg-blue-400/70 rounded-t" style={{ height: `${height}%` }} />
                      <span className="text-[9px] text-muted-foreground">{s}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Paper-level comparison */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="sis-papers">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Paper-Level Scores (AI vs Human)</h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">Papers sorted by AI score (highest first)</div>
            </div>
            <div className="p-2 max-h-96 overflow-y-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border text-[10px] sticky top-0 bg-background">
                    <th className="text-left py-1 pr-2 font-medium w-6">#</th>
                    <th className="text-left py-1 pr-2 font-medium">Paper</th>
                    <th className="text-right py-1 px-1 font-medium">AI</th>
                    <th className="text-right py-1 px-1 font-medium">Human</th>
                    <th className="text-right py-1 px-1 font-medium">Sig</th>
                    <th className="text-right py-1 px-1 font-medium">Rig</th>
                    <th className="text-right py-1 px-1 font-medium">Nov</th>
                    <th className="text-right py-1 px-1 font-medium">Cla</th>
                  </tr>
                </thead>
                <tbody>
                  {ds.papers.map((p, i) => {
                    const d = p.details || {};
                    return (
                      <tr key={p.id} className="border-b border-border/20 hover:bg-secondary/20">
                        <td className="py-0.5 pr-2 text-muted-foreground">{i+1}</td>
                        <td className="py-0.5 pr-2 truncate max-w-[200px]" title={p.title}>{p.title}</td>
                        <td className="text-right py-0.5 px-1 font-mono font-semibold">{p.ai_score}</td>
                        <td className="text-right py-0.5 px-1 font-mono text-muted-foreground">{p.human_score}</td>
                        <td className="text-right py-0.5 px-1 font-mono text-muted-foreground/70">{d.significance || "—"}</td>
                        <td className="text-right py-0.5 px-1 font-mono text-muted-foreground/70">{d.rigor || "—"}</td>
                        <td className="text-right py-0.5 px-1 font-mono text-muted-foreground/70">{d.novelty || "—"}</td>
                        <td className="text-right py-0.5 px-1 font-mono text-muted-foreground/70">{d.clarity || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ))}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Model:</strong> Opus 4.6 with extended thinking (8K thinking budget). Same model used in the pairwise tournament as both summarizer and judge.</li>
          <li><strong>Input:</strong> Abstract + AI impact assessment (same as pairwise mode "Abstract + Summary").</li>
          <li><strong>Scoring:</strong> 1.0-10.0 overall score + sub-dimensions (significance, rigor, novelty, clarity).</li>
          <li><strong>Pairwise accuracy metric:</strong> For each pair of papers, does the single-item score ordering agree with the human ground truth ordering? This is directly comparable to the pairwise tournament's accuracy.</li>
          <li><strong>Limitation:</strong> Single-item scoring is susceptible to calibration drift (the LLM may cluster scores in a narrow range). Pairwise comparison forces a binary choice, avoiding this issue.</li>
        </ul>
      </div>
    </div>
  );
}
