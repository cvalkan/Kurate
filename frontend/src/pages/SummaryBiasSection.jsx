import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { AlertCircle, RefreshCw } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT 5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3";
  return m;
}

function cellColor(val, min, max) {
  if (max === min) return "bg-secondary/20";
  const t = (val - min) / (max - min);
  if (t > 0.75) return "bg-green-100 text-green-900";
  if (t > 0.5) return "bg-emerald-50 text-emerald-900";
  if (t > 0.25) return "bg-amber-50 text-amber-900";
  return "bg-orange-50 text-orange-900";
}

function HeatmapGrid({ title, description, judges, summarizers, grid }) {
  if (!grid || !grid.length) return null;
  const flat = grid.flat();
  const min = Math.min(...flat);
  const max = Math.max(...flat);

  return (
    <div className="border border-border rounded-lg p-4" data-testid="heatmap-grid">
      <h3 className="text-sm font-semibold mb-0.5">{title}</h3>
      {description && <p className="text-[10px] text-muted-foreground mb-3">{description}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="text-left px-2 py-1.5 text-[10px] font-medium text-muted-foreground w-28">
                Judge \ Summary
              </th>
              {summarizers.map(s => (
                <th key={s} className="text-center px-2 py-1.5 text-[10px] font-medium text-muted-foreground">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {judges.map((j, ri) => (
              <tr key={j}>
                <td className="px-2 py-1.5 font-medium text-xs">{j}</td>
                {grid[ri].map((val, ci) => {
                  const isSelf = judges[ri] === summarizers[ci];
                  return (
                    <td key={ci} className="text-center px-2 py-1.5">
                      <span
                        className={`inline-block px-2.5 py-1 rounded font-mono text-xs font-semibold ${cellColor(val, min, max)} ${isSelf ? "ring-2 ring-accent/40" : ""}`}
                        data-testid={`cell-${ri}-${ci}`}
                      >
                        {val.toFixed(1)}%
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-3 mt-2 text-[10px] text-muted-foreground">
        <span className="inline-block w-3 h-3 rounded ring-2 ring-accent/40 bg-secondary/20" /> = same model as judge & summarizer (self-bias indicator)
      </div>
    </div>
  );
}

function BiasCards({ selfBias }) {
  if (!selfBias) return null;
  const entries = Object.entries(selfBias);
  return (
    <div className="border border-border rounded-lg p-4" data-testid="self-bias-section">
      <h3 className="text-sm font-semibold mb-0.5">Self-Bias Detection</h3>
      <p className="text-[10px] text-muted-foreground mb-3">
        Does a judge agree with consensus more when reading its own summaries?
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {entries.map(([model, data]) => {
          const biasColor = data.bias > 2 ? "text-red-600" : data.bias > 0 ? "text-amber-600" : "text-green-600";
          return (
            <div key={model} className="border border-border/50 rounded-lg p-3 bg-secondary/5" data-testid={`bias-card-${model.replace(/\s/g, "-")}`}>
              <div className="text-xs font-semibold mb-2">{model}</div>
              <div className="space-y-1 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Own summary</span>
                  <span className="font-mono font-medium">{data.own_summary_rate.toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Other summaries (avg)</span>
                  <span className="font-mono font-medium">{data.other_summary_avg.toFixed(1)}%</span>
                </div>
                <div className="flex justify-between pt-1 border-t border-border/30">
                  <span className="text-muted-foreground">Self-bias</span>
                  <span className={`font-mono font-semibold ${biasColor}`}>
                    {data.bias > 0 ? "+" : ""}{data.bias.toFixed(1)}pp
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ConsistencySection({ judgeConsistency, summaryInfluence }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {judgeConsistency && (
        <div className="border border-border rounded-lg p-4" data-testid="judge-consistency">
          <h3 className="text-sm font-semibold mb-0.5">Judge Consistency</h3>
          <p className="text-[10px] text-muted-foreground mb-3">
            Given the same summary, how often do different judges agree?
          </p>
          <div className="space-y-2">
            {Object.entries(judgeConsistency).map(([summary, data]) => (
              <div key={summary} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{summary} summary</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 bg-secondary rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent rounded-full"
                      style={{ width: `${data.avg_agreement}%` }}
                    />
                  </div>
                  <span className="font-mono font-medium w-14 text-right">{data.avg_agreement.toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {summaryInfluence && (
        <div className="border border-border rounded-lg p-4" data-testid="summary-influence">
          <h3 className="text-sm font-semibold mb-0.5">Summary Influence</h3>
          <p className="text-[10px] text-muted-foreground mb-3">
            Given the same judge, how consistent is the verdict across different summaries?
          </p>
          <div className="space-y-2">
            {Object.entries(summaryInfluence).map(([judge, data]) => (
              <div key={judge} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{judge} as judge</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 bg-secondary rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent rounded-full"
                      style={{ width: `${data.avg_consistency}%` }}
                    />
                  </div>
                  <span className="font-mono font-medium w-14 text-right">{data.avg_consistency.toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ProgressBar({ status }) {
  if (!status || status.phase === "idle") return null;
  const { completed, total } = status.progress || {};
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const phaseLabel = status.phase === "generating_summaries"
    ? "Generating AI summaries (3 models)"
    : status.phase === "running_fullpdf"
    ? "Running full-PDF baseline (3 judges)"
    : "Running 9-config experiment";

  return (
    <div className="border border-accent/30 rounded-lg p-3 bg-accent/5 mb-4" data-testid="pipeline-progress">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="h-3 w-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        <span className="text-xs font-medium">{phaseLabel}</span>
        <span className="text-[10px] text-muted-foreground ml-auto">{completed}/{total} ({pct}%)</span>
      </div>
      <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
        <div className="h-full bg-accent transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SummaryStats({ data }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-5" data-testid="summary-stats">
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Matches Analyzed</div>
        <div className="text-xl font-semibold font-mono">{data.num_matches}</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Summary Evaluations</div>
        <div className="text-xl font-semibold font-mono">{data.total_evaluations}</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Full-PDF Baseline</div>
        <div className="text-xl font-semibold font-mono">{data.fullpdf_matches || 0}</div>
        <div className="text-[10px] text-muted-foreground">{data.fullpdf_matches ? `${data.fullpdf_matches} matches` : "not run"}</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Unanimous Agreement</div>
        <div className="text-xl font-semibold font-mono">{data.unanimous_rate}%</div>
        <div className="text-[10px] text-muted-foreground">{data.unanimous_matches}/{data.num_matches} matches</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Consensus Rate</div>
        <div className="text-xl font-semibold font-mono">{data.consensus_rate}%</div>
        <div className="text-[10px] text-muted-foreground">{data.consensus_matches}/{data.num_matches} clear majority</div>
      </div>
    </div>
  );
}

function FullPdfStats({ stats }) {
  if (!stats) return null;
  const interJudge = stats._inter_judge_agreement;
  const models = Object.entries(stats).filter(([k]) => !k.startsWith("_"));
  return (
    <div className="border border-border rounded-lg p-4" data-testid="fullpdf-stats">
      <h3 className="text-sm font-semibold mb-0.5">Full-PDF Baseline Stats</h3>
      <p className="text-[10px] text-muted-foreground mb-3">
        Each judge evaluated the same 200 matches using the full paper text (no summary). Inter-judge agreement on full PDF: <span className="font-mono font-semibold">{interJudge?.toFixed(1) ?? "—"}%</span>
      </p>
      <div className="grid grid-cols-3 gap-3">
        {models.map(([model, data]) => (
          <div key={model} className="border border-border/50 rounded-lg p-3 bg-secondary/5">
            <div className="text-xs font-semibold mb-1">{model}</div>
            <div className="text-[11px] text-muted-foreground">
              {data.matches} matches evaluated
            </div>
            {data.vs_original != null && (
              <div className="text-[11px] mt-1">
                <span className="text-muted-foreground">vs extract baseline: </span>
                <span className="font-mono font-medium">{data.vs_original.toFixed(1)}%</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const CATEGORY_LABELS = {
  "q-bio.BM": "Biomolecules",
  "econ.GN": "Economics",
};

export default function SummaryBiasSection({ category = "q-bio.BM" }) {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const catLabel = CATEGORY_LABELS[category] || category;

  const fetchData = useCallback(async () => {
    try {
      const [sRes, rRes] = await Promise.all([
        axios.get(`${API}/api/summary-bias/status?category=${category}`),
        axios.get(`${API}/api/summary-bias/results?category=${category}`),
      ]);
      setStatus(sRes.data);
      if (rRes.data.status === "ok") setResults(rRes.data);
      else setResults(null);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    setResults(null);
    fetchData();
    const iv = setInterval(fetchData, 8000);
    return () => clearInterval(iv);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-12 justify-center text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin" /> Loading...
      </div>
    );
  }

  const isRunning = status?.phase !== "idle";

  return (
    <div className="space-y-5" data-testid="summary-bias-section">
      {/* Experiment description */}
      <div className="border border-border rounded-lg p-4 bg-secondary/5">
        <p className="text-xs text-muted-foreground leading-relaxed">
          <strong>Experiment:</strong> For each paper in the {catLabel} category, 3 AI impact summaries are generated
          (one per LLM: Claude Opus, Gemini 3, GPT 5.2). Then 200 randomly selected matches are re-evaluated
          in all 9 configurations (3 judges x 3 summary sources = 1,800 evaluations).
          This reveals whether a judge is biased toward summaries written by its own model.
        </p>
      </div>

      {/* Progress */}
      <ProgressBar status={status} />

      {/* Status when no results */}
      {!results && !isRunning && (
        <div className="flex items-center gap-2 py-8 justify-center text-muted-foreground text-sm">
          <AlertCircle className="h-4 w-4" /> No experiment data yet. Pipeline needs to be triggered by admin.
        </div>
      )}

      {/* Results */}
      {results && (
        <>
          <SummaryStats data={results} />

          <HeatmapGrid
            title="Agreement with 9-Config Consensus"
            description="Each cell shows how often this (judge, summary) configuration agrees with the majority vote across all 9 configs. Highlighted cells = same model wrote summary and judged."
            judges={results.judges}
            summarizers={results.summarizers}
            grid={results.grid_consensus}
          />

          <HeatmapGrid
            title="Agreement with Original Match Result (Extract-based)"
            description="Each cell shows how often this configuration agrees with the original tournament match verdict (which used extracted sections, no summaries)."
            judges={results.judges}
            summarizers={results.summarizers}
            grid={results.grid_original}
          />

          {results.grid_fullpdf_same_judge && (
            <HeatmapGrid
              title="Agreement with Same Judge on Full PDF"
              description="Each cell shows how often the (judge, summary) verdict matches the same judge's verdict when reading the full paper PDF. This isolates summary quality by controlling for judge identity."
              judges={results.judges}
              summarizers={results.summarizers}
              grid={results.grid_fullpdf_same_judge}
            />
          )}

          {results.grid_fullpdf_majority && (
            <HeatmapGrid
              title="Agreement with Full-PDF Majority Vote"
              description="Each cell shows agreement with the 3-judge majority vote on the full PDF. This is the strongest baseline — it reflects what judges conclude with all information available."
              judges={results.judges}
              summarizers={results.summarizers}
              grid={results.grid_fullpdf_majority}
            />
          )}

          {results.fullpdf_stats && <FullPdfStats stats={results.fullpdf_stats} />}

          <BiasCards selfBias={results.self_bias} />

          <ConsistencySection
            judgeConsistency={results.judge_consistency}
            summaryInfluence={results.summary_influence}
          />
        </>
      )}
    </div>
  );
}
