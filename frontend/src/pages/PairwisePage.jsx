import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  GitCompare, Play, Square, Download, BarChart3,
  CheckCircle, XCircle, Loader2, AlertCircle,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m;
}

function AgreementBadge({ rate, label, sub }) {
  const color = rate >= 70 ? "text-green-600" : rate >= 55 ? "text-amber-600" : "text-red-600";
  const bg = rate >= 70 ? "bg-green-50" : rate >= 55 ? "bg-amber-50" : "bg-red-50";
  return (
    <div className={`p-3 rounded-lg border border-border ${bg} text-center`}>
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{rate}%</div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function PairwisePage() {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [numPairs, setNumPairs] = useState(50);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchAll = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        axios.get(`${API}/api/pairwise/status`),
        axios.get(`${API}/api/pairwise/results`),
      ]);
      setStatus(s.data);
      if (r.data.status === "ok") setResults(r.data);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    if (!status?.fetching && !status?.tournament_running) return;
    const iv = setInterval(fetchAll, 5000);
    return () => clearInterval(iv);
  }, [status?.fetching, status?.tournament_running, fetchAll]);

  const fetchPairs = async () => {
    try {
      await axios.post(`${API}/api/pairwise/fetch-pairs`,
        { source: "qeios", num_pairs: numPairs },
        { headers: adminHeaders() });
      fetchAll();
    } catch (e) { console.error(e); }
  };

  const runTournament = async () => {
    try {
      await axios.post(`${API}/api/pairwise/run-tournament`,
        { parallel: 10 },
        { headers: adminHeaders() });
      fetchAll();
    } catch (e) { console.error(e); }
  };

  const stopTournament = async () => {
    try {
      await axios.post(`${API}/api/pairwise/stop-tournament`, {}, { headers: adminHeaders() });
      fetchAll();
    } catch (e) { console.error(e); }
  };

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <GitCompare className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="pairwise-title">Pairwise Expert Comparison</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Unbiased head-to-head test: fetch real reviewer pairs (1 pair per reviewer, no ties),
          run AI on the exact same pairs, and measure agreement rate. No ranking — just direct comparison.
        </p>
      </div>

      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 mb-6 bg-secondary/10 space-y-3" data-testid="admin-controls">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Pairs to fetch:</label>
              <Input
                type="number" min={10} max={500} value={numPairs}
                onChange={e => setNumPairs(parseInt(e.target.value) || 50)}
                className="w-20 h-8 text-xs" data-testid="num-pairs-input"
              />
            </div>
            <Button size="sm" onClick={fetchPairs} disabled={status?.fetching} className="gap-1.5" data-testid="fetch-btn">
              {status?.fetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              {status?.fetching ? "Fetching..." : "Fetch from Qeios"}
            </Button>
            <div className="border-l border-border h-6 mx-1" />
            {!status?.tournament_running ? (
              <Button size="sm" onClick={runTournament} disabled={!status?.ai_pending} className="gap-1.5" data-testid="run-btn">
                <Play className="h-3.5 w-3.5" /> Run AI Tournament
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stopTournament} className="gap-1.5" data-testid="stop-btn">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>

          {/* Progress */}
          {(status?.fetching || status?.tournament_running) && (
            <div className="flex items-center gap-2 text-xs">
              <Loader2 className="h-3 w-3 animate-spin text-accent" />
              {status.fetching && <span>Fetching pairs: {status.progress?.found || 0} / {status.progress?.target || "?"}</span>}
              {status.tournament_running && <span>AI tournament: {status.progress?.completed || 0} / {status.progress?.total || "?"}</span>}
            </div>
          )}
        </div>
      )}

      {/* Status summary */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-6 text-center">
          {[
            ["Total Pairs", status.total_pairs],
            ["AI Completed", status.ai_completed],
            ["AI Pending", status.ai_pending],
            ["AI Failed", status.ai_failed],
          ].map(([label, val], i) => (
            <div key={i} className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">{label}</div>
              <div className="font-semibold text-base">{val}</div>
            </div>
          ))}
        </div>
      )}

      {/* Domain breakdown */}
      {status?.domains && Object.keys(status.domains).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-6">
          {Object.entries(status.domains).sort((a, b) => b[1] - a[1]).map(([domain, count]) => (
            <div key={domain} className="p-2 border border-border/50 rounded text-xs text-center">
              <div className="text-muted-foreground">{domain}</div>
              <div className="font-semibold">{count} pairs</div>
            </div>
          ))}
        </div>
      )}

      {/* Results */}
      {results ? (
        <div className="space-y-5">
          {/* Overall agreement */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
              <BarChart3 className="h-4 w-4" /> Overall Agreement
            </h2>
            <div className="flex items-center gap-4">
              <AgreementBadge
                rate={results.overall_agreement.rate}
                label="AI vs Expert"
                sub={`${results.overall_agreement.agree}/${results.overall_agreement.total} pairs`}
              />
              <div className="text-xs text-muted-foreground max-w-md">
                {results.overall_agreement.rate >= 60
                  ? "AI agrees with human expert more often than not."
                  : results.overall_agreement.rate >= 50
                  ? "AI is near chance level — limited domain expertise."
                  : "AI disagrees with human expert more often than not."}
              </div>
            </div>
          </div>

          {/* By domain */}
          {Object.keys(results.by_domain).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Agreement by Domain</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(results.by_domain).map(([domain, stats]) => (
                  <AgreementBadge
                    key={domain} rate={stats.rate}
                    label={domain} sub={`${stats.agree}/${stats.total}`}
                  />
                ))}
              </div>
            </div>
          )}

          {/* By model */}
          {Object.keys(results.by_model).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Agreement by Model</h2>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(results.by_model).map(([model, stats]) => (
                  <AgreementBadge
                    key={model} rate={stats.rate}
                    label={shortModel(model)} sub={`${stats.agree}/${stats.total}`}
                  />
                ))}
              </div>
            </div>
          )}

          {/* By score gap */}
          {Object.keys(results.by_score_gap).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Agreement by Score Gap</h2>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {Object.entries(results.by_score_gap).map(([gap, stats]) => (
                  <AgreementBadge
                    key={gap} rate={stats.rate}
                    label={`Gap: ${gap} star${gap === "1" ? "" : "s"}`}
                    sub={`${stats.agree}/${stats.total}`}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Full text vs abstract */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-3">Full Text vs Abstract</h2>
            <div className="grid grid-cols-2 gap-2">
              <AgreementBadge
                rate={results.full_text_vs_abstract.full_text.rate}
                label="Full Text" sub={`${results.full_text_vs_abstract.full_text.agree}/${results.full_text_vs_abstract.full_text.total}`}
              />
              <AgreementBadge
                rate={results.full_text_vs_abstract.abstract_only.rate}
                label="Abstract Only" sub={`${results.full_text_vs_abstract.abstract_only.agree}/${results.full_text_vs_abstract.abstract_only.total}`}
              />
            </div>
          </div>

          {/* Sample pairs table */}
          {results.sample_pairs?.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h2 className="text-xs font-medium">Sample Pairs</h2>
              </div>
              <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-background">
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-left px-2 py-1.5 font-medium">Paper 1</th>
                      <th className="text-left px-2 py-1.5 font-medium">Paper 2</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Domain</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Gap</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.sample_pairs.map((p, i) => (
                      <tr key={i} className="border-b border-border/20 hover:bg-secondary/10">
                        <td className="px-2 py-1 max-w-[180px] truncate" title={p.paper1_title}>
                          {p.human_winner === "paper1" ? <strong>{p.paper1_title}</strong> : p.paper1_title}
                        </td>
                        <td className="px-2 py-1 max-w-[180px] truncate" title={p.paper2_title}>
                          {p.human_winner === "paper2" ? <strong>{p.paper2_title}</strong> : p.paper2_title}
                        </td>
                        <td className="text-center px-1.5 py-1 text-[10px] text-muted-foreground">{p.domain?.split(" ")[0]}</td>
                        <td className="text-center px-1.5 py-1 font-mono">{p.score_gap}</td>
                        <td className="text-center px-1.5 py-1">
                          {p.agree
                            ? <CheckCircle className="h-3.5 w-3.5 text-green-600 inline" />
                            : <XCircle className="h-3.5 w-3.5 text-red-500 inline" />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      ) : status?.total_pairs === 0 ? (
        <div className="border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No comparison pairs yet. Use the admin controls above to fetch pairs from Qeios.</p>
        </div>
      ) : null}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 mt-6 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Pair selection:</strong> For each reviewer who rated ≥2 papers, pick exactly 1 pair (no ties). This ensures unbiased, independent comparisons.</li>
          <li><strong>Full text:</strong> Both papers fetched with full body text from Qeios. AI uses section extraction where available, falls back to abstract.</li>
          <li><strong>AI evaluation:</strong> Round-robin across GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro. Presentation order randomized.</li>
          <li><strong>Agreement:</strong> Direct binary match — does the AI pick the same winner as the human expert? No ranking or scoring.</li>
        </ul>
      </div>
    </div>
  );
}
