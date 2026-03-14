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

function ComparisonTable({ data }) {
  const p = data.pooled;
  const levels = [
    { key: "easy", label: "Cross-tier (easy)" },
    { key: "medium", label: "Adjacent-tier (medium)" },
    { key: "hard", label: "Within-tier (hard)" },
  ];
  const pwWins = (p.intersection?.pw_accuracy || 0) >= (p.intersection?.si_accuracy || 0);
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <Scale className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">PW vs SI — Accuracy on Same Pairs, Ranking on Full Data</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "25%" }} />
            <col /><col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-right font-medium bg-violet-500/[0.06]">PW Accuracy</th>
              <th className="py-1.5 px-2 text-right font-medium bg-emerald-500/[0.06]">SI Accuracy</th>
              <th className="py-1.5 px-2 text-right font-medium bg-violet-500/[0.06]">PW Spearman {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium bg-emerald-500/[0.06]">SI Spearman {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium text-foreground/50">pairs</th>
            </tr>
          </thead>
          <tbody>
            {p.intersection && (
              <tr className="border-b border-border bg-accent/5">
                <td className="py-1.5 px-2 text-left text-xs font-semibold">Pooled (same pairs)</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{p.intersection.pw_accuracy}%</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-emerald-500/[0.06] ${!pwWins ? "font-bold" : ""}`}>{p.intersection.si_accuracy}%</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-violet-500/[0.06] ${(p.pw_rho || 0) >= (p.si_rho || 0) ? "font-bold" : ""}`}>{p.pw_rho?.toFixed(3) ?? "\u2014"}</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-emerald-500/[0.06] ${(p.si_rho || 0) > (p.pw_rho || 0) ? "font-bold" : ""}`}>{p.si_rho?.toFixed(3) ?? "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/50">{p.intersection.pairs?.toLocaleString()}</td>
              </tr>
            )}
            {levels.map(({ key, label }) => {
              const d = p.by_difficulty?.[key] || {};
              const pwB = (d.pw_rate || 0) >= (d.si_rate || 0);
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left text-xs text-foreground/60">{label}</td>
                  <td className={`py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-violet-500/[0.06] ${pwB ? "font-semibold" : ""}`}>{d.pw_rate != null ? `${d.pw_rate}%` : "\u2014"}</td>
                  <td className={`py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-emerald-500/[0.06] ${!pwB ? "font-semibold" : ""}`}>{d.si_rate != null ? `${d.si_rate}%` : "\u2014"}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-violet-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-emerald-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/40">{(d.pw_pairs ?? d.si_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-2">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>PW</strong> = pairwise AI judges (round-robin GPT-5.2, Opus, Gemini).{" "}
          <strong>SI</strong> = single-item AI scoring (Opus 4.6 Thinking, 1-10).{" "}
          <strong>Accuracy</strong> is on the <strong>same {p.intersection?.pairs?.toLocaleString()} pairs</strong> where both methods have verdicts — ensuring a fair per-pair comparison.{" "}
          <strong>Spearman {"\u03C1"}</strong> uses each method's full data (PW: {p.pw_pairs?.toLocaleString()} matches, SI: {p.si_pairs?.toLocaleString()} pairs)
          because ranking quality depends on each method's total output.{" "}
          Both compared against <strong>h1_avg_rating</strong> (averaged human reviewer scores).
        </p>
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>Why split the metrics:</strong>{" "}
          Accuracy on different pair sets is confounded by difficulty — SI's C(n,2) pairs include more close-quality papers that are harder to judge.
          On the same pairs, the comparison is controlled. Ranking {"\u03C1"} is holistic — in practice, you deploy one method and use all its data to rank papers.
        </p>
        {p.pw_rho != null && p.si_rho != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Winner: {(p.pw_rho || 0) > (p.si_rho || 0) ? "Pairwise" : "Single-Item"}</strong> on ranking correlation
            (Spearman {"\u03C1"} {p.pw_rho?.toFixed(3)} vs {p.si_rho?.toFixed(3)}).
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
                <th className="py-1 px-1.5 text-right font-medium bg-violet-500/[0.06]">PW Acc</th>
                <th className="py-1 px-1.5 text-right font-medium bg-emerald-500/[0.06]">SI Acc</th>
                <th className="py-1 px-1.5 text-right font-medium bg-violet-500/[0.06]">PW {"\u03C1"}</th>
                <th className="py-1 px-1.5 text-right font-medium bg-emerald-500/[0.06]">SI {"\u03C1"}</th>
                <th className="py-1 px-1.5 text-right font-medium text-foreground/50">Pairs</th>
                <th className="py-1 px-1.5 text-right font-medium">Papers</th>
                <th className="py-1 px-1.5 text-center font-medium">Winner</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pwRho = d.pw?.bt_rho || 0;
                const siRho = d.si?.bt_rho || 0;
                const pwWins = pwRho > siRho;
                const intr = d.intersection || {};
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{intr.pw_accuracy ?? d.pw?.accuracy}%</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-emerald-500/[0.06] ${!pwWins ? "font-bold" : ""}`}>{intr.si_accuracy ?? d.si?.accuracy}%</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{d.pw?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-emerald-500/[0.06] ${!pwWins ? "font-bold" : ""}`}>{d.si?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono text-foreground/50">{intr.pairs?.toLocaleString() ?? "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono">{d.n_papers}</td>
                    <td className="py-1 px-1.5 text-center">
                      <span className={`text-[9px] font-semibold ${pwWins ? "text-violet-700" : "text-emerald-700"}`}>{pwWins ? "PW" : "SI"}</span>
                    </td>
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

function UnifiedPage({ apiUrl, headerDesc, testId }) {
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

  return (
    <div className="space-y-6" data-testid={testId}>
      <div className="text-[10px] text-muted-foreground mb-1 flex items-center justify-between flex-wrap gap-1">
        <span>{headerDesc}</span>
        <span className="font-mono text-muted-foreground/80">
          {data.n_datasets} datasets
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="PW Accuracy" value={`${p.intersection?.pw_accuracy ?? p.pw_accuracy}%`} sub={`${p.intersection?.pairs?.toLocaleString()} same pairs`} accent={(p.intersection?.pw_accuracy || p.pw_accuracy) >= (p.intersection?.si_accuracy || p.si_accuracy)} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="SI Accuracy" value={`${p.intersection?.si_accuracy ?? p.si_accuracy}%`} sub={`${p.intersection?.pairs?.toLocaleString()} same pairs`} accent={(p.intersection?.si_accuracy || p.si_accuracy) > (p.intersection?.pw_accuracy || p.pw_accuracy)} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`PW Spearman \u03C1`} value={p.pw_rho?.toFixed(3) ?? "\u2014"} sub="BT ranking vs h1_avg" accent={(p.pw_rho || 0) >= (p.si_rho || 0)} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`SI Spearman \u03C1`} value={p.si_rho?.toFixed(3) ?? "\u2014"} sub="score ranking vs h1_avg" accent={(p.si_rho || 0) > (p.pw_rho || 0)} />
        </div>
      </div>

      <ComparisonTable data={data} />
      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}

export function UnifiedCompSection() {
  return <UnifiedPage
    apiUrl="/api/validation/unified-benchmark?gt_type=comp"
    headerDesc={<>PW judges (round-robin) vs SI scoring (Opus 4.6 Thinking) — accuracy on same pairs, ranking on full data. <strong>Comparative GT</strong> (ICLR, PeerRead, eLife Neuro).</>}
    testId="unified-comp"
  />;
}

export function UnifiedStanSection() {
  return <UnifiedPage
    apiUrl="/api/validation/unified-benchmark?gt_type=stan"
    headerDesc={<>PW judges vs SI scoring — accuracy on same pairs, ranking on full data. <strong>Standalone GT</strong> (eLife, MIDL, Qeios, ResearchHub).</>}
    testId="unified-stan"
  />;
}
