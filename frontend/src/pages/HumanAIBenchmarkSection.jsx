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

function ComparisonRow({ label, hh, hc, ah, ac, highlight }) {
  const fmt = (v) => v?.rate != null ? `${v.rate}%` : "—";
  const kfmt = (v) => v?.kappa != null ? v.kappa.toFixed(2) : "—";
  const nfmt = (v) => v?.pairs != null ? v.pairs.toLocaleString() : "—";
  return (
    <tr className={`border-b border-border/30 ${highlight ? "bg-accent/5" : ""}`}>
      <td className="py-1.5 px-2 text-left text-xs font-medium">{label}</td>
      <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(hh)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(hc)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(ah)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(ac)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{kfmt(ah)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{nfmt(hh)}</td>
    </tr>
  );
}

function DifficultyTable({ data }) {
  if (!data) return null;
  const levels = [
    { key: "easy", label: "Cross-tier (easy)", desc: "e.g., Oral vs Reject" },
    { key: "medium", label: "Adjacent-tier (medium)", desc: "e.g., Spotlight vs Poster" },
    { key: "hard", label: "Within-tier (hard)", desc: "e.g., Poster vs Poster" },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="py-1.5 px-2 text-left font-medium">Difficulty</th>
            <th className="py-1.5 px-2 text-right font-medium">H-H</th>
            <th className="py-1.5 px-2 text-right font-medium">H-Comm</th>
            <th className="py-1.5 px-2 text-right font-medium">H-Comm (LOO)</th>
            <th className="py-1.5 px-2 text-right font-medium">AI-H</th>
            <th className="py-1.5 px-2 text-right font-medium">AI-Comm</th>
            <th className="py-1.5 px-2 text-right font-medium text-[10px]">n (H-H)</th>
          </tr>
        </thead>
        <tbody>
          {levels.map(({ key, label, desc }) => {
            const d = data[key] || {};
            const fmt = (v) => v?.rate != null && v.pairs > 0 ? `${v.rate}%` : "—";
            const nfmt = (v) => v?.pairs > 0 ? v.pairs.toLocaleString() : "—";
            return (
              <tr key={key} className="border-b border-border/20">
                <td className="py-1.5 px-2 text-left">
                  <span className="font-medium">{label}</span>
                  <span className="text-muted-foreground/60 ml-1 text-[9px]">{desc}</span>
                </td>
                <td className="py-1.5 px-2 text-right font-mono">{fmt(d.human_human)}</td>
                <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{fmt(d.human_committee)}</td>
                <td className="py-1.5 px-2 text-right font-mono">{fmt(d.human_committee_loo)}</td>
                <td className="py-1.5 px-2 text-right font-mono">{fmt(d.ai_human)}</td>
                <td className="py-1.5 px-2 text-right font-mono">{fmt(d.ai_committee)}</td>
                <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{nfmt(d.human_human)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
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
                <th className="py-1 px-2 text-right font-medium">BT rho</th>
                <th className="py-1 px-2 text-right font-medium">Pairs</th>
                <th className="py-1 px-2 text-right font-medium">Experts</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pw = d.pairwise || {};
                const bt = d.bt_correlation || {};
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.ai_human?.rate ?? "—"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.human_human?.rate ?? "—"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.ai_committee?.rate ?? "—"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{pw.human_committee_loo?.rate ?? "—"}%</td>
                    <td className="py-1 px-2 text-right font-mono text-muted-foreground/60">{pw.human_committee?.rate ?? "—"}%</td>
                    <td className="py-1 px-2 text-right font-mono">{d.inter_rater_rho?.toFixed(2) ?? "—"}</td>
                    <td className="py-1 px-2 text-right font-mono">{bt.spearman_rho?.toFixed(2) ?? "—"}</td>
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
          <Metric label="H-Comm (LOO)" value={`${pw.human_committee_loo?.rate ?? "—"}%`} sub={`kappa = ${pw.human_committee_loo?.kappa ?? "—"}`} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-H Pairwise" value={`${pw.ai_human.rate}%`} sub={`kappa = ${pw.ai_human.kappa}`} accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-Committee" value={`${pw.ai_committee.rate}%`} sub={`kappa = ${pw.ai_committee.kappa}`} accent />
        </div>
      </div>

      {/* Main comparison table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
          <Scale className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Pairwise Agreement — Controlled Same-Pair Comparison</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1.5 px-2 text-left font-medium">Scope</th>
                <th className="py-1.5 px-2 text-right font-medium">H-H</th>
                <th className="py-1.5 px-2 text-right font-medium">H-Comm</th>
                <th className="py-1.5 px-2 text-right font-medium">H-Comm (LOO)</th>
                <th className="py-1.5 px-2 text-right font-medium">AI-H</th>
                <th className="py-1.5 px-2 text-right font-medium">AI-Comm</th>
                <th className="py-1.5 px-2 text-right font-medium text-[10px]">kappa (AI-H)</th>
                <th className="py-1.5 px-2 text-right font-medium text-[10px]">n (H-H)</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                const fmt = (v) => v?.rate != null ? `${v.rate}%` : "—";
                const kfmt = (v) => v?.kappa != null ? v.kappa.toFixed(2) : "—";
                const nfmt = (v) => v?.pairs != null ? v.pairs.toLocaleString() : "—";
                return (
                  <tr className="border-b border-border/30 bg-accent/5">
                    <td className="py-1.5 px-2 text-left text-xs font-medium">Pooled (all datasets)</td>
                    <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.human_human)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-xs text-muted-foreground">{fmt(pw.human_committee)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.human_committee_loo)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.ai_human)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-xs">{fmt(pw.ai_committee)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{kfmt(pw.ai_human)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-[10px] text-muted-foreground">{nfmt(pw.human_human)}</td>
                  </tr>
                );
              })()}
              {/* NeurIPS reference row removed */}
            </tbody>
          </table>
        </div>
        <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>H-H</strong> = individual expert vs individual expert.{" "}
            <strong>H-Comm</strong> = individual expert vs majority (expert is part of committee — inflated).{" "}
            <strong>H-Comm (LOO)</strong> = individual expert vs leave-one-out majority (expert excluded from committee — fair independent comparison).{" "}
            <strong>AI-H</strong> = AI (judge majority) vs individual expert.{" "}
            <strong>AI-Comm</strong> = AI majority vs expert majority committee.{" "}
            All computed on the exact same controlled paper pairs.
          </p>
        </div>
      </div>

      {/* Difficulty stratification */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
          <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Stratified by Difficulty</span>
        </div>
        <DifficultyTable data={p.by_difficulty} />
        <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            Cross-tier pairs (e.g., oral vs reject) are trivially easy for both humans and AI.
            Within-tier (hard) pairs are the most informative, as both raters must distinguish papers of similar quality.
          </p>
        </div>
      </div>

      {/* BT Rank Correlation */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <span className="text-xs font-semibold">Ranking Correlation (Bradley-Terry)</span>
        </div>
        <div className="px-3 py-3 flex items-center gap-6">
          <Metric label="Spearman rho" value={p.bt_correlation.spearman_rho?.toFixed(3) ?? "—"} sub="Human BT vs AI BT" />
          <Metric label="Kendall tau" value={p.bt_correlation.kendall_tau?.toFixed(3) ?? "—"} sub="Human BT vs AI BT" />
          {p.theoretical_ceiling && (
            <Metric label="Thurstonian ceiling" value={`${p.theoretical_ceiling}%`} sub={`Given rho = ${p.inter_rater_rho?.toFixed(2)}`} />
          )}
        </div>
        <div className="px-3 py-2 bg-secondary/5 border-t border-border/50">
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            BT rankings computed separately from human-derived matches and AI matches on the same paper sets.
            Spearman rho measures rank-order agreement. The Thurstonian ceiling is the maximum achievable pairwise agreement
            given the observed inter-rater noise (rho = {p.inter_rater_rho?.toFixed(2)}), computed from the Thurstonian model:
            P(agree) = Phi(dq / sqrt(2sigma^2))^2 + (1 - Phi(dq / sqrt(2sigma^2)))^2.
            rho here is the average Spearman rank correlation between reviewer pairs (ordering-based, not score-magnitude-based).
          </p>
        </div>
      </div>

      {/* Per-dataset breakdown */}
      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}
