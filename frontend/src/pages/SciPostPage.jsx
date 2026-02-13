import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Beaker, Play, Square, Loader2, AlertCircle, Info,
  BarChart3, Layers, FileText, X, ChevronDown, ChevronUp,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const DIMENSIONS = ["validity", "significance", "originality", "clarity"];
const DIM_COLORS = {
  validity: "text-blue-600 bg-blue-50",
  significance: "text-purple-600 bg-purple-50",
  originality: "text-amber-600 bg-amber-50",
  clarity: "text-green-600 bg-green-50",
};

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m;
}

function RateBadge({ rate, label, sub }) {
  const color = rate >= 70 ? "text-green-600" : rate >= 50 ? "text-amber-600" : "text-red-600";
  const bg = rate >= 70 ? "bg-green-50" : rate >= 50 ? "bg-amber-50" : "bg-red-50";
  return (
    <div className={`p-3 rounded-lg border border-border ${bg} text-center`}>
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{rate}%</div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

/* ── Tooltip ──────────────────────────────────────────────────────────── */
function Tooltip({ text, children }) {
  return (
    <span className="relative group inline-flex items-center">
      {children}
      <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-md bg-foreground text-background text-[11px] leading-snug px-3 py-2 opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
        {text}
      </span>
    </span>
  );
}

/* ── Prompt Modal ─────────────────────────────────────────────────────── */
function PromptModal({ prompts, onClose }) {
  const [activeDim, setActiveDim] = useState("validity");
  if (!prompts) return null;

  const filledTemplate = prompts.template
    ?.replace("{title}", "<paper title>")
    .replace("{abstract}", "<paper abstract>")
    .replace("{task}", prompts.dimension_tasks?.[activeDim] || "")
    .replace("{DIMENSION}", activeDim.toUpperCase());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-background border border-border rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <FileText className="h-4 w-4" /> LLM Evaluation Prompts
          </h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary" data-testid="close-prompt-modal">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Dimension tabs */}
        <div className="flex border-b border-border px-4">
          {DIMENSIONS.map(d => (
            <button
              key={d}
              onClick={() => setActiveDim(d)}
              className={`px-3 py-2 text-xs font-medium capitalize border-b-2 transition-colors ${
                activeDim === d
                  ? "border-accent text-accent"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              data-testid={`prompt-tab-${d}`}
            >
              {d}
            </button>
          ))}
        </div>

        <div className="overflow-y-auto flex-1 p-5 space-y-4">
          {/* Dimension-specific task */}
          <div>
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Dimension Task</div>
            <div className="text-sm bg-secondary/30 rounded-lg px-4 py-3 border border-border/50">
              {prompts.dimension_tasks?.[activeDim]}
            </div>
          </div>

          {/* System prompt */}
          <div>
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-1">System Prompt</div>
            <div className="text-xs bg-secondary/30 rounded-lg px-4 py-2 border border-border/50 font-mono">
              {prompts.system}
            </div>
          </div>

          {/* Full prompt */}
          <div>
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Full Prompt Sent to Model</div>
            <pre className="text-[11px] bg-secondary/30 rounded-lg px-4 py-3 border border-border/50 whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">
              {filledTemplate}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SciPostPage({ embedded = false }) {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [numPapers, setNumPapers] = useState(15);
  const [isStarting, setIsStarting] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const [expandedRows, setExpandedRows] = useState(new Set());
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchAll = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        axios.get(`${API}/api/scipost/status`),
        axios.get(`${API}/api/scipost/results`),
      ]);
      setStatus(s.data);
      if (r.data.status === "ok") setResults(r.data);
      if (s.data?.fetching || s.data?.running) setIsStarting(false);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    if (!status?.fetching && !status?.running && !isStarting) return;
    const iv = setInterval(fetchAll, isStarting ? 1000 : 2000);
    return () => clearInterval(iv);
  }, [status?.fetching, status?.running, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/scipost/fetch-and-run`,
        { num_papers: numPapers, dimensions: DIMENSIONS },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success(`Started! Fetching ${numPapers} papers...`);
      else if (res.data.status === "already_running") { toast.warning("Already running"); setIsStarting(false); }
      else { toast.error(res.data.message || "Unknown error"); setIsStarting(false); }
      fetchAll();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || "Failed to start");
      setIsStarting(false);
    }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/scipost/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped");
      setIsStarting(false);
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed to stop"); }
  };

  const toggleRow = (i) => {
    setExpandedRows(prev => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });
  };

  const running = status?.fetching || status?.running || isStarting;

  const content = (
    <>
      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 mb-6 bg-secondary/10 space-y-3" data-testid="admin-controls">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Papers to fetch:</label>
              <Input type="number" min={5} max={100} value={numPapers}
                onChange={e => setNumPapers(parseInt(e.target.value) || 15)}
                className="w-20 h-8 text-xs" data-testid="num-papers-input" disabled={running} />
            </div>
            {!running ? (
              <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid="fetch-run-btn">
                <Play className="h-3.5 w-3.5" /> Fetch & Evaluate
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid="stop-btn">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>
          {running && (
            <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2">
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              <span className="font-medium">
                {isStarting && !status?.fetching ? "Starting..." :
                  status?.progress?.phase === "scanning" ? "Scanning SciPost submissions..." :
                  status?.progress?.phase === "fetching papers" ? `Fetching papers: ${status?.progress?.papers_found || 0}` :
                  `Evaluating: ${status?.progress?.comparisons_done || 0} comparisons done`}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Status cards */}
      {status && status.total_comparisons > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-6 text-center">
          {[["Total Comparisons", status.total_comparisons], ["AI Completed", status.ai_completed],
            ["AI Pending", status.ai_pending], ["AI Failed", status.ai_failed]]
            .map(([l, v], i) => (
              <div key={i} className="p-2 border border-border/50 rounded text-xs">
                <div className="text-muted-foreground">{l}</div>
                <div className="font-semibold text-base">{v}</div>
              </div>
            ))}
        </div>
      )}

      {results ? (
        <div className="space-y-5">
          {/* View Prompts button */}
          <div className="flex justify-end">
            <Button variant="outline" size="sm" className="gap-1.5 text-xs" onClick={() => setShowPrompts(true)} data-testid="view-prompts-btn">
              <FileText className="h-3.5 w-3.5" /> View LLM Prompts
            </Button>
          </div>

          {/* Per-dimension agreement */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-1 flex items-center gap-1.5">
              <Layers className="h-4 w-4" /> Agreement by Dimension
              <Tooltip text="Compares the AI consensus rating (average of all 3 models) against the human referee rating for each dimension. Shows how well AI as a group matches the human expert.">
                <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help ml-1" />
              </Tooltip>
            </h2>
            <p className="text-xs text-muted-foreground mb-3">
              "Close" = AI consensus rating within ±1 of human (on 1–6 scale). MAE = Mean Absolute Error.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {DIMENSIONS.map(dim => {
                const d = results.by_dimension?.[dim];
                if (!d) return null;
                return (
                  <div key={dim} className={`p-3 rounded-lg border ${DIM_COLORS[dim]} border-border`} data-testid={`dim-card-${dim}`}>
                    <div className="text-xs font-medium mb-2 capitalize">{dim}</div>
                    <div className="text-2xl font-bold font-mono">{d.close_rate}%</div>
                    <div className="text-[10px] text-muted-foreground">
                      {d.close_match}/{d.total} close | MAE: {d.mae}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Overall model performance */}
          {results.model_overall && Object.keys(results.model_overall).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" /> Model Performance (All Dimensions)
                <Tooltip text="Shows each individual model's accuracy against the human referee, measured independently. A model scores 'close' when its own rating is within ±1 of the human rating — no consensus averaging involved.">
                  <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help ml-1" />
                </Tooltip>
              </h2>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(results.model_overall).map(([mk, stats]) => (
                  <RateBadge key={mk} rate={stats.close_rate} label={shortModel(mk)} sub={`${stats.total} ratings`} />
                ))}
              </div>
            </div>
          )}

          {/* Model performance by dimension */}
          {results.by_model && Object.keys(results.by_model).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Model × Dimension Breakdown</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs" data-testid="model-dim-table">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 px-2">Model</th>
                      {DIMENSIONS.map(d => <th key={d} className="text-center py-2 px-2 capitalize">{d}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(results.by_model).map(([mk, dims]) => (
                      <tr key={mk} className="border-b border-border/30">
                        <td className="py-2 px-2 font-medium">{shortModel(mk)}</td>
                        {DIMENSIONS.map(dim => {
                          const s = dims[dim];
                          if (!s) return <td key={dim} className="text-center text-muted-foreground">—</td>;
                          const color = s.close_rate >= 70 ? "text-green-600" : s.close_rate >= 50 ? "text-amber-600" : "text-red-600";
                          return <td key={dim} className={`text-center font-mono ${color}`}>{s.close_rate}%</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Rating distribution */}
          {results.rating_distribution && (
            <div className="border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium mb-3">Rating Distribution (Human vs AI)</h2>
              <div className="grid grid-cols-2 gap-4">
                {[["Human Ratings", "human", "bg-blue-500"], ["AI Ratings", "ai", "bg-purple-500"]].map(([title, key, barColor]) => (
                  <div key={key}>
                    <div className="text-xs text-muted-foreground mb-2">{title}</div>
                    <div className="flex gap-1">
                      {[1,2,3,4,5,6].map(r => {
                        const count = results.rating_distribution[key]?.[r] || 0;
                        const max = Math.max(...Object.values(results.rating_distribution[key] || {}), 1);
                        const height = Math.max((count / max) * 60, 4);
                        return (
                          <div key={r} className="flex flex-col items-center">
                            <div className="text-[10px] text-muted-foreground mb-1">{count}</div>
                            <div className={`w-6 ${barColor} rounded-t`} style={{ height: `${height}px` }} />
                            <div className="text-[10px] mt-1">{r}</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
              <div className="text-[10px] text-muted-foreground mt-2">Scale: 1=Poor, 2=Low, 3=OK, 4=Good, 5=High, 6=Top</div>
            </div>
          )}

          {/* Sample comparisons — now with Referee column */}
          {results.samples?.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden" data-testid="samples-table">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center justify-between">
                <h2 className="text-xs font-medium">Sample Comparisons</h2>
                <Tooltip text="Each row is one referee report × one dimension. The same paper appears multiple times because different referees rated it, and each dimension (validity, significance, etc.) is evaluated separately.">
                  <span className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-help">
                    <Info className="h-3 w-3" /> Why do papers repeat?
                  </span>
                </Tooltip>
              </div>
              <div className="overflow-x-auto max-h-[450px] overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-background z-10">
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-left px-2 py-1.5 font-medium">Paper</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Referee</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Dim</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Human</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">AI</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">GPT</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Claude</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Gemini</th>
                      <th className="w-6"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.samples.map((s, i) => {
                      const diff = s.ai_consensus ? Math.abs(s.human_rating - s.ai_consensus) : null;
                      const match = diff !== null && diff <= 1;
                      const expanded = expandedRows.has(i);
                      const modelEntries = Object.entries(s.ai_ratings || {}).slice(0, 3);
                      return (
                        <tr key={i} className={`border-b border-border/20 hover:bg-secondary/10 cursor-pointer ${expanded ? "bg-secondary/5" : ""}`} onClick={() => toggleRow(i)} data-testid={`sample-row-${i}`}>
                          <td className="px-2 py-1 max-w-[180px] truncate" title={s.paper_title}>{s.paper_title}</td>
                          <td className="text-center px-1.5 py-1 text-muted-foreground font-mono text-[10px]" data-testid={`referee-${i}`}>{s.referee || "—"}</td>
                          <td className={`text-center px-1.5 py-1 capitalize ${DIM_COLORS[s.dimension]?.split(' ')[0] || ''}`}>{s.dimension?.substring(0, 4)}</td>
                          <td className="text-center px-1.5 py-1 font-mono font-medium">
                            {s.human_rating} <span className="text-[9px] text-muted-foreground">({s.human_label})</span>
                          </td>
                          <td className={`text-center px-1.5 py-1 font-mono ${match ? 'text-green-600' : 'text-red-500'}`}>{s.ai_consensus?.toFixed(1) || '—'}</td>
                          {modelEntries.map(([mk, rating]) => (
                            <td key={mk} className="text-center px-1.5 py-1 font-mono text-muted-foreground">{rating || '—'}</td>
                          ))}
                          {/* pad if fewer than 3 models */}
                          {Array.from({ length: Math.max(0, 3 - modelEntries.length) }).map((_, j) => (
                            <td key={`pad-${j}`} className="text-center px-1.5 py-1 text-muted-foreground">—</td>
                          ))}
                          <td className="px-1 py-1 text-muted-foreground">
                            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      ) : status?.total_comparisons === 0 ? (
        <div className="border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No SciPost comparisons yet. Use the admin controls to fetch and evaluate papers.</p>
        </div>
      ) : null}

      <div className="border border-border rounded-lg p-4 mt-6 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Data source:</strong> SciPost Physics — open peer review with structured referee ratings.</li>
          <li><strong>Dimensions:</strong> Validity, Significance, Originality, Clarity (each rated 1-6 by human referees).</li>
          <li><strong>AI evaluation:</strong> Each model rates the paper on each dimension using only title + abstract.</li>
          <li><strong>Agreement metric:</strong> "Close" = AI within +/-1 of human rating. MAE = average absolute difference.</li>
          <li><strong>Why papers repeat:</strong> Each row = 1 referee x 1 dimension. A paper with 2 referees and 4 dimensions produces 8 rows.</li>
        </ul>
      </div>

      {/* Prompt modal */}
      {showPrompts && <PromptModal prompts={results?.prompts} onClose={() => setShowPrompts(false)} />}
    </>
  );

  if (embedded) return <div className="space-y-5">{content}</div>;

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <Beaker className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="scipost-title">SciPost Dimension Analysis</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Physics papers from SciPost with structured referee ratings.
          AI rates each paper on <strong>validity</strong>, <strong>significance</strong>, <strong>originality</strong>, and <strong>clarity</strong> — then we compare against human referee scores.
        </p>
      </div>
      {content}
    </div>
  );
}
