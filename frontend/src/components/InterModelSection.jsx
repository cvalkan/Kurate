import { useState, useEffect } from "react";
import axios from "axios";
import { GitCompare } from "lucide-react";

const METHOD_ORDER = ["reg_wr", "trueskill", "openskill"];

function bestInRow(methods) {
  let best = null;
  let bestVal = -Infinity;
  for (const [k, v] of Object.entries(methods)) {
    if (v.rho > bestVal) { bestVal = v.rho; best = k; }
  }
  return best;
}

const PAIR_LABELS = {
  "anthropic/claude-opus vs gemini/gemini-3-pro-preview": "Claude Opus vs Gemini Pro",
  "anthropic/claude-opus vs openai/gpt-5_2": "Claude Opus vs GPT-5.2",
  "gemini/gemini-3-pro-preview vs openai/gpt-5_2": "Gemini Pro vs GPT-5.2",
  "claude vs gemini": "Claude Opus vs Gemini Pro",
  "claude vs gpt": "Claude Opus vs GPT-5.2",
  "gemini vs gpt": "Gemini Pro vs GPT-5.2",
};

function AgreementTable({ title, subtitle, color, data, testId }) {
  if (!data || Object.keys(data).length === 0) return null;
  const rows = Object.entries(data).map(([key, d]) => ({ pair: PAIR_LABELS[key] || key, ...d }));
  return (
    <div className="border border-border rounded-lg overflow-hidden" data-testid={testId}>
      <div className={`px-3 py-2 ${color} border-b border-border`}>
        <span className="text-xs font-semibold">{title}</span>
        <span className="text-[10px] text-muted-foreground ml-1.5">{subtitle}</span>
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
            {rows.map((row, i) => (
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
  );
}

export function InterModelSection({ pwData, siData, viewMode = "aggregate", osUpdatedAt }) {
  const [siMode, setSiMode] = useState("full");
  const isAvg = viewMode === "average";
  const pwRows = (isAvg && pwData?.avg_pw_inter_model?.length ? pwData.avg_pw_inter_model : pwData?.pw_inter_model) || [];
  const methodLabels = pwData?.method_labels || {};
  const siCorrFull = siData?.inter_model_si || {};
  const siCorrControlled = siData?.controlled_inter_model_si || {};
  const siCorr = siMode === "controlled" ? siCorrControlled : siCorrFull;
  const hasOs = pwRows.some(r => Object.keys(r.methods || {}).some(k => k.startsWith("openskill")));
  const hasControlled = Object.keys(siCorrControlled).length > 0;

  // PW match-level agreement (actual pair-level, not median-split)
  const pwAgreement = pwData?.pw_match_agreement || (isAvg ? pwData?.avg_agreement : pwData?.agreement) || {};

  // SI match-level agreement
  const siAgreementFull = siData?.si_match_agreement || {};
  const siAgreementControlled = siData?.si_match_agreement_controlled || {};
  const siAgreement = siMode === "controlled" ? siAgreementControlled : siAgreementFull;
  const hasSiAgreement = Object.keys(siAgreementFull).length > 0;

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
      siRows.push({ pair: `${modelLabelMap[m1]} vs ${modelLabelMap[m2]}`, rho: data.spearman, n: data.n });
    }
  }

  const ModeToggle = ({ value, onChange }) => (
    <div className="flex items-center gap-0.5 bg-secondary/50 rounded p-0.5">
      <button className={`px-2 py-0.5 text-[10px] rounded transition-colors ${value === "full" ? "bg-background text-foreground font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
        onClick={() => onChange("full")}>Full</button>
      <button className={`px-2 py-0.5 text-[10px] rounded transition-colors ${value === "controlled" ? "bg-background text-foreground font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
        onClick={() => onChange("controlled")}>Controlled</button>
    </div>
  );

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

      {/* Match-level agreement: PW and SI side by side */}
      {(Object.keys(pwAgreement).length > 0 || hasSiAgreement) && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Match-Level Agreement</h3>
            {hasControlled && <ModeToggle value={siMode} onChange={setSiMode} />}
          </div>
          {siMode === "controlled" && (
            <p className="text-[10px] text-muted-foreground mb-2">
              SI restricted to papers that appear in both models' PW match pools — same paper set as the PW agreement.
            </p>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AgreementTable
              title="PW Match Agreement"
              subtitle="(when two models judge the same pair, how often do they pick the same winner?)"
              color="bg-sky-500/5"
              data={pwAgreement}
              testId="pw-agreement-table"
            />
            {hasSiAgreement && (
              <AgreementTable
                title={`SI Score Agreement (${siMode})`}
                subtitle="(for paper pairs, how often do two models' SI scores agree on ordering?)"
                color="bg-violet-500/5"
                data={siAgreement}
                testId="si-agreement-table"
              />
            )}
          </div>
        </div>
      )}

      {/* Ranking correlations: PW and SI side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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

        {siRows.length > 0 && (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="si-inter-model-table">
            <div className="px-3 py-2 bg-violet-500/5 border-b border-border">
              <span className="text-xs font-semibold">SI Inter-Model ({siMode})</span>
              <span className="text-[10px] text-muted-foreground ml-1.5">
                (how similarly do models rate papers directly)
              </span>
            </div>
            <table className="w-full text-xs">
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

      {/* SI vs PW Simulation */}
      <SimulationTable />

    </div>
  );
}


const API_SIM = process.env.REACT_APP_BACKEND_URL;
const PAIR_LABELS_SHORT = {
  "claude vs gemini": "Claude vs Gemini",
  "claude vs gpt": "Claude vs GPT",
  "gemini vs gpt": "Gemini vs GPT",
};

function SimulationTable() {
  const [data, setData] = useState(null);
  useEffect(() => {
    axios.get(`${API_SIM}/api/si-pw-simulation`).then(r => setData(r.data)).catch(() => {});
  }, []);

  if (!data || !data.length) return null;
  const mppValues = data[0]?.simulated?.map(s => s.mpp) || [];

  return (
    <div className="mt-4 border border-border rounded-lg overflow-hidden" data-testid="simulation-table">
      <div className="px-3 py-2 bg-amber-500/5 border-b border-border">
        <span className="text-xs font-semibold">Ranking Correlation: SI Scores vs Simulated Pairwise Tournament</span>
      </div>
      <div className="px-3 py-2 text-[10px] text-muted-foreground border-b border-border bg-secondary/5">
        Each model's SI scores deterministically resolve simulated matches (higher score wins).
        TrueSkill rankings are then computed from these virtual matches at different depths.
        The gap between "SI direct" and the simulated rows quantifies the information loss
        from converting absolute scores to binary win/loss. Only ranking correlation varies —
        match-level agreement stays constant (see tables above).
        Note: SI correlations here are computed on the subset of papers appearing in shared PW pairs (~2,800),
        which may differ slightly from the full SI Inter-Model correlations above (~5,400 papers).
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-muted-foreground bg-secondary/5">
              <th className="py-1.5 px-3 text-left font-medium">Method</th>
              {data.map(d => (
                <th key={d.pair} className="py-1.5 px-3 text-right font-medium">{PAIR_LABELS_SHORT[d.pair] || d.pair}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border/20 bg-violet-500/5">
              <td className="py-1.5 px-3 font-medium">SI (direct scores)</td>
              {data.map(d => (
                <td key={d.pair} className="py-1.5 px-3 text-right font-mono font-semibold">
                  {d.si_correlation.toFixed(3)}
                  <span className="text-[9px] text-muted-foreground ml-1">n={d.n_papers}</span>
                </td>
              ))}
            </tr>
            {mppValues.map(mpp => (
              <tr key={mpp} className="border-b border-border/20">
                <td className="py-1.5 px-3 text-muted-foreground">Simulated PW @ {mpp} m/p</td>
                {data.map(d => {
                  const sim = d.simulated.find(s => s.mpp === mpp);
                  return (
                    <td key={d.pair} className="py-1.5 px-3 text-right font-mono">{sim?.correlation.toFixed(3) ?? "\u2014"}</td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
