import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ArrowRight, BookOpen, Sparkles, Clock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, accentFor, PERIODS, RANK_TYPES } from "@/lib/api";

const COL_LABEL = { score: "Score", rating: "Rating", gap: "Gap" };
const COL_TOOLTIP = {
  score: "Comparative tournament-based ranking score",
  rating: "Standalone scientific impact rating from 1.0 to 10.0",
  gap: "Percentile difference between Score and Rating",
};

function CategoryChip({ code, name, field, active, onClick }) {
  const a = accentFor(field);
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={`chip-${code}`}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-all ${a.bg} ${a.text} ${active ? "ring-1 ring-blue-600 border-blue-600" : a.border}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${a.dot}`} />
      {code}
      <span className="text-slate-500 font-normal hidden sm:inline">· {name}</span>
    </button>
  );
}

function MetricTile({ label, value, last }) {
  return (
    <div className={`flex flex-col px-6 py-5 ${last ? "" : "border-r border-slate-200"}`}>
      <span className="font-serif text-3xl font-medium text-slate-900 leading-none">{value}</span>
      <span className="mt-2 text-xs font-medium uppercase tracking-[0.08em] text-slate-500">{label}</span>
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
    rankType === "rating" ? value.toFixed(1) :
    rankType === "gap" ? `${value}%` :
    value;
  return (
    <tr className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70 transition-colors cursor-pointer" data-testid={`paper-row-${paper.id}`}>
      <td className="pl-5 pr-2 py-3 align-top w-10">
        <span className="font-serif text-lg text-slate-900">{paper.rank}</span>
      </td>
      <td className="px-2 py-3 align-top">
        <div className="text-sm font-medium text-slate-900 leading-snug line-clamp-2 pr-2">{paper.title}</div>
        <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500 flex-wrap">
          {paper.category_code && paper.category_code !== "—" && (
            <>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium bg-blue-50 text-blue-700 border-blue-200">
                {paper.category_code}
              </span>
              <span className="hidden md:inline text-slate-500">·</span>
            </>
          )}
          <span className="hidden md:inline">{paper.authors.slice(0, 2).join(", ")}{paper.authors.length > 2 ? ` +${paper.authors.length - 2}` : ""}</span>
        </div>
      </td>
      <td className="px-2 py-3 align-top text-right whitespace-nowrap">
        <span className="font-serif text-base text-slate-900">{display}</span>
      </td>
      <td className="pl-2 pr-5 py-3 align-top text-right whitespace-nowrap text-xs text-slate-500 hidden sm:table-cell">
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
    Promise.all([api.categories(), api.metrics()]).then(([c, m]) => {
      setCategories(c); setMetrics(m);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    api.papers({ category, period, rank_type: rankType, q, limit: 8 })
      .then((res) => setPapers(res.results))
      .finally(() => setLoading(false));
  }, [category, period, rankType, q]);

  const chipCats = useMemo(() => categories.slice(0, 8), [categories]);
  const filterParams = new URLSearchParams({ category, period, rank_type: rankType, q }).toString();

  return (
    <section id="rankings" className="bg-white">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-10 lg:pt-14 pb-12">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-slate-500">
          <span className="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          Live · Scientific Paper Rankings
        </div>

        <div className="mt-6 grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12">
          {/* LEFT */}
          <div className="lg:col-span-5 flex flex-col">
            <h1 className="font-serif text-4xl sm:text-5xl lg:text-[3.25rem] font-medium leading-[1.05] tracking-tight text-slate-900">
              Paper Rankings.
              <span className="block text-slate-500 italic font-normal">across live arXiv categories.</span>
            </h1>
            <p className="mt-5 text-base text-slate-600 leading-relaxed max-w-xl">
              Search and explore AI-assisted scientific preprint rankings. Kurate helps researchers
              explore ranked papers using category-based leaderboards and AI-assisted paper comparison.
            </p>

            <div className="mt-7 border border-slate-200 bg-white p-5 rounded-sm shadow-[0_1px_0_rgba(15,23,42,0.04)]">
              <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Search</label>
              <div className="relative mt-1.5">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <Input
                  data-testid="search-input"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search papers, authors, topics, or arXiv categories..."
                  className="pl-9 h-10 rounded-sm border-slate-200 focus-visible:ring-1 focus-visible:ring-blue-600 focus-visible:border-blue-600"
                />
              </div>

              <div className="mt-4 grid grid-cols-2 lg:grid-cols-3 gap-3">
                <div>
                  <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Category</label>
                  <Select value={category} onValueChange={setCategory}>
                    <SelectTrigger data-testid="filter-category" className="mt-1.5 h-10 rounded-sm border-slate-200">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Categories</SelectItem>
                      {categories.map((c) => (
                        <SelectItem key={c.code} value={c.code}>{c.code} · {c.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Time Period</label>
                  <Select value={period} onValueChange={setPeriod}>
                    <SelectTrigger data-testid="filter-period" className="mt-1.5 h-10 rounded-sm border-slate-200">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PERIODS.map((p) => (
                        <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="col-span-2 lg:col-span-1">
                  <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Sort by</label>
                  <Select value={rankType} onValueChange={setRankType}>
                    <SelectTrigger data-testid="filter-rank-type" className="mt-1.5 h-10 rounded-sm border-slate-200">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RANK_TYPES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="mt-5 flex flex-col sm:flex-row gap-2">
                <Link
                  to={`/leaderboard?${filterParams}`}
                  data-testid="search-rankings-button"
                  className="flex-1 inline-flex h-10 items-center justify-center gap-2 rounded-sm bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
                >
                  <Search className="h-4 w-4" /> Search Rankings
                </Link>
                <a
                  href="https://kurate.org/methodology"
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="view-methodology-button"
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-sm border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors"
                >
                  <BookOpen className="h-4 w-4" /> Methodology
                </a>
              </div>
            </div>

            <div className="mt-5">
              <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500 mb-2">Quick categories</div>
              <div className="flex flex-wrap gap-2">
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
          <div className="lg:col-span-7">
            <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2 min-w-0">
                  <Sparkles className="h-4 w-4 text-blue-600 shrink-0" strokeWidth={1.5} />
                  <h2 className="font-serif text-lg font-medium text-slate-900 truncate">Top Papers</h2>
                </div>
                <Link
                  to={`/leaderboard?${filterParams}`}
                  data-testid="view-full-leaderboard-link"
                  className="text-xs font-medium text-blue-600 hover:text-blue-700 inline-flex items-center gap-1 whitespace-nowrap"
                >
                  Full leaderboard <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
              <table className="w-full" data-testid="leaderboard-table">
                <thead>
                  <tr className="text-[10px] font-medium uppercase tracking-wider text-slate-500 bg-white border-b border-slate-100">
                    <th className="pl-5 pr-2 py-2.5 text-left w-10">#</th>
                    <th className="px-2 py-2.5 text-left">Paper</th>
                    <th className="px-2 py-2.5 text-right" title={COL_TOOLTIP[rankType]}>{COL_LABEL[rankType]}</th>
                    <th className="pl-2 pr-5 py-2.5 text-right hidden sm:table-cell">Published</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && papers.length === 0 && (
                    <tr><td colSpan={4} className="px-5 py-10 text-center text-sm text-slate-500">Loading rankings…</td></tr>
                  )}
                  {!loading && papers.length === 0 && (
                    <tr><td colSpan={4} className="px-5 py-10 text-center text-sm text-slate-500">No papers match these filters.</td></tr>
                  )}
                  {papers.map((p) => <LeaderboardRow key={p.id} paper={p} rankType={rankType} />)}
                </tbody>
              </table>
              <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between text-xs text-slate-500">
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="h-3 w-3" /> Updated {metrics?.latest_update || "—"}
                </span>
                <Link to={`/leaderboard?${filterParams}`} data-testid="view-full-leaderboard-footer" className="font-medium text-blue-600 hover:text-blue-700">View all →</Link>
              </div>
            </div>
          </div>
        </div>

        {/* Metrics strip — only live, supported numbers */}
        <div className="mt-10 border border-slate-200 rounded-sm bg-white grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-4 divide-y sm:divide-y-0">
          <MetricTile label="Papers Ranked" value={metrics?.papers_ranked ?? "—"} />
          <MetricTile label="Active Categories" value={metrics?.active_categories ?? "—"} />
          <MetricTile label="AI Judges" value={metrics?.ai_judges ?? "—"} />
          <MetricTile label="Latest Update" value={metrics?.latest_update ?? "—"} last />
        </div>
      </div>
    </section>
  );
}
