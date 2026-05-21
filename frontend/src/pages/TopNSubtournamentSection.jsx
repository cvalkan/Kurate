import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../components/ui/tooltip";

const API = process.env.REACT_APP_BACKEND_URL;

// Render a small ranked column for one signal.
function RankColumn({ rows, rankKey, scoreKey, title, sub, highlight, accent, onHover, hoveredId }) {
  const sorted = useMemo(() => [...rows].sort((a, b) => a[rankKey] - b[rankKey]), [rows, rankKey]);
  return (
    <div className="flex-1 min-w-0 border border-border rounded-lg bg-card overflow-hidden" data-testid={`column-${rankKey}`}>
      <div className={`px-3 py-2 border-b border-border ${accent}`}>
        <div className="font-medium text-sm flex items-center justify-between">
          <span>{title}</span>
        </div>
        <div className="text-[11px] text-muted-foreground">{sub}</div>
      </div>
      <ol className="divide-y divide-border/60">
        {sorted.map((r) => {
          const isHover = hoveredId === r.paper_id;
          return (
            <li
              key={r.paper_id}
              className={`px-2 py-1.5 text-xs flex gap-2 cursor-pointer transition-colors ${isHover ? "bg-accent/15" : "hover:bg-muted/60"}`}
              onMouseEnter={() => onHover(r.paper_id)}
              onMouseLeave={() => onHover(null)}
              data-testid={`row-${rankKey}-${r[rankKey]}`}
            >
              <span className="w-6 text-right shrink-0 text-muted-foreground tabular-nums">{r[rankKey]}</span>
              <a
                href={`/paper/${r.paper_id}`}
                className="flex-1 truncate text-foreground hover:text-accent"
                title={r.title}
              >
                {r.title}
              </a>
              <span className="w-12 text-right shrink-0 text-muted-foreground tabular-nums" title={highlight(r).title}>
                {highlight(r).value}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function CorrelationTriangle({ corr }) {
  const cells = [
    { key: "live_iso", label: "LIVE ↔ ISO", val: corr.spearman_r },
    { key: "live_si", label: "LIVE ↔ SI", val: corr.spearman_live_vs_si },
    { key: "iso_si",  label: "ISO ↔ SI",  val: corr.spearman_iso_vs_si },
  ];
  return (
    <div className="grid grid-cols-3 gap-3" data-testid="correlations-triangle">
      {cells.map((c) => (
        <div key={c.key} className="border border-border rounded-md p-3 bg-card">
          <div className="text-[11px] text-muted-foreground uppercase tracking-wider">{c.label}</div>
          <div className="text-2xl font-semibold tabular-nums mt-1">
            ρ = {c.val !== undefined && c.val !== null ? Number(c.val).toFixed(3) : "—"}
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">Spearman, within these 50 papers</div>
        </div>
      ))}
    </div>
  );
}

function TopKOverlapTable({ overlap }) {
  if (!overlap) return null;
  const ks = Object.keys(overlap).sort((a, b) => Number(a) - Number(b));
  return (
    <div className="border border-border rounded-lg overflow-hidden bg-card">
      <table className="w-full text-xs" data-testid="topk-overlap-table">
        <thead className="bg-muted/40">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">k</th>
            <th className="px-2 py-1.5 text-right font-medium">LIVE ∩ ISO</th>
            <th className="px-2 py-1.5 text-right font-medium">LIVE ∩ SI</th>
            <th className="px-2 py-1.5 text-right font-medium">ISO ∩ SI</th>
            <th className="px-2 py-1.5 text-right font-medium">All three</th>
          </tr>
        </thead>
        <tbody>
          {ks.map((k) => {
            const o = overlap[k];
            const cell = (n) => `${n}/${k}`;
            return (
              <tr key={k} className="border-t border-border/60">
                <td className="px-2 py-1 font-medium tabular-nums">top {k}</td>
                <td className="px-2 py-1 text-right tabular-nums">{cell(o.live_iso)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{cell(o.live_si)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{cell(o.iso_si)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{cell(o.all_three)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TopNSubtournamentSection({ category = "quant-ph", label = "Quantum Physics" }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hoveredId, setHoveredId] = useState(null);

  useEffect(() => {
    setLoading(true);
    axios.get(`${API}/api/topn-subtournament/${category}`, { params: { _t: Date.now() } })
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [category]);

  if (loading) return <div className="text-sm text-muted-foreground py-8 text-center">Loading sub-tournament results...</div>;
  if (!data || !data.rows?.length) return <div className="text-sm text-muted-foreground py-8 text-center">No sub-tournament data for <code>{category}</code>.</div>;

  const corr = data.correlations || {};
  return (
    <TooltipProvider>
      <div className="space-y-5" data-testid="topn-subtournament">
        {/* Header stats */}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span><b className="text-foreground">{data.top_n}</b> papers ({label})</span>
          <span><b className="text-foreground">{data.matches_completed?.toLocaleString()}</b> isolated matches</span>
          <span><b className="text-foreground">{data.target_matches_per_paper}</b> matches/paper target</span>
          <span><b className="text-foreground">{data.elapsed_minutes}</b> min run-time</span>
          <span>Models: {Object.entries(data.model_distribution || {}).map(([m, n]) => `${m} (${n})`).join(", ")}</span>
        </div>

        {/* Correlation cards */}
        <CorrelationTriangle corr={corr} />

        {/* Methodology */}
        <div className="border border-border rounded-lg p-4 bg-card text-xs leading-relaxed text-muted-foreground max-w-4xl space-y-2">
          <div><b className="text-foreground">Setup.</b> The 50 highest single-item-rated quant-ph papers were run through a fresh round-robin tournament with ≈20 matches per paper (500 unique pairs). The match prompt, content mode (<code>abstract + Claude Opus 4.6 thinking summary</code>), and judge round-robin (GPT-5.2 / Claude Opus 4.6 / Gemini 3.1 Pro) are identical to production.</div>
          <div><b className="text-foreground">ISO</b> = TrueSkill (μ − 3σ) computed from just these 500 isolated matches. <b className="text-foreground">LIVE</b> = the production within-top-50 ordering by the paper's existing <code>ts_score</code>, earned over the full quant-ph tournament (24-248 prior matches per paper). <b className="text-foreground">SI</b> = single-item rating averaged across three judges (the same field that selected the 50).</div>
          <div>Hover any row to highlight the same paper across all three columns. Click a title to open the paper.</div>
        </div>

        {/* The 3 columns */}
        <div className="flex gap-3 flex-wrap lg:flex-nowrap">
          <RankColumn
            rows={data.rows} rankKey="live_rank"
            title="LIVE  (production TrueSkill)"
            sub="Within-top-50 rank · score = ts_score"
            accent="bg-blue-500/5"
            hoveredId={hoveredId} onHover={setHoveredId}
            highlight={(r) => ({ value: r.live_ts_score, title: `ts_score · ${r.live_comparisons} prior comparisons` })}
          />
          <RankColumn
            rows={data.rows} rankKey="iso_rank"
            title="ISO  (isolated tournament)"
            sub="500 fresh matches · same Elo scale as LIVE"
            accent="bg-emerald-500/5"
            hoveredId={hoveredId} onHover={setHoveredId}
            highlight={(r) => ({ value: r.iso_elo, title: `Elo = round((μ−3σ)·10 + 1200) · μ=${r.iso_mu.toFixed(2)} σ=${r.iso_sigma.toFixed(2)} · ${r.iso_wins}-${r.iso_losses}` })}
          />
          <RankColumn
            rows={data.rows} rankKey="si_rank"
            title="SI  (single-item rating)"
            sub="One LLM call/paper · 1-10 scale"
            accent="bg-amber-500/5"
            hoveredId={hoveredId} onHover={setHoveredId}
            highlight={(r) => ({ value: r.ai_rating.toFixed(1), title: "single-item ai_rating (avg of 3 judges)" })}
          />
        </div>

        {/* Top-K overlap */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Top-K overlap (out of these 50)</h3>
          <TopKOverlapTable overlap={data.top_k_overlap} />
        </div>

        {/* Biggest disagreements */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Largest LIVE → ISO movers</h3>
          <div className="border border-border rounded-lg overflow-hidden bg-card">
            <table className="w-full text-xs" data-testid="movers-table">
              <thead className="bg-muted/40 text-[11px]">
                <tr>
                  <th className="px-2 py-1.5 text-right font-medium">live #</th>
                  <th className="px-2 py-1.5 text-right font-medium">iso #</th>
                  <th className="px-2 py-1.5 text-right font-medium">si #</th>
                  <th className="px-2 py-1.5 text-right font-medium">Δ live→iso</th>
                  <th className="px-2 py-1.5 text-right font-medium">SI</th>
                  <th className="px-2 py-1.5 text-right font-medium">iso W-L</th>
                  <th className="px-2 py-1.5 text-right font-medium">live cmps</th>
                  <th className="px-2 py-1.5 text-left font-medium">Paper</th>
                </tr>
              </thead>
              <tbody>
                {[...data.rows]
                  .sort((a, b) => Math.abs(b.delta_live_iso) - Math.abs(a.delta_live_iso))
                  .slice(0, 15)
                  .map((r) => {
                    const arrow = r.delta_live_iso > 0 ? "↑" : (r.delta_live_iso < 0 ? "↓" : "·");
                    const cls   = r.delta_live_iso > 0 ? "text-emerald-600 dark:text-emerald-400" : (r.delta_live_iso < 0 ? "text-rose-600 dark:text-rose-400" : "");
                    return (
                      <tr key={r.paper_id} className="border-t border-border/60 hover:bg-muted/30">
                        <td className="px-2 py-1 text-right tabular-nums">{r.live_rank}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.iso_rank}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.si_rank}</td>
                        <td className={`px-2 py-1 text-right tabular-nums font-medium ${cls}`}>{arrow}{Math.abs(r.delta_live_iso)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.ai_rating.toFixed(1)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.iso_wins}-{r.iso_losses}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r.live_comparisons}</td>
                        <td className="px-2 py-1 truncate max-w-md"><a href={`/paper/${r.paper_id}`} className="hover:text-accent" title={r.title}>{r.title}</a></td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}

export default TopNSubtournamentSection;
