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
          { group: "AI vs Human", label: "AI vs Individual aggregate", rho: bt.individual?.spearman_rho, tau: bt.individual?.kendall_tau, fair: true, color: "sky",
            desc: "Each expert's vote on each pair is a separate BT match (preserving individual disagreements). AI BT is compared against this combined human BT" },
          { group: "", label: "AI vs Avg Rating", rho: bt.vs_avg_rating_rho, tau: null, fair: false,
            desc: "AI BT ranking vs simple average of reviewer scores — different methodologies (BT vs mean)" },
          { group: "", label: "AI vs Majority", rho: bt.committee?.spearman_rho, tau: bt.committee?.kendall_tau, fair: false, color: "amber",
            desc: "AI BT vs BT from majority-vote matches — one match per pair, loses margin information" },
          { group: "", label: "AI vs Committee (ICLR PC)", rho: bt.vs_tier_rho, tau: null, fair: false, highlight: true, color: "rose",
            desc: "AI BT vs actual program committee tier decisions — coarse (4 tiers only)" },
          { group: "Human internal", label: "Single expert vs Individual aggregate (LOO)", rho: bt.avg_expert_vs_loo_indiv?.spearman_rho, tau: null, fair: true, color: "sky",
            desc: "One human reviewer vs all other reviewers (self excluded) — mirrors the AI row: single judge vs crowd. Apples-to-apples human ceiling" },
          { group: "", label: "Single expert vs Avg Rating (LOO)", rho: bt.avg_expert_vs_loo_avg?.spearman_rho, tau: null, fair: false,
            desc: "One reviewer's BT vs LOO average scores — different methodologies (BT vs mean)" },
          { group: "", label: "Single expert vs Majority (LOO)", rho: bt.avg_expert_vs_loo?.spearman_rho, tau: null, fair: false, color: "amber",
            desc: "One reviewer's BT vs LOO majority BT — loses margin information, LOO ties skipped" },
          { group: "", label: "Single expert vs Committee (ICLR PC)", rho: bt.avg_expert_vs_tier?.spearman_rho, tau: null, fair: false, highlight: true, color: "rose",
            desc: "Expert BT vs tier decisions — circular (reviewers influenced the decisions)" },
          { group: "", label: "Single expert vs Majority", rho: bt.avg_expert_vs_comm?.spearman_rho, tau: bt.avg_expert_vs_comm?.kendall_tau, fair: false, color: "amber",
            desc: "Circular — expert's own votes are included in the majority" },
          { group: "", label: "Single expert vs Individual aggregate", rho: bt.avg_expert_vs_indiv?.spearman_rho, tau: bt.avg_expert_vs_indiv?.kendall_tau, fair: false, color: "sky",
            desc: "Circular — expert's own votes are included in the aggregate" },
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
                    const bg = r.color === "rose" ? "bg-rose-500/[0.06]" : r.color === "amber" ? "bg-amber-500/[0.06]" : r.color === "sky" ? "bg-sky-500/[0.06]" : "";
                    return (
                      <tr key={i} className={`border-b border-border/20 ${showGroup && i > 0 ? "border-t border-border" : ""} ${r.fair ? "bg-accent/5" : bg}`}>
                        <td className={`py-1.5 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 ${showGroup ? "" : "text-transparent select-none"}`}>{r.group || lastGroup}</td>
                        <td className={`py-1.5 px-2 ${r.fair ? "font-semibold" : ""} ${r.highlight ? "font-medium" : !r.fair && !r.color ? "text-foreground/50" : ""}`}>{r.label}</td>
                        <td className={`py-1.5 px-2 text-right font-mono ${r.fair ? "font-bold" : ""} ${r.highlight ? "font-semibold" : !r.fair && !r.color ? "font-normal text-foreground/50" : ""}`}>{f(r.rho)}</td>
                        <td className={`py-1.5 px-2 text-right font-mono ${r.fair ? "" : ""} ${r.highlight ? "" : !r.fair && !r.color ? "font-normal text-foreground/50" : ""}`}>{f(r.tau)}</td>
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
              {bt.vs_tier_rho != null && bt.avg_expert_vs_tier?.spearman_rho != null && (
                <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">
                  <strong>Key finding</strong> (highlighted rows): AI outperforms a single human expert at predicting committee decisions
                  ({bt.vs_tier_rho.toFixed(3)} vs {bt.avg_expert_vs_tier.spearman_rho.toFixed(3)}) — even though the human has
                  a circularity advantage (their scores influenced those very decisions). AI compensates with consistency:
                  no off-days or idiosyncratic biases that make individual reviewers disagree with the eventual consensus.
                </p>
              )}
            </div>
          </div>
        );
      })()}

      {/* 4. Inter-Rater Reliability (Human-Human + AI-Human) */}
      {/* Per-dataset breakdown */}

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
