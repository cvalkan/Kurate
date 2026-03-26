import { useState, useEffect } from "react";
import axios from "axios";
import { TrendingUp } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export function PwVsSiSection({ category, siData: externalSiData, viewMode = "aggregate" }) {
  const [data, setData] = useState(null);
  const [controlled, setControlled] = useState(false);

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
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
            Pairwise Tournament vs Single-Item Ranking
          </h2>
          <div className="flex items-center gap-0.5 p-0.5 bg-secondary/50 rounded-md" data-testid="pw-vs-si-toggle">
            {[["full", "Full"], ["ctrl", "Controlled"]].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setControlled(key === "ctrl")}
                className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
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
          const perModelSource = isAvg && data.avg_per_model ? data.avg_per_model : data.per_model;
          const withinSource = isAvg && data.avg_within_model ? data.avg_within_model : data.within_model;
          const mData = perModelSource?.[mk];
          if (!mData) return null;
          const wmData = withinSource?.[mk];
          const combinedRows = controlled
            ? (mData.controlled_rows || [])
            : (mData.rows || []);
          const withinRows = (wmData?.rows || []);
          const allRhos = [...combinedRows, ...withinRows].map(r => r.spearman_rho);
          const bestRho = allRhos.length > 0 ? Math.max(...allRhos) : null;
          const shortName = mData.label.split(" ")[0];
          return (
            <div key={mk} className="border border-border rounded-lg overflow-hidden" data-testid={`pw-vs-si-${mk}`}>
              <div className="px-3 py-1.5 bg-secondary/10 border-b border-border">
                <span className="text-[10px] font-semibold">vs {mData.label} Scores</span>
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
                    <tr><td colSpan={4} className="py-0.5 px-2 text-[9px] text-muted-foreground bg-secondary/5 font-medium">
                      {controlled ? "All judges (controlled)" : "All judges combined"}
                    </td></tr>
                  )}
                  {combinedRows.map(row => (
                    <tr key={`c-${row.method}`} className={`border-b border-border/10 ${row.spearman_rho === bestRho ? "bg-emerald-500/[0.04]" : ""}`}>
                      <td className="py-1 px-2 font-medium">{row.label}</td>
                      <td className={`py-1 px-2 text-right font-mono ${row.spearman_rho === bestRho ? "font-bold text-emerald-700" : "font-semibold"}`}>{row.spearman_rho.toFixed(3)}</td>
                      <td className="py-1 px-2 text-right font-mono">{row.kendall_tau.toFixed(3)}</td>
                      <td className="py-1 px-2 text-right font-mono text-muted-foreground">{row.avg_mpp || "—"}</td>
                    </tr>
                  ))}
                  {withinRows.length > 0 && (
                    <tr><td colSpan={4} className="py-0.5 px-2 text-[9px] text-muted-foreground bg-secondary/5 font-medium">
                      {shortName} only
                      {wmData?.n_matches ? <span className="ml-1 font-normal">({wmData.n_matches.toLocaleString()} matches)</span> : ""}
                    </td></tr>
                  )}
                  {withinRows.map(row => (
                    <tr key={`w-${row.method}`} className={`border-b border-border/10 ${row.spearman_rho === bestRho ? "bg-emerald-500/[0.04]" : ""}`}>
                      <td className="py-1 px-2 font-medium">{row.label}</td>
                      <td className={`py-1 px-2 text-right font-mono ${row.spearman_rho === bestRho ? "font-bold text-emerald-700" : "font-semibold"}`}>{row.spearman_rho.toFixed(3)}</td>
                      <td className="py-1 px-2 text-right font-mono">{row.kendall_tau.toFixed(3)}</td>
                      <td className="py-1 px-2 text-right font-mono text-muted-foreground">{row.avg_mpp || wmData?.avg_mpp || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </div>
  );
}
