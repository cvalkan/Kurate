import { ShieldCheck } from "lucide-react";

const COLORS = {
  claude: { line: "#c084fc", bg: "bg-purple-500/10", dot: "bg-purple-500" },
  gpt: { line: "#60a5fa", bg: "bg-blue-500/10", dot: "bg-blue-500" },
  gemini: { line: "#34d399", bg: "bg-emerald-500/10", dot: "bg-emerald-500" },
};

function CoherenceChart({ models }) {
  const modelKeys = Object.keys(models).sort();
  // Find max n across all bins for bar sizing
  const allBins = modelKeys.flatMap(k => models[k].bins || []);
  const maxN = Math.max(...allBins.map(b => b.n || 0), 1);
  const binLabels = models[modelKeys[0]]?.bins?.map(b => b.label) || [];

  return (
    <div className="relative">
      {/* Y-axis label */}
      <div className="flex items-end gap-2 mb-1">
        <span className="text-[10px] text-muted-foreground font-medium">Agreement %</span>
        <div className="flex-1" />
        <span className="text-[10px] text-muted-foreground font-medium">SI score gap (|s(A) - s(B)|)</span>
      </div>

      {/* Chart area */}
      <div className="relative h-52 border-l border-b border-border/40 ml-8">
        {/* Y-axis gridlines and labels */}
        {[100, 80, 60, 40].map(pct => (
          <div key={pct} className="absolute left-0 right-0 border-t border-border/15" style={{ bottom: `${pct}%` }}>
            <span className="absolute -left-9 -top-2 text-[9px] text-muted-foreground font-mono">{pct}%</span>
          </div>
        ))}
        {/* 50% reference line */}
        <div className="absolute left-0 right-0 border-t border-dashed border-amber-400/40" style={{ bottom: "50%" }}>
          <span className="absolute right-1 -top-3 text-[8px] text-amber-600/60 font-medium">coin flip</span>
        </div>

        {/* Bin columns */}
        <div className="absolute inset-0 flex">
          {binLabels.map((label, bi) => (
            <div key={label} className="flex-1 relative flex items-end justify-center gap-px px-px">
              {/* Bars per model */}
              {modelKeys.map(mk => {
                const bin = models[mk]?.bins?.[bi];
                const rate = bin?.agreement_rate;
                if (rate == null || bin.n === 0) return <div key={mk} className="flex-1" />;
                const h = Math.max(rate * 100, 1);
                const col = COLORS[mk] || COLORS.claude;
                return (
                  <div key={mk} className="flex-1 flex flex-col items-center justify-end h-full" data-testid={`coherence-bar-${mk}-${bi}`}>
                    <div
                      className="w-full max-w-6 rounded-t-sm transition-all relative group"
                      style={{ height: `${h}%`, backgroundColor: col.line, opacity: 0.75 }}
                    >
                      <div className="absolute -top-5 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 bg-background border border-border rounded px-1 py-0.5 text-[8px] font-mono whitespace-nowrap shadow-sm z-10 pointer-events-none">
                        {(rate * 100).toFixed(1)}% (n={bin.n})
                      </div>
                    </div>
                  </div>
                );
              })}
              {/* X-axis label */}
              <span className="absolute -bottom-5 left-0 right-0 text-center text-[9px] text-muted-foreground font-mono">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 mt-7">
        {modelKeys.map(mk => {
          const m = models[mk];
          const col = COLORS[mk] || COLORS.claude;
          return (
            <div key={mk} className="flex items-center gap-1.5 text-[10px]">
              <div className={`w-2.5 h-2.5 rounded-sm ${col.dot}`} />
              <span className="font-medium">{m.label}</span>
              <span className="text-muted-foreground">({(m.overall_agreement * 100).toFixed(1)}% overall, n={m.total_pairs.toLocaleString()})</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CoherenceTable({ models }) {
  const modelKeys = Object.keys(models).sort();
  const binLabels = models[modelKeys[0]]?.bins?.map(b => b.label) || [];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border text-muted-foreground bg-secondary/5">
            <th className="py-1.5 px-2 text-left font-medium">Model</th>
            <th className="py-1.5 px-2 text-right font-medium">Overall</th>
            {binLabels.map(l => (
              <th key={l} className="py-1.5 px-1.5 text-right font-medium font-mono text-[10px]">{l}</th>
            ))}
            <th className="py-1.5 px-2 text-right font-medium">n</th>
          </tr>
        </thead>
        <tbody>
          {modelKeys.map(mk => {
            const m = models[mk];
            const col = COLORS[mk] || COLORS.claude;
            return (
              <tr key={mk} className="border-b border-border/20" data-testid={`coherence-row-${mk}`}>
                <td className="py-1.5 px-2 font-medium flex items-center gap-1.5">
                  <div className={`w-2 h-2 rounded-sm ${col.dot}`} />
                  {m.label}
                </td>
                <td className="py-1.5 px-2 text-right font-mono font-semibold">
                  {(m.overall_agreement * 100).toFixed(1)}%
                </td>
                {m.bins.map((bin, i) => {
                  const rate = bin.agreement_rate;
                  const isBest = rate != null && modelKeys.every(mk2 => {
                    const other = models[mk2]?.bins?.[i]?.agreement_rate;
                    return other == null || rate >= other;
                  });
                  return (
                    <td key={i} className={`py-1.5 px-1.5 text-right font-mono text-[10px] ${isBest ? "font-bold text-emerald-700" : ""}`}>
                      {rate != null ? `${(rate * 100).toFixed(1)}%` : "\u2014"}
                      {bin.n > 0 && <span className="text-muted-foreground/50 ml-0.5 text-[8px]">({bin.n})</span>}
                    </td>
                  );
                })}
                <td className="py-1.5 px-2 text-right font-mono text-muted-foreground">{m.total_pairs.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function CoherenceSection({ data }) {
  const coherence = data?.score_pairwise_coherence;
  if (!coherence || coherence.status !== "ok" || !coherence.models) return null;

  const models = coherence.models;
  if (Object.keys(models).length === 0) return null;

  return (
    <div className="mb-8" data-testid="coherence-section">
      <div className="mb-3">
        <h2 className="font-heading text-lg font-semibold tracking-tight flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          Score–Pairwise Coherence
        </h2>
        <p className="text-muted-foreground text-xs mt-1 max-w-2xl">
          When a model rates paper A higher than paper B (single-item score), does it also pick A in a head-to-head match?
          Bars show agreement rate by score gap. A more internally coherent model shows sharply rising bars.
        </p>
      </div>

      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-emerald-500/5 border-b border-border">
          <span className="text-xs font-semibold">Agreement rate by SI score gap</span>
          <span className="text-[10px] text-muted-foreground ml-1.5">
            (% of pairwise matches where the higher-scored paper won)
          </span>
        </div>
        <div className="p-4">
          <CoherenceChart models={models} />
        </div>
        <div className="border-t border-border">
          <CoherenceTable models={models} />
        </div>
      </div>
    </div>
  );
}
