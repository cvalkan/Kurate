import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { ChevronLeft, Search, X, Quote, FileText, Sparkles, Filter } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const SECTION_COLORS = {
  "Limitations":  "#ef4444",
  "Future Work":  "#3b82f6",
  "Discussion":   "#a855f7",
  "Conclusion":   "#22c55e",
  "Introduction": "#eab308",
  "Other":        "#6b7280",
};

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}

export default function OpenProblemsExperimentPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("all");        // all | field_general | paper_specific
  const [section, setSection] = useState("all");    // all | Limitations | ...
  const [groupByPaper, setGroupByPaper] = useState(false);

  useEffect(() => {
    setLoading(true);
    axios.get(`${API}/api/experiments/open-problems?limit=2000`)
      .then(r => setData(r.data))
      .catch(e => setData({ error: String(e) }))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (!data?.problems) return [];
    const q = search.trim().toLowerCase();
    return data.problems.filter(p => {
      if (scope !== "all" && p.scope !== scope) return false;
      if (section !== "all" && p.source_section !== section) return false;
      if (q) {
        const hay = `${p.title} ${p.description} ${p.evidence_quote} ${p.paper_title}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [data, search, scope, section]);

  const sectionCounts = useMemo(() => {
    if (!data?.problems) return {};
    const c = {};
    data.problems.forEach(p => { c[p.source_section] = (c[p.source_section] || 0) + 1; });
    return c;
  }, [data]);

  const sections = Object.keys(SECTION_COLORS);

  return (
    <div className="container mx-auto max-w-6xl px-4 py-8 space-y-6">
      {/* Breadcrumb */}
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
          Claude Opus 4.8 reads each paper's full text and surfaces only problems that the authors themselves
          explicitly call out as unsolved, as limitations, or as future directions — every problem carries a
          verbatim quote so you can verify it. Eventually these will run in a pairwise tournament along two axes
          (impact × difficulty) to identify high-impact, low-hanging fruit.
        </p>
      </div>

      {loading && <div className="text-sm text-muted-foreground">Loading…</div>}
      {data?.error && <div className="text-sm text-destructive">Error: {data.error}</div>}

      {data && !loading && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="opx-summary">
            <Stat label="Problems extracted" value={data.total} />
            <Stat label="Papers with ≥1 problem" value={`${data.papers_with_problems}/${data.papers_total}`} />
            <Stat label="Papers with none" value={data.papers_no_problems} />
            <Stat label="Visible after filters" value={filtered.length} />
          </div>

          {/* Filter bar */}
          <div className="border border-border rounded-lg p-3 bg-card space-y-2.5" data-testid="opx-filter">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[220px] max-w-md">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search title / description / quote / paper…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-7 pr-7 py-1.5 text-xs rounded border border-border bg-background outline-none focus:border-accent"
                  data-testid="opx-search"
                />
                {search && (
                  <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>

              <div className="inline-flex rounded-md bg-secondary/60 p-0.5 gap-0.5" data-testid="opx-scope">
                {[
                  { v: "all", label: "All scopes" },
                  { v: "field_general", label: "Field-general only" },
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

              <label className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={groupByPaper}
                  onChange={(e) => setGroupByPaper(e.target.checked)}
                  className="accent-accent"
                  data-testid="opx-group-toggle"
                />
                Group by paper
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <Filter className="h-3 w-3 text-muted-foreground" />
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground mr-1">Source section</span>
              <button
                onClick={() => setSection("all")}
                className={`text-[10px] px-2 py-0.5 rounded border ${section === "all" ? "bg-foreground text-background border-foreground" : "border-border bg-background text-muted-foreground hover:text-foreground"}`}
                data-testid="opx-section-all"
              >
                All
              </button>
              {sections.map(s => {
                const count = sectionCounts[s] || 0;
                if (count === 0) return null;
                const active = section === s;
                const col = SECTION_COLORS[s];
                return (
                  <button
                    key={s}
                    onClick={() => setSection(s)}
                    className={`text-[10px] px-2 py-0.5 rounded border inline-flex items-center gap-1`}
                    style={active
                      ? { borderColor: col, backgroundColor: col, color: "#fff" }
                      : { borderColor: col, color: col, backgroundColor: `${col}10` }}
                    data-testid={`opx-section-${s}`}
                  >
                    {s} <span className="opacity-70 font-mono">{count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Problem list */}
          {groupByPaper ? <GroupedView problems={filtered} /> : <FlatView problems={filtered} />}
        </>
      )}
    </div>
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

function ProblemCard({ problem, hidePaperLink = false }) {
  const col = SECTION_COLORS[problem.source_section] || SECTION_COLORS.Other;
  return (
    <div className="border border-border rounded-lg p-4 bg-card hover:border-accent/40 transition-colors" data-testid={`opx-problem-${problem.id}`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-medium leading-snug">
          <Sparkles className="inline h-3 w-3 mr-1 text-accent" />
          {problem.title}
        </h3>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded border whitespace-nowrap shrink-0"
          style={{ borderColor: col, color: col, backgroundColor: `${col}10` }}
        >
          {problem.source_section}
        </span>
      </div>

      <p className="text-[12.5px] text-foreground/85 leading-snug">{problem.description}</p>

      {problem.evidence_quote && (
        <div className="mt-2.5 pl-3 border-l-2 border-border/60">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5 flex items-center gap-1">
            <Quote className="h-3 w-3" /> Authors say
          </div>
          <p className="text-[11.5px] text-muted-foreground italic leading-snug">&ldquo;{problem.evidence_quote}&rdquo;</p>
        </div>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
        {!hidePaperLink && (
          <span className="inline-flex items-center gap-1" title={problem.paper_title}>
            <FileText className="h-3 w-3" />
            <span className="line-clamp-1 max-w-md">{problem.paper_title}</span>
          </span>
        )}
        {(problem.paper_categories || []).slice(0, 3).map(c => (
          <span key={c} className="font-mono px-1 py-0.5 rounded bg-secondary/40">{c}</span>
        ))}
        {problem.paper_published && <span>{fmtDate(problem.paper_published)}</span>}
        {problem.paper_score != null && <span className="font-mono">score {problem.paper_score}</span>}
        <span className={`font-mono ${problem.scope === "field_general" ? "text-foreground/70" : "text-amber-600"}`}>
          {problem.scope}
        </span>
      </div>
    </div>
  );
}

function FlatView({ problems }) {
  if (problems.length === 0) {
    return <div className="text-sm text-muted-foreground py-10 text-center">No problems match current filters.</div>;
  }
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3" data-testid="opx-list">
      {problems.map(p => <ProblemCard key={p.id} problem={p} />)}
    </div>
  );
}

function GroupedView({ problems }) {
  const grouped = useMemo(() => {
    const m = new Map();
    problems.forEach(p => {
      if (!m.has(p.paper_id)) m.set(p.paper_id, {
        paper_id: p.paper_id,
        paper_title: p.paper_title,
        paper_score: p.paper_score,
        paper_categories: p.paper_categories,
        paper_published: p.paper_published,
        problems: [],
      });
      m.get(p.paper_id).problems.push(p);
    });
    return Array.from(m.values()).sort((a, b) => (b.paper_score || 0) - (a.paper_score || 0));
  }, [problems]);

  if (grouped.length === 0) {
    return <div className="text-sm text-muted-foreground py-10 text-center">No problems match current filters.</div>;
  }

  return (
    <div className="space-y-5" data-testid="opx-grouped">
      {grouped.map(g => (
        <div key={g.paper_id}>
          <div className="flex items-center gap-3 mb-2 text-xs">
            <FileText className="h-3.5 w-3.5 text-accent" />
            <div className="font-medium">{g.paper_title}</div>
            <div className="flex-1" />
            <div className="text-[10px] text-muted-foreground flex items-center gap-2">
              {(g.paper_categories || []).slice(0, 3).map(c => (
                <span key={c} className="font-mono px-1 py-0.5 rounded bg-secondary/40">{c}</span>
              ))}
              {g.paper_published && <span>{fmtDate(g.paper_published)}</span>}
              {g.paper_score != null && <span className="font-mono">score {g.paper_score}</span>}
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 pl-6 border-l-2 border-border/40 ml-1.5">
            {g.problems.map(p => <ProblemCard key={p.id} problem={p} hidePaperLink={true} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
