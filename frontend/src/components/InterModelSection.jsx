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

export function InterModelSection({ pwData, siData, viewMode = "aggregate", osUpdatedAt }) {
  const isAvg = viewMode === "average";
  const pwRows = (isAvg && pwData?.avg_pw_inter_model?.length ? pwData.avg_pw_inter_model : pwData?.pw_inter_model) || [];
  const methodLabels = pwData?.method_labels || {};
  const siCorr = siData?.inter_model_si || {};
  const hasOs = pwRows.some(r => Object.keys(r.methods || {}).some(k => k.startsWith("openskill")));

  if (pwRows.length === 0 && Object.keys(siCorr).length === 0) return null;

  // Build SI rows from inter_model_si dict
  const siRows = [];
  const modelLabelMap = { claude: "Claude Opus", gpt: "GPT-5.2", gemini: "Gemini 3 Pro" };
  const modelOrder = ["claude", "gpt", "gemini"];
  for (let i = 0; i < modelOrder.length; i++) {
    for (let j = i + 1; j < modelOrder.length; j++) {
      const m1 = modelOrder[i], m2 = modelOrder[j];
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
  }

  return (
    <div className="mb-8" data-testid="inter-model-section">
      <div className="mb-3">
        <h2 className="font-heading text-lg font-semibold tracking-tight flex items-center gap-2">
          <GitCompare className="h-4 w-4 text-muted-foreground" />
          Inter-Model Agreement
        </h2>
        <p className="text-muted-foreground text-xs mt-1 max-w-2xl">
          How similarly do Claude Opus, GPT-5.2, and Gemini 3 Pro rank papers?
          PW uses each model's own head-to-head match results; SI uses each model's direct 1–10 scores.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* PW Inter-Model */}
        {pwRows.length > 0 && (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-inter-model-table">
            <div className="px-3 py-2 bg-sky-500/5 border-b border-border">
              <span className="text-xs font-semibold">PW Inter-Model</span>
              <span className="text-[10px] text-muted-foreground ml-1.5">
                (how similarly do models rank papers from their pairwise matches)
              </span>
              {hasOs && osUpdatedAt && <span className="text-[9px] text-muted-foreground/50 ml-1">· OS updated {new Date(osUpdatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
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
        {siRows.length > 0 && (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="si-inter-model-table">
            <div className="px-3 py-2 bg-violet-500/5 border-b border-border">
              <span className="text-xs font-semibold">SI Inter-Model</span>
              <span className="text-[10px] text-muted-foreground ml-1.5">
                (how similarly do models rate papers directly)
              </span>
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border text-muted-foreground bg-secondary/5">
                  <th className="py-1.5 px-3 text-left font-medium">Pair</th>
                  <th className="py-1.5 px-3 text-right font-medium">Spearman {"\u03C1"}</th>
                  <th className="py-1.5 px-3 text-right font-medium">n</th>
                </tr>
              </thead>
              <tbody>
                {siRows.map((row, i) => (
                  <tr key={i} className="border-b border-border/20">
                    <td className="py-1.5 px-3 font-medium">{row.pair}</td>
                    <td className="py-1.5 px-3 text-right font-mono font-semibold">{row.rho?.toFixed(3) ?? "—"}</td>
                    <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{row.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
