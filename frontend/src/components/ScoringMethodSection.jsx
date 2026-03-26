import { useState, useEffect } from "react";
import axios from "axios";
import { Activity } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const METHOD_COLORS = {
  "win_rate vs trueskill": "bg-violet-500/10",
};

export function ScoringMethodSection({ category }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = category ? { category } : {};
    axios.get(`${API}/api/scoring-method-correlation`, { params, timeout: 60000 })
      .then(r => { if (r.data?.status === "ok") setData(r.data); else setData(null); })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [category]);

  if (loading) return (
    <div className="my-6" data-testid="scoring-method-section-loading">
      <div className="flex items-center gap-3 mb-3">
        <div className="h-4 w-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
        <span className="text-xs text-muted-foreground">Computing scoring method correlations&hellip;</span>
      </div>
      <div className="space-y-2 animate-pulse">
        <div className="h-5 w-48 bg-secondary/30 rounded" />
        <div className="h-32 bg-secondary/30 rounded-lg" />
      </div>
    </div>
  );

  if (!data) return null;

  const f = v => v?.toFixed(4) ?? "\u2014";

  return (
    <div className="mb-8" data-testid="scoring-method-section">
      <div className="mb-3">
        <h2 className="font-heading text-lg font-semibold tracking-tight flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          Scoring Method Agreement
        </h2>
        <p className="text-muted-foreground text-xs mt-1 max-w-2xl">
          How similarly do different ranking algorithms order {data.n_papers.toLocaleString()} papers
          from {data.n_matches.toLocaleString()} pairwise matches?
          High correlations mean the leaderboard is robust to scoring method choice.
        </p>
      </div>

      {/* Correlation table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-border bg-secondary/10 text-muted-foreground">
              <th className="py-2 px-3 text-left font-medium">Pair</th>
              <th className="py-2 px-3 text-right font-medium">{"Spearman \u03C1"}</th>
              <th className="py-2 px-3 text-right font-medium">{"Kendall \u03C4"}</th>
            </tr>
          </thead>
          <tbody>
            {data.correlations.map((c, i) => {
              const pairKey = `${c.method1} vs ${c.method2}`;
              return (
                <tr key={i} className={`border-b border-border/20 ${METHOD_COLORS[pairKey] || ""}`}>
                  <td className="py-2 px-3 font-medium">{c.label}</td>
                  <td className="py-2 px-3 text-right font-mono font-semibold">{f(c.spearman_rho)}</td>
                  <td className="py-2 px-3 text-right font-mono">{f(c.kendall_tau)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Rank agreement at extremes */}
      {data.rank_agreement?.length > 0 && (
        <div className="mt-3 border border-border rounded-lg overflow-hidden">
          <div className="px-3 py-1.5 bg-secondary/10 border-b border-border">
            <span className="text-[10px] font-semibold text-muted-foreground">
              Top/Bottom K% Agreement Between Methods
            </span>
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1.5 px-3 text-left font-medium">Pair</th>
                <th className="py-1.5 px-3 text-right font-medium">K%</th>
                <th className="py-1.5 px-3 text-right font-medium bg-emerald-500/[0.06]">Top K%</th>
                <th className="py-1.5 px-3 text-right font-medium bg-rose-500/[0.06]">Bottom K%</th>
              </tr>
            </thead>
            <tbody>
              {data.rank_agreement.map((r, i) => {
                const label = data.correlations.find(
                  c => c.method1 === r.method1 && c.method2 === r.method2
                )?.label || `${r.method1} vs ${r.method2}`;
                const isFirst = i === 0 || data.rank_agreement[i - 1].method1 !== r.method1 ||
                  data.rank_agreement[i - 1].method2 !== r.method2;
                return (
                  <tr key={i} className={`border-b border-border/20 ${isFirst ? "border-t border-border/40" : ""}`}>
                    <td className="py-1 px-3 font-medium">{isFirst ? label : ""}</td>
                    <td className="py-1 px-3 text-right font-mono">{r.pct}%</td>
                    <td className="py-1 px-3 text-right font-mono bg-emerald-500/[0.06]">{r.top_overlap}%</td>
                    <td className="py-1 px-3 text-right font-mono bg-rose-500/[0.06]">{r.bottom_overlap}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[9px] text-muted-foreground/50 mt-2">
        Computed from {data.n_matches.toLocaleString()} standard-mode matches
        across {data.n_papers.toLocaleString()} papers in {data.compute_time_s}s.
        Win-Rate = Jeffreys-prior regularized; TrueSkill = incremental Bayesian rating (mu=25, sigma=8.33).
      </p>
    </div>
  );
}
