import { useEffect, useRef, useState, useCallback } from "react";
import { Activity, Copy, AlertTriangle, Timer } from "lucide-react";
import { usePerfDebounce } from "./_shared";

/**
 * Phase 0 instrumentation overlay.
 *
 * Subscribes to:
 *  - `performance.measure` entries (filter, sort, histogram, render, data:fetch/parse/flatten)
 *  - `longtask` PerformanceObserver entries
 *
 * Surfaces the most recent value per measurement type plus a rolling window of long tasks.
 * A "Copy trace" button serializes the full measurement timeline as JSON for sharing.
 */

const TRACKED = [
  { key: "data:fetch",     label: "Fetch",      hint: "Network + body download" },
  { key: "data:parse",     label: "Parse",      hint: "JSON.parse on the response text" },
  { key: "data:flatten",   label: "Flatten",    hint: "Promote ratings to top-level fields" },
  { key: "perf:filter",    label: "Filter",     hint: "applyFilters() — search/category/threshold" },
  { key: "perf:sort",      label: "Sort",       hint: "applySort() over the filtered set" },
  { key: "perf:histogram", label: "Histogram",  hint: "Column distribution recompute" },
  { key: "perf:render",    label: "Render",     hint: "React commit (Profiler actualDuration)" },
];

const LONG_TASK_THRESHOLD = 50; // browser definition (frames > 50ms == jank)

export function PerfOverlay({ className = "", title = "Performance overlay" }) {
  const [stats, setStats] = useState({}); // {key: {last, max, count}}
  const [longTasks, setLongTasks] = useState([]); // [{duration, startTime}]
  const [supported, setSupported] = useState({ measure: true, longtask: true });
  const tracesRef = useRef([]);

  useEffect(() => {
    if (typeof PerformanceObserver === "undefined") {
      setSupported({ measure: false, longtask: false });
      return;
    }

    let measureObs = null;
    let longTaskObs = null;

    try {
      measureObs = new PerformanceObserver((list) => {
        const updates = {};
        list.getEntries().forEach((e) => {
          if (!TRACKED.some(t => t.key === e.name)) return;
          updates[e.name] = updates[e.name] || [];
          updates[e.name].push(e.duration);
          tracesRef.current.push({ t: e.startTime, name: e.name, ms: e.duration });
          if (tracesRef.current.length > 500) tracesRef.current.shift();
        });
        if (Object.keys(updates).length === 0) return;
        setStats((prev) => {
          const next = { ...prev };
          for (const [k, durs] of Object.entries(updates)) {
            const last = durs[durs.length - 1];
            const prevEntry = next[k] || { last: 0, max: 0, count: 0 };
            next[k] = {
              last,
              max: Math.max(prevEntry.max, ...durs),
              count: prevEntry.count + durs.length,
            };
          }
          return next;
        });
      });
      measureObs.observe({ entryTypes: ["measure"] });
    } catch (e) {
      setSupported((s) => ({ ...s, measure: false }));
    }

    try {
      longTaskObs = new PerformanceObserver((list) => {
        const entries = list.getEntries().map((e) => ({ duration: e.duration, startTime: e.startTime }));
        if (entries.length === 0) return;
        setLongTasks((prev) => {
          const next = [...prev, ...entries];
          return next.slice(-30); // keep last 30
        });
        entries.forEach((e) => {
          tracesRef.current.push({ t: e.startTime, name: "longtask", ms: e.duration });
        });
      });
      longTaskObs.observe({ type: "longtask", buffered: true });
    } catch (e) {
      setSupported((s) => ({ ...s, longtask: false }));
    }

    return () => {
      measureObs?.disconnect();
      longTaskObs?.disconnect();
    };
  }, []);

  const reset = useCallback(() => {
    setStats({});
    setLongTasks([]);
    tracesRef.current = [];
    if (typeof performance !== "undefined" && performance.clearMeasures) {
      try { performance.clearMeasures(); } catch (_) { /* ignore */ }
    }
  }, []);

  const copyTrace = useCallback(async () => {
    const payload = {
      capturedAt: new Date().toISOString(),
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "",
      viewport: typeof window !== "undefined" ? { w: window.innerWidth, h: window.innerHeight } : null,
      memory: typeof performance !== "undefined" && performance.memory
        ? {
            jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
            totalJSHeapSize: performance.memory.totalJSHeapSize,
            usedJSHeapSize: performance.memory.usedJSHeapSize,
          }
        : null,
      stats,
      longTasks,
      traces: tracesRef.current,
    };
    const text = JSON.stringify(payload, null, 2);
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      // Fallback: open in a new window
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    }
  }, [stats, longTasks]);

  const longTaskCount = longTasks.length;
  const longTaskMax = longTasks.reduce((m, e) => Math.max(m, e.duration), 0);
  const longTaskTotal = longTasks.reduce((s, e) => s + e.duration, 0);

  const [debounceMs, setDebounceMs] = usePerfDebounce();

  return (
    <div className={`border border-border rounded-lg p-3 bg-card space-y-2 ${className}`} data-testid="perf-overlay">
      <div className="flex items-center gap-2 flex-wrap">
        <Activity className="h-3.5 w-3.5 text-accent" />
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{title}</span>
        {!supported.measure && (
          <span className="text-[10px] text-amber-600 inline-flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" /> measure API unavailable
          </span>
        )}
        <div className="flex-1" />
        {/* Debounce control */}
        <div className="inline-flex items-center gap-1.5 text-[10px] text-muted-foreground" title="Idle delay before committing search / slider drafts to the filter state. 0 = no debounce.">
          <Timer className="h-3 w-3" />
          <span className="hidden sm:inline">Debounce</span>
          <input
            type="range" min={0} max={500} step={10}
            value={debounceMs}
            onChange={(e) => setDebounceMs(parseInt(e.target.value, 10))}
            className="w-24 accent-accent"
            data-testid="perf-debounce-slider"
          />
          <span className="font-mono tabular-nums text-foreground w-10 text-right">{debounceMs} ms</span>
        </div>
        <button onClick={reset} className="text-[10px] text-muted-foreground hover:text-foreground px-2 py-0.5 rounded border border-border" data-testid="perf-reset">
          Reset
        </button>
        <button onClick={copyTrace} className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground px-2 py-0.5 rounded border border-border" data-testid="perf-copy">
          <Copy className="h-3 w-3" /> Copy trace
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2" data-testid="perf-grid">
        {TRACKED.map((t) => {
          const s = stats[t.key];
          const last = s?.last;
          const max = s?.max;
          const slow = last != null && last > LONG_TASK_THRESHOLD;
          return (
            <div key={t.key} className="min-w-0" title={t.hint}>
              <div className="text-[9px] uppercase tracking-wider text-muted-foreground truncate">{t.label}</div>
              <div className={`font-mono tabular-nums text-[12px] ${slow ? "text-amber-500" : "text-foreground"}`}>
                {last != null ? `${last.toFixed(1)} ms` : "—"}
              </div>
              <div className="text-[9px] text-muted-foreground tabular-nums">
                max {max != null ? `${max.toFixed(0)} ms` : "—"} · n {s?.count ?? 0}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3 text-[10px] text-muted-foreground border-t border-border/40 pt-2" data-testid="perf-longtasks">
        <span className="inline-flex items-center gap-1">
          <AlertTriangle className={`h-3 w-3 ${longTaskCount > 0 ? "text-amber-500" : ""}`} />
          Long tasks ({">"}50&nbsp;ms)
        </span>
        <span className="font-mono">count {longTaskCount}</span>
        <span className="font-mono">max {longTaskMax.toFixed(0)} ms</span>
        <span className="font-mono">total {longTaskTotal.toFixed(0)} ms</span>
        {!supported.longtask && (
          <span className="text-amber-600">longtask observer unavailable</span>
        )}
        {/* Mini sparkline of recent long-task durations */}
        {longTaskCount > 0 && (
          <div className="flex items-end gap-px h-3 flex-1 max-w-[200px]" aria-hidden>
            {longTasks.slice(-30).map((e, i) => (
              <div
                key={i}
                style={{
                  width: 3,
                  height: `${Math.min(12, e.duration / 20)}px`,
                  backgroundColor: e.duration > 200 ? "#ef4444" : e.duration > 100 ? "#f97316" : "#eab308",
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
