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

function AgreementTable({ data }) {
  const p = data.pooled;
  const ag = p.agreement;
  const cf = p.coin_flip;
  const diff = p.by_difficulty;
  const levels = [
    { key: "easy", label: "Cross-tier (easy)", desc: "e.g., large score gap" },
    { key: "medium", label: "Adjacent-tier (medium)", desc: "e.g., moderate gap" },
    { key: "hard", label: "Within-tier (hard)", desc: "e.g., similar scores" },
  ];
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <Scale className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Pairwise Agreement — AI vs Aggregate Human Score</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "30%" }} />
            <col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-right font-medium">AI-GT agreement</th>
              <th className="py-1.5 px-2 text-right font-medium">kappa</th>
              <th className="py-1.5 px-2 text-right font-medium">GT tie rate</th>
              <th className="py-1.5 px-2 text-right font-medium">paper pairs</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border bg-accent/5">
              <td className="py-1.5 px-2 text-left text-xs font-semibold">Pooled (GT ties = coin flip)</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs font-bold">{cf?.rate ?? "\u2014"}%</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{ag?.kappa ?? "\u2014"}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{p.gt_tie_rate ?? "\u2014"}%</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs">{cf?.total?.toLocaleString()}</td>
            </tr>
            <tr className="border-b border-border/40">
              <td className="py-1.5 px-2 text-left text-xs text-foreground/60">Pooled (GT ties excluded)</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{ag?.rate ?? "\u2014"}%</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{ag?.kappa ?? "\u2014"}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60"></td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{ag?.pairs?.toLocaleString()}</td>
            </tr>
            {levels.map(({ key, label, desc }) => {
              const d = diff?.[key] || {};
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left text-xs">
                    <span className="text-foreground/60">{label}</span>
                    <span className="text-foreground/40 ml-1 text-[9px]">{desc}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{d.cf_rate != null ? `${d.cf_rate}%` : (d.rate != null ? `${d.rate}%` : "\u2014")}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60"></td>
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
          <strong>AI-GT agreement</strong> = how often the AI's pairwise preference matches the ground truth derived from
          the aggregate human score (h1_avg_rating). Standalone GT datasets have a single aggregate score per paper
          (not multiple independent reviewers), so Human-Human and Human-Committee metrics are not available.
          GT ties occur when two papers have the same aggregate score. The coin-flip row randomly resolves these ties.
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
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1 px-2 text-left font-medium">Dataset</th>
                <th className="py-1 px-2 text-right font-medium">AI-GT%</th>
                <th className="py-1 px-2 text-right font-medium">CF%</th>
                <th className="py-1 px-2 text-right font-medium">Ranking ρ</th>
                <th className="py-1 px-2 text-right font-medium">GT tie%</th>
                <th className="py-1 px-2 text-right font-medium">Pairs</th>
                <th className="py-1 px-2 text-right font-medium">Papers</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => (
                <tr key={d.dataset_id} className="border-b border-border/20">
                  <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                  <td className="py-1 px-2 text-right font-mono">{d.agreement?.rate ?? "\u2014"}%</td>
                  <td className="py-1 px-2 text-right font-mono">{d.coin_flip?.rate ?? "\u2014"}%</td>
                  <td className="py-1 px-2 text-right font-mono">{d.bt_correlation?.spearman_rho?.toFixed(3) ?? "\u2014"}</td>
                  <td className="py-1 px-2 text-right font-mono">{d.gt_tie_rate ?? "\u2014"}%</td>
                  <td className="py-1 px-2 text-right font-mono">{d.controlled_pairs}</td>
                  <td className="py-1 px-2 text-right font-mono">{d.n_papers}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StandaloneBenchmarkPage({ apiUrl, headerDesc, testId }) {
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
  const bt = p.bt_correlation || {};

  return (
    <div className="space-y-6" data-testid={testId}>
      <div className="text-[10px] text-muted-foreground mb-1 flex items-center justify-between flex-wrap gap-1">
        <span>{headerDesc}</span>
        <span className="font-mono text-muted-foreground/80">
          <strong>{data.total_controlled_pairs?.toLocaleString()}</strong> pairs across <strong>{data.total_papers?.toLocaleString()}</strong> papers ({data.avg_matches_per_paper} matches/paper avg)
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-GT Agreement" value={`${p.coin_flip?.rate ?? p.agreement?.rate ?? "\u2014"}%`} sub="GT ties = coin flip" accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="AI-GT (ties excl.)" value={`${p.agreement?.rate ?? "\u2014"}%`} sub="GT ties excluded" />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="Ranking Spearman ρ" value={bt.spearman_rho?.toFixed(3) ?? "\u2014"} sub="AI vs GT ranking" accent />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="GT Tie Rate" value={`${p.gt_tie_rate ?? "\u2014"}%`} sub="same aggregate score" />
        </div>
      </div>

      <AgreementTable data={data} />

      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}

export function StandalonePWSection() {
  return <StandaloneBenchmarkPage
    apiUrl="/api/validation/human-ai-benchmark?gt_type=stan"
    headerDesc={<>AI pairwise judges (best available mode) vs aggregate human scores. <strong>Standalone GT</strong> — reviewers scored papers independently (eLife biology, MIDL, Qeios, ResearchHub).</>}
    testId="pw-stan-benchmark"
  />;
}

export function StandaloneSISection() {
  return <StandaloneBenchmarkPage
    apiUrl="/api/validation/si-benchmark?gt_type=stan"
    headerDesc={<>AI single-item scores (<strong>Opus 4.6 Thinking</strong>, 1-10) vs aggregate human scores. <strong>Standalone GT</strong> — reviewers scored papers independently.</>}
    testId="si-stan-benchmark"
  />;
}
