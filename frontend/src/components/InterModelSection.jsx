import { useState } from "react";
import { GitCompare } from "lucide-react";

const METHOD_ORDER = ["reg_wr", "trueskill", "openskill"];

function bestInRow(methods) {
  let best = null;
  let bestVal = -Infinity;
  for (const [k, v] of Object.entries(methods)) {
    if (v.rho > bestVal) {
      bestVal = v.rho;
      best = k;
    }
  }
  return best;
}

const PAIR_LABELS = {
  "anthropic/claude-opus vs gemini/gemini-3-pro-preview": "Claude Opus vs Gemini Pro",
  "anthropic/claude-opus vs openai/gpt-5_2": "Claude Opus vs GPT-5.2",
  "gemini/gemini-3-pro-preview vs openai/gpt-5_2": "Gemini Pro vs GPT-5.2",
};

export function InterModelSection({ pwData, siData, viewMode = "aggregate", osUpdatedAt }) {
  const [siMode, setSiMode] = useState("full"); // "full" | "controlled"
  const isAvg = viewMode === "average";
  const pwRows = (isAvg && pwData?.avg_pw_inter_model?.length ? pwData.avg_pw_inter_model : pwData?.pw_inter_model) || [];
  const methodLabels = pwData?.method_labels || {};
  const siCorrFull = siData?.inter_model_si || {};
  const siCorrControlled = siData?.controlled_inter_model_si || {};
  const siCorr = siMode === "controlled" ? siCorrControlled : siCorrFull;
  const hasOs = pwRows.some(r => Object.keys(r.methods || {}).some(k => k.startsWith("openskill")));
  const hasControlled = Object.keys(siCorrControlled).length > 0;

  // PW match-level agreement
  const agreement = (isAvg ? pwData?.avg_agreement : pwData?.agreement) || {};

  if (pwRows.length === 0 && Object.keys(siCorrFull).length === 0) return null;

  // Build SI rows
  const modelLabelMap = { claude: "Claude Opus", gpt: "GPT-5.2", gemini: "Gemini 3 Pro" };
  const pairOrder = [["claude", "gemini"], ["claude", "gpt"], ["gemini", "gpt"]];
  const siRows = [];
  for (const [m1, m2] of pairOrder) {
    const key = `${m1} vs ${m2}`;
    const altKey = `${m2} vs ${m1}`;
    const data = siCorr[key] || siCorr[altKey];
    if (data) {
      siRows.push({
        pair: `${modelLabelMap[m1]} vs ${modelLabelMap[m2]}`,
        rho: data.spearman,
        n: data.n,
      });
    }
  }

  // Build agreement rows
  const agreementRows = Object.entries(agreement).map(([key, data]) => ({
    pair: PAIR_LABELS[key] || key,
    ...data,
  }));

  return (
    <div className="mb-8" data-testid="inter-model-section">
      <div className="mb-3">
        <h2 className="font-heading text-lg font-semibold tracking-tight flex items-center gap-2">
          <a href="#inter-model" className="flex items-center gap-2 hover:text-accent transition-colors">
          <GitCompare className="h-4 w-4 text-muted-foreground" />
          Inter-Model Agreement
          </a>
        </h2>
        <p className="text-muted-foreground text-xs mt-1 max-w-2xl">
          How similarly do Claude Opus, GPT-5.2, and Gemini 3 Pro rank papers?
          PW uses each model's own head-to-head match results; SI uses each model's direct 1–10 scores.
        </p>
      </div>

      {/* Match-level agreement */}
      {agreementRows.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden mb-4" data-testid="pw-agreement-table">
          <div className="px-3 py-2 bg-emerald-500/5 border-b border-border">
            <span className="text-xs font-semibold">Match-Level Agreement</span>
            <span className="text-[10px] text-muted-foreground ml-1.5">
              (when two models judge the same paper pair, how often do they pick the same winner?)
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground bg-secondary/5">
                  <th className="py-1.5 px-3 text-left font-medium">Pair</th>
                  <th className="py-1.5 px-3 text-right font-medium">Agreement</th>
                  <th className="py-1.5 px-3 text-right font-medium">Agree</th>
                  <th className="py-1.5 px-3 text-right font-medium">Disagree</th>
                  <th className="py-1.5 px-3 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {agreementRows.map((row, i) => (
                  <tr key={i} className="border-b border-border/20">
                    <td className="py-1.5 px-3 font-medium">{row.pair}</td>
                    <td className="py-1.5 px-3 text-right font-mono font-semibold">{row.rate?.toFixed(1)}%</td>
                    <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{row.agree?.toLocaleString()}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{row.disagree?.toLocaleString()}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{row.total?.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* PW Inter-Model */}
        {pwRows.length > 0 && (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-inter-model-table">
            <div className="px-3 py-2 bg-sky-500/5 border-b border-border">
              <span className="text-xs font-semibold">PW Inter-Model</span>
              <span className="text-[10px] text-muted-foreground ml-1.5">
                (how similarly do models rank papers from their pairwise matches)
              </span>
              {hasOs && osUpdatedAt && <span className="text-[10px] text-muted-foreground/50 ml-1">· OS updated {new Date(osUpdatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground bg-secondary/5">
                    <th className="py-1.5 px-3 text-left font-medium">Pair</th>
                    {METHOD_ORDER.map(m => (
                      <th key={m} className="py-1.5 px-1.5 text-right font-medium whitespace-nowrap text-[10px]">
                        {(methodLabels[m] || m).replace("Dashboard (raw win%)", "Raw WR").replace("Regularized WR", "Reg WR").replace("Bradley-Terry", "BT")}
                      </th>
                    ))}
                    <th className="py-1.5 px-1.5 text-right font-medium whitespace-nowrap text-[10px]">m/paper</th>
                  </tr>
                </thead>
                <tbody>
                  {pwRows.map((row, i) => {
                    const best = bestInRow(row.methods);
                    const mpp = Object.values(row.methods).find(v => v?.avg_mpp)?.avg_mpp;
                    return (
                      <tr key={i} className="border-b border-border/20">
                        <td className="py-1.5 px-3 font-medium">{row.pair}</td>
                        {METHOD_ORDER.map(m => {
                          const v = row.methods[m];
                          const isBest = m === best;
                          return (
                            <td key={m} className={`py-1.5 px-1.5 text-right font-mono text-[10px] ${isBest ? "font-bold text-sky-700" : ""}`}>
                              {v ? v.rho?.toFixed(3) ?? "—" : "\u2014"}
                            </td>
                          );
                        })}
                        <td className="py-1.5 px-1.5 text-right font-mono text-[10px] text-muted-foreground">{mpp || "\u2014"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* SI Inter-Model */}
        {(siRows.length > 0 || hasControlled) && (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="si-inter-model-table">
            <div className="px-3 py-2 bg-violet-500/5 border-b border-border flex items-center justify-between">
              <div>
                <span className="text-xs font-semibold">SI Inter-Model</span>
                <span className="text-[10px] text-muted-foreground ml-1.5">
                  (how similarly do models rate papers directly)
                </span>
              </div>
              {hasControlled && (
                <div className="flex items-center gap-0.5 bg-secondary/50 rounded p-0.5" data-testid="si-mode-toggle">
                  <button
                    className={`px-2 py-0.5 text-[10px] rounded transition-colors ${siMode === "full" ? "bg-background text-foreground font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                    onClick={() => setSiMode("full")}
                  >Full</button>
                  <button
                    className={`px-2 py-0.5 text-[10px] rounded transition-colors ${siMode === "controlled" ? "bg-background text-foreground font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                    onClick={() => setSiMode("controlled")}
                  >Controlled</button>
                </div>
              )}
            </div>
            {siMode === "controlled" && (
              <div className="px-3 py-1.5 bg-violet-500/5 border-b border-border text-[10px] text-muted-foreground">
                Restricted to papers that appear in both models' PW match pools — same paper set as the ranking correlations.
              </div>
            )}
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground bg-secondary/5">
                  <th className="py-1.5 px-3 text-left font-medium">Pair</th>
                  <th className="py-1.5 px-3 text-right font-medium">Spearman {"\u03C1"}</th>
                  <th className="py-1.5 px-3 text-right font-medium">n</th>
                </tr>
              </thead>
              <tbody>
                {siRows.length > 0 ? siRows.map((row, i) => (
                  <tr key={i} className="border-b border-border/20">
                    <td className="py-1.5 px-3 font-medium">{row.pair}</td>
                    <td className="py-1.5 px-3 text-right font-mono font-semibold">{row.rho?.toFixed(3) ?? "—"}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{row.n}</td>
                  </tr>
                )) : (
                  <tr><td colSpan={3} className="py-3 px-3 text-center text-muted-foreground">No data for {siMode} mode</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
