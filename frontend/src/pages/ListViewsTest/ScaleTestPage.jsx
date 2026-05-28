import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import axios from "axios";
import { Loader2, Play, Clock, HardDrive, AlertTriangle } from "lucide-react";
import { METRICS } from "./_shared";
import { HeatmapPage } from "./HeatmapView";

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
        const text = await resp.text();
        bytes = new Blob([text]).size;
        const obj = JSON.parse(text);
        tParseEnd = performance.now();
        return obj;
      })
      .then((obj) => {
        const raw = obj?.exp3?.papers || [];
        const flat = raw.map(p => {
          const out = {
            paper_id: p.paper_id,
            title: p.title,
            category: p.category,
            categories: p.categories || (p.category ? [p.category] : []),
            authors: p.authors || [],
            published: p.published || null,
            arxiv_id: p.arxiv_id || null,
          };
          const ratings = p.ratings || {};
          METRICS.forEach(m => {
            out[m.key] = ratings[m.key] ?? null;
            if (m.reason) out[`${m.key}_reason`] = ratings[`${m.key}_reason`] || "";
          });
          return out;
        });
        tFlattenEnd = performance.now();
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
  const [loadKey, setLoadKey] = useState(null);
  const [committed, setCommitted] = useState({ n: 1000, seed: 42, reasoning: true });

  const { papers, loading, n, error, perf } = useScalingTestPapers(
    loadKey, committed.n, committed.seed, committed.reasoning
  );

  const trigger = useCallback(() => {
    setCommitted({ n: nDraft, seed: seedDraft, reasoning: reasoningDraft });
    setLoadKey((k) => (k || 0) + 1);
  }, [nDraft, seedDraft, reasoningDraft]);

  const big = nDraft >= 50000;

  const data = useMemo(() => ({ papers, loading, n, error }), [papers, loading, n, error]);

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

      {big && (
        <div className="flex items-center gap-2 text-[11px] text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          {nDraft.toLocaleString()} papers will produce a ~{(nDraft * 1.17 / 1024).toFixed(0)} MB JSON payload. Expect 3–15&nbsp;s download and noticeable filter lag.
        </div>
      )}

      {(perf.totalMs != null || error) && (
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

      {!loading && papers.length > 0 && (
        <div className="text-[10px] text-muted-foreground" data-testid="scale-summary">
          Loaded <b>{n.toLocaleString()}</b> synthetic papers. Use the filter bar below to stress-test client-side
          search, sort, threshold, and category logic. Filter timing is reported above on every reload.
        </div>
      )}
    </div>
  );

  return (
    <HeatmapPage
      data={data}
      listStateKey="scale-test"
      titleOverride="Scaling test — Heatmap with synthetic papers"
      subtitleOverride="Stress-test environment. Choose a paper count and click Generate. The list page below is identical to the production heatmap so any client-side perf cliff (filter, sort, render) shows up here at the chosen scale. Server-side filtering is NOT applied here — this is intentional, so we can measure the pure client-side cost."
      headerExtras={headerExtras}
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
