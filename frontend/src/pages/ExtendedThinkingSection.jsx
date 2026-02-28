import { useState, useEffect } from "react";
import axios from "axios";
import { Play, Square, RefreshCw, Brain } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ValidationConvergence } from "@/components/ConvergenceSection";

const API = process.env.REACT_APP_BACKEND_URL;
const ADMIN_HEADERS = { "X-Admin-Token": sessionStorage.getItem("admin_token") };

const DATASETS = [
  { id: "iclr-codegen", label: "ICLR Code Gen" },
  { id: "iclr-fairness", label: "ICLR Fairness" },
  { id: "iclr-llm", label: "ICLR LLM" },
  { id: "iclr-molecules", label: "ICLR Molecules" },
  { id: "iclr-optimization", label: "ICLR Optimization" },
  { id: "iclr-ot", label: "ICLR Optimal Transport" },
  { id: "iclr-pdes", label: "ICLR PDEs" },
  { id: "iclr-protein", label: "ICLR Protein" },
  { id: "peerread_acl_2017", label: "PeerRead ACL 2017" },
  { id: "elife-microbiology", label: "eLife Microbiology" },
  { id: "elife-cancer", label: "eLife Cancer" },
  { id: "elife-neuro-100", label: "eLife Neuroscience" },
  { id: "elife-comp-sys-bio", label: "eLife Comp & Sys Bio" },
];

export default function ExtendedThinkingSection() {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedDs, setSelectedDs] = useState(DATASETS[0].id);

  const fetchStatus = async () => {
    try {
      const r = await axios.get(`${API}/api/validation/extended-thinking/status`);
      setStatus(r.data);
      setRunning(r.data?.running || false);
    } catch { /* ignore */ }
    try {
      const r = await axios.get(`${API}/api/validation/extended-thinking/results`, { timeout: 30000 });
      setResults(r.data);
    } catch (e) { console.warn("Extended thinking results fetch error:", e.message); }
    setLoading(false);
  };

  useEffect(() => { fetchStatus(); }, []);
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(fetchStatus, 10000);
    return () => clearInterval(iv);
  }, [running]);

  const startRun = async () => {
    try {
      await axios.post(`${API}/api/validation/extended-thinking/run`,
        { dataset_id: selectedDs, num_pairs: 200 },
        { headers: ADMIN_HEADERS });
      setRunning(true);
      fetchStatus();
    } catch (e) { console.error(e); }
  };

  const stopRun = async () => {
    try {
      await axios.post(`${API}/api/validation/extended-thinking/stop`, {}, { headers: ADMIN_HEADERS });
      setRunning(false);
    } catch (e) { console.error(e); }
  };

  const data = results?.status === "ok" ? results : null;

  return (
    <div className="space-y-5" data-testid="extended-thinking">
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Brain className="h-4 w-4" /> Experiment Design
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Does giving the AI summarizer a "thinking budget" (extended thinking) produce better summaries for paper comparison?</p>
          <p><strong>Method:</strong> Generate impact summaries using Claude Opus 4.6 with extended thinking (10K token budget). Run pairwise tournament on the same cross-tier pairs as the Opus 4.6 baseline, using the same judge models. Compare accuracy.</p>
          <p><strong>Control:</strong> Abstract + Summary (Opus 4.6) — standard single-pass summary</p>
          <p><strong>Treatment:</strong> Abstract + Summary (Opus 4.6 Extended Thinking) — summary generated with 10K thinking token budget</p>
        </div>
      </div>

      {/* Run controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={selectedDs}
          onChange={e => setSelectedDs(e.target.value)}
          className="text-xs border border-border rounded px-2 py-1.5"
          data-testid="thinking-dataset-select"
        >
          {DATASETS.map(ds => (
            <option key={ds.id} value={ds.id}>{ds.label}</option>
          ))}
        </select>
        {running ? (
          <>
            <span className="text-xs text-muted-foreground animate-pulse flex items-center gap-1">
              <RefreshCw className="h-3 w-3 animate-spin" /> Running...
              {status?.done > 0 && ` ${status.done}/${status.total}`}
            </span>
            <Button size="sm" variant="destructive" className="gap-1.5 text-xs" onClick={stopRun}>
              <Square className="h-3 w-3" /> Stop
            </Button>
          </>
        ) : (
          <Button size="sm" className="gap-1.5 text-xs" onClick={startRun} data-testid="start-thinking-run">
            <Play className="h-3 w-3" /> Generate Thinking Summaries + Run 200 pairs
          </Button>
        )}
      </div>

      {/* Results */}
      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Papers with Thinking Summary" value={data.papers_with_thinking || 0} />
            <StatCard label="Thinking Matches" value={data.thinking_matches || 0} sub="same opus46 pairs replayed" />
            <StatCard label="Baseline Accuracy" value={`${data.baseline_accuracy || 0}%`} sub={`${data.baseline_gt_pairs || 0} non-tie same-pair comparisons`} />
            <StatCard
              label="Thinking Accuracy"
              value={`${data.thinking_accuracy || 0}%`}
              sub={`${data.lift > 0 ? "+" : ""}${data.lift || 0}pp vs baseline`}
              accent={data.lift > 0}
            />
          </div>
          {data.mcnemar && (
            <div className="border border-border rounded-lg p-3 text-xs">
              <strong>McNemar's test (same-pair):</strong>{" "}
              p = {data.mcnemar.p_value}, {data.mcnemar.significant ? "significant" : "not significant"}{" "}
              (only_baseline={data.mcnemar.only_baseline}, only_thinking={data.mcnemar.only_thinking})
            </div>
          )}
          {data.by_dataset && Object.keys(data.by_dataset).length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium">By Dataset</h3>
              </div>
              <table className="w-full text-[11px]">
                <thead><tr className="border-b text-[10px] text-muted-foreground">
                  <th className="text-left px-3 py-1.5">Dataset</th>
                  <th className="text-right px-3">Non-tie pairs</th>
                  <th className="text-right px-3">Baseline</th>
                  <th className="text-right px-3">Thinking</th>
                  <th className="text-right px-3">Lift</th>
                </tr></thead>
                <tbody>
                  {Object.entries(data.by_dataset)
                    .sort((a, b) => b[1].lift - a[1].lift)
                    .map(([ds, d]) => (
                    <tr key={ds} className="border-b border-border/30">
                      <td className="px-3 py-1.5 font-medium">{ds}</td>
                      <td className="text-right px-3">{d.pairs}</td>
                      <td className="text-right px-3">{d.baseline}%</td>
                      <td className="text-right px-3 font-medium">{d.thinking}%</td>
                      <td className={`text-right px-3 font-mono ${d.lift > 0 ? "text-green-600" : d.lift < 0 ? "text-red-500" : ""}`}>
                        {d.lift > 0 ? "+" : ""}{d.lift}pp
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!data && !running && (
        <div className="text-center py-8 text-muted-foreground">
          <Brain className="h-8 w-8 mx-auto mb-3 opacity-30" />
          <p className="text-sm">{loading ? "Loading results..." : "No results yet. Select a dataset and click run to start."}</p>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, sub, accent }) {
  return (
    <div className={`border rounded-lg p-3 ${accent ? "border-green-300 bg-green-50/30" : "border-border"}`}>
      <p className="text-[10px] text-muted-foreground mb-0.5">{label}</p>
      <p className="text-xl font-bold">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}
