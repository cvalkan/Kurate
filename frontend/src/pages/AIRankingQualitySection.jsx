import { useState, useEffect } from "react";
import axios from "axios";
import { BarChart3 } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function AIRankingQualitySection() {
  return <AIRankingQualityPage apiUrl="/api/validation/ai-ranking-quality?gt_type=comp" testId="ai-ranking-quality" />;
}

export function AIRankingQualityUnfilteredSection() {
  return <AIRankingQualityPage apiUrl="/api/validation/ai-ranking-quality-unfiltered?gt_type=comp" testId="ai-ranking-quality-unfiltered" />;
}

function AIRankingQualityPage({ apiUrl, testId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}${apiUrl}`, { timeout: 60000 })
      .then(r => { if (r.data?.status === "ok") setData(r.data); else setError("No data"); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [apiUrl]);

  if (loading) return (
    <div className="space-y-3 animate-pulse">
      {[1, 2, 3].map(i => <div key={i} className="h-20 bg-secondary/30 rounded-lg" />)}
    </div>
  );
  if (error) return <div className="text-sm text-destructive">Error: {error}</div>;
  if (!data) return <div className="text-sm text-muted-foreground">No data available.</div>;

  const f = v => v?.toFixed(3) ?? "\u2014";
  const pb = data.pooled_bt;

  return (
    <div className="space-y-6" data-testid={testId}>
      <div className="text-[10px] text-muted-foreground leading-relaxed">
        AI BT ranking from <strong>all thinking-mode matches</strong> (1 judge per pair, random sample).
        Human ground truth from <strong>all expert pairs</strong> with {"\u2265"}2 non-tying opinions — not restricted to AI{"'"}s pair set.
        Each method uses its full available data independently.
      </div>

      <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] text-amber-900 leading-relaxed">
        <strong>Methodological note:</strong> The existing AI matches were generated under a pair-selection filter that
        excluded <strong>within-tier comparisons</strong> (e.g. Poster vs. Poster), so AI{"'"}s pair sample is biased toward
        easier comparisons. The human ground truth uses all expert pairs including within-tier. The filter has been
        removed for future validation runs; the {"\u03C1"} values below will improve as within-tier AI matches are added.
      </div>

      {/* Pooled summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "vs Aggregate", rho: pb.indiv?.spearman_rho, n: pb.indiv?.n_datasets },
          { label: "vs Majority Vote", rho: pb.maj?.spearman_rho, n: pb.maj?.n_datasets },
          { label: "vs Committee (Tier)", rho: pb.tier?.spearman_rho, n: pb.tier?.n_datasets },
          { label: "vs Avg Rating", rho: pb.avg_rating?.spearman_rho, n: pb.avg_rating?.n_datasets },
        ].map((m, i) => (
          <div key={i} className="border border-border rounded-lg p-3 bg-background text-center">
            <div className={`text-lg font-bold font-mono ${i === 0 ? "text-accent" : "text-foreground"}`}>
              {f(m.rho)}
            </div>
            <div className="text-[10px] text-muted-foreground leading-tight">{m.label}</div>
            {m.n && <div className="text-[9px] text-muted-foreground/60 mt-0.5">{m.n} datasets</div>}
          </div>
        ))}
      </div>

      {/* Per-dataset table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
          <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Per-Dataset AI Ranking Correlation</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1.5 px-2 text-left font-medium">Dataset</th>
                <th className="py-1.5 px-2 text-right font-medium bg-sky-500/[0.06]">vs Aggregate</th>
                <th className="py-1.5 px-2 text-right font-medium bg-amber-500/[0.06]">vs Majority</th>
                <th className="py-1.5 px-2 text-right font-medium bg-rose-500/[0.06]">vs Committee</th>
                <th className="py-1.5 px-2 text-right font-medium">vs Avg Rating</th>
                <th className="py-1.5 px-2 text-right font-medium text-foreground/50">AI pairs</th>
                <th className="py-1.5 px-2 text-right font-medium text-foreground/50">Expert pairs</th>
                <th className="py-1.5 px-2 text-right font-medium text-foreground/50">Overlap</th>
              </tr>
            </thead>
            <tbody>
              {data.per_dataset.map(d => {
                const bt = d.bt || {};
                const overlapPct = d.n_expert_pairs > 0 ? Math.round(100 * d.pair_overlap / d.n_expert_pairs) : 0;
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1.5 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className="py-1.5 px-2 text-right font-mono font-semibold bg-sky-500/[0.06]">{f(bt.indiv?.spearman_rho)}</td>
                    <td className="py-1.5 px-2 text-right font-mono bg-amber-500/[0.06]">{f(bt.maj?.spearman_rho)}</td>
                    <td className="py-1.5 px-2 text-right font-mono bg-rose-500/[0.06]">{f(bt.tier?.spearman_rho)}</td>
                    <td className="py-1.5 px-2 text-right font-mono">{typeof bt.avg_rating === "number" ? bt.avg_rating.toFixed(3) : f(bt.avg_rating?.spearman_rho)}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-foreground/50">{d.n_ai_pairs}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-foreground/50">{d.n_expert_pairs}</td>
                    <td className="py-1.5 px-2 text-right font-mono text-foreground/50">{overlapPct}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-1.5">
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>vs Aggregate</strong>: AI BT ranking correlated with human BT where each expert vote is a separate match.{" "}
            <strong>vs Majority</strong>: AI BT vs human majority-vote BT (one consensus per pair).{" "}
            <strong>vs Committee</strong>: AI BT vs actual program committee tier decisions (ICLR only).{" "}
            <strong>vs Avg Rating</strong>: AI BT vs simple average of expert scores.
          </p>
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Overlap</strong>: fraction of expert pairs that AI also evaluated. Lower overlap = more independent comparison.
            All pooled {"\u03C1"} values are equal-weighted across datasets.
          </p>
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Key difference from Human vs AI Benchmark</strong>: that page uses <em>controlled pairs</em> (same pair set
            for both AI and human) to enable fair head-to-head comparison. This page uses each method{"'"}s <em>full data</em> to
            measure absolute ranking quality without sampling assumptions.
          </p>
        </div>
      </div>
    </div>
  );
}
