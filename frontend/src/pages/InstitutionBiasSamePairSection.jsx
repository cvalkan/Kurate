import { useState, useEffect } from "react";
import axios from "axios";
import { Info, Building2 } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function InstitutionBiasSamePairSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/institution-bias-samepair/results`, { timeout: 30000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(e => console.warn(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Loading institution bias analysis...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No data available.</div>;

  const pooled = data.pooled || {};
  const byJudge = data.by_judge || {};
  const bySummarizer = data.by_summarizer || {};
  const matrix = data.matrix || {};
  const tierPairs = data.tier_pairs || {};

  // Derive judges and summarizers from matrix keys
  const matrixJudges = [...new Set(Object.keys(matrix).map(k => k.split("|")[1]))].sort();
  const matrixSummarizers = [...new Set(Object.keys(matrix).map(k => k.split("|")[0]))].sort();

  return (
    <div className="space-y-5" data-testid="institution-bias-samepair">
      {/* Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Building2 className="h-4 w-4" /> Institution Prestige Bias Analysis
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Do AI judges favor papers from prestigious institutions (Google, Meta, Stanford, MIT, etc.) more than human reviewers do? And does the choice of summarizer LLM affect how much institutional identity leaks into the evaluation?</p>
          <p><strong>Method:</strong> Extract author affiliations from paper headers. Classify as <em>Big Tech</em> (Google, Meta, OpenAI, Microsoft), <em>Top University</em> (Stanford, MIT, CMU, Berkeley, etc.), or <em>Other</em>. Compare AI judge accuracy and prestige preference rates.</p>
          <p><strong>Same-pair control:</strong> Only pairs where all 4 judges (Opus 4.5, Opus 4.6, GPT-5.2, Gemini 3 Pro) evaluated the exact same pair. Differences between judges are purely due to the model — not pair selection.</p>
          <p><strong>Pair categories:</strong></p>
          <ul className="list-disc list-inside ml-2 space-y-0.5">
            <li><strong>Prestige-gap:</strong> one paper from a prestigious institution, one from an unknown — tests whether AI over-favors the big name</li>
            <li><strong>Cross-institution:</strong> papers from different identifiable institutions</li>
            <li><strong>Same-institution:</strong> both papers share at least one institution</li>
            <li><strong>No institution:</strong> neither paper has identifiable affiliations in the header</li>
          </ul>
          <p><strong>Data:</strong> {data.total_shared_pairs?.toLocaleString()} shared pairs across {data.total_datasets} datasets.</p>
        </div>
      </div>

      {/* Key finding */}
      {Object.keys(byJudge).length > 0 && (
        <div className="border-2 border-emerald-200 rounded-lg p-4 bg-emerald-50/30" data-testid="ibsp-finding">
          <h3 className="text-xs font-semibold mb-2 text-emerald-900">Key Finding</h3>
          <p className="text-xs text-emerald-800/80">
            <strong>AI judges show less institutional prestige bias than human reviewers.</strong> On identical prestige-gap pairs, all judges pick the prestigious paper less often than humans do.
            Bias deltas: {Object.entries(byJudge).sort((a, b) => a[1].bias_delta - b[1].bias_delta).map(([j, s]) => `${j} ${s.bias_delta > 0 ? "+" : ""}${s.bias_delta}pp`).join(", ")}.
            {" "}(Negative = less biased than human reviewers.)
          </p>
        </div>
      )}

      {/* Pooled accuracy by category */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-pooled">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Accuracy by Pair Category</h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">All 4 judges evaluated the exact same pairs. Only cross-tier pairs with clear human ground truth included.</div>
        </div>
        <div className="p-3">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border text-[10px]">
                <th className="text-left py-1.5 pr-3 font-medium">Category</th>
                <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                <th className="text-right py-1.5 px-2 font-medium">Correct/Total</th>
                <th className="py-1.5 px-2 w-1/4"></th>
              </tr>
            </thead>
            <tbody>
              {["prestige_gap", "cross_institution", "same_institution", "no_institution"].map(cat => {
                const d = pooled[cat];
                if (!d || !d.total) return null;
                const label = cat.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                return (
                  <tr key={cat} className="border-b border-border/30">
                    <td className="py-1.5 pr-3 font-medium capitalize">{label}</td>
                    <td className="text-right py-1.5 px-2 font-mono">{d.accuracy}%</td>
                    <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{d.correct.toLocaleString()}/{d.total.toLocaleString()}</td>
                    <td className="py-1.5 px-2">
                      <div className="h-2.5 bg-secondary/30 rounded-full overflow-hidden">
                        <div className="h-full rounded-full bg-blue-500" style={{ width: `${(d.accuracy / 100) * 100}%` }} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per-judge prestige preference */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-judges">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Prestige Preference by Judge</h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            Every row uses the exact same set of prestige-gap pairs. Differences are purely due to the judge model.
          </div>
        </div>
        <div className="p-3">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border text-[10px]">
                <th className="text-left py-1.5 pr-3 font-medium">Judge</th>
                <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                <th className="text-right py-1.5 px-2 font-medium">AI Picks Prestige</th>
                <th className="text-right py-1.5 px-2 font-medium">Human Picks Prestige</th>
                <th className="text-right py-1.5 px-2 font-medium">Bias Delta</th>
                <th className="text-right py-1.5 px-2 font-medium">Pairs</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byJudge).sort((a, b) => a[1].bias_delta - b[1].bias_delta).map(([judge, stats]) => (
                <tr key={judge} className="border-b border-border/30">
                  <td className="py-1.5 pr-3 font-medium">{judge}</td>
                  <td className="text-right py-1.5 px-2 font-mono">{stats.accuracy}%</td>
                  <td className="text-right py-1.5 px-2 font-mono">{stats.ai_prestige_pct}%</td>
                  <td className="text-right py-1.5 px-2 font-mono">{stats.human_prestige_pct}%</td>
                  <td className={`text-right py-1.5 px-2 font-mono font-semibold ${stats.bias_delta < 0 ? "text-emerald-600" : "text-red-600"}`}>
                    {stats.bias_delta > 0 ? "+" : ""}{stats.bias_delta}pp
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{stats.total.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Summarizer × Judge Matrix */}
      {matrixJudges.length > 0 && matrixSummarizers.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-matrix">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Summarizer x Judge Prestige Bias Matrix</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              Bias delta (pp) for each summarizer–judge combination. Negative = less biased than human reviewers.
              Rows = which LLM wrote the summary. Columns = which LLM judged. On the same shared pairs.
            </div>
          </div>
          <div className="p-3 overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border text-[10px]">
                  <th className="text-left py-1.5 pr-3 font-medium">Summarizer \ Judge</th>
                  {matrixJudges.map(j => (
                    <th key={j} className="text-center py-1.5 px-2 font-medium">{j}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrixSummarizers.map(sum => (
                  <tr key={sum} className="border-b border-border/30">
                    <td className="py-1.5 pr-3 font-medium">{sum}</td>
                    {matrixJudges.map(judge => {
                      const cell = matrix[`${sum}|${judge}`];
                      if (!cell) return <td key={judge} className="text-center py-1.5 px-2 text-muted-foreground/40">—</td>;
                      const d = cell.bias_delta;
                      const intensity = Math.min(Math.abs(d) / 10, 1);
                      const bg = d < 0
                        ? `rgba(16, 185, 129, ${intensity * 0.3})`
                        : `rgba(239, 68, 68, ${intensity * 0.3})`;
                      return (
                        <td key={judge} className="text-center py-1.5 px-2" style={{ backgroundColor: bg }}>
                          <span className={`font-mono font-semibold text-[11px] ${d < 0 ? "text-emerald-700" : "text-red-700"}`}>
                            {d > 0 ? "+" : ""}{d}
                          </span>
                          <br />
                          <span className="text-[9px] text-muted-foreground">{cell.total}</span>
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

      {/* Per-summarizer prestige preference */}
      {Object.keys(bySummarizer).length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-summarizers">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Does the Summarizer LLM Affect Prestige Bias?</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              Restricted to the same shared pairs as the judge table above. The summarizer reads the full paper (including author names and affiliations).
              If a summarizer leaks more institutional identity, judges reading its output may show more prestige bias.
              Note: not all summarizers evaluated every shared pair, so N varies — but the pair pool is the same.
            </div>
          </div>
          <div className="p-3">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border text-[10px]">
                  <th className="text-left py-1.5 pr-3 font-medium">Summarizer</th>
                  <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                  <th className="text-right py-1.5 px-2 font-medium">AI Picks Prestige</th>
                  <th className="text-right py-1.5 px-2 font-medium">Human Picks Prestige</th>
                  <th className="text-right py-1.5 px-2 font-medium">Bias Delta</th>
                  <th className="text-right py-1.5 px-2 font-medium">Pairs</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(bySummarizer).sort((a, b) => a[1].bias_delta - b[1].bias_delta).map(([sum, stats]) => (
                  <tr key={sum} className="border-b border-border/30">
                    <td className="py-1.5 pr-3 font-medium">{sum}</td>
                    <td className="text-right py-1.5 px-2 font-mono">{stats.accuracy}%</td>
                    <td className="text-right py-1.5 px-2 font-mono">{stats.ai_prestige_pct}%</td>
                    <td className="text-right py-1.5 px-2 font-mono">{stats.human_prestige_pct}%</td>
                    <td className={`text-right py-1.5 px-2 font-mono font-semibold ${stats.bias_delta < 0 ? "text-emerald-600" : "text-red-600"}`}>
                      {stats.bias_delta > 0 ? "+" : ""}{stats.bias_delta}pp
                    </td>
                    <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{stats.total.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tier pair accuracy */}
      {Object.keys(tierPairs).length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-tiers">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Accuracy by Institution Tier Pairing</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">How does accuracy vary based on the prestige levels of the two compared papers?</div>
          </div>
          <div className="p-3">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border text-[10px]">
                  <th className="text-left py-1.5 pr-3 font-medium">Tier Pairing</th>
                  <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                  <th className="text-right py-1.5 px-2 font-medium">Pairs</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(tierPairs).sort((a, b) => b[1].accuracy - a[1].accuracy).map(([pair, stats]) => (
                  <tr key={pair} className="border-b border-border/30">
                    <td className="py-1.5 pr-3 font-medium">{pair.replace(/_/g, " ").replace(/vs/g, "vs.")}</td>
                    <td className="text-right py-1.5 px-2 font-mono">{stats.accuracy}%</td>
                    <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{stats.total.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology & Limitations</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Same-pair control:</strong> Only pairs where all 4 judges evaluated the same paper pair are included, eliminating pair-selection confounds.</li>
          <li><strong>Institution extraction:</strong> Pattern matching on the first 3000 characters of full text (author affiliations area). 15 major institutions tracked.</li>
          <li><strong>Prestige tiers:</strong> Big Tech = Google/DeepMind, Meta/FAIR, OpenAI, Microsoft. Top University = Stanford, MIT, CMU, Berkeley, Princeton, Harvard, Oxford, Cambridge, ETH, Tsinghua, Peking.</li>
          <li><strong>Summarizer bias:</strong> The summarizer reads the full paper (including authors), so it may encode institutional identity into the summary. The judge only sees the summary — but if the summary leaks prestige cues, the judge inherits that bias.</li>
          <li><strong>Limitation:</strong> Human ground truth (ICLR/eLife reviewers) may itself be prestige-biased. A "fair" AI would match human bias, not eliminate it. Negative deltas indicate AI is less biased than the human baseline.</li>
        </ul>
      </div>
    </div>
  );
}
