import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Scale, BarChart3, AlertCircle, Play, Info, Loader2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;
function adminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

const MODE_ORDER = ["abstract", "extract", "full_pdf"];
const MODE_LABELS = { abstract: "Abstract", extract: "Extract", full_pdf: "Full PDF" };

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m;
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
      <div className="font-medium mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill || p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono font-medium">{p.value}%</span>
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

export default function PairwiseAgreementSection({ datasetId, datasetName }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [runningMode, setRunningMode] = useState(null);
  const [tournamentStatus, setTournamentStatus] = useState(null);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchData = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([
        axios.get(`${API}/api/validation/cross-mode-agreement`, { params: { dataset_id: datasetId } }),
        axios.get(`${API}/api/validation/status`, { params: { dataset_id: datasetId } }),
      ]);
      if (r.data.status === "ok") setData(r.data);
      else if (r.data.status === "insufficient_modes") setData({ status: "insufficient", available: r.data.available || [] });
      setTournamentStatus(s.data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [datasetId]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    if (!tournamentStatus?.tournament_running && !runningMode) return;
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, [tournamentStatus?.tournament_running, runningMode, fetchData]);

  const runTargeted = async (mode) => {
    setRunningMode(mode);
    try {
      const res = await axios.post(`${API}/api/validation/run-targeted-pairwise`,
        { dataset_id: datasetId, content_mode: mode, parallel: 30 },
        { headers: adminHeaders() });
      if (res.data.status === "started") toast.success(`Running ${MODE_LABELS[mode]}: ${res.data.missing} pairs`);
      else if (res.data.status === "complete") { toast.info(res.data.message); setRunningMode(null); }
      else if (res.data.status === "already_running") { toast.warning("Already running"); setRunningMode(null); }
      else { toast.error(res.data.message || "Error"); setRunningMode(null); }
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); setRunningMode(null); }
  };

  if (loading) return <div className="text-xs text-muted-foreground py-6 text-center">Loading...</div>;

  const isRunning = tournamentStatus?.tournament_running || !!runningMode;

  if (!data || data.status === "insufficient" || !data.common_pairs) {
    const available = data?.available || [];
    const missing = MODE_ORDER.filter(m => !available.includes(m));
    return (
      <div className="space-y-4">
        <div className="border border-border rounded-lg p-6 text-center" data-testid="pw-agreement-empty">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground mb-2">Need tournament data in at least 2 input formats to compare.</p>
          <p className="text-xs text-muted-foreground mb-4">Available: {available.length > 0 ? available.map(m => MODE_LABELS[m]).join(", ") : "none"}.</p>
          {isAdmin && missing.length > 0 && (
            <div className="flex flex-wrap gap-2 justify-center">
              {missing.map(m => (
                <Button key={m} size="sm" className="gap-1.5 text-xs" onClick={() => runTargeted(m)} disabled={isRunning} data-testid={`run-targeted-${m}`}>
                  <Play className="h-3 w-3" /> Run {MODE_LABELS[m]}
                </Button>
              ))}
            </div>
          )}
        </div>
        {isRunning && <RunningIndicator runningMode={runningMode} status={tournamentStatus} />}
        <MethodologyNote />
      </div>
    );
  }

  // Sorted modes
  const sortedModes = MODE_ORDER.filter(m => data.modes_compared.includes(m));

  // Main agreement chart data (Abstract, Extract, Full PDF) - includes AI majority if available
  const mainChartData = sortedModes.map(mode => {
    const row = { name: MODE_LABELS[mode], "AI vs Expert": data.by_mode[mode].ai_expert.rate, "AI vs Majority": data.by_mode[mode].ai_majority.rate };
    const aiMaj = data.ai_majority_vs_expert?.[mode];
    if (aiMaj) row["AI Consensus vs Majority"] = aiMaj.ai_majority_vs_expert_majority.rate;
    return row;
  });
  const hasAiMajority = sortedModes.some(m => data.ai_majority_vs_expert?.[m]);

  // Per-model chart data
  const allModels = new Set();
  sortedModes.forEach(m => { Object.keys(data.per_model?.[m] || {}).forEach(mk => allModels.add(mk)); });
  const modelList = [...allModels].sort();

  const modelChartData = sortedModes.map(mode => {
    const row = { name: MODE_LABELS[mode] };
    modelList.forEach(mk => {
      const s = data.per_model?.[mode]?.[mk];
      if (s) row[shortModel(mk)] = s.ai_majority.rate;
    });
    return row;
  });
  const MODEL_COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444"];

  const missingModes = MODE_ORDER.filter(m => !data.modes_compared.includes(m));

  return (
    <div className="space-y-5">
      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
        <div className="p-2 border border-border/50 rounded text-xs" data-testid="pw-common-pairs">
          <div className="text-muted-foreground">Paper Pairs</div>
          <div className="font-semibold text-base">{data.common_pairs}</div>
          <div className="text-[10px] text-muted-foreground">shared across formats</div>
        </div>
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Input Formats</div>
          <div className="font-semibold text-base">{sortedModes.length}</div>
          <div className="text-[10px] text-muted-foreground">{sortedModes.map(m => MODE_LABELS[m]).join(", ")}</div>
        </div>
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Expert-Expert</div>
          <div className="font-semibold text-base text-green-600">{data.expert_expert.rate}%</div>
          <div className="text-[10px] text-muted-foreground">{data.expert_expert.agree}/{data.expert_expert.total}</div>
        </div>
        <div className="p-2 border border-border/50 rounded text-xs">
          <div className="text-muted-foreground">Best AI vs Majority</div>
          <div className="font-semibold text-base text-accent">
            {Math.max(...sortedModes.map(m => data.by_mode[m].ai_majority.rate))}%
          </div>
        </div>
      </div>

      {/* Admin controls */}
      {isAdmin && missingModes.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap border border-border/50 rounded-lg p-3 bg-secondary/10" data-testid="pw-run-controls">
          <span className="text-xs text-muted-foreground">Run missing:</span>
          {missingModes.map(m => (
            <Button key={m} size="sm" variant="outline" className="gap-1.5 text-xs h-7" onClick={() => runTargeted(m)} disabled={isRunning} data-testid={`run-targeted-${m}`}>
              <Play className="h-3 w-3" /> {MODE_LABELS[m]}
            </Button>
          ))}
        </div>
      )}
      {isRunning && <RunningIndicator runningMode={runningMode} status={tournamentStatus} />}

      {/* Agreement by input format chart */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-agreement-chart">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <BarChart3 className="h-3 w-3" /> Agreement with Human Experts by Input Format
          </h3>
          <div className="text-[10px] text-muted-foreground mt-0.5">{data.common_pairs} paper pairs evaluated with each format</div>
        </div>
        <div className="p-3">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={mainChartData} barCategoryGap="20%">
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="AI vs Expert" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              <Bar dataKey="AI vs Majority" fill="#8b5cf6" radius={[3, 3, 0, 0]} />
              {hasAiMajority && <Bar dataKey="AI Consensus vs Majority" fill="#22c55e" radius={[3, 3, 0, 0]} />}
            </BarChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground justify-center">
            <span className="inline-block w-8 h-px bg-green-500" />
            Expert-Expert baseline: {data.expert_expert.rate}%
          </div>
        </div>
      </div>

      {/* Per-model chart */}
      {modelList.length >= 2 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-model-chart">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium flex items-center gap-1.5">
              <Users className="h-3 w-3" /> Per-Model Agreement with Expert Majority
            </h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">How each LLM performs by input format</div>
          </div>
          <div className="p-3">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={modelChartData} barCategoryGap="20%">
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                <Tooltip content={<CustomTooltip />} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {modelList.map((mk, i) => (
                  <Bar key={mk} dataKey={shortModel(mk)} fill={MODEL_COLORS[i % MODEL_COLORS.length]} radius={[3, 3, 0, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Detailed table */}
      <div className="border border-border rounded-lg overflow-hidden" data-testid="pw-agreement-table">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Scale className="h-3 w-3" /> Detailed Agreement Rates ({data.common_pairs} pairs)
          </h3>
        </div>
        <div className="p-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1.5 pr-3 text-muted-foreground font-medium">Input Format</th>
                <th className="text-center py-1.5 px-2 text-muted-foreground font-medium">AI vs Expert</th>
                <th className="text-center py-1.5 px-2 text-muted-foreground font-medium">AI vs Majority</th>
                {hasAiMajority && <th className="text-center py-1.5 px-2 text-muted-foreground font-medium">AI Consensus vs Majority</th>}
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border/50">
                <td className="py-1.5 pr-3 text-muted-foreground italic">Expert-Expert</td>
                <td className="text-center py-1.5 px-2 font-mono font-semibold text-green-600">{data.expert_expert.rate}%</td>
                <td className="text-center py-1.5 px-2 text-[10px] text-muted-foreground">baseline</td>
                {hasAiMajority && <td className="text-center py-1.5 px-2 text-[10px] text-muted-foreground">baseline</td>}
              </tr>
              {sortedModes.map(mode => {
                const s = data.by_mode[mode];
                const aiMaj = data.ai_majority_vs_expert?.[mode];
                const best_ae = Math.max(...sortedModes.map(m => data.by_mode[m].ai_expert.rate));
                const best_am = Math.max(...sortedModes.map(m => data.by_mode[m].ai_majority.rate));
                const ae_color = s.ai_expert.rate === best_ae ? "text-green-600 font-bold" : "text-amber-600";
                const am_color = s.ai_majority.rate === best_am ? "text-green-600 font-bold" : "text-amber-600";
                return (
                  <tr key={mode} className="border-b border-border/50 last:border-0">
                    <td className="py-1.5 pr-3 font-medium">{MODE_LABELS[mode]}</td>
                    <td className={`text-center py-1.5 px-2 font-mono font-semibold ${ae_color}`}>
                      {s.ai_expert.rate}% <span className="text-[9px] text-muted-foreground">({s.ai_expert.agree}/{s.ai_expert.total})</span>
                    </td>
                    <td className={`text-center py-1.5 px-2 font-mono font-semibold ${am_color}`}>
                      {s.ai_majority.rate}% <span className="text-[9px] text-muted-foreground">({s.ai_majority.agree}/{s.ai_majority.total})</span>
                    </td>
                    {hasAiMajority && (
                      <td className="text-center py-1.5 px-2 font-mono font-semibold text-green-600">
                        {aiMaj ? `${aiMaj.ai_majority_vs_expert_majority.rate}%` : "—"}
                        {aiMaj && <span className="text-[9px] text-muted-foreground ml-1">({aiMaj.ai_majority_vs_expert_majority.agree}/{aiMaj.ai_majority_vs_expert_majority.total})</span>}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mode overlap */}
      {data.mode_disagreements && Object.keys(data.mode_disagreements).length > 0 && (
        <div className="border border-border rounded-lg p-4" data-testid="pw-mode-overlap">
          <h3 className="text-xs font-medium mb-3 flex items-center gap-1.5">
            <BarChart3 className="h-3 w-3" /> AI Pick Consistency Across Input Formats
          </h3>
          <div className="space-y-3">
            {Object.entries(data.mode_disagreements).map(([key, d]) => {
              const pairLabel = key.split("_vs_").map(k => MODE_LABELS[k] || k).join(" vs ");
              const agreeRate = d.total > 0 ? Math.round((d.agree / d.total) * 1000) / 10 : 0;
              return <HBar key={key} rate={agreeRate} label={pairLabel} sub={`${d.agree}/${d.total} same, ${d.differ} differ`} color="bg-green-400/70" />;
            })}
          </div>
        </div>
      )}

      <MethodologyNote />
    </div>
  );
}

function RunningIndicator({ runningMode, status }) {
  return (
    <div className="flex items-center gap-2 text-xs bg-accent/10 rounded px-3 py-2" data-testid="pw-running-indicator">
      <Loader2 className="h-4 w-4 animate-spin text-accent" />
      <span>Evaluating {runningMode ? MODE_LABELS[runningMode] : ""} pairs... {status?.tournament_progress?.completed_matches || 0}/{status?.tournament_progress?.total_matches || "?"}</span>
    </div>
  );
}

function MethodologyNote() {
  return (
    <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="pw-agreement-methodology">
      <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
      <ul className="text-xs text-muted-foreground space-y-1">
        <li><strong>Comparison set:</strong> Agreement rates computed on the same paper pairs across all input formats.</li>
        <li><strong>AI vs Expert:</strong> How often an individual AI model agrees with each human reviewer.</li>
        <li><strong>AI vs Majority:</strong> How often an individual AI model agrees with the human reviewer consensus.</li>
        <li><strong>AI Consensus vs Majority:</strong> How often the 3-model majority vote agrees with the human majority (where all 3 models evaluated the pair).</li>
        <li><strong>Models:</strong> GPT-5.2, Claude Opus 4.5, Gemini 3 Pro.</li>
      </ul>
    </div>
  );
}
