import { useState, useEffect } from "react";
import axios from "axios";
import { Trophy, TrendingUp, Target, Loader2, BarChart3, Layers } from "lucide-react";

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

function ProgressBar({ pct, current, target }) {
  return (
    <div className="space-y-1 mb-4">
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{current.toLocaleString()} / {target.toLocaleString()} matches</span>
        <span className="font-mono">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-secondary/30 overflow-hidden">
        <div className="h-full rounded-full bg-accent transition-all duration-1000" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ─── Ranking Correlation Tab ─── */
function RankingTab({ data }) {
  const { correlation, leaderboard_top, leaderboard_bottom } = data;

  return (
    <div className="space-y-6">
      {/* Correlation */}
      {correlation?.n_paired > 0 && (
        <div className="border border-border/50 rounded overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
            <h3 className="text-xs font-medium flex items-center gap-1.5">
              <TrendingUp className="h-3 w-3" /> AI vs Human Reviewer Correlation
            </h3>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {correlation.n_paired.toLocaleString()} papers with both AI Elo and human reviewer scores. Improves as matches accumulate.
            </p>
          </div>
          <div className="p-3">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1.5 pr-3 font-medium text-muted-foreground">Metric</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Spearman</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Pearson</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border/30">
                  <td className="py-1.5 pr-3 font-medium">Elo (TrueSkill) vs Human Avg</td>
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

      {/* Leaderboard */}
      <div className="border border-border/50 rounded overflow-hidden" data-testid="iclr2026-leaderboard">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Trophy className="h-3 w-3" /> Top 25 Papers (by Elo)
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1.5 pl-3 pr-2 font-medium text-muted-foreground w-8">#</th>
                <th className="text-left py-1.5 pr-2 font-medium text-muted-foreground">Paper</th>
                <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Elo</th>
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
                  <td className="py-1.5 pr-2 max-w-sm truncate" title={p.title}>
                    <a href={`https://openreview.net/forum?id=${p.openreview_id}`}
                      target="_blank" rel="noopener noreferrer"
                      className="hover:underline text-foreground">
                      {p.title || p.openreview_id}
                    </a>
                    {p.label && <span className="ml-1.5 text-[9px] text-muted-foreground bg-secondary/30 px-1 py-0.5 rounded">{p.label}</span>}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono font-semibold">{p.elo}</td>
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
        <div className="border border-border/50 rounded overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
            <h3 className="text-xs font-medium">Bottom 10 Papers</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1.5 pl-3 pr-2 font-medium text-muted-foreground w-8">#</th>
                  <th className="text-left py-1.5 pr-2 font-medium text-muted-foreground">Paper</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Elo</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">W/L</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Win%</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Human</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard_bottom.map(p => (
                  <tr key={p.paper_id} className="border-b border-border/20 hover:bg-secondary/10">
                    <td className="py-1.5 pl-3 pr-2 font-mono text-muted-foreground">{p.rank}</td>
                    <td className="py-1.5 pr-2 max-w-sm truncate" title={p.title}>
                      <a href={`https://openreview.net/forum?id=${p.openreview_id}`}
                        target="_blank" rel="noopener noreferrer"
                        className="hover:underline text-foreground">
                        {p.title || p.openreview_id}
                      </a>
                    </td>
                    <td className="text-right py-1.5 px-2 font-mono font-semibold">{p.elo}</td>
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

/* ─── Multi-Model Analysis Tab ─── */
function MultiModelTab({ data }) {
  const { model_stats, total_matches } = data;

  return (
    <div className="space-y-6">
      {/* Model distribution */}
      <div className="border border-border/50 rounded overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Target className="h-3 w-3" /> Model Distribution (Round-Robin)
          </h3>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-3 gap-4">
            {model_stats.map(m => (
              <div key={m.model} className="text-center">
                <div className="text-xs font-medium mb-1" style={{ color: MODEL_COLORS[m.model] || "#6b7280" }}>
                  {MODEL_LABELS[m.model] || m.model}
                </div>
                <div className="text-lg font-mono font-semibold">{m.matches.toLocaleString()}</div>
                <div className="text-[10px] text-muted-foreground">
                  {(m.matches / total_matches * 100).toFixed(1)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Per-model correlation placeholder */}
      {data.per_model_correlation?.length > 0 && (
        <div className="border border-border/50 rounded overflow-hidden">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
            <h3 className="text-xs font-medium">Per-Model Correlation with Human Scores</h3>
          </div>
          <div className="p-3">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1.5 pr-3 font-medium text-muted-foreground">Model</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Spearman</th>
                  <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">n papers</th>
                </tr>
              </thead>
              <tbody>
                {data.per_model_correlation.map(m => (
                  <tr key={m.model} className="border-b border-border/20">
                    <td className="py-1.5 pr-3 font-medium" style={{ color: MODEL_COLORS[m.model] || "#6b7280" }}>
                      {MODEL_LABELS[m.model] || m.model}
                    </td>
                    <td className="text-right py-1.5 px-2 font-mono font-semibold">{m.spearman.toFixed(4)}</td>
                    <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{m.n.toLocaleString()}</td>
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

/* ─── Convergence Tab ─── */
function ConvergenceTab({ data }) {
  return (
    <div className="border border-border/50 rounded overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
        <h3 className="text-xs font-medium flex items-center gap-1.5">
          <TrendingUp className="h-3 w-3" /> Tournament Progress
        </h3>
      </div>
      <div className="p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Matches", value: data.total_matches.toLocaleString(), sub: `of ${data.target_matches.toLocaleString()}` },
            { label: "Papers", value: data.total_papers.toLocaleString(), sub: "unique" },
            { label: "Avg/Paper", value: data.avg_matches_per_paper, sub: "matches" },
            { label: "Progress", value: `${data.progress_pct}%`, sub: "complete" },
          ].map(s => (
            <div key={s.label} className="text-center">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{s.label}</div>
              <div className="text-lg font-mono font-semibold">{s.value}</div>
              <div className="text-[10px] text-muted-foreground">{s.sub}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ─── Main Component ─── */
export default function ICLR2026TournamentSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("standard");

  useEffect(() => {
    axios.get(`${API}/api/validation/iclr2026-tournament`)
      .then(r => setData(r.data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground animate-pulse p-4"><Loader2 className="h-4 w-4 animate-spin" /> Loading tournament data...</div>;
  if (error) return <div className="text-sm text-destructive p-4">Error: {error}</div>;
  if (!data || data.status === "no_data") return <div className="text-sm text-muted-foreground p-4">No match data yet.</div>;

  const tabs = [
    { id: "standard", label: "Ranking Correlation", icon: BarChart3 },
    { id: "multimodel", label: "Multi-Model Analysis", icon: Layers },
    { id: "convergence", label: "Convergence", icon: TrendingUp },
  ];

  return (
    <div data-testid="iclr2026-tournament">
      {/* Progress bar */}
      <ProgressBar pct={data.progress_pct} current={data.total_matches} target={data.target_matches} />

      {/* Tabs */}
      <div className="flex items-center border-b border-border mb-4">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors -mb-px ${
              tab === t.id ? "border-accent text-accent" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
            data-testid={`tab-${t.id}`}
          >
            <t.icon className="h-3.5 w-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "standard" && <RankingTab data={data} />}
      {tab === "multimodel" && <MultiModelTab data={data} />}
      {tab === "convergence" && <ConvergenceTab data={data} />}
    </div>
  );
}
