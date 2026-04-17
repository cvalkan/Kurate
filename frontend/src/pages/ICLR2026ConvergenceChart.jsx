import { useState, useEffect } from "react";
import axios from "axios";
import { TrendingUp } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const SERIES = [
  { key: "ai_vs_avg_rating", label: "AI Pairwise vs Avg Rating", color: "#16a34a" },
  { key: "ai_vs_committee", label: "AI Pairwise vs Committee Tier", color: "#2563eb" },
];

export default function ConvergenceChart({ apiPath = "/api/validation/iclr2026-convergence" }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}${apiPath}`)
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [apiPath]);

  if (loading) return <div className="text-xs text-muted-foreground animate-pulse p-4">Loading convergence data...</div>;
  if (!data?.checkpoints?.length) return null;

  const points = data.checkpoints.filter(cp =>
    cp.total_matches > 0
    && (cp.ai_vs_avg_rating || cp.ai_vs_committee)
    && cp.avg_matches <= 30
  );
  if (points.length < 2) return null;

  const siBaseline = data.si_baseline?.rho ?? null;

  // Chart dimensions
  const W = 600, H = 260, PAD_L = 50, PAD_R = 20, PAD_T = 20, PAD_B = 40;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  const xMax = 30;
  const xMin = 0;
  const xScale = (v) => PAD_L + ((v - xMin) / (xMax - xMin)) * plotW;

  // Find y range across all series + SI baseline
  let yMin = 1, yMax = 0;
  for (const s of SERIES) {
    for (const p of points) {
      const v = p[s.key];
      if (v != null) {
        yMin = Math.min(yMin, v);
        yMax = Math.max(yMax, v);
      }
    }
  }
  if (siBaseline != null) {
    yMin = Math.min(yMin, siBaseline);
    yMax = Math.max(yMax, siBaseline);
  }
  yMin = Math.floor(yMin * 10) / 10;
  yMax = Math.ceil(yMax * 10) / 10;
  if (yMax - yMin < 0.1) { yMin -= 0.05; yMax += 0.05; }

  const yScale = (v) => PAD_T + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  // Grid lines
  const yTicks = [];
  for (let v = yMin; v <= yMax + 0.001; v += 0.05) {
    yTicks.push(Math.round(v * 100) / 100);
  }

  // X-axis ticks: dedupe to avoid overlap when many checkpoints exist
  let xTicks = points.map(p => p.avg_matches);
  if (xTicks.length > 15) {
    // Thin out: keep ~12 evenly-spaced ticks plus the first and last
    const step = Math.ceil(xTicks.length / 12);
    xTicks = xTicks.filter((_, i) => i % step === 0 || i === xTicks.length - 1);
  }

  return (
    <div className="border border-border/50 rounded overflow-hidden mt-6" data-testid="convergence-chart">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border/50">
        <h3 className="text-xs font-medium flex items-center gap-1.5">
          <TrendingUp className="h-3 w-3" />
          Correlation Convergence (Spearman rho vs matches/paper)
        </h3>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          Shows how AI-human ranking correlation improves as more pairwise matches accumulate per paper.
          Currently at {data.current_avg} avg matches/paper ({data.total_matches.toLocaleString()} total).
          {siBaseline != null && (
            <> The dashed <span style={{ color: "#ea580c" }}>orange</span> line shows the
            <strong> Single-Item baseline</strong> — Spearman ρ = <strong>{siBaseline.toFixed(3)}</strong> between
            the AI's direct per-paper score (Opus 4.6 Thinking, 1-10 scale) and human avg reviewer rating
            across {data.si_baseline.n_papers.toLocaleString()} papers. Pairwise should reach or exceed this level.</>
          )}
        </p>
      </div>
      <div className="p-4 flex justify-center">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[600px]" style={{ fontFamily: "ui-monospace, monospace" }}>
          {/* Grid */}
          {yTicks.map(v => (
            <g key={`gy-${v}`}>
              <line x1={PAD_L} x2={W - PAD_R} y1={yScale(v)} y2={yScale(v)}
                stroke="var(--border)" strokeWidth={0.5} strokeDasharray={v === 0 ? "0" : "3,3"} />
              <text x={PAD_L - 6} y={yScale(v) + 3} textAnchor="end" fontSize={9} fill="var(--muted-foreground)">{v.toFixed(2)}</text>
            </g>
          ))}
          {xTicks.map(v => (
            <g key={`gx-${v}`}>
              <line x1={xScale(v)} x2={xScale(v)} y1={PAD_T} y2={H - PAD_B}
                stroke="var(--border)" strokeWidth={0.3} strokeDasharray="2,4" />
              <text x={xScale(v)} y={H - PAD_B + 14} textAnchor="middle" fontSize={9} fill="var(--muted-foreground)">{v}</text>
            </g>
          ))}

          {/* Axis labels */}
          <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={10} fill="var(--muted-foreground)">Avg matches per paper</text>
          <text x={12} y={H / 2} textAnchor="middle" fontSize={10} fill="var(--muted-foreground)"
            transform={`rotate(-90, 12, ${H / 2})`}>Spearman rho</text>

          {/* Lines */}
          {SERIES.map(s => {
            const valid = points.filter(p => p[s.key] != null);
            if (valid.length < 2) return null;
            const path = valid.map((p, i) => `${i === 0 ? "M" : "L"}${xScale(p.avg_matches)},${yScale(p[s.key])}`).join(" ");
            return (
              <g key={s.key}>
                <path d={path} fill="none" stroke={s.color} strokeWidth={2} />
                {valid.map((p, i) => (
                  <circle key={i} cx={xScale(p.avg_matches)} cy={yScale(p[s.key])} r={3}
                    fill={s.color} stroke="var(--background)" strokeWidth={1.5} />
                ))}
              </g>
            );
          })}

          {/* Single-Item baseline — horizontal reference line */}
          {siBaseline != null && (
            <g>
              <line x1={PAD_L} x2={W - PAD_R} y1={yScale(siBaseline)} y2={yScale(siBaseline)}
                stroke="#ea580c" strokeWidth={1.5} strokeDasharray="5,3" />
              <text x={W - PAD_R - 4} y={yScale(siBaseline) - 4} textAnchor="end" fontSize={9}
                fill="#ea580c" fontWeight={600}>
                Single-Item ρ = {siBaseline.toFixed(3)}
              </text>
            </g>
          )}

          {/* Legend */}
          {SERIES.map((s, i) => (
            <g key={s.key} transform={`translate(${PAD_L + 10}, ${PAD_T + 8 + i * 16})`}>
              <line x1={0} x2={16} y1={0} y2={0} stroke={s.color} strokeWidth={2} />
              <circle cx={8} cy={0} r={2.5} fill={s.color} />
              <text x={22} y={3.5} fontSize={10} fill="var(--foreground)">{s.label}</text>
            </g>
          ))}
          {siBaseline != null && (
            <g transform={`translate(${PAD_L + 10}, ${PAD_T + 8 + SERIES.length * 16})`}>
              <line x1={0} x2={16} y1={0} y2={0} stroke="#ea580c" strokeWidth={1.5} strokeDasharray="5,3" />
              <text x={22} y={3.5} fontSize={10} fill="var(--foreground)">AI Single-Item vs Avg Rating</text>
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
