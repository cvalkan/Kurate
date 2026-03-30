import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Play, Square, FlaskConical, Info, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, Legend } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
const getAdminHeaders = () => ({ "X-Admin-Token": sessionStorage.getItem("admin_token") });

const DATASETS = [
  { id: "iclr-llm", label: "ICLR LLM" },
  { id: "iclr-codegen", label: "ICLR Code Gen" },
  { id: "iclr-pdes", label: "ICLR PDEs" },
  { id: "iclr-ot", label: "ICLR Opt. Transport" },
  { id: "iclr-fairness", label: "ICLR Fairness" },
  { id: "iclr-protein", label: "ICLR Protein" },
  { id: "iclr-molecules", label: "ICLR Molecules" },
  { id: "iclr-optimization", label: "ICLR Optimization" },
  { id: "elife-cancer", label: "eLife Cancer Biology" },
  { id: "elife-comp-sys-bio", label: "eLife Comp. & Sys. Bio." },
  { id: "elife-microbiology", label: "eLife Microbiology" },
  { id: "elife-neuro-100", label: "eLife Neuroscience" },
];
const SUMMARIZERS = [
  { id: "gpt", label: "GPT-5.2" },
  { id: "gemini", label: "Gemini 3 Pro" },
  { id: "gpt54", label: "GPT-5.4" },
];

const SUM_COLORS = {
  "Opus 4.5": "#8b5cf6", "Opus 4.6": "#a78bfa", "Opus 4.6 Thinking": "#c4b5fd",
  "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b", "Extract": "#6b7280",
  "GPT-5.4": "#10b981",
};

export default function SummarizerABSection() {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedDs, setSelectedDs] = useState(DATASETS[0].id);
  const [selectedSum, setSelectedSum] = useState(SUMMARIZERS[0].id);
  const [compData, setCompData] = useState(null);

  const [results, setResults] = useState(null);
  const [expData, setExpData] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/summarizer-ab/status`);
      setStatus(r.data);
      setRunning(r.data?.running || false);
    } catch(e) { console.warn("Fetch error:", e.message || e); }
    setLoading(false);
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [datasetsRes, resultsRes, aeRes] = await Promise.all([
        axios.get(`${API}/api/validation/datasets`).catch(() => ({ data: { datasets: [] } })),
        axios.get(`${API}/api/validation/summarizer-ab/results`, { timeout: 30000 }).catch(() => ({ data: {} })),
        axios.get(`${API}/api/validation/assessor-evaluator/results`, { timeout: 30000 }).catch(() => ({ data: {} })),
      ]);
      // Use precomputed modes from datasets endpoint instead of 12 separate calls
      const modes_by_ds = {};
      const allDs = datasetsRes.data.datasets || [];
      DATASETS.forEach(ds => {
        const found = allDs.find(d => d.dataset_id === ds.id);
        if (found?.modes) {
          modes_by_ds[ds.id] = found.modes.map(m => ({ id: m, label: m, matches: 0 }));
        }
      });
      // Fallback: fetch individually only for datasets missing modes
      const missing = DATASETS.filter(ds => !modes_by_ds[ds.id]);
      if (missing.length > 0) {
        const fallback = await Promise.all(missing.map(ds => 
          axios.get(`${API}/api/validation/available-modes`, { params: { dataset_id: ds.id } }).catch(() => ({ data: { modes: [] } }))
        ));
        missing.forEach((ds, i) => { modes_by_ds[ds.id] = fallback[i].data.modes || []; });
      }
      setCompData(modes_by_ds);
      if (resultsRes.data.status === "ok") setResults(resultsRes.data);
      if (aeRes.data?.experimental) setExpData(aeRes.data.experimental);
    } catch (e) { console.warn(e); }
  }, []);

  useEffect(() => { fetchStatus(); fetchData(); }, [fetchStatus, fetchData]);
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(fetchStatus, 10000);
    return () => clearInterval(iv);
  }, [running, fetchStatus]);

  const startRun = async () => {
    try {
      await axios.post(`${API}/api/validation/summarizer-ab/run`,
        { dataset_id: selectedDs, summarizer: selectedSum, num_pairs: 300 },
        { headers: getAdminHeaders() });
      setRunning(true);
      fetchStatus();
    } catch (e) { console.error(e); }
  };

  const stopRun = async () => {
    try {
      await axios.post(`${API}/api/validation/summarizer-ab/stop`, {}, { headers: ADMIN_HEADERS });
      setRunning(false);
    } catch (e) { console.error(e); }
  };

  // Build a summary of which datasets have data for which summarizers
  const coverageData = compData ? DATASETS.map(ds => {
    const modes = compData[ds.id] || [];
    const row = { name: ds.label.replace("ICLR ", "") };
    for (const mode of modes) {
      if (mode.id === "abstract_plus_summary") row["Opus 4.5"] = mode.matches;
      else if (mode.id === "abstract_plus_summary:opus46") row["Opus 4.6"] = mode.matches;
      else if (mode.id === "abstract_plus_summary:thinking") row["Opus 4.6 Thinking"] = mode.matches;
      else if (mode.id === "abstract_plus_summary:gpt_summary") row["GPT-5.2"] = mode.matches;
      else if (mode.id === "abstract_plus_summary:gemini_summary") row["Gemini 3 Pro"] = mode.matches;
      else if (mode.id === "abstract_plus_summary:gpt54_summary") row["GPT-5.4"] = mode.matches;
    }
    return row;
  }) : [];

  return (
    <div className="space-y-5" data-testid="summarizer-ab-experiment">
      {/* Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <FlaskConical className="h-4 w-4" /> Summarizer A/B: GPT vs Gemini vs Opus Summaries
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> How does the choice of summarizer model affect tournament accuracy and ranking, controlling for the same judge models and paper pairs?</p>
          <p><strong>Method:</strong> Generate impact assessment summaries using GPT-5.2, Gemini 3 Pro, and compare with existing Opus 4.5/4.6/Thinking summaries. Run the same round-robin judges on the same cross-tier pairs. Compare pairwise accuracy and ranking correlation on overlapping pairs.</p>
          <p><strong>All comparisons on exact same pairs</strong> to avoid pair-selection bias.</p>
          <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-900 leading-relaxed mt-1">
            <strong>Limitation:</strong> The common-pairs intersection is <strong>100% cross-tier</strong> at ~5 M/P. This comparison
            cannot test within-tier robustness. A controlled within-tier test (same pairs through all summarizers) would
            require ~5,000 additional matches. Until then, the ranking below applies to cross-tier comparisons only.
          </div>
        </div>
      </div>

      {/* Admin controls */}
      <div className="border border-border rounded-lg p-3 bg-secondary/10 flex items-center gap-3 flex-wrap" data-testid="sumab-controls">
        <select className="h-8 rounded border border-border bg-background px-2 text-xs"
          value={selectedDs} onChange={e => setSelectedDs(e.target.value)} disabled={running}>
          {DATASETS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <select className="h-8 rounded border border-border bg-background px-2 text-xs"
          value={selectedSum} onChange={e => setSelectedSum(e.target.value)} disabled={running}>
          {SUMMARIZERS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        {!running ? (
          <Button size="sm" onClick={startRun} className="gap-1.5 text-xs" data-testid="sumab-start-btn">
            <Play className="h-3 w-3" /> Generate Summaries + Run 300 Pairs
          </Button>
        ) : (
          <Button size="sm" variant="destructive" onClick={stopRun} className="gap-1.5 text-xs">
            <Square className="h-3 w-3" /> Stop
          </Button>
        )}
        {running && status && (
          <span className="text-xs text-muted-foreground">
            [{status.dataset_id}/{status.summarizer}] {status.phase}: {status.done}/{status.total}
          </span>
        )}
      </div>

      {/* Same-pair results */}
      {results && (() => {
        const pooled = results.pooled || {};
        const sorted_models = Object.entries(pooled).sort((a, b) => (b[1].avg_rho || 0) - (a[1].avg_rho || 0));
        const maxRho = Math.max(...sorted_models.map(([, v]) => v.avg_rho || 0), 0.1);
        const datasets_arr = Object.entries(results.by_dataset || {});

        return (
          <>
            {/* Pooled table */}
            <div className="border-2 border-blue-200 rounded-lg overflow-hidden bg-blue-50/20" data-testid="sumab-results">
              <div className="px-3 py-2 bg-blue-100/30 border-b border-blue-200">
                <h3 className="text-xs font-medium text-blue-900 flex items-center gap-1.5">
                  <BarChart3 className="h-3 w-3" /> Same-Pair Results (All Comparisons on Identical Pairs)
                </h3>
                {results.pooled_datasets && (
                  <p className="text-[10px] text-blue-700 mt-0.5">
                    Pooled over {results.pooled_datasets.length} datasets where all compared summarizers have data: {results.pooled_datasets.map(d => d.replace("iclr-", "").replace("elife-", "e:")).join(", ")}
                  </p>
                )}
              </div>
              <div className="p-3">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-blue-200 text-[10px]">
                      <th className="text-left py-1.5 pr-3 font-medium">Summarizer</th>
                      <th className="text-right py-1.5 px-2 font-medium">Avg ρ</th>
                      <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                      <th className="text-right py-1.5 px-2 font-medium">Correct/Total</th>
                      <th className="text-right py-1.5 px-2 font-medium">Avg M/P</th>
                      <th className="py-1.5 px-2 w-1/4"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted_models.map(([name, v]) => (
                      <tr key={name} className="border-b border-blue-100">
                        <td className="py-1.5 pr-3 font-medium">{name}</td>
                        <td className="text-right py-1.5 px-2 font-mono">
                          {v.avg_rho != null ? <span className={v.avg_rho >= maxRho - 0.01 ? "text-green-600 font-semibold" : ""}>{v.avg_rho.toFixed(3)}</span> : "—"}
                        </td>
                        <td className="text-right py-1.5 px-2 font-mono">{v.accuracy}%</td>
                        <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{v.correct}/{v.total}</td>
                        <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{v.avg_mpp ?? "—"}</td>
                        <td className="py-1.5 px-2">
                          <div className="h-2.5 bg-blue-100 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${((v.avg_rho || 0) / (maxRho * 1.1)) * 100}%`, backgroundColor: SUM_COLORS[name] || "#94a3b8" }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Experimental: GPT-5.4 comparison on shared pairs */}
            {expData?.pooled && Object.keys(expData.pooled).length > 0 && (() => {
              const expEntries = (expData.summarizers || [])
                .map(s => [s, expData.pooled[`${s}|Round-Robin`]])
                .filter(([, v]) => v)
                .sort((a, b) => (b[1].accuracy || 0) - (a[1].accuracy || 0));
              const totalPairs = expEntries[0]?.[1]?.total || 0;
              return (
                <div className="border-2 border-emerald-200 rounded-lg overflow-hidden bg-emerald-50/20" data-testid="sumab-experimental">
                  <div className="px-3 py-2 bg-emerald-100/30 border-b border-emerald-200">
                    <h3 className="text-xs font-medium text-emerald-900 flex items-center gap-1.5">
                      <FlaskConical className="h-3 w-3" /> Experimental: GPT-5.4 as Summarizer
                    </h3>
                    <p className="text-[10px] text-emerald-700 mt-0.5">
                      Same-pair comparison on {totalPairs} overlapping pairs across {expData.datasets_used?.length || 0} datasets where GPT-5.4 has data.
                      Smaller N than the main table — early signal only.
                    </p>
                  </div>
                  <div className="p-3">
                    <table className="w-full text-[11px]">
                      <thead>
                        <tr className="border-b border-emerald-200 text-[10px]">
                          <th className="text-left py-1.5 pr-3 font-medium">Summarizer</th>
                          <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                          <th className="text-right py-1.5 px-2 font-medium">Correct/Total</th>
                          <th className="py-1.5 px-2 w-1/4"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {expEntries.map(([name, v]) => {
                          const isExp = name === "GPT-5.4";
                          return (
                            <tr key={name} className={`border-b border-emerald-100 ${isExp ? "bg-emerald-50" : ""}`}>
                              <td className={`py-1.5 pr-3 ${isExp ? "font-semibold" : "font-medium"}`}>{name}</td>
                              <td className="text-right py-1.5 px-2 font-mono">{v.accuracy}%</td>
                              <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{v.correct}/{v.total}</td>
                              <td className="py-1.5 px-2">
                                <div className="h-2.5 bg-emerald-100 rounded-full overflow-hidden">
                                  <div className="h-full rounded-full" style={{ width: `${(v.accuracy / 100) * 100}%`, backgroundColor: SUM_COLORS[name] || "#94a3b8" }} />
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })()}

            {/* Per-dataset breakdown */}
            {datasets_arr.map(([dsId, ds]) => {
              const firstMode = Object.values(ds.modes || {})[0];
              const ties = firstMode?.expert_ties || 0;
              return (
              <div key={dsId} className="border border-border rounded-lg overflow-hidden" data-testid={`sumab-ds-${dsId}`}>
                <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                  <h3 className="text-xs font-medium">
                    {ds.name} — {ds.shared_pairs} shared pairs
                    {ties > 0 && <span className="text-muted-foreground font-normal"> ({ties} expert ties excluded from accuracy)</span>}
                  </h3>
                </div>
                <div className="p-3">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-border text-[10px]">
                        <th className="text-left py-1 pr-3 font-medium">Summarizer</th>
                        <th className="text-right py-1 px-2 font-medium">ρ</th>
                        <th className="text-right py-1 px-2 font-medium">Accuracy</th>
                        <th className="text-right py-1 px-2 font-medium">Correct/Total</th>
                        <th className="text-right py-1 px-2 font-medium">Avg M/P</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(ds.modes || {}).sort((a, b) => (b[1].rho || 0) - (a[1].rho || 0)).map(([name, v]) => (
                        <tr key={name} className="border-b border-border/30">
                          <td className="py-1 pr-3 font-medium">{name}</td>
                          <td className="text-right py-1 px-2 font-mono">{v.rho ?? "—"}</td>
                          <td className="text-right py-1 px-2 font-mono">{v.accuracy}%</td>
                          <td className="text-right py-1 px-2 font-mono text-muted-foreground">{v.correct}/{v.total}</td>
                          <td className="text-right py-1 px-2 font-mono text-muted-foreground">{v.avg_mpp ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
            })}
          </>
        );
      })()}

      {/* Data coverage table */}
      {coverageData.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="sumab-coverage">
          <div className="px-3 py-2 bg-secondary/10 border-b border-border">
            <h3 className="text-xs font-medium">Match Coverage by Summarizer & Dataset</h3>
            <div className="text-[10px] text-muted-foreground mt-0.5">Number of completed matches per (summarizer, dataset) combination.</div>
          </div>
          <div className="p-3 overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border text-[10px]">
                  <th className="text-left py-1.5 pr-2 font-medium">Dataset</th>
                  {["Opus 4.5", "Opus 4.6", "Opus 4.6 Thinking", "GPT-5.2", "Gemini 3 Pro"].map(s => (
                    <th key={s} className="text-right py-1.5 px-2 font-medium">{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {coverageData.map(row => (
                  <tr key={row.name} className="border-b border-border/30">
                    <td className="py-1.5 pr-2 font-medium">{row.name}</td>
                    {["Opus 4.5", "Opus 4.6", "Opus 4.6 Thinking", "GPT-5.2", "Gemini 3 Pro"].map(s => (
                      <td key={s} className="text-right py-1.5 px-2 font-mono">
                        {row[s] ? <span className="text-green-600">{row[s]}</span> : <span className="text-muted-foreground/30">—</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Summary generation:</strong> Each summarizer processes the full paper text (abstract + extracted sections) to produce an impact assessment.</li>
          <li><strong>Tournament:</strong> Same 3-model round-robin judges (GPT-5.2, Opus 4.6, Gemini 3 Pro) on the same cross-tier pairs as the Opus 4.6 baseline.</li>
          <li><strong>Same-pair comparison:</strong> Ranking ρ and accuracy computed only on the intersection of pairs across all summarizers being compared.</li>
          <li><strong>Results will appear on the tournament page</strong> as additional content mode tabs once matches are complete.</li>
        </ul>
      </div>
    </div>
  );
}
