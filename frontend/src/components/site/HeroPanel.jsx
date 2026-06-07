import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ArrowRight, BookOpen, Sparkles, Clock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { homepageApi, accentFor, PERIODS, RANK_TYPES } from "@/lib/homepage-api";

const COL_LABEL = { score: "Score", rating: "Rating", gap: "Gap" };

function CategoryChip({ code, name, field, active, onClick }) {
  const a = accentFor(field);
  return (
    <button
      onClick={onClick}
      data-testid={`chip-${code}`}
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
        active
          ? `${a.bg} ${a.text} ${a.border} ring-1 ring-current/10`
          : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
      }`}
    >
      {code}
      <span className="ml-1 opacity-60">· {name}</span>
    </button>
  );
}

function MetricTile({ label, value, last }) {
  return (
    <div className={`flex flex-col items-center py-3 px-4 ${!last ? "border-r border-slate-200" : ""}`}>
      <span className="text-lg font-semibold text-slate-900 tabular-nums">{value}</span>
      <span className="text-[11px] text-slate-500 mt-0.5">{label}</span>
    </div>
  );
}

function formatPublished(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function LeaderboardRow({ paper, rankType }) {
  const value = paper[rankType] ?? paper.score;
  const display =
    rankType === "rating" ? (value || 0).toFixed(1) :
    rankType === "gap" ? `${value || 0}%` :
    value;
  return (
    <tr className="border-b border-slate-100 last:border-0 hover:bg-slate-50/60 transition-colors">
      <td className="py-2.5 pl-4 pr-2 text-xs text-slate-400 font-mono w-8">{paper.rank}</td>
      <td className="py-2.5 px-2">
        <Link to={`/paper/${paper.id}`} className="text-sm font-medium text-slate-900 hover:text-blue-700 transition-colors line-clamp-1" data-testid={`paper-link-${paper.rank}`}>
          {paper.title}
        </Link>
        <div className="flex items-center gap-1.5 mt-0.5 text-[11px] text-slate-500">
          {paper.category_code && paper.category_code !== "—" && (
            <>
              <span className="font-mono text-slate-400">{paper.category_code}</span>
              <span className="text-slate-300">·</span>
            </>
          )}
          {paper.authors.slice(0, 2).join(", ")}{paper.authors.length > 2 ? ` +${paper.authors.length - 2}` : ""}
        </div>
      </td>
      <td className="py-2.5 px-2 text-right text-sm font-semibold text-slate-900 tabular-nums w-20">{display}</td>
      <td className="py-2.5 pr-4 text-right text-[11px] text-slate-400 w-28 hidden sm:table-cell">
        {formatPublished(paper.published_at)}
      </td>
    </tr>
  );
}

export default function HeroPanel() {
  const [categories, setCategories] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);

  const [q, setQ] = useState("");
  const [category, setCategory] = useState("all");
  const [period, setPeriod] = useState("all");
  const [rankType, setRankType] = useState("score");

  useEffect(() => {
    Promise.all([homepageApi.categories(), homepageApi.metrics()]).then(([c, m]) => {
      setCategories(c); setMetrics(m);
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const fetchPapers = async () => {
      setLoading(true);
      try {
        const res = await homepageApi.papers({ category, period, rank_type: rankType, q, limit: 8 });
        if (!cancelled) setPapers(res.results);
      } catch {
        // ignore
      }
      if (!cancelled) setLoading(false);
    };
    fetchPapers();
    return () => { cancelled = true; };
  }, [category, period, rankType, q]);

  const chipCats = useMemo(() => categories.slice(0, 8), [categories]);
  const filterParams = new URLSearchParams({ category, period, rank_type: rankType, q }).toString();

  return (
    <section id="rankings" className="w-full bg-white" data-testid="hero-panel">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-10 pb-6">
        {/* Live badge */}
        <div className="flex items-center gap-2 mb-6">
          <span className="relative flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" /><span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" /></span>
          <span className="text-xs font-medium text-slate-500">Live · Scientific Paper Rankings</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-start">
          {/* LEFT */}
          <div className="space-y-5">
            <h1 className="font-serif text-4xl sm:text-5xl lg:text-[3.25rem] leading-[1.1] tracking-tight text-slate-900">
              Paper Rankings. <br className="hidden sm:block" /> across live arXiv categories.
            </h1>
            <p className="text-base text-slate-600 max-w-lg leading-relaxed">
              Search and explore AI-assisted scientific preprint rankings. Kurate helps researchers
              explore ranked papers using category-based leaderboards and AI-assisted paper comparison.
            </p>

            {/* Search + Filters */}
            <div className="space-y-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <Input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search papers, authors, topics, or arXiv categories..."
                  className="pl-9 h-10 rounded-sm border-slate-200 focus-visible:ring-1 focus-visible:ring-blue-600 focus-visible:border-blue-600"
                  data-testid="hero-search"
                />
              </div>

              <div className="flex flex-wrap gap-2">
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger className="w-[180px] h-9 text-xs rounded-sm border-slate-200" data-testid="hero-category-select">
                    <SelectValue placeholder="Category" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Categories</SelectItem>
                    {categories.map((c) => (
                      <SelectItem key={c.code} value={c.code}>{c.code} · {c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={period} onValueChange={setPeriod}>
                  <SelectTrigger className="w-[140px] h-9 text-xs rounded-sm border-slate-200" data-testid="hero-period-select">
                    <SelectValue placeholder="Time Period" />
                  </SelectTrigger>
                  <SelectContent>
                    {PERIODS.map((p) => (
                      <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={rankType} onValueChange={setRankType}>
                  <SelectTrigger className="w-[120px] h-9 text-xs rounded-sm border-slate-200" data-testid="hero-ranktype-select">
                    <SelectValue placeholder="Sort by" />
                  </SelectTrigger>
                  <SelectContent>
                    {RANK_TYPES.map((r) => (
                      <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center gap-2">
                <Link
                  to={`/leaderboard`}
                  className="inline-flex items-center gap-1.5 rounded-sm bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 transition-colors"
                  data-testid="hero-search-btn"
                >
                  Search Rankings
                </Link>
                <Link
                  to="/methodology"
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900 transition-colors"
                  data-testid="hero-methodology-link"
                >
                  <BookOpen className="h-3.5 w-3.5" /> Methodology
                </Link>
              </div>
            </div>

            {/* Quick categories */}
            <div className="space-y-2 pt-2">
              <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Quick categories</span>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setCategory("all")}
                  data-testid="chip-all"
                  className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${category === "all" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-700 border-slate-200 hover:border-slate-400"}`}
                >
                  All
                </button>
                {chipCats.map((c) => (
                  <CategoryChip
                    key={c.code}
                    code={c.code}
                    name={c.name}
                    field={c.field}
                    active={category === c.code}
                    onClick={() => setCategory(c.code === category ? "all" : c.code)}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* RIGHT - Top Papers leaderboard */}
          <div className="border border-slate-200 rounded-sm overflow-hidden bg-white" data-testid="hero-leaderboard">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50/50">
              <h2 className="font-serif text-lg text-slate-900">Top Papers</h2>
              <Link to="/leaderboard" className="text-xs font-medium text-blue-600 hover:text-blue-800 flex items-center gap-1" data-testid="hero-full-leaderboard-link">
                Full leaderboard <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-100 text-[11px] uppercase text-slate-400 tracking-wider">
                  <th className="py-2 pl-4 pr-2 font-medium">#</th>
                  <th className="py-2 px-2 font-medium">Paper</th>
                  <th className="py-2 px-2 text-right font-medium">{COL_LABEL[rankType]}</th>
                  <th className="py-2 pr-4 text-right font-medium hidden sm:table-cell">Published</th>
                </tr>
              </thead>
              <tbody>
                {loading && papers.length === 0 && (
                  <tr><td colSpan="4" className="py-10 text-center text-sm text-slate-400">Loading rankings...</td></tr>
                )}
                {!loading && papers.length === 0 && (
                  <tr><td colSpan="4" className="py-10 text-center text-sm text-slate-400">No papers match these filters.</td></tr>
                )}
                {papers.map((p) => <LeaderboardRow key={p.id} paper={p} rankType={rankType} />)}
              </tbody>
            </table>
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-100 bg-slate-50/30">
              <span className="text-[11px] text-slate-400 flex items-center gap-1">
                <Clock className="h-3 w-3" /> Updated {metrics?.latest_update || "—"}
              </span>
              <Link to="/leaderboard" className="text-[11px] font-medium text-blue-600 hover:text-blue-800" data-testid="hero-view-all-link">
                View all <ArrowRight className="h-3 w-3 inline" />
              </Link>
            </div>
          </div>
        </div>

        {/* Metrics strip */}
        {metrics && (
          <div className="flex justify-center border border-slate-200 rounded-sm mt-8 divide-x divide-slate-200 bg-white" data-testid="hero-metrics">
            <MetricTile label="Papers Ranked" value={metrics.papers_ranked?.toLocaleString()} />
            <MetricTile label="Active Categories" value={metrics.active_categories} />
            <MetricTile label="Comparisons" value={metrics.total_comparisons?.toLocaleString()} />
            <MetricTile label="AI Judges" value={metrics.ai_judges} last />
          </div>
        )}
      </div>
    </section>
  );
}
