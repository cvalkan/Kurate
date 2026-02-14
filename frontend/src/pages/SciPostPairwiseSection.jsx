import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Play, Square, Loader2, AlertCircle, Layers,
  BarChart3, GitCompare,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const DIMENSIONS = ["validity", "significance", "originality", "clarity"];
const DIM_COLORS = {
  validity: { text: "text-blue-700", bg: "bg-blue-50", bar: "bg-blue-400/70", border: "border-blue-200" },
  significance: { text: "text-purple-700", bg: "bg-purple-50", bar: "bg-purple-400/70", border: "border-purple-200" },
  originality: { text: "text-amber-700", bg: "bg-amber-50", bar: "bg-amber-400/70", border: "border-amber-200" },
  clarity: { text: "text-green-700", bg: "bg-green-50", bar: "bg-green-400/70", border: "border-green-200" },
};

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

function aggregateGapStats(results) {
  const totals = { small: { agree: 0, total: 0 }, medium: { agree: 0, total: 0 }, large: { agree: 0, total: 0 } };
  Object.values(results?.by_dimension || {}).forEach(dim => {
    const gaps = dim.by_gap || {};
    Object.keys(totals).forEach(k => {
      if (gaps[k]) { totals[k].agree += gaps[k].agree || 0; totals[k].total += gaps[k].total || 0; }
    });
  });
  Object.keys(totals).forEach(k => {
    const t = totals[k].total || 0, a = totals[k].agree || 0;
    totals[k].rate = t ? Math.round((a / t) * 1000) / 10 : 0;
  });
  return totals;
}

const GAP_LABELS = [
  { key: "small", label: "Small (\u22641.0)" },
  { key: "medium", label: "Medium (1.0\u20132.0)" },
  { key: "large", label: "Large (>2.0)" },
];

function ModeColumn({ mode, modeLabel, results, status }) {
  if (!results && (!status || status.total_pairs === 0)) {
    return (
      <div className="text-center py-8">
        <AlertCircle className="h-6 w-6 mx-auto mb-2 text-muted-foreground/30" />
        <p className="text-xs text-muted-foreground">No {modeLabel} data yet</p>
      </div>
    );
  }

  const gapStats = results ? aggregateGapStats(results) : null;

  return (
    <div className="space-y-4">
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
          {/* Overall */}
          <div className="p-3 rounded-lg border border-border bg-secondary/5" data-testid={`pw-scipost-overall-${mode}`}>
            <div className="text-[10px] text-muted-foreground mb-1">Majority vs Human (all dims)</div>
            <div className={`text-2xl font-bold font-mono ${results.overall_majority.rate >= 60 ? "text-green-700" : "text-amber-700"}`}>
              {results.overall_majority.rate}%
            </div>
            <div className="text-[10px] text-muted-foreground">{results.overall_majority.agree}/{results.overall_majority.total}</div>
          </div>

          {/* Per dimension */}
          <div className="space-y-2" data-testid={`pw-scipost-dims-${mode}`}>
            <div className="text-xs font-medium">By Dimension</div>
            {DIMENSIONS.map(dim => {
              const d = results.by_dimension?.[dim];
              if (!d) return null;
              return <HBar key={dim} rate={d.majority.rate} label={dim.charAt(0).toUpperCase() + dim.slice(1)} sub={`${d.majority.agree}/${d.majority.total}`} color={DIM_COLORS[dim]?.bar} />;
            })}
          </div>

          {/* Per model */}
          {results.by_model_overall && (
            <div className="space-y-2" data-testid={`pw-scipost-models-${mode}`}>
              <div className="text-xs font-medium">Model Agreement</div>
              {Object.entries(results.by_model_overall)
                .sort((a, b) => b[1].rate - a[1].rate)
                .map(([mk, s]) => (
                  <HBar key={mk} rate={s.rate} label={shortModel(mk)} sub={`${s.agree}/${s.total}`} />
                ))}
            </div>
          )}

          {/* Gap */}
          {gapStats && Object.values(gapStats).some(g => g.total > 0) && (
            <div className="space-y-2" data-testid={`pw-scipost-gap-${mode}`}>
              <div className="text-xs font-medium">By Score Gap</div>
              {GAP_LABELS.map(gap => {
                const g = gapStats[gap.key];
                if (!g || g.total === 0) return null;
                return <HBar key={gap.key} rate={g.rate} label={gap.label} sub={`${g.agree}/${g.total}`} />;
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function SciPostPairwiseSection() {
  const [absStatus, setAbsStatus] = useState(null);
  const [absResults, setAbsResults] = useState(null);
  const [extStatus, setExtStatus] = useState(null);
  const [extResults, setExtResults] = useState(null);
  const [numPairs, setNumPairs] = useState(8);
  const [parallelAgents, setParallelAgents] = useState(5);
  const [isStarting, setIsStarting] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchAll = useCallback(async () => {
    try {
      const [as, ar, es, er] = await Promise.all([
        axios.get(`${API}/api/scipost/pairwise/status`),
        axios.get(`${API}/api/scipost/pairwise/results`),
        axios.get(`${API}/api/scipost/pairwise-extract/status`),
        axios.get(`${API}/api/scipost/pairwise-extract/results`),
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
      const res = await axios.post(`${API}/api/scipost/pairwise/fetch-and-run`,
        { num_pairs_per_dim: numPairs, dimensions: DIMENSIONS, parallel_agents: parallelAgents },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success(`Synced run started`);
      else if (res.data.status === "already_running") { toast.warning("Already running"); setIsStarting(false); }
      else { toast.error(res.data.message || "Error"); setIsStarting(false); }
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); setIsStarting(false); }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/scipost/pairwise/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped"); setIsStarting(false); fetchAll();
    } catch (e) { toast.error("Failed to stop"); }
  };

  const running = absStatus?.fetching || absStatus?.running || isStarting;

  // Model x Dimension table - combine both modes
  const dimTable = absResults || extResults;

  return (
    <div className="space-y-5">
      {/* Admin */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 bg-secondary/10 space-y-3" data-testid="pw-scipost-admin">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Pairs/dim:</label>
              <Input type="number" min={3} max={50} value={numPairs}
                onChange={e => setNumPairs(parseInt(e.target.value) || 8)}
                className="w-16 h-8 text-xs" disabled={running} data-testid="pw-scipost-num-input" />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Agents:</label>
              <Input type="number" min={1} max={15} value={parallelAgents}
                onChange={e => setParallelAgents(Math.min(15, Math.max(1, parseInt(e.target.value) || 5)))}
                className="w-16 h-8 text-xs" disabled={running} data-testid="pw-scipost-agents-input" />
            </div>
            {!running ? (
              <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid="pw-scipost-run-btn">
                <Play className="h-3.5 w-3.5" /> Fetch & Evaluate
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5" data-testid="pw-scipost-stop-btn">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>
          {running && (
            <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2" data-testid="pw-scipost-progress">
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              <span className="font-medium">
                {isStarting ? "Starting..." : `Evaluating: ${absStatus?.progress?.pairs_done || 0}/${absStatus?.progress?.target || '?'}`}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Side-by-side Abstract | Extract */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="pw-scipost-comparison">
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

      {/* Model x Dimension table (shared) */}
      {dimTable?.by_dimension && (
        <div className="border border-border rounded-lg p-4">
          <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
            <BarChart3 className="h-4 w-4" /> Model x Dimension Agreement
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="pw-scipost-dim-table">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-2 px-2">Model</th>
                  {DIMENSIONS.map(d => <th key={d} className="text-center py-2 px-2 capitalize">{d}</th>)}
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const allModels = new Set();
                  Object.values(dimTable.by_dimension || {}).forEach(d =>
                    Object.keys(d.by_model || {}).forEach(m => allModels.add(m))
                  );
                  return [...allModels].map(mk => (
                    <tr key={mk} className="border-b border-border/30">
                      <td className="py-2 px-2 font-medium">{shortModel(mk)}</td>
                      {DIMENSIONS.map(dim => {
                        const s = dimTable.by_dimension?.[dim]?.by_model?.[mk];
                        if (!s) return <td key={dim} className="text-center text-muted-foreground">\u2014</td>;
                        const clr = s.rate >= 70 ? "text-green-600" : s.rate >= 50 ? "text-amber-600" : "text-red-600";
                        return <td key={dim} className={`text-center font-mono ${clr}`}>{s.rate}%</td>;
                      })}
                    </tr>
                  ));
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="pw-scipost-methodology">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Source:</strong> SciPost — peer-reviewed physics papers with per-dimension expert ratings.</li>
          <li><strong>Pair sync:</strong> Abstract and Extract modes use identical paper pairs.</li>
          <li><strong>AI evaluation:</strong> Each pair rated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro on 4 dimensions.</li>
          <li><strong>Agreement:</strong> Majority vote and per-model agreement with the human verdict, by dimension and score gap.</li>
        </ul>
      </div>
    </div>
  );
}
