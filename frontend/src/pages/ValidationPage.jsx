import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { FlaskConical, Download, Play, RotateCcw, TrendingUp, TrendingDown, Minus, AlertCircle, Users, Zap } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

function CorrelationBadge({ value, label }) {
  const abs = Math.abs(value);
  let color = "text-muted-foreground";
  let bg = "bg-secondary/50";
  if (abs >= 0.7) { color = "text-green-700"; bg = "bg-green-50"; }
  else if (abs >= 0.4) { color = "text-amber-700"; bg = "bg-amber-50"; }
  else if (abs >= 0.2) { color = "text-orange-700"; bg = "bg-orange-50"; }
  return (
    <div className={`p-4 rounded-lg border border-border ${bg}`} data-testid={`correlation-${label.toLowerCase().replace(/[^a-z]/g, '-')}`}>
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className={`text-2xl font-semibold font-mono ${color}`}>
        {value >= 0 ? "+" : ""}{value.toFixed(3)}
      </div>
    </div>
  );
}

function RankDelta({ delta }) {
  if (delta === 0) return <span className="text-muted-foreground flex items-center gap-0.5"><Minus className="h-3 w-3" /> 0</span>;
  if (delta > 0) return <span className="text-red-600 flex items-center gap-0.5"><TrendingDown className="h-3 w-3" /> +{delta.toFixed(0)}</span>;
  return <span className="text-green-600 flex items-center gap-0.5"><TrendingUp className="h-3 w-3" /> {delta.toFixed(0)}</span>;
}

function AgreementGauge({ rate, label, subtitle }) {
  const color = rate >= 65 ? "text-green-600" : rate >= 55 ? "text-amber-600" : "text-muted-foreground";
  return (
    <div className="p-4 rounded-lg border border-border bg-secondary/50" data-testid={`gauge-${label?.toLowerCase().replace(/[^a-z]/g, '-') || 'agreement'}`}>
      <div className="text-xs text-muted-foreground mb-1">{label || "Pairwise Agreement"}</div>
      <div className={`text-2xl font-semibold font-mono ${color}`}>{rate}%</div>
      <div className="text-[10px] text-muted-foreground">{subtitle || "50% = random"}</div>
    </div>
  );
}

// ─── Ranking Table ───────────────────────────────────────────────────────────

function RankingTable({ data, mode }) {
  const isPairwise = mode === "pairwise";
  return (
    <div className="border border-border rounded-lg overflow-hidden" data-testid={`ranking-table-${mode}`}>
      <div className="px-4 py-3 bg-secondary/30 border-b border-border">
        <h3 className="text-sm font-medium">
          {isPairwise ? "Human (Pairwise) vs AI Ranking" : "Human (Avg Rating) vs AI Ranking"}
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          {isPairwise
            ? "Human ranking from Bradley-Terry on expert-derived pairwise comparisons. Delta = AI rank − Human rank."
            : "Sorted by H1 avg rating. Delta = AI rank − Human rank (negative = AI ranked higher)."}
        </p>
      </div>
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b border-border text-xs">
              <th className="text-left px-3 py-2 font-medium">Paper</th>
              {!isPairwise && <th className="text-right px-2 py-2 font-medium">H1 Rating</th>}
              <th className="text-right px-2 py-2 font-medium">Human Rank</th>
              {isPairwise && <th className="text-right px-2 py-2 font-medium">H Score</th>}
              {isPairwise && <th className="text-right px-2 py-2 font-medium">H Win%</th>}
              {isPairwise && <th className="text-right px-2 py-2 font-medium">H Matches</th>}
              <th className="text-right px-2 py-2 font-medium">AI Rank</th>
              <th className="text-right px-2 py-2 font-medium">AI Score</th>
              <th className="text-right px-2 py-2 font-medium">AI Win%</th>
              <th className="text-right px-2 py-2 font-medium">AI Matches</th>
              <th className="text-right px-3 py-2 font-medium">Delta</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.id} className="border-b border-border/30 hover:bg-secondary/10">
                <td className="px-3 py-2 max-w-[250px]">
                  <div className="truncate text-xs font-medium" title={row.title}>{row.title}</div>
                  <div className="text-[10px] text-muted-foreground">{row.journal}</div>
                </td>
                {!isPairwise && (
                  <td className="text-right px-2 py-2">
                    <span className={`font-mono text-xs font-medium ${
                      row.h1_avg_rating >= 2.5 ? "text-green-600" :
                      row.h1_avg_rating >= 1.5 ? "text-amber-600" : "text-muted-foreground"
                    }`}>{row.h1_avg_rating.toFixed(1)}</span>
                    <span className="text-[10px] text-muted-foreground ml-0.5">({row.h1_rating_count})</span>
                  </td>
                )}
                <td className="text-right px-2 py-2 font-mono text-xs">{typeof row.human_rank === 'number' && row.human_rank % 1 !== 0 ? row.human_rank.toFixed(1) : row.human_rank}</td>
                {isPairwise && <td className="text-right px-2 py-2 font-mono text-xs text-muted-foreground">{row.human_score}</td>}
                {isPairwise && <td className="text-right px-2 py-2 font-mono text-xs text-muted-foreground">{row.human_win_rate}%</td>}
                {isPairwise && <td className="text-right px-2 py-2 font-mono text-xs text-muted-foreground">{row.human_matches}</td>}
                <td className="text-right px-2 py-2 font-mono text-xs">{row.ai_rank}</td>
                <td className="text-right px-2 py-2 font-mono text-xs text-muted-foreground">{row.ai_score}</td>
                <td className="text-right px-2 py-2 font-mono text-xs text-muted-foreground">{row.ai_win_rate}%</td>
                <td className="text-right px-2 py-2 font-mono text-xs text-muted-foreground">{row.ai_matches}</td>
                <td className="text-right px-3 py-2 text-xs"><RankDelta delta={row.rank_delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Experiment Section ──────────────────────────────────────────────────────

function ExperimentSection({ title, icon, description, correlation, pairwiseAgreement, interpretation, stats, children }) {
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 bg-secondary/20 border-b border-border">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-heading text-base font-medium">{title}</h2>
        </div>
        <p className="text-xs text-muted-foreground mt-1">{description}</p>
      </div>
      <div className="p-4 space-y-4">
        {/* Correlation badges */}
        {correlation && (
          <div className="space-y-3">
            {pairwiseAgreement && (
              <>
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Direct Match Outcomes</div>
                <div className="grid grid-cols-2 gap-3">
                  <AgreementGauge rate={pairwiseAgreement.agreement_rate} label="Match Agreement" subtitle={`${pairwiseAgreement.agreements}/${pairwiseAgreement.overlapping_pairs} pairs · 50% = random`} />
                  <AgreementGauge rate={pairwiseAgreement.ranking_concordance} label="Ranking Concordance" subtitle={`${pairwiseAgreement.concordant_pairs}/${pairwiseAgreement.concordant_pairs + pairwiseAgreement.discordant_pairs} pairs · BT rank order`} />
                </div>
              </>
            )}
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Global Ranking Correlation</div>
            <div className="grid grid-cols-3 gap-3">
              <CorrelationBadge value={correlation.spearman_rho} label="Spearman ρ" />
              <CorrelationBadge value={correlation.kendall_tau} label="Kendall τ" />
              <CorrelationBadge value={correlation.pearson_r} label="Pearson r" />
            </div>
          </div>
        )}
        {/* Interpretation */}
        {interpretation && (
          <div className="p-3 border border-border rounded-lg bg-background text-sm text-muted-foreground">
            {interpretation}
          </div>
        )}
        {/* Stats line */}
        {stats && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            {stats.map((s, i) => <span key={i}>{s}</span>)}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function ValidationPage() {
  const [status, setStatus] = useState(null);
  const [avgResults, setAvgResults] = useState(null);
  const [pairResults, setPairResults] = useState(null);
  const [loading, setLoading] = useState({ import: false, tournament: false, reset: false });
  const [matchCount, setMatchCount] = useState(100);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchStatus = useCallback(async () => {
    try { setStatus((await axios.get(`${API}/api/validation/status`)).data); } catch (e) { console.error(e); }
  }, []);

  const fetchResults = useCallback(async () => {
    try {
      const [avg, pair] = await Promise.all([
        axios.get(`${API}/api/validation/results`),
        axios.get(`${API}/api/validation/pairwise-results`),
      ]);
      if (avg.data.status === "ok") setAvgResults(avg.data);
      if (pair.data.status === "ok") setPairResults(pair.data);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchStatus(); fetchResults(); }, [fetchStatus, fetchResults]);

  useEffect(() => {
    if (!status?.tournament_running) return;
    const interval = setInterval(() => { fetchStatus(); fetchResults(); }, 5000);
    return () => clearInterval(interval);
  }, [status?.tournament_running, fetchStatus, fetchResults]);

  const importPapers = async () => {
    setLoading(l => ({ ...l, import: true }));
    try { await axios.post(`${API}/api/validation/import`, {}, { headers: getAdminHeaders() }); fetchStatus(); }
    catch (e) { console.error(e); }
    finally { setLoading(l => ({ ...l, import: false })); }
  };

  const runTournament = async () => {
    setLoading(l => ({ ...l, tournament: true }));
    try {
      await axios.post(`${API}/api/validation/run-tournament`, { num_matches: matchCount, parallel: 3 }, { headers: getAdminHeaders() });
      fetchStatus();
    } catch (e) { console.error(e); }
    finally { setLoading(l => ({ ...l, tournament: false })); }
  };

  const resetAll = async () => {
    if (!window.confirm("Delete all validation papers and matches?")) return;
    setLoading(l => ({ ...l, reset: true }));
    try {
      await axios.post(`${API}/api/validation/reset`, {}, { headers: getAdminHeaders() });
      setAvgResults(null); setPairResults(null); fetchStatus();
    } catch (e) { console.error(e); }
    finally { setLoading(l => ({ ...l, reset: false })); }
  };

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-2">
          <FlaskConical className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="validation-title">Human vs AI Validation</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-2xl">
          Does PaperSumo's AI tournament agree with human experts? We import {status?.papers_imported || 47} biomedical
          papers rated by specialists on H1 Connect and compare AI pairwise rankings against human judgments.
        </p>
      </div>

      {/* Status cards */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div className="p-3 border border-border rounded-lg" data-testid="stat-papers">
            <div className="text-xs text-muted-foreground">H1 Papers</div>
            <div className="text-xl font-semibold">{status.papers_imported}</div>
            <div className="text-[10px] text-muted-foreground">{"\u2265"}{status.min_expert_ratings} expert ratings each</div>
          </div>
          <div className="p-3 border border-border rounded-lg" data-testid="stat-matches">
            <div className="text-xs text-muted-foreground">AI Matches</div>
            <div className="text-xl font-semibold">{status.matches_completed}</div>
            <div className="text-[10px] text-muted-foreground">{status.coverage_pct}% of {status.total_possible_pairs} pairs</div>
          </div>
          <div className="p-3 border border-border rounded-lg" data-testid="stat-avg-matches">
            <div className="text-xs text-muted-foreground">Avg Matches/Paper</div>
            <div className="text-xl font-semibold">{status.avg_matches_per_paper}</div>
            <div className="text-[10px] text-muted-foreground">min {status.min_matches_per_paper} / max {status.max_matches_per_paper}</div>
          </div>
          <div className="p-3 border border-border rounded-lg" data-testid="stat-tournament">
            <div className="text-xs text-muted-foreground">Tournament</div>
            <div className="text-xl font-semibold">
              {status.tournament_running ? <span className="text-accent">Running</span>
                : status.matches_completed > 0 ? "Complete" : "Not started"}
            </div>
            {status.tournament_running && (
              <div className="text-[10px] text-muted-foreground">
                {status.tournament_progress.completed_matches}/{status.tournament_progress.total_matches}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 mb-6 bg-secondary/10" data-testid="admin-controls">
          <h3 className="text-sm font-medium mb-3">Controls</h3>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="outline" onClick={importPapers} disabled={loading.import} className="gap-1.5" data-testid="btn-import">
              <Download className="h-3.5 w-3.5" /> {loading.import ? "Importing..." : "Import H1 Papers"}
            </Button>
            <div className="flex items-center gap-1.5">
              <input type="number" min={10} max={500} value={matchCount}
                onChange={e => setMatchCount(Math.min(500, Math.max(10, Number(e.target.value))))}
                className="w-16 h-8 text-xs border border-border rounded px-2 bg-background" data-testid="input-match-count" />
              <Button size="sm" onClick={runTournament}
                disabled={loading.tournament || status?.tournament_running || !status?.papers_imported}
                className="gap-1.5" data-testid="btn-run-tournament">
                <Play className="h-3.5 w-3.5" /> {status?.tournament_running ? "Running..." : "Run Tournament"}
              </Button>
            </div>
            <Button size="sm" variant="ghost" onClick={resetAll} disabled={loading.reset || status?.tournament_running}
              className="gap-1.5 text-red-600 hover:text-red-700 hover:bg-red-50 ml-auto" data-testid="btn-reset">
              <RotateCcw className="h-3.5 w-3.5" /> Reset
            </Button>
          </div>
        </div>
      )}

      {/* Tournament progress */}
      {status?.tournament_running && (
        <div className="border border-accent/30 rounded-lg p-4 mb-6 bg-accent/5">
          <div className="flex items-center gap-2 mb-2">
            <div className="h-4 w-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium">Tournament in progress</span>
          </div>
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div className="h-full bg-accent transition-all duration-500"
              style={{ width: `${(status.tournament_progress.completed_matches / Math.max(status.tournament_progress.total_matches, 1)) * 100}%` }} />
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {status.tournament_progress.completed_matches} / {status.tournament_progress.total_matches} matches
          </div>
        </div>
      )}

      {/* No data */}
      {!avgResults && !pairResults && !status?.tournament_running && (
        <div className="border border-border rounded-lg p-8 text-center mb-6">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            {!status?.papers_imported ? "No papers imported yet." : "No tournament results yet. Run the tournament."}
          </p>
        </div>
      )}

      {/* ── Experiment 2: Pairwise-Derived (primary) ── */}
      {pairResults && (
        <div className="mb-6">
          <ExperimentSection
            title="Experiment: Pairwise-Derived Human Rankings"
            icon={<Users className="h-4 w-4 text-accent" />}
            description={`Extracts head-to-head preferences from ${pairResults.experts_contributing} experts who rated multiple papers. If Expert A rated Paper X higher than Paper Y, that's one human comparison. Both human and AI rankings use Bradley-Terry on pairwise data.`}
            correlation={pairResults.correlation}
            pairwiseAgreement={pairResults.pairwise_agreement}
            interpretation={pairResults.interpretation}
            stats={[
              `${pairResults.papers_analyzed} papers`,
              `${pairResults.human_matches_derived} human pairs (${pairResults.human_matches_ties_excluded} ties excluded)`,
              `${pairResults.ai_matches} AI matches`,
              `${pairResults.pairwise_agreement.overlapping_pairs} directly overlapping pairs`,
            ]}
          >
            <RankingTable data={pairResults.comparison} mode="pairwise" />
          </ExperimentSection>
        </div>
      )}

      {/* ── Experiment 1: Avg Rating (secondary) ── */}
      {avgResults && (
        <div className="mb-6">
          <ExperimentSection
            title="Experiment: Average H1 Rating"
            icon={<Zap className="h-4 w-4 text-muted-foreground" />}
            description="Ranks papers by their average H1 Connect rating (Good=1, Very Good=2, Exceptional=3). Limited by the narrow 3-point scale — many ties make correlation unreliable."
            correlation={avgResults.correlation}
            interpretation={avgResults.interpretation}
            stats={[
              `${avgResults.papers_analyzed} papers`,
              `${avgResults.total_matches} AI matches`,
              ...Object.entries(avgResults.model_usage || {}).map(([m, c]) => `${m.split("/")[1]?.slice(0, 12)}: ${c}`),
            ]}
          >
            <RankingTable data={avgResults.comparison} mode="avg" />
          </ExperimentSection>
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1.5">
          <li><strong>Pairwise experiment (primary):</strong> For each expert who rated 2+ papers, we derive implicit head-to-head comparisons from rating differences. These form human pairwise matches, ranked via Bradley-Terry — the same algorithm used for AI. This is an apples-to-apples comparison.</li>
          <li><strong>Average rating experiment:</strong> Papers ranked by mean H1 rating. Limited because the 3-point scale produces many ties and a narrow range (1.0–2.2 for papers with 5+ ratings).</li>
          <li><strong>AI tournament:</strong> Abstract-only pairwise comparisons using round-robin GPT-5.2, Claude Opus 4.5, Gemini 3 Pro. Ranked via Bradley-Terry + Elo.</li>
          <li><strong>Pairwise agreement:</strong> For paper pairs compared by both humans and AI, the percentage where both pick the same winner. 50% = random chance.</li>
          <li><strong>Spearman ρ / Kendall τ:</strong> Rank correlation (−1 to +1). Values near +1 = AI and human rankings agree.</li>
        </ul>
      </div>
    </div>
  );
}
