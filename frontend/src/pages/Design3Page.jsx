import { useRef, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ArrowUp, ArrowDown, ChevronRight, PanelLeftClose, PanelLeft } from "lucide-react";
import { Input } from "@/components/ui/input";
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

const SORTS = [
  { value: "score", label: "Score" },
  { value: "ai_rating", label: "Rating" },
  { value: "gap_score", label: "Gap" },
  { value: "published", label: "Published" },
  { value: "comparisons", label: "Matches" },
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

export default function Design3Page() {
  const d = useLeaderboardData();
  const sentinelRef = useRef(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [catSearch, setCatSearch] = useState("");
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

  // Group categories by domain for sidebar
  const filteredCats = catSearch
    ? d.categories.filter(c => c.id.toLowerCase().includes(catSearch.toLowerCase()) || c.name.toLowerCase().includes(catSearch.toLowerCase()))
    : d.categories;
  const grouped = {};
  for (const c of filteredCats) {
    const g = c.group || "Other";
    if (!grouped[g]) grouped[g] = [];
    grouped[g].push(c);
  }

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="flex min-h-[calc(100vh-65px)]">
        {/* Sidebar */}
        {sidebarOpen && (
          <aside className="w-64 shrink-0 border-r border-slate-200 bg-white overflow-y-auto">
            <div className="p-4 border-b border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Filters</span>
                <button onClick={() => setSidebarOpen(false)} className="text-slate-400 hover:text-slate-600"><PanelLeftClose className="h-4 w-4" /></button>
              </div>
              {/* Search */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <Input value={d.keyword} onChange={e => d.setKeyword(e.target.value)} placeholder="Search papers..."
                  className="pl-8 h-9 text-sm rounded-sm border-slate-200" />
              </div>
            </div>

            {/* Period */}
            <div className="p-4 border-b border-slate-100">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Time Period</div>
              <div className="space-y-0.5">
                {PERIODS.map(p => (
                  <button key={p.value} onClick={() => d.setPeriod(p.value)}
                    className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors ${d.period === p.value ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Sort */}
            <div className="p-4 border-b border-slate-100">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Sort By</div>
              <div className="space-y-0.5">
                {SORTS.map(s => (
                  <button key={s.value} onClick={() => d.handleSort(s.value)}
                    className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors flex items-center justify-between ${
                      (d.sortKey === s.value || (d.sortKey === "rank" && s.value === "score")) ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"
                    }`}>
                    <span>{s.label}</span>
                    {(d.sortKey === s.value) && <span className="text-[10px] text-blue-500">{d.sortDir === "asc" ? "↑" : "↓"}</span>}
                  </button>
                ))}
              </div>
            </div>

            {/* Categories */}
            <div className="p-4">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Categories</div>
              <div className="relative mb-2">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-slate-400" />
                <input value={catSearch} onChange={e => setCatSearch(e.target.value)} placeholder="Filter..."
                  className="w-full pl-7 pr-2 py-1.5 text-xs border border-slate-200 rounded-sm focus:outline-none focus:ring-1 focus:ring-blue-600" />
              </div>
              <div className="space-y-0.5 max-h-[400px] overflow-y-auto">
                <button onClick={() => d.setCategory("")}
                  className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors ${!d.category ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
                  All Categories
                </button>
                {Object.entries(grouped).sort(([a],[b]) => a.localeCompare(b)).map(([group, cats]) => (
                  <div key={group}>
                    <div className="px-2.5 pt-3 pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-400">{group}</div>
                    {cats.map(c => (
                      <button key={c.id} onClick={() => d.setCategory(c.id)}
                        className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors flex items-center gap-2 ${d.category === c.id ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
                        <span className="font-mono text-[10px] text-blue-600 shrink-0">{c.id}</span>
                        <span className="truncate">{c.name}</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </aside>
        )}

        {/* Main content */}
        <main className="flex-1 min-w-0">
          <div className="px-6 lg:px-8 pt-6 pb-12">
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
              {!sidebarOpen && (
                <button onClick={() => setSidebarOpen(true)} className="text-slate-400 hover:text-slate-600" title="Open sidebar">
                  <PanelLeft className="h-5 w-5" />
                </button>
              )}
              <div>
                <h1 className="font-serif text-2xl sm:text-3xl font-medium tracking-tight text-slate-900">{categoryName} Paper Rankings</h1>
                <p className="text-sm text-slate-500 mt-0.5">
                  {d.totalPapers} papers · {d.totalMatches} comparisons ·
                  <Link to="/methodology" className="text-blue-600 hover:underline ml-1">Methodology</Link>
                </p>
              </div>
            </div>

            {/* Table */}
            <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
              {d.loading && d.leaderboard.length === 0 ? (
                <div className="space-y-2 p-4">
                  {[...Array(10)].map((_, i) => <div key={i} className="h-12 bg-slate-50 rounded-sm animate-pulse" />)}
                </div>
              ) : d.leaderboard.length === 0 ? (
                <div className="py-16 text-center text-sm text-slate-400">No papers found for this period.</div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="text-[10px] font-medium uppercase tracking-wider text-slate-500 bg-slate-50 border-b border-slate-100">
                      <th className="pl-5 pr-2 py-2.5 text-center w-10"><SortHeader label="#" sortKey="rank" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-left"><SortHeader label="Paper" sortKey="title" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-right"><SortHeader label="Score" sortKey="score" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-right hidden md:table-cell"><SortHeader label="CI" sortKey="wilson_margin" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-right hidden md:table-cell"><SortHeader label="Match" sortKey="comparisons" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      <th className="px-2 py-2.5 text-right hidden lg:table-cell"><SortHeader label="Win %" sortKey="win_rate" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                      {d.showRatingCol && <th className="px-2 py-2.5 text-right hidden lg:table-cell"><SortHeader label="Rating" sortKey="ai_rating" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>}
                      {d.showGapCol && <th className="px-2 py-2.5 text-right hidden xl:table-cell"><SortHeader label="Gap" sortKey="gap_score" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>}
                      <th className="pl-2 pr-5 py-2.5 text-right hidden sm:table-cell"><SortHeader label="Published" sortKey="published" current={d.sortKey} dir={d.sortDir} onSort={d.handleSort} /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.leaderboard.map((p, i) => (
                      <tr key={p.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70 transition-colors">
                        <td className="pl-5 pr-2 py-3 text-center align-baseline"><span className="font-serif text-base font-medium text-blue-600">{p.rank_ts || p.rank || i + 1}</span></td>
                        <td className="px-2 py-3">
                          <Link to={`/paper/${p.id}`} className="text-sm font-medium text-slate-900 hover:text-blue-700 leading-snug line-clamp-2">
                            <LatexTitle text={p.title} />
                          </Link>
                          <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                            <span>{p.authors?.slice(0, 2).join(", ")}{p.authors?.length > 2 ? ` +${p.authors.length - 2}` : ""}</span>
                            {p.primary_category && (
                              <>
                                <span className="text-slate-300">·</span>
                                <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium bg-blue-50 text-blue-700 border-blue-200">{p.primary_category}</span>
                              </>
                            )}
                          </div>
                        </td>
                        <td className="px-2 py-3 text-right align-baseline"><span className="text-sm font-semibold tabular-nums">{p.ts_score || p.score || "—"}</span></td>
                        <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden md:table-cell">{p.ci > 0 ? `±${Math.round(p.ci)}` : "—"}</td>
                        <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden md:table-cell">{p.comparisons ?? "—"}</td>
                        <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden lg:table-cell">{p.win_rate != null ? `${p.win_rate}%` : "—"}</td>
                        {d.showRatingCol && <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden lg:table-cell">{p.ai_rating || "—"}</td>}
                        {d.showGapCol && <td className={`px-2 py-3 text-right align-baseline text-xs hidden xl:table-cell ${p.gap_score > 0 ? "text-emerald-600" : p.gap_score < 0 ? "text-red-400" : "text-slate-500"}`}>{p.gap_score != null ? (p.gap_score > 0 ? "+" : "") + p.gap_score : "—"}</td>}
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
        </main>
      </div>
      <SiteFooter />
    </div>
  );
}
