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
          <p><sup>1</sup> Individual-level pairwise agreement: AI judge (or expert) vs. individual expert preference. Reviewer identities are positional (Reviewer 1, 2, …) not real — "Reviewer 1" on different papers is a different person. Positional pairing approximates random-pair agreement but cannot capture individual reviewer effects.</p>
          <p><sup>2</sup> <strong>Majority</strong> = virtual majority vote from reviewer score-derived pairwise preferences (our construction). Human vs. Majority uses LOO: expert excluded from the majority they are tested against.</p>
          <p><sup>3</sup> When LOO voters split evenly, the pair is skipped — a selection bias toward pairs where remaining experts agree. More common than in non-LOO (fewer voters).</p>
          <p><sup>4</sup> <strong>Committee</strong> = actual ICLR program committee accept/reject tier decisions (cross-tier pairs only).</p>
          <p><sup>5</sup> <strong>Circular</strong>: the same reviewers who provide scores also influenced the committee decisions — structurally inflating human accuracy. AI vs. Committee has no such circularity.</p>
          <p><sup>6</sup> Fraction of expert comparisons that are ties (at least one reviewer gave both papers the same score). ICLR uses only 6 distinct ratings (1, 3, 5, 6, 8, 10) on a 1–10 scale, heavily concentrated around 5–6, making ties structurally common.</p>
          <p><sup>7</sup> <strong>Coin flip</strong>: tied experts get a random preference (50% expected agreement) instead of being excluded. Corrects the double-filter selection bias in Human vs. Human.</p>
          <p><sup>8</sup> <strong>Ties excluded</strong>: only comparisons where expert(s) had clear preferences. This creates a <strong>selection bias</strong> because Human vs. Human requires <em>both</em> experts to have preferences on the same pair (double filter), while AI vs. Human only requires one (single filter). Example: if experts A, B, C review a pair and B ties, Human vs. Human keeps only A-C (1 of 3 comparisons), while AI vs. Human keeps AI-A and AI-C (2 of 3). The double filter retains only comparisons where both reviewers could distinguish the papers — an inherently more agreeable subset. Difficulty rows use coin-flip to correct for this.</p>
          <p><sup>9</sup> <strong>Equal-weighted</strong>: concordance averaged per dataset (each dataset weighted equally regardless of how many comparisons it contributes). Because reviewer identities are positional, "per reviewer pair" is effectively per dataset. Pooled rows weight by comparison volume, so large high-agreement datasets dominate.</p>
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
                    The first table row assigns 50% agreement on tied comparisons. But on pairs where at least one expert ties,
                    AI actually agrees with the <em>non-tying</em> expert(s) <strong>{tv.ai_rate}%</strong> of the time ({tv.ai_total?.toLocaleString()} comparisons) —
                    well above that 50% assumption.
                    {tv.hh_total > 0 && <> Among those same pairs, non-tying experts agree with each other at {tv.hh_rate}% ({tv.hh_total?.toLocaleString()} comparisons).</>}
                    {tv.ai_rate > 50 && <> The coin flip therefore <strong>underestimates</strong> AI — it has real signal on pairs where humans can't resolve a preference,
                    and the {cf.ai_human}% AI-Human figure in the table is conservative.</>}
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
                <th className="py-1 px-2 text-left font-medium" rowSpan={2}>Dataset</th>
                <th className="py-1 px-1.5 text-center font-medium bg-sky-500/[0.06]" colSpan={4}>Individual</th>
                <th className="py-1 px-1.5 text-center font-medium bg-amber-500/[0.06]" colSpan={4}>Majority (LOO)</th>
                <th className="py-1 px-1.5 text-center font-medium bg-rose-500/[0.06]" colSpan={4}>Committee</th>
                <th className="py-1 px-1.5 text-right font-medium text-foreground/50" rowSpan={2}>Pairs</th>
              </tr>
              <tr className="border-b border-border text-muted-foreground text-[9px]">
                <th className="py-0.5 px-1.5 text-right font-medium bg-sky-500/[0.06]">AI-H%</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-sky-500/[0.06]">H-H%</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-sky-500/[0.06]">AI BT</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-sky-500/[0.06]">H BT</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-amber-500/[0.06]">AI%</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-amber-500/[0.06]">H%(LOO)</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-amber-500/[0.06]">AI BT</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-amber-500/[0.06]">H BT</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-rose-500/[0.06]">AI%</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-rose-500/[0.06]">H%</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-rose-500/[0.06]">AI BT</th>
                <th className="py-0.5 px-1.5 text-right font-medium bg-rose-500/[0.06]">H BT</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pw = d.pairwise || {};
                const bt = d.bt_correlation || {};
                const ta = d.tier_accuracy || {};
                const f3 = v => v?.toFixed(3) ?? "\u2014";
                const ah = pw.ai_human?.cf_rate ?? pw.ai_human?.rate;
                const hh = pw.human_human?.cf_rate ?? pw.human_human?.rate;
                const amaj = pw.ai_committee?.rate;
                const hmaj = pw.human_committee_loo?.cf_rate ?? pw.human_committee_loo?.rate;
                const apc = ta.ai_rate;
                const hpc = ta.hh_rate;
                const abt1 = bt.individual?.spearman_rho;
                const hbt1 = bt.avg_expert_vs_loo_indiv?.spearman_rho;
                const abt2 = bt.committee?.spearman_rho;
                const hbt2 = bt.avg_expert_vs_loo?.spearman_rho;
                const abt3 = bt.vs_tier_rho;
                const hbt3 = bt.avg_expert_vs_tier?.spearman_rho;
                const b = (a, h) => a != null && h != null && a > h ? "font-semibold" : "";
                const bh = (a, h) => h != null && a != null && h > a ? "font-semibold" : "";
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-sky-500/[0.06] ${b(ah, hh)}`}>{ah ?? "\u2014"}%</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-sky-500/[0.06] ${bh(ah, hh)}`}>{hh ?? "\u2014"}%</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-sky-500/[0.06] ${b(abt1, hbt1)}`}>{f3(abt1)}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-sky-500/[0.06] ${bh(abt1, hbt1)}`}>{f3(hbt1)}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-amber-500/[0.06] ${b(amaj, hmaj)}`}>{amaj ?? "\u2014"}%</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-amber-500/[0.06] ${bh(amaj, hmaj)}`}>{hmaj ?? "\u2014"}%</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-amber-500/[0.06] ${b(abt2, hbt2)}`}>{f3(abt2)}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-amber-500/[0.06] ${bh(abt2, hbt2)}`}>{f3(hbt2)}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-rose-500/[0.06] ${b(apc, hpc)}`}>{apc != null ? `${apc}%` : "\u2014"}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-rose-500/[0.06] ${bh(apc, hpc)}`}>{hpc != null ? `${hpc}%` : "\u2014"}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-rose-500/[0.06] ${b(abt3, hbt3)}`}>{f3(abt3)}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-rose-500/[0.06] ${bh(abt3, hbt3)}`}>{f3(hbt3)}</td>
                    <td className="py-1 px-1.5 text-right font-mono text-foreground/50">{d.controlled_pairs}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              <strong>Note on PeerRead ACL 2017:</strong> This dataset behaves differently from ICLR — AI-H BT correlation (0.434) is far below
              the ICLR range (0.69–0.90). Contributing factors: only 2–3 reviewers per paper (vs 4–5), a coarser 1–5 scale with 51% tie rate,
              no decision tiers (all null), and 2017-era NLP reviewing norms that may not align with modern LLM assessments.
              The high H-H agreement (86.7%) is likely inflated by the 2-reviewer double-filter bias (footnote 8 above).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function DatasetRankings({ datasets }) {
  const [selectedDs, setSelectedDs] = useState(null);
  const [rankData, setRankData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sortCol, setSortCol] = useState("ai_rank");
  const [sortAsc, setSortAsc] = useState(true);

  const dsOptions = datasets?.filter(d => d.dataset_id && d.controlled_pairs >= 20) || [];

  useEffect(() => {
    if (!selectedDs) { setRankData(null); return; }
    setLoading(true);
    axios.get(`${API}/api/validation/dataset-rankings/${selectedDs}`, { timeout: 30000 })
      .then(r => { if (r.data?.status === "ok") setRankData(r.data); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedDs]);

  const toggleSort = (col) => {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(col.includes("rank")); }
  };

  const sorted = rankData?.papers ? [...rankData.papers].sort((a, b) => {
    const av = a[sortCol] ?? 9999, bv = b[sortCol] ?? 9999;
    return sortAsc ? av - bv : bv - av;
  }) : [];

  const TIER_COLORS = { oral: "text-emerald-600", spotlight: "text-sky-600", poster: "text-foreground/70", reject: "text-rose-500", withdrawn: "text-foreground/40" };

  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-semibold text-muted-foreground">Paper-level rankings:</span>
        <select
          className="text-xs border border-border rounded px-2 py-1 bg-background"
          value={selectedDs || ""}
          onChange={e => setSelectedDs(e.target.value || null)}
          data-testid="dataset-rankings-select"
        >
          <option value="">Select a dataset...</option>
          {dsOptions.map(d => (
            <option key={d.dataset_id} value={d.dataset_id}>{d.name || d.dataset_id} ({d.controlled_pairs} pairs)</option>
          ))}
        </select>
      </div>

      {loading && <div className="text-xs text-muted-foreground mt-2 animate-pulse">Loading rankings...</div>}

      {rankData && !loading && (
        <div className="mt-3 border border-border rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center justify-between">
            <span className="text-xs font-semibold">
              {dsOptions.find(d => d.dataset_id === selectedDs)?.name || selectedDs} — {rankData.n_papers} papers, {rankData.n_controlled_pairs} controlled pairs
            </span>
            <span className="text-[10px] text-muted-foreground">Click column headers to sort</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]" data-testid="dataset-rankings-table">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  {[
                    { key: "ai_rank", label: "AI Rank", bg: "bg-sky-500/[0.06]" },
                    { key: "ai_bt", label: "AI BT", bg: "bg-sky-500/[0.06]" },
                    { key: "ai_wl", label: "AI W/L", bg: "bg-sky-500/[0.06]", noSort: true },
                    { key: "h_indiv_rank", label: "H-Indiv Rank", bg: "bg-amber-500/[0.06]" },
                    { key: "h_indiv_bt", label: "H-Indiv BT", bg: "bg-amber-500/[0.06]" },
                    { key: "h_indiv_wl", label: "H-Indiv W/L", bg: "bg-amber-500/[0.06]", noSort: true },
                    { key: "h_maj_rank", label: "H-Maj Rank", bg: "bg-rose-500/[0.06]" },
                    { key: "h_maj_bt", label: "H-Maj BT", bg: "bg-rose-500/[0.06]" },
                    { key: "h_maj_wl", label: "H-Maj W/L", bg: "bg-rose-500/[0.06]", noSort: true },
                    { key: "decision", label: "Decision" },
                    { key: "h1_avg_rating", label: "H Avg" },
                    { key: "title", label: "Title", noSort: true },
                  ].map(col => (
                    <th
                      key={col.key}
                      className={`py-1.5 px-1.5 text-right font-medium whitespace-nowrap ${col.bg || ""} ${col.noSort ? "" : "cursor-pointer hover:text-foreground"} ${col.key === "title" ? "text-left" : ""}`}
                      onClick={col.noSort ? undefined : () => toggleSort(col.key)}
                    >
                      {col.label}
                      {sortCol === col.key && <span className="ml-0.5">{sortAsc ? "\u25B2" : "\u25BC"}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r, i) => {
                  const matchAiMaj = r.ai_bt === r.h_maj_bt;
                  return (
                    <tr key={i} className={`border-b border-border/20 ${matchAiMaj ? "bg-amber-500/[0.04]" : ""}`}>
                      <td className="py-1 px-1.5 text-right font-mono font-semibold bg-sky-500/[0.06]">{r.ai_rank}</td>
                      <td className="py-1 px-1.5 text-right font-mono bg-sky-500/[0.06]">{r.ai_bt}</td>
                      <td className="py-1 px-1.5 text-right font-mono text-foreground/60 bg-sky-500/[0.06]">{r.ai_wl}</td>
                      <td className="py-1 px-1.5 text-right font-mono font-semibold bg-amber-500/[0.06]">{r.h_indiv_rank}</td>
                      <td className="py-1 px-1.5 text-right font-mono bg-amber-500/[0.06]">{r.h_indiv_bt}</td>
                      <td className="py-1 px-1.5 text-right font-mono text-foreground/60 bg-amber-500/[0.06]">{r.h_indiv_wl}</td>
                      <td className="py-1 px-1.5 text-right font-mono font-semibold bg-rose-500/[0.06]">{r.h_maj_rank}</td>
                      <td className={`py-1 px-1.5 text-right font-mono bg-rose-500/[0.06] ${matchAiMaj ? "font-bold" : ""}`}>{r.h_maj_bt}</td>
                      <td className="py-1 px-1.5 text-right font-mono text-foreground/60 bg-rose-500/[0.06]">{r.h_maj_wl}</td>
                      <td className={`py-1 px-1.5 text-right text-[10px] capitalize ${TIER_COLORS[r.tier] || ""}`}>{r.decision || "\u2014"}</td>
                      <td className="py-1 px-1.5 text-right font-mono">{r.h1_avg_rating != null ? Number(r.h1_avg_rating).toFixed(1) : "\u2014"}</td>
                      <td className="py-1 px-1.5 text-left max-w-[300px] truncate" title={r.title}>{r.title}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-1">
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              <strong>AI BT</strong>: Elo from {rankData.n_ai_matches} thinking-mode matches (1 judge per pair, round-robin across 3 models).{" "}
              <strong>H-Indiv BT</strong>: Elo from individual expert votes (each expert{"'"}s preference = one match — multiple matches per pair).{" "}
              <strong>H-Maj BT</strong>: Elo from expert majority vote (one consensus vote per pair).{" "}
              Rows highlighted where AI BT = H-Maj BT — a structural artifact when both have 1 vote/pair on the same pairs with identical W/L records.{" "}
              H-Indiv BT breaks this coupling by using per-expert granularity.
            </p>
          </div>
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
          { group: "AI vs Human", label: "AI vs Individual aggregate", rho: bt.individual?.spearman_rho, tau: bt.individual?.kendall_tau, color: "sky", pair: "indiv", side: "ai",
            desc: "Each expert's vote on each pair is a separate BT match (preserving individual disagreements). AI BT is compared against this combined human BT" },
          { group: "", label: "AI vs Avg Rating", rho: bt.vs_avg_rating_rho, tau: null, pair: "avg", side: "ai",
            desc: "AI BT ranking vs simple average of reviewer scores — different methodologies (BT vs mean)" },
          { group: "", label: "AI vs Majority", rho: bt.committee?.spearman_rho, tau: bt.committee?.kendall_tau, color: "amber", pair: "maj", side: "ai",
            desc: "AI BT vs BT from majority-vote matches — one match per pair, loses margin information" },
          { group: "", label: "AI vs Committee (ICLR PC)", rho: bt.vs_tier_rho, tau: bt.vs_tier_tau, color: "rose", pair: "tier", side: "ai",
            desc: "AI BT vs actual program committee tier decisions — coarse (4 tiers only)" },
          { group: "Human internal", label: "Single expert vs Individual aggregate (LOO)", rho: bt.avg_expert_vs_loo_indiv?.spearman_rho, tau: bt.avg_expert_vs_loo_indiv?.kendall_tau, color: "sky", pair: "indiv", side: "h",
            desc: "One human reviewer vs all other reviewers (self excluded) — mirrors the AI row: single judge vs crowd. Apples-to-apples human ceiling" },
          { group: "", label: "Single expert vs Avg Rating (LOO)", rho: bt.avg_expert_vs_loo_avg?.spearman_rho, tau: bt.avg_expert_vs_loo_avg?.kendall_tau, pair: "avg", side: "h",
            desc: "One reviewer's BT vs LOO average scores — different methodologies (BT vs mean)" },
          { group: "", label: "Single expert vs Majority (LOO)", rho: bt.avg_expert_vs_loo?.spearman_rho, tau: bt.avg_expert_vs_loo?.kendall_tau, color: "amber", pair: "maj", side: "h",
            desc: "One reviewer's BT vs LOO majority BT — loses margin information, LOO ties skipped" },
          { group: "", label: "Single expert vs Committee (ICLR PC)", rho: bt.avg_expert_vs_tier?.spearman_rho, tau: bt.avg_expert_vs_tier?.kendall_tau, color: "rose", pair: "tier", side: "h",
            desc: "Expert BT vs tier decisions — circular (reviewers influenced the decisions)" },
          { group: "", label: "Single expert vs Majority", rho: bt.avg_expert_vs_comm?.spearman_rho, tau: bt.avg_expert_vs_comm?.kendall_tau, circular: true,
            desc: "Circular — expert's own votes are included in the majority" },
          { group: "", label: "Single expert vs Individual aggregate", rho: bt.avg_expert_vs_indiv?.spearman_rho, tau: bt.avg_expert_vs_indiv?.kendall_tau, circular: true,
            desc: "Circular — expert's own votes are included in the aggregate" },
        ];
        const aiRhos = { indiv: bt.individual?.spearman_rho, maj: bt.committee?.spearman_rho, tier: bt.vs_tier_rho, avg: bt.vs_avg_rating_rho };
        const hRhos = { indiv: bt.avg_expert_vs_loo_indiv?.spearman_rho, maj: bt.avg_expert_vs_loo?.spearman_rho, tier: bt.avg_expert_vs_tier?.spearman_rho, avg: bt.avg_expert_vs_loo_avg?.spearman_rho };
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
                    const bg = r.color === "rose" ? "bg-rose-500/[0.06]" : r.color === "amber" ? "bg-amber-500/[0.06]" : r.color === "sky" ? "bg-sky-500/[0.06]" : "";
                    // Bold: winner in paired comparison, or standalone metrics
                    let isWinner = false;
                    if (r.pair && r.side && r.rho != null) {
                      const opponent = r.side === "ai" ? hRhos[r.pair] : aiRhos[r.pair];
                      isWinner = opponent == null || r.rho >= opponent;
                    }
                    const bold = isWinner ? "font-semibold" : "";
                    const dim = r.circular ? "text-foreground/60 italic" : "";
                    return (
                      <tr key={i} className={`border-b border-border/20 ${showGroup && i > 0 ? "border-t border-border" : ""} ${bg}`}>
                        <td className={`py-1.5 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 ${showGroup ? "" : "text-transparent select-none"}`}>{r.group || lastGroup}</td>
                        <td className={`py-1.5 px-2 ${dim}`}>{r.label}</td>
                        <td className={`py-1.5 px-2 text-right font-mono ${bold} ${dim}`}>{f(r.rho)}</td>
                        <td className={`py-1.5 px-2 text-right font-mono ${dim}`}>{f(r.tau)}</td>
                        <td className="py-1.5 px-2 text-muted-foreground text-[10px]">{r.desc}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                All BT rankings use each method's full match data on <strong>controlled pairs</strong> (the same pair set for both AI and human).
                "Single expert" builds BT from each expert's preferences individually, then averages the correlation across all experts.
                <strong>Majority</strong> = virtual majority vote from reviewer preferences (our construction).
                <strong>Committee (ICLR PC)</strong> = actual program committee tier decisions (coarse: 4 tiers).
                Human vs Committee is circular (reviewers influenced the decisions).
                All pooled {"\u03C1"} values are <strong>equal-weighted across datasets</strong> (each dataset contributes one {"\u03C1"} regardless of size).
                Size-weighted pooling would lower all correlations because PeerRead ACL 2017 (the largest dataset by match count) has the weakest {"\u03C1"}.
              </p>
              {bt.vs_tier_rho != null && bt.avg_expert_vs_tier?.spearman_rho != null && (
                <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">
                  <strong>Key finding</strong> (highlighted rows): AI outperforms a single human expert at predicting committee decisions
                  ({bt.vs_tier_rho.toFixed(3)} vs {bt.avg_expert_vs_tier.spearman_rho.toFixed(3)}) — even though the human has
                  a circularity advantage (their scores influenced those very decisions). AI compensates with consistency:
                  no off-days or idiosyncratic biases that make individual reviewers disagree with the eventual consensus.
                </p>
              )}
              {bt.vs_tier_rho != null && bt.avg_expert_vs_tier?.spearman_rho != null && (
                <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">
                  <strong>Ceiling analysis:</strong> A 4-tier committee ranking (Oral/Spotlight/Poster/Reject) imposes a theoretical
                  maximum {"\u03C1"} {"\u2248"} 0.878 — even a perfect tier predictor with random within-tier ordering cannot exceed this.
                  AI reaches <strong>{(bt.vs_tier_rho / 0.878 * 100).toFixed(0)}%</strong> of this ceiling
                  ({bt.vs_tier_rho.toFixed(3)}), a single expert reaches {(bt.avg_expert_vs_tier.spearman_rho / 0.878 * 100).toFixed(0)}%
                  ({bt.avg_expert_vs_tier.spearman_rho.toFixed(3)}).
                  Notably, AI's {"\u03C1"} significantly exceeds what its 82.9% cross-tier accuracy alone would predict ({"\u03C1"} {"\u2248"} 0.58 for
                  random within-tier ordering at that accuracy) — indicating AI produces <strong>meaningful within-tier ranking</strong>,
                  not just correct tier classification. This is a <strong>conservative win for AI</strong>: the human's higher pairwise accuracy (87.9%)
                  comes from circularity, while AI's ranking advantage is earned without it.
                </p>
              )}
              <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">
                <strong>Tie handling in BT:</strong> BT correlations are computed on <strong>non-tie pairs only</strong> — pairs where
                at least one human reviewer expressed a preference. Pairs where all reviewers tied (gave both papers the same score)
                generate no BT match and are excluded.
                {p.tie_stats?.tie_fraction != null && <>{" "}With a {(p.tie_stats.tie_fraction * 100).toFixed(0)}% overall tie fraction,
                roughly {(p.tie_stats.tie_fraction * 100).toFixed(0)}% of potential pairs are invisible to the human BT ranking.
                Unlike pairwise agreement (which uses coin-flip correction for ties), BT has no equivalent correction —
                injecting random matches would corrupt the ranking model. The BT {"\u03C1"} therefore measures ranking quality
                on the <em>resolvable</em> subset of pairs, complementing the pairwise agreement metrics which account for ties explicitly.</>}
              </p>
            </div>
          </div>
        );
      })()}

      {/* 4. Inter-Rater Reliability (Human-Human + AI-Human) */}
      {/* Per-dataset breakdown */}

      {/* 5. Per-dataset breakdown */}
      <DatasetTable datasets={data.per_dataset} />

      {/* 6. Per-paper rankings for a selected dataset */}
      <DatasetRankings datasets={data.per_dataset} />
    </div>
  );
}

export default function HumanAIBenchmarkSection() {
  return <BenchmarkPage
    apiUrl="/api/validation/human-ai-benchmark?gt_type=comp"
    headerDesc={<>AI judges use <strong>Opus 4.6 Thinking</strong> summaries (abstract + AI impact assessment). Round-robin across GPT-5.2, Claude Opus, Gemini 3 Pro. <strong>Comparative GT</strong> (8 ICLR topics, PeerRead ACL 2017).</>}
    testId="human-ai-benchmark"
  />;
}
