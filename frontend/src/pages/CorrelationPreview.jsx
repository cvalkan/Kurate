/**
 * CorrelationPreview — clean typographic redesign of the Model Correlation page.
 *
 * Design system (4 sizes only):
 *   text-xs  (12px) — footnotes, axis labels, sample sizes
 *   text-sm  (14px) — body text, table cells, descriptions
 *   text-base(16px) — sub-section titles, card headers
 *   text-lg  (18px) — section headings
 *
 * Weights: font-semibold (titles), font-medium (labels/stats), normal (body)
 * Model colors: Claude=#ea580c  GPT=#16a34a  Gemini=#2563eb (everywhere)
 */

import { useState, useEffect } from "react";
import axios from "axios";
import { Bot, Crosshair, Info, AlertTriangle, CheckCircle, TrendingUp, ShieldCheck } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

/* ─── Unified model config ─── */
const MODELS = {
  "anthropic/claude-opus": { label: "Claude Opus", color: "#ea580c", bg: "bg-orange-50", border: "border-orange-200", text: "text-orange-700" },
  "gemini/gemini-3-pro-preview": { label: "Gemini 3 Pro", color: "#2563eb", bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700" },
  "openai/gpt-5_2": { label: "GPT-5.2", color: "#16a34a", bg: "bg-green-50", border: "border-green-200", text: "text-green-700" },
};

const BIAS_MODELS = {
  "gpt-5.2": { label: "GPT-5.2", color: "#16a34a" },
  "claude-opus-4-5-20251101": { label: "Claude Opus 4.5", color: "#ea580c" },
  "claude-opus-4-6": { label: "Claude Opus 4.6", color: "#c2410c" },
  "gemini-3-pro-preview": { label: "Gemini 3 Pro", color: "#2563eb" },
};

function modelCfg(key) {
  return MODELS[key] || { label: key.split("/").pop(), color: "#6b7280", bg: "bg-secondary", border: "border-border", text: "text-foreground" };
}

function shortLabel(key) { return modelCfg(key).label; }

/* ─── Reusable section wrapper ─── */
function Section({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="mb-8">
      <div className="flex items-center gap-2 mb-1">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        <h2 className="text-base font-semibold">{title}</h2>
      </div>
      {subtitle && <p className="text-sm text-muted-foreground mb-4">{subtitle}</p>}
      {children}
    </div>
  );
}

/* ─── Correlation value with consistent color coding ─── */
function CorrVal({ value, size = "sm" }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const cls = value > 0.7 ? "text-green-600" : value > 0.4 ? "text-amber-600" : "text-red-600";
  return <span className={`font-mono font-medium ${cls} ${size === "lg" ? "text-base" : "text-sm"}`}>{value.toFixed(2)}</span>;
}

/* ─── Model Cards ─── */
function ModelCards({ models }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
      {models.map(m => {
        const cfg = modelCfg(m.key);
        return (
          <div key={m.key} className={`p-3 rounded-lg border ${cfg.border} ${cfg.bg}`} data-testid={`model-card-${m.key}`}>
            <div className="flex items-center gap-2 mb-1">
              <Bot className={`h-4 w-4 ${cfg.text}`} />
              <span className={`text-sm font-semibold ${cfg.text}`}>{cfg.label}</span>
            </div>
            <span className="text-sm text-muted-foreground">
              <span className="font-mono font-medium text-foreground">{m.total_matches?.toLocaleString()}</span> matches
            </span>
            {cfg.label === "Claude Opus" && (
              <span className="block text-xs text-muted-foreground mt-0.5">Opus 4.6 (and 4.5 until Feb 22, 2026)</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Rank Correlations Table ─── */
function RankCorrelationsTable({ correlations, tsCorrelations, models }) {
  const pairs = Object.keys(correlations);
  return (
    <div className="overflow-x-auto mb-6">
      <table className="w-full text-sm" data-testid="rank-correlations-table">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Pair</th>
            <th className="text-left py-2 pr-4 font-medium text-muted-foreground" colSpan={3}>Win Rate</th>
            <th className="text-left py-2 pr-4 font-medium text-muted-foreground" colSpan={3}>TrueSkill</th>
          </tr>
          <tr className="border-b border-border/40">
            <th />
            <th className="text-left py-1 pr-3 text-xs font-medium text-muted-foreground">Spearman</th>
            <th className="text-left py-1 pr-3 text-xs font-medium text-muted-foreground">Pearson</th>
            <th className="text-left py-1 pr-3 text-xs font-medium text-muted-foreground">n</th>
            <th className="text-left py-1 pr-3 text-xs font-medium text-muted-foreground">Spearman</th>
            <th className="text-left py-1 pr-3 text-xs font-medium text-muted-foreground">Pearson</th>
            <th className="text-left py-1 pr-3 text-xs font-medium text-muted-foreground">n</th>
          </tr>
        </thead>
        <tbody>
          {pairs.map(pair => {
            const wr = correlations[pair];
            const ts = tsCorrelations?.[pair];
            const pairLabel = pair.split(" vs ").map(k => {
              const m = models.find(mo => mo.key === k);
              return m ? shortLabel(m.key) : k.split("/").pop();
            }).join(" vs ");
            return (
              <tr key={pair} className="border-b border-border/20">
                <td className="py-2 pr-4 font-medium">{pairLabel}</td>
                <td className="py-2 pr-3"><CorrVal value={wr?.spearman_r} /></td>
                <td className="py-2 pr-3"><CorrVal value={wr?.pearson_r} /></td>
                <td className="py-2 pr-3 text-xs text-muted-foreground font-mono">{wr?.n_papers?.toLocaleString()}</td>
                <td className="py-2 pr-3"><CorrVal value={ts?.spearman_r} /></td>
                <td className="py-2 pr-3"><CorrVal value={ts?.pearson_r} /></td>
                <td className="py-2 pr-3 text-xs text-muted-foreground font-mono">{ts?.n_papers?.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground mt-2">
        Low Win Rate correlations (~0.6) reflect sampling noise, not genuine model disagreement.
        TrueSkill recovers the shared signal by adjusting for opponent strength.
      </p>
    </div>
  );
}

/* ─── Pairwise Agreement Table ─── */
function AgreementTable({ agreement, models }) {
  return (
    <div className="overflow-x-auto mb-6">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Pair</th>
            <th className="text-right py-2 px-3 font-medium text-muted-foreground">Agree</th>
            <th className="text-right py-2 px-3 font-medium text-muted-foreground">Disagree</th>
            <th className="text-right py-2 px-3 font-medium text-muted-foreground">Rate</th>
            <th className="text-right py-2 px-3 font-medium text-muted-foreground">n</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(agreement).map(([pair, stats]) => {
            const pairLabel = pair.split(" vs ").map(k => {
              const m = models.find(mo => mo.key === k);
              return m ? shortLabel(m.key) : k.split("/").pop();
            }).join(" vs ");
            return (
              <tr key={pair} className="border-b border-border/20">
                <td className="py-2 pr-4 font-medium">{pairLabel}</td>
                <td className="text-right py-2 px-3 font-mono">{stats.agree?.toLocaleString()}</td>
                <td className="text-right py-2 px-3 font-mono">{stats.disagree?.toLocaleString()}</td>
                <td className="text-right py-2 px-3 font-mono font-medium">{stats.rate != null ? `${(stats.rate * 100).toFixed(1)}%` : "—"}</td>
                <td className="text-right py-2 px-3 text-xs text-muted-foreground font-mono">{stats.n?.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Inter-Model Section ─── */
function InterModelTables({ pwCorr, siCorr }) {
  const pairOrder = [
    ["anthropic/claude-opus", "gemini/gemini-3-pro-preview"],
    ["anthropic/claude-opus", "openai/gpt-5_2"],
    ["gemini/gemini-3-pro-preview", "openai/gpt-5_2"],
  ];
  const siPairOrder = [["claude", "gemini"], ["claude", "gpt"], ["gemini", "gpt"]];
  const siLabels = { claude: "Claude Opus", gpt: "GPT-5.2", gemini: "Gemini 3 Pro" };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      {/* PW Inter-Model */}
      <div>
        <h3 className="text-sm font-semibold mb-2">Pairwise (PW) Inter-Model</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Pair</th>
              <th className="text-right py-2 px-2 font-medium text-muted-foreground">Spearman</th>
              <th className="text-right py-2 px-2 font-medium text-muted-foreground">n</th>
            </tr>
          </thead>
          <tbody>
            {pwCorr && pairOrder.map(([k1, k2]) => {
              const key = `${k1} vs ${k2}`;
              const data = pwCorr[key] || pwCorr[`${k2} vs ${k1}`];
              if (!data) return null;
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-2 pr-3 font-medium">{shortLabel(k1)} vs {shortLabel(k2)}</td>
                  <td className="text-right py-2 px-2"><CorrVal value={data.spearman} /></td>
                  <td className="text-right py-2 px-2 text-xs text-muted-foreground font-mono">{data.n?.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* SI Inter-Model */}
      <div>
        <h3 className="text-sm font-semibold mb-2">Single-Item (SI) Inter-Model</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Pair</th>
              <th className="text-right py-2 px-2 font-medium text-muted-foreground">Spearman</th>
              <th className="text-right py-2 px-2 font-medium text-muted-foreground">n</th>
            </tr>
          </thead>
          <tbody>
            {siCorr && siPairOrder.map(([m1, m2]) => {
              const key = `${m1} vs ${m2}`;
              const data = siCorr[key] || siCorr[`${m2} vs ${m1}`];
              if (!data) return null;
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-2 pr-3 font-medium">{siLabels[m1]} vs {siLabels[m2]}</td>
                  <td className="text-right py-2 px-2"><CorrVal value={data.spearman} /></td>
                  <td className="text-right py-2 px-2 text-xs text-muted-foreground font-mono">{data.n?.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Positional Bias Bars ─── */
function BiasBar({ model, pos1Rate, total, pValue, significant, color }) {
  const pos2Rate = 100 - pos1Rate;
  const magnitude = Math.abs(pos1Rate - 50);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium" style={{ color }}>{model}</span>
        <span className="text-muted-foreground font-mono">{total.toLocaleString()} matches</span>
      </div>
      <div className="relative h-7 rounded overflow-hidden bg-secondary/20 flex">
        <div className="h-full flex items-center justify-end pr-2 text-xs font-mono font-medium transition-all duration-700"
          style={{ width: `${pos1Rate}%`, backgroundColor: `${color}25`, borderRight: "2px solid var(--border)", color }}>
          {pos1Rate.toFixed(1)}%
        </div>
        <div className="h-full flex items-center justify-start pl-2 text-xs font-mono text-muted-foreground transition-all duration-700"
          style={{ width: `${pos2Rate}%` }}>
          {pos2Rate.toFixed(1)}%
        </div>
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-foreground/20 pointer-events-none" />
      </div>
      <div className="text-xs text-muted-foreground">
        {significant ? (
          <span className="flex items-center gap-1 text-amber-600">
            <AlertTriangle className="h-3 w-3" />
            Significant bias ({magnitude.toFixed(1)}pp, p={pValue < 0.001 ? "<0.001" : pValue.toFixed(3)})
          </span>
        ) : (
          <span className="flex items-center gap-1 text-emerald-600">
            <CheckCircle className="h-3 w-3" />
            No significant bias (p={pValue.toFixed(3)})
          </span>
        )}
      </div>
    </div>
  );
}

/* ─── Coherence Table ─── */
function CoherenceTable({ coherence }) {
  if (!coherence?.models) return null;
  const modelLabels = { "Claude Opus": "#ea580c", "GPT-5.2": "#16a34a", "Gemini 3 Pro": "#2563eb" };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Model</th>
            <th className="text-right py-2 px-2 font-medium text-muted-foreground">Agreement</th>
            <th className="text-right py-2 px-2 font-medium text-muted-foreground">n pairs</th>
          </tr>
        </thead>
        <tbody>
          {coherence.models.map(m => (
            <tr key={m.model} className="border-b border-border/20">
              <td className="py-2 pr-3 font-medium" style={{ color: modelLabels[m.model] || "#6b7280" }}>{m.model}</td>
              <td className="text-right py-2 px-2 font-mono font-medium">{(m.overall_rate * 100).toFixed(1)}%</td>
              <td className="text-right py-2 px-2 text-xs text-muted-foreground font-mono">{m.total_pairs?.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Main Preview Page ─── */
export default function CorrelationPreview() {
  const [data, setData] = useState(null);
  const [biasData, setBiasData] = useState(null);
  const [coherence, setCoherence] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/api/model-analysis`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/positional-bias`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/score-pairwise-coherence`).then(r => r.data).catch(() => null),
    ]).then(([analysis, bias, coh]) => {
      setData(analysis);
      setBiasData(bias);
      setCoherence(coh);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="max-w-5xl mx-auto p-6 text-sm text-muted-foreground animate-pulse">Loading...</div>;
  if (!data) return <div className="max-w-5xl mx-auto p-6 text-sm text-destructive">Failed to load data.</div>;

  const { models, correlations, ts_correlations, agreement, inter_model_pw, inter_model_si } = data;

  return (
    <div className="max-w-5xl mx-auto px-6 py-8" data-testid="correlation-preview">
      {/* Page header */}
      <h1 className="text-lg font-semibold mb-1">Model Correlation</h1>
      <p className="text-sm text-muted-foreground mb-6">
        How well do Claude Opus, GPT-5.2, and Gemini 3 Pro agree on paper rankings?
      </p>

      {/* Matchmaking bias note */}
      <div className="border border-border rounded-lg p-3 bg-secondary/5 mb-6">
        <div className="flex items-start gap-2">
          <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Matchmaking bias:</span>{" "}
            The tournament uses adaptive matchmaking that over-samples contested pairs. Agreement rates
            are biased downward — models are disproportionately tested on the hardest cases.
          </p>
        </div>
      </div>

      {/* Model cards */}
      {models && <ModelCards models={models} />}

      {/* Rank Correlations */}
      {correlations && (
        <Section icon={TrendingUp} title="Rank Correlations" subtitle="Pooled correlation across all papers.">
          <RankCorrelationsTable correlations={correlations} tsCorrelations={ts_correlations} models={models} />
        </Section>
      )}

      {/* Pairwise Agreement */}
      {agreement && (
        <Section icon={ShieldCheck} title="Pairwise Agreement" subtitle="How often do two models pick the same winner for the same paper pair?">
          <AgreementTable agreement={agreement} models={models} />
        </Section>
      )}

      {/* Inter-Model Correlations */}
      <Section icon={TrendingUp} title="Inter-Model Correlations" subtitle="How similarly do the models rank papers, measured via pairwise win rates and single-item scores?">
        <InterModelTables pwCorr={inter_model_pw} siCorr={inter_model_si} />
      </Section>

      {/* Score-Pairwise Coherence */}
      {coherence?.models && (
        <Section icon={ShieldCheck} title="Score-Pairwise Coherence" subtitle="When a model's SI score predicts A > B, how often does it also pick A in a head-to-head?">
          <CoherenceTable coherence={coherence} />
        </Section>
      )}

      {/* Positional Bias */}
      {biasData?.models?.length > 0 && (
        <Section icon={Crosshair} title="Positional Bias"
          subtitle="Does the order in which papers are presented affect which one wins?">
          <div className="border border-border rounded-lg p-3 bg-secondary/5 mb-4">
            <div className="flex items-start gap-2">
              <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
              <p className="text-sm text-muted-foreground">
                The pipeline randomly flips presentation order for each match. A 50% split = no bias.
                P-values from exact binomial test (H<sub>0</sub>: p = 0.5).
              </p>
            </div>
          </div>
          {/* Overall */}
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-2">Overall</h3>
            <div className="relative h-8 rounded overflow-hidden bg-secondary/20 flex">
              <div className="h-full flex items-center justify-center text-sm font-mono font-medium transition-all duration-700"
                style={{ width: `${biasData.overall.pos1_rate}%`, backgroundColor: "rgba(99,102,241,0.15)", color: "#6366f1" }}>
                {biasData.overall.pos1_rate.toFixed(1)}%
              </div>
              <div className="h-full flex items-center justify-center text-sm font-mono text-muted-foreground transition-all duration-700"
                style={{ width: `${100 - biasData.overall.pos1_rate}%` }}>
                {(100 - biasData.overall.pos1_rate).toFixed(1)}%
              </div>
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-foreground/30 pointer-events-none" />
            </div>
            <div className="text-center text-xs text-muted-foreground mt-1">
              {biasData.overall.total.toLocaleString()} matches
            </div>
          </div>
          {/* Per model */}
          <h3 className="text-sm font-semibold mb-3">By Model</h3>
          <div className="space-y-4">
            {biasData.models.map(m => {
              const cfg = BIAS_MODELS[m.model] || { label: m.model, color: "#6b7280" };
              return (
                <BiasBar key={m.model} model={cfg.label} pos1Rate={m.pos1_rate} total={m.total}
                  pValue={m.p_value} significant={m.significant} color={cfg.color} />
              );
            })}
          </div>

          {/* Summary table */}
          <div className="mt-6 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Model</th>
                  <th className="text-right py-2 px-2 font-medium text-muted-foreground">Matches</th>
                  <th className="text-right py-2 px-2 font-medium text-muted-foreground">Pos 1</th>
                  <th className="text-right py-2 px-2 font-medium text-muted-foreground">Pos 2</th>
                  <th className="text-right py-2 px-2 font-medium text-muted-foreground">Pos 1 Rate</th>
                  <th className="text-right py-2 px-2 font-medium text-muted-foreground">p-value</th>
                </tr>
              </thead>
              <tbody>
                {biasData.models.map(m => {
                  const cfg = BIAS_MODELS[m.model] || { label: m.model, color: "#6b7280" };
                  return (
                    <tr key={m.model} className="border-b border-border/20">
                      <td className="py-2 pr-3 font-medium" style={{ color: cfg.color }}>{cfg.label}</td>
                      <td className="text-right py-2 px-2 font-mono">{m.total.toLocaleString()}</td>
                      <td className="text-right py-2 px-2 font-mono">{m.pos1_wins.toLocaleString()}</td>
                      <td className="text-right py-2 px-2 font-mono">{m.pos2_wins.toLocaleString()}</td>
                      <td className="text-right py-2 px-2 font-mono font-medium">{m.pos1_rate.toFixed(1)}%</td>
                      <td className="text-right py-2 px-2 font-mono">{m.p_value < 0.001 ? "<0.001" : m.p_value.toFixed(4)}{m.significant ? " *" : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}
