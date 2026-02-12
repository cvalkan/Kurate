import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { FlaskConical, Download, Play, RotateCcw, TrendingUp, TrendingDown, Minus, AlertCircle, Users, ChevronDown } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
function getAdminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

// ─── Shared Components ───────────────────────────────────────────────────────

function CorrelationBadge({ value, label }) {
  const abs = Math.abs(value);
  const color = abs >= 0.7 ? "text-green-700" : abs >= 0.4 ? "text-amber-700" : abs >= 0.2 ? "text-orange-700" : "text-muted-foreground";
  const bg = abs >= 0.7 ? "bg-green-50" : abs >= 0.4 ? "bg-amber-50" : abs >= 0.2 ? "bg-orange-50" : "bg-secondary/50";
  return (
    <div className={`p-3 rounded-lg border border-border ${bg}`}>
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{value >= 0 ? "+" : ""}{value.toFixed(3)}</div>
    </div>
  );
}

function RankDelta({ delta }) {
  if (delta === 0) return <span className="text-muted-foreground flex items-center gap-0.5"><Minus className="h-3 w-3" /> 0</span>;
  if (delta > 0) return <span className="text-red-600 flex items-center gap-0.5"><TrendingDown className="h-3 w-3" /> +{delta.toFixed(0)}</span>;
  return <span className="text-green-600 flex items-center gap-0.5"><TrendingUp className="h-3 w-3" /> {delta.toFixed(0)}</span>;
}

// ─── Dataset Panel ───────────────────────────────────────────────────────────

function DatasetPanel({ ds, isAdmin }) {
  const [status, setStatus] = useState(null);
  const [pairwise, setPairwise] = useState(null);
  const [irt, setIrt] = useState(null);
  const [agreement, setAgreement] = useState(null);
  const [expanded, setExpanded] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [s, p, i, a] = await Promise.all([
        axios.get(`${API}/api/validation/status`, { params: { dataset_id: ds.dataset_id } }),
        axios.get(`${API}/api/validation/pairwise-results`, { params: { dataset_id: ds.dataset_id } }),
        axios.get(`${API}/api/validation/irt-results`, { params: { dataset_id: ds.dataset_id } }),
        axios.get(`${API}/api/validation/agreement-analysis`, { params: { dataset_id: ds.dataset_id } }),
      ]);
      setStatus(s.data);
      if (p.data.status === "ok") setPairwise(p.data);
      if (i.data.status === "ok") setIrt(i.data);
      if (a.data.status === "ok") setAgreement(a.data);
    } catch (e) { console.error(e); }
  }, [ds.dataset_id]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    if (!status?.tournament_running) return;
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [status?.tournament_running, fetchAll]);

  const runTournament = async () => {
    try {
      await axios.post(`${API}/api/validation/run-tournament`,
        { dataset_id: ds.dataset_id, num_matches: 500, parallel: 5 },
        { headers: getAdminHeaders() });
      fetchAll();
    } catch (e) { console.error(e); }
  };

  return (
    <div className="border border-border rounded-lg overflow-hidden" data-testid={`dataset-${ds.dataset_id}`}>
      {/* Header — always visible */}
      <button className="w-full px-4 py-3 bg-secondary/20 border-b border-border flex items-center justify-between hover:bg-secondary/30 transition-colors" onClick={() => setExpanded(!expanded)}>
        <div className="text-left">
          <h2 className="font-heading text-base font-medium">{ds.name}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">{ds.description || ds.source}</p>
        </div>
        <div className="flex items-center gap-4">
          {/* Summary metrics inline */}
          {pairwise && (
            <div className="hidden md:flex items-center gap-3 text-xs">
              <span className="font-mono">ρ<sub>pw</sub> = <strong className={pairwise.correlation.spearman_rho >= 0.4 ? "text-green-600" : "text-muted-foreground"}>{pairwise.correlation.spearman_rho.toFixed(2)}</strong></span>
              <span className="font-mono">ρ<sub>irt</sub> = <strong className={irt?.correlation?.irt_score_vs_ai?.spearman_rho >= 0.4 ? "text-green-600" : "text-muted-foreground"}>{irt?.correlation?.irt_score_vs_ai?.spearman_rho?.toFixed(2) || "—"}</strong></span>
              {agreement && <span>AI-Expert: <strong className={agreement.ai_expert.rate > 60 ? "text-green-600" : "text-amber-600"}>{agreement.ai_expert.rate}%</strong></span>}
            </div>
          )}
          <span className="text-xs text-muted-foreground">{ds.papers} papers · {ds.matches} matches</span>
          <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`} />
        </div>
      </button>

      {expanded && (
        <div className="p-4 space-y-5">
          {/* Status row */}
          {status && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-center">
              {[
                ["Papers", status.papers_imported, `${status.papers_with_full_text} full text`],
                ["AI Matches", status.matches_completed, `${status.coverage_pct}% coverage`],
                ["Extraction", status.matches_with_extraction, `${status.matches_abstract_only} abstract-only`],
                ["Avg/Paper", status.avg_matches_per_paper, `${status.min_matches_per_paper}–${status.max_matches_per_paper}`],
                ["Tournament", status.tournament_running ? "Running" : "Complete", status.tournament_running ? `${status.tournament_progress.completed_matches}/${status.tournament_progress.total_matches}` : ""],
              ].map(([label, val, sub], i) => (
                <div key={i} className="p-2 border border-border/50 rounded text-xs">
                  <div className="text-muted-foreground">{label}</div>
                  <div className={`font-semibold ${val === "Running" ? "text-accent" : ""}`}>{val}</div>
                  {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Progress bar */}
          {status?.tournament_running && (
            <div className="border border-accent/30 rounded p-3 bg-accent/5">
              <div className="flex items-center gap-2 mb-1">
                <div className="h-3 w-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                <span className="text-xs font-medium">Tournament in progress</span>
              </div>
              <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                <div className="h-full bg-accent transition-all" style={{ width: `${(status.tournament_progress.completed_matches / Math.max(status.tournament_progress.total_matches, 1)) * 100}%` }} />
              </div>
            </div>
          )}

          {isAdmin && !status?.tournament_running && status?.matches_completed === 0 && (
            <Button size="sm" onClick={runTournament} className="gap-1.5">
              <Play className="h-3.5 w-3.5" /> Run Tournament (500 matches)
            </Button>
          )}

          {/* Agreement */}
          {agreement && (
            <div className="grid grid-cols-3 gap-2">
              {[
                ["Expert-Expert", agreement.expert_expert.rate, `${agreement.expert_expert.agree}/${agreement.expert_expert.total}`, agreement.expert_expert.rate >= 70 ? "text-green-600" : "text-red-600"],
                ["AI-Expert", agreement.ai_expert.rate, `${agreement.ai_expert.agree}/${agreement.ai_expert.total}`, agreement.ai_expert.rate > agreement.expert_expert.rate ? "text-green-600" : "text-amber-600"],
                ["AI-Majority", agreement.ai_majority.rate, `${agreement.ai_majority.agree}/${agreement.ai_majority.total}`, "text-amber-600"],
              ].map(([label, rate, sub, color], i) => (
                <div key={i} className="p-3 border border-border rounded text-center">
                  <div className="text-[10px] text-muted-foreground">{label}</div>
                  <div className={`text-xl font-semibold font-mono ${color}`}>{rate}%</div>
                  <div className="text-[10px] text-muted-foreground">{sub} pairs</div>
                </div>
              ))}
            </div>
          )}

          {/* Two experiments side by side */}
          {(pairwise || irt) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Pairwise BT */}
              {pairwise && (
                <div className="border border-border rounded-lg overflow-hidden">
                  <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                    <h3 className="text-xs font-medium flex items-center gap-1.5">
                      <Users className="h-3 w-3" /> Pairwise BT (no severity correction)
                    </h3>
                  </div>
                  <div className="p-3 space-y-2">
                    <div className="grid grid-cols-3 gap-2">
                      <CorrelationBadge value={pairwise.correlation.spearman_rho} label="Spearman ρ" />
                      <CorrelationBadge value={pairwise.correlation.kendall_tau} label="Kendall τ" />
                      <CorrelationBadge value={pairwise.correlation.pearson_r} label="Pearson r" />
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {pairwise.papers_analyzed} papers · {pairwise.human_matches_derived} human pairs · {pairwise.ai_matches} AI matches
                    </div>
                    <RankingTable rows={pairwise.comparison} mode="pairwise" />
                  </div>
                </div>
              )}

              {/* IRT Direct Score */}
              {irt && (
                <div className="border border-border rounded-lg overflow-hidden">
                  <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                    <h3 className="text-xs font-medium flex items-center gap-1.5">
                      <FlaskConical className="h-3 w-3" /> IRT Score (severity-adjusted)
                    </h3>
                  </div>
                  <div className="p-3 space-y-2">
                    <div className="grid grid-cols-3 gap-2">
                      <CorrelationBadge value={irt.correlation.irt_score_vs_ai.spearman_rho} label="Spearman ρ" />
                      <CorrelationBadge value={irt.correlation.irt_score_vs_ai.kendall_tau} label="Kendall τ" />
                      <CorrelationBadge value={irt.correlation.irt_score_vs_ai.pearson_r} label="Pearson r" />
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                      <span>{irt.improvement.distinct_scores_raw}→{irt.improvement.distinct_scores_irt} distinct scores</span>
                      <span>·</span>
                      <span>Δρ = {irt.improvement.delta >= 0 ? "+" : ""}{irt.improvement.delta.toFixed(3)}</span>
                    </div>
                    <RankingTable rows={irt.comparison} mode="irt" />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RankingTable({ rows, mode }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? rows : rows.slice(0, 10);
  const isPw = mode === "pairwise";

  return (
    <div className="border border-border/50 rounded overflow-hidden">
      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b border-border text-[10px]">
              <th className="text-left px-2 py-1.5 font-medium">Paper</th>
              <th className="text-right px-1.5 py-1.5 font-medium">{isPw ? "H Rank" : "IRT"}</th>
              <th className="text-right px-1.5 py-1.5 font-medium">AI</th>
              <th className="text-right px-1.5 py-1.5 font-medium">Δ</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(r => (
              <tr key={r.id} className="border-b border-border/20 hover:bg-secondary/10">
                <td className="px-2 py-1 max-w-[180px] truncate" title={r.title}>{r.title}</td>
                <td className="text-right px-1.5 py-1 font-mono">{isPw ? r.human_rank : r.irt_rank}</td>
                <td className="text-right px-1.5 py-1 font-mono">{r.ai_rank}</td>
                <td className="text-right px-1.5 py-1"><RankDelta delta={r.rank_delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 10 && (
        <button onClick={() => setShowAll(!showAll)} className="w-full py-1.5 text-[10px] text-muted-foreground hover:bg-secondary/20 border-t border-border/50">
          {showAll ? "Show less" : `Show all ${rows.length} papers`}
        </button>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function ValidationPage() {
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState({ import: false });
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchDatasets = useCallback(async () => {
    try { setDatasets((await axios.get(`${API}/api/validation/datasets`)).data.datasets || []); }
    catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchDatasets(); const i = setInterval(fetchDatasets, 15000); return () => clearInterval(i); }, [fetchDatasets]);

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-6xl py-6 md:py-10">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <FlaskConical className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="validation-title">Human vs AI Validation</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Does PaperSumo's AI tournament agree with human peer reviewers? Each dataset below imports real papers with
          reviewer scores, runs an independent AI tournament using full-text extraction, and measures rank correlation.
        </p>
      </div>

      {/* Admin import controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-3 mb-6 bg-secondary/10" data-testid="admin-controls">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Admin:</span>
            Import datasets via API POST /api/validation/import-iclr
            <Button size="sm" variant="ghost" className="ml-auto text-xs gap-1" onClick={fetchDatasets}>
              <RotateCcw className="h-3 w-3" /> Refresh
            </Button>
          </div>
        </div>
      )}

      {datasets.length === 0 ? (
        <div className="border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No validation datasets yet.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {datasets.map(ds => (
            <DatasetPanel key={ds.dataset_id} ds={ds} isAdmin={isAdmin} />
          ))}
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 mt-6 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Data:</strong> ICLR papers with 4+ peer reviews, sourced from OpenReview (berenslab/iclr-dataset). Full PDFs downloaded for section extraction.</li>
          <li><strong>Pairwise BT:</strong> Derives head-to-head matches from reviewers who scored multiple papers. Both sides ranked via Bradley-Terry. Implicitly cancels severity bias.</li>
          <li><strong>IRT Score:</strong> Z-scores each reviewer's ratings against their personal mean/std, averages per paper. Explicitly removes severity bias. Produces finer-grained scores.</li>
          <li><strong>Agreement:</strong> Expert-Expert = reviewer pairwise agreement rate. AI-Expert = AI vs individual reviewer. AI-Majority = AI vs reviewer consensus.</li>
        </ul>
      </div>
    </div>
  );
}
