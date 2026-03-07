import { useState, useEffect } from "react";
import axios from "axios";
import { Info, Building2, Lock } from "lucide-react";

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

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Loading same-pair institution bias analysis...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No data available.</div>;

  const pooled = data.pooled || {};
  const byJudge = data.by_judge || {};
  const tierPairs = data.tier_pairs || {};

  return (
    <div className="space-y-5" data-testid="institution-bias-samepair">
      {/* Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Lock className="h-4 w-4" /> Institution Bias — Same-Pair Controlled
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Same as the general institution bias analysis, but with a stricter control: only pairs where <em>all 3 judges</em> (Opus 4.6, GPT-5.2, Gemini 3 Pro) evaluated the exact same pair are included.</p>
          <p><strong>Why this matters:</strong> The general analysis includes different pairs per judge, which can confound the comparison. Here, every judge sees the same set of paper pairs, so differences in bias are purely due to the judge model — not pair selection.</p>
          <p><strong>Data:</strong> {data.total_shared_pairs?.toLocaleString()} shared pairs across {data.total_datasets} datasets where all 3 judges have verdicts.</p>
        </div>
      </div>

      {/* Key finding */}
      {Object.keys(byJudge).length > 0 && (
        <div className="border-2 border-emerald-200 rounded-lg p-4 bg-emerald-50/30" data-testid="ibsp-finding">
          <h3 className="text-xs font-semibold mb-2 text-emerald-900">Key Finding (Same-Pair Controlled)</h3>
          <p className="text-xs text-emerald-800/80">
            On identical prestige-gap pairs, all judges pick the prestigious paper <em>less often</em> than human reviewers.
            Bias deltas: {Object.entries(byJudge).sort((a, b) => a[1].bias_delta - b[1].bias_delta).map(([j, s]) => `${j} ${s.bias_delta}pp`).join(", ")}.
          </p>
        </div>
      )}

      {/* Pooled accuracy by category */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-pooled">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Accuracy by Pair Category (Same-Pair Controlled)</h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">All 3 judges evaluated the exact same pairs. Only cross-tier pairs with clear human ground truth included.</div>
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
          <h3 className="text-xs font-medium">Prestige Preference by Judge — Same Pairs</h3>
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
                <th className="text-right py-1.5 px-2 font-medium">AI → Prestige</th>
                <th className="text-right py-1.5 px-2 font-medium">Human → Prestige</th>
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

      {/* Tier pair accuracy */}
      {Object.keys(tierPairs).length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ibsp-tiers">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Accuracy by Institution Tier Pairing</h3>
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
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Same-pair control:</strong> Only pairs where Opus 4.6, GPT-5.2, AND Gemini 3 Pro all evaluated the same paper pair are included. This eliminates pair-selection confounds.</li>
          <li><strong>Smaller N:</strong> The same-pair requirement reduces the dataset significantly compared to the general analysis. Results may have wider confidence intervals.</li>
          <li><strong>Interpretation:</strong> If bias deltas are similar to the general analysis, the finding is robust. If they differ, the general analysis may have been confounded by pair selection.</li>
        </ul>
      </div>
    </div>
  );
}
