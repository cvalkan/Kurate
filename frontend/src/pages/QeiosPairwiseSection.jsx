import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Play, Square, Loader2, AlertCircle, Layers,
  CheckCircle, XCircle, BarChart3, GitCompare, FileText, X,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const GAP_LABELS = [
  { key: "small", label: "Small (≤1 star)" },
  { key: "medium", label: "Medium (1–2 stars)" },
  { key: "large", label: "Large (>2 stars)" },
];

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m;
}

function Badge({ rate, label, sub, testId }) {
  const color = rate >= 70 ? "text-green-600" : rate >= 50 ? "text-amber-600" : "text-red-600";
  const bg = rate >= 70 ? "bg-green-50" : rate >= 50 ? "bg-amber-50" : "bg-red-50";
  return (
    <div className={`p-3 rounded-lg border border-border ${bg} text-center`} data-testid={testId}>
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{rate}%</div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function QeiosPairwiseSection({ initialMode = "abstract" }) {
  const [mode, setMode] = useState(initialMode);
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [numPairs, setNumPairs] = useState(20);
  const [parallelAgents, setParallelAgents] = useState(5);
  const [isStarting, setIsStarting] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");
  const pairwisePath = mode === "extract" ? "pairwise-extract" : "pairwise";
  const modeLabel = mode === "extract" ? "Extract" : "Abstract";

  const fetchAll = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        axios.get(`${API}/api/qeios/${pairwisePath}/status`),
        axios.get(`${API}/api/qeios/${pairwisePath}/results`),
      ]);
      setStatus(s.data);
      if (r.data.status === "ok") setResults(r.data);
      if (s.data?.fetching || s.data?.running) setIsStarting(false);
    } catch (e) { console.error(e); }
  }, [pairwisePath]);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => { setResults(null); setStatus(null); }, [mode]);
  useEffect(() => {
    if (!status?.fetching && !status?.running && !isStarting) return;
    const iv = setInterval(fetchAll, isStarting ? 1000 : 2000);
    return () => clearInterval(iv);
  }, [status?.fetching, status?.running, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/qeios/pairwise/fetch-and-run`,
        { num_pairs: numPairs, parallel_agents: parallelAgents },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success(`Synced run started — ${parallelAgents} agents, ${numPairs} pairs`);
      else if (res.data.status === "already_running") { toast.warning("Already running"); setIsStarting(false); }
      else { toast.error(res.data.message || "Error"); setIsStarting(false); }
      fetchAll();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || "Failed");
      setIsStarting(false);
    }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/qeios/pairwise/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped");
      setIsStarting(false);
      fetchAll();
    } catch (e) { toast.error("Failed to stop"); }
  };

  const running = status?.fetching || status?.running || isStarting;

  return (
    <div className="space-y-5">
      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 bg-secondary/10 space-y-3" data-testid={`pw-qeios-admin-${mode}`}>
          {mode === "abstract" ? (
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted-foreground whitespace-nowrap">Pairs:</label>
                <Input type="number" min={5} max={100} value={numPairs}
                  onChange={e => setNumPairs(parseInt(e.target.value) || 20)}
                  className="w-16 h-8 text-xs" data-testid="pw-qeios-num-input" disabled={running} />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted-foreground whitespace-nowrap">Parallel agents:</label>
                <Input type="number" min={1} max={15} value={parallelAgents}
                  onChange={e => setParallelAgents(Math.min(15, Math.max(1, parseInt(e.target.value) || 5)))}
                  className="w-16 h-8 text-xs" data-testid="pw-qeios-agents-input" disabled={running} />
              </div>
              {!running ? (
                <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid="pw-qeios-run-btn">
                  <Play className="h-3.5 w-3.5" /> Fetch & Evaluate (Synced)
                </Button>
              ) : (
                <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid="pw-qeios-stop-btn">
                  <Square className="h-3.5 w-3.5" /> Stop
                </Button>
              )}
              <span className="text-[10px] text-muted-foreground italic">
                {parallelAgents} agents evaluate {parallelAgents * 6} LLM calls simultaneously. Data is additive.
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-3 flex-wrap">
              {running && (
                <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid="pw-qeios-stop-btn-extract">
                  <Square className="h-3.5 w-3.5" /> Stop
                </Button>
              )}
              <span className="text-xs text-muted-foreground">
                Use the <strong>Qeios (Abstract)</strong> tab to start a synced evaluation — both modes share the same paper pairs.
              </span>
            </div>
          )}
          {running && (
            <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2" data-testid={`pw-qeios-progress-${mode}`}>
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              <span className="font-medium">
                {isStarting && !status?.fetching ? "Starting synced run..." :
                  status?.progress?.phase === "scanning" ? "Scanning Crossref for reviewers..." :
                  status?.progress?.phase === "fetching" ? `Fetching pairs... ${status?.progress?.pairs_fetched || 0} ready` :
                  `Evaluating: ${status?.progress?.pairs_done || 0}/${status?.progress?.target || '?'} done`}
                {status?.progress?.phase === "evaluating" && status?.progress?.pairs_in_flight > 0 &&
                  ` (${status.progress.pairs_in_flight} in-flight)`}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Status cards */}
      {status && status.total_pairs > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
          {[["Total Pairs", status.total_pairs, "total"], ["AI Completed", status.ai_completed, "completed"],
            ["AI Pending", status.ai_pending, "pending"], ["AI Failed", status.ai_failed, "failed"]]
            .map(([l, v, key]) => (
              <div key={key} className="p-2 border border-border/50 rounded text-xs" data-testid={`pw-qeios-status-${key}-${mode}`}>
                <div className="text-muted-foreground">{l}</div>
                <div className="font-semibold text-base">{v}</div>
              </div>
            ))}
        </div>
      )}

      {/* Domain breakdown */}
      {status?.by_domain && Object.keys(status.by_domain).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {Object.entries(status.by_domain).sort((a, b) => b[1] - a[1]).map(([d, c]) => (
            <div key={d} className="p-2 border border-border/50 rounded text-xs text-center">
              <div className="text-muted-foreground">{d}</div>
              <div className="font-semibold">{c} pairs</div>
            </div>
          ))}
        </div>
      )}

      {results ? (
        <div className="space-y-5">
          {/* Overall majority */}
          <div className="border border-border rounded-lg p-4" data-testid={`pw-qeios-overall-${mode}`}>
            <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
              <Layers className="h-4 w-4" /> Overall Majority Agreement ({modeLabel})
            </h2>
            <Badge rate={results.overall_majority.rate} label="Majority vs Human"
              sub={`${results.overall_majority.agree}/${results.overall_majority.total} pairs`}
              testId={`pw-qeios-majority-badge-${mode}`} />
          </div>

          {/* Performance by model */}
          {results.by_model_overall && Object.keys(results.by_model_overall).length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-qeios-model-${mode}`}>
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" /> Performance by Model ({modeLabel})
              </h2>
              <div className="space-y-3">
                {Object.entries(results.by_model_overall)
                  .sort((a, b) => b[1].rate - a[1].rate)
                  .map(([mk, s], i) => (
                    <div key={mk} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-medium">{shortModel(mk)}</span>
                        <span className="font-mono text-muted-foreground">{s.agree}/{s.total} &bull; {s.rate}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-secondary/40 overflow-hidden">
                        <div className="h-full bg-accent/70" style={{ width: `${s.rate}%` }} />
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Agreement by score gap */}
          {results.by_gap && Object.values(results.by_gap).some(g => g.total > 0) && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-qeios-gap-${mode}`}>
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" /> Agreement by Score Gap ({modeLabel})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {GAP_LABELS.map(gap => {
                  const g = results.by_gap?.[gap.key];
                  if (!g || g.total === 0) return null;
                  return (
                    <div key={gap.key} className="border border-border/60 rounded-lg p-3" data-testid={`pw-qeios-gap-card-${mode}-${gap.key}`}>
                      <div className="text-xs font-medium mb-1">{gap.label}</div>
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-2">
                        <span>{g.agree}/{g.total} pairs</span>
                        <span className="font-mono">{g.rate}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-secondary/40 overflow-hidden">
                        <div className="h-full bg-accent/70" style={{ width: `${g.rate}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* By domain */}
          {results.by_domain && Object.keys(results.by_domain).length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-qeios-domain-${mode}`}>
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <GitCompare className="h-4 w-4" /> Agreement by Domain
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(results.by_domain).map(([d, s]) => (
                  <Badge key={d} rate={s.rate} label={d} sub={`${s.agree}/${s.total}`} />
                ))}
              </div>
            </div>
          )}

          {/* Inter-model agreement */}
          {results.inter_model && Object.keys(results.inter_model).length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-qeios-inter-${mode}`}>
              <h2 className="text-sm font-medium mb-3">Inter-Model Agreement</h2>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(results.inter_model).map(([k, s]) => {
                  const [m1, m2] = k.split(" vs ");
                  return <Badge key={k} rate={s.rate} label={`${shortModel(m1)} vs ${shortModel(m2)}`} sub={`${s.agree}/${s.total}`} />;
                })}
              </div>
            </div>
          )}

          {/* Sample pairs */}
          {results.samples?.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden" data-testid={`pw-qeios-samples-${mode}`}>
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h2 className="text-xs font-medium">Sample Pairs</h2>
              </div>
              <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
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
                    {results.samples.map((s, i) => (
                      <tr key={i} className="border-b border-border/20 hover:bg-secondary/10">
                        <td className="px-2 py-1 max-w-[180px] truncate" title={s.paper1_title}>
                          <span className={s.human_winner === "paper1" ? "font-semibold" : ""}>{s.paper1_title}</span>
                          <span className="text-[9px] text-muted-foreground ml-1">({s.human_score1})</span>
                        </td>
                        <td className="px-2 py-1 max-w-[180px] truncate" title={s.paper2_title}>
                          <span className={s.human_winner === "paper2" ? "font-semibold" : ""}>{s.paper2_title}</span>
                          <span className="text-[9px] text-muted-foreground ml-1">({s.human_score2})</span>
                        </td>
                        <td className="text-center px-1.5 py-1 text-[10px] text-muted-foreground">{(s.domain || "").split(" ")[0]}</td>
                        <td className="text-center px-1.5 py-1 font-mono">{s.score_gap}</td>
                        <td className="text-center px-1.5 py-1 font-mono text-[10px]">
                          <span className={s.models_agree >= 2 ? "text-green-600" : "text-red-500"}>
                            {s.models_agree}/{s.models_total}
                          </span>
                        </td>
                        <td className="text-center px-1.5 py-1">
                          {s.majority_agree === true && <CheckCircle className="h-3.5 w-3.5 text-green-600 inline" />}
                          {s.majority_agree === false && <XCircle className="h-3.5 w-3.5 text-red-500 inline" />}
                          {s.majority_agree === null && <span className="text-muted-foreground">-</span>}
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
        <div className="border border-border rounded-lg p-8 text-center" data-testid={`pw-qeios-empty-${mode}`}>
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No pairwise comparisons yet. Use admin controls to fetch and evaluate.</p>
        </div>
      ) : null}

      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid={`pw-qeios-methodology-${mode}`}>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium">Methodology</h3>
          {results?.prompts && (
            <Button variant="outline" size="sm" className="gap-1.5 h-7 text-xs" onClick={() => setShowPrompts(true)} data-testid={`pw-qeios-view-prompts-${mode}`}>
              <FileText className="h-3 w-3" /> View Prompts
            </Button>
          )}
        </div>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Source:</strong> Qeios — open peer review with star ratings. One pair per reviewer (no ties) for independence.</li>
          <li><strong>Pair sync:</strong> Abstract and Extract modes use identical paper pairs for head-to-head comparison.</li>
          <li><strong>AI evaluation:</strong> Each pair evaluated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro. Presentation order randomized per model.</li>
          <li><strong>Content:</strong> {mode === "extract" ? "Full body text extracted from Qeios HTML, processed with section extraction algorithm." : "Abstract-only comparison (no full text)."}</li>
          <li><strong>Agreement:</strong> Majority vote and per-model agreement with the human verdict, by domain and score gap.</li>
        </ul>
      </div>

      {/* Prompts modal */}
      {showPrompts && results?.prompts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowPrompts(false)}>
          <div className="bg-background border border-border rounded-lg shadow-lg w-full max-w-2xl max-h-[80vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()} data-testid={`pw-qeios-prompts-modal-${mode}`}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <h3 className="text-sm font-semibold">AI Comparison Prompts</h3>
              <button onClick={() => setShowPrompts(false)} className="p-1 rounded hover:bg-secondary/30" data-testid="pw-qeios-prompts-close">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">System Prompt</div>
                <pre className="text-xs bg-secondary/20 rounded p-3 whitespace-pre-wrap font-mono leading-relaxed">{results.prompts.system_prompt}</pre>
              </div>
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">User Prompt Template</div>
                <pre className="text-xs bg-secondary/20 rounded p-3 whitespace-pre-wrap font-mono leading-relaxed">{results.prompts.user_prompt}</pre>
              </div>
              {results.prompts.content_note && (
                <div className="text-xs text-muted-foreground bg-accent/5 rounded p-3 border border-accent/10">
                  <strong>Note:</strong> {results.prompts.content_note}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
