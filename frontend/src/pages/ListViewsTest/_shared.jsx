import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { ChevronLeft, Search, X } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

const API = process.env.REACT_APP_BACKEND_URL;

// Master metric configuration. `reason: true` ⇒ has `<name>_reason` field.
export const METRICS = [
  { key: "score",                  label: "Impact",       short: "Impact",   color: "#6366f1", core: true,  reason: false, desc: "Composite overall predicted scientific impact (1-10)." },
  { key: "significance",           label: "Significance", short: "Signif.",  color: "#0ea5e9", core: true,  reason: false, desc: "Likely influence on future research, practice or applications." },
  { key: "rigor",                  label: "Rigor",        short: "Rigor",    color: "#22c55e", core: true,  reason: false, desc: "Methodological soundness — proofs, baselines, experimental design." },
  { key: "novelty",                label: "Novelty",      short: "Novelty",  color: "#a855f7", core: true,  reason: false, desc: "Originality of the idea, method or framing." },
  { key: "clarity",                label: "Clarity",      short: "Clarity",  color: "#eab308", core: true,  reason: false, desc: "Writing quality and logical organization." },
  { key: "difficulty",             label: "Difficulty",   short: "Diffic.",  color: "#8b5cf6", core: false, reason: true,  desc: "Technical difficulty: 1 = accessible to undergrads, 10 = deep specialist expertise." },
  { key: "surprisingness",         label: "Surprisingness", short: "Surpris.", color: "#ec4899", core: false, reason: true,  desc: "How unexpected the results are vs. current understanding." },
  { key: "reproducibility",        label: "Reproducibility", short: "Reprod.", color: "#06b6d4", core: false, reason: true,  desc: "Could an independent researcher replicate the main results from this paper alone?" },
  { key: "translational_potential",label: "Translational",  short: "Transl.", color: "#f97316", core: false, reason: true,  desc: "How close is this work to real-world application or commercial value? Consider industrial usage, clinical deployment, patentability, and economic impact. 1 = pure theory with no foreseeable application, 5 = clear potential for applied follow-up, 10 = directly applicable to industry, clinical use, or deployment." },
  { key: "evidence_strength",      label: "Evidence",        short: "Evid.",   color: "#14b8a6", core: false, reason: true,  desc: "How well experiments, proofs and ablations support the claims." },
  { key: "generalisability",       label: "Generalisability", short: "General.", color: "#f43f5e", core: false, reason: true,  desc: "How broadly findings apply beyond tested conditions." },
];

export const METRIC_BY_KEY = Object.fromEntries(METRICS.map(m => [m.key, m]));

// Diverging color scale for a 1-10 score. Neutral grey near 5, green up, red down.
export function scoreColor(value) {
  if (value == null) return "transparent";
  const t = Math.max(0, Math.min(1, (value - 1) / 9));
  // 5 = neutral; >5 green; <5 red. Strength proportional to distance from 5.
  const dist = Math.abs(value - 5.5) / 4.5; // 0..1
  const strength = Math.min(1, dist);
  if (value >= 5.5) {
    // green tones
    const a = 0.10 + 0.65 * strength;
    return `rgba(34,197,94,${a.toFixed(3)})`;
  }
  const a = 0.10 + 0.65 * strength;
  return `rgba(239,68,68,${a.toFixed(3)})`;
  // eslint-disable-next-line no-unused-vars
  // t kept above intentionally for future heat ramps
}

export function scoreTextColor(value) {
  if (value == null) return "var(--muted-foreground)";
  const dist = Math.abs(value - 5.5) / 4.5;
  return dist > 0.55 ? "#fff" : "inherit";
}

// Per-metric hue: each metric uses its brand color, intensity scaled by value.
// Returns rgba string. Low value = pale wash, high value = saturated.
export function metricHueColor(metric, value) {
  if (value == null) return "transparent";
  const hex = metric.color.replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  // Non-linear ramp: emphasises high-end variation where most papers cluster
  const t = Math.pow(value / 10, 1.4);
  const a = 0.06 + 0.84 * t;
  return `rgba(${r},${g},${b},${a.toFixed(3)})`;
}
export function metricHueTextColor(metric, value) {
  if (value == null) return "var(--muted-foreground)";
  const t = Math.pow(value / 10, 1.4);
  return t > 0.55 ? "#fff" : "inherit";
}

// Viridis-like perceptually-uniform colormap, colorblind safe.
const VIRIDIS_STOPS = [
  [0.0,  [68, 1, 84]],     // dark purple
  [0.25, [59, 82, 139]],   // blue
  [0.5,  [33, 144, 140]],  // teal
  [0.75, [94, 201, 98]],   // green
  [1.0,  [253, 231, 36]],  // yellow
];
export function viridisColor(t) {
  if (t == null || isNaN(t)) return "transparent";
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < VIRIDIS_STOPS.length; i++) {
    const [t1, c1] = VIRIDIS_STOPS[i - 1];
    const [t2, c2] = VIRIDIS_STOPS[i];
    if (t <= t2) {
      const f = (t - t1) / (t2 - t1);
      const r = Math.round(c1[0] + (c2[0] - c1[0]) * f);
      const g = Math.round(c1[1] + (c2[1] - c1[1]) * f);
      const b = Math.round(c1[2] + (c2[2] - c1[2]) * f);
      return `rgb(${r},${g},${b})`;
    }
  }
  return "rgb(253,231,36)";
}
export function viridisTextColor(t) {
  if (t == null) return "var(--muted-foreground)";
  return t < 0.55 ? "#fff" : "#0a0a0a";
}

// Compute per-paper percentile within a metric (excluding nulls).
// Returns Map<paper_id, percentile in [0,1]>.
export function computePercentileMap(papers, metricKey) {
  const valued = papers
    .map(p => ({ id: p.paper_id, v: p[metricKey] }))
    .filter(x => x.v != null)
    .sort((a, b) => a.v - b.v);
  const n = valued.length;
  const map = new Map();
  // Average-rank ties so identical values get identical percentile.
  let i = 0;
  while (i < n) {
    let j = i;
    while (j < n && valued[j].v === valued[i].v) j++;
    const avgRank = (i + j - 1) / 2;
    const pct = n > 1 ? avgRank / (n - 1) : 0.5;
    for (let k = i; k < j; k++) map.set(valued[k].id, pct);
    i = j;
  }
  return map;
}

// Mini histogram strip data (8 bins from 1-10) for a metric across papers.
export function computeMiniHistogram(papers, metricKey, bins = 8) {
  const counts = new Array(bins).fill(0);
  const values = papers.map(p => p[metricKey]).filter(v => v != null);
  values.forEach(v => {
    const idx = Math.min(bins - 1, Math.floor(((v - 1) / 9) * bins));
    counts[idx]++;
  });
  const max = Math.max(1, ...counts);
  const mean = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return { counts, max, mean, n: values.length };
}

export function useExtendedPapers() {
  const [state, setState] = useState({ loading: true, papers: [], n: 0, error: null });
  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/api/prompt-stability-results`).then(r => {
      if (cancelled) return;
      const papers = r.data?.exp3?.papers || [];
      // Pre-flatten ratings into top-level fields for easy sort/filter
      const flat = papers.map(p => {
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
      setState({ loading: false, papers: flat, n: r.data?.exp3?.n || flat.length, error: null });
    }).catch(err => {
      if (!cancelled) setState({ loading: false, papers: [], n: 0, error: String(err) });
    });
    return () => { cancelled = true; };
  }, []);
  return state;
}

// Custom hook bundling search / category / sort / metric-range state, persisted to localStorage.
export function useListState(viewKey, defaults = {}) {
  const storageKey = `list-views:${viewKey}`;
  const [state, setStateRaw] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (stored) return { ...buildDefaults(defaults), ...stored, categories: new Set(stored.categories || []), hidden: new Set(stored.hidden || []) };
    } catch (_) { /* ignore */ }
    return buildDefaults(defaults);
  });
  const setState = (patch) => setStateRaw(prev => {
    const next = typeof patch === "function" ? patch(prev) : { ...prev, ...patch };
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        ...next,
        categories: Array.from(next.categories || []),
        hidden: Array.from(next.hidden || []),
      }));
    } catch (_) { /* ignore */ }
    return next;
  });
  return [state, setState];
}

function buildDefaults(d) {
  return {
    search: "",
    categories: new Set(),
    categoryMode: d.categoryMode || "any", // "any" | "primary" | "cross-listed"
    categoryLogic: d.categoryLogic || "or", // "or" | "and" — combine multiple selected cats
    sortKey: d.sortKey || "score",
    sortDir: d.sortDir || "desc",
    metricMin: d.metricMin || {}, // { metric: number } — threshold value
    metricOp: d.metricOp || {},   // { metric: "gte" | "lte" } — operator per metric, default "gte"
    hidden: new Set(d.hidden || []), // hidden metric keys
    includeNulls: d.includeNulls ?? true,
    headerMode: d.headerMode || "labels", // "labels" | "charts"
  };
}

export function applyFilters(papers, state) {
  const q = (state.search || "").trim().toLowerCase();
  const cats = state.categories;
  const mode = state.categoryMode || "any";
  const logic = state.categoryLogic || "or";
  const minMap = state.metricMin || {};
  const opMap = state.metricOp || {};
  return papers.filter(p => {
    if (q) {
      const titleMatch = p.title && p.title.toLowerCase().includes(q);
      const authorMatch = (p.authors || []).some(a => a && a.toLowerCase().includes(q));
      if (!titleMatch && !authorMatch) return false;
    }
    if (cats.size > 0) {
      const primary = p.category;
      const all = p.categories || (primary ? [primary] : []);
      const lookup = (cat) => {
        if (mode === "primary") return cat === primary;
        if (mode === "cross-listed") return all.includes(cat) && cat !== primary;
        return all.includes(cat);
      };
      const selected = Array.from(cats);
      const match = logic === "and"
        ? selected.every(lookup)
        : selected.some(lookup);
      if (!match) return false;
    }
    for (const [k, threshold] of Object.entries(minMap)) {
      if (threshold == null) continue;
      const op = opMap[k] || "gte";
      // No-op thresholds — never restrict the result set.
      // - gte at 0 lets everything through
      // - lte at 10 lets everything through
      // - lte at 0 can never match (scores are 1-10) — treat as no-op rather than filter everything
      if (op === "gte" && threshold === 0) continue;
      if (op === "lte" && (threshold === 10 || threshold === 0)) continue;
      const val = p[k];
      if (val == null) {
        if (!state.includeNulls) return false;
        continue;
      }
      if (op === "gte" && val < threshold) return false;
      if (op === "lte" && val > threshold) return false;
    }
    return true;
  });
}

export function applySort(papers, state) {
  const { sortKey, sortDir } = state;
  const dir = sortDir === "asc" ? 1 : -1;
  const arr = [...papers];
  arr.sort((a, b) => {
    if (sortKey === "title") return a.title.localeCompare(b.title) * dir;
    if (sortKey === "category") return (a.category || "").localeCompare(b.category || "") * dir;
    const av = a[sortKey], bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;   // nulls always sink
    if (bv == null) return -1;
    return (av - bv) * dir;
  });
  return arr;
}

// Top filter bar shared across views
export function FilterBar({ state, setState, papers, sortableKeys = null, showColumnToggle = false }) {
  const categories = useMemo(() => {
    const set = new Set();
    papers.forEach(p => {
      if (p.category) set.add(p.category);
      (p.categories || []).forEach(c => set.add(c));
    });
    return Array.from(set).sort();
  }, [papers]);

  const visibleMetrics = sortableKeys
    ? METRICS.filter(m => sortableKeys.includes(m.key))
    : METRICS;

  const toggleCategory = (cat) => setState(prev => {
    const next = new Set(prev.categories);
    next.has(cat) ? next.delete(cat) : next.add(cat);
    return { ...prev, categories: next };
  });

  const toggleHidden = (key) => setState(prev => {
    const next = new Set(prev.hidden);
    next.has(key) ? next.delete(key) : next.add(key);
    return { ...prev, hidden: next };
  });

  const resetAll = () => setState({
    search: "", categories: new Set(),
    categoryMode: "any", categoryLogic: "or",
    sortKey: "score", sortDir: "desc",
    metricMin: {}, metricOp: {},
    hidden: new Set(),
    includeNulls: true,
  });

  return (
    <div className="border border-border rounded-lg p-3 bg-card space-y-3" data-testid="filter-bar">
      <div className="flex flex-wrap items-center gap-2">
        {/* Title search */}
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search title or author..."
            value={state.search}
            onChange={(e) => setState({ search: e.target.value })}
            className="w-full pl-7 pr-7 py-1.5 text-xs rounded border border-border bg-background outline-none focus:border-accent"
            data-testid="lv-search"
          />
          {state.search && (
            <button onClick={() => setState({ search: "" })} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        <div className="flex-1" />

        <button onClick={resetAll} className="text-xs py-1 px-2 rounded border border-border bg-background hover:bg-secondary" data-testid="lv-reset">
          Reset
        </button>
      </div>

      {/* Category multiselect */}
      {categories.length > 0 && (() => {
        const mode = state.categoryMode || "any";
        const logic = state.categoryLogic || "or";
        const selected = Array.from(state.categories);
        const modeLabel = mode === "primary" ? "Primary only" : mode === "cross-listed" ? "Secondary only" : "Any";
        const joinSep = selected.length > 1 ? ` ${logic.toUpperCase()} ` : ", ";
        const summaryText = selected.length === 0
          ? `${modeLabel} · all ${categories.length} categories`
          : `${modeLabel} · ${selected.slice(0, 3).join(joinSep)}${selected.length > 3 ? ` +${selected.length - 3}` : ""}`;
        return (
          <details className="border-t border-border/40 pt-2 group">
            <summary className="text-[10px] uppercase tracking-wider cursor-pointer select-none flex items-center gap-2 hover:text-foreground text-muted-foreground list-none [&::-webkit-details-marker]:hidden">
              <span className="text-sm leading-none inline-block transition-transform group-open:rotate-90">▸</span>
              <span>Category</span>
              <span className="normal-case tracking-normal text-[11px] text-foreground/70 font-normal">{summaryText}</span>
              {selected.length > 0 && (
                <button
                  onClick={(e) => { e.preventDefault(); setState(prev => ({ ...prev, categories: new Set(), categoryMode: "any" })); }}
                  className="ml-auto text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-secondary normal-case tracking-normal"
                  data-testid="lv-cat-clear"
                >
                  Clear
                </button>
              )}
            </summary>
            <div className="space-y-2 mt-2">
              {/* Mode row — segmented control, kept aligned with the tags row */}
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider w-[64px] shrink-0">Match</span>
                <div className="inline-flex rounded-md bg-secondary/60 p-0.5 gap-0.5 -ml-0.5" data-testid="lv-cat-mode">
                  {[
                    { v: "any", label: "Any", tip: "Match papers where the selected category is listed as either the primary category or any secondary (cross-listed) category." },
                    { v: "primary", label: "Primary only", tip: "Match only papers whose primary category is among the selected categories." },
                    { v: "cross-listed", label: "Secondary only", tip: "Match only papers cross-listed in the selected categories, but where the primary category is something else." },
                  ].map(opt => {
                    const active = (state.categoryMode || "any") === opt.v;
                    return (
                      <Tooltip key={opt.v}>
                        <TooltipTrigger asChild>
                          <button
                            onClick={() => setState({ categoryMode: opt.v })}
                            className={`text-[10px] px-2.5 py-1 rounded transition-colors ${active ? "bg-background text-foreground shadow-sm font-medium" : "text-muted-foreground hover:text-foreground"}`}
                            data-testid={`lv-cat-mode-${opt.v}`}
                          >
                            {opt.label}
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs bg-popover text-popover-foreground border border-border shadow-md">
                          <div className="space-y-0.5">
                            <div className="text-[11px] font-medium">{opt.label}</div>
                            <p className="text-[11px] leading-snug text-muted-foreground">{opt.tip}</p>
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
                </div>
              </div>

              {/* Logic row — only matters when 2+ categories selected */}
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider w-[64px] shrink-0">Logic</span>
                <div className="inline-flex rounded-md bg-secondary/60 p-0.5 gap-0.5 -ml-0.5" data-testid="lv-cat-logic">
                  {[
                    { v: "or", label: "OR" },
                    { v: "and", label: "AND" },
                  ].map(opt => {
                    const active = (state.categoryLogic || "or") === opt.v;
                    return (
                      <button
                        key={opt.v}
                        onClick={() => setState({ categoryLogic: opt.v })}
                        className={`text-[10px] px-2.5 py-1 rounded transition-colors ${active ? "bg-background text-foreground shadow-sm font-medium" : "text-muted-foreground hover:text-foreground"}`}
                        data-testid={`lv-cat-logic-${opt.v}`}
                        title={
                          opt.v === "and" ? "Paper must match ALL selected categories"
                          : "Paper must match ANY selected category"
                        }
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Category tags row */}
              <div className="flex flex-wrap gap-1 items-start">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider w-[64px] shrink-0 mt-0.5">Tags</span>
                <div className="flex flex-wrap gap-1 flex-1">
                  {categories.map(cat => {
                    const active = state.categories.has(cat);
                    return (
                      <button
                        key={cat}
                        onClick={() => toggleCategory(cat)}
                        className={`text-[10px] font-mono px-1.5 py-0.5 rounded border transition-colors ${active ? "bg-accent text-accent-foreground border-accent" : "border-border bg-background hover:bg-secondary text-muted-foreground"}`}
                        data-testid={`lv-cat-${cat}`}
                      >
                        {cat}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </details>
        );
      })()}

      {/* Per-metric minimum filters */}
      <details className="border-t border-border/40 pt-2 group" open>
        <summary className="text-[10px] text-muted-foreground uppercase tracking-wider cursor-pointer select-none mb-2 hover:text-foreground flex items-center gap-2 list-none [&::-webkit-details-marker]:hidden">
          <span className="text-sm leading-none inline-block transition-transform group-open:rotate-90">▸</span>
          <span>Per-metric minimum (drag to filter)</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <label
                className="ml-auto flex items-center gap-1 text-[10px] normal-case tracking-normal cursor-pointer text-muted-foreground hover:text-foreground"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  checked={state.includeNulls}
                  onChange={(e) => setState({ includeNulls: e.target.checked })}
                  className="accent-accent"
                  data-testid="lv-include-nulls"
                />
                Include N/A
              </label>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs bg-popover text-popover-foreground border border-border shadow-md">
              <div className="space-y-0.5">
                <div className="text-[11px] font-medium">Include N/A</div>
                <p className="text-[11px] leading-snug text-muted-foreground">
                  Some extended metrics (reproducibility, evidence strength, etc.) are N/A for purely theoretical
                  or position papers. When ON, those papers still pass the active threshold filters; when OFF,
                  they are excluded as soon as any threshold is set on a metric they lack.
                </p>
              </div>
            </TooltipContent>
          </Tooltip>
        </summary>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
          {visibleMetrics.map(m => {
            const v = state.metricMin?.[m.key] ?? 0;
            const op = state.metricOp?.[m.key] || "gte";
            const symbol = op === "gte" ? "≥" : "≤";
            const isNoop = (op === "gte" && v === 0) || (op === "lte" && (v === 10 || v === 0));
            const flipOp = () => setState(prev => ({
              ...prev,
              metricOp: { ...(prev.metricOp || {}), [m.key]: op === "gte" ? "lte" : "gte" },
            }));
            return (
              <div key={m.key} className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: m.color }} />
                <span className="text-[11px] text-foreground/80 w-32 shrink-0 truncate" title={`${m.label} — ${m.desc}`}>{m.label}</span>
                <input
                  type="range" min={0} max={10} step={0.5}
                  value={v}
                  onChange={(e) => setState(prev => ({ ...prev, metricMin: { ...prev.metricMin, [m.key]: parseFloat(e.target.value) } }))}
                  className="flex-1 accent-accent min-w-0"
                  data-testid={`lv-min-${m.key}`}
                />
                <button
                  onClick={flipOp}
                  className={`text-[10px] font-mono w-12 text-right tabular-nums shrink-0 rounded px-1 py-0.5 hover:bg-secondary transition-colors cursor-pointer ${isNoop ? "text-muted-foreground/60" : "text-foreground"}`}
                  title={`Currently: ${op === "gte" ? "≥ (at least)" : "≤ (at most)"}${isNoop ? " — filter inactive" : ""}. Click to flip.`}
                  data-testid={`lv-op-${m.key}`}
                >
                  {symbol} {v.toFixed(1)}
                </button>
              </div>
            );
          })}
        </div>
      </details>

      {/* Column visibility toggle */}
      {showColumnToggle && (
        <div className="flex flex-wrap gap-1 items-center pt-1 border-t border-border/50">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider mr-1">Show</span>
          {METRICS.map(m => {
            const hidden = state.hidden.has(m.key);
            return (
              <button
                key={m.key}
                onClick={() => toggleHidden(m.key)}
                className={`text-[10px] px-1.5 py-0.5 rounded border ${hidden ? "border-border bg-background text-muted-foreground" : "border-accent/40 bg-accent/10 text-accent-foreground"}`}
                style={!hidden ? { borderColor: m.color, backgroundColor: `${m.color}15`, color: m.color } : {}}
                data-testid={`lv-col-${m.key}`}
                title={hidden ? `Show ${m.label}` : `Hide ${m.label}`}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Wrapping shell for every test page
export function ListViewShell({ title, subtitle, children }) {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <Link to="/test/list-views" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" data-testid="lv-back">
          <ChevronLeft className="h-3 w-3" /> Back to all list views
        </Link>
      </div>
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="text-xs text-muted-foreground mt-1 max-w-2xl">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

// Reusable wrapper to attach a reasoning tooltip to a metric value
export function MetricValue({ metric, value, reason, className, children }) {
  const content = children ?? (
    <span className={className}>{value != null ? value.toFixed(1) : "—"}</span>
  );
  if (!reason) return content;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent side="top" className="max-w-sm bg-popover text-popover-foreground border border-border shadow-md">
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: metric.color }} />
            <span className="text-[11px] font-medium">{metric.label}: {value?.toFixed(1)}</span>
          </div>
          <p className="text-[11px] leading-snug">{reason}</p>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
