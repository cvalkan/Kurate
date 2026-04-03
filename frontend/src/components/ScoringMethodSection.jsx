import { Activity } from "lucide-react";

const METHOD_COLORS = {
  "win_rate vs trueskill": "bg-violet-500/10",
};

export function ScoringMethodSection({ category, scoringData }) {
  const data = scoringData;

  if (!data || !data.correlations?.length) return null;

  return (
    <div className="my-6" data-testid="scoring-method-section">
      <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
        <Activity className="h-4 w-4" /> Scoring Method Agreement
      </h3>
      <p className="text-xs text-muted-foreground mb-3">
        Spearman rank correlation between different scoring methods on the same set of papers ({data.n_papers?.toLocaleString()} papers).
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
            {data.correlations.map((c, i) => (
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
