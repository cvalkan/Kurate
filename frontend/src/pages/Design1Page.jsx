import { useRef, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ArrowUp, ArrowDown, ChevronDown, BookOpen, Clock, Sparkles } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LatexTitle } from "@/components/LatexTitle";
import { useLeaderboardData } from "@/hooks/useLeaderboardData";
import TopNav from "@/components/site/TopNav";
import SiteFooter from "@/components/site/SiteFooter";

const PERIODS = [
  { value: "recent", label: "Newly Added" },
  { value: "week", label: "Last 7 Days" },
  { value: "month", label: "Last 30 Days" },
  { value: "all", label: "All Time" },
];

function SortHeader({ label, sortKey, current, dir, onSort }) {
  const active = current === sortKey;
  return (
    <button onClick={() => onSort(sortKey)} className={`inline-flex items-center gap-0.5 hover:text-slate-900 transition-colors ${active ? "text-slate-900" : ""}`}>
      {label}
      {active && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
    </button>
  );
}

/* ── Searchable Category Dropdown (reused from homepage) ── */
function CategoryDropdown({ categories, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const grouped = useMemo(() => {
    const fl = filter.toLowerCase();
    const filtered = categories.filter(c =>
      !fl || c.id.toLowerCase().includes(fl) || c.name.toLowerCase().includes(fl) || (c.group || "").toLowerCase().includes(fl)
    );
    const groups = {};
    for (const c of filtered) {
      const g = c.group || "Other";
      if (!groups[g]) groups[g] = [];
      groups[g].push(c);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [categories, filter]);

  const selected = categories.find(c => c.id === value);
  const label = !value ? "All Categories" : (selected ? `${selected.id} · ${selected.name}` : value);

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)}
        className="flex h-10 w-full items-center justify-between rounded-sm border border-slate-200 bg-transparent px-3 py-2 text-sm shadow-sm">
        <span className="truncate text-left">{label}</span>
        <ChevronDown className="h-4 w-4 opacity-50 shrink-0 ml-1" />
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 w-72 max-h-80 overflow-y-auto rounded-sm border border-slate-200 bg-white shadow-lg">
          <div className="sticky top-0 bg-white border-b border-slate-100 p-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
              <input autoFocus value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter categories..."
                className="w-full pl-8 pr-3 py-1.5 text-sm border border-slate-200 rounded-sm focus:outline-none focus:ring-1 focus:ring-blue-600" />
            </div>
          </div>
          <div className="p-1">
            <button onClick={() => { onChange(""); setOpen(false); setFilter(""); }}
              className={`w-full text-left px-3 py-2 text-sm rounded-sm transition-colors ${!value ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-50"}`}>
              All Categories
            </button>
            {grouped.map(([group, cats]) => (
              <div key={group}>
                <div className="px-3 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">{group}</div>
                {cats.map(c => (
                  <button key={c.id} onClick={() => { onChange(c.id); setOpen(false); setFilter(""); }}
                    className={`w-full text-left px-3 py-1.5 text-sm rounded-sm transition-colors flex items-center gap-2 ${value === c.id ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-50"}`}>
                    <span className="font-mono text-blue-600 text-xs">{c.id}</span>
                    <span className="text-slate-700">{c.name}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Design1Page() {
  const d = useLeaderboardData();
  const sentinelRef = useRef(null);
  const categoryName = d.category ? (d.categories.find(c => c.id === d.category)?.name || "Papers") : "All";

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && d.nextCursor && !d.loadingMore) d.loadMore();
    }, { rootMargin: "400px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [d.loadMore, d.nextCursor, d.loadingMore]); // eslint-disable-line react-hooks/exhaustive-deps

  // Quick category chips from featured
  const featuredSet = new Set(d.featured);
  const chipCats = d.categories.filter(c => featuredSet.has(c.id));

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-10 pb-12">
        {/* Title */}
        <h1 className="font-serif text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 mb-2">{categoryName} Paper Rankings</h1>
        <p className="text-sm text-slate-600 max-w-2xl mb-8">
          AI-estimated scientific impact ranking. Papers compared using full-text analysis by multiple LLMs.
          <Link to="/methodology" className="text-blue-600 hover:underline ml-1">Methodology</Link>
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          {/* LEFT — Filter card */}
          <div className="lg:col-span-4">
            <div className="border border-slate-200 bg-white p-5 rounded-sm shadow-[0_1px_0_rgba(15,23,42,0.04)] sticky top-20">
              <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Search</label>
              <div className="relative mt-1.5">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <Input value={d.keyword} onChange={e => d.setKeyword(e.target.value)} placeholder="Search papers, authors..."
                  className="pl-9 h-10 rounded-sm border-slate-200 focus-visible:ring-1 focus-visible:ring-blue-600" />
              </div>

              <div className="mt-4">
                <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Category</label>
                <div className="mt-1.5">
                  <CategoryDropdown categories={d.categories} value={d.category} onChange={d.setCategory} />
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Time Period</label>
                  <Select value={d.period} onValueChange={d.setPeriod}>
                    <SelectTrigger className="mt-1.5 h-10 rounded-sm border-slate-200"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PERIODS.map(p => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500">Sort by</label>
                  <Select value={d.sortKey === "rank" ? "score" : d.sortKey} onValueChange={k => d.handleSort(k)}>
                    <SelectTrigger className="mt-1.5 h-10 rounded-sm border-slate-200"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="score">Score</SelectItem>
                      <SelectItem value="ai_rating">Rating</SelectItem>
                      <SelectItem value="gap_score">Gap</SelectItem>
                      <SelectItem value="published">Published</SelectItem>
                      <SelectItem value="comparisons">Matches</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Quick categories */}
              <div className="mt-5 pt-4 border-t border-slate-100">
                <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500 mb-2">Quick categories</div>
                <div className="flex flex-wrap gap-1.5">
                  <button onClick={() => d.setCategory("")}
                    className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
                      !d.category ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
                    }`}>
                    All
                  </button>
                  {chipCats.map(c => (
                    <button key={c.id} onClick={() => d.setCategory(c.id)}
                      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
                        d.category === c.id ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
                      }`}>
                      {c.name}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4 pt-4 border-t border-slate-100 text-xs text-slate-400">
                {d.totalPapers} papers · {d.totalMatches} comparisons
              </div>
            </div>
          </div>

          {/* RIGHT — Table */}
          <div className="lg:col-span-8">
            <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-blue-600" strokeWidth={1.5} />
                  <h2 className="font-serif text-lg font-medium text-slate-900">{categoryName}</h2>
                </div>
                <span className="text-xs text-slate-500">{d.leaderboard.length} papers shown</span>
              </div>

              {d.loading && d.leaderboard.length === 0 ? (
                <div className="space-y-2 p-4">
                  {[...Array(8)].map((_, i) => <div key={i} className="h-12 bg-slate-50 rounded-sm animate-pulse" />)}
                </div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="text-[10px] font-medium uppercase tracking-wider text-slate-500 bg-white border-b border-slate-100">
                      <th className="pl-5 pr-2 py-2.5 text-center w-10"><SortHeader label="#" sortKey="rank" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-left"><SortHeader label="Paper" sortKey="title" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-right"><SortHeader label="Score" sortKey="score" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      {d.showRatingCol && <th className="px-2 py-2.5 text-right hidden lg:table-cell"><SortHeader label="Rating" sortKey="ai_rating" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>}
                      <th className="pl-2 pr-5 py-2.5 text-right hidden sm:table-cell"><SortHeader label="Published" sortKey="published" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.leaderboard.map((p, i) => (
                      <tr key={p.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70 transition-colors">
                        <td className="pl-5 pr-2 py-3 text-center align-baseline"><span className="font-serif text-base font-medium text-blue-600">{p.rank_ts || p.rank || i + 1}</span></td>
                        <td className="px-2 py-3">
                          <Link to={`/paper/${p.id}`} className="text-sm font-medium text-slate-900 hover:text-blue-700 transition-colors leading-snug line-clamp-2">
                            <LatexTitle text={p.title} />
                          </Link>
                          <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500 flex-wrap">
                            <span>{p.authors?.slice(0, 2).join(", ")}{p.authors?.length > 2 ? ` +${p.authors.length - 2}` : ""}</span>
                          </div>
                        </td>
                        <td className="px-2 py-3 text-right align-baseline"><span className="text-sm font-semibold text-slate-900 tabular-nums">{p.ts_score || p.score || "—"}</span></td>
                        {d.showRatingCol && <td className="px-2 py-3 text-right align-baseline hidden lg:table-cell text-xs text-slate-500">{p.ai_rating || "—"}</td>}
                        <td className="pl-2 pr-5 py-3 text-right align-baseline text-xs text-slate-500 hidden sm:table-cell">
                          {p.published ? new Date(p.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {d.nextCursor && <div ref={sentinelRef} className="py-4 text-center text-xs text-slate-400">{d.loadingMore ? "Loading more..." : ""}</div>}
            </div>
          </div>
        </div>
      </div>
      <SiteFooter />
    </div>
  );
}
