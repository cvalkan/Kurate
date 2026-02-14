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
  { key: "small", label: "Small (\u22641 star)" },
  { key: "medium", label: "Medium (1\u20132 stars)" },
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

function HBar({ rate, label, sub, color = "bg-blue-400/70" }) {
  const textColor = rate >= 70 ? "text-green-700" : rate >= 50 ? "text-amber-700" : "text-red-700";
  return (
    <div className="space-y-1">
      {label && <div className="text-[10px] text-muted-foreground">{label}</div>}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2.5 rounded-full bg-secondary/40 overflow-hidden">
          <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(rate, 100)}%` }} />
        </div>
        <span className={`text-xs font-mono font-semibold min-w-[40px] text-right ${textColor}`}>{rate}%</span>
      </div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function ModeColumn({ mode, modeLabel, results, status }) {
  if (!results && (!status || status.total_pairs === 0)) {
    return (
      <div className="text-center py-8">
        <AlertCircle className="h-6 w-6 mx-auto mb-2 text-muted-foreground/30" />
        <p className="text-xs text-muted-foreground">No {modeLabel} data yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Status */}
      {status && status.total_pairs > 0 && (
        <div className="flex gap-2 text-center">
          {[["Pairs", status.total_pairs], ["Done", status.ai_completed]].map(([l, v]) => (
            <div key={l} className="flex-1 p-1.5 border border-border/50 rounded text-[10px]">
              <div className="text-muted-foreground">{l}</div>
              <div className="font-semibold">{v}</div>
            </div>
          ))}
        </div>
      )}

      {results && (
        <>
          {/* Overall majority */}
          <div className="p-3 rounded-lg border border-border bg-secondary/5" data-testid={`pw-qeios-overall-${mode}`}>
            <div className="text-[10px] text-muted-foreground mb-1">Majority vs Human</div>
            <div className={`text-2xl font-bold font-mono ${results.overall_majority.rate >= 60 ? "text-green-700" : "text-amber-700"}`}>
              {results.overall_majority.rate}%
            </div>
            <div className="text-[10px] text-muted-foreground">{results.overall_majority.agree}/{results.overall_majority.total} pairs</div>
          </div>

          {/* Per model */}
          {results.by_model_overall && (
            <div className="space-y-2" data-testid={`pw-qeios-models-${mode}`}>
              <div className="text-xs font-medium">Model Agreement</div>
              {Object.entries(results.by_model_overall)
                .sort((a, b) => b[1].rate - a[1].rate)
                .map(([mk, s]) => (
                  <HBar key={mk} rate={s.rate} label={shortModel(mk)} sub={`${s.agree}/${s.total}`} />
                ))}
            </div>
          )}

          {/* Score gap */}
          {results.by_gap && Object.values(results.by_gap).some(g => g.total > 0) && (
            <div className="space-y-2" data-testid={`pw-qeios-gap-${mode}`}>
              <div className="text-xs font-medium">By Score Gap</div>
              {GAP_LABELS.map(gap => {
                const g = results.by_gap?.[gap.key];
                if (!g || g.total === 0) return null;
                return <HBar key={gap.key} rate={g.rate} label={gap.label} sub={`${g.agree}/${g.total}`} />;
              })}
            </div>
          )}

          {/* Inter-model */}
          {results.inter_model && Object.keys(results.inter_model).length > 0 && (
            <div className="space-y-2" data-testid={`pw-qeios-inter-${mode}`}>
              <div className="text-xs font-medium">Inter-Model</div>
              {Object.entries(results.inter_model).map(([k, s]) => {
                const [m1, m2] = k.split(" vs ");
                return <HBar key={k} rate={s.rate} label={`${shortModel(m1)} vs ${shortModel(m2)}`} sub={`${s.agree}/${s.total}`} color="bg-purple-400/70" />;
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function QeiosPairwiseSection() {
  const [absStatus, setAbsStatus] = useState(null);
  const [absResults, setAbsResults] = useState(null);
  const [extStatus, setExtStatus] = useState(null);
  const [extResults, setExtResults] = useState(null);
  const [numPairs, setNumPairs] = useState(20);
  const [parallelAgents, setParallelAgents] = useState(5);
  const [isStarting, setIsStarting] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchAll = useCallback(async () => {
    try {
      const [as, ar, es, er] = await Promise.all([
        axios.get(`${API}/api/qeios/pairwise/status`),
        axios.get(`${API}/api/qeios/pairwise/results`),
        axios.get(`${API}/api/qeios/pairwise-extract/status`),
        axios.get(`${API}/api/qeios/pairwise-extract/results`),
      ]);
      setAbsStatus(as.data);
      if (ar.data.status === "ok") setAbsResults(ar.data);
      setExtStatus(es.data);
      if (er.data.status === "ok") setExtResults(er.data);
      if (as.data?.fetching || as.data?.running) setIsStarting(false);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    if (!absStatus?.fetching && !absStatus?.running && !isStarting) return;
    const iv = setInterval(fetchAll, isStarting ? 1000 : 2000);
    return () => clearInterval(iv);
  }, [absStatus?.fetching, absStatus?.running, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/qeios/pairwise/fetch-and-run`,
        { num_pairs: numPairs, parallel_agents: parallelAgents },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success(`Synced run started`);
      else if (res.data.status === "already_running") { toast.warning("Already running"); setIsStarting(false); }
      else { toast.error(res.data.message || "Error"); setIsStarting(false); }
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); setIsStarting(false); }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/qeios/pairwise/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped"); setIsStarting(false); fetchAll();
    } catch (e) { toast.error("Failed to stop"); }
  };

  const running = absStatus?.fetching || absStatus?.running || isStarting;
  const prompts = absResults?.prompts || extResults?.prompts;

  return (
    <div className="space-y-5">
      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 bg-secondary/10 space-y-3" data-testid="pw-qeios-admin">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Pairs:</label>
              <Input type="number" min={5} max={100} value={numPairs}
                onChange={e => setNumPairs(parseInt(e.target.value) || 20)}
                className="w-16 h-8 text-xs" disabled={running} data-testid="pw-qeios-num-input" />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Agents:</label>
              <Input type="number" min={1} max={15} value={parallelAgents}
                onChange={e => setParallelAgents(Math.min(15, Math.max(1, parseInt(e.target.value) || 5)))}
                className="w-16 h-8 text-xs" disabled={running} data-testid="pw-qeios-agents-input" />
            </div>
            {!running ? (
              <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid="pw-qeios-run-btn">
                <Play className="h-3.5 w-3.5" /> Fetch & Evaluate
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid="pw-qeios-stop-btn">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>
          {running && (
            <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2" data-testid="pw-qeios-progress">
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              <span className="font-medium">
                {isStarting && !absStatus?.fetching ? "Starting synced run..." :
                  absStatus?.progress?.phase === "scanning" ? "Scanning Crossref..." :
                  absStatus?.progress?.phase === "fetching" ? `Fetching pairs... ${absStatus?.progress?.pairs_fetched || 0}` :
                  `Evaluating: ${absStatus?.progress?.pairs_done || 0}/${absStatus?.progress?.target || '?'}`}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Domain breakdown */}
      {absStatus?.by_domain && Object.keys(absStatus.by_domain).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {Object.entries(absStatus.by_domain).sort((a, b) => b[1] - a[1]).map(([d, c]) => (
            <div key={d} className="p-2 border border-border/50 rounded text-xs text-center">
              <div className="text-muted-foreground">{d}</div>
              <div className="font-semibold">{c} pairs</div>
            </div>
          ))}
        </div>
      )}

      {/* Side-by-side Abstract | Extract */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="pw-qeios-comparison">
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3 flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5" /> Abstract
          </h3>
          <ModeColumn mode="abstract" modeLabel="Abstract" results={absResults} status={absStatus} />
        </div>
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-3 flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5" /> Extract
          </h3>
          <ModeColumn mode="extract" modeLabel="Extract" results={extResults} status={extStatus} />
        </div>
      </div>

      {/* Sample pairs table - show from whichever mode has data */}
      {(absResults?.samples?.length > 0 || extResults?.samples?.length > 0) && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-qeios-samples">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h2 className="text-xs font-medium">Sample Pairs</h2>
          </div>
          <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
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
                {(absResults?.samples || extResults?.samples || []).map((s, i) => (
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
                      <span className={s.models_agree >= 2 ? "text-green-600" : "text-red-500"}>{s.models_agree}/{s.models_total}</span>
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

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="pw-qeios-methodology">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium">Methodology</h3>
          {prompts && (
            <Button variant="outline" size="sm" className="gap-1.5 h-7 text-xs" onClick={() => setShowPrompts(true)} data-testid="pw-qeios-view-prompts">
              <FileText className="h-3 w-3" /> View Prompts
            </Button>
          )}
        </div>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Source:</strong> Qeios — open peer review with star ratings. One pair per reviewer (no ties).</li>
          <li><strong>Pair sync:</strong> Abstract and Extract modes use identical paper pairs.</li>
          <li><strong>AI evaluation:</strong> Each pair evaluated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.</li>
          <li><strong>Agreement:</strong> Majority vote and per-model agreement with the human verdict.</li>
        </ul>
      </div>

      {/* Prompts modal */}
      {showPrompts && prompts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowPrompts(false)}>
          <div className="bg-background border border-border rounded-lg shadow-lg w-full max-w-2xl max-h-[80vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()} data-testid="pw-qeios-prompts-modal">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <h3 className="text-sm font-semibold">AI Comparison Prompts</h3>
              <button onClick={() => setShowPrompts(false)} className="p-1 rounded hover:bg-secondary/30" data-testid="pw-qeios-prompts-close">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">System Prompt</div>
                <pre className="text-xs bg-secondary/20 rounded p-3 whitespace-pre-wrap font-mono leading-relaxed">{prompts.system_prompt}</pre>
              </div>
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">User Prompt Template</div>
                <pre className="text-xs bg-secondary/20 rounded p-3 whitespace-pre-wrap font-mono leading-relaxed">{prompts.user_prompt}</pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
