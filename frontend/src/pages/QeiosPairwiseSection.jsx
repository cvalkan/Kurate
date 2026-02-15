import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Play, Square, Loader2, AlertCircle, Layers, Users,
  BarChart3, GitCompare, FileText, X, CheckCircle, XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const MODE_LABELS = { abstract: "Abstract", extract: "Extract", abstract_plus_summary: "Abstract + Summary" };
const MODEL_COLORS = ["#3b82f6", "#f59e0b", "#8b5cf6"];
const DOMAIN_COLORS = {
  "Social Sciences": "#3b82f6", "Physical Sciences": "#8b5cf6",
  "Health Sciences": "#22c55e", "Life Sciences": "#f59e0b", "Unknown": "#94a3b8",
};
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

export default function QeiosPairwiseSection() {
  const [dataByMode, setDataByMode] = useState({});
  const [statusByMode, setStatusByMode] = useState({});
  const [numPairs, setNumPairs] = useState(20);
  const [parallelAgents, setParallelAgents] = useState(5);
  const [isStarting, setIsStarting] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const MODES = [
    { id: "abstract", statusUrl: "/api/qeios/pairwise/status", resultsUrl: "/api/qeios/pairwise/results" },
    { id: "extract", statusUrl: "/api/qeios/pairwise-extract/status", resultsUrl: "/api/qeios/pairwise-extract/results" },
    { id: "abstract_plus_summary", statusUrl: "/api/qeios/pairwise-summary/status", resultsUrl: "/api/qeios/pairwise-summary/results" },
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
    const iv = setInterval(fetchAll, isStarting ? 1000 : 2000);
    return () => clearInterval(iv);
  }, [statusByMode, isStarting, fetchAll]);

  const fetchAndRun = async () => {
    setIsStarting(true);
    try {
      const res = await axios.post(`${API}/api/qeios/pairwise/fetch-and-run`,
        { num_pairs: numPairs, parallel_agents: parallelAgents },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success("Synced run started");
      else if (res.data.status === "already_running") { toast.warning("Already running"); setIsStarting(false); }
      else { toast.error(res.data.message || "Error"); setIsStarting(false); }
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); setIsStarting(false); }
  };

  const stop = async () => {
    try {
      await axios.post(`${API}/api/qeios/pairwise/stop`, {}, { headers: adminHeaders() });
      toast.info("Stopped"); setIsStarting(false); fetchAll();
    } catch { toast.error("Failed to stop"); }
  };

  const running = Object.values(statusByMode).some(s => s?.fetching || s?.running) || isStarting;
  const availableModes = Object.keys(dataByMode);
  const hasData = availableModes.length > 0;

  // Primary mode: prefer abstract_plus_summary (richest), then extract, fallback to abstract
  const primaryMode = availableModes.includes("abstract_plus_summary") ? "abstract_plus_summary" :
    availableModes.includes("extract") ? "extract" : availableModes[0];
  const primaryData = dataByMode[primaryMode];

  // Collect all models across modes
  const allModels = new Set();
  availableModes.forEach(mode => {
    Object.keys(dataByMode[mode]?.by_model_overall || {}).forEach(mk => allModels.add(mk));
  });
  const modelList = [...allModels].sort();

  // Collect all domains from primary data
  const domainList = primaryData ? Object.keys(primaryData.by_domain || {}).filter(d => d !== "Unknown") : [];

  // Chart data: agreement by input format
  const agreementChartData = availableModes.map(mode => {
    const r = dataByMode[mode];
    return { name: MODE_LABELS[mode] || mode, "AI vs Expert": r.overall_majority.rate };
  });

  // Chart data: per-model by mode
  const modelChartData = availableModes.map(mode => {
    const row = { name: MODE_LABELS[mode] || mode };
    modelList.forEach(mk => {
      const s = dataByMode[mode]?.by_model_overall?.[mk];
      if (s) row[shortModel(mk)] = s.rate;
    });
    return row;
  });

  // Prompts from whichever mode has data
  const prompts = primaryData?.prompts;

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
                {isStarting && !statusByMode.abstract?.fetching ? "Starting synced run..." :
                  statusByMode.abstract?.progress?.phase === "scanning" ? "Scanning Crossref..." :
                  statusByMode.abstract?.progress?.phase === "fetching" ? `Fetching pairs... ${statusByMode.abstract?.progress?.pairs_fetched || 0}` :
                  `Evaluating: ${statusByMode.abstract?.progress?.pairs_done || 0}/${statusByMode.abstract?.progress?.target || '?'}`}
              </span>
            </div>
          )}
        </div>
      )}

      {!hasData && (
        <div className="border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No Qeios pairwise data yet.</p>
        </div>
      )}

      {hasData && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center" data-testid="pw-qeios-summary">
            <div className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">Domains</div>
              <div className="font-semibold text-base">{domainList.length}</div>
              <div className="text-[10px] text-muted-foreground">{domainList.join(", ")}</div>
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
          <div className="border border-border rounded-lg p-4" data-testid="pw-qeios-agreement-chart">
            <h2 className="text-sm font-medium mb-1 flex items-center gap-1.5">
              <GitCompare className="h-4 w-4" /> Majority Agreement by Input Format
            </h2>
            <p className="text-[10px] text-muted-foreground mb-3">AI 3-model majority vote vs human expert verdict (all domains combined)</p>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={agreementChartData} barSize={40}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                <Tooltip content={<Tip />} />
                <Bar dataKey="AI vs Expert" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Per-domain breakdown cards — per mode */}
          {availableModes.map(mode => {
            const modeData = dataByMode[mode];
            const modeDomains = modeData?.by_domain ? Object.keys(modeData.by_domain).filter(d => d !== "Unknown") : [];
            if (!modeDomains.length) return null;
            return (
              <div key={`dom-${mode}`} className="border border-border rounded-lg p-4" data-testid={`pw-qeios-domains-${mode}`}>
                <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                  <Layers className="h-4 w-4" /> Agreement by Domain ({MODE_LABELS[mode]})
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {modeDomains.map(dom => {
                    const d = modeData.by_domain[dom];
                    if (!d) return null;
                    const rate = d.majority.rate;
                    const color = rate >= 70 ? "text-green-700" : rate >= 50 ? "text-amber-700" : "text-red-700";
                    return (
                      <div key={dom} className="p-3 border border-border rounded-lg text-center">
                        <div className="text-[10px] text-muted-foreground mb-1">{dom}</div>
                        <div className={`text-xl font-bold font-mono ${color}`}>{rate}%</div>
                        <div className="text-[10px] text-muted-foreground">{d.majority.agree}/{d.majority.total}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Per-model agreement chart */}
          {modelList.length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid="pw-qeios-model-chart">
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

          {/* Model x Domain table — per mode */}
          {availableModes.map(mode => {
            const modeData = dataByMode[mode];
            const modeDomains = modeData?.by_domain ? Object.keys(modeData.by_domain).filter(d => d !== "Unknown") : [];
            if (!modeDomains.length) return null;
            return (
              <div key={`tbl-${mode}`} className="border border-border rounded-lg p-4" data-testid={`pw-qeios-domain-table-${mode}`}>
                <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                  <BarChart3 className="h-4 w-4" /> Model x Domain ({MODE_LABELS[mode]})
                </h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="text-left py-2 px-2">Model</th>
                        {modeDomains.map(d => <th key={d} className="text-center py-2 px-2">{d}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {modelList.map(mk => (
                        <tr key={mk} className="border-b border-border/30">
                          <td className="py-2 px-2 font-medium">{shortModel(mk)}</td>
                          {modeDomains.map(dom => {
                            const s = modeData.by_domain[dom]?.by_model?.[mk];
                            if (!s) return <td key={dom} className="text-center text-muted-foreground">&mdash;</td>;
                            const clr = s.rate >= 70 ? "text-green-600" : s.rate >= 50 ? "text-amber-600" : "text-red-600";
                            return <td key={dom} className={`text-center font-mono ${clr}`}>{s.rate}%</td>;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}

          {/* Score gap breakdown — per mode */}
          {availableModes.map(mode => {
            const modeData = dataByMode[mode];
            if (!modeData?.by_gap || !Object.values(modeData.by_gap).some(g => g.total > 0)) return null;
            return (
              <div key={`gap-${mode}`} className="border border-border rounded-lg p-4" data-testid={`pw-qeios-gap-${mode}`}>
                <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                  <BarChart3 className="h-4 w-4" /> By Score Gap ({MODE_LABELS[mode]})
                </h2>
                {GAP_LABELS.map(gap => {
                  const g = modeData.by_gap?.[gap.key];
                  if (!g || g.total === 0) return null;
                  return <HBar key={gap.key} rate={g.rate} label={gap.label} sub={`${g.agree}/${g.total}`} />;
                })}
              </div>
            );
          })}

          {/* Inter-model agreement */}
          {primaryData?.inter_model && Object.keys(primaryData.inter_model).length > 0 && (
            <div className="border border-border rounded-lg p-4" data-testid="pw-qeios-inter">
              <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
                <GitCompare className="h-4 w-4" /> Inter-Model Agreement ({MODE_LABELS[primaryMode]})
              </h2>
              {Object.entries(primaryData.inter_model).map(([k, s]) => {
                const [m1, m2] = k.split(" vs ");
                return <HBar key={k} rate={s.rate} label={`${shortModel(m1)} vs ${shortModel(m2)}`} sub={`${s.agree}/${s.total}`} color="bg-purple-400/70" />;
              })}
            </div>
          )}

          {/* Sample pairs table */}
          {primaryData?.samples?.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-qeios-samples">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h2 className="text-xs font-medium">Sample Pairs ({MODE_LABELS[primaryMode]})</h2>
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
                    {primaryData.samples.map((s, i) => (
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
              <li><strong>Source:</strong> Qeios &mdash; open peer review with star ratings. One pair per reviewer (no ties).</li>
              <li><strong>Pair sync:</strong> Abstract and Extract modes use identical paper pairs.</li>
              <li><strong>AI evaluation:</strong> Each pair evaluated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.</li>
              <li><strong>Agreement:</strong> Majority vote and per-model agreement with the human verdict.</li>
            </ul>
          </div>
        </>
      )}

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
