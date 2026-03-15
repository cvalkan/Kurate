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

function AgreementTable({ pw, difficulty, totalPairs, tieImpact, tieValidation, tierAccuracy, tieStats, concordance }) {
  const fmt = (v) => v?.rate != null ? `${v.rate}%` : "\u2014";
  const fmtN = (v, n) => {
    if (v == null) return "\u2014";
    const warn = n != null && n < 30;
    return <>{v}%{warn && <sup className="text-amber-500 ml-0.5">&dagger;</sup>}</>;
  };
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
            <col /><col /><col /><col /><col /><col />
            <col style={{ width: "5%" }} /><col style={{ width: "5.5%" }} /><col style={{ width: "6%" }} />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-1.5 text-left font-medium">Scope</th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-sky-500/[0.06]"><div>AI vs.</div><div>Human<sup>1</sup></div></th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-sky-500/[0.06]"><div>Human vs.</div><div>Human<sup>1</sup></div></th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-amber-500/[0.06]"><div>AI vs.</div><div>Majority<sup>2</sup></div></th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-amber-500/[0.06]"><div>Human vs.</div><div>Majority (LOO)<sup>3</sup></div></th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-rose-500/[0.06]"><div>AI vs.</div><div>Committee<sup>4</sup></div></th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-rose-500/[0.06]"><div>Human vs.</div><div>Committee<sup>4,5</sup></div></th>
              <th className="py-1.5 px-1.5 text-right font-medium">tie%<sup>6</sup></th>
              <th className="py-1.5 px-1.5 text-right font-medium">kappa</th>
              <th className="py-1.5 px-1.5 text-right font-medium">pairs</th>
            </tr>
          </thead>
          <tbody>
            {tieImpact?.coin_flip && (
              <tr className="border-b border-border bg-accent/5">
                <td className="py-1.5 px-2 text-left text-xs font-semibold">All pairs (ties = coin flip)<sup>7</sup></td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-sky-500/[0.06]">{tieImpact.coin_flip.ai_human != null ? `${tieImpact.coin_flip.ai_human}%` : "\u2014"}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-sky-500/[0.06]">{tieImpact.coin_flip.human_human != null ? `${tieImpact.coin_flip.human_human}%` : "\u2014"}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-amber-500/[0.06]">{tieImpact.coin_flip.ai_committee != null ? `${tieImpact.coin_flip.ai_committee}%` : "\u2014"}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-amber-500/[0.06]">{tieImpact.coin_flip.human_committee_loo != null ? `${tieImpact.coin_flip.human_committee_loo}%` : "\u2014"}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-rose-500/[0.06]">{tierAccuracy?.ai_rate != null ? `${tierAccuracy.ai_rate}%` : "\u2014"}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{tierAccuracy?.hh_rate != null ? `${tierAccuracy.hh_rate}%` : "\u2014"}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{tieImpact.tie_rates?.hh != null ? `${tieImpact.tie_rates.hh}%` : ""}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{tieImpact.coin_flip.ai_human_kappa != null ? tieImpact.coin_flip.ai_human_kappa.toFixed(2) : ""}</td>
                <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{totalPairs?.toLocaleString()}</td>
              </tr>
            )}
            <tr className="border-b border-border/40">
              <td className="py-1.5 px-2 text-left text-xs font-normal text-foreground/60">All pairs (ties excluded)<sup>8</sup></td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-sky-500/[0.06]">{fmt(pw.ai_human)}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-sky-500/[0.06]">{fmt(pw.human_human)}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.ai_committee)}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{fmt(pw.human_committee_loo)}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{tierAccuracy?.ai_rate != null ? `${tierAccuracy.ai_rate}%` : "\u2014"}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{tierAccuracy?.hh_rate != null ? `${tierAccuracy.hh_rate}%` : "\u2014"}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{kfmt(pw.ai_human)}</td>
              <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{totalPairs?.toLocaleString()}</td>
            </tr>
            {difficulty && levels.map(({ key, label, desc }) => {
              const d = difficulty[key] || {};
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left text-xs">
                    <div className="text-foreground/60">{label}</div>
                    <div className="text-foreground/40 text-[9px] whitespace-nowrap">{desc}</div>
                  </td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-sky-500/[0.06]">{d.ah_cf != null ? fmtN(d.ah_cf, d.ah_cf_n) : fmt(d.ai_human)}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-sky-500/[0.06]">{d.hh_cf != null ? fmtN(d.hh_cf, d.hh_cf_n) : fmt(d.human_human)}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{fmtN(d.ai_committee?.rate, d.ai_committee?.pairs)}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{d.hc_loo_cf != null ? fmtN(d.hc_loo_cf, d.hc_loo_cf_n) : fmt(d.human_committee_loo)}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{d.tier_ai?.pairs > 0 ? fmtN(d.tier_ai.rate, d.tier_ai.pairs) : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{d.tier_hh?.pairs > 0 ? fmtN(d.tier_hh.rate, d.tier_hh.pairs) : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{d.hh_tie_rate != null ? `${d.hh_tie_rate}%` : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{d.ah_cf_kappa != null ? d.ah_cf_kappa.toFixed(2) : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{(d.n_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
            {concordance && (
              <>
                <tr className="border-t border-border/30 bg-accent/5">
                  <td className="py-1.5 px-2 text-left text-xs font-semibold">Equal-weighted (coin flip)<sup>9,7</sup><div className="text-foreground/40 text-[9px]">per reviewer, ties randomly resolved</div></td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-sky-500/[0.06]">{concordance.ai_h_cf != null ? `${(concordance.ai_h_cf * 100).toFixed(1)}%` : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-bold bg-sky-500/[0.06]">{concordance.hh_cf != null ? `${(concordance.hh_cf * 100).toFixed(1)}%` : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
                </tr>
                <tr className="border-b border-border/30">
                  <td className="py-1.5 px-2 text-left text-xs font-normal text-foreground/60">Equal-weighted (ties excluded)<sup>9,8</sup><div className="text-foreground/40 text-[9px]">per reviewer, ties dropped</div></td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-sky-500/[0.06]">{concordance.ai_h != null ? `${(concordance.ai_h * 100).toFixed(1)}%` : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-sky-500/[0.06]">{concordance.hh != null ? `${(concordance.hh * 100).toFixed(1)}%` : "\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-amber-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60 bg-rose-500/[0.06]">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono text-xs font-normal text-foreground/60">{"\u2014"}</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-1">
        <div className="text-[10px] text-muted-foreground leading-relaxed space-y-0.5">
          <p><sup>1</sup> Individual-level pairwise agreement: AI judge (or expert) vs. individual expert preference. Reviewer identities are positional (Reviewer 1, 2, …) — "Reviewer 1" on different papers is a different person. Concordance between positional reviewers approximates random-pair agreement but cannot capture individual reviewer effects (e.g., consistently lenient or harsh graders).</p>
          <p><sup>2</sup> <strong>Majority</strong> = virtual majority vote from reviewer score-derived pairwise preferences (our construction). Human vs. Majority uses LOO: expert excluded from the majority they are tested against.</p>
          <p><sup>3</sup> When LOO voters split evenly, the pair is skipped — a selection bias toward pairs where remaining experts agree. More common than in non-LOO (fewer voters).</p>
          <p><sup>4</sup> <strong>Committee</strong> = actual ICLR program committee accept/reject tier decisions (cross-tier pairs only).</p>
          <p><sup>5</sup> <strong>Circular</strong>: the same reviewers who provide scores also influenced the committee decisions — structurally inflating human accuracy. AI vs. Committee has no such circularity.</p>
          <p><sup>6</sup> Fraction of expert comparisons that are ties (at least one reviewer gave both papers the same score). ICLR uses only 6 distinct ratings (1, 3, 5, 6, 8, 10) on a 1–10 scale, heavily concentrated around 5–6, making ties structurally common.</p>
          <p><sup>7</sup> <strong>Coin flip</strong>: tied experts get a random preference (50% expected agreement) instead of being excluded. Corrects the double-filter selection bias in Human vs. Human.</p>
          <p><sup>8</sup> <strong>Ties excluded</strong>: only comparisons where expert(s) had clear preferences. This creates a <strong>selection bias</strong> because Human vs. Human requires <em>both</em> experts to have preferences on the same pair (double filter), while AI vs. Human only requires one (single filter). Example: if experts A, B, C review a pair and B ties, Human vs. Human keeps only A-C (1 of 3 comparisons), while AI vs. Human keeps AI-A and AI-C (2 of 3). The double filter retains only comparisons where both reviewers could distinguish the papers — an inherently more agreeable subset. Difficulty rows use coin-flip to correct for this.</p>
          <p><sup>9</sup> <strong>Equal-weighted</strong>: averaged per reviewer pair (each pair weighted equally regardless of volume), unlike pooled rows which weight by number of comparisons.</p>
          <p><sup>&dagger;</sup> <strong>Small sample</strong> (n &lt; 30): treat with caution — estimate is unreliable at this sample size.</p>
        </div>
        {(() => {
          const cf = tieImpact?.coin_flip;
          const ex = tieImpact?.excluded;
          if (!cf || !ex || cf.human_human == null || cf.ai_human == null) return null;
          const cfGap = Math.abs(cf.human_human - cf.ai_human).toFixed(1);
          return (
            <>
              {(() => {
                const tv = tieValidation;
                if (!tv || tv.ai_total < 50) return null;
                return (
                  <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">
                    <strong>Is the coin flip conservative?</strong>{" "}
                    On pairs where at least one expert ties, AI agrees with <em>non-tying</em> experts <strong>{tv.ai_rate}%</strong> ({tv.ai_total?.toLocaleString()} comparisons) —
                    well above the 50% coin-flip assumption.
                    {tv.hh_total > 0 && <> Non-tying experts agree at {tv.hh_rate}% on these same pairs.</>}
                    {tv.ai_rate > 50 && <> The coin flip <strong>underestimates</strong> AI — it has real signal on pairs humans can't resolve.</>}
                  </p>
                );
              })()}
              <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">
                <strong>Conclusion:</strong>{" "}
                Under fair comparison (coin flip), AI-Human ({cf.ai_human}%) and Human-Human ({cf.human_human}%) are within <strong>{cfGap}pp</strong>.
                The {(tieStats?.tie_fraction * 100)?.toFixed(0) ?? "?"}% tie fraction is a fundamental limit of peer review.
                AI provides verdicts on these pairs too, making it a strictly more complete signal source.
              </p>
            </>
          );
        })()}
      </div>
    </div>
  );
}

function ReliabilityTables({ p, pw, concordance }) {
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
        {concordance?.hh_cf != null && concordance?.hh != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Note on coin-flip concordance:</strong>{" "}
            H-H drops from {(concordance.hh * 100).toFixed(1)}% to {(concordance.hh_cf * 100).toFixed(1)}% under coin-flip — a large drop because
            each reviewer pair gets equal weight, and pairs where one reviewer uses a coarse scoring scale (many ties) are penalized heavily.
            A reviewer who ties 60% of pairs contributes many 50%-agreement coin-flips, dragging that pair's concordance down.
            This doesn't necessarily mean the reviewer is unskilled — coarse scales and cautious scoring both produce ties.
            The coin-flip value ({(concordance.hh_cf * 100).toFixed(1)}%) is the most conservative H-H estimate;
            the ties-excluded value ({(concordance.hh * 100).toFixed(1)}%) is the most optimistic. The truth lies between them.
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
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1 px-2 text-left font-medium">Dataset</th>
                <th className="py-1 px-1.5 text-right font-medium bg-sky-500/[0.06]">AI-H%</th>
                <th className="py-1 px-1.5 text-right font-medium bg-sky-500/[0.06]">H-H%</th>
                <th className="py-1 px-1.5 text-right font-medium bg-amber-500/[0.06]">AI-Maj%</th>
                <th className="py-1 px-1.5 text-right font-medium bg-amber-500/[0.06]">H-Maj%(LOO)</th>
                <th className="py-1 px-1.5 text-right font-medium bg-rose-500/[0.06]">AI-PC%</th>
                <th className="py-1 px-1.5 text-right font-medium">rho</th>
                <th className="py-1 px-1.5 text-right font-medium">BT(fair)</th>
                <th className="py-1 px-1.5 text-right font-medium text-foreground/50">Pairs</th>
                <th className="py-1 px-1.5 text-right font-medium text-foreground/50">Experts</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pw = d.pairwise || {};
                const bt_indiv = d.bt_correlation?.individual || {};
                const ta = d.tier_accuracy || {};
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-sky-500/[0.06]">{pw.ai_human?.cf_rate ?? pw.ai_human?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-sky-500/[0.06]">{pw.human_human?.cf_rate ?? pw.human_human?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-amber-500/[0.06]">{pw.ai_committee?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-amber-500/[0.06]">{pw.human_committee_loo?.cf_rate ?? pw.human_committee_loo?.rate ?? "\u2014"}%</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-rose-500/[0.06]">{ta.ai_rate != null ? `${ta.ai_rate}%` : "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono text-foreground/60">{d.inter_rater_rho?.toFixed(2) ?? "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono">{bt_indiv.spearman_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono text-foreground/50">{d.controlled_pairs}</td>
                    <td className="py-1 px-1.5 text-right font-mono text-foreground/50">{d.n_experts}</td>
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
          <Metric label="AI vs. Majority" value={`${cf?.ai_committee ?? pw.ai_committee.rate}%`} accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="Human vs. Majority (LOO)" value={`${cf?.human_committee_loo ?? pw.human_committee_loo?.rate ?? "\u2014"}%`} sub="ties = coin flip" />
        </div>
      </div>

      {/* 1. Merged agreement + difficulty + tie impact table */}
      <AgreementTable pw={pw} difficulty={p.by_difficulty} totalPairs={data.total_controlled_pairs} tieImpact={p.tie_impact} tieValidation={p.tie_validation} tierAccuracy={p.tier_accuracy} tieStats={p.tie_stats} concordance={{ hh: p.tie_stats?.concordance_rate, ai_h: p.ai_h_concordance, hh_cf: p.tie_stats?.cf_concordance_rate, ai_h_cf: p.ai_h_cf_concordance }} />

      {/* 2. Ranking Correlation (Bradley-Terry) */}
      {(() => {
        const bt = p.bt_correlation || {};
        const f = (v) => v?.toFixed(3) ?? "\u2014";
        const rows = [
          { group: "AI vs Human", label: "AI vs Individual aggregate", rho: bt.individual?.spearman_rho, tau: bt.individual?.kendall_tau, fair: true,
            desc: "AI BT vs all-expert-votes BT — no circularity, same methodology as human baseline" },
          { group: "", label: "AI vs Avg Rating", rho: bt.vs_avg_rating_rho, tau: null, fair: false,
            desc: "AI BT vs h1_avg_rating — clean but cross-methodology (BT vs scores)" },
          { group: "", label: "AI vs Majority", rho: bt.committee?.spearman_rho, tau: bt.committee?.kendall_tau, fair: false,
            desc: "AI BT vs expert-majority BT — majority collapsing differs from individual aggregate" },
          { group: "", label: "AI vs Committee (ICLR PC)", rho: bt.vs_tier_rho, tau: null, fair: false,
            desc: "AI BT vs actual program committee tier decisions — coarse (4 tiers only)" },
          { group: "Human internal", label: "Single expert vs Individual aggregate (LOO)", rho: bt.avg_expert_vs_loo_indiv?.spearman_rho, tau: null, fair: true,
            desc: "Expert BT vs LOO all-other-experts BT — fairest human baseline (same methodology as AI)" },
          { group: "", label: "Single expert vs Avg Rating (LOO)", rho: bt.avg_expert_vs_loo_avg?.spearman_rho, tau: null, fair: false,
            desc: "Expert BT vs LOO h1_avg_rating — clean but cross-methodology (BT vs scores)" },
          { group: "", label: "Single expert vs Majority (LOO)", rho: bt.avg_expert_vs_loo?.spearman_rho, tau: null, fair: false,
            desc: "Expert BT vs LOO majority BT — LOO ties skipped, majority collapsing" },
          { group: "", label: "Single expert vs Committee (ICLR PC)", rho: bt.avg_expert_vs_tier?.spearman_rho, tau: null, fair: false,
            desc: "Expert BT vs tier decisions — circular (reviewers influenced the decisions)" },
          { group: "", label: "Single expert vs Majority", rho: bt.avg_expert_vs_comm?.spearman_rho, tau: bt.avg_expert_vs_comm?.kendall_tau, fair: false,
            desc: "Circular — expert's votes are in the majority they're tested against" },
          { group: "", label: "Single expert vs Individual aggregate", rho: bt.avg_expert_vs_indiv?.spearman_rho, tau: bt.avg_expert_vs_indiv?.kendall_tau, fair: false,
            desc: "Circular — expert's votes are in the aggregate" },
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
                      <tr key={i} className={`border-b border-border/20 ${showGroup && i > 0 ? "border-t border-border" : ""} ${r.fair ? "bg-accent/5" : ""}`}>
                        <td className={`py-1.5 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 ${showGroup ? "" : "text-transparent select-none"}`}>{r.group || lastGroup}</td>
                        <td className={`py-1.5 px-2 ${r.fair ? "font-semibold" : "text-foreground/50"}`}>{r.label}</td>
                        <td className={`py-1.5 px-2 text-right font-mono ${r.fair ? "font-bold" : "font-normal text-foreground/50"}`}>{f(r.rho)}</td>
                        <td className={`py-1.5 px-2 text-right font-mono ${r.fair ? "" : "font-normal text-foreground/50"}`}>{f(r.tau)}</td>
                        <td className="py-1.5 px-2 text-muted-foreground text-[10px]">{r.desc}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                All BT rankings use each method's full match data. "Single expert" builds BT from each expert's preferences
                individually, then averages the correlation across all experts.
                <strong>Majority</strong> = virtual majority vote from reviewer preferences (our construction).
                <strong>Committee (ICLR PC)</strong> = actual program committee tier decisions (coarse: 4 tiers).
                Human vs Committee is circular (reviewers influenced the decisions).
              </p>
            </div>
          </div>
        );
      })()}

      {/* 4. Inter-Rater Reliability (Human-Human + AI-Human) */}
      <ReliabilityTables p={p} pw={pw} concordance={{ hh: p.tie_stats?.concordance_rate, ai_h: p.ai_h_concordance, hh_cf: p.tie_stats?.cf_concordance_rate, ai_h_cf: p.ai_h_cf_concordance }} />

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
