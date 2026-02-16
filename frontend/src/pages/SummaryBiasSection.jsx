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
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5" data-testid="summary-stats">
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Matches Analyzed</div>
        <div className="text-xl font-semibold font-mono">{data.num_matches}</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Summary Evaluations</div>
        <div className="text-xl font-semibold font-mono">{data.total_evaluations}</div>
        <div className="text-[10px] text-muted-foreground">9 configs per match</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">Full-PDF Evaluations</div>
        <div className="text-xl font-semibold font-mono">{(data.fullpdf_matches || 0) * 3}</div>
        <div className="text-[10px] text-muted-foreground">3 judges per match</div>
      </div>
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="text-[10px] text-muted-foreground">All 9 Configs Agree</div>
        <div className="text-xl font-semibold font-mono">{data.unanimous_rate}%</div>
        <div className="text-[10px] text-muted-foreground">{data.unanimous_matches}/{data.num_matches} matches</div>
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

function ConvergenceChart({ data }) {
  if (!data || !data.curve || data.curve.length < 2) return null;
  const { curve, extract_curve, summarizer_curves, config_correlations, total_extract_matches, total_fullpdf_matches, total_consensus_matches, papers } = data;

  return (
    <div className="space-y-5" data-testid="convergence-section">
      {/* Chart 1: Internal convergence (x = consensus matches) */}
      <InternalConvergenceChart curve={curve} total_consensus_matches={total_consensus_matches} papers={papers} />

      {/* Chart 2: Apples-to-apples comparison (x = avg matches per paper) */}
      <ComparisonChart curve={curve} extract_curve={extract_curve} total_consensus_matches={total_consensus_matches} total_extract_matches={total_extract_matches} papers={papers} />

      {/* Per-config table */}
      {config_correlations && Object.keys(config_correlations).length > 0 && (
        <div className="border border-border rounded-lg p-4">
          <h4 className="text-xs font-semibold mb-1.5">Per-Config Ranking Correlation (200 matches each)</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-2 py-1 font-medium text-[10px] text-muted-foreground">Configuration</th>
                  <th className="text-right px-2 py-1 font-medium text-[10px] text-muted-foreground">vs Extract</th>
                  <th className="text-right px-2 py-1 font-medium text-[10px] text-muted-foreground">vs Full PDF</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(config_correlations).map(([ck, d]) => (
                  <tr key={ck} className="border-b border-border/20">
                    <td className="px-2 py-1 text-xs">{d.label}</td>
                    <td className="text-right px-2 py-1 font-mono">{d.vs_extract?.toFixed(3) ?? "—"}</td>
                    <td className="text-right px-2 py-1 font-mono">{d.vs_fullpdf?.toFixed(3) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function InternalConvergenceChart({ curve, total_consensus_matches, papers }) {
  const W = 600, H = 240, PAD = { t: 20, r: 20, b: 40, l: 50 };
  const cw = W - PAD.l - PAD.r, ch = H - PAD.t - PAD.b;

  const maxX = Math.max(...curve.map(p => p.matches));
  const allY = curve.flatMap(p => [p.vs_extract_spearman, p.vs_fullpdf_spearman, p.vs_final_spearman].filter(v => v != null));
  const yMin = Math.max(0, Math.floor(Math.min(...allY) * 10) / 10 - 0.1);

  const sx = x => PAD.l + (x / maxX) * cw;
  const sy = y => PAD.t + (1 - (y - yMin) / (1.0 - yMin)) * ch;

  const lines = [
    { key: "vs_extract_spearman", color: "#2563eb", label: "vs Extract tournament" },
    { key: "vs_fullpdf_spearman", color: "#059669", label: "vs Full-PDF baseline" },
    { key: "vs_final_spearman", color: "#9333ea", label: "Internal stability" },
  ];

  const makePath = (key) => {
    const pts = curve.filter(p => p[key] != null);
    if (pts.length < 2) return null;
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.matches).toFixed(1)},${sy(p[key]).toFixed(1)}`).join(" ");
  };

  return (
    <div className="border border-border rounded-lg p-4 space-y-3">
      <div>
        <h3 className="text-sm font-semibold mb-0.5">Summary Ranking Convergence</h3>
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          How the summary-based BT ranking evolves as more consensus matches are added.
          <strong> Purple</strong> = internal stability (how stable is the ranking). <strong>Green</strong> = correlation with the full-PDF ranking (accuracy).
          <strong> Blue</strong> = correlation with the extract tournament ({total_consensus_matches} summary matches vs the full extract tournament).
          The ranking stabilizes quickly and reaches high correlation with full-PDF by ~100 matches ({papers} papers).
        </p>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[600px]">
        {[0.2, 0.4, 0.6, 0.8, 1.0].filter(v => v >= yMin).map(v => (
          <g key={v}>
            <line x1={PAD.l} y1={sy(v)} x2={W - PAD.r} y2={sy(v)} stroke="#e5e7eb" strokeWidth="0.5" />
            <text x={PAD.l - 4} y={sy(v) + 3} textAnchor="end" fontSize="8" fill="#9ca3af">{v.toFixed(1)}</text>
          </g>
        ))}
        {curve.filter((_, i) => i % Math.max(1, Math.floor(curve.length / 5)) === 0 || i === curve.length - 1).map(p => (
          <text key={p.matches} x={sx(p.matches)} y={H - 8} textAnchor="middle" fontSize="8" fill="#9ca3af">{p.matches}</text>
        ))}
        <text x={PAD.l + cw / 2} y={H} textAnchor="middle" fontSize="8" fill="#9ca3af">Consensus matches</text>
        <text x={4} y={PAD.t + ch / 2} textAnchor="middle" fontSize="8" fill="#9ca3af" transform={`rotate(-90,4,${PAD.t + ch / 2})`}>Spearman ρ</text>
        {lines.map(({ key, color }) => {
          const d = makePath(key);
          return d ? <path key={key} d={d} fill="none" stroke={color} strokeWidth="2" /> : null;
        })}
        {lines.map(({ key, color }) => {
          const last = [...curve].reverse().find(p => p[key] != null);
          return last ? <circle key={key + "d"} cx={sx(last.matches)} cy={sy(last[key])} r="3" fill={color} /> : null;
        })}
      </svg>
      <div className="flex flex-wrap gap-4 text-[10px]">
        {lines.map(({ key, color, label }) => {
          const last = [...curve].reverse().find(p => p[key] != null);
          return last ? (
            <div key={key} className="flex items-center gap-1.5">
              <div className="w-3 h-0.5 rounded" style={{ backgroundColor: color }} />
              <span className="text-muted-foreground">{label}:</span>
              <span className="font-mono font-medium">{last[key]?.toFixed(3)}</span>
            </div>
          ) : null;
        })}
      </div>
    </div>
  );
}

function ComparisonChart({ curve, extract_curve, total_consensus_matches, total_extract_matches, papers }) {
  if (!extract_curve || extract_curve.length < 2) return null;

  const W = 620, H = 260, PAD = { t: 20, r: 20, b: 44, l: 50 };
  const cw = W - PAD.l - PAD.r, ch = H - PAD.t - PAD.b;

  const allAvg = [
    ...curve.map(p => p.avg_matches_per_paper),
    ...extract_curve.map(p => p.avg_matches_per_paper),
  ];
  const maxX = Math.max(...allAvg);
  const allY = [
    ...curve.flatMap(p => [p.vs_fullpdf_spearman].filter(v => v != null)),
    ...extract_curve.flatMap(p => [p.vs_fullpdf_spearman].filter(v => v != null)),
  ];
  const yMin = Math.max(0, Math.floor(Math.min(...allY) * 10) / 10 - 0.1);

  const sx = x => PAD.l + (x / maxX) * cw;
  const sy = y => PAD.t + (1 - (y - yMin) / (1.0 - yMin)) * ch;

  const makePath = (points, key, xKey) => {
    const pts = points.filter(p => p[key] != null);
    if (pts.length < 2) return null;
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p[xKey]).toFixed(1)},${sy(p[key]).toFixed(1)}`).join(" ");
  };

  const summaryPath = makePath(curve, "vs_fullpdf_spearman", "avg_matches_per_paper");
  const extractPath = makePath(extract_curve, "vs_fullpdf_spearman", "avg_matches_per_paper");
  const lastSummary = [...curve].reverse().find(p => p.vs_fullpdf_spearman != null);
  const lastExtract = [...extract_curve].reverse().find(p => p.vs_fullpdf_spearman != null);

  return (
    <div className="border border-border rounded-lg p-4 space-y-3">
      <div>
        <h3 className="text-sm font-semibold mb-0.5">Summary vs Extract: Convergence to Full-PDF Ranking</h3>
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          Apples-to-apples comparison: both curves use the same x-axis (avg matches per paper) and measure correlation with the same full-PDF ranking.
          The <strong>green</strong> line (abstract + summary) converges faster and higher than the <strong>orange dashed</strong> line (section extracts).
          At ~5 matches/paper, summaries already outperform extracts at ~40 matches/paper.
          Summary data: {total_consensus_matches} matches. Extract data: {total_extract_matches?.toLocaleString()} matches. {papers} papers.
        </p>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[620px]">
        {[0.2, 0.4, 0.6, 0.8, 1.0].filter(v => v >= yMin).map(v => (
          <g key={v}>
            <line x1={PAD.l} y1={sy(v)} x2={W - PAD.r} y2={sy(v)} stroke="#e5e7eb" strokeWidth="0.5" />
            <text x={PAD.l - 4} y={sy(v) + 3} textAnchor="end" fontSize="8" fill="#9ca3af">{v.toFixed(1)}</text>
          </g>
        ))}
        {[2, 5, 10, 15, 20, 30, 40, 60, 80].filter(v => v <= maxX * 1.05).map(v => (
          <text key={v} x={sx(v)} y={H - 12} textAnchor="middle" fontSize="8" fill="#9ca3af">{v}</text>
        ))}
        <text x={PAD.l + cw / 2} y={H - 1} textAnchor="middle" fontSize="8" fill="#9ca3af">Avg matches per paper</text>
        <text x={4} y={PAD.t + ch / 2} textAnchor="middle" fontSize="8" fill="#9ca3af" transform={`rotate(-90,4,${PAD.t + ch / 2})`}>Spearman ρ vs Full PDF</text>

        {extractPath && <path d={extractPath} fill="none" stroke="#f59e0b" strokeWidth="2" strokeDasharray="6,3" />}
        {lastExtract && <circle cx={sx(lastExtract.avg_matches_per_paper)} cy={sy(lastExtract.vs_fullpdf_spearman)} r="3" fill="#f59e0b" />}

        {summaryPath && <path d={summaryPath} fill="none" stroke="#059669" strokeWidth="2.5" />}
        {lastSummary && <circle cx={sx(lastSummary.avg_matches_per_paper)} cy={sy(lastSummary.vs_fullpdf_spearman)} r="3.5" fill="#059669" />}
      </svg>
      <div className="flex flex-wrap gap-5 text-[10px]">
        {lastSummary && (
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-0.5 rounded bg-emerald-600" />
            <span className="text-muted-foreground">Abstract + Summary (consensus):</span>
            <span className="font-mono font-semibold">ρ = {lastSummary.vs_fullpdf_spearman?.toFixed(3)}</span>
            <span className="text-muted-foreground">@ {lastSummary.avg_matches_per_paper} avg/paper</span>
          </div>
        )}
        {lastExtract && (
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-0.5 rounded" style={{ background: "repeating-linear-gradient(90deg, #f59e0b 0 4px, transparent 4px 7px)" }} />
            <span className="text-muted-foreground">Extract (sections):</span>
            <span className="font-mono font-semibold">ρ = {lastExtract.vs_fullpdf_spearman?.toFixed(3)}</span>
            <span className="text-muted-foreground">@ {lastExtract.avg_matches_per_paper} avg/paper</span>
          </div>
        )}
      </div>
    </div>
  );
}

const SUMMARIZER_COLORS = {
  "Claude Opus": "#8b5cf6",
  "Gemini 3": "#059669",
  "GPT 5.2": "#2563eb",
};

function SummarizerConvergenceChart({ summarizer_curves, extract_curve, papers }) {
  if (!summarizer_curves || Object.keys(summarizer_curves).length < 2) return null;

  const W = 620, H = 260, PAD = { t: 20, r: 20, b: 44, l: 50 };
  const cw = W - PAD.l - PAD.r, ch = H - PAD.t - PAD.b;

  const allPts = Object.values(summarizer_curves).flat();
  const extPts = extract_curve || [];
  const allAvg = [...allPts.map(p => p.avg_matches_per_paper), ...extPts.map(p => p.avg_matches_per_paper)];
  const maxX = Math.max(...allAvg);
  const allY = [...allPts, ...extPts].map(p => p.vs_fullpdf_spearman).filter(v => v != null);
  const yMin = Math.max(0, Math.floor(Math.min(...allY) * 10) / 10 - 0.1);

  const sx = x => PAD.l + (x / maxX) * cw;
  const sy = y => PAD.t + (1 - (y - yMin) / (1.0 - yMin)) * ch;

  const makePath = (points) => {
    const pts = points.filter(p => p.vs_fullpdf_spearman != null);
    if (pts.length < 2) return null;
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.avg_matches_per_paper).toFixed(1)},${sy(p.vs_fullpdf_spearman).toFixed(1)}`).join(" ");
  };

  const entries = Object.entries(summarizer_curves);
  const extractPath = extPts.length >= 2 ? makePath(extPts) : null;
  const lastExtract = extPts.length ? [...extPts].reverse().find(p => p.vs_fullpdf_spearman != null) : null;

  return (
    <div className="border border-border rounded-lg p-4 space-y-3">
      <div>
        <h3 className="text-sm font-semibold mb-0.5">Convergence by Summary Model</h3>
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          For each summary model, the 3 judges' majority vote is used to build a tournament ranking. Each curve shows how fast that
          summarizer's ranking converges to the full-PDF baseline. The <strong>orange dashed</strong> line shows the extract-based tournament for reference.
          This reveals which summary model produces the most efficient ranking signal per match.
        </p>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[620px]">
        {[0.2, 0.4, 0.6, 0.8, 1.0].filter(v => v >= yMin).map(v => (
          <g key={v}>
            <line x1={PAD.l} y1={sy(v)} x2={W - PAD.r} y2={sy(v)} stroke="#e5e7eb" strokeWidth="0.5" />
            <text x={PAD.l - 4} y={sy(v) + 3} textAnchor="end" fontSize="8" fill="#9ca3af">{v.toFixed(1)}</text>
          </g>
        ))}
        {[2, 5, 10, 15, 20, 30, 40, 60, 80].filter(v => v <= maxX * 1.05).map(v => (
          <text key={v} x={sx(v)} y={H - 12} textAnchor="middle" fontSize="8" fill="#9ca3af">{v}</text>
        ))}
        <text x={PAD.l + cw / 2} y={H - 1} textAnchor="middle" fontSize="8" fill="#9ca3af">Avg matches per paper</text>
        <text x={4} y={PAD.t + ch / 2} textAnchor="middle" fontSize="8" fill="#9ca3af" transform={`rotate(-90,4,${PAD.t + ch / 2})`}>Spearman ρ vs Full PDF</text>

        {/* Extract reference (dashed) */}
        {extractPath && <path d={extractPath} fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="6,3" />}
        {lastExtract && <circle cx={sx(lastExtract.avg_matches_per_paper)} cy={sy(lastExtract.vs_fullpdf_spearman)} r="2.5" fill="#f59e0b" />}

        {/* Per-summarizer curves */}
        {entries.map(([name, points]) => {
          const d = makePath(points);
          const color = SUMMARIZER_COLORS[name] || "#666";
          const last = [...points].reverse().find(p => p.vs_fullpdf_spearman != null);
          return d ? (
            <g key={name}>
              <path d={d} fill="none" stroke={color} strokeWidth="2" />
              {last && <circle cx={sx(last.avg_matches_per_paper)} cy={sy(last.vs_fullpdf_spearman)} r="3" fill={color} />}
            </g>
          ) : null;
        })}
      </svg>
      <div className="flex flex-wrap gap-4 text-[10px]">
        {entries.map(([name, points]) => {
          const last = [...points].reverse().find(p => p.vs_fullpdf_spearman != null);
          const color = SUMMARIZER_COLORS[name] || "#666";
          return last ? (
            <div key={name} className="flex items-center gap-1.5">
              <div className="w-3 h-0.5 rounded" style={{ backgroundColor: color }} />
              <span className="text-muted-foreground">{name} summary:</span>
              <span className="font-mono font-semibold">ρ = {last.vs_fullpdf_spearman?.toFixed(3)}</span>
            </div>
          ) : null;
        })}
        {lastExtract && (
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 rounded" style={{ background: "repeating-linear-gradient(90deg, #f59e0b 0 3px, transparent 3px 6px)" }} />
            <span className="text-muted-foreground">Extract:</span>
            <span className="font-mono font-semibold">ρ = {lastExtract.vs_fullpdf_spearman?.toFixed(3)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

const CATEGORY_LABELS = {
  "q-bio.BM": "Biomolecules",
  "econ.GN": "Economics",
  "physics.comp-ph": "Computational Physics",
};

export default function SummaryBiasSection({ category = "q-bio.BM" }) {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [convergence, setConvergence] = useState(null);
  const [loading, setLoading] = useState(true);
  const catLabel = CATEGORY_LABELS[category] || category;

  const fetchData = useCallback(async () => {
    try {
      const [sRes, rRes, cRes] = await Promise.all([
        axios.get(`${API}/api/summary-bias/status?category=${category}`),
        axios.get(`${API}/api/summary-bias/results?category=${category}`),
        axios.get(`${API}/api/summary-bias/convergence?category=${category}`).catch(() => ({ data: {} })),
      ]);
      setStatus(sRes.data);
      if (rRes.data.status === "ok") setResults(rRes.data);
      else setResults(null);
      if (cRes.data.status === "ok") setConvergence(cRes.data);
      else setConvergence(null);
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

          {convergence && <ConvergenceChart data={convergence} />}
        </>
      )}
    </div>
  );
}
