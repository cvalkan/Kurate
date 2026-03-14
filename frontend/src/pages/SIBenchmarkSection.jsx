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

function AgreementTable({ pw, difficulty, totalPairs, tieImpact, pooled }) {
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
            <col style={{ width: "20%" }} />
            <col /><col /><col /><col /><col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">AI-Human</th>
              <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">Human-Human</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">AI-Comm</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">Human-Comm (LOO)</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">Human-Comm</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">tie rate</th>
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
                <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{tieImpact.tie_rates?.hh != null ? `${tieImpact.tie_rates.hh}%` : ""}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{tieImpact.coin_flip.ai_human_kappa != null ? tieImpact.coin_flip.ai_human_kappa.toFixed(2) : ""}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{tieImpact.coin_flip.total_pairs?.toLocaleString()}</td>
              </tr>
            )}
            <tr className="border-b border-border/40">
              <td className="py-1.5 px-2 text-left text-xs text-foreground/60">Pooled (ties excluded)</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-sky-500/[0.06]">{fmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-sky-500/[0.06]">{fmt(pw.human_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.ai_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.human_committee_loo)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.human_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60"></td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{kfmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{totalPairs?.toLocaleString()}</td>
            </tr>
            {difficulty && levels.map(({ key, label, desc }) => {
              const d = difficulty[key] || {};
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left text-xs">
                    <span className="text-foreground/60">{label}</span>
                    <span className="text-foreground/40 ml-1 text-[9px]">{desc}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-sky-500/[0.06]">{d.ah_cf != null ? `${d.ah_cf}%` : fmt(d.ai_human)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-sky-500/[0.06]">{d.hh_cf != null ? `${d.hh_cf}%` : fmt(d.human_human)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(d.ai_committee)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{d.hc_loo_cf != null ? `${d.hc_loo_cf}%` : fmt(d.human_committee_loo)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(d.human_committee)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{d.hh_tie_rate != null ? `${d.hh_tie_rate}%` : ""}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{(d.n_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-2">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>AI-Human</strong> = AI single-item score vs individual expert score (pairwise preferences derived from both).{" "}
          <strong>Human-Human</strong> = individual expert vs individual expert.{" "}
          <strong>AI-Comm</strong> = AI vs expert majority committee.{" "}
          <strong>Human-Comm (LOO)</strong> = individual expert vs leave-one-out majority (fair independent comparison).{" "}
          <strong>Human-Comm</strong> = individual expert vs majority (structurally inflated).{" "}
          Unlike the pairwise benchmark, here AI also produces numerical scores, so AI can also tie (two papers with the same score —
          {pooled?.ai_tie_fraction != null ? `${(pooled.ai_tie_fraction * 100).toFixed(1)}%` : "~8%"} of AI pairs vs ~43% of human pairs).
          Difficulty rows and the coin-flip row use tie-corrected values for AI-Human, Human-Human, and Human-Comm (LOO).
        </p>
        {(() => {
          const cf = tieImpact?.coin_flip;
          const ex = tieImpact?.excluded;
          if (!cf || !ex || cf.human_human == null || cf.ai_human == null) return null;
          const hhGapExcl = (ex.hh_rate - ex.ah_rate).toFixed(1);
          const cfGap = Math.abs(cf.human_human - cf.ai_human).toFixed(1);
          return (
            <>
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                <strong>Tie correction:</strong>{" "}
                With ties excluded, Human-Human ({ex.hh_rate}%) appears to outperform AI-Human ({ex.ah_rate}%) by {hhGapExcl}pp.
                This is the same measurement artifact as in the pairwise benchmark: excluding ties selects for easier pairs.
                Here, both humans and AI can tie, but AI ties far less often ({pooled?.ai_tie_fraction != null ? `${(pooled.ai_tie_fraction * 100).toFixed(1)}%` : "~8%"} vs ~43%),
                so the bias still disproportionately inflates Human-Human.
              </p>
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                Under coin-flip correction, the gap closes
                to <strong>{cfGap}pp</strong> ({cf.human_human}% vs {cf.ai_human}%),
                and AI-Comm ({cf.ai_committee}%) matches Human-Comm LOO ({cf.human_committee_loo}%).
                The pattern is consistent with the pairwise benchmark: <strong>AI achieves human-level agreement</strong> when
                measured fairly, even with a single scoring call per paper rather than pairwise comparisons.
              </p>
            </>
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
          <strong>Concordance vs agreement:</strong>{" "}
          Unlike the pooled pairwise agreement rates above ({pw?.human_human?.rate}% Human-Human, {pw?.ai_human?.rate}% AI-Human),
          where prolific reviewer pairs dominate, concordance here ({(hhConc * 100).toFixed(1)}% and {(ahConc * 100).toFixed(1)}%)
          is averaged per unit — each reviewer pair or expert gets equal weight regardless of volume.
          The {((pw?.human_human?.rate ?? 0) - (hhConc ?? 0) * 100).toFixed(1)}pp Human-Human gap
          ({pw?.human_human?.rate}% pooled vs {(hhConc * 100).toFixed(1)}% averaged) suggests high-volume reviewer pairs agree more,
          likely from shared conference tracks with clearer quality differences.
          For AI-Human the gap is negligible ({pw?.ai_human?.rate}% vs {(ahConc * 100).toFixed(1)}%):
          <strong>AI agreement is consistent across experts</strong> regardless of volume.
        </p>
        {hhConc != null && ahConc != null && ts.tie_fraction != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Interpretation:</strong>{" "}
            Here the AI uses a single model (Opus 4.6 Thinking) scoring each paper once, yet AI-Human concordance
            ({(ahConc * 100).toFixed(1)}%) is close to Human-Human ({(hhConc * 100).toFixed(1)}%).
            The {(ts.tie_fraction * 100).toFixed(0)}% human tie fraction shows that reviewers often cannot distinguish between papers.
            AI ties far less ({p.ai_tie_fraction != null ? `${(p.ai_tie_fraction * 100).toFixed(1)}%` : "~8%"}) because it uses finer-grained scores,
            providing signal on pairs humans cannot resolve.
          </p>
        )}
        {p.theoretical_ceiling != null && p.inter_rater_rho != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Derived rho and Thurstonian ceiling:</strong>{" "}
            Concordance is converted to a correlation via the Kruskal (1958) identity: rho = sin(pi x (concordance - 0.5)),
            interpretable as the signal-to-noise ratio of reviewer scores.
            The Thurstonian model then translates rho into a ceiling — the maximum pairwise agreement achievable given inter-rater noise.
            At rho = {p.inter_rater_rho.toFixed(2)}, even perfectly calibrated reviewers would agree on at most {p.theoretical_ceiling}% of pairs;
            any system approaching this is extracting nearly all recoverable signal.
          </p>
        )}
        {p.inter_rater_rho != null && p.ai_h_rho != null && p.ai_h_rho > p.inter_rater_rho && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>AI-Human rho ({p.ai_h_rho.toFixed(2)}) exceeds Human-Human rho ({p.inter_rater_rho.toFixed(2)}):</strong>{" "}
            Even with a single model and one call per paper, AI comparisons carry higher SNR than typical human-human comparisons.
            This suggests that a single-item AI scoring tournament can converge to the true ranking faster than
            a human-scored tournament with the same number of papers.
          </p>
        )}
        {p.inter_rater_rho != null && p.ai_h_rho != null && p.ai_h_rho <= p.inter_rater_rho && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>AI-Human rho ({p.ai_h_rho.toFixed(2)}) vs Human-Human rho ({p.inter_rater_rho.toFixed(2)}):</strong>{" "}
            With only a single model and one call per paper, AI concordance is slightly lower than human-human concordance.
            This is expected — the pairwise benchmark (which uses 3 models in round-robin) achieves higher AI-Human concordance
            through its built-in noise reduction.
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

function SIBenchmarkPage({ apiUrl, headerDesc, testId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}${apiUrl}`, { timeout: 90000 })
      .then(r => setData(r.data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [apiUrl]);

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
    <div className="space-y-6" data-testid={testId}>
      {/* Header metrics */}
      <div className="text-[10px] text-muted-foreground mb-1 flex items-center justify-between flex-wrap gap-1">
        <span>{headerDesc}</span>
        <span className="font-mono text-muted-foreground/80"><strong>{data.total_controlled_pairs?.toLocaleString()}</strong> pairs across <strong>{data.total_papers?.toLocaleString()}</strong> papers ({data.avg_matches_per_paper} matches/paper avg)</span>
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
      <AgreementTable pw={pw} difficulty={p.by_difficulty} totalPairs={data.total_controlled_pairs} tieImpact={p.tie_impact} pooled={p} />

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

export default function SIBenchmarkSection() {
  return <SIBenchmarkPage
    apiUrl="/api/validation/si-benchmark?gt_type=stan"
    headerDesc={<>AI scores each paper individually with <strong>Opus 4.6 Thinking</strong> (1-10 scale). Standalone GT datasets (eLife biology, MIDL, Qeios, ResearchHub) — reviewers scored papers independently.</>}
    testId="si-benchmark-stan"
  />;
}

export function SIBenchmarkCompSection() {
  return <SIBenchmarkPage
    apiUrl="/api/validation/si-benchmark?gt_type=comp"
    headerDesc={<>AI scores each paper individually with <strong>Opus 4.6 Thinking</strong> (1-10 scale). Comparative GT datasets (ICLR, PeerRead, eLife Neuro) — reviewers compared papers against each other.</>}
    testId="si-benchmark-comp"
  />;
}
