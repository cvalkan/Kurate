import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  GitCompare, Play, Square, Download, BarChart3,
  CheckCircle, XCircle, Loader2, AlertCircle, Layers,
} from "lucide-react";
import { toast } from "sonner";

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

function Badge({ rate, label, sub }) {
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
  const [numPairs, setNumPairs] = useState(20);
  const [isStarting, setIsStarting] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchAll = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        axios.get(`${API}/api/pairwise/status`),
        axios.get(`${API}/api/pairwise/results`),
      ]);
      setStatus(s.data);
      if (r.data.status === "ok") setResults(r.data);
      // Clear starting state once backend confirms running
      if (s.data?.fetching || s.data?.tournament_running) {
        setIsStarting(false);
      }
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    // Poll faster when running or starting
    if (!status?.fetching && !status?.tournament_running && !isStarting) return;
    const iv = setInterval(fetchAll, isStarting ? 1000 : 2000);
    return () => clearInterval(iv);
  }, [status?.fetching, status?.tournament_running, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/pairwise/fetch-and-run`,
        { source: "qeios", num_pairs: numPairs },
        { headers: adminHeaders() });
      if (res.data.status === "started") {
        toast.success(`Started! Scanning Crossref for reviewers...`);
      } else if (res.data.status === "already_running") {
        toast.warning("Already running");
        setIsStarting(false);
      } else {
        toast.error(res.data.message || "Unknown error");
        setIsStarting(false);
      }
      fetchAll();
    } catch (e) {
      console.error(e);
      toast.error(e.response?.data?.detail || e.message || "Failed to start");
      setIsStarting(false);
    }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/pairwise/stop-tournament`, {}, { headers: adminHeaders() });
      toast.info("Stopped");
      setIsStarting(false);
      fetchAll();
    } catch (e) {
      console.error(e);
      toast.error(e.response?.data?.detail || "Failed to stop");
    }
  };

  const running = status?.fetching || status?.tournament_running || isStarting;

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <GitCompare className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="pairwise-title">Pairwise Expert Comparison</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Unbiased head-to-head: fetch real reviewer pairs (1 per reviewer, no ties),
          evaluate with all 3 AI models, measure agreement. No ranking — direct comparison.
        </p>
      </div>

      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 mb-6 bg-secondary/10 space-y-3" data-testid="admin-controls">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground whitespace-nowrap">New pairs:</label>
              <Input
                type="number" min={5} max={200} value={numPairs}
                onChange={e => setNumPairs(parseInt(e.target.value) || 20)}
                className="w-20 h-8 text-xs" data-testid="num-pairs-input"
              />
            </div>
            {!running ? (
              <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid="fetch-run-btn">
                <Play className="h-3.5 w-3.5" /> Fetch & Evaluate (3 models)
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid="stop-btn">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>
          {running && (
            <div className="flex items-center gap-2 text-xs">
              <Loader2 className="h-3 w-3 animate-spin text-accent" />
              <span>
                Fetched: {status?.progress?.pairs_fetched || 0} | Evaluated: {status?.progress?.pairs_evaluated || 0} / {status?.progress?.target || "?"}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Status */}
      {status && status.total_pairs > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4 text-center">
          {[["Total Pairs", status.total_pairs], ["AI Completed", status.ai_completed], ["AI Pending", status.ai_pending], ["AI Failed", status.ai_failed]]
            .map(([l, v], i) => (
              <div key={i} className="p-2 border border-border/50 rounded text-xs">
                <div className="text-muted-foreground">{l}</div>
                <div className="font-semibold text-base">{v}</div>
              </div>
            ))}
        </div>
      )}

      {/* Domain breakdown */}
      {status?.domains && Object.keys(status.domains).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-6">
          {Object.entries(status.domains).sort((a, b) => b[1] - a[1]).map(([d, c]) => (
            <div key={d} className="p-2 border border-border/50 rounded text-xs text-center">
              <div className="text-muted-foreground">{d}</div>
              <div className="font-semibold">{c} pairs</div>
            </div>
          ))}
        </div>
      )}

      {results ? (
        <div className="space-y-5">
          {/* Majority agreement */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
              <Layers className="h-4 w-4" /> Majority Vote Agreement (3 models)
            </h2>
            <div className="flex items-center gap-4">
              <Badge rate={results.majority_agreement.rate} label="Majority vs Expert"
                sub={`${results.majority_agreement.agree}/${results.majority_agreement.total} pairs`} />
              <div className="text-xs text-muted-foreground max-w-md">
                {results.majority_agreement.rate >= 60 ? "AI majority agrees with human expert more often than not."
                  : results.majority_agreement.rate >= 50 ? "AI majority is near chance level."
                  : "AI majority disagrees more often than not."}
              </div>
            </div>
          </div>

          {/* Per model */}
          {Object.keys(results.by_model).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Agreement by Model</h2>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(results.by_model).map(([m, s]) => (
                  <Badge key={m} rate={s.rate} label={shortModel(m)} sub={`${s.agree}/${s.total}`} />
                ))}
              </div>
            </div>
          )}

          {/* Inter-model */}
          {Object.keys(results.inter_model || {}).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Inter-Model Agreement</h2>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(results.inter_model).map(([k, s]) => {
                  const [m1, m2] = k.split(" vs ");
                  return <Badge key={k} rate={s.rate} label={`${shortModel(m1)} vs ${shortModel(m2)}`} sub={`${s.agree}/${s.total}`} />;
                })}
              </div>
            </div>
          )}

          {/* By domain */}
          {Object.keys(results.by_domain).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Majority Agreement by Domain</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(results.by_domain).map(([d, s]) => (
                  <Badge key={d} rate={s.rate} label={d} sub={`${s.agree}/${s.total}`} />
                ))}
              </div>
            </div>
          )}

          {/* By score gap */}
          {Object.keys(results.by_score_gap).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Majority Agreement by Score Gap</h2>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {Object.entries(results.by_score_gap).map(([g, s]) => (
                  <Badge key={g} rate={s.rate} label={`Gap: ${g} star${g === "1" ? "" : "s"}`} sub={`${s.agree}/${s.total}`} />
                ))}
              </div>
            </div>
          )}

          {/* Full text vs abstract */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-3">Full Text vs Abstract</h2>
            <div className="grid grid-cols-2 gap-2">
              <Badge rate={results.full_text_vs_abstract.full_text.rate} label="Full Text"
                sub={`${results.full_text_vs_abstract.full_text.agree}/${results.full_text_vs_abstract.full_text.total}`} />
              <Badge rate={results.full_text_vs_abstract.abstract_only.rate} label="Abstract Only"
                sub={`${results.full_text_vs_abstract.abstract_only.agree}/${results.full_text_vs_abstract.abstract_only.total}`} />
            </div>
          </div>

          {/* Pairs table */}
          {results.sample_pairs?.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h2 className="text-xs font-medium">All Pairs</h2>
              </div>
              <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-background">
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-left px-2 py-1.5 font-medium">Paper 1</th>
                      <th className="text-left px-2 py-1.5 font-medium">Paper 2</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Domain</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Gap</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Models</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Majority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.sample_pairs.map((p, i) => (
                      <tr key={i} className="border-b border-border/20 hover:bg-secondary/10">
                        <td className="px-2 py-1 max-w-[200px] truncate" title={p.paper1_title}>
                          <span className={p.human_winner === "paper1" ? "font-semibold" : ""}>{p.paper1_title}</span>
                          <span className="text-[9px] text-muted-foreground ml-1">({p.human_score1}★)</span>
                        </td>
                        <td className="px-2 py-1 max-w-[200px] truncate" title={p.paper2_title}>
                          <span className={p.human_winner === "paper2" ? "font-semibold" : ""}>{p.paper2_title}</span>
                          <span className="text-[9px] text-muted-foreground ml-1">({p.human_score2}★)</span>
                        </td>
                        <td className="text-center px-1.5 py-1 text-[10px] text-muted-foreground">{(p.domain || "").split(" ")[0]}</td>
                        <td className="text-center px-1.5 py-1 font-mono">{p.score_gap}</td>
                        <td className="text-center px-1.5 py-1 font-mono text-[10px]">
                          <span className={p.models_agree >= 2 ? "text-green-600" : "text-red-500"}>{p.models_agree}/{p.models_total}</span>
                        </td>
                        <td className="text-center px-1.5 py-1">
                          {p.majority_agree === true && <CheckCircle className="h-3.5 w-3.5 text-green-600 inline" />}
                          {p.majority_agree === false && <XCircle className="h-3.5 w-3.5 text-red-500 inline" />}
                          {p.majority_agree === null && <span className="text-muted-foreground">—</span>}
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
          <p className="text-sm text-muted-foreground">No comparison pairs yet. Use the admin controls above to fetch and evaluate pairs.</p>
        </div>
      ) : null}

      <div className="border border-border rounded-lg p-4 mt-6 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Pair selection:</strong> For each Qeios reviewer who rated ≥2 papers, pick exactly 1 pair (no ties). One pair per reviewer ensures independence.</li>
          <li><strong>Full text:</strong> Both papers fetched with full body text. AI uses section extraction where available, else abstract.</li>
          <li><strong>3-model evaluation:</strong> Every pair evaluated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro. Presentation order randomized per model.</li>
          <li><strong>Agreement:</strong> Per-model and majority-vote agreement with human expert. Broken down by domain, score gap, and text type.</li>
        </ul>
      </div>
    </div>
  );
}
