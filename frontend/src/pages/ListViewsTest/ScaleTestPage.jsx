import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import axios from "axios";
import { Loader2, Play, Clock, HardDrive, AlertTriangle, Server, Cpu } from "lucide-react";
import { METRICS, flattenPaper } from "./_shared";
import { HeatmapPage } from "./HeatmapView";
import { PerfOverlay } from "./PerfOverlay";

const API = process.env.REACT_APP_BACKEND_URL;

const PRESETS = [
  { n: 200, label: "200 (real-ish)" },
  { n: 1000, label: "1k" },
  { n: 5000, label: "5k" },
  { n: 10000, label: "10k" },
  { n: 25000, label: "25k" },
  { n: 50000, label: "50k" },
  { n: 100000, label: "100k" },
];

function fmtMs(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function fmtBytes(b) {
  if (b == null) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KiB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MiB`;
}

/**
 * Hook that loads N synthetic papers from /api/scaling-test/papers and
 * exposes performance metrics for each phase (network, JSON parse, flatten).
 */
function useScalingTestPapers(loadKey, n, seed, includeReasoning) {
  const [data, setData] = useState({ papers: [], loading: true, n: 0, error: null });
  const [perf, setPerf] = useState({});
  const abortRef = useRef(null);

  useEffect(() => {
    if (loadKey == null) {
      setData({ papers: [], loading: false, n: 0, error: null });
      return;
    }
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setData(prev => ({ ...prev, loading: true, error: null }));

    const t0 = performance.now();
    let tFetchEnd, tParseEnd, tFlattenEnd, bytes = null;

    fetch(`${API}/api/scaling-test/papers?n=${n}&seed=${seed}&reasoning=${includeReasoning}`, { signal: ctrl.signal })
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        tFetchEnd = performance.now();
        // Emit performance.measure entries so <PerfOverlay> picks them up
        try {
          const m = `data:fetch-${t0}`;
          performance.mark(m, { startTime: t0 });
          performance.measure("data:fetch", m);
          performance.clearMarks(m);
        } catch (_) { /* ignore */ }
        const tParseStart = performance.now();
        const text = await resp.text();
        bytes = new Blob([text]).size;
        const obj = JSON.parse(text);
        tParseEnd = performance.now();
        try {
          const m = `data:parse-${tParseStart}`;
          performance.mark(m, { startTime: tParseStart });
          performance.measure("data:parse", m);
          performance.clearMarks(m);
        } catch (_) { /* ignore */ }
        return obj;
      })
      .then((obj) => {
        const tFlattenStart = performance.now();
        const raw = obj?.exp3?.papers || [];
        const flat = raw.map(flattenPaper);
        tFlattenEnd = performance.now();
        try {
          const m = `data:flatten-${tFlattenStart}`;
          performance.mark(m, { startTime: tFlattenStart });
          performance.measure("data:flatten", m);
          performance.clearMarks(m);
        } catch (_) { /* ignore */ }
        setPerf({
          fetchMs: tFetchEnd - t0,
          parseMs: tParseEnd - tFetchEnd,
          flattenMs: tFlattenEnd - tParseEnd,
          totalMs: tFlattenEnd - t0,
          bytes,
          backendGenMs: obj.gen_ms,
        });
        setData({ papers: flat, loading: false, n: raw.length, error: null });
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setData({ papers: [], loading: false, n: 0, error: String(err) });
        setPerf({});
      });

    return () => ctrl.abort();
  }, [loadKey, n, seed, includeReasoning]);

  return { ...data, perf };
}

export default function ScaleTestPage() {
  const [nDraft, setNDraft] = useState(1000);
  const [seedDraft, setSeedDraft] = useState(42);
  const [reasoningDraft, setReasoningDraft] = useState(true);
  const [sourceMode, setSourceMode] = useState("client"); // "client" | "server"
  const [loadKey, setLoadKey] = useState(null);
  const [committed, setCommitted] = useState({ n: 1000, seed: 42, reasoning: true, mode: "client" });

  // Client-mode hook fetches everything; only fires when committed.mode === "client" and loadKey set.
  const clientLoadKey = committed.mode === "client" ? loadKey : null;
  const { papers, loading, n, error, perf } = useScalingTestPapers(
    clientLoadKey, committed.n, committed.seed, committed.reasoning
  );

  const trigger = useCallback(() => {
    setCommitted({ n: nDraft, seed: seedDraft, reasoning: reasoningDraft, mode: sourceMode });
    setLoadKey((k) => (k || 0) + 1);
  }, [nDraft, seedDraft, reasoningDraft, sourceMode]);

  const big = nDraft >= 50000;

  // Client-mode `data` for HeatmapPage; ignored in server mode.
  const data = useMemo(
    () => ({ papers, loading, n, error }),
    [papers, loading, n, error]
  );

  // Server-mode source spec. When committed.mode === "server" and a load has been triggered,
  // pass it to HeatmapPage so it switches to the server-paged data provider.
  const serverSource = useMemo(() => {
    if (committed.mode !== "server" || loadKey == null) return null;
    return {
      dataset: "synthetic",
      n: committed.n,
      seed: committed.seed,
      reasoning: committed.reasoning,
    };
  }, [committed.mode, committed.n, committed.seed, committed.reasoning, loadKey]);

  const headerExtras = (
    <div className="border border-border rounded-lg p-3 bg-card space-y-3" data-testid="scale-controls">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground mr-1">Paper count</span>
        {PRESETS.map(p => (
          <button
            key={p.n}
            onClick={() => setNDraft(p.n)}
            className={`text-[11px] px-2.5 py-1 rounded border transition-colors ${
              nDraft === p.n
                ? "bg-foreground text-background border-foreground"
                : "bg-background text-muted-foreground hover:text-foreground border-border"
            }`}
            data-testid={`scale-n-${p.n}`}
          >
            {p.label}
          </button>
        ))}
        <input
          type="number" min={1} max={200000} step={100}
          value={nDraft}
          onChange={(e) => setNDraft(Math.max(1, Math.min(200000, parseInt(e.target.value, 10) || 0)))}
          className="w-24 text-[11px] px-2 py-1 rounded border border-border bg-background outline-none focus:border-accent"
          data-testid="scale-n-input"
        />
        <div className="w-px h-5 bg-border mx-1" />
        <label className="text-[11px] inline-flex items-center gap-1.5">
          <span className="text-muted-foreground">Seed</span>
          <input
            type="number"
            value={seedDraft}
            onChange={(e) => setSeedDraft(parseInt(e.target.value, 10) || 0)}
            className="w-16 text-[11px] px-2 py-1 rounded border border-border bg-background outline-none focus:border-accent"
            data-testid="scale-seed-input"
          />
        </label>
        <label className="text-[11px] inline-flex items-center gap-1 text-muted-foreground hover:text-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={reasoningDraft}
            onChange={(e) => setReasoningDraft(e.target.checked)}
            className="accent-accent"
            data-testid="scale-reasoning"
          />
          Include reasoning text
        </label>
        <div className="w-px h-5 bg-border mx-1" />
        {/* Source toggle: client-side (current) vs server-side (Phase 2) */}
        <div className="inline-flex rounded-md border border-border overflow-hidden text-[11px]" data-testid="scale-source">
          <button
            onClick={() => setSourceMode("client")}
            className={`inline-flex items-center gap-1 px-2.5 py-1 transition-colors ${sourceMode === "client" ? "bg-accent text-accent-foreground" : "bg-background text-muted-foreground hover:text-foreground"}`}
            data-testid="scale-source-client"
            title="Load the entire dataset, filter/sort/page on the client. Tests pure client-side cost."
          >
            <Cpu className="h-3 w-3" />
            Client
          </button>
          <button
            onClick={() => setSourceMode("server")}
            className={`inline-flex items-center gap-1 px-2.5 py-1 transition-colors ${sourceMode === "server" ? "bg-accent text-accent-foreground" : "bg-background text-muted-foreground hover:text-foreground"}`}
            data-testid="scale-source-server"
            title="Filter / sort / page on the server. Tests Phase 2 architecture."
          >
            <Server className="h-3 w-3" />
            Server
          </button>
        </div>
        <div className="flex-1" />
        <button
          onClick={trigger}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded bg-accent text-accent-foreground hover:brightness-110 disabled:opacity-50"
          data-testid="scale-load"
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          {loading ? "Loading…" : (loadKey == null ? "Generate" : "Reload")}
        </button>
      </div>

      {big && sourceMode === "client" && (
        <div className="flex items-center gap-2 text-[11px] text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          {nDraft.toLocaleString()} papers in client mode → ~{(nDraft * 1.17 / 1024).toFixed(0)} MB JSON payload. Switch to <b>Server</b> mode to scale comfortably.
        </div>
      )}
      {big && sourceMode === "server" && (
        <div className="text-[11px] text-muted-foreground">
          Server mode: only the visible page (40 rows) is transferred per request. Filter / sort / histogram run on the server.
        </div>
      )}

      {committed.mode === "client" && (perf.totalMs != null || error) && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-[10px] border-t border-border/40 pt-2" data-testid="scale-perf">
          <Stat icon={Clock} label="Backend gen" value={perf.backendGenMs != null ? fmtMs(perf.backendGenMs) : "—"} />
          <Stat icon={Clock} label="Network + body" value={fmtMs(perf.fetchMs)} />
          <Stat icon={Clock} label="JSON.parse" value={fmtMs(perf.parseMs)} />
          <Stat icon={Clock} label="Flatten" value={fmtMs(perf.flattenMs)} />
          <Stat icon={HardDrive} label="Payload" value={fmtBytes(perf.bytes)} />
        </div>
      )}

      {error && (
        <div className="text-[11px] text-destructive">
          <AlertTriangle className="inline h-3 w-3 mr-1" /> {error}
        </div>
      )}

      {!loading && committed.mode === "client" && papers.length > 0 && (
        <div className="text-[10px] text-muted-foreground" data-testid="scale-summary">
          Loaded <b>{n.toLocaleString()}</b> synthetic papers (client mode). Filter timing is reported in the perf overlay below.
        </div>
      )}
      {committed.mode === "server" && loadKey != null && (
        <div className="text-[10px] text-muted-foreground" data-testid="scale-summary">
          Server mode active — each filter change makes one HTTP request to <code>/api/papers-list</code>. Each scroll past the loaded rows fetches the next 40-row page.
        </div>
      )}
    </div>
  );

  return (
    <HeatmapPage
      data={data}
      serverSource={serverSource}
      listStateKey={`scale-test:${committed.mode}`}
      titleOverride={`Scaling test — Heatmap (${committed.mode} mode)`}
      subtitleOverride={
        committed.mode === "server"
          ? "Server-paged stress test. Filter / sort / paging run on the backend; only the visible page is transferred. Compare with Client mode to measure the Phase 2 win at scale."
          : "Client-side stress test. The full corpus is loaded, then everything (filter, sort, paging, histograms) happens in the browser. Use this to measure the pure client-side cost at scale."
      }
      headerExtras={<>
        {headerExtras}
        <PerfOverlay title="Phase 0 live performance" />
      </>}
    />
  );
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-1.5">
      <Icon className="h-3 w-3 text-muted-foreground shrink-0" />
      <div className="min-w-0">
        <div className="text-muted-foreground uppercase tracking-wider text-[9px]">{label}</div>
        <div className="font-mono text-foreground text-[11px] tabular-nums">{value}</div>
      </div>
    </div>
  );
}
