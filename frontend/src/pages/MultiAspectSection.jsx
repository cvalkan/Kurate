import { useState, useEffect } from "react";
import axios from "axios";
import { Play, Square, Layers, BarChart3, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
const ADMIN_HEADERS = { "X-Admin-Token": sessionStorage.getItem("admin_token") };

const DATASETS = [
  { id: "iclr-llm", label: "ICLR LLM" },
  { id: "iclr-codegen", label: "ICLR Code Gen" },
  { id: "iclr-protein", label: "ICLR Protein" },
  { id: "peerread_acl_2017", label: "PeerRead ACL 2017" },
];

const DIM_COLORS = {
  novelty: "#8b5cf6", applications: "#3b82f6", rigor: "#22c55e",
  breadth: "#f59e0b", timeliness: "#ef4444",
};

function Stat({ label, value, sub, color = "text-foreground" }) {
  return (
    <div className="p-3 border border-border/50 rounded-lg text-center">
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

export default function MultiAspectSection() {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedDs, setSelectedDs] = useState(DATASETS[0].id);
  const [numPairs, setNumPairs] = useState(500);

  const fetchStatus = async () => {
    try {
      const r = await axios.get(`${API}/api/validation/multi-aspect/status`);
      setStatus(r.data);
      setRunning(r.data?.running || false);
    } catch { /* ignore */ }
    try {
      const r = await axios.get(`${API}/api/validation/multi-aspect/results`, { timeout: 30000 });
      setResults(r.data);
    } catch (e) { console.warn("Multi-aspect results error:", e.message); }
    setLoading(false);
  };

  useEffect(() => { fetchStatus(); }, []);
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, [running]);

  const startRun = async () => {
    try {
      await axios.post(`${API}/api/validation/multi-aspect/run`,
        { dataset_id: selectedDs, num_pairs: numPairs },
        { headers: ADMIN_HEADERS });
      setRunning(true);
      fetchStatus();
    } catch (e) { console.error(e); }
  };

  const stopRun = async () => {
    try {
      await axios.post(`${API}/api/validation/multi-aspect/stop`, {}, { headers: ADMIN_HEADERS });
      setRunning(false);
    } catch (e) { console.error(e); }
  };

  const data = results?.status === "ok" ? results : null;

  // Chart data
  const dimChartData = data ? Object.entries(data.per_dimension).map(([dim, v]) => ({
    name: v.label, rate: v.rate, dim, correct: v.correct, total: v.total,
  })) : [];

  return (
    <div className="space-y-5" data-testid="multi-aspect-experiment">
      {/* Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Layers className="h-4 w-4" /> Experiment Design
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Does forcing the AI judge to evaluate 5 separate dimensions before deciding a winner improve accuracy compared to a single holistic judgment?</p>
          <p><strong>Method:</strong> Same cross-tier pairs as the Opus 4.6 baseline. Instead of one "which is better?" question, the judge outputs a winner per dimension. The aggregate winner is the majority across the 5 dimensions.</p>
          <p><strong>Input:</strong> Abstract + Opus 4.6 Thinking summaries (best available). Same 3-model round-robin judges.</p>
          <p><strong>Dimensions:</strong> (1) Novelty & Innovation, (2) Real-World Applications, (3) Methodological Rigor, (4) Breadth of Impact, (5) Timeliness & Relevance — same criteria as the holistic prompt.</p>
        </div>
      </div>

      {/* Admin controls */}
      <div className="border border-border rounded-lg p-3 bg-secondary/10 flex items-center gap-3 flex-wrap" data-testid="ma-admin-controls">
        <select className="h-8 rounded border border-border bg-background px-2 text-xs"
          value={selectedDs} onChange={e => setSelectedDs(e.target.value)} disabled={running} data-testid="ma-dataset-select">
          {DATASETS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <input type="number" min={50} max={2000} value={numPairs}
          onChange={e => setNumPairs(parseInt(e.target.value) || 500)}
          className="w-20 h-8 rounded border border-border bg-background px-2 text-xs" disabled={running} />
        {!running ? (
          <Button size="sm" onClick={startRun} className="gap-1.5 text-xs" data-testid="ma-start-btn">
            <Play className="h-3 w-3" /> Run Multi-Aspect
          </Button>
        ) : (
          <Button size="sm" variant="destructive" onClick={stopRun} className="gap-1.5 text-xs">
            <Square className="h-3 w-3" /> Stop
          </Button>
        )}
        {running && status && <span className="text-xs text-muted-foreground">{status.done}/{status.total} matches</span>}
      </div>

      {loading && <div className="text-xs text-muted-foreground text-center py-6">Loading results...</div>}

      {data && (
        <>
          {/* Headline stats */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="ma-stats">
            <Stat label="Baseline (Holistic)" value={`${data.baseline.rate}%`}
              sub={`${data.baseline.correct}/${data.baseline.total}`} color="text-muted-foreground" />
            <Stat label="Multi-Aspect (Agg.)" value={`${data.aggregate.rate}%`}
              sub={`${data.aggregate.correct}/${data.aggregate.total}`}
              color={data.lift > 0 ? "text-green-600" : data.lift < 0 ? "text-red-600" : "text-amber-600"} />
            <Stat label="Lift" value={`${data.lift > 0 ? "+" : ""}${data.lift}pp`}
              sub={data.mcnemar?.significant ? "Significant" : "Not significant"}
              color={data.lift > 0 ? "text-green-600" : "text-red-600"} />
            <Stat label="Dimension Agreement" value={`${data.dimension_agreement.rate}%`}
              sub={`${data.dimension_agreement.all_agree}/${data.dimension_agreement.total} all 5 agree`}
              color="text-blue-600" />
            <Stat label="Total Matches" value={data.total_matches} color="text-muted-foreground" />
          </div>

          {/* Per-dimension accuracy chart */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="ma-dimension-chart">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium flex items-center gap-1.5">
                <BarChart3 className="h-3 w-3" /> Accuracy by Dimension
              </h3>
              <div className="text-[10px] text-muted-foreground mt-0.5">Which dimension best predicts the human ground truth winner?</div>
            </div>
            <div className="p-3">
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={dimChartData} barCategoryGap="20%">
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-15} textAnchor="end" height={50} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                  <Tooltip content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const p = payload[0];
                    return (
                      <div className="bg-background border border-border rounded px-3 py-2 shadow text-xs">
                        <div className="font-medium">{label}</div>
                        <div className="font-mono">{p.value}% ({p.payload.correct}/{p.payload.total})</div>
                      </div>
                    );
                  }} />
                  <ReferenceLine y={data.baseline.rate} stroke="#94a3b8" strokeDasharray="5 5" label={{ value: `Baseline ${data.baseline.rate}%`, fontSize: 10, fill: "#94a3b8" }} />
                  <ReferenceLine y={data.aggregate.rate} stroke="#22c55e" strokeDasharray="3 3" label={{ value: `Aggregate ${data.aggregate.rate}%`, fontSize: 10, fill: "#22c55e" }} />
                  <Bar dataKey="rate" name="Accuracy" radius={[4, 4, 0, 0]}>
                    {dimChartData.map((e, i) => <Cell key={i} fill={DIM_COLORS[e.dim] || "#94a3b8"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* McNemar */}
          <div className="border border-border rounded-lg p-4" data-testid="ma-mcnemar">
            <h3 className="text-xs font-medium mb-2">McNemar's Test: Multi-Aspect Aggregate vs Holistic Baseline</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div><span className="text-muted-foreground">Pairs:</span> <span className="font-mono">{data.mcnemar?.pairs}</span></div>
              <div><span className="text-muted-foreground">Only baseline correct:</span> <span className="font-mono">{data.mcnemar?.only_baseline}</span></div>
              <div><span className="text-muted-foreground">Only multi-aspect correct:</span> <span className="font-mono">{data.mcnemar?.only_multi_aspect}</span></div>
              <div><span className="text-muted-foreground">p-value:</span> <span className={`font-mono ${data.mcnemar?.significant ? "text-green-600 font-bold" : ""}`}>{data.mcnemar?.p_value}</span></div>
            </div>
          </div>

          {/* Per-dimension table */}
          <div className="border border-border rounded-lg overflow-hidden" data-testid="ma-dimension-table">
            <div className="px-3 py-2 bg-secondary/10 border-b border-border">
              <h3 className="text-xs font-medium">Detailed Per-Dimension Accuracy</h3>
            </div>
            <div className="p-3">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border text-[10px]">
                    <th className="text-left py-1.5 pr-3 font-medium">Dimension</th>
                    <th className="text-right py-1.5 px-2 font-medium">Correct</th>
                    <th className="text-right py-1.5 px-2 font-medium">Total</th>
                    <th className="text-right py-1.5 px-2 font-medium">Accuracy</th>
                    <th className="text-right py-1.5 px-2 font-medium">vs Baseline</th>
                    <th className="py-1.5 px-2 w-1/4"></th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.per_dimension).map(([dim, v]) => {
                    const diff = v.rate - data.baseline.rate;
                    return (
                      <tr key={dim} className="border-b border-border/30">
                        <td className="py-1.5 pr-3 font-medium">{v.label}</td>
                        <td className="text-right py-1.5 px-2 font-mono">{v.correct}</td>
                        <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{v.total}</td>
                        <td className="text-right py-1.5 px-2 font-mono">
                          <span className={v.rate > data.baseline.rate ? "text-green-600 font-semibold" : "text-amber-600"}>{v.rate}%</span>
                        </td>
                        <td className={`text-right py-1.5 px-2 font-mono text-[10px] ${diff > 0 ? "text-green-600" : "text-red-600"}`}>
                          {diff > 0 ? "+" : ""}{diff.toFixed(1)}pp
                        </td>
                        <td className="py-1.5 px-2">
                          <div className="h-2.5 bg-secondary/30 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${v.rate}%`, backgroundColor: DIM_COLORS[dim] || "#94a3b8" }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="border-t-2 border-border bg-secondary/10 font-semibold">
                    <td className="py-1.5 pr-3">Aggregate (majority of 5)</td>
                    <td className="text-right py-1.5 px-2 font-mono">{data.aggregate.correct}</td>
                    <td className="text-right py-1.5 px-2 font-mono text-muted-foreground">{data.aggregate.total}</td>
                    <td className="text-right py-1.5 px-2 font-mono">
                      <span className={data.aggregate.rate > data.baseline.rate ? "text-green-600" : "text-amber-600"}>{data.aggregate.rate}%</span>
                    </td>
                    <td className={`text-right py-1.5 px-2 font-mono text-[10px] ${data.lift > 0 ? "text-green-600" : "text-red-600"}`}>
                      {data.lift > 0 ? "+" : ""}{data.lift}pp
                    </td>
                    <td></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {!data && !loading && (
        <div className="border border-border rounded-lg p-6 text-center text-xs text-muted-foreground">
          No multi-aspect data yet. Run the experiment above.
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Pair selection:</strong> Same cross-tier pairs as the Opus 4.6 baseline tournament.</li>
          <li><strong>Prompt:</strong> Judge outputs a winner per dimension instead of a single holistic verdict.</li>
          <li><strong>Aggregate:</strong> Majority vote across the 5 dimensions (3+ agree → winner).</li>
          <li><strong>Per-dimension accuracy:</strong> How well each individual dimension predicts the human GT winner.</li>
          <li><strong>Dimension agreement:</strong> Fraction of pairs where all 5 dimensions pick the same paper.</li>
        </ul>
      </div>
    </div>
  );
}
