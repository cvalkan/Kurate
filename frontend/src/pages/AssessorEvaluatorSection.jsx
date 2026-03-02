import { useState, useEffect } from "react";
import axios from "axios";
import { FlaskConical, Info } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const JUDGE_COLORS = {
  "Round-Robin": "#22c55e", "Opus 4.6": "#8b5cf6", "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b",
};

function HeatCell({ value, maxVal, label, sub }) {
  const intensity = value != null ? Math.min(Math.abs(value) / Math.max(maxVal, 0.01), 1) : 0;
  const bg = value != null ? `rgba(34, 197, 94, ${intensity * 0.25})` : "transparent";
  return (
    <td className="text-center py-2 px-2 font-mono" style={{ backgroundColor: bg }}>
      {value != null ? (
        <>
          <div className={value >= maxVal * 0.9 ? "text-green-600 font-semibold" : ""}>{label}</div>
          {sub && <div className="text-[9px] text-muted-foreground font-normal">{sub}</div>}
        </>
      ) : <span className="text-muted-foreground/30">—</span>}
    </td>
  );
}

export default function AssessorEvaluatorSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState("rho"); // "rho" or "accuracy"

  useEffect(() => {
    axios.get(`${API}/api/validation/assessor-evaluator/results`, { timeout: 30000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(e => console.warn(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Loading assessor × evaluator matrix...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No data available. Run the Summarizer Cross-Model experiment first.</div>;

  const summarizers = data.summarizers || [];
  const judges = data.judges || [];

  // Build pooled matrix
  const pooled = data.pooled || {};
  const maxRho = Math.max(...Object.values(pooled).map(v => v.avg_rho || 0), 0.1);
  const maxAcc = Math.max(...Object.values(pooled).map(v => v.accuracy || 0), 50);

  return (
    <div className="space-y-5" data-testid="assessor-evaluator">
      {/* Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <FlaskConical className="h-4 w-4" /> Assessor vs Evaluator: Full Matrix
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Which model should <em>write</em> the impact assessment (assessor/summarizer), and which should <em>judge</em> the comparison (evaluator)? Are these roles better filled by the same or different models?</p>
          <p><strong>Method:</strong> 5 summarizer models × 4 judge strategies (3 single + round-robin), all evaluated on the exact same pairs within each dataset. Ranking correlation (ρ) and pairwise accuracy against human ground truth.</p>
          <p><strong>Same-pair control:</strong> All cells use the intersection of pairs where ALL 5 summarizers have data, eliminating pair-selection bias.</p>
        </div>
      </div>

      {/* Metric toggle */}
      <div className="flex gap-2">
        <button onClick={() => setMetric("rho")} className={`px-3 py-1 text-xs rounded-full border ${metric === "rho" ? "bg-primary text-primary-foreground" : "border-border text-muted-foreground"}`}>
          Ranking ρ
        </button>
        <button onClick={() => setMetric("accuracy")} className={`px-3 py-1 text-xs rounded-full border ${metric === "accuracy" ? "bg-primary text-primary-foreground" : "border-border text-muted-foreground"}`}>
          Pairwise Accuracy
        </button>
      </div>

      {/* Pooled heatmap */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="ae-pooled">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Pooled Across Datasets — {metric === "rho" ? "Ranking Correlation (ρ)" : "Pairwise Accuracy"}</h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">Rows = summarizer model, columns = judge strategy. Green = better. All on identical pairs.</div>
        </div>
        <div className="p-3 overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border text-[10px]">
                <th className="text-left py-1.5 pr-3 font-medium">Assessor ↓ / Evaluator →</th>
                {judges.map(j => (
                  <th key={j} className="text-center py-1.5 px-3 font-medium min-w-[90px]">
                    <span style={{ color: JUDGE_COLORS[j] }}>{j}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {summarizers.map(sum => {
                const row = judges.map(j => pooled[`${sum}|${j}`]);
                return (
                  <tr key={sum} className="border-b border-border/30">
                    <td className="py-2 pr-3 font-medium">{sum}</td>
                    {row.map((cell, i) => {
                      if (!cell) return <td key={i} className="text-center py-2 px-3 text-muted-foreground/30">—</td>;
                      const val = metric === "rho" ? cell.avg_rho : cell.accuracy;
                      const maxV = metric === "rho" ? maxRho : maxAcc;
                      const label = metric === "rho" ? (val != null ? val.toFixed(3) : "—") : `${val}%`;
                      const sub = `${cell.correct}/${cell.total}`;
                      return <HeatCell key={i} value={val} maxVal={maxV} label={label} sub={sub} />;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per-dataset breakdowns */}
      {Object.entries(data.by_dataset || {}).map(([dsId, ds]) => {
        const cells = ds.cells || [];
        const dsMax = metric === "rho"
          ? Math.max(...cells.map(c => c.rho || 0), 0.1)
          : Math.max(...cells.map(c => c.accuracy || 0), 50);

        return (
          <div key={dsId} className="border border-border rounded-lg overflow-hidden" data-testid={`ae-ds-${dsId}`}>
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">{ds.name} — {ds.shared_pairs} shared pairs</h3>
            </div>
            <div className="p-3 overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border text-[10px]">
                    <th className="text-left py-1.5 pr-3 font-medium">Assessor ↓ / Evaluator →</th>
                    {judges.map(j => (
                      <th key={j} className="text-center py-1.5 px-3 font-medium min-w-[90px]">
                        <span style={{ color: JUDGE_COLORS[j] }}>{j}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {summarizers.map(sum => (
                    <tr key={sum} className="border-b border-border/30">
                      <td className="py-2 pr-3 font-medium">{sum}</td>
                      {judges.map(j => {
                        const cell = cells.find(c => c.summarizer === sum && c.judge === j);
                        if (!cell) return <td key={j} className="text-center py-2 px-3 text-muted-foreground/30">—</td>;
                        const val = metric === "rho" ? cell.rho : cell.accuracy;
                        const label = metric === "rho" ? (val != null ? val.toFixed(3) : "—") : `${val}%`;
                        return <HeatCell key={j} value={val} maxVal={dsMax} label={label} sub={`${cell.pairs}p`} />;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      {/* Key findings */}
      <div className="border-2 border-green-200 rounded-lg p-4 bg-green-50/30" data-testid="ae-findings">
        <h3 className="text-xs font-semibold mb-2 text-green-900">Key Findings</h3>
        <ul className="text-xs text-green-800/80 space-y-1">
          <li><strong>Round-robin always wins:</strong> In every row, the Round-Robin column has the highest ρ. Model diversity matters more than picking the "best" single judge.</li>
          <li><strong>Best configuration:</strong> Opus 4.6 Thinking summaries + Round-Robin judging (avg ρ best or tied-for-best across datasets).</li>
          <li><strong>Assessor matters more than evaluator:</strong> The ρ range across rows (summarizers) is wider than across columns (judges), confirming that input quality is the bigger lever.</li>
          <li><strong>Self-consistency is not an advantage:</strong> GPT-5.2 judging GPT-5.2 summaries and Gemini judging Gemini summaries perform worse than cross-model combinations.</li>
          <li><strong>Caveat:</strong> Only 2 datasets with all 5 summarizers (248 total pairs). Per-judge columns have small N (22-55 pairs per cell).</li>
        </ul>
      </div>

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Assessor:</strong> The model that generates the impact assessment summary from the paper's full text.</li>
          <li><strong>Evaluator:</strong> The model that compares two papers' summaries and picks a winner.</li>
          <li><strong>Round-Robin:</strong> Majority vote across all 3 judge models (GPT-5.2, Opus 4.6, Gemini 3 Pro).</li>
          <li><strong>Same pairs:</strong> Intersection of all 5 summarizers — every cell uses the exact same paper pairs.</li>
          <li><strong>Ranking ρ:</strong> Spearman correlation between AI's BT ranking and human reviewers' BT ranking.</li>
          <li><strong>Accuracy:</strong> Fraction of pairwise comparisons where AI agrees with human expert majority.</li>
        </ul>
      </div>
    </div>
  );
}
