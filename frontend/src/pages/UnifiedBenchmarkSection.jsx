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

function ComparisonTable({ data, gtType }) {
  const p = data.pooled;
  const levels = [
    { key: "easy", label: "Cross-tier (easy)" },
    { key: "medium", label: "Adjacent-tier (medium)" },
    { key: "hard", label: "Within-tier (hard)" },
  ];
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <Scale className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Pairwise Agreement — PW vs SI on Same Pairs</span>
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
              {gtType === "comp" && <th className="py-1.5 px-2 text-right font-medium">Human-Human</th>}
              <th className="py-1.5 px-2 text-right font-medium bg-violet-500/[0.06]">PW Spearman {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium bg-emerald-500/[0.06]">SI Spearman {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium">pairs</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border bg-accent/5">
              <td className="py-1.5 px-2 text-left text-xs font-semibold">Pooled</td>
              <td className={`py-1.5 px-2 text-right font-mono text-xs bg-violet-500/[0.06] ${p.pw_accuracy >= p.si_accuracy ? "font-bold" : ""}`}>{p.pw_accuracy}%</td>
              <td className={`py-1.5 px-2 text-right font-mono text-xs bg-emerald-500/[0.06] ${p.si_accuracy > p.pw_accuracy ? "font-bold" : ""}`}>{p.si_accuracy}%</td>
              {gtType === "comp" && <td className="py-1.5 px-2 text-right font-mono text-xs">{data.per_dataset?.[0]?.hh?.rate != null ? `${p.pw_accuracy}%` : "\u2014"}</td>}
              <td className={`py-1.5 px-2 text-right font-mono text-xs bg-violet-500/[0.06] ${(p.pw_rho || 0) >= (p.si_rho || 0) ? "font-bold" : ""}`}>{p.pw_rho?.toFixed(3) ?? "\u2014"}</td>
              <td className={`py-1.5 px-2 text-right font-mono text-xs bg-emerald-500/[0.06] ${(p.si_rho || 0) > (p.pw_rho || 0) ? "font-bold" : ""}`}>{p.si_rho?.toFixed(3) ?? "\u2014"}</td>
              <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{data.total_controlled_pairs?.toLocaleString()}</td>
            </tr>
            {levels.map(({ key, label }) => {
              const d = p.by_difficulty?.[key] || {};
              const pwBold = (d.pw_rate || 0) >= (d.si_rate || 0);
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left text-xs text-foreground/60">{label}</td>
                  <td className={`py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-violet-500/[0.06] ${pwBold ? "font-semibold" : ""}`}>{d.pw_rate != null ? `${d.pw_rate}%` : "\u2014"}</td>
                  <td className={`py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-emerald-500/[0.06] ${!pwBold ? "font-semibold" : ""}`}>{d.si_rate != null ? `${d.si_rate}%` : "\u2014"}</td>
                  {gtType === "comp" && <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{d.hh_rate != null ? `${d.hh_rate}%` : ""}</td>}
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-violet-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-emerald-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60">{(d.n_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-2">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>PW</strong> = pairwise AI judges (round-robin GPT-5.2, Opus, Gemini).{" "}
          <strong>SI</strong> = single-item AI scoring (Opus 4.6 Thinking, 1-10 per paper).{" "}
          Both evaluated on the <strong>exact same {data.total_controlled_pairs?.toLocaleString()} pairs</strong> across {data.total_papers} papers.{" "}
          {gtType === "comp"
            ? "Accuracy = AI preference vs individual expert preference (ties excluded). Spearman \u03C1 = AI BT ranking vs h1_avg_rating ranking."
            : "Accuracy = AI preference vs aggregate human score (h1_avg_rating). Spearman \u03C1 = AI BT ranking vs h1_avg_rating ranking."}
        </p>
        {p.pw_rho != null && p.si_rho != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Winner: {(p.pw_rho || 0) > (p.si_rho || 0) ? "Pairwise" : "Single-Item"}</strong> on ranking correlation
            (Spearman {"\u03C1"} {p.pw_rho?.toFixed(3)} vs {p.si_rho?.toFixed(3)}).
            {gtType === "comp"
              ? " Pairwise judges see both papers side-by-side, enabling direct comparison — this produces more accurate rankings when the ground truth was itself generated comparatively."
              : " Single-item scoring is more effective when human ground truth was generated from independent ratings rather than head-to-head comparisons."}
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
                <th className="py-1 px-2 text-right font-medium bg-violet-500/[0.06]">PW Acc</th>
                <th className="py-1 px-2 text-right font-medium bg-emerald-500/[0.06]">SI Acc</th>
                <th className="py-1 px-2 text-right font-medium bg-violet-500/[0.06]">PW {"\u03C1"}</th>
                <th className="py-1 px-2 text-right font-medium bg-emerald-500/[0.06]">SI {"\u03C1"}</th>
                <th className="py-1 px-2 text-right font-medium">Pairs</th>
                <th className="py-1 px-2 text-right font-medium">Papers</th>
                <th className="py-1 px-2 text-center font-medium">Winner</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pwRho = d.pw?.bt_rho || 0;
                const siRho = d.si?.bt_rho || 0;
                const pwWins = pwRho > siRho;
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className={`py-1 px-2 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{d.pw?.ai_human?.rate}%</td>
                    <td className={`py-1 px-2 text-right font-mono bg-emerald-500/[0.06] ${!pwWins ? "font-bold" : ""}`}>{d.si?.ai_human?.rate}%</td>
                    <td className={`py-1 px-2 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{d.pw?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className={`py-1 px-2 text-right font-mono bg-emerald-500/[0.06] ${!pwWins ? "font-bold" : ""}`}>{d.si?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className="py-1 px-2 text-right font-mono">{d.controlled_pairs}</td>
                    <td className="py-1 px-2 text-right font-mono">{d.n_papers}</td>
                    <td className="py-1 px-2 text-center">
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

function UnifiedPage({ apiUrl, headerDesc, testId, gtType }) {
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
          <strong>{data.total_controlled_pairs?.toLocaleString()}</strong> pairs across <strong>{data.total_papers}</strong> papers ({data.avg_matches_per_paper} matches/paper avg)
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="PW Accuracy" value={`${p.pw_accuracy}%`} sub="pairwise judges" accent={p.pw_accuracy >= p.si_accuracy} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label="SI Accuracy" value={`${p.si_accuracy}%`} sub="single-item scoring" accent={p.si_accuracy > p.pw_accuracy} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`PW Spearman \u03C1`} value={p.pw_rho?.toFixed(3) ?? "\u2014"} sub="AI vs h1_avg ranking" accent={(p.pw_rho || 0) >= (p.si_rho || 0)} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`SI Spearman \u03C1`} value={p.si_rho?.toFixed(3) ?? "\u2014"} sub="AI vs h1_avg ranking" accent={(p.si_rho || 0) > (p.pw_rho || 0)} />
        </div>
      </div>

      <ComparisonTable data={data} gtType={gtType} />
      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}

export function UnifiedCompSection() {
  return <UnifiedPage
    apiUrl="/api/validation/unified-benchmark?gt_type=comp"
    headerDesc={<>PW judges (round-robin GPT-5.2, Opus, Gemini) vs SI scoring (Opus 4.6 Thinking) on the exact same pairs. <strong>Comparative GT</strong> (ICLR, PeerRead).</>}
    testId="unified-comp"
    gtType="comp"
  />;
}

export function UnifiedStanSection() {
  return <UnifiedPage
    apiUrl="/api/validation/unified-benchmark?gt_type=stan"
    headerDesc={<>PW judges vs SI scoring on the exact same pairs. <strong>Standalone GT</strong> (eLife biology, MIDL, Qeios, ResearchHub) — aggregate human scores as ground truth.</>}
    testId="unified-stan"
    gtType="stan"
  />;
}
