import { useState, useEffect } from "react";
import axios from "axios";
import { Scale, TrendingUp, ChevronDown, ChevronRight } from "lucide-react";

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

function AgreementTable({ pw, difficulty, totalPairs }) {
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
              <th className="py-1.5 px-2 text-right font-medium">H-H</th>
              <th className="py-1.5 px-2 text-right font-medium">H-Comm</th>
              <th className="py-1.5 px-2 text-right font-medium">H-Comm (LOO)</th>
              <th className="py-1.5 px-2 text-right font-medium">AI-H</th>
              <th className="py-1.5 px-2 text-right font-medium">AI-Comm</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">kappa (AI-H)</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">paper pairs</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border bg-accent/5">
              <td className="py-1.5 px-2 text-left text-xs font-semibold">Pooled (all datasets)</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.human_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{fmt(pw.human_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.human_committee_loo)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.ai_committee)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{kfmt(pw.ai_human)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{totalPairs?.toLocaleString()}</td>
            </tr>
            {difficulty && levels.map(({ key, label, desc }) => {
              const d = difficulty[key] || {};
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left">
                    <span className="font-medium text-muted-foreground">{label}</span>
                    <span className="text-muted-foreground/50 ml-1 text-[9px]">{desc}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{fmt(d.human_human)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground/60">{fmt(d.human_committee)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{fmt(d.human_committee_loo)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{fmt(d.ai_human)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{fmt(d.ai_committee)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground/40"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground/60">{(d.n_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>H-H</strong> = individual expert vs individual expert.{" "}
          <strong>H-Comm</strong> = individual expert vs majority (expert is part of committee — inflated).{" "}
          <strong>H-Comm (LOO)</strong> = individual expert vs leave-one-out majority (fair independent comparison).{" "}
          <strong>AI-H</strong> = AI (judge majority) vs individual expert.{" "}
          <strong>AI-Comm</strong> = AI majority vs expert majority committee.{" "}
          All computed on the exact same controlled paper pairs. Difficulty rows break down the pooled row by tier gap.
        </p>
      </div>
    </div>
  );
}

function ReliabilityTables({ p }) {
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
        <span className="text-xs font-semibold">Inter-Rater Reliability</span>
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
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>Human-Human:</strong> For each pair of reviewers sharing 5+ papers, we count concordance on non-tie paper pairs.{" "}
          <strong>AI-Human:</strong> For each expert, we count how often AI agrees with their preference (averaged per expert, not pooled).{" "}
          Both exclude tie pairs where a reviewer gave both papers the same score.
        </p>
      </div>
    </div>
  );
}

function TieImpactTable({ tieImpact }) {
  if (!tieImpact) return null;
  const hh = tieImpact.hh || {};
  const ah = tieImpact.ah || {};
  const counts = tieImpact.tie_counts || {};
  const scenarios = [
    { key: "excluded", label: "Excluded (current)", desc: "Tie pairs removed from analysis" },
    { key: "coin_flip", label: "Ties = coin flip", desc: "Tied reviewer randomly picks one paper" },
  ];
  const hhCf = hh.coin_flip?.rate;
  const ahCf = ah.coin_flip?.rate;
  const gap = hhCf != null && ahCf != null ? Math.abs(hhCf - ahCf).toFixed(1) : null;
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Tie Impact Analysis</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Tie handling</th>
              <th className="py-1.5 px-2 text-right font-medium">H-H agreement</th>
              <th className="py-1.5 px-2 text-right font-medium">AI-H agreement</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">n (H-H)</th>
              <th className="py-1.5 px-2 text-right font-medium text-[10px]">n (AI-H)</th>
              <th className="py-1.5 px-2 text-left font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map(({ key, label, desc }) => (
              <tr key={key} className={`border-b border-border/20 ${key === "excluded" ? "bg-accent/5" : ""}`}>
                <td className="py-1.5 px-2 font-medium">{label}</td>
                <td className="py-1.5 px-2 text-right font-mono font-bold">{hh[key]?.rate ?? "\u2014"}%</td>
                <td className="py-1.5 px-2 text-right font-mono font-bold">{ah[key]?.rate ?? "\u2014"}%</td>
                <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{(hh[key]?.n ?? 0).toLocaleString()}</td>
                <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{(ah[key]?.n ?? 0).toLocaleString()}</td>
                <td className="py-1.5 px-2 text-muted-foreground text-[10px]">{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          {gap != null && (
            <><strong>Key finding:</strong> When ties are resolved randomly (coin flip), H-H and AI-H agreement
            are within <strong>{gap} percentage points</strong> ({hhCf}% vs {ahCf}%).
            The apparent advantage of H-H over AI-H in the "excluded" scenario ({hh.excluded?.rate}% vs {ah.excluded?.rate}%)
            is largely an artifact of dropping tie pairs: humans who agree on a clear preference tend to agree on which paper is better,
            but this selects for easy comparisons. AI, which never ties, is measured on a harder mix of pairs.
            Under fair conditions (coin flip), <strong>AI judges perform on par with human experts</strong>.{" "}</>
          )}
          H-H ties: {(counts.hh_one_tie ?? 0).toLocaleString()} pairs with one expert tied, {(counts.hh_both_tie ?? 0).toLocaleString()} with both tied.{" "}
          AI-H ties: {(counts.ah_tie ?? 0).toLocaleString()} expert comparisons where the expert ties. "Coin flip" shows the expected value.
        </p>
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

  return (
    <div className="space-y-6" data-testid="human-ai-benchmark">
      {/* Header metrics */}
      <div className="text-[10px] text-muted-foreground mb-1 flex items-center justify-between flex-wrap gap-1">
        <span>AI judges use <strong>Opus 4.6 Thinking</strong> summaries (abstract + AI impact assessment). Majority vote across GPT-5.2, Claude Opus, Gemini 3 Pro.</span>
        <span className="font-mono text-muted-foreground/80"><strong>{data.total_controlled_pairs?.toLocaleString()}</strong> total pairs evaluated</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="H-H Pairwise" value={`${pw.human_human.rate}%`} sub={`kappa = ${pw.human_human.kappa}`} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="H-Comm (LOO)" value={`${pw.human_committee_loo?.rate ?? "\u2014"}%`} sub={`kappa = ${pw.human_committee_loo?.kappa ?? "\u2014"}`} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-H Pairwise" value={`${pw.ai_human.rate}%`} sub={`kappa = ${pw.ai_human.kappa}`} accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-Committee" value={`${pw.ai_committee.rate}%`} sub={`kappa = ${pw.ai_committee.kappa}`} accent />
        </div>
      </div>

      {/* 1. Merged agreement + difficulty table */}
      <AgreementTable pw={pw} difficulty={p.by_difficulty} totalPairs={data.total_controlled_pairs} />

      {/* 2. Tie Impact Analysis */}
      <TieImpactTable tieImpact={p.tie_impact} />

      {/* 3. Ranking Correlation (Bradley-Terry) */}
      {(() => {
        const bt = p.bt_correlation || {};
        const f = (v) => v?.toFixed(3) ?? "\u2014";
        const rows = [
          { group: "AI vs Human", label: "AI vs Committee", rho: bt.committee?.spearman_rho, tau: bt.committee?.kendall_tau,
            desc: "AI BT vs expert-majority BT" },
          { group: "", label: "AI vs Individual aggregate", rho: bt.individual?.spearman_rho, tau: bt.individual?.kendall_tau,
            desc: "AI BT vs all-expert-votes BT" },
          { group: "Human internal", label: "Avg single expert vs Committee", rho: bt.avg_expert_vs_comm?.spearman_rho, tau: bt.avg_expert_vs_comm?.kendall_tau,
            desc: "Each expert's BT vs committee BT (averaged)" },
          { group: "", label: "Avg single expert vs Individual aggregate", rho: bt.avg_expert_vs_indiv?.spearman_rho, tau: bt.avg_expert_vs_indiv?.kendall_tau,
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
      <ReliabilityTables p={p} />

      {/* 5. Per-dataset breakdown */}
      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}
