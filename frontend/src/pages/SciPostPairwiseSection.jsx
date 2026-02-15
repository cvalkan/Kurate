import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Play, Square, Loader2, AlertCircle, Layers, Users,
  BarChart3, GitCompare,
} from "lucide-react";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const DIMENSIONS = ["validity", "significance", "originality", "clarity"];
const DIM_COLORS = {
  validity: "#3b82f6", significance: "#8b5cf6",
  originality: "#f59e0b", clarity: "#22c55e",
};
const MODE_LABELS = { abstract: "Abstract", extract: "Extract", abstract_plus_summary: "Abstract + Summary" };
const MODEL_COLORS = ["#3b82f6", "#f59e0b", "#8b5cf6"];

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m;
}

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
      <div className="font-medium mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill || p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono font-medium">{typeof p.value === "number" ? `${p.value}%` : p.value}</span>
        </div>
      ))}
    </div>
  );
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

export default function SciPostPairwiseSection() {
  const [dataByMode, setDataByMode] = useState({});
  const [statusByMode, setStatusByMode] = useState({});
  const [numPairs, setNumPairs] = useState(8);
  const [parallelAgents, setParallelAgents] = useState(5);
  const [isStarting, setIsStarting] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const MODES = [
    { id: "abstract", statusUrl: "/api/scipost/pairwise/status", resultsUrl: "/api/scipost/pairwise/results" },
    { id: "extract", statusUrl: "/api/scipost/pairwise-extract/status", resultsUrl: "/api/scipost/pairwise-extract/results" },
    { id: "abstract_plus_summary", statusUrl: "/api/scipost/pairwise-summary/status", resultsUrl: "/api/scipost/pairwise-summary/results" },
  ];

  const fetchAll = useCallback(async () => {
    try {
      const responses = await Promise.all(
        MODES.flatMap(m => [
          axios.get(`${API}${m.statusUrl}`).catch(() => ({ data: {} })),
          axios.get(`${API}${m.resultsUrl}`).catch(() => ({ data: {} })),
        ])
      );
      const newData = {};
      const newStatus = {};
      MODES.forEach((m, i) => {
        newStatus[m.id] = responses[i * 2].data;
        if (responses[i * 2 + 1].data.status === "ok") newData[m.id] = responses[i * 2 + 1].data;
      });
      setDataByMode(newData);
      setStatusByMode(newStatus);
      if (newStatus.abstract?.fetching || newStatus.abstract?.running) setIsStarting(false);
    } catch (e) { console.error(e); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    const anyRunning = Object.values(statusByMode).some(s => s?.fetching || s?.running);
    if (!anyRunning && !isStarting) return;
    const iv = setInterval(fetchAll, 3000);
    return () => clearInterval(iv);
  }, [statusByMode, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/scipost/pairwise/fetch-and-run`,
        { num_pairs_per_dim: numPairs, dimensions: DIMENSIONS, parallel_agents: parallelAgents },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success("Synced run started");
      else { toast.warning(res.data.message || res.data.status); setIsStarting(false); }
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); setIsStarting(false); }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/scipost/pairwise/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped"); setIsStarting(false); fetchAll();
    } catch { toast.error("Failed to stop"); }
  };

  const running = Object.values(statusByMode).some(s => s?.fetching || s?.running) || isStarting;
  const availableModes = Object.keys(dataByMode);
  const hasData = availableModes.length > 0;

  // Build aggregate agreement chart data (by mode)
  const agreementChartData = availableModes.map(mode => {
    const r = dataByMode[mode];
    return { name: MODE_LABELS[mode] || mode, "AI vs Expert": r.overall_majority.rate };
  });

  // Per-dimension chart data (best mode's data)
  const primaryMode = availableModes.includes("abstract_plus_summary") ? "abstract_plus_summary" : availableModes[0];
  const primaryData = dataByMode[primaryMode];

  // Per-model chart: individual expert agreement by mode
  const allModels = new Set();
  availableModes.forEach(mode => {
    Object.keys(dataByMode[mode]?.by_model_overall || {}).forEach(mk => allModels.add(mk));
  });
  const modelList = [...allModels].sort();

  const modelChartData = availableModes.map(mode => {
    const row = { name: MODE_LABELS[mode] || mode };
    modelList.forEach(mk => {
      const s = dataByMode[mode]?.by_model_overall?.[mk];
      if (s) row[shortModel(mk)] = s.rate;
    });
    return row;
  });

  return (
    <div className="space-y-5">
      {/* Admin controls */}
      {isAdmin && (
        <div className="border border-border rounded-lg p-4 bg-secondary/10 space-y-3" data-testid="pw-scipost-admin">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Pairs/dim:</label>
              <Input type="number" min={3} max={50} value={numPairs}
                onChange={e => setNumPairs(parseInt(e.target.value) || 8)}
                className="w-16 h-8 text-xs" disabled={running} />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Agents:</label>
              <Input type="number" min={1} max={15} value={parallelAgents}
                onChange={e => setParallelAgents(Math.min(15, Math.max(1, parseInt(e.target.value) || 5)))}
                className="w-16 h-8 text-xs" disabled={running} />
            </div>
            {!running ? (
              <Button size="sm" onClick={fetchAndRun} className="gap-1.5" data-testid="pw-scipost-run-btn">
                <Play className="h-3.5 w-3.5" /> Fetch & Evaluate
              </Button>
            ) : (
              <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            )}
          </div>
          {running && (
            <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2">
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              <span className="font-medium">Evaluating...</span>
            </div>
          )}
        </div>
      )}

      {!hasData && (
        <div className="border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No SciPost pairwise data yet.</p>
        </div>
      )}

      {hasData && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
            <div className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">Dimensions</div>
              <div className="font-semibold text-base">4</div>
              <div className="text-[10px] text-muted-foreground">validity, significance, originality, clarity</div>
            </div>
            <div className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">Input Formats</div>
              <div className="font-semibold text-base">{availableModes.length}</div>
              <div className="text-[10px] text-muted-foreground">{availableModes.map(m => MODE_LABELS[m]).join(", ")}</div>
            </div>
            <div className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">Total Pairs</div>
              <div className="font-semibold text-base">{primaryData?.total_pairs || 0}</div>
              <div className="text-[10px] text-muted-foreground">per mode</div>
            </div>
            <div className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">Models</div>
              <div className="font-semibold text-base">{modelList.length}</div>
              <div className="text-[10px] text-muted-foreground">{modelList.map(shortModel).join(", ")}</div>
            </div>
          </div>

          {/* Main agreement chart */}
          <div className="border border-border rounded-lg p-4" data-testid="pw-scipost-agreement-chart">
            <h2 className="text-sm font-medium mb-1 flex items-center gap-1.5">
              <GitCompare className="h-4 w-4" /> Majority Agreement by Input Format
            </h2>
            <p className="text-[10px] text-muted-foreground mb-3">AI 3-model majority vote vs human expert verdict (all dimensions combined)</p>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={agreementChartData} barSize={40}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                <Tooltip content={<Tip />} />
                <Bar dataKey="AI vs Expert" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Per-dimension breakdown */}
          {primaryData?.by_dimension && (
            <div className="border border-border rounded-lg p-4" data-testid="pw-scipost-dimensions">
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <Layers className="h-4 w-4" /> Agreement by Dimension ({MODE_LABELS[primaryMode]})
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {DIMENSIONS.map(dim => {
                  const d = primaryData.by_dimension[dim];
                  if (!d) return null;
                  const rate = d.majority.rate;
                  const color = rate >= 70 ? "text-green-700" : rate >= 50 ? "text-amber-700" : "text-red-700";
                  return (
                    <div key={dim} className="p-3 border border-border rounded-lg text-center" data-testid={`dim-${dim}`}>
                      <div className="text-[10px] text-muted-foreground capitalize mb-1">{dim}</div>
                      <div className={`text-xl font-bold font-mono ${color}`}>{rate}%</div>
                      <div className="text-[10px] text-muted-foreground">{d.majority.agree}/{d.majority.total}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Per-model agreement chart */}
          {modelList.length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid="pw-scipost-model-chart">
              <h2 className="text-sm font-medium mb-1 flex items-center gap-1.5">
                <Users className="h-4 w-4" /> Per-Model Agreement with Individual Expert
              </h2>
              <p className="text-[10px] text-muted-foreground mb-3">How each LLM performs by input format</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={modelChartData} barGap={2}>
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                  <Tooltip content={<Tip />} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  {modelList.map((mk, i) => (
                    <Bar key={mk} dataKey={shortModel(mk)} fill={MODEL_COLORS[i % MODEL_COLORS.length]} radius={[3, 3, 0, 0]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Model x Dimension table */}
          {primaryData?.by_dimension && (
            <div className="border border-border rounded-lg p-4" data-testid="pw-scipost-dim-table">
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" /> Model x Dimension ({MODE_LABELS[primaryMode]})
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 px-2">Model</th>
                      {DIMENSIONS.map(d => <th key={d} className="text-center py-2 px-2 capitalize">{d}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {modelList.map(mk => (
                      <tr key={mk} className="border-b border-border/30">
                        <td className="py-2 px-2 font-medium">{shortModel(mk)}</td>
                        {DIMENSIONS.map(dim => {
                          const s = primaryData.by_dimension[dim]?.by_model?.[mk];
                          if (!s) return <td key={dim} className="text-center text-muted-foreground">&mdash;</td>;
                          const clr = s.rate >= 70 ? "text-green-600" : s.rate >= 50 ? "text-amber-600" : "text-red-600";
                          return <td key={dim} className={`text-center font-mono ${clr}`}>{s.rate}%</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Score gap breakdown */}
          {primaryData?.by_dimension && (() => {
            const totals = { small: { agree: 0, total: 0 }, medium: { agree: 0, total: 0 }, large: { agree: 0, total: 0 } };
            Object.values(primaryData.by_dimension).forEach(dim => {
              Object.entries(dim.by_gap || {}).forEach(([k, v]) => {
                if (totals[k]) { totals[k].agree += v.agree || 0; totals[k].total += v.total || 0; }
              });
            });
            const hasGap = Object.values(totals).some(g => g.total > 0);
            if (!hasGap) return null;
            return (
              <div className="border border-border rounded-lg p-4" data-testid="pw-scipost-gap">
                <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                  <BarChart3 className="h-4 w-4" /> By Score Gap ({MODE_LABELS[primaryMode]})
                </h2>
                {[
                  { key: "small", label: "Small (\u22641.0)" },
                  { key: "medium", label: "Medium (1.0\u20132.0)" },
                  { key: "large", label: "Large (>2.0)" },
                ].map(gap => {
                  const g = totals[gap.key];
                  if (!g || g.total === 0) return null;
                  const rate = Math.round(g.agree / g.total * 1000) / 10;
                  return <HBar key={gap.key} rate={rate} label={gap.label} sub={`${g.agree}/${g.total}`} />;
                })}
              </div>
            );
          })()}

          {/* Methodology */}
          <div className="border border-border rounded-lg p-4 bg-secondary/10">
            <h3 className="text-sm font-medium mb-2">Methodology</h3>
            <ul className="text-xs text-muted-foreground space-y-1">
              <li><strong>Source:</strong> SciPost &mdash; peer-reviewed physics papers with per-dimension expert ratings (1&ndash;6 scale).</li>
              <li><strong>Dimensions:</strong> Validity, Significance, Originality, Clarity &mdash; each evaluated independently.</li>
              <li><strong>AI evaluation:</strong> Each pair rated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.</li>
              <li><strong>Agreement:</strong> Majority vote and per-model agreement with the human expert verdict.</li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
