import { useState, useEffect, useMemo, useCallback, useRef, memo, forwardRef } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { ChevronLeft, Search, X, ArrowUp, ArrowDown, Quote } from "lucide-react";
import { TableVirtuoso } from "react-virtuoso";
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useIsHoverDevice, scoreColor, scoreTextColor } from "@/pages/ListViewsTest/_shared";

const API = process.env.REACT_APP_BACKEND_URL;

const METRICS = [
  { key: "impact",     label: "Impact",     short: "Impact",     color: "#0ea5e9", desc: "How much the field gains if this problem is solved (1-10)." },
  { key: "difficulty", label: "Difficulty", short: "Diffic.",    color: "#8b5cf6", desc: "How hard it would be for a competent group to solve in 1-2 years (1-10)." },
  { key: "fruit",      label: "Fruit",      short: "Fruit",      color: "#22c55e", desc: "Low-hanging-fruit score: impact × (10 - difficulty). Higher = high impact AND low difficulty.", derived: true },
];

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

// HoverTooltip shim that auto-suppresses on touch devices (mirrors the heatmap pattern)
function HoverTooltip({ content, children, side = "top" }) {
  const isHover = useIsHoverDevice();
  if (!isHover || !content) return children;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} className="max-w-md bg-popover text-popover-foreground border border-border shadow-md">
        {content}
      </TooltipContent>
    </Tooltip>
  );
}

const METRIC_COL_WIDTH = 64;
const DATE_COL_WIDTH = 100;
const CATEGORY_COL_WIDTH = 132;
const SCOPE_COL_WIDTH = 96;

function ScopePill({ scope }) {
  const col = scope === "field_general" ? "#22c55e" : "#f97316";
  const label = scope === "field_general" ? "field" : "paper";
  return (
    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border whitespace-nowrap"
          style={{ borderColor: col, color: col, backgroundColor: `${col}10` }}
          title={scope}>
      {label}
    </span>
  );
}

function _ProblemCell({ problem }) {
  const tooltip = (
    <div className="space-y-2">
      <div>
        <div className="text-[11px] font-medium leading-snug">{problem.title}</div>
        <div className="text-[10px] text-muted-foreground mt-1 leading-snug">{problem.description}</div>
      </div>
      {problem.evidence_quote && (
        <div className="border-l-2 border-border pl-2">
          <div className="text-[9px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
            <Quote className="h-2.5 w-2.5" /> Authors say
          </div>
          <p className="text-[10px] text-muted-foreground italic leading-snug mt-0.5">&ldquo;{problem.evidence_quote}&rdquo;</p>
        </div>
      )}
      <div className="text-[9px] text-muted-foreground border-t border-border pt-1">
        From: <span className="text-foreground">{problem.paper_title}</span>
      </div>
    </div>
  );
  return (
    <HoverTooltip content={tooltip}>
      <div className="min-w-0 cursor-default">
        <div className="text-xs font-medium leading-tight line-clamp-2 min-h-[2em]" title={problem.title}>
          {problem.title}
        </div>
        <div className="text-[10px] text-muted-foreground leading-tight line-clamp-1 mt-1" title={problem.paper_title}>
          {problem.paper_title}
        </div>
      </div>
    </HoverTooltip>
  );
}
const ProblemCell = memo(_ProblemCell);

function _MetricCell({ value, reason, color, metricLabel }) {
  if (value == null) {
    return <div className="w-full h-10 flex items-center justify-center text-[11px] text-muted-foreground opacity-40">—</div>;
  }
  const tooltip = reason ? (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
        <span className="text-[11px] font-medium">{metricLabel}: {value}</span>
      </div>
      <p className="text-[11px] leading-snug">{reason}</p>
    </div>
  ) : null;
  return (
    <HoverTooltip content={tooltip}>
      <div
        className="w-full h-10 flex items-center justify-center text-[12px] font-medium tabular-nums cursor-default"
        style={{ backgroundColor: scoreColor(value), color: scoreTextColor(value) }}
      >
        {Number(value).toFixed(0)}
      </div>
    </HoverTooltip>
  );
}
const MetricCell = memo(_MetricCell);

function _ProblemRow({ problem }) {
  const fruit = problem.fruit;
  const cats = problem.paper_categories || [];
  const primary = cats[0] || "—";
  return (
    <>
      <td className="py-2 px-3 border-b border-border/30 align-top">
        <span className="text-[11px] text-muted-foreground whitespace-nowrap leading-tight">
          {fmtDate(problem.paper_published)}
        </span>
      </td>
      <td className="py-2 px-3 border-b border-border/30 align-top">
        <ProblemCell problem={problem} />
      </td>
      <td className="py-2 px-2 border-b border-border/30 align-top">
        <HoverTooltip content={cats.length > 1 ? (
          <div className="space-y-1">
            <div className="text-[11px] font-medium">arXiv categories</div>
            <div className="flex flex-wrap gap-1">
              {cats.map((c, i) => (
                <span key={c} className="font-mono text-[10px] px-1.5 py-0.5 rounded border"
                      style={i === 0
                        ? { borderColor: "hsl(var(--accent))", color: "hsl(var(--accent))", backgroundColor: "hsl(var(--accent) / 0.10)" }
                        : { borderColor: "hsl(var(--border))", color: "hsl(var(--muted-foreground))" }}>
                  {c}
                </span>
              ))}
            </div>
            <div className="text-[10px] text-muted-foreground">First = primary; rest are secondary.</div>
          </div>
        ) : null}>
          <div className="flex flex-wrap gap-1 items-center cursor-default">
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border whitespace-nowrap"
              style={{ borderColor: "hsl(var(--accent))", color: "hsl(var(--accent))", backgroundColor: "hsl(var(--accent) / 0.10)" }}>
              {primary}
            </span>
            {cats.length > 1 && (
              <span className="text-[10px] text-muted-foreground">+{cats.length - 1}</span>
            )}
          </div>
        </HoverTooltip>
      </td>
      <td className="py-2 px-2 border-b border-border/30 align-top text-center">
        <ScopePill scope={problem.scope} />
      </td>
      <td className="p-0 border-b border-border/30">
        <MetricCell value={problem.impact} reason={problem.impact_reason} color="#0ea5e9" metricLabel="Impact" />
      </td>
      <td className="p-0 border-b border-border/30">
        <MetricCell value={problem.difficulty} reason={problem.difficulty_reason} color="#8b5cf6" metricLabel="Difficulty" />
      </td>
      <td className="p-0 border-b border-border/30">
        <MetricCell value={fruit} reason={problem.impact != null && problem.difficulty != null ? `Impact ${problem.impact} × (10 - Difficulty ${problem.difficulty}) = ${fruit}` : null} color="#22c55e" metricLabel="Fruit" />
      </td>
    </>
  );
}
const ProblemRow = memo(_ProblemRow);

export default function OpenProblemsExperimentPage() {
  const [data, setData] = useState({ problems: [], total: 0, papers_with_problems: 0, papers_total: 0, papers_no_problems: 0, loading: true, error: null });
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [scope, setScope] = useState("all");
  const [categories, setCategories] = useState(() => new Set());  // multi-select
  const [sortKey, setSortKey] = useState("fruit");
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    axios.get(`${API}/api/experiments/open-problems?limit=2000`)
      .then(r => {
        const augmented = (r.data.problems || []).map(p => ({
          ...p,
          fruit: (p.impact != null && p.difficulty != null) ? Math.round(p.impact * (10 - p.difficulty) * 10) / 10 : null,
        }));
        setData({ ...r.data, problems: augmented, loading: false, error: null });
      })
      .catch(e => setData(d => ({ ...d, loading: false, error: String(e) })));
  }, []);

  // Debounce search
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchDraft), 120);
    return () => clearTimeout(id);
  }, [searchDraft]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let out = data.problems;
    if (q) {
      out = out.filter(p => {
        const hay = `${p.title} ${p.description} ${p.evidence_quote} ${p.paper_title}`.toLowerCase();
        return hay.includes(q);
      });
    }
    if (scope !== "all") out = out.filter(p => p.scope === scope);
    if (categories.size > 0) {
      out = out.filter(p => (p.paper_categories || []).some(c => categories.has(c)));
    }
    return out;
  }, [data.problems, search, scope, categories]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      if (sortKey === "title") return a.title.localeCompare(b.title) * dir;
      if (sortKey === "published") return ((a.paper_published || "") > (b.paper_published || "") ? 1 : -1) * dir;
      if (sortKey === "section") return (a.source_section || "").localeCompare(b.source_section || "") * dir;
      if (sortKey === "scope") return (a.scope || "").localeCompare(b.scope || "") * dir;
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * dir;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  // Sort the sortable keys mapping: category sort by primary category alpha
  const setSort = useCallback((key) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => (d === "asc" ? "desc" : "asc"));
        return prev;
      }
      setSortDir("desc");
      return key;
    });
  }, []);

  // Build category list — unique across all problems, sorted alphabetically,
  // with counts (using paper-category multi-match: a problem in cs.LG+cs.AI counts in both).
  const categoryCounts = useMemo(() => {
    const c = {};
    data.problems.forEach(p => {
      (p.paper_categories || []).forEach(cat => { c[cat] = (c[cat] || 0) + 1; });
    });
    return c;
  }, [data.problems]);

  const toggleCategory = useCallback((cat) => {
    setCategories(prev => {
      const next = new Set(prev);
      next.has(cat) ? next.delete(cat) : next.add(cat);
      return next;
    });
  }, []);

  const allCategories = useMemo(() => Object.keys(categoryCounts).sort(), [categoryCounts]);

  const TableComponent = useMemo(() => {
    return ({ style, children, ...rest }) => (
      <table {...rest} className="w-full text-xs border-collapse table-fixed" style={style}>
        <colgroup>
          <col style={{ width: DATE_COL_WIDTH }} />
          <col className="w-[260px] min-w-[230px] sm:w-auto sm:min-w-[360px]" />
          <col style={{ width: CATEGORY_COL_WIDTH }} />
          <col style={{ width: SCOPE_COL_WIDTH }} />
          {METRICS.map(m => <col key={m.key} style={{ width: METRIC_COL_WIDTH }} />)}
        </colgroup>
        {children}
      </table>
    );
  }, []);

  const virtuosoComponents = useMemo(() => ({
    Table: TableComponent,
    TableHead: forwardRef(function TH({ children, ...props }, ref) {
      return <thead ref={ref} {...props} className="sticky top-0 z-20 bg-card">{children}</thead>;
    }),
    TableRow: forwardRef(function TR({ children, ...props }, ref) {
      const idx = parseInt(props["data-index"], 10);
      const stripe = Number.isFinite(idx) && idx % 2 === 1 ? "bg-secondary/10" : "bg-background";
      return <tr ref={ref} {...props} className={stripe} style={{ height: 60 }}>{children}</tr>;
    }),
    EmptyPlaceholder: () => (
      <tbody>
        <tr><td colSpan={4 + METRICS.length} className="py-12 text-center text-muted-foreground">No problems match current filters.</td></tr>
      </tbody>
    ),
  }), [TableComponent]);

  const itemContent = useCallback((_, p) => <ProblemRow problem={p} />, []);

  const fixedHeaderContent = useCallback(() => (
    <tr>
      <th className="text-left py-2 px-3 border-b border-border bg-card">
        <SortHeader name="Published" sortKey="published" current={sortKey} dir={sortDir} onClick={setSort} />
      </th>
      <th className="text-left py-2 px-3 border-b border-border bg-card">
        <SortHeader name="Problem" sortKey="title" current={sortKey} dir={sortDir} onClick={setSort} />
      </th>
      <th className="text-left py-2 px-2 border-b border-border bg-card">
        <SortHeader name="Category" sortKey="category" current={sortKey} dir={sortDir} onClick={setSort} />
      </th>
      <th className="text-center py-2 px-1 border-b border-border bg-card">
        <SortHeader name="Scope" sortKey="scope" current={sortKey} dir={sortDir} onClick={setSort} />
      </th>
      {METRICS.map(m => {
        const active = sortKey === m.key;
        return (
          <th key={m.key} className="text-center py-2 px-0.5 border-b border-border bg-card">
            <HoverTooltip content={
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: m.color }} />
                  <span className="text-[11px] font-medium">{m.label}</span>
                </div>
                <p className="text-[11px] leading-snug">{m.desc}</p>
              </div>
            }>
              <button
                onClick={() => setSort(m.key)}
                className={`inline-flex items-center justify-center text-[10px] font-medium w-full transition-colors hover:text-foreground tabular-nums ${active ? "text-foreground" : "text-muted-foreground"}`}
                data-testid={`opx-th-${m.key}`}
              >
                <span className="truncate">{m.short}</span>
                {active && (sortDir === "asc" ? <ArrowUp className="h-2 w-2 shrink-0 ml-px" /> : <ArrowDown className="h-2 w-2 shrink-0 ml-px" />)}
              </button>
            </HoverTooltip>
          </th>
        );
      })}
    </tr>
  ), [sortKey, sortDir, setSort]);

  return (
    <TooltipProvider delayDuration={150} skipDelayDuration={0} disableHoverableContent>
      <div className="container mx-auto max-w-7xl px-4 py-8 space-y-5">
        <Link to="/validation" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" data-testid="opx-back">
          <ChevronLeft className="h-3 w-3" /> Back to Validation Hub
        </Link>

        <div>
          <span className="inline-block text-[10px] font-mono uppercase tracking-wider text-muted-foreground bg-secondary/60 px-2 py-0.5 rounded">
            Experiment · Open Problems
          </span>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">Author-flagged open problems</h1>
          <p className="mt-2 text-sm text-muted-foreground max-w-3xl leading-relaxed">
            Open research problems extracted from the <b>100 highest-ranked papers</b> across all arXiv categories.
            Claude Opus 4.8 reads each paper's full text and surfaces only problems the authors themselves
            explicitly call out as unsolved. Each problem is rated for <b>impact</b> (what the field gains if solved)
            and <b>difficulty</b> (how hard it would be for a competent group in 1-2 years), with a one-sentence
            justification per axis. The <b>Fruit</b> column is <code>impact × (10 − difficulty)</code> — sort by it
            to surface high-impact, low-hanging fruit.
          </p>
        </div>

        {data.loading && <div className="text-sm text-muted-foreground">Loading…</div>}
        {data.error && <div className="text-sm text-destructive">Error: {data.error}</div>}

        {!data.loading && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="opx-summary">
              <Stat label="Problems extracted" value={data.total} />
              <Stat label="Papers covered" value={`${data.papers_with_problems}/${data.papers_total}`} />
              <Stat label="Papers with none" value={data.papers_no_problems} />
              <Stat label="Visible" value={sorted.length} />
            </div>

            {/* Filter bar */}
            <div className="border border-border rounded-lg p-3 bg-card space-y-2.5" data-testid="opx-filter">
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative flex-1 min-w-[220px] max-w-md">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder="Search title / description / quote / paper…"
                    value={searchDraft}
                    onChange={(e) => setSearchDraft(e.target.value)}
                    className="w-full pl-7 pr-7 py-1.5 text-xs rounded border border-border bg-background outline-none focus:border-accent"
                    data-testid="opx-search"
                  />
                  {searchDraft && (
                    <button onClick={() => setSearchDraft("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>
                <div className="inline-flex rounded-md bg-secondary/60 p-0.5 gap-0.5" data-testid="opx-scope">
                  {[
                    { v: "all", label: "All scopes" },
                    { v: "field_general", label: "Field-general" },
                    { v: "paper_specific", label: "Paper-specific" },
                  ].map(o => {
                    const active = scope === o.v;
                    return (
                      <button
                        key={o.v}
                        onClick={() => setScope(o.v)}
                        className={`text-[10px] px-2.5 py-1 rounded transition-colors ${active ? "bg-background text-foreground shadow-sm font-medium" : "text-muted-foreground hover:text-foreground"}`}
                        data-testid={`opx-scope-${o.v}`}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <details className="border-t border-border/40 pt-2 group">
                <summary className="text-[10px] text-muted-foreground uppercase tracking-wider cursor-pointer select-none flex items-center gap-2 list-none [&::-webkit-details-marker]:hidden hover:text-foreground">
                  <span className="text-sm leading-none inline-block transition-transform group-open:rotate-90">▸</span>
                  <span>Category</span>
                  <span className="normal-case tracking-normal text-[11px] text-foreground/70 font-normal">
                    {categories.size === 0
                      ? `Any · all ${allCategories.length} categories`
                      : `${Array.from(categories).slice(0, 3).join(", ")}${categories.size > 3 ? ` +${categories.size - 3}` : ""}`}
                  </span>
                  {categories.size > 0 && (
                    <button
                      onClick={(e) => { e.preventDefault(); setCategories(new Set()); }}
                      className="ml-auto text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-secondary normal-case tracking-normal"
                      data-testid="opx-cat-clear"
                    >
                      Clear
                    </button>
                  )}
                </summary>
                <div className="flex flex-wrap gap-1 mt-2" data-testid="opx-category">
                  {allCategories.map(cat => {
                    const active = categories.has(cat);
                    const count = categoryCounts[cat] || 0;
                    return (
                      <button
                        key={cat}
                        onClick={() => toggleCategory(cat)}
                        className={`text-[10px] font-mono px-1.5 py-0.5 rounded border inline-flex items-center gap-1 transition-colors ${active ? "bg-accent text-accent-foreground border-accent" : "border-border bg-background text-muted-foreground hover:text-foreground"}`}
                        data-testid={`opx-cat-${cat}`}
                      >
                        {cat} <span className="opacity-70">{count}</span>
                      </button>
                    );
                  })}
                </div>
              </details>
            </div>

            <div className="border border-border rounded-lg bg-card" style={{ overflowX: "auto" }} data-testid="opx-table">
              <TableVirtuoso
                useWindowScroll
                data={sorted}
                increaseViewportBy={{ top: 400, bottom: 800 }}
                components={virtuosoComponents}
                fixedHeaderContent={fixedHeaderContent}
                itemContent={itemContent}
                computeItemKey={(_, p) => p.id}
              />
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  );
}

function SortHeader({ name, sortKey, current, dir, onClick }) {
  const active = current === sortKey;
  return (
    <button
      onClick={() => onClick(sortKey)}
      className={`text-[10px] font-medium hover:text-foreground transition-colors inline-flex items-center gap-1 ${active ? "text-foreground" : "text-muted-foreground"}`}
    >
      {name}
      {active && (dir === "asc" ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />)}
    </button>
  );
}

function Stat({ label, value }) {
  return (
    <div className="border border-border rounded-lg p-3 bg-card">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums mt-0.5">{value}</div>
    </div>
  );
}
