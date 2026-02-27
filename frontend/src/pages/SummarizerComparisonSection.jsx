import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { Play, Square, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;
const ADMIN_HEADERS = { "X-Admin-Token": sessionStorage.getItem("admin_token") || "papersumo2025" };

export default function SummarizerComparisonSection() {
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [prevCount, setPrevCount] = useState(0);
  const pollRef = useRef(null);

  const fetchResults = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/summarizer-comparison/results`);
      setResults(r.data);
      return r.data.total_pairs || 0;
    } catch (e) { console.error(e); return 0; }
  }, []);

  useEffect(() => { fetchResults(); }, [fetchResults]);

  // Poll while running
  useEffect(() => {
    if (!running) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      const count = await fetchResults();
      // Stop polling if no progress for 2 consecutive polls
      if (count > 0 && count === prevCount) {
        // Could be done — check status
        const s = await axios.get(`${API}/api/validation/summarizer-comparison/status`);
        if (!s.data.is_running) {
          setRunning(false);
        }
      }
      setPrevCount(count);
    }, 5000);
    return () => clearInterval(pollRef.current);
  }, [running, prevCount, fetchResults]);

  const runComparison = async () => {
    setPrevCount(results?.total_pairs || 0);
    setRunning(true);
    try {
      await axios.post(`${API}/api/validation/summarizer-comparison/run`,
        { num_pairs: 200, parallel: 8 },
        { headers: ADMIN_HEADERS });
    } catch (e) {
      setRunning(false);
    }
  };

  const stopComparison = async () => {
    try {
      await axios.post(`${API}/api/validation/summarizer-comparison/stop`, {}, { headers: ADMIN_HEADERS });
    } catch (e) { console.error(e); }
    setRunning(false);
    fetchResults();
  };

  const total = results?.total_pairs || 0;
  const hasData = results?.status === "ok" && total > 0;

  return (
    <div className="space-y-4" data-testid="summarizer-comparison">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground">
            Each paper pair has a known correct answer from <strong>committee decisions</strong> (ICLR accept/reject tiers),{" "}
            <strong>reviewer majority</strong> (score consensus), or <strong>editorial assessment</strong> (eLife significance).{" "}
            Only non-tie pairs (where ground truth has a clear winner) are included.{" "}
            The AI judge sees abstract + summary and picks a winner — we measure which summarizer leads to more correct picks.
          </p>
        </div>
        <div className="flex gap-2 shrink-0 items-center">
          {running ? (
            <>
              <span className="text-xs text-muted-foreground animate-pulse flex items-center gap-1">
                <RefreshCw className="h-3 w-3 animate-spin" /> Running... {total} pairs done
              </span>
              <Button size="sm" variant="destructive" className="gap-1.5 text-xs" onClick={stopComparison}>
                <Square className="h-3 w-3" /> Stop
              </Button>
            </>
          ) : (
            <Button size="sm" className="gap-1.5 text-xs" onClick={runComparison}>
              <Play className="h-3 w-3" /> {total > 0 ? "+200 pairs" : "Run 200 pairs"}
            </Button>
          )}
        </div>
      </div>

      {!hasData && !running && (
        <div className="border border-border rounded-lg p-6 text-center text-sm text-muted-foreground">
          No comparison data yet. Click 'Run 200 pairs' to start.
        </div>
      )}

      {hasData && (
        <>
          {/* Overall accuracy */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <ScoreCard label="Opus 4.5 Accuracy" value={`${results.opus45_accuracy}%`}
              sub={`${Math.round(results.opus45_accuracy * total / 100)}/${total} correct`}
              color={results.opus45_accuracy >= results.opus46_accuracy ? "text-green-600" : "text-muted-foreground"} />
            <ScoreCard label="Opus 4.6 Accuracy" value={`${results.opus46_accuracy}%`}
              sub={`${Math.round(results.opus46_accuracy * total / 100)}/${total} correct`}
              color={results.opus46_accuracy >= results.opus45_accuracy ? "text-green-600" : "text-muted-foreground"} />
            <ScoreCard label="Both Correct" value={results.both_correct} sub={`${(results.both_correct / total * 100).toFixed(1)}% of pairs`} />
            <ScoreCard label="Neither Correct" value={results.neither_correct} sub={`${(results.neither_correct / total * 100).toFixed(1)}% of pairs`} />
          </div>

          {/* Unique wins */}
          <div className="grid grid-cols-2 gap-3">
            <div className="border border-border rounded-lg p-3 text-center">
              <div className="text-[10px] text-muted-foreground mb-1">Opus 4.5 wins exclusively</div>
              <div className="text-lg font-semibold text-amber-600">{results.opus45_only}</div>
              <div className="text-[10px] text-muted-foreground">pairs where only 4.5 was correct</div>
            </div>
            <div className="border border-border rounded-lg p-3 text-center">
              <div className="text-[10px] text-muted-foreground mb-1">Opus 4.6 wins exclusively</div>
              <div className="text-lg font-semibold text-blue-600">{results.opus46_only}</div>
              <div className="text-[10px] text-muted-foreground">pairs where only 4.6 was correct</div>
            </div>
          </div>

          {/* By dataset */}
          {results.by_dataset && Object.keys(results.by_dataset).length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium">Accuracy by Dataset</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-left px-3 py-1.5">Dataset</th>
                      <th className="text-right px-3 py-1.5">Pairs</th>
                      <th className="text-right px-3 py-1.5">Opus 4.5</th>
                      <th className="text-right px-3 py-1.5">Opus 4.6</th>
                      <th className="text-right px-3 py-1.5">Winner</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(results.by_dataset).sort((a, b) => b[1].total - a[1].total).map(([ds, v]) => (
                      <tr key={ds} className="border-b border-border/20">
                        <td className="px-3 py-1.5 font-medium">{ds}</td>
                        <td className="text-right px-3 py-1.5">{v.total}</td>
                        <td className={`text-right px-3 py-1.5 font-mono ${v.opus45_pct >= v.opus46_pct ? "font-semibold text-green-600" : ""}`}>{v.opus45_pct}%</td>
                        <td className={`text-right px-3 py-1.5 font-mono ${v.opus46_pct >= v.opus45_pct ? "font-semibold text-green-600" : ""}`}>{v.opus46_pct}%</td>
                        <td className="text-right px-3 py-1.5">{v.opus45_pct > v.opus46_pct ? "4.5" : v.opus46_pct > v.opus45_pct ? "4.6" : "Tie"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* By ground truth type */}
          {results.by_ground_truth && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {[
                ["Committee Decision", results.by_ground_truth.committee_decision, "ICLR/MIDL accept tiers (Oral > Spotlight > Poster > Reject)"],
                ["Reviewer Majority", results.by_ground_truth.reviewer_majority, "Consensus of 2+ reviewer scores"],
                ["Editorial Assessment", results.by_ground_truth.editorial_assessment, "eLife significance labels (useful < valuable < important < fundamental)"],
              ].map(([label, data, desc]) => data?.total > 0 && (
                <div key={label} className="border border-border rounded-lg p-3">
                  <div className="text-[10px] font-medium mb-1">{label}</div>
                  <div className="text-[9px] text-muted-foreground mb-2">{desc}</div>
                  <div className="space-y-1.5">
                    {data.single_reviewer_pct !== undefined && (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="w-28 text-muted-foreground">Single reviewer:</span>
                        <span className="font-mono font-medium">{data.single_reviewer_pct}%</span>
                        <span className="text-[9px] text-muted-foreground">({data.single_reviewer_paper_pairs} paper pairs)</span>
                      </div>
                    )}
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-28 text-amber-600">AI + Opus 4.5:</span>
                      <span className={`font-mono font-medium ${data.opus45_pct >= (data.single_reviewer_pct || 0) ? "text-green-600" : ""}`}>{data.opus45_pct}%</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-28 text-blue-600">AI + Opus 4.6:</span>
                      <span className={`font-mono font-medium ${data.opus46_pct >= (data.single_reviewer_pct || 0) ? "text-green-600" : ""}`}>{data.opus46_pct}%</span>
                    </div>
                    <div className="text-[9px] text-muted-foreground mt-1">{data.total} paper pairs</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* By score gap */}
          {results.by_gap && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium">Accuracy by Human Score Gap</h3>
                <p className="text-[9px] text-muted-foreground">Harder pairs (small gap) test whether the AI can distinguish papers that even human reviewers disagree on</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-border text-[10px]">
                      <th className="text-left px-3 py-1.5">Score Gap</th>
                      <th className="text-right px-3 py-1.5">Pairs</th>
                      <th className="text-right px-3 py-1.5">Human</th>
                      <th className="text-right px-3 py-1.5">Opus 4.5</th>
                      <th className="text-right px-3 py-1.5">Opus 4.6</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(results.by_gap).filter(([,d]) => d.total > 0).map(([gap, data]) => (
                      <tr key={gap} className="border-b border-border/20">
                        <td className="px-3 py-1.5 font-medium">{gap}</td>
                        <td className="text-right px-3 py-1.5">{data.total}</td>
                        <td className="text-right px-3 py-1.5 font-mono text-muted-foreground">{data.human_pct != null ? `${data.human_pct}%` : "—"}</td>
                        <td className="text-right px-3 py-1.5 font-mono text-amber-600">{(data.opus45 / data.total * 100).toFixed(1)}%</td>
                        <td className="text-right px-3 py-1.5 font-mono text-blue-600">{(data.opus46 / data.total * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ScoreCard({ label, value, sub, color = "" }) {
  return (
    <div className="border border-border rounded-lg p-3 text-center">
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}
