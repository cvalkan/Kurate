import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Play, Square, Loader2, AlertCircle, Layers,
  CheckCircle, XCircle, BarChart3, GitCompare,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const DIMENSIONS = ["validity", "significance", "originality", "clarity"];
const GAP_LABELS = [
  { key: "small", label: "Small (≤1.0)" },
  { key: "medium", label: "Medium (1.0–2.0)" },
  { key: "large", label: "Large (>2.0)" },
];
const DIM_COLORS = {
  validity: "text-blue-600 bg-blue-50 border-blue-200",
  significance: "text-purple-600 bg-purple-50 border-purple-200",
  originality: "text-amber-600 bg-amber-50 border-amber-200",
  clarity: "text-green-600 bg-green-50 border-green-200",
};

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m;
}

function safeTestId(value) {
  return value ? value.replace(/[^a-z0-9-]/gi, "-") : "unknown";
}

function aggregateGapStats(results) {
  const totals = {
    small: { agree: 0, total: 0 },
    medium: { agree: 0, total: 0 },
    large: { agree: 0, total: 0 },
  };
  Object.values(results?.by_dimension || {}).forEach(dim => {
    const gaps = dim.by_gap || {};
    Object.keys(totals).forEach(k => {
      if (gaps[k]) {
        totals[k].agree += gaps[k].agree || 0;
        totals[k].total += gaps[k].total || 0;
      }
    });
  });
  Object.keys(totals).forEach(k => {
    const t = totals[k].total || 0;
    const a = totals[k].agree || 0;
    totals[k].rate = t ? Math.round((a / t) * 1000) / 10 : 0;
  });
  return totals;
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

export default function SciPostPairwiseSection({ mode = "abstract" }) {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [numPairs, setNumPairs] = useState(8);
  const [isStarting, setIsStarting] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");
  const pairwisePath = mode === "extract" ? "pairwise-extract" : "pairwise";
  const modeLabel = mode === "extract" ? "Extract" : "Abstract";

  const fetchAll = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        axios.get(`${API}/api/scipost/${pairwisePath}/status`),
        axios.get(`${API}/api/scipost/${pairwisePath}/results`),
      ]);
      setStatus(s.data);
      if (r.data.status === "ok") setResults(r.data);
      if (s.data?.fetching || s.data?.running) setIsStarting(false);
    } catch (e) { console.error(e); }
  }, [pairwisePath]);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    setResults(null);
    setStatus(null);
  }, [mode]);
  useEffect(() => {
    if (!status?.fetching && !status?.running && !isStarting) return;
    const iv = setInterval(fetchAll, isStarting ? 1000 : 2000);
    return () => clearInterval(iv);
  }, [status?.fetching, status?.running, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/scipost/${pairwisePath}/fetch-and-run`,
        { num_pairs_per_dim: numPairs, dimensions: DIMENSIONS },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success(`Started! ${numPairs} pairs per dimension...`);
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
      await axios.post(`${API}/api/scipost/${pairwisePath}/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped");
      setIsStarting(false);
      fetchAll();
    } catch (e) { toast.error("Failed to stop"); }
  };

  const running = status?.fetching || status?.running || isStarting;

  const gapStats = results ? aggregateGapStats(results) : null;
  const hasGapData = gapStats && Object.values(gapStats).some(g => g.total > 0);
  
  // Debug logging
  console.log(`[${mode}] Results:`, results ? 'present' : 'null');
  console.log(`[${mode}] Gap stats:`, gapStats);
  console.log(`[${mode}] Has gap data:`, hasGapData);

  return (
    <div className="space-y-5">
      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 bg-secondary/10 space-y-3" data-testid={`pw-scipost-admin-${mode}`}>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Pairs per dimension:</label>
              <Input type="number" min={3} max={30} value={numPairs}
                onChange={e => setNumPairs(parseInt(e.target.value) || 8)}
                className="w-20 h-8 text-xs" data-testid={`pw-scipost-num-input-${mode}`} disabled={running} />
            </div>
            {!running ? (
              <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid={`pw-scipost-run-btn-${mode}`}>
                <Play className="h-3.5 w-3.5" /> Fetch & Evaluate
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid={`pw-scipost-stop-btn-${mode}`}>
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>
          {running && (
            <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2" data-testid={`pw-scipost-progress-${mode}`}>
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              <span className="font-medium">
                {isStarting && !status?.fetching ? "Starting..." :
                  status?.progress?.phase === "scanning" ? `Scanning SciPost... ${status?.progress?.papers_found || 0} papers found` :
                  status?.progress?.phase === "extracting_pdfs" ? `Extracting PDFs... ${status?.progress?.pdfs_done || 0} ready` :
                  `Evaluating: ${status?.progress?.pairs_done || 0} / ${status?.progress?.target || '?'} pairs`}
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
              <div key={key} className="p-2 border border-border/50 rounded text-xs" data-testid={`pw-status-${key}-${mode}`}>
                <div className="text-muted-foreground">{l}</div>
                <div className="font-semibold text-base">{v}</div>
              </div>
            ))}
        </div>
      )}

      {results ? (
        <div className="space-y-5">
          {/* Overall majority */}
          <div className="border border-border rounded-lg p-4" data-testid={`pw-overall-majority-${mode}`}>
            <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
              <Layers className="h-4 w-4" /> Overall Majority Agreement (all dimensions)
            </h2>
            <Badge rate={results.overall_majority.rate} label="Majority vs Human"
              sub={`${results.overall_majority.agree}/${results.overall_majority.total} pairs`}
              testId={`pw-overall-majority-badge-${mode}`} />
          </div>

          {/* Performance by model */}
          {results.by_model_overall && Object.keys(results.by_model_overall).length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-performance-model-${mode}`}>
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" /> Performance by Model ({modeLabel})
              </h2>
              <div className="space-y-3">
                {Object.entries(results.by_model_overall)
                  .sort((a, b) => b[1].rate - a[1].rate)
                  .map(([mk, s], i) => (
                    <div key={mk} className="space-y-1" data-testid={`pw-performance-row-${mode}-${i}`}>
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-medium">{shortModel(mk)}</span>
                        <span className="font-mono text-muted-foreground">{s.agree}/{s.total} • {s.rate}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-secondary/40 overflow-hidden" data-testid={`pw-performance-bar-${mode}-${i}`}>
                        <div className="h-full bg-accent/70" style={{ width: `${s.rate}%` }} />
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Agreement by score gap */}
          {hasGapData && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-gap-chart-${mode}`}>
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" /> Agreement by Score Gap ({modeLabel})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {GAP_LABELS.map((gap, i) => {
                  const g = gapStats[gap.key];
                  return (
                    <div key={gap.key} className="border border-border/60 rounded-lg p-3" data-testid={`pw-gap-card-${mode}-${gap.key}`}>
                      <div className="text-xs font-medium mb-1">{gap.label}</div>
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-2">
                        <span>{g.agree}/{g.total} pairs</span>
                        <span className="font-mono">{g.rate}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-secondary/40 overflow-hidden" data-testid={`pw-gap-bar-${mode}-${i}`}>
                        <div className="h-full bg-accent/70" style={{ width: `${g.rate}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Per-dimension breakdown */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
              <GitCompare className="h-4 w-4" /> Agreement by Dimension
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {DIMENSIONS.map(dim => {
                const d = results.by_dimension?.[dim];
                if (!d) return null;
                return (
                  <div key={dim} className={`p-3 rounded-lg border ${DIM_COLORS[dim]}`} data-testid={`pw-dim-${dim}-${mode}`}>
                    <div className="text-xs font-medium mb-1 capitalize">{dim}</div>
                    <div className="text-2xl font-bold font-mono">{d.majority.rate}%</div>
                    <div className="text-[10px] text-muted-foreground">
                      {d.majority.agree}/{d.majority.total} pairs
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Per-dimension per-model */}
          <div className="border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
              <BarChart3 className="h-4 w-4" /> Model Agreement by Dimension
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-xs" data-testid={`pw-model-dim-table-${mode}`}>
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 px-2">Model</th>
                    {DIMENSIONS.map(d => <th key={d} className="text-center py-2 px-2 capitalize">{d}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const allModels = new Set();
                    Object.values(results.by_dimension || {}).forEach(d =>
                      Object.keys(d.by_model || {}).forEach(m => allModels.add(m))
                    );
                    return [...allModels].map(mk => {
                      const safeMk = safeTestId(mk);
                      return (
                        <tr key={mk} className="border-b border-border/30">
                          <td className="py-2 px-2 font-medium" data-testid={`pw-model-name-${mode}-${safeMk}`}>{shortModel(mk)}</td>
                          {DIMENSIONS.map(dim => {
                            const s = results.by_dimension?.[dim]?.by_model?.[mk];
                            if (!s) return <td key={dim} className="text-center text-muted-foreground">—</td>;
                            const clr = s.rate >= 70 ? "text-green-600" : s.rate >= 50 ? "text-amber-600" : "text-red-600";
                            return <td key={dim} className={`text-center font-mono ${clr}`} data-testid={`pw-model-rate-${mode}-${safeMk}-${dim}`}>{s.rate}%</td>;
                          })}
                        </tr>
                      );
                    });
                  })()}
                </tbody>
              </table>
            </div>
          </div>

          {/* Inter-model agreement */}
          {results.inter_model && Object.keys(results.inter_model).length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid={`pw-inter-model-${mode}`}>
              <h2 className="text-sm font-medium mb-3">Inter-Model Agreement</h2>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(results.inter_model).map(([k, s], i) => {
                  const [m1, m2] = k.split(" vs ");
                  return <Badge key={k} rate={s.rate} label={`${shortModel(m1)} vs ${shortModel(m2)}`} sub={`${s.agree}/${s.total}`} testId={`pw-inter-model-badge-${mode}-${i}`} />;
                })}
              </div>
            </div>
          )}

          {/* Sample pairs */}
          {results.samples?.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden" data-testid={`pw-samples-table-${mode}`}>
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h2 className="text-xs font-medium">Sample Pairs</h2>
              </div>
              <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-background">
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-center px-1.5 py-1.5 font-medium">Dim</th>
                      <th className="text-left px-2 py-1.5 font-medium">Paper 1</th>
                      <th className="text-left px-2 py-1.5 font-medium">Paper 2</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Gap</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Models</th>
                      <th className="text-center px-1.5 py-1.5 font-medium">Majority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.samples.map((s, i) => (
                      <tr key={i} className="border-b border-border/20 hover:bg-secondary/10">
                        <td className={`text-center px-1.5 py-1 capitalize text-[10px] ${DIM_COLORS[s.dimension]?.split(' ')[0] || ''}`}>
                          {s.dimension?.substring(0, 4)}
                        </td>
                        <td className="px-2 py-1 max-w-[180px] truncate" title={s.paper1_title}>
                          <span className={s.human_winner === "paper1" ? "font-semibold" : ""}>{s.paper1_title}</span>
                          <span className="text-[9px] text-muted-foreground ml-1">({s.human_score1})</span>
                        </td>
                        <td className="px-2 py-1 max-w-[180px] truncate" title={s.paper2_title}>
                          <span className={s.human_winner === "paper2" ? "font-semibold" : ""}>{s.paper2_title}</span>
                          <span className="text-[9px] text-muted-foreground ml-1">({s.human_score2})</span>
                        </td>
                        <td className="text-center px-1.5 py-1 font-mono">{s.score_gap}</td>
                        <td className="text-center px-1.5 py-1 font-mono text-[10px]">
                          <span className={s.models_agree >= 2 ? "text-green-600" : "text-red-500"}>
                            {s.models_agree}/{s.models_total}
                          </span>
                        </td>
                        <td className="text-center px-1.5 py-1">
                          {s.majority_agree === true && <CheckCircle className="h-3.5 w-3.5 text-green-600 inline" />}
                          {s.majority_agree === false && <XCircle className="h-3.5 w-3.5 text-red-500 inline" />}
                          {s.majority_agree === null && <span className="text-muted-foreground">—</span>}
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
        <div className="border border-border rounded-lg p-8 text-center" data-testid={`pw-empty-state-${mode}`}>
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No pairwise comparisons yet. Use admin controls to fetch and evaluate.</p>
        </div>
      ) : null}

      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid={`pw-methodology-${mode}`}>
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Source:</strong> SciPost Physics — open peer review with structured referee ratings per dimension.</li>
          <li><strong>Pair creation:</strong> For each dimension, papers are paired randomly. The human winner is the paper with the higher average referee rating on that dimension. Near-ties are excluded.</li>
          <li><strong>AI evaluation:</strong> Each pair evaluated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro with a dimension-specific prompt. Presentation order randomized per model.</li>
          <li><strong>Content:</strong> {mode === "extract" ? "PDFs are downloaded and key sections are extracted (intro/method/results/conclusion)." : "Abstract-only comparison (no PDF extraction)."}</li>
          <li><strong>Agreement:</strong> Majority vote and per-model agreement with the human verdict, broken down by dimension and score gap.</li>
        </ul>
      </div>
    </div>
  );
}
