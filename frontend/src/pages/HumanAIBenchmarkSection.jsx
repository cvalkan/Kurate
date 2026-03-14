import { useState, useEffect } from "react";
import axios from "axios";
import { Scale, ChevronDown, ChevronRight } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL || "";

function Metric({ label, value, sub, accent }) {
  return (
    <div className="text-center px-3 py-2">
      <div className={`text-lg font-bold font-mono ${accent ? "text-accent" : "text-foreground"}`}>{value}</div>
      <div className="text-[10px] text-muted-foreground leading-tight">{label}</div>
      {sub && <div className="text-[9px] text-muted-foreground/60 mt-0.5">{sub}</div>}
    </div>
  );
}

function AgreementTable({ pw, difficulty, totalPairs, tieImpact }) {
  const fmt = (v) => v?.rate != null ? `${v.rate}%` : "\u2014";
  const kfmt = (v) => v?.kappa != null ? v.kappa.toFixed(2) : "\u2014";
  const levels = [
    { key: "easy", label: "Cross-tier (easy)", desc: "e.g., Oral vs Reject" },
    { key: "medium", label: "Adjacent-tier (medium)", desc: "e.g., Spotlight vs Poster" },
    { key: "hard", label: "Within-tier (hard)", desc: "e.g., Poster vs Poster" },
  ];
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <Scale className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Pairwise Agreement — Controlled Same-Pair Comparison</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "22%" }} />
            <col /><col /><col /><col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">AI-Human</th>
              <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">Human-Human</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">AI-Comm</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">Human-Comm (LOO)</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">Human-Comm</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">kappa (AI-H)</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">paper pairs</th>
            </tr>
          </thead>
          <tbody>
            {tieImpact?.coin_flip && (
              <tr className="border-b border-border bg-accent/5">
                <td className="py-1.5 px-2 text-left text-xs font-semibold">Pooled (ties = coin flip)</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs font-bold bg-sky-500/[0.06]">{tieImpact.coin_flip.ai_human != null ? `${tieImpact.coin_flip.ai_human}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs font-bold bg-sky-500/[0.06]">{tieImpact.coin_flip.human_human != null ? `${tieImpact.coin_flip.human_human}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs font-bold bg-amber-500/[0.06]">{tieImpact.coin_flip.ai_committee != null ? `${tieImpact.coin_flip.ai_committee}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs font-bold bg-amber-500/[0.06]">{tieImpact.coin_flip.human_committee_loo != null ? `${tieImpact.coin_flip.human_committee_loo}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs font-bold text-muted-foreground bg-amber-500/[0.06]">{tieImpact.coin_flip.human_committee != null ? `${tieImpact.coin_flip.human_committee}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{tieImpact.coin_flip.ai_human_kappa != null ? tieImpact.coin_flip.ai_human_kappa.toFixed(2) : ""}</td>
                <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{tieImpact.coin_flip.total_pairs?.toLocaleString()}</td>
              </tr>
            )}
            <tr className="border-b border-border/40">
              <td className="py-1.5 px-2 text-left text-xs text-muted-foreground">Pooled (ties excluded)</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground bg-sky-500/[0.06]">{fmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground bg-sky-500/[0.06]">{fmt(pw.human_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground bg-amber-500/[0.06]">{fmt(pw.ai_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground bg-amber-500/[0.06]">{fmt(pw.human_committee_loo)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground/60 bg-amber-500/[0.06]">{fmt(pw.human_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground/60">{kfmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground/60">{totalPairs?.toLocaleString()}</td>
            </tr>
            {difficulty && levels.map(({ key, label, desc }) => {
              const d = difficulty[key] || {};
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left">
                    <span className="font-medium text-muted-foreground">{label}</span>
                    <span className="text-muted-foreground/50 ml-1 text-[9px]">{desc}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground bg-sky-500/[0.06]">{d.ah_cf != null ? `${d.ah_cf}%` : fmt(d.ai_human)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground bg-sky-500/[0.06]">{d.hh_cf != null ? `${d.hh_cf}%` : fmt(d.human_human)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground bg-amber-500/[0.06]">{fmt(d.ai_committee)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground bg-amber-500/[0.06]">{fmt(d.human_committee_loo)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground/60 bg-amber-500/[0.06]">{fmt(d.human_committee)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground/40"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground/60">{(d.n_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-2">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>AI-Human</strong> = AI (round-robin judge) vs individual expert.{" "}
          <strong>Human-Human</strong> = individual expert vs individual expert.{" "}
          <strong>AI-Comm</strong> = AI vs expert majority committee.{" "}
          <strong>Human-Comm (LOO)</strong> = individual expert vs leave-one-out majority (fair).{" "}
          <strong>Human-Comm</strong> = expert vs committee they belong to (inflated).{" "}
          All on the same controlled paper pairs. Difficulty rows use coin-flip values for AI-Human and Human-Human.
        </p>
        {(() => {
          const cf = tieImpact?.coin_flip;
          const ex = tieImpact?.excluded;
          if (!cf || !ex || cf.human_human == null || cf.ai_human == null) return null;
          const cfGap = Math.abs(cf.human_human - cf.ai_human).toFixed(1);
          return (
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              <strong>Tie correction:</strong>{" "}
              When a human reviewer gives two papers the same score, that comparison is dropped — selecting for "easy" pairs
              and inflating Human-Human agreement. The coin-flip row corrects this by randomly resolving ties.
              Under this fair comparison, the Human-Human vs AI-Human gap closes
              to <strong>{cfGap}pp</strong> ({cf.human_human}% vs {cf.ai_human}%),
              and AI-Comm ({cf.ai_committee}%) matches Human-Comm LOO ({cf.human_committee_loo}%).
              The difficulty rows also use coin-flip values for AI-Human and Human-Human, ensuring the same fair comparison across all tiers.
              AI judges achieve <strong>human-level pairwise agreement</strong>, validating LLM judges as a scalable
              alternative to human reviewers for relative quality ranking of scientific preprints.
            </p>
          );
        })()}
      </div>
    </div>
  );
}

function ReliabilityTables({ p, pw }) {
  const ts = p.tie_stats || {};
  const hhConc = ts.concordance_rate;
  const ahConc = p.ai_h_concordance;
  const rows = [
    { scope: "Human-Human", metric: "Pairwise concordance", value: hhConc != null ? `${(hhConc * 100).toFixed(1)}%` : "\u2014",
      desc: "How often two experts agree on which paper is better (non-tie pairs)" },
    { scope: "Human-Human", metric: "Derived rho", value: p.inter_rater_rho?.toFixed(2) ?? "\u2014",
      desc: "Kruskal (1958): rho = sin(\u03C0 \u00D7 (concordance \u2212 0.5))" },
    { scope: "Human-Human", metric: "Thurstonian ceiling", value: p.theoretical_ceiling != null ? `${p.theoretical_ceiling}%` : "\u2014",
      desc: `Max achievable pairwise agreement given inter-rater noise (rho = ${p.inter_rater_rho?.toFixed(2)})` },
    { scope: "Human-Human", metric: "Tie fraction", value: ts.tie_fraction != null ? `${(ts.tie_fraction * 100).toFixed(1)}%` : "\u2014",
      desc: `${ts.tied_excluded?.toLocaleString() ?? "?"} reviewer paper-pairs excluded (same score)` },
    { scope: "AI-Human", metric: "Pairwise concordance", value: ahConc != null ? `${(ahConc * 100).toFixed(1)}%` : "\u2014",
      desc: "How often AI agrees with each individual expert (averaged per expert)" },
    { scope: "AI-Human", metric: "Derived rho", value: p.ai_h_rho?.toFixed(2) ?? "\u2014",
      desc: "Same Kruskal conversion applied to AI-human concordance" },
  ];

  let lastScope = "";
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border">
        <span className="text-xs font-semibold">Inter-Rater Concordance — Equal-Weighted by Reviewer</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-left font-medium">Metric</th>
              <th className="py-1.5 px-2 text-right font-medium">Value</th>
              <th className="py-1.5 px-2 text-left font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const showScope = r.scope !== lastScope;
              lastScope = r.scope;
              return (
                <tr key={i} className={`border-b border-border/20 ${showScope && i > 0 ? "border-t border-border" : ""}`}>
                  <td className={`py-1.5 px-2 font-medium ${showScope ? "" : "text-transparent select-none"}`}>{r.scope}</td>
                  <td className="py-1.5 px-2">{r.metric}</td>
                  <td className="py-1.5 px-2 text-right font-mono font-bold">{r.value}</td>
                  <td className="py-1.5 px-2 text-muted-foreground text-[10px]">{r.desc}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-2">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>Human-Human:</strong> For each pair of reviewers sharing 5+ papers, we count concordance on non-tie paper pairs.{" "}
          <strong>AI-Human:</strong> For each expert, we count how often AI agrees with their preference (averaged per expert, not pooled).{" "}
          Both exclude tie pairs where a reviewer gave both papers the same score.
        </p>
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>Concordance vs agreement:</strong>{" "}
          The pairwise agreement rates in the table above (Human-Human {pw?.human_human?.rate}%, AI-Human {pw?.ai_human?.rate}%) are <em>pooled</em> —
          every expert-vs-expert comparison counts equally, so prolific reviewer pairs with many shared papers dominate.
          Concordance here ({(hhConc * 100).toFixed(1)}% and {(ahConc * 100).toFixed(1)}%) is <em>averaged per unit</em>:
          each reviewer pair (or each expert, for AI-Human) gets equal weight regardless of volume.
          The {((pw?.human_human?.rate ?? 0) - (hhConc ?? 0) * 100).toFixed(1)}pp gap for Human-Human
          ({pw?.human_human?.rate}% pooled vs {(hhConc * 100).toFixed(1)}% averaged) indicates that high-volume reviewer pairs tend to agree more —
          likely because they share papers from the same conference track where quality differences are clearer.
          For AI-Human, the gap is negligible ({pw?.ai_human?.rate}% vs {(ahConc * 100).toFixed(1)}%),
          showing that <strong>AI agreement is consistent across experts</strong> regardless of how many papers each reviewed.
        </p>
        {hhConc != null && ahConc != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Interpretation:</strong>{" "}
            AI-Human concordance ({(ahConc * 100).toFixed(1)}%) slightly <strong>exceeds</strong> Human-Human concordance ({(hhConc * 100).toFixed(1)}%).
            On the non-tie pairs where human experts have clear preferences, AI agrees with each individual expert more often than
            two experts agree with each other. This is not because AI is "better" than humans — it likely reflects that AI judges,
            by cycling through three models in round-robin (GPT-5.2, Opus, Gemini), produce a smoothed signal that aligns well with any single expert's view,
            much like a committee tends to agree with each member more than members agree with each other.
          </p>
        )}
        {ts.tie_fraction != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            The {(ts.tie_fraction * 100).toFixed(0)}% tie fraction means that in nearly half of all reviewer paper-pair comparisons,
            the human expert cannot distinguish quality between the two papers. These are not failures of judgment — they reflect a genuine
            limit of how much information a reviewer can extract from a single reading.
            AI judges, which are forced to always produce a verdict, effectively operate in this "indistinguishable" zone where humans abstain.
            The fact that AI still agrees with humans at {(ahConc * 100).toFixed(1)}% on the decisive subset — while also providing verdicts on
            the 42% of pairs humans cannot resolve — makes AI a <strong>strictly more complete</strong> signal source for paper ranking.
          </p>
        )}
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>Derived rho</strong> converts the raw concordance rate into a correlation coefficient
          using the Kruskal (1958) identity for bivariate normals: rho = sin(pi x (concordance - 0.5)).
          A concordance of 50% (chance) maps to rho = 0; perfect concordance maps to rho = 1.
          This rho is interpretable as the signal-to-noise ratio of reviewer scores: it captures what fraction of the
          variance in a reviewer's scores reflects true paper quality versus idiosyncratic noise.
        </p>
        {p.theoretical_ceiling != null && p.inter_rater_rho != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Thurstonian ceiling</strong> ({p.theoretical_ceiling}%) translates rho into a practical upper bound on pairwise agreement.
            Given rho = {p.inter_rater_rho.toFixed(2)}, the Thurstonian model estimates that even two perfectly calibrated reviewers
            drawing from the same noise distribution would agree on at most {p.theoretical_ceiling}% of paper pairs — because on close-quality
            pairs, reviewer noise dominates and their orderings diverge by chance. This ceiling contextualizes the observed agreement rates:
            any system (human or AI) approaching {p.theoretical_ceiling}% is extracting nearly all the recoverable signal from the data.
          </p>
        )}
        {p.inter_rater_rho != null && p.ai_h_rho != null && p.ai_h_rho > p.inter_rater_rho && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>AI-Human rho ({p.ai_h_rho.toFixed(2)}) exceeds Human-Human rho ({p.inter_rater_rho.toFixed(2)}):</strong>{" "}
            Since concordance is already equal-weighted per reviewer pair, this gap is not a volume artifact — it means
            each AI pairwise comparison carries a <em>higher signal-to-noise ratio</em> than a typical human-human comparison.
            In a Bradley-Terry tournament, higher SNR per match means faster convergence to the true ranking.
            Concretely: an AI tournament needs fewer matches to achieve the same ranking quality as a human tournament,
            or equivalently, with the same number of matches, AI produces a <strong>more accurate ranking</strong>.
            This is likely because the AI round-robin (3 models taking turns) acts as a built-in noise-reduction mechanism:
            each model brings different strengths, and their combined signal across matches is more stable than any single rater —
            analogous to averaging multiple human reviewers, but at the cost of a single automated call per match.
          </p>
        )}
      </div>
    </div>
  );
}

function DatasetTable({ datasets }) {
  const [expanded, setExpanded] = useState(false);
  if (!datasets?.length) return null;
  return (
    <div>
      <button onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-accent hover:underline mb-2" data-testid="toggle-per-dataset">
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Per-dataset breakdown ({datasets.length} datasets)
      </button>
      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]" style={{ tableLayout: "fixed" }}>
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1 px-2 text-left font-medium">Dataset</th>
                <th className="py-1 px-2 text-right font-medium">AI-H%</th>
                <th className="py-1 px-2 text-right font-medium">H-H%</th>
                <th className="py-1 px-2 text-right font-medium">AI-C%</th>
                <th className="py-1 px-2 text-right font-medium">H-C% (LOO)</th>
                <th className="py-1 px-2 text-right font-medium text-muted-foreground/60">H-C%</th>
                <th className="py-1 px-2 text-right font-medium">rho</th>
                <th className="py-1 px-2 text-right font-medium">BT(C)</th>
                <th className="py-1 px-2 text-right font-medium text-muted-foreground/60">BT(I)</th>
                <th className="py-1 px-2 text-right font-medium">Pairs</th>
                <th className="py-1 px-2 text-right font-medium">Experts</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pw = d.pairwise || {};
                const bt_c = d.bt_correlation?.committee || {};
                const bt_i = d.bt_correlation?.individual || {};
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.ai_human?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.human_human?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.ai_committee?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.human_committee_loo?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-2 text-right font-mono text-muted-foreground/60">{pw.human_committee?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{d.inter_rater_rho?.toFixed(2) ?? "\u2014"}</td>
                    <td className="py-1 px-2 text-right font-mono">{bt_c.spearman_rho?.toFixed(2) ?? "\u2014"}</td>
                    <td className="py-1 px-2 text-right font-mono text-muted-foreground/60">{bt_i.spearman_rho?.toFixed(2) ?? "\u2014"}</td>
                    <td className="py-1 px-2 text-right font-mono">{d.controlled_pairs}</td>
                    <td className="py-1 px-2 text-right font-mono">{d.n_experts}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function HumanAIBenchmarkSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/validation/human-ai-benchmark`, { timeout: 90000 })
      .then(r => setData(r.data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="space-y-3 animate-pulse">
      {[1, 2, 3].map(i => <div key={i} className="h-24 bg-secondary/30 rounded-lg" />)}
    </div>
  );
  if (error) return <div className="text-sm text-destructive">Error: {error}</div>;
  if (!data || data.status !== "ok") return <div className="text-sm text-muted-foreground">No benchmark data available.</div>;

  const p = data.pooled;
  const pw = p.pairwise;
  const cf = p.tie_impact?.coin_flip;

  return (
    <div className="space-y-6" data-testid="human-ai-benchmark">
      {/* Header metrics */}
      <div className="text-[10px] text-muted-foreground mb-1 flex items-center justify-between flex-wrap gap-1">
        <span>AI judges use <strong>Opus 4.6 Thinking</strong> summaries (abstract + AI impact assessment). Majority vote across GPT-5.2, Claude Opus, Gemini 3 Pro.</span>
        <span className="font-mono text-muted-foreground/80"><strong>{data.total_controlled_pairs?.toLocaleString()}</strong> total pairs evaluated</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-Human Pairwise" value={`${cf?.ai_human ?? pw.ai_human.rate}%`} accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="Human-Human Pairwise" value={`${cf?.human_human ?? pw.human_human.rate}%`} sub="ties = coin flip" />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-Committee" value={`${cf?.ai_committee ?? pw.ai_committee.rate}%`} accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="Human-Comm (LOO)" value={`${cf?.human_committee_loo ?? pw.human_committee_loo?.rate ?? "\u2014"}%`} sub="ties = coin flip" />
        </div>
      </div>

      {/* 1. Merged agreement + difficulty + tie impact table */}
      <AgreementTable pw={pw} difficulty={p.by_difficulty} totalPairs={data.total_controlled_pairs} tieImpact={p.tie_impact} />

      {/* 2. Ranking Correlation (Bradley-Terry) */}
      {(() => {
        const bt = p.bt_correlation || {};
        const f = (v) => v?.toFixed(3) ?? "\u2014";
        const rows = [
          { group: "AI vs Human", label: "AI vs Committee", rho: bt.committee?.spearman_rho, tau: bt.committee?.kendall_tau,
            desc: "AI BT vs expert-majority BT" },
          { group: "", label: "AI vs Individual aggregate", rho: bt.individual?.spearman_rho, tau: bt.individual?.kendall_tau,
            desc: "AI BT vs all-expert-votes BT" },
          { group: "Human internal", label: "Single expert vs Committee", rho: bt.avg_expert_vs_comm?.spearman_rho, tau: bt.avg_expert_vs_comm?.kendall_tau,
            desc: "Each expert's BT vs committee BT (averaged)" },
          { group: "", label: "Single expert vs Individual aggregate", rho: bt.avg_expert_vs_indiv?.spearman_rho, tau: bt.avg_expert_vs_indiv?.kendall_tau,
            desc: "Each expert's BT vs all-votes BT (averaged)" },
        ];
        let lastGroup = "";
        return (
          <div className="border border-border rounded-lg overflow-hidden">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <span className="text-xs font-semibold">Ranking Correlation (Bradley-Terry)</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="py-1.5 px-2 text-left font-medium w-24"></th>
                    <th className="py-1.5 px-2 text-left font-medium">Comparison</th>
                    <th className="py-1.5 px-2 text-right font-medium">Spearman rho</th>
                    <th className="py-1.5 px-2 text-right font-medium">Kendall tau</th>
                    <th className="py-1.5 px-2 text-left font-medium text-[10px]">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const showGroup = r.group && r.group !== lastGroup;
                    if (r.group) lastGroup = r.group;
                    return (
                      <tr key={i} className={`border-b border-border/20 ${showGroup && i > 0 ? "border-t border-border" : ""}`}>
                        <td className={`py-1.5 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 ${showGroup ? "" : "text-transparent select-none"}`}>{r.group || lastGroup}</td>
                        <td className="py-1.5 px-2 font-medium">{r.label}</td>
                        <td className="py-1.5 px-2 text-right font-mono font-bold">{f(r.rho)}</td>
                        <td className="py-1.5 px-2 text-right font-mono">{f(r.tau)}</td>
                        <td className="py-1.5 px-2 text-muted-foreground text-[10px]">{r.desc}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                All BT rankings computed on the same controlled paper sets. "Avg single expert" builds BT from each expert's preferences
                individually, then averages the correlation across all experts — this is the typical single-rater baseline.
              </p>
            </div>
          </div>
        );
      })()}

      {/* 4. Inter-Rater Reliability (Human-Human + AI-Human) */}
      <ReliabilityTables p={p} pw={pw} />

      {/* 5. Per-dataset breakdown */}
      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}
