import { useMemo, useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Search, X, Tag, ChevronDown, Archive, Lock, Sparkles, Activity } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLeaderboardData } from "@/hooks/useLeaderboardData";
import { LeaderboardTableNew } from "@/components/leaderboard/LeaderboardTableNew";
import TopNav from "@/components/site/TopNav";
import SiteFooter from "@/components/site/SiteFooter";

const PERIODS = [
  { value: "recent", label: "Newly Added" },
  { value: "week", label: "Last 7 Days" },
  { value: "month", label: "Last 30 Days" },
  { value: "all", label: "All Time" },
];

export default function Design2Page() {
  const d = useLeaderboardData();
  const [archiveOpen, setArchiveOpen] = useState(false);
  const archiveRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (archiveRef.current && !archiveRef.current.contains(e.target)) setArchiveOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const featuredSet = new Set(d.featured);
  const chipCats = d.categories.filter(c => featuredSet.has(c.id));
  const overflowCats = d.categories.filter(c => !featuredSet.has(c.id));

  // Tag chips from allTags
  const topTags = useMemo(() => d.allTags.slice(0, 30), [d.allTags]);

  const toggleTag = (tagId) => {
    if (d.selectedTags.includes(tagId)) {
      d.setSelectedTags(d.selectedTags.filter(t => t !== tagId));
    } else {
      d.setSelectedTags([...d.selectedTags, tagId]);
    }
    if (!d.tagFilterOpen) d.setTagFilterOpen(true);
  };

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-8 pb-12">
        {/* Title */}
        <div className="mb-6">
          <h1 className="font-serif text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 mb-1">
            {d.activeArchive ? `${d.categoryName} — ${d.activeArchive.label}` : `${d.categoryName} Paper Rankings`}
          </h1>
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span>{d.totalPapers} papers</span>
            <span className="text-slate-300">·</span>
            <span>{d.totalMatches} comparisons</span>
            {d.isRanking && (
              <span className="inline-flex items-center gap-1 text-blue-600 animate-pulse"><Activity className="h-3 w-3" /> Ranking</span>
            )}
            <span className="text-slate-300">·</span>
            <Link to="/methodology" className="text-blue-600 hover:underline">Methodology</Link>
          </div>
        </div>

        {/* Category chips */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <button onClick={() => { d.setCategory(""); d.setSelectedTags([]); d.setTagFilterOpen(false); d.clearArchive(); }}
            className={`inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
              !d.category && !d.isTagMode ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
            }`}>
            All Categories
          </button>
          {chipCats.map(c => (
            <button key={c.id} onClick={() => { d.setCategory(c.id); d.setSelectedTags([]); d.setTagFilterOpen(false); d.clearArchive(); }}
              className={`inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                d.category === c.id && !d.isTagMode ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
              }`}>
              {c.name}
            </button>
          ))}
          {overflowCats.length > 0 && (
            <Select value={d.category} onValueChange={v => { d.setCategory(v); d.setSelectedTags([]); d.setTagFilterOpen(false); d.clearArchive(); }}>
              <SelectTrigger className="h-8 w-auto px-3 rounded-full text-xs border-slate-200">
                <span>{overflowCats.find(c => c.id === d.category)?.name || "More"}</span>
              </SelectTrigger>
              <SelectContent>
                {overflowCats.map(c => <SelectItem key={c.id} value={c.id}>{c.id} · {c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <div className="w-px h-5 bg-slate-200 mx-1" />
          <button onClick={() => { d.setTagFilterOpen(!d.tagFilterOpen); if (d.tagFilterOpen && !d.hasSelectedTags) d.setTagFilterOpen(false); }}
            className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
              d.isTagMode ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
            }`}>
            <Tag className="h-3 w-3" /> Tags {d.hasSelectedTags ? `(${d.selectedTags.length})` : ""}
          </button>
        </div>

        {/* Tag filter panel */}
        {d.tagFilterOpen && (
          <div className="mb-4 border border-slate-200 rounded-sm p-4 bg-white">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-700">Filter by tags</span>
                <div className="flex items-center gap-1 text-[10px]">
                  <button onClick={() => d.setTagMode("or")}
                    className={`px-2 py-0.5 rounded-sm border ${d.tagMode === "or" ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-500"}`}>
                    OR
                  </button>
                  <button onClick={() => d.setTagMode("and")}
                    className={`px-2 py-0.5 rounded-sm border ${d.tagMode === "and" ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-500"}`}>
                    AND
                  </button>
                </div>
              </div>
              {d.hasSelectedTags && (
                <button onClick={() => { d.setSelectedTags([]); d.setTagFilterOpen(false); }} className="text-xs text-slate-400 hover:text-slate-600">
                  Clear all
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {topTags.map(tag => (
                <button key={tag.id} onClick={() => toggleTag(tag.id)}
                  className={`inline-flex items-center px-2 py-1 rounded-sm text-xs border transition-all ${
                    d.selectedTags.includes(tag.id) ? "bg-blue-50 text-blue-700 border-blue-200 font-medium" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
                  }`}>
                  {tag.id} <span className="ml-1 text-slate-400">{tag.count}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Filter bar */}
        <div className="flex flex-wrap items-end gap-3 mb-6 pb-5 border-b border-slate-200">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input value={d.keyword} onChange={e => d.setKeyword(e.target.value)} placeholder="Search papers, authors, topics..."
              className="pl-9 h-10 rounded-sm border-slate-200 focus-visible:ring-1 focus-visible:ring-blue-600" />
            {d.keyword && (
              <button onClick={() => d.setKeyword("")} className="absolute right-3 top-1/2 -translate-y-1/2">
                <X className="h-3.5 w-3.5 text-slate-400 hover:text-slate-600" />
              </button>
            )}
          </div>
          <Select value={d.activeArchive ? "__archive" : d.period} onValueChange={v => { if (v !== "__archive") { d.setPeriod(v); d.clearArchive(); } }}>
            <SelectTrigger className="h-10 w-[150px] rounded-sm border-slate-200 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {PERIODS.map(p => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
            </SelectContent>
          </Select>
          {d.archives.length > 0 && (
            <div className="relative" ref={archiveRef}>
              <button onClick={() => setArchiveOpen(v => !v)}
                className={`inline-flex items-center gap-1.5 h-10 px-3 rounded-sm border text-sm transition-all ${
                  d.activeArchive ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-600 hover:border-slate-400"
                }`}>
                <Archive className="h-3.5 w-3.5" />
                {d.activeArchive?.label || "Archive"}
                <ChevronDown className={`h-3 w-3 transition-transform ${archiveOpen ? "rotate-180" : ""}`} />
              </button>
              {archiveOpen && (
                <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-sm shadow-lg min-w-[220px] max-h-[320px] overflow-y-auto py-1">
                  <button onClick={() => { d.clearArchive(); setArchiveOpen(false); }}
                    className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 transition-colors text-slate-500">
                    Live rankings
                  </button>
                  {d.archives.map(a => {
                    const slug = a.period_type === "weekly" ? `w${a.week}` : `m${a.month}`;
                    return (
                      <button key={`${a.category}-${a.year}-${slug}`}
                        onClick={() => { d.loadArchive(a); setArchiveOpen(false); }}
                        className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 transition-colors flex items-center justify-between">
                        <span>{a.label}</span>
                        <span className="text-[10px] text-slate-400 ml-3">{a.paper_count} papers</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Table */}
        <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
          <LeaderboardTableNew
            leaderboard={d.leaderboard} loading={d.loading}
            sortKey={d.sortKey} sortDir={d.sortDir} onSort={d.handleSort}
            showRatingCol={d.showRatingCol} showGapCol={d.showGapCol}
            hasSelectedTags={d.hasSelectedTags} globalStats={d.globalStats}
            isArchive={!!d.activeArchive} nextCursor={d.nextCursor}
            loadMore={d.loadMore} loadingMore={d.loadingMore} keyword={d.keyword}
          />
        </div>

        <div className="mt-4 text-center text-xs text-slate-400">
          {d.hasSelectedTags
            ? `Cross-category rankings for ${d.selectedTags.join(d.tagMode === "and" ? " AND " : " OR ")} papers.`
            : "Win-rate scores from pairwise comparisons. Papers compared using full-text analysis."}
        </div>
      </div>
      <SiteFooter />
    </div>
  );
}
