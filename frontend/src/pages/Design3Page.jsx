import { useMemo, useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Search, X, PanelLeftClose, PanelLeft, Tag, Archive, ChevronDown, ChevronRight, Activity } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useLeaderboardData } from "@/hooks/useLeaderboardData";
import { LeaderboardTableNew } from "@/components/leaderboard/LeaderboardTableNew";
import TopNav from "@/components/site/TopNav";
import SiteFooter from "@/components/site/SiteFooter";

function SidebarSection({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-slate-100">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between p-4 pb-2 hover:bg-slate-50/50 transition-colors">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{title}</span>
        <ChevronDown className={`h-3 w-3 text-slate-400 transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

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
  { value: "win_rate", label: "Win %" },
  { value: "comparisons", label: "Matches" },
  { value: "wilson_margin", label: "95% CI" },
  { value: "published", label: "Published" },
];

export default function Design3Page() {
  const d = useLeaderboardData();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [catSearch, setCatSearch] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const archiveRef = useRef(null);
  const activeCodes = useMemo(() => new Set(d.categories.map(c => c.id)), [d.categories]);

  useEffect(() => {
    const handler = (e) => { if (archiveRef.current && !archiveRef.current.contains(e.target)) setArchiveOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Group categories by domain
  const filteredCats = catSearch
    ? d.categories.filter(c => c.id.toLowerCase().includes(catSearch.toLowerCase()) || c.name.toLowerCase().includes(catSearch.toLowerCase()))
    : d.categories;
  const grouped = {};
  for (const c of filteredCats) {
    const g = c.group || "Other";
    if (!grouped[g]) grouped[g] = [];
    grouped[g].push(c);
  }

  // Filter tags
  const filteredTags = useMemo(() => {
    const tags = d.allTags.slice(0, 50);
    if (!tagSearch) return tags;
    const lc = tagSearch.toLowerCase();
    return tags.filter(t => t.id.toLowerCase().includes(lc));
  }, [d.allTags, tagSearch]);

  const toggleTag = (tagId) => {
    if (d.selectedTags.includes(tagId)) {
      d.setSelectedTags(d.selectedTags.filter(t => t !== tagId));
    } else {
      d.setSelectedTags([...d.selectedTags, tagId]);
    }
    if (!d.tagFilterOpen) d.setTagFilterOpen(true);
  };

  const selectCategory = (id) => {
    d.setCategory(id);
    d.setSelectedTags([]);
    d.setTagFilterOpen(false);
    d.clearArchive();
  };

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="flex min-h-[calc(100vh-65px)]">
        {/* Sidebar */}
        {sidebarOpen && (
          <aside className="w-72 shrink-0 border-r border-slate-200 bg-white overflow-y-auto">
            {/* Search */}
            <div className="p-4 border-b border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Search</span>
                <button onClick={() => setSidebarOpen(false)} className="text-slate-400 hover:text-slate-600"><PanelLeftClose className="h-4 w-4" /></button>
              </div>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <Input value={d.keyword} onChange={e => d.setKeyword(e.target.value)} placeholder="Papers, authors..."
                  className="pl-8 h-9 text-sm rounded-sm border-slate-200" />
                {d.keyword && <button onClick={() => d.setKeyword("")} className="absolute right-2.5 top-1/2 -translate-y-1/2"><X className="h-3 w-3 text-slate-400" /></button>}
              </div>
            </div>

            {/* Time Period */}
            <SidebarSection title="Time Period" defaultOpen={true}>
              <div className="space-y-0.5">
                {PERIODS.map(p => (
                  <button key={p.value} onClick={() => { d.setPeriod(p.value); d.clearArchive(); }}
                    className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors ${d.period === p.value && !d.activeArchive ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
                    {p.label}
                  </button>
                ))}
              </div>
            </SidebarSection>

            {/* Categories */}
            <SidebarSection title="Field" defaultOpen={false}>
              <div className="relative mb-2">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-slate-400" />
                <input value={catSearch} onChange={e => setCatSearch(e.target.value)} placeholder="Filter..."
                  className="w-full pl-6 pr-2 py-1 text-xs border border-slate-200 rounded-sm focus:outline-none focus:ring-1 focus:ring-blue-600" />
              </div>
              <div className="space-y-0.5 max-h-[400px] overflow-y-auto">
                <button onClick={() => selectCategory("")}
                  className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors ${!d.category && !d.isTagMode ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
                  All Categories
                </button>
                {Object.entries(grouped).sort(([a],[b]) => a.localeCompare(b)).map(([group, cats]) => (
                  <div key={group}>
                    <div className="px-2.5 pt-3 pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-400">{group}</div>
                    {cats.map(c => (
                      <button key={c.id} onClick={() => selectCategory(c.id)}
                        className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors flex items-center gap-2 ${
                          d.category === c.id && !d.isTagMode ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"
                        }`}>
                        <span className="font-mono text-[10px] text-blue-600 shrink-0">{c.id}</span>
                        <span className="truncate">{c.name}</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </SidebarSection>

            {/* Filter (tag cloud) */}
            <SidebarSection title="Cross-Field" defaultOpen={false}>
              <div className="flex items-center justify-between mb-2">
                {d.hasSelectedTags && (
                  <div className="flex items-center gap-1 text-[10px]">
                    <button onClick={() => d.setTagMode("or")}
                      className={`px-1.5 py-0.5 rounded-sm border ${d.tagMode === "or" ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-400"}`}>
                      OR
                    </button>
                    <button onClick={() => d.setTagMode("and")}
                      className={`px-1.5 py-0.5 rounded-sm border ${d.tagMode === "and" ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-400"}`}>
                      AND
                    </button>
                  </div>
                )}
                {d.hasSelectedTags && (
                  <button onClick={() => { d.setSelectedTags([]); d.setTagFilterOpen(false); }} className="text-[10px] text-slate-400 hover:text-slate-600">Clear</button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {filteredTags.map(tag => (
                  <button key={tag.id} onClick={() => toggleTag(tag.id)}
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border transition-all ${
                      d.selectedTags.includes(tag.id) ? "bg-blue-50 text-blue-700 border-blue-200 font-medium" : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
                    }`}>
                    {tag.id}
                  </button>
                ))}
              </div>
            </SidebarSection>

            {/* Sort By */}
            <SidebarSection title="Sort By" defaultOpen={false}>
              <div className="space-y-0.5">
                {SORTS.map(s => (
                  <button key={s.value} onClick={() => d.handleSort(s.value)}
                    className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors flex items-center justify-between ${
                      (d.sortKey === s.value || (d.sortKey === "rank" && s.value === "score")) ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"
                    }`}>
                    <span>{s.label}</span>
                    {d.sortKey === s.value && <span className="text-[10px] text-blue-500">{d.sortDir === "asc" ? "\u2191" : "\u2193"}</span>}
                  </button>
                ))}
              </div>
            </SidebarSection>
          </aside>
        )}

        {/* Collapsed sidebar toggle */}
        {!sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="w-5 shrink-0 border-r border-slate-200 hover:bg-slate-100 transition-colors flex items-center justify-center"
            title="Open filters"
          >
            <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
          </button>
        )}

        {/* Main content */}
        <main className="flex-1 min-w-0">
          <div className="px-6 lg:px-8 pt-6 pb-12">
            <div className="flex items-start justify-between mb-6">
              <div>
                <h1 className="font-serif text-2xl sm:text-3xl font-medium tracking-tight text-slate-900">
                  {d.activeArchive ? `${d.categoryName} — ${d.activeArchive.label}` : `${d.categoryName} Paper Rankings`}
                </h1>
                <div className="flex items-center gap-3 text-sm text-slate-500 mt-0.5">
                    <span>{d.totalPapers} papers</span>
                    {d.isRanking && <><span className="text-slate-300">·</span><span className="inline-flex items-center gap-1 text-blue-600 animate-pulse"><Activity className="h-3 w-3" /> Ranking</span></>}
                </div>
              </div>
              {d.archives.length > 0 && d.category && (
                <div className="relative shrink-0 mt-1" ref={archiveRef}>
                  <button onClick={() => setArchiveOpen(v => !v)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm border text-xs font-medium transition-all ${
                      d.activeArchive ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-500 hover:border-slate-400"
                    }`}>
                    <Archive className="h-3 w-3" />
                    {d.activeArchive ? d.activeArchive.label : "Live"}
                    <ChevronDown className={`h-3 w-3 transition-transform ${archiveOpen ? "rotate-180" : ""}`} />
                  </button>
                  {archiveOpen && (
                    <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-sm shadow-lg min-w-[220px] max-h-[320px] overflow-y-auto py-1">
                      <button onClick={() => { d.clearArchive(); setArchiveOpen(false); }}
                        className={`w-full text-left px-3 py-1.5 text-sm transition-colors ${!d.activeArchive ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-50 text-slate-600"}`}>
                        Live rankings
                      </button>
                      <div className="px-3 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">Archive</div>
                      {d.archives.map(a => {
                        const slug = a.period_type === "weekly" ? `w${a.week}` : `m${a.month}`;
                        return (
                          <button key={`${a.category}-${a.year}-${slug}`}
                            onClick={() => { d.loadArchive(a); setArchiveOpen(false); }}
                            className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 transition-colors flex items-center justify-between">
                            <span>{a.label}</span>
                            <span className="text-[10px] text-slate-400 ml-3">{a.paper_count}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Selected tags display */}
            {d.hasSelectedTags && (
              <div className="mb-4 flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-500">Filtering by:</span>
                {d.selectedTags.map(t => (
                  <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs bg-blue-50 text-blue-700 border border-blue-200">
                    {t}
                    <button onClick={() => toggleTag(t)} className="hover:text-blue-900"><X className="h-3 w-3" /></button>
                  </span>
                ))}
                <span className="text-[10px] text-slate-400">{d.tagMode === "and" ? "AND" : "OR"}</span>
              </div>
            )}

            {/* Table */}
            <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
              <LeaderboardTableNew
                leaderboard={d.leaderboard} loading={d.loading}
                sortKey={d.sortKey} sortDir={d.sortDir} onSort={d.handleSort}
                showRatingCol={d.showRatingCol} showGapCol={d.showGapCol}
                hasSelectedTags={d.hasSelectedTags} globalStats={d.globalStats}
                isArchive={!!d.activeArchive} nextCursor={d.nextCursor}
                loadMore={d.loadMore} loadingMore={d.loadingMore} keyword={d.keyword}
                onCategoryClick={(cat) => { d.setCategory(cat); d.setSelectedTags([]); d.setTagFilterOpen(false); d.clearArchive(); }}
                activeCodes={activeCodes}
              />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
