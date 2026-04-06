import { Activity } from "lucide-react";

const METHOD_COLORS = {
  "win_rate vs trueskill": "bg-violet-500/10",
};

export function ScoringMethodSection({ category, scoringData, viewMode = "aggregate", osUpdatedAt }) {
  const data = scoringData;
  const isAvg = viewMode === "average";
  const rows = (isAvg && data?.avg_correlations?.length ? data.avg_correlations : data?.correlations) || [];
  const hasOs = rows.some(c => c.method1?.startsWith("openskill") || c.method2?.startsWith("openskill"));

  if (!data || !rows.length) return null;

  return (
    <div className="my-6" data-testid="scoring-method-section">
      <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
        <Activity className="h-4 w-4" /> Scoring Method Agreement
      </h3>
      <p className="text-xs text-muted-foreground mb-3">
        Spearman rank correlation between different scoring methods on the same set of papers ({data.n_papers?.toLocaleString()} papers).
        {hasOs && osUpdatedAt && <span className="ml-1 text-muted-foreground/60">OpenSkill data from {new Date(osUpdatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}.</span>}
      </p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm" data-testid="scoring-method-table">
          <thead>
            <tr className="bg-muted/30">
              <th className="text-left px-3 py-2 text-xs font-medium">Pair</th>
              <th className="text-right px-3 py-2 text-xs font-medium">Spearman ρ</th>
              <th className="text-right px-3 py-2 text-xs font-medium">Kendall τ</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c, i) => (
              <tr key={i} className={`border-t border-border/50 ${METHOD_COLORS[c.label?.toLowerCase()] || ""}`}>
                <td className="px-3 py-1.5 text-xs">{c.label?.replace("Regularized WR", "Reg WR").replace("Bradley-Terry", "BT").replace("Normalized Win-Rate", "Win Rate")}</td>
                <td className="px-3 py-1.5 text-xs text-right font-mono tabular-nums">{c.spearman_rho?.toFixed(4)}</td>
                <td className="px-3 py-1.5 text-xs text-right font-mono tabular-nums">{c.kendall_tau?.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-muted-foreground mt-2">
        TrueSkill uses 3-pass iterative EP on a Gaussian factor graph (μ=25, σ=8.33).
      </p>
    </div>
  );
}
