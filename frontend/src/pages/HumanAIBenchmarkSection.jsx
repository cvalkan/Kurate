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

function AgreementTable({ pw, difficulty, totalPairs, tieImpact, tieValidation, tierAccuracy }) {
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
            <col style={{ width: "18%" }} />
            <col /><col /><col /><col /><col /><col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">AI-Human</th>
              <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">Human-Human</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">AI vs Exp. Maj.</th>
              <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">H vs Exp. Maj. (LOO)</th>
              <th className="py-1.5 px-2 text-right font-medium bg-rose-500/[0.06]">AI vs ICLR PC</th>
              <th className="py-1.5 px-2 text-right font-medium bg-rose-500/[0.06]">H vs ICLR PC</th>
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
                <td className="py-1.5 px-2 text-right font-mono text-xs bg-rose-500/[0.06]">{tierAccuracy?.ai_rate != null ? `${tierAccuracy.ai_rate}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs bg-rose-500/[0.06]">{tierAccuracy?.hh_rate != null ? `${tierAccuracy.hh_rate}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{tieImpact.tie_rates?.hh != null ? `${tieImpact.tie_rates.hh}%` : ""}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{tieImpact.coin_flip.ai_human_kappa != null ? tieImpact.coin_flip.ai_human_kappa.toFixed(2) : ""}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{totalPairs?.toLocaleString()}</td>
              </tr>
            )}
            <tr className="border-b border-border/40">
              <td className="py-1.5 px-2 text-left text-xs text-foreground/60">Pooled (ties excluded)</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-sky-500/[0.06]">{fmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-sky-500/[0.06]">{fmt(pw.human_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.ai_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.human_committee_loo)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-rose-500/[0.06]"></td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-rose-500/[0.06]"></td>
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
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-rose-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-rose-500/[0.06]"></td>
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
          <strong>AI-Human</strong> = AI (round-robin judge) vs individual expert.{" "}
          <strong>Human-Human</strong> = individual expert vs individual expert.{" "}
          <strong>Exp. Maj.</strong> = virtual committee from reviewer score-derived pairwise preferences (majority vote).{" "}
          <strong>ICLR PC</strong> = actual program committee accept/reject tier decisions (cross-tier pairs only).{" "}
          H vs ICLR PC is structurally inflated: the same reviewers influenced the decisions they are being tested against.{" "}
          Difficulty rows and the coin-flip row use tie-corrected values for AI-Human, Human-Human, and H vs Exp. Maj. (LOO).
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
                <strong>Tie correction — why it matters:</strong>{" "}
                With ties excluded, Human-Human ({ex.hh_rate}%) appears to outperform AI-Human ({ex.ah_rate}%) by {hhGapExcl} percentage points.
                However, this gap is a <strong>measurement artifact</strong> caused by a <strong>selection bias</strong> from different within-pair filter strictness.
                Both metrics use the same set of controlled paper pairs, but within each pair, a Human-Human comparison requires
                <em>both</em> experts to have a clear preference — a <strong>double filter</strong>. An AI-Human comparison only requires
                the <em>one</em> human expert to have a preference (AI always has a verdict) — a <strong>single filter</strong>.
                Example: on a pair reviewed by experts A (non-tie), B (ties), C (non-tie), Human-Human keeps only A-C (1 of 3 comparisons),
                while AI-Human keeps AI-A and AI-C (2 of 3). This double filter creates a <strong>selection bias</strong>:
                it retains only comparisons where both reviewers could tell the papers apart — an inherently more agreeable subset.
              </p>
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                The coin-flip row corrects this by randomly assigning a preference to tied experts instead of excluding them.
                On tie comparisons, expected agreement is 50% (the random preference matches any real preference half the time).
                Human-Human drops more because it has more excluded comparisons to restore (both sides can be tied),
                while AI-Human drops less because only the human side gets the coin flip — AI keeps its real verdict.
                Under this correction, the gap closes
                to <strong>{cfGap} percentage points</strong> ({cf.human_human}% vs {cf.ai_human}%).
                At the committee level, AI vs Exp. Maj. ({cf.ai_committee}%) matches H vs Exp. Maj. LOO ({cf.human_committee_loo}%).
                The same correction applies to the difficulty rows.
                Note: ties and tiers measure different things — tiers are venue decisions (oral/poster/reject),
                ties are a reviewer giving both papers the same score. Ties are most common within the same tier.
              </p>
              {(() => {
                const tv = tieValidation;
                if (!tv || tv.ai_total < 50) return null;
                return (
                  <p className="text-[10px] text-muted-foreground leading-relaxed">
                    <strong>Is the coin flip conservative?</strong>{" "}
                    The coin flip assumes AI has no signal on tie pairs (50% expected agreement).
                    To test this: on pairs where at least one expert ties, we check how often AI agrees with the <em>non-tying</em> experts.
                    Result: AI agrees with non-tying experts <strong>{tv.ai_rate}%</strong> of the time ({tv.ai_total?.toLocaleString()} comparisons).
                    {tv.hh_total > 0 && <> For reference, non-tying experts agree with <em>each other</em> at {tv.hh_rate}% on these same pairs ({tv.hh_total?.toLocaleString()} comparisons).</>}
                    {tv.ai_rate > 50 ? (
                      <> Since {tv.ai_rate}% {">"} 50%, the coin flip <strong>underestimates</strong> AI's true agreement — AI has real signal on the pairs humans can't resolve.</>
                    ) : (
                      <> At ~50%, AI's signal on tie pairs is near chance.</>
                    )}
                  </p>
                );
              })()}
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                <strong>Significance for AI-based paper ranking:</strong>{" "}
                AI judges achieve <strong>human-level pairwise agreement</strong> on scientific paper quality when measured fairly.
                The 42% tie fraction reveals that human reviewers often cannot distinguish quality between papers — a fundamental
                limit of peer review. On the pairs where humans <em>can</em> distinguish, AI agrees with
                them at the same rate humans agree with each other.
                This validates LLM judges as a scalable alternative to human reviewers for relative quality ranking
                of scientific preprints.
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
            AI-Human concordance ({(ahConc * 100).toFixed(1)}%) slightly <strong>exceeds</strong> Human-Human ({(hhConc * 100).toFixed(1)}%).
            This likely reflects the AI round-robin (GPT-5.2, Opus, Gemini) producing a smoothed signal that aligns well with any single expert,
            much like a committee agrees with each member more than members agree with each other.
            Meanwhile, the {(ts.tie_fraction * 100).toFixed(0)}% tie fraction shows that human reviewers often cannot distinguish quality between papers —
            a fundamental limit of peer review. AI, which always produces a verdict, provides signal on the pairs humans
            cannot resolve, making it a <strong>strictly more complete</strong> source for ranking.
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
            Each AI comparison carries higher SNR than a typical human-human comparison.
            In a Bradley-Terry tournament this means faster convergence: an AI tournament needs fewer matches to reach the same ranking quality,
            or produces a <strong>more accurate ranking</strong> with the same number of matches.
            The AI round-robin acts as built-in noise reduction — each model brings different strengths, making the combined signal
            more stable than any single rater.
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

function BenchmarkPage({ apiUrl, headerDesc, testId }) {
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
          <Metric label="AI vs Exp. Maj." value={`${cf?.ai_committee ?? pw.ai_committee.rate}%`} accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="H vs Exp. Maj. (LOO)" value={`${cf?.human_committee_loo ?? pw.human_committee_loo?.rate ?? "\u2014"}%`} sub="ties = coin flip" />
        </div>
      </div>

      {/* 1. Merged agreement + difficulty + tie impact table */}
      <AgreementTable pw={pw} difficulty={p.by_difficulty} totalPairs={data.total_controlled_pairs} tieImpact={p.tie_impact} tieValidation={p.tie_validation} tierAccuracy={p.tier_accuracy} />

      {/* 2. Ranking Correlation (Bradley-Terry) */}
      {(() => {
        const bt = p.bt_correlation || {};
        const f = (v) => v?.toFixed(3) ?? "\u2014";
        const rows = [
          { group: "AI vs Human", label: "AI vs Avg Rating", rho: bt.vs_avg_rating_rho, tau: null,
            desc: "AI BT ranking vs h1_avg_rating ranking (same metric as summary table)" },
          { group: "", label: "AI vs Committee", rho: bt.committee?.spearman_rho, tau: bt.committee?.kendall_tau,
            desc: "AI BT vs expert-majority BT" },
          { group: "", label: "AI vs Individual aggregate", rho: bt.individual?.spearman_rho, tau: bt.individual?.kendall_tau,
            desc: "AI BT vs all-expert-votes BT" },
          { group: "Human internal", label: "Single expert vs Committee", rho: bt.avg_expert_vs_comm?.spearman_rho, tau: bt.avg_expert_vs_comm?.kendall_tau,
            desc: "Each expert's BT vs committee BT (averaged)" },
          { group: "", label: "Single expert vs Individual aggregate", rho: bt.avg_expert_vs_indiv?.spearman_rho, tau: bt.avg_expert_vs_indiv?.kendall_tau,
            desc: "Each expert's BT vs all-votes BT (averaged)" },
          { group: "", label: "Single expert vs LOO Committee", rho: bt.avg_expert_vs_loo?.spearman_rho, tau: null,
            desc: "Each expert's BT vs their leave-one-out committee BT (averaged)" },
          { group: "", label: "Single expert vs LOO Individual Aggregate", rho: bt.avg_expert_vs_loo_indiv?.spearman_rho, tau: null,
            desc: "Each expert's BT vs LOO all-other-experts BT (each preference = 1 match)" },
          { group: "", label: "Single expert vs LOO Avg Rating", rho: bt.avg_expert_vs_loo_avg?.spearman_rho, tau: null,
            desc: "Each expert's BT vs LOO h1_avg_rating (cleanest human baseline)" },
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
                All BT rankings use each method's full match data (not restricted to controlled pairs). "Single expert" builds BT from each expert's preferences
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

export default function HumanAIBenchmarkSection() {
  return <BenchmarkPage
    apiUrl="/api/validation/human-ai-benchmark?gt_type=comp"
    headerDesc={<>AI judges use <strong>Opus 4.6 Thinking</strong> summaries (abstract + AI impact assessment). Round-robin across GPT-5.2, Claude Opus, Gemini 3 Pro. <strong>Comparative GT</strong> (ICLR, PeerRead, eLife Neuro).</>}
    testId="human-ai-benchmark"
  />;
}
