import { useState, useEffect } from "react";
import axios from "axios";
import { FlaskConical, Info, Building2 } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function BiasBar({ aiPct, humanPct, label }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{label}</span>
        <span>delta: {(aiPct - humanPct) > 0 ? "+" : ""}{(aiPct - humanPct).toFixed(1)}pp</span>
      </div>
      <div className="flex gap-1 items-center">
        <div className="flex-1 h-3 bg-secondary/30 rounded-full overflow-hidden relative">
          <div className="absolute h-full bg-blue-400/60 rounded-full" style={{ width: `${humanPct}%` }} />
          <div className="absolute h-full bg-emerald-500/80 rounded-full border-r-2 border-white" style={{ width: `${aiPct}%` }} />
        </div>
        <span className="text-[10px] font-mono w-16 text-right">{aiPct}%</span>
      </div>
      <div className="flex justify-between text-[9px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> AI</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-400 inline-block" /> Human {humanPct}%</span>
      </div>
    </div>
  );
}

export default function InstitutionBiasSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/institution-bias/results`, { timeout: 30000 })
      .then(r => { if (r.data.status === "ok") setData(r.data); })
      .catch(e => console.warn(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-8">Loading institution bias analysis...</div>;
  if (!data) return <div className="text-xs text-muted-foreground text-center py-8">No data available.</div>;

  const pooled = data.pooled || {};
  const byJudge = data.by_judge || {};
  const tierPairs = data.tier_pairs || {};
  const institutions = data.institutions || [];

  return (
    <div className="space-y-5" data-testid="institution-bias">
      {/* Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Building2 className="h-4 w-4" /> Institution Prestige Bias Analysis
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Do AI judges favor papers from prestigious institutions (Google, Meta, Stanford, MIT, etc.) more than human reviewers do?</p>
          <p><strong>Method:</strong> Extract author affiliations from paper headers (first 3000 chars). Classify institutions as <em>Big Tech</em> (Google, Meta, OpenAI, Microsoft), <em>Top University</em> (Stanford, MIT, CMU, Berkeley, etc.), or <em>Other</em>. Compare AI judge accuracy and prestige preference rates across pair categories.</p>
          <p><strong>Pair categories:</strong></p>
          <ul className="list-disc list-inside ml-2 space-y-0.5">
            <li><strong>Prestige-gap:</strong> one paper from a prestigious institution, one from an unknown — tests whether AI over-favors the big name</li>
            <li><strong>Cross-institution:</strong> papers from different identifiable institutions</li>
            <li><strong>Same-institution:</strong> both papers share at least one institution</li>
            <li><strong>No institution:</strong> neither paper has identifiable affiliations in the header</li>
          </ul>
          <p><strong>Data:</strong> {data.total_matches?.toLocaleString()} matches across {data.total_datasets} ICLR and eLife datasets. All match types (Opus 4.5/4.6, GPT, Gemini summaries).</p>
        </div>
      </div>

      {/* Key finding */}
      <div className="border-2 border-emerald-200 rounded-lg p-4 bg-emerald-50/30" data-testid="ib-finding">
        <h3 className="text-xs font-semibold mb-2 text-emerald-900">Key Finding</h3>
        <p className="text-xs text-emerald-800/80">
          <strong>AI judges show less institutional prestige bias than human reviewers.</strong> In prestige-gap pairs (one prestigious + one unknown institution), human reviewers favor the prestigious paper{" "}
          {byJudge[Object.keys(byJudge)[0]]?.human_prestige_pct}% of the time. All three AI judges favor it less often — with a gap of{" "}
          {Object.values(byJudge).map(j => `${j.bias_delta}pp`).join(" to ")} (negative = less biased than humans).
        </p>
      </div>

      {/* Pooled accuracy by category */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="ib-pooled">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Accuracy by Pair Category (Pooled)</h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">Does pair type affect how well AI agrees with human ground truth?</div>
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
      <div className="border border-border rounded-lg overflow-hidden" data-testid="ib-judges">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Prestige Preference by Judge (Prestige-Gap Pairs Only)</h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            How often does each judge pick the paper from a prestigious institution? Compared to how often human reviewers do.
            Negative delta = AI is <em>less</em> biased toward prestige than humans.
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
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ib-tiers">
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
          <li><strong>Institution extraction:</strong> Pattern matching on the first 3000 characters of the paper's full text (author affiliations section). Only 15 major institutions tracked — many papers have no identifiable institution.</li>
          <li><strong>Prestige tiers:</strong> Big Tech = Google/DeepMind, Meta/FAIR, OpenAI, Microsoft. Top University = Stanford, MIT, CMU, Berkeley, Princeton, Harvard, Oxford, Cambridge, ETH, Tsinghua, Peking.</li>
          <li><strong>Limitation — confounded variable:</strong> Prestigious institutions produce higher-quality papers on average, so favoring them may reflect quality recognition, not bias. The key metric is the <em>delta</em> between AI and human preference (if AI is equally or less biased, the system is fair).</li>
          <li><strong>Limitation — paper text leaks identity:</strong> Even though author names are not sent to judges, writing style, self-citations, and dataset names can implicitly reveal institutional origin.</li>
          <li><strong>Limitation — human ground truth is also biased:</strong> ICLR and eLife reviewers may themselves be biased toward prestigious institutions. A "fair" AI would match human bias, not eliminate it.</li>
        </ul>
      </div>
    </div>
  );
}
