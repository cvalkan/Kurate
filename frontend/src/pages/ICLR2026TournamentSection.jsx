import { useState, useEffect } from "react";
import axios from "axios";
import { Trophy, TrendingUp, Target, Loader2 } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const MODEL_LABELS = {
  "gpt-5.4": "GPT-5.4",
  "claude-opus-4-6": "Claude Opus 4.6",
  "gemini-3-pro-preview": "Gemini 3 Pro",
};

const MODEL_COLORS = {
  "gpt-5.4": "#2563eb",
  "claude-opus-4-6": "#ea580c",
  "gemini-3-pro-preview": "#f59e0b",
};

function ProgressBar({ pct, label }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span className="font-mono">{pct}%</span>
      </div>
      <div className="h-2 rounded-full bg-secondary/30 overflow-hidden">
        <div className="h-full rounded-full bg-accent transition-all duration-1000" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function ICLR2026TournamentSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/validation/iclr2026-tournament`)
      .then(r => setData(r.data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground animate-pulse p-4"><Loader2 className="h-4 w-4 animate-spin" /> Loading tournament data...</div>;
  if (error) return <div className="text-sm text-destructive p-4">Error: {error}</div>;
  if (!data || data.status === "no_data") return <div className="text-sm text-muted-foreground p-4">No match data yet. The pipeline is still starting.</div>;

  const { total_matches, total_papers, target_matches, progress_pct, correlation, model_stats,
          leaderboard_top, leaderboard_bottom, avg_matches_per_paper } = data;

  return (
    <div className="space-y-6" data-testid="iclr2026-tournament">
      {/* Overview stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Matches", value: total_matches.toLocaleString(), sub: `of ${target_matches.toLocaleString()}` },
          { label: "Papers", value: total_papers.toLocaleString(), sub: "unique" },
          { label: "Avg/Paper", value: avg_matches_per_paper, sub: "matches" },
          { label: "Models", value: model_stats.length, sub: "round-robin" },
        ].map(s => (
          <div key={s.label} className="p-3 rounded-lg border border-border bg-secondary/10">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{s.label}</div>
            <div className="text-lg font-mono font-semibold">{s.value}</div>
            <div className="text-[10px] text-muted-foreground">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Progress */}
      <ProgressBar pct={progress_pct} label={`${total_matches.toLocaleString()} / ${target_matches.toLocaleString()} matches completed`} />

      {/* Model distribution */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Target className="h-3 w-3" /> Model Distribution
          </h3>
        </div>
        <div className="p-3">
          <div className="flex gap-3">
            {model_stats.map(m => (
              <div key={m.model} className="flex-1 text-center">
                <div className="text-xs font-medium" style={{ color: MODEL_COLORS[m.model] || "#6b7280" }}>
                  {MODEL_LABELS[m.model] || m.model}
                </div>
                <div className="text-sm font-mono font-semibold">{m.matches.toLocaleString()}</div>
                <div className="text-[10px] text-muted-foreground">
                  {(m.matches / total_matches * 100).toFixed(1)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Correlation with human reviewers */}
      {correlation?.n_paired > 0 && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium flex items-center gap-1.5">
              <TrendingUp className="h-3 w-3" /> AI vs Human Reviewer Correlation
            </h3>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              Based on {correlation.n_paired.toLocaleString()} papers with both AI rankings and human reviewer scores.
              Correlations will improve as more matches complete.
            </p>
          </div>
          <div className="p-3">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1.5 pr-3 font-medium text-muted-foreground">Metric</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Spearman</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Pearson</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border/30">
                  <td className="py-1.5 pr-3 font-medium">TrueSkill vs Human Avg</td>
                  <td className="text-right py-1.5 px-2 font-mono font-semibold text-green-600">{correlation.trueskill_spearman}</td>
                  <td className="text-right py-1.5 px-2 font-mono">{correlation.trueskill_pearson}</td>
                </tr>
                <tr>
                  <td className="py-1.5 pr-3 font-medium">Win Rate vs Human Avg</td>
                  <td className="text-right py-1.5 px-2 font-mono">{correlation.winrate_spearman}</td>
                  <td className="text-right py-1.5 px-2" />
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Top 25 leaderboard */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Trophy className="h-3 w-3" /> Top 25 Papers (by TrueSkill)
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="iclr2026-leaderboard">
            <thead>
              <tr className="border-b border-border text-[10px]">
                <th className="text-left py-1.5 pl-3 pr-2 font-medium text-muted-foreground w-8">#</th>
                <th className="text-left py-1.5 pr-2 font-medium text-muted-foreground">Paper</th>
                <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">TrueSkill</th>
                <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">W/L</th>
                <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Win%</th>
                <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Human</th>
                <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">n</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard_top?.map(p => (
                <tr key={p.paper_id} className="border-b border-border/20 hover:bg-secondary/10">
                  <td className="py-1.5 pl-3 pr-2 font-mono text-muted-foreground">{p.rank}</td>
                  <td className="py-1.5 pr-2 max-w-xs truncate" title={p.title}>
                    <a href={`https://openreview.net/forum?id=${p.openreview_id}`}
                      target="_blank" rel="noopener noreferrer"
                      className="hover:underline text-foreground">
                      {p.title || p.openreview_id}
                    </a>
                    {p.label && <span className="ml-1.5 text-[9px] text-muted-foreground bg-secondary/30 px-1 py-0.5 rounded">{p.label}</span>}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono font-semibold">{p.trueskill_mu.toFixed(1)}</td>
                  <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{p.wins}/{p.losses}</td>
                  <td className="text-right py-1.5 px-2 font-mono">{p.win_rate}%</td>
                  <td className="text-right py-1.5 px-2 font-mono">
                    {p.human_avg != null ? (
                      <span className={p.human_avg >= 6 ? "text-green-600" : p.human_avg >= 4 ? "text-amber-600" : "text-red-600"}>
                        {p.human_avg}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{p.matches}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bottom 10 */}
      {leaderboard_bottom?.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Bottom 10 Papers</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-[10px]">
                  <th className="text-left py-1.5 pl-3 pr-2 font-medium text-muted-foreground w-8">#</th>
                  <th className="text-left py-1.5 pr-2 font-medium text-muted-foreground">Paper</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">TrueSkill</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">W/L</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Win%</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Human</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard_bottom.map(p => (
                  <tr key={p.paper_id} className="border-b border-border/20 hover:bg-secondary/10">
                    <td className="py-1.5 pl-3 pr-2 font-mono text-muted-foreground">{p.rank}</td>
                    <td className="py-1.5 pr-2 max-w-xs truncate" title={p.title}>
                      <a href={`https://openreview.net/forum?id=${p.openreview_id}`}
                        target="_blank" rel="noopener noreferrer"
                        className="hover:underline text-foreground">
                        {p.title || p.openreview_id}
                      </a>
                    </td>
                    <td className="text-right py-1.5 px-2 font-mono font-semibold">{p.trueskill_mu.toFixed(1)}</td>
                    <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{p.wins}/{p.losses}</td>
                    <td className="text-right py-1.5 px-2 font-mono">{p.win_rate}%</td>
                    <td className="text-right py-1.5 px-2 font-mono">
                      {p.human_avg != null ? (
                        <span className={p.human_avg >= 6 ? "text-green-600" : p.human_avg >= 4 ? "text-amber-600" : "text-red-600"}>
                          {p.human_avg}
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
