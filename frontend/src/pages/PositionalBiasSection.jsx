import { useState, useEffect } from "react";
import axios from "axios";
import { Crosshair, AlertTriangle, CheckCircle, Info } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const MODEL_COLORS = {
  "gpt-5.2": "#3b82f6",
  "gpt-5.4": "#2563eb",
  "claude-opus-4-5-20251101": "#8b5cf6",
  "claude-opus-4-6": "#a78bfa",
  "gemini-3-pro-preview": "#f59e0b",
};

const MODEL_LABELS = {
  "gpt-5.2": "GPT-5.2",
  "gpt-5.4": "GPT-5.4",
  "claude-opus-4-5-20251101": "Claude Opus 4.5",
  "claude-opus-4-6": "Claude Opus 4.6",
  "gemini-3-pro-preview": "Gemini 3 Pro",
};

function BiasBar({ pos1Rate, color, label, total, pValue, significant }) {
  const pos2Rate = 100 - pos1Rate;
  const biasDir = pos1Rate > 50 ? "first" : pos1Rate < 50 ? "second" : "none";
  const magnitude = Math.abs(pos1Rate - 50);

  return (
    <div className="space-y-1.5" data-testid={`bias-bar-${label}`}>
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium" style={{ color }}>{MODEL_LABELS[label] || label}</span>
        <span className="text-muted-foreground font-mono">{total.toLocaleString()} matches</span>
      </div>
      <div className="relative h-7 rounded-md overflow-hidden bg-secondary/20 flex">
        <div
          className="h-full flex items-center justify-end pr-2 text-[10px] font-mono font-medium transition-all duration-700"
          style={{
            width: `${pos1Rate}%`,
            backgroundColor: `${color}30`,
            borderRight: "2px solid var(--border)",
            color,
          }}
        >
          {pos1Rate.toFixed(1)}%
        </div>
        <div
          className="h-full flex items-center justify-start pl-2 text-[10px] font-mono font-medium text-muted-foreground transition-all duration-700"
          style={{ width: `${pos2Rate}%` }}
        >
          {pos2Rate.toFixed(1)}%
        </div>
        {/* 50% center line */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-foreground/20 pointer-events-none" />
      </div>
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
        {significant ? (
          <span className="flex items-center gap-1 text-amber-600">
            <AlertTriangle className="h-3 w-3" />
            Significant bias toward {biasDir} position (+{magnitude.toFixed(1)}pp, p={pValue < 0.001 ? "<0.001" : pValue.toFixed(3)})
          </span>
        ) : (
          <span className="flex items-center gap-1 text-emerald-600">
            <CheckCircle className="h-3 w-3" />
            No significant bias (p={pValue.toFixed(3)})
          </span>
        )}
      </div>
    </div>
  );
}

export default function PositionalBiasSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/positional-bias`)
      .then(r => setData(r.data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-sm text-muted-foreground animate-pulse p-4">Loading positional bias data...</div>;
  if (error) return <div className="text-sm text-destructive p-4">Error: {error}</div>;
  if (!data?.models?.length) return <div className="text-sm text-muted-foreground p-4">No match data available yet.</div>;

  const { models, overall } = data;

  return (
    <div className="space-y-6 mb-6" data-testid="positional-bias-section">
      {/* Section header */}
      <div className="flex items-center gap-2 pt-4">
        <Crosshair className="h-5 w-5 text-accent" />
        <div>
          <h2 className="font-heading text-base md:text-lg font-semibold" data-testid="positional-bias-title">Positional Bias</h2>
          <p className="text-xs text-muted-foreground">Does the order in which papers are presented affect which one wins?</p>
        </div>
      </div>

      {/* Methodology note */}
      <div className="border border-border rounded-lg p-3 bg-secondary/5">
        <div className="flex items-start gap-2">
          <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div className="text-xs text-muted-foreground space-y-1">
            <p>
              LLM judges may develop a preference for whichever paper appears first (or second) in the prompt,
              regardless of content — a phenomenon known as <strong>positional bias</strong>. To measure this,
              the pipeline randomly flips the presentation order for 50% of matches and tracks which position wins.
            </p>
            <p>
              A perfectly unbiased model would pick position 1 exactly 50% of the time. Significance is assessed
              via an exact binomial test (H<sub>0</sub>: p = 0.5).
            </p>
          </div>
        </div>
      </div>

      {/* Overall bar */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Crosshair className="h-3 w-3" />
            Overall (All Models Combined)
          </h3>
        </div>
        <div className="p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="text-xs text-muted-foreground">Paper shown 1st</div>
            <div className="flex-1" />
            <div className="text-xs text-muted-foreground">Paper shown 2nd</div>
          </div>
          <div className="relative h-9 rounded-md overflow-hidden bg-secondary/20 flex">
            <div
              className="h-full flex items-center justify-center text-xs font-mono font-semibold transition-all duration-700"
              style={{
                width: `${overall.pos1_rate}%`,
                backgroundColor: "rgba(99, 102, 241, 0.15)",
                color: "rgb(99, 102, 241)",
              }}
            >
              {overall.pos1_rate.toFixed(1)}%
            </div>
            <div
              className="h-full flex items-center justify-center text-xs font-mono font-semibold text-muted-foreground transition-all duration-700"
              style={{ width: `${100 - overall.pos1_rate}%` }}
            >
              {(100 - overall.pos1_rate).toFixed(1)}%
            </div>
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-foreground/30 pointer-events-none" />
          </div>
          <div className="mt-2 text-center text-[10px] text-muted-foreground">
            {overall.total.toLocaleString()} matches
            {" · "}
            {overall.significant ? (
              <span className="text-amber-600">Significant positional bias detected (p={overall.p_value < 0.001 ? "<0.001" : overall.p_value.toFixed(4)})</span>
            ) : (
              <span className="text-emerald-600">No significant overall bias (p={overall.p_value.toFixed(4)})</span>
            )}
          </div>
        </div>
      </div>

      {/* Per-model bars */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Crosshair className="h-3 w-3" />
            By Model
          </h3>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            Position 1 win rate for each judge model. Center line = 50% (no bias).
          </p>
        </div>
        <div className="p-4 space-y-5">
          {models.map(m => (
            <BiasBar
              key={m.model}
              label={m.model}
              pos1Rate={m.pos1_rate}
              color={MODEL_COLORS[m.model] || "#6b7280"}
              total={m.total}
              pValue={m.p_value}
              significant={m.significant}
            />
          ))}
        </div>
      </div>

      {/* Summary table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium">Detailed Statistics</h3>
        </div>
        <div className="p-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-[10px]">
                <th className="text-left py-1.5 pr-3 font-medium">Model</th>
                <th className="text-right py-1.5 px-2 font-medium">Matches</th>
                <th className="text-right py-1.5 px-2 font-medium">Pos 1 Wins</th>
                <th className="text-right py-1.5 px-2 font-medium">Pos 2 Wins</th>
                <th className="text-right py-1.5 px-2 font-medium">Pos 1 Rate</th>
                <th className="text-right py-1.5 px-2 font-medium">Bias</th>
                <th className="text-right py-1.5 px-2 font-medium">p-value</th>
              </tr>
            </thead>
            <tbody>
              {models.map(m => (
                <tr key={m.model} className="border-b border-border/30">
                  <td className="py-2 pr-3 font-medium" style={{ color: MODEL_COLORS[m.model] }}>
                    {MODEL_LABELS[m.model] || m.model}
                  </td>
                  <td className="text-right py-2 px-2 font-mono">{m.total.toLocaleString()}</td>
                  <td className="text-right py-2 px-2 font-mono">{m.pos1_wins.toLocaleString()}</td>
                  <td className="text-right py-2 px-2 font-mono">{m.pos2_wins.toLocaleString()}</td>
                  <td className="text-right py-2 px-2 font-mono">{m.pos1_rate.toFixed(1)}%</td>
                  <td className="text-right py-2 px-2 font-mono">
                    <span className={m.significant ? "text-amber-600" : "text-emerald-600"}>
                      {m.bias_magnitude.toFixed(1)}pp {m.bias_direction === "first" ? "→1st" : "→2nd"}
                    </span>
                  </td>
                  <td className="text-right py-2 px-2 font-mono">
                    {m.p_value < 0.001 ? "<0.001" : m.p_value.toFixed(4)}
                    {m.significant && " *"}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-border font-medium">
                <td className="py-2 pr-3">Overall</td>
                <td className="text-right py-2 px-2 font-mono">{overall.total.toLocaleString()}</td>
                <td className="text-right py-2 px-2 font-mono">{overall.pos1_wins.toLocaleString()}</td>
                <td className="text-right py-2 px-2 font-mono">{overall.pos2_wins.toLocaleString()}</td>
                <td className="text-right py-2 px-2 font-mono">{overall.pos1_rate.toFixed(1)}%</td>
                <td className="text-right py-2 px-2 font-mono">
                  <span className={overall.significant ? "text-amber-600" : "text-emerald-600"}>
                    {Math.abs(overall.pos1_rate - 50).toFixed(1)}pp
                  </span>
                </td>
                <td className="text-right py-2 px-2 font-mono">
                  {overall.p_value < 0.001 ? "<0.001" : overall.p_value.toFixed(4)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
