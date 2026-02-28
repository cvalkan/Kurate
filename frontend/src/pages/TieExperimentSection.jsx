import { useState, useEffect } from "react";
import axios from "axios";
import { Play, Square, Scale, BarChart3, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;
const ADMIN_HEADERS = { "X-Admin-Token": sessionStorage.getItem("admin_token") };

const DATASETS = [
  { id: "iclr-llm", label: "ICLR LLM" },
  { id: "iclr-codegen", label: "ICLR Code Gen" },
  { id: "iclr-fairness", label: "ICLR Fairness" },
  { id: "elife-cancer", label: "eLife Cancer" },
  { id: "peerread_acl_2017", label: "PeerRead ACL 2017" },
];

function Stat({ label, value, sub, color = "text-foreground" }) {
  return (
    <div className="p-3 border border-border/50 rounded-lg text-center" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
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
          <span className="font-mono font-medium">{typeof p.value === "number" ? `${p.value}%` : p.value}</span>
        </div>
      ))}
    </div>
  );
}

const GAP_LABELS = { small: "Small (1 pt)", medium: "Medium (2 pts)", large: "Large (3+ pts)" };
const GAP_COLORS = { small: "#f59e0b", medium: "#3b82f6", large: "#22c55e" };

export default function TieExperimentSection() {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedDs, setSelectedDs] = useState(DATASETS[0].id);
  const [numPairs, setNumPairs] = useState(500);

  const fetchStatus = async () => {
    try {
      const r = await axios.get(`${API}/api/validation/tie-experiment/status`);
      setStatus(r.data);
      setRunning(r.data?.running || false);
    } catch { /* ignore */ }
    try {
      const r = await axios.get(`${API}/api/validation/tie-experiment/results`, { timeout: 30000 });
      setResults(r.data);
    } catch (e) { console.warn("Tie experiment results fetch error:", e.message); }
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
      await axios.post(`${API}/api/validation/tie-experiment/run`,
        { dataset_id: selectedDs, num_pairs: numPairs },
        { headers: ADMIN_HEADERS });
      setRunning(true);
      fetchStatus();
    } catch (e) { console.error(e); }
  };

  const stopRun = async () => {
    try {
      await axios.post(`${API}/api/validation/tie-experiment/stop`, {}, { headers: ADMIN_HEADERS });
      setRunning(false);
    } catch (e) { console.error(e); }
  };

  const data = results?.status === "ok" ? results : null;

  // Build gap chart data
  const gapChartData = [];
  if (data?.by_dataset) {
    const dsResults = Object.values(data.by_dataset);
    if (dsResults.length > 0) {
      const ds = dsResults[0]; // Primary dataset
      for (const bucket of ["small", "medium", "large"]) {
        const g = ds.gap_analysis?.[bucket];
        if (g) {
          gapChartData.push({
            name: GAP_LABELS[bucket],
            "Baseline Accuracy": g.baseline_accuracy,
            "Tie Rate": g.tie_rate,
            "Non-Tie Accuracy": g.tie_accuracy,
            bucket,
          });
        }
      }
    }
  }

  return (
    <div className="space-y-5" data-testid="tie-experiment">
      {/* Experiment Design */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Scale className="h-4 w-4" /> Experiment Design
        </h3>
        <div className="text-xs text-muted-foreground space-y-1.5">
          <p><strong>Question:</strong> Does allowing AI judges to declare ties improve accuracy on decisive pairs, and are ties well-calibrated (landing on close-score pairs)?</p>
          <p><strong>Method:</strong> Replay the same opus46 cross-tier pairs with a modified prompt that permits <code>"winner": "tie"</code>. Compare forced-choice baseline accuracy with tie-allowed accuracy on non-tie decisions. Analyze tie rate by human score gap.</p>
          <p><strong>Baseline:</strong> Abstract + Summary (Opus 4.6) — forced choice only.</p>
          <p><strong>Treatment:</strong> Same input, same judges, but prompt allows ties when papers are close in impact.</p>
        </div>
      </div>

      {/* Admin controls */}
      <div className="border border-border rounded-lg p-3 bg-secondary/10 flex items-center gap-3 flex-wrap" data-testid="tie-admin-controls">
        <select
          className="h-8 rounded border border-border bg-background px-2 text-xs"
          value={selectedDs}
          onChange={e => setSelectedDs(e.target.value)}
          disabled={running}
          data-testid="tie-dataset-select"
        >
          {DATASETS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <input
          type="number" min={50} max={2000} value={numPairs}
          onChange={e => setNumPairs(parseInt(e.target.value) || 500)}
          className="w-20 h-8 rounded border border-border bg-background px-2 text-xs"
          disabled={running}
          data-testid="tie-num-pairs"
        />
        {!running ? (
          <Button size="sm" onClick={startRun} className="gap-1.5 text-xs" data-testid="tie-start-btn">
            <Play className="h-3 w-3" /> Run Tie Experiment
          </Button>
        ) : (
          <Button size="sm" variant="destructive" onClick={stopRun} className="gap-1.5 text-xs" data-testid="tie-stop-btn">
            <Square className="h-3 w-3" /> Stop
          </Button>
        )}
        {running && status && (
          <span className="text-xs text-muted-foreground">
            {status.done}/{status.total} matches ({status.ties} ties)
          </span>
        )}
      </div>

      {loading && <div className="text-xs text-muted-foreground text-center py-6">Loading results...</div>}

      {data && (
        <>
          {/* Pooled results */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="tie-pooled-stats">
            <Stat label="Tie Rate" value={`${data.tie_rate}%`}
              sub={`${data.total_ties} / ${data.total_pairs_with_gt} pairs`}
              color="text-blue-600" />
            <Stat label="Baseline Accuracy" value={`${data.baseline_accuracy}%`}
              sub="Forced choice (opus46)"
              color="text-muted-foreground" />
            <Stat label="Tie Non-Tie Acc." value={`${data.tie_accuracy_non_tie}%`}
              sub="When AI picks a winner"
              color={data.lift > 0 ? "text-green-600" : data.lift < 0 ? "text-red-600" : "text-amber-600"} />
            <Stat label="Lift" value={`${data.lift > 0 ? "+" : ""}${data.lift}pp`}
              sub={data.mcnemar?.significant ? "Significant" : "Not significant"}
              color={data.lift > 0 ? "text-green-600" : "text-red-600"} />
            <Stat label="Calibration" value={`${data.tie_calibration?.calibration_ratio}%`}
              sub={`${data.tie_calibration?.close_pairs_tied}/${data.total_ties} ties on close pairs`}
              color={data.tie_calibration?.calibration_ratio >= 50 ? "text-green-600" : "text-amber-600"} />
          </div>

          {/* McNemar details */}
          <div className="border border-border rounded-lg p-4" data-testid="tie-mcnemar">
            <h3 className="text-xs font-medium mb-2 flex items-center gap-1.5">
              <BarChart3 className="h-3 w-3" /> McNemar's Test (Non-Tie Decisions Only)
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div><span className="text-muted-foreground">Non-tie pairs:</span> <span className="font-mono">{data.mcnemar?.non_tie_pairs}</span></div>
              <div><span className="text-muted-foreground">Only baseline correct:</span> <span className="font-mono">{data.mcnemar?.only_baseline}</span></div>
              <div><span className="text-muted-foreground">Only tie-allowed correct:</span> <span className="font-mono">{data.mcnemar?.only_tie}</span></div>
              <div><span className="text-muted-foreground">p-value:</span> <span className={`font-mono ${data.mcnemar?.significant ? "text-green-600 font-bold" : ""}`}>{data.mcnemar?.p_value}</span></div>
            </div>
          </div>

          {/* Gap Analysis Chart */}
          {gapChartData.length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden" data-testid="tie-gap-chart">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium flex items-center gap-1.5">
                  <BarChart3 className="h-3 w-3" /> Tie Rate & Accuracy by Human Score Gap
                </h3>
                <div className="text-[10px] text-muted-foreground mt-0.5">Are ties calibrated? Higher tie rate on close pairs = well-calibrated.</div>
              </div>
              <div className="p-3">
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={gapChartData} barCategoryGap="20%">
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="Baseline Accuracy" fill="#94a3b8" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="Tie Rate" radius={[3, 3, 0, 0]}>
                      {gapChartData.map((entry, i) => (
                        <Cell key={i} fill={GAP_COLORS[entry.bucket]} />
                      ))}
                    </Bar>
                    <Bar dataKey="Non-Tie Accuracy" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Per-dataset breakdown */}
          {Object.keys(data.by_dataset).length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden" data-testid="tie-by-dataset">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium">Results by Dataset</h3>
              </div>
              <div className="p-3 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-left py-1.5 pr-3 font-medium">Dataset</th>
                      <th className="text-center py-1.5 px-2 font-medium">Pairs</th>
                      <th className="text-center py-1.5 px-2 font-medium">Tie Rate</th>
                      <th className="text-center py-1.5 px-2 font-medium">Baseline Acc.</th>
                      <th className="text-center py-1.5 px-2 font-medium">Non-Tie Acc.</th>
                      <th className="text-center py-1.5 px-2 font-medium">Lift</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.by_dataset).map(([ds, d]) => (
                      <tr key={ds} className="border-b border-border/50 last:border-0">
                        <td className="py-1.5 pr-3 font-medium">{ds}</td>
                        <td className="text-center py-1.5 px-2 font-mono">{d.pairs}</td>
                        <td className="text-center py-1.5 px-2 font-mono text-blue-600">{d.tie_rate}%</td>
                        <td className="text-center py-1.5 px-2 font-mono">{d.baseline_accuracy}%</td>
                        <td className="text-center py-1.5 px-2 font-mono">{d.tie_accuracy_non_tie}%</td>
                        <td className={`text-center py-1.5 px-2 font-mono ${d.lift > 0 ? "text-green-600" : d.lift < 0 ? "text-red-600" : ""}`}>
                          {d.lift > 0 ? "+" : ""}{d.lift}pp
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tie calibration detail */}
          {data.tie_calibration && (
            <div className="border border-border rounded-lg p-4" data-testid="tie-calibration">
              <h3 className="text-xs font-medium mb-2 flex items-center gap-1.5">
                <Info className="h-3 w-3" /> Tie Calibration
              </h3>
              <div className="text-xs text-muted-foreground space-y-1">
                <p>Of <strong>{data.total_ties}</strong> total ties declared by the AI:</p>
                <p className="ml-3"><strong className="text-green-600">{data.tie_calibration.close_pairs_tied}</strong> were on close pairs (human score gap &le; 1 point) — correct abstention</p>
                <p className="ml-3"><strong className="text-red-600">{data.tie_calibration.far_pairs_tied}</strong> were on far pairs (human score gap &ge; 2 points) — missed opportunity</p>
                <p>A well-calibrated model should tie more on close pairs and less on easy pairs.</p>
              </div>
            </div>
          )}
        </>
      )}

      {!data && !loading && (
        <div className="border border-border rounded-lg p-6 text-center text-xs text-muted-foreground" data-testid="tie-no-data">
          No tie experiment data yet. Run the experiment above to see results.
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10" data-testid="tie-methodology">
        <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5" /> Methodology
        </h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Pair selection:</strong> Same cross-tier pairs as the Opus 4.6 baseline tournament. Both experiments see identical paper pairs.</li>
          <li><strong>Prompt:</strong> Modified to allow <code>{`"winner": "tie"`}</code> when the model cannot confidently distinguish papers.</li>
          <li><strong>Judges:</strong> Same 3-model round-robin (GPT-5.2, Claude Opus 4.6, Gemini 3 Pro).</li>
          <li><strong>Tie rate:</strong> Fraction of pairs where the AI declared a tie instead of picking a winner.</li>
          <li><strong>Non-tie accuracy:</strong> Among pairs where the AI did pick a winner, agreement with human expert GT.</li>
          <li><strong>Calibration:</strong> Fraction of ties that fall on close-score pairs (gap &le; 1). Higher = better calibrated.</li>
          <li><strong>McNemar's test:</strong> Statistical comparison of non-tie accuracy vs forced-choice baseline on the same pairs.</li>
        </ul>
      </div>
    </div>
  );
}
