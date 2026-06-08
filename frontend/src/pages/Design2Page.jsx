import { useRef, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ArrowUp, ArrowDown, ChevronDown, Sparkles } from "lucide-react";
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

export default function Design2Page() {
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

  // Quick category chips
  const featuredSet = new Set(d.featured);
  const chipCats = d.categories.filter(c => featuredSet.has(c.id));

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-10 pb-12">
        {/* Title */}
        <h1 className="font-serif text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 mb-1">{categoryName} Paper Rankings</h1>
        <p className="text-sm text-slate-600 mb-6">
          {d.totalPapers} papers · {d.totalMatches} comparisons ·
          <Link to="/methodology" className="text-blue-600 hover:underline ml-1">Methodology</Link>
        </p>

        {/* Category chips */}
        <div className="flex flex-wrap gap-2 mb-6">
          <button onClick={() => d.setCategory("")}
            className={`inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
              !d.category ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
            }`}>
            All Categories
          </button>
          {chipCats.map(c => (
            <button key={c.id} onClick={() => d.setCategory(c.id)}
              className={`inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                d.category === c.id ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
              }`}>
              {c.name}
            </button>
          ))}
          {d.categories.length > chipCats.length && (
            <Select value={d.category} onValueChange={d.setCategory}>
              <SelectTrigger className="h-8 w-auto px-3 rounded-full text-xs border-slate-200">
                <span>More categories</span>
              </SelectTrigger>
              <SelectContent>
                {d.categories.filter(c => !featuredSet.has(c.id)).map(c => (
                  <SelectItem key={c.id} value={c.id}>{c.id} · {c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Inline filter bar — all in one row */}
        <div className="flex flex-wrap items-end gap-3 mb-6 pb-6 border-b border-slate-200">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input value={d.keyword} onChange={e => d.setKeyword(e.target.value)} placeholder="Search papers, authors, topics..."
              className="pl-9 h-10 rounded-sm border-slate-200 focus-visible:ring-1 focus-visible:ring-blue-600" />
          </div>
          <Select value={d.period} onValueChange={d.setPeriod}>
            <SelectTrigger className="h-10 w-[150px] rounded-sm border-slate-200 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {PERIODS.map(p => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={d.sortKey === "rank" ? "score" : d.sortKey} onValueChange={k => d.handleSort(k)}>
            <SelectTrigger className="h-10 w-[130px] rounded-sm border-slate-200 text-sm"><SelectValue placeholder="Sort by" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="score">Score</SelectItem>
              <SelectItem value="ai_rating">Rating</SelectItem>
              <SelectItem value="gap_score">Gap</SelectItem>
              <SelectItem value="published">Published</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Table */}
        <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
          {d.loading && d.leaderboard.length === 0 ? (
            <div className="space-y-2 p-4">
              {[...Array(8)].map((_, i) => <div key={i} className="h-12 bg-slate-50 rounded-sm animate-pulse" />)}
            </div>
          ) : d.leaderboard.length === 0 ? (
            <div className="py-16 text-center text-sm text-slate-400">No papers found for this period.</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="text-[10px] font-medium uppercase tracking-wider text-slate-500 bg-slate-50 border-b border-slate-100">
                  <th className="pl-5 pr-2 py-2.5 text-center w-10">#</th>
                  <th className="px-2 py-2.5 text-left">Paper</th>
                  <th className="px-2 py-2.5 text-right">Score</th>
                  <th className="px-2 py-2.5 text-right hidden md:table-cell">CI</th>
                  <th className="px-2 py-2.5 text-right hidden md:table-cell">Match</th>
                  <th className="px-2 py-2.5 text-right hidden lg:table-cell">Win %</th>
                  {d.showRatingCol && <th className="px-2 py-2.5 text-right hidden lg:table-cell">Rating</th>}
                  {d.showGapCol && <th className="px-2 py-2.5 text-right hidden lg:table-cell">Gap</th>}
                  <th className="pl-2 pr-5 py-2.5 text-right hidden sm:table-cell">Published</th>
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
                      </div>
                    </td>
                    <td className="px-2 py-3 text-right align-baseline"><span className="text-sm font-semibold tabular-nums">{p.ts_score || p.score || "—"}</span></td>
                    <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden md:table-cell">{p.ci > 0 ? `±${Math.round(p.ci)}` : "—"}</td>
                    <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden md:table-cell">{p.comparisons ?? "—"}</td>
                    <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden lg:table-cell">{p.win_rate != null ? `${p.win_rate}%` : "—"}</td>
                    {d.showRatingCol && <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden lg:table-cell">{p.ai_rating || "—"}</td>}
                    {d.showGapCol && <td className={`px-2 py-3 text-right align-baseline text-xs hidden lg:table-cell ${p.gap_score > 0 ? "text-emerald-600" : p.gap_score < 0 ? "text-red-400" : "text-slate-500"}`}>{p.gap_score != null ? (p.gap_score > 0 ? "+" : "") + p.gap_score : "—"}</td>}
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
      <SiteFooter />
    </div>
  );
}
