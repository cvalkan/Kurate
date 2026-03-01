import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Play, Square, FlaskConical, Info, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, Legend } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
const ADMIN_HEADERS = { "X-Admin-Token": sessionStorage.getItem("admin_token") };

const DATASETS = [
  { id: "iclr-llm", label: "ICLR LLM" },
  { id: "iclr-codegen", label: "ICLR Code Gen" },
  { id: "iclr-pdes", label: "ICLR PDEs" },
  { id: "iclr-ot", label: "ICLR Opt. Transport" },
  { id: "iclr-fairness", label: "ICLR Fairness" },
  { id: "iclr-protein", label: "ICLR Protein" },
];
const SUMMARIZERS = [
  { id: "gpt", label: "GPT-5.2" },
  { id: "gemini", label: "Gemini 3 Pro" },
];

const SUM_COLORS = {
  "Opus 4.5": "#8b5cf6", "Opus 4.6": "#a78bfa", "Opus 4.6 Thinking": "#c4b5fd",
  "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b", "Extract": "#6b7280",
};

export default function SummarizerABSection() {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedDs, setSelectedDs] = useState(DATASETS[0].id);
  const [selectedSum, setSelectedSum] = useState(SUMMARIZERS[0].id);
  const [compData, setCompData] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/summarizer-ab/status`);
      setStatus(r.data);
      setRunning(r.data?.running || false);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  // Fetch same-pair comparison data
  const fetchComparison = useCallback(async () => {
    try {
      // Get available modes for each ICLR dataset to check which summarizers have data
      const modes_by_ds = {};
      for (const ds of DATASETS) {
        const r = await axios.get(`${API}/api/validation/available-modes`, { params: { dataset_id: ds.id } });
        modes_by_ds[ds.id] = r.data.modes || [];
      }
      setCompData(modes_by_ds);
    } catch (e) { console.warn(e); }
  }, []);

  useEffect(() => { fetchStatus(); fetchComparison(); }, [fetchStatus, fetchComparison]);
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(fetchStatus, 10000);
    return () => clearInterval(iv);
  }, [running, fetchStatus]);

  const startRun = async () => {
    try {
      await axios.post(`${API}/api/validation/summarizer-ab/run`,
        { dataset_id: selectedDs, summarizer: selectedSum, num_pairs: 300 },
        { headers: ADMIN_HEADERS });
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
          <p><strong>Method:</strong> Generate impact assessment summaries using GPT-5.2, Gemini 3 Pro, and compare with existing Opus 4.5/4.6/Thinking summaries. Run the same round-robin judges on the same cross-tier pairs. Compare pairwise accuracy and BT ranking correlation on overlapping pairs.</p>
          <p><strong>All comparisons on exact same pairs</strong> to avoid pair-selection bias (which previously inflated the Opus 4.6 Thinking advantage from +0.057 to +0.000 on ranking).</p>
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
