import { useState, useEffect } from "react";
import axios from "axios";
import { TrendingUp, ShieldCheck } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const COH_COLORS = {
  claude: { line: "#c084fc", dot: "bg-purple-500" },
  gpt: { line: "#60a5fa", dot: "bg-blue-500" },
  gemini: { line: "#34d399", dot: "bg-emerald-500" },
};

function CoherenceChart({ models }) {
  const modelKeys = Object.keys(models).sort();
  const binLabels = models[modelKeys[0]]?.bins?.map(b => b.label) || [];

  return (
    <div className="relative">
      <div className="flex items-end gap-2 mb-1">
        <span className="text-[10px] text-muted-foreground font-medium">Agreement %</span>
        <div className="flex-1" />
        <span className="text-[10px] text-muted-foreground font-medium">SI score gap (|s(A) − s(B)|)</span>
      </div>
      <div className="relative h-44 border-l border-b border-border/40 ml-8">
        {[100, 80, 60, 40].map(pct => (
          <div key={pct} className="absolute left-0 right-0 border-t border-border/15" style={{ bottom: `${pct}%` }}>
            <span className="absolute -left-9 -top-2 text-[10px] text-muted-foreground font-mono">{pct}%</span>
          </div>
        ))}
        <div className="absolute left-0 right-0 border-t border-dashed border-amber-400/40" style={{ bottom: "50%" }}>
          <span className="absolute right-1 -top-3 text-[10px] text-amber-600/60 font-medium">coin flip</span>
        </div>
        <div className="absolute inset-0 flex">
          {binLabels.map((label, bi) => (
            <div key={label} className="flex-1 relative flex items-end justify-center gap-px px-px">
              {modelKeys.map(mk => {
                const bin = models[mk]?.bins?.[bi];
                const rate = bin?.agreement_rate;
                if (rate == null || bin.n === 0) return <div key={mk} className="flex-1" />;
                const h = Math.max(rate * 100, 1);
                const col = COH_COLORS[mk] || COH_COLORS.claude;
                return (
                  <div key={mk} className="flex-1 flex flex-col items-center justify-end h-full" data-testid={`coherence-bar-${mk}-${bi}`}>
                    <div
                      className="w-full max-w-5 rounded-t-sm transition-all relative group"
                      style={{ height: `${h}%`, backgroundColor: col.line, opacity: 0.75 }}
                    >
                      <div className="absolute -top-5 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 bg-background border border-border rounded px-1 py-0.5 text-[10px] font-mono whitespace-nowrap shadow-sm z-10 pointer-events-none">
                        {(rate * 100).toFixed(1)}% (n={bin.n})
                      </div>
                    </div>
                  </div>
                );
              })}
              <span className="absolute -bottom-5 left-0 right-0 text-center text-[10px] text-muted-foreground font-mono">{label}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-center gap-4 mt-6">
        {modelKeys.map(mk => {
          const m = models[mk];
          const col = COH_COLORS[mk] || COH_COLORS.claude;
          return (
            <div key={mk} className="flex items-center gap-1.5 text-[10px]">
              <div className={`w-2.5 h-2.5 rounded-sm ${col.dot}`} />
              <span className="font-medium">{m.label}</span>
              <span className="text-muted-foreground">({(m.overall_agreement * 100).toFixed(1)}%, n={m.total_pairs.toLocaleString()})</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CoherenceTable({ models }) {
  const modelKeys = Object.keys(models).sort();
  const binLabels = models[modelKeys[0]]?.bins?.map(b => b.label) || [];

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-border text-muted-foreground bg-secondary/5">
          <th className="py-1.5 px-2 text-left font-medium">Model</th>
          <th className="py-1.5 px-2 text-right font-medium">Overall</th>
          {binLabels.map(l => (
            <th key={l} className="py-1.5 px-1.5 text-right font-medium font-mono text-[10px]">{l}</th>
          ))}
          <th className="py-1.5 px-2 text-right font-medium">n</th>
        </tr>
      </thead>
      <tbody>
        {modelKeys.map(mk => {
          const m = models[mk];
          const col = COH_COLORS[mk] || COH_COLORS.claude;
          return (
            <tr key={mk} className="border-b border-border/20" data-testid={`coherence-row-${mk}`}>
              <td className="py-1.5 px-2 font-medium flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-sm ${col.dot}`} />
                {m.label}
              </td>
              <td className="py-1.5 px-2 text-right font-mono font-semibold">
                {(m.overall_agreement * 100).toFixed(1)}%
              </td>
              {m.bins.map((bin, i) => {
                const rate = bin.agreement_rate;
                const isBest = rate != null && modelKeys.every(mk2 => {
                  const other = models[mk2]?.bins?.[i]?.agreement_rate;
                  return other == null || rate >= other;
                });
                return (
                  <td key={i} className={`py-1.5 px-1.5 text-right font-mono text-[10px] ${isBest ? "font-bold text-emerald-700" : ""}`}>
                    {rate != null ? `${(rate * 100).toFixed(1)}%` : "\u2014"}
                    {bin.n > 0 && <span className="text-muted-foreground/50 ml-0.5 text-[10px]">({bin.n})</span>}
                  </td>
                );
              })}
              <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{m.total_pairs.toLocaleString()}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function PwVsSiSection({ category, siData: externalSiData, viewMode = "aggregate", osUpdatedAt, coherenceData }) {
  const [data, setData] = useState(externalSiData?.pw_vs_si || null);
  const [controlled, setControlled] = useState(false);

  // Derive avgData directly from prop — no state needed
  const avgData = externalSiData?.avg_pw_vs_si || null;

  useEffect(() => {
    if (externalSiData?.pw_vs_si) {
      setData(externalSiData.pw_vs_si);
      return;
    }
    const params = category ? { category } : {};
    axios.get(`${API}/api/si-rating-stats`, { params, timeout: 60000 })
      .then(r => { if (r.data?.pw_vs_si) setData(r.data.pw_vs_si); })
      .catch(() => {});
  }, [category, externalSiData]);

  if (!data || !data.per_model || Object.keys(data.per_model).length === 0) return null;

  return (
    <div className="mb-8 space-y-4" data-testid="pw-vs-si-section">
      <div className="mb-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="font-heading text-lg font-semibold tracking-tight flex items-center gap-2">
            <a href="#pw-vs-si" className="flex items-center gap-2 hover:text-accent transition-colors">
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
            Pairwise Tournament vs Single-Item Ranking
            </a>
          </h2>
          <div className="flex items-center gap-0.5 p-0.5 bg-secondary/50 rounded-md" data-testid="pw-vs-si-toggle">
            {[["full", "Full"], ["ctrl", "Controlled"]].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setControlled(key === "ctrl")}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                  (key === "ctrl") === controlled
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                data-testid={`pw-vs-si-${key}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-muted-foreground text-xs mt-1 max-w-2xl">
          {controlled
            ? "Controlled: combined PW subsampled to same matches/paper as single judge. Shows whether multi-judge diversity adds signal beyond match count."
            : `How well does the tournament ranking correlate with each model's direct 1-10 quality scores? "All judges" uses all models' matches (${data.n_matches?.toLocaleString()} total); "single judge" isolates each model's own matches.`
          }
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {["claude", "gpt", "gemini"].map(mk => {
          const isAvg = viewMode === "average";
          const mDataAgg = data.per_model?.[mk];
          const wmDataAgg = data.within_model?.[mk];

          // In Average mode: use averaged rows (WR/TS + OS all computed per-category)
          let combinedRows, withinRows;
          if (controlled && isAvg && avgData?.per_model?.[mk]) {
            combinedRows = avgData.per_model[mk].controlled_rows || [];
            withinRows = avgData.within_model?.[mk]?.rows || [];
          } else if (controlled) {
            combinedRows = mDataAgg?.controlled_rows || [];
            withinRows = wmDataAgg?.rows || [];
          } else if (isAvg && avgData?.per_model?.[mk]) {
            combinedRows = avgData.per_model[mk].rows || [];
            withinRows = avgData.within_model?.[mk]?.rows || [];
          } else {
            combinedRows = mDataAgg?.rows || [];
            withinRows = wmDataAgg?.rows || [];
          }

          if (!mDataAgg) return null;
          const allRhos = [...combinedRows, ...withinRows].map(r => r.spearman_rho);
          const bestRho = allRhos.length > 0 ? Math.max(...allRhos) : null;
          const shortName = mDataAgg.label.split(" ")[0];
          return (
            <div key={mk} className="border border-border rounded-lg overflow-hidden" data-testid={`pw-vs-si-${mk}`}>
              <div className="px-3 py-1.5 bg-secondary/10 border-b border-border">
                <span className="text-[10px] font-semibold">vs {mDataAgg.label} Scores</span>
              </div>
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-border/50 text-muted-foreground">
                    <th className="py-1 px-2 text-left font-medium">Ranking Method</th>
                    <th className="py-1 px-2 text-right font-medium">{"\u03C1"}</th>
                    <th className="py-1 px-2 text-right font-medium">{"\u03C4"}</th>
                    <th className="py-1 px-2 text-right font-medium">m/paper</th>
                  </tr>
                </thead>
                <tbody>
                  {combinedRows.length > 0 && (
                    <tr><td colSpan={4} className="py-0.5 px-2 text-[10px] text-muted-foreground bg-secondary/5 font-medium">
                      {controlled ? "All judges (controlled)" : "All judges combined"}
                    </td></tr>
                  )}
                  {combinedRows.map(row => (
                    <tr key={`c-${row.method}`} className={`border-b border-border/10 ${row.spearman_rho === bestRho ? "bg-emerald-500/[0.04]" : ""}`}>
                      <td className="py-1 px-2 font-medium">{row.label}</td>
                      <td className={`py-1 px-2 text-right font-mono ${row.spearman_rho === bestRho ? "font-bold text-emerald-700" : "font-semibold"}`}>{row.spearman_rho?.toFixed(3) ?? "—"}</td>
                      <td className="py-1 px-2 text-right font-mono">{row.kendall_tau?.toFixed(3) ?? "—"}</td>
                      <td className="py-1 px-2 text-right font-mono text-muted-foreground">{row.avg_mpp || "—"}</td>
                    </tr>
                  ))}
                  {withinRows.length > 0 && (
                    <tr><td colSpan={4} className="py-0.5 px-2 text-[10px] text-muted-foreground bg-secondary/5 font-medium">
                      {shortName} only
                      {wmDataAgg?.n_matches ? <span className="ml-1 font-normal">({wmDataAgg.n_matches.toLocaleString()} matches)</span> : ""}
                    </td></tr>
                  )}
                  {withinRows.map(row => (
                    <tr key={`w-${row.method}`} className={`border-b border-border/10 ${row.spearman_rho === bestRho ? "bg-emerald-500/[0.04]" : ""}`}>
                      <td className="py-1 px-2 font-medium">{row.label}</td>
                      <td className={`py-1 px-2 text-right font-mono ${row.spearman_rho === bestRho ? "font-bold text-emerald-700" : "font-semibold"}`}>{row.spearman_rho?.toFixed(3) ?? "—"}</td>
                      <td className="py-1 px-2 text-right font-mono">{row.kendall_tau?.toFixed(3) ?? "—"}</td>
                      <td className="py-1 px-2 text-right font-mono text-muted-foreground">{row.avg_mpp || wmDataAgg?.avg_mpp || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
      {osUpdatedAt && (
        <p className="text-xs text-muted-foreground mt-2" data-testid="os-footnote">
          OpenSkill rows from {new Date(osUpdatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}.
        </p>
      )}

      {/* Score–Pairwise Coherence subsection */}
      {coherenceData?.status === "ok" && coherenceData.models && Object.keys(coherenceData.models).length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="coherence-section">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
            <div>
              <span className="text-xs font-semibold">Score–Pairwise Coherence</span>
              <span className="text-[10px] text-muted-foreground ml-1.5">
                When a model's SI score predicts s(A) &gt; s(B), does it also pick A in a head-to-head?
              </span>
            </div>
          </div>
          <div className="p-4">
            <CoherenceChart models={coherenceData.models} />
          </div>
          <div className="border-t border-border">
            <CoherenceTable models={coherenceData.models} />
          </div>
        </div>
      )}
    </div>
  );
}
