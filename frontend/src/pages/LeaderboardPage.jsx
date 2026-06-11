import { useMemo, useState, useRef, useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Search, X, PanelLeftClose, PanelLeft, Tag, Archive, ChevronDown, ChevronRight, Activity, LockOpen, ArrowRight, Lock, SlidersHorizontal, Layers, CalendarRange, Bookmark, Lightbulb } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { useLeaderboardData } from "@/hooks/useLeaderboardData";
import { useBasePath } from "@/contexts/BasePathContext";
import { useAuth } from "@/contexts/AuthContext";
import { RankedTable } from "@/components/leaderboard/RankedTable";
import { SuggestionModal } from "@/components/SuggestionModal";
import TopNav from "@/components/site/TopNav";
import SiteFooter from "@/components/site/SiteFooter";
import { Helmet } from "react-helmet";
import axios from "axios";

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

export default function LeaderboardPage({ archiveMode }) {
  const d = useLeaderboardData();
  const navigate = useNavigate();
  const basePath = useBasePath();
  const params = useParams();
  const isDesktop = typeof window !== 'undefined' && window.innerWidth >= 1024;
  const [sidebarOpen, setSidebarOpen] = useState(isDesktop);
  const [catSearch, setCatSearch] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [mobilePerksOpen, setMobilePerksOpen] = useState(false);
  const archiveRef = useRef(null);
  const activeCodes = useMemo(() => new Set(d.categories.map(c => c.id)), [d.categories]);
  const { user } = useAuth();
  const isLoggedIn = !!user;
  const requireAuth = () => window.dispatchEvent(new Event("open-auth-modal"));

  // Archive mode: load archive data and set category for the hook
  const [archiveData, setArchiveData] = useState(null);
  const [archiveLoading, setArchiveLoading] = useState(!!archiveMode);
  useEffect(() => {
    if (!archiveMode || !params.category) return;
    // Set the category on the hook so it fetches archives list for this category
    if (params.category !== d.category) d.setCategory(params.category);
    const isWeekly = params.weekOrMonth?.startsWith("w");
    const num = parseInt(params.weekOrMonth?.replace(/^[wm]/, ""), 10);
    const API = process.env.REACT_APP_BACKEND_URL;
    const url = isWeekly
      ? `${API}/api/archive/${params.category}/${params.year}/w${num}`
      : `${API}/api/archive/${params.category}/${params.year}/m${num}`;
    setArchiveLoading(true);
    axios.get(url).then(r => {
      if (r.data.status !== "not_found") setArchiveData(r.data);
    }).catch(() => {}).finally(() => setArchiveLoading(false));
  }, [archiveMode, params.category, params.year, params.weekOrMonth]); // eslint-disable-line react-hooks/exhaustive-deps

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
      <Helmet>
        <title>{d.categoryName} Paper Rankings | Kurate.org</title>
        <meta name="description" content={`AI-ranked ${d.categoryName} scientific preprints. ${d.totalPapers} papers compared by three LLMs.`} />
        <link rel="canonical" href={`https://kurate.org/${d.category ? `?cat=${d.category}` : ""}`} />
      </Helmet>
      <TopNav />
      <div className="flex min-h-[calc(100vh-65px)]">
        {/* Sidebar — inline on desktop, overlay drawer on mobile */}
        {sidebarOpen && (
          <div className="fixed inset-0 z-40 bg-black/30 lg:hidden" onClick={() => setSidebarOpen(false)} />
        )}
        {sidebarOpen && (
          <aside className="fixed inset-y-0 left-0 z-50 w-72 bg-white overflow-y-auto shadow-lg lg:sticky lg:top-[65px] lg:z-auto lg:shrink-0 lg:border-r lg:border-slate-200 lg:shadow-none lg:h-[calc(100vh-65px)] pt-14 sm:pt-16 lg:pt-0">
            {/* Mobile drawer header */}
            <div className="flex items-center justify-between p-4 border-b border-slate-100 lg:hidden">
              <span className="text-sm font-semibold text-slate-900">Filters</span>
              <button onClick={() => setSidebarOpen(false)} className="text-slate-400 hover:text-slate-600"><X className="h-5 w-5" /></button>
            </div>
            {!isLoggedIn ? (
              /* Locked sidebar — single CTA, all controls disabled */
              <>
                <div className="p-4 border-b border-slate-100">
                  <div className="rounded-sm border border-blue-200 bg-blue-50/50 p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <LockOpen className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                      <span className="text-xs font-semibold text-slate-900">Sign up for free</span>
                    </div>
                    <p className="text-[11px] text-slate-600 leading-relaxed mb-1">
                      Unlock search, filters, categories, archives, and{" "}
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button type="button" className="underline decoration-dotted underline-offset-2 decoration-slate-400 cursor-help text-slate-700">more</button>
                          </TooltipTrigger>
                          <TooltipContent side="bottom" align="start" className="max-w-xs p-3">
                            <p className="text-xs font-semibold mb-2">What you get with a free account</p>
                            <ul className="space-y-1.5">
                              {[
                                { icon: Layers, label: "Browse all categories", detail: "All arXiv & ChemRxiv fields" },
                                { icon: CalendarRange, label: "All time periods", detail: "Newly Added, Last 30 Days, All Time" },
                                { icon: Tag, label: "Cross-category tag filters", detail: "Filter by tag combinations" },
                                { icon: Archive, label: "Weekly & monthly archives", detail: "Browse frozen historical snapshots" },
                                { icon: Bookmark, label: "Bookmark papers", detail: "Build personalized reading lists" },
                                { icon: Lightbulb, label: "Suggest new fields", detail: "Propose categories to add" },
                              ].map(({ icon: Icon, label, detail }) => (
                                <li key={label} className="flex items-start gap-2">
                                  <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 text-blue-600" />
                                  <div><div className="text-xs font-medium leading-tight">{label}</div><div className="text-[11px] opacity-80 leading-tight">{detail}</div></div>
                                </li>
                              ))}
                            </ul>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </p>
                    <button onClick={requireAuth} className="w-full inline-flex items-center justify-center gap-1.5 rounded-sm bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition-colors mt-2">
                      Sign up <ArrowRight className="h-3 w-3" />
                    </button>
                  </div>
                </div>
                <div className="p-4 opacity-40 pointer-events-none select-none">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Search</span>
                    <button onClick={() => setSidebarOpen(false)} className="text-slate-400"><PanelLeftClose className="h-4 w-4" /></button>
                  </div>
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                    <Input disabled placeholder="Papers, authors..." className="pl-8 h-9 text-sm rounded-sm border-slate-200" />
                  </div>
                  <div className="mt-6 space-y-4">
                    <div><div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Time Period</div>
                      {PERIODS.map(p => <div key={p.value} className="px-2.5 py-1.5 text-sm text-slate-400">{p.label}</div>)}
                    </div>
                    <div><div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Field</div>
                      <div className="px-2.5 py-1.5 text-sm text-slate-400">All Categories</div>
                    </div>
                    <div><div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Cross-Field</div></div>
                  </div>
                </div>
                {/* Suggest teaser (greyed out, locked) */}
                <div className="px-4 py-3 border-t border-slate-100 opacity-40 pointer-events-none">
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <Lightbulb className="h-3.5 w-3.5 text-blue-500" />
                    <span>Suggest a field</span>
                    <Lock className="h-3 w-3 ml-auto text-slate-400" />
                  </div>
                </div>
              </>
            ) : (
              /* Unlocked sidebar — full controls */
              <>
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
                  <button key={p.value}
                    onClick={() => { d.setPeriod(p.value); d.clearArchive(); }}
                    className={`w-full text-left px-2.5 py-1.5 rounded-sm text-sm transition-colors ${
                      d.period === p.value && !d.activeArchive ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50"
                    }`}>
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
                {/* Suggest a field */}
                <div className="p-4 border-t border-slate-100">
                  <button onClick={() => setSuggestOpen(true)} className="w-full inline-flex items-center justify-center gap-2 rounded-sm border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50/50 transition-colors">
                    <Lightbulb className="h-3.5 w-3.5" /> Suggest a field
                  </button>
                </div>
              </>
            )}
          </aside>
        )}

        {/* Collapsed sidebar toggle — desktop only */}
        {!sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="hidden lg:flex w-5 shrink-0 border-r border-slate-200 hover:bg-slate-100 transition-colors items-center justify-center"
            title="Open filters"
          >
            <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
          </button>
        )}

        {/* Main content */}
        <main className="flex-1 min-w-0">
          <div className="px-5 sm:px-6 lg:px-8 pt-6 pb-12">
            {(() => {
              const isArchive = archiveMode && archiveData;
              const archiveLabel = archiveData?.label || "";
              const archiveCat = params.category || "";
              const archiveCatName = d.categories.find(c => c.id === archiveCat)?.name || archiveCat;
              const displayTitle = isArchive ? `${archiveCatName} — ${archiveLabel}` : (d.activeArchive ? `${d.categoryName} — ${d.activeArchive.label}` : `${d.categoryName} Paper Rankings`);
              const displayLeaderboard = isArchive ? (archiveData.leaderboard || []) : d.leaderboard;
              const displayLoading = archiveMode ? archiveLoading : d.loading;
              const displayPapers = isArchive ? displayLeaderboard.length : d.totalPapers;

              return (
                <>
                  {/* Mobile CTA — slim bar for logged-out users (sidebar hidden on mobile) */}
                  {!isLoggedIn && (
                    <div className="lg:hidden mb-4">
                      <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-sm bg-blue-50 border border-blue-100">
                        <span className="text-[11px] text-slate-600">
                          <LockOpen className="h-3 w-3 text-blue-600 inline mr-1 -mt-px" />Unlock filters, categories &{" "}
                          <button type="button"
                            onPointerDown={(e) => { if (e.pointerType === "touch") setMobilePerksOpen(v => !v); }}
                            onMouseEnter={() => setMobilePerksOpen(true)}
                            onMouseLeave={() => setMobilePerksOpen(false)}
                            className="underline decoration-dotted underline-offset-2 decoration-slate-400 text-slate-700 font-medium cursor-help">
                            more
                          </button>
                        </span>
                        <button onClick={requireAuth} className="shrink-0 inline-flex items-center gap-1 rounded-sm bg-blue-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-blue-700 transition-colors">
                          Sign up <ArrowRight className="h-2.5 w-2.5" />
                        </button>
                      </div>
                      {mobilePerksOpen && (
                        <div className="mt-1.5 px-3 py-2.5 rounded-sm bg-white border border-slate-200 shadow-sm"
                          onMouseLeave={() => setMobilePerksOpen(false)}>
                          <p className="text-xs font-semibold mb-2 text-slate-800">What you get with a free account</p>
                          <ul className="space-y-1.5">
                            {[
                              { icon: Layers, label: "Browse all categories", detail: "All arXiv & ChemRxiv fields" },
                              { icon: CalendarRange, label: "All time periods", detail: "Newly Added, Last 30 Days, All Time" },
                              { icon: Tag, label: "Cross-category tag filters", detail: "Filter by tag combinations" },
                              { icon: Archive, label: "Weekly & monthly archives", detail: "Browse frozen historical snapshots" },
                              { icon: Bookmark, label: "Bookmark papers", detail: "Build personalized reading lists" },
                              { icon: Lightbulb, label: "Suggest new fields", detail: "Propose categories to add" },
                            ].map(({ icon: Icon, label, detail }) => (
                              <li key={label} className="flex items-start gap-2">
                                <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 text-blue-600" />
                                <div><div className="text-xs font-medium leading-tight">{label}</div><div className="text-[11px] text-slate-500 leading-tight">{detail}</div></div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex items-start justify-between mb-6">
                    <div>
                      {/* Mobile filters button */}
                      {!archiveMode && (
                        <button onClick={() => setSidebarOpen(true)}
                          className="lg:hidden inline-flex items-center gap-1.5 mb-3 px-3 py-1.5 rounded-sm border border-slate-200 text-xs font-medium text-slate-600 hover:border-slate-400 transition-colors">
                          <SlidersHorizontal className="h-3.5 w-3.5" /> Filters
                        </button>
                      )}
                      {isArchive && (
                        <a onClick={(e) => { e.preventDefault(); navigate(`${basePath}/?cat=${archiveCat}&period=all`); }} href="#"
                          className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 mb-3 transition-colors cursor-pointer">
                          ← Back to live leaderboard
                        </a>
                      )}
                      <h1 className="font-serif text-2xl sm:text-3xl font-medium tracking-tight text-slate-900">{displayTitle}</h1>
                      <div className="flex items-center gap-3 text-sm text-slate-500 mt-0.5">
                        <span>
                          {isArchive
                            ? `${displayLeaderboard.length} papers`
                            : d.debouncedKeyword
                              ? `${d.totalInPeriod} papers found`
                              : d.period !== "all" && d.totalInPeriod !== d.totalPapers
                                ? `${d.totalInPeriod} of ${d.totalPapers} papers`
                                : `${displayPapers} papers`
                          }
                        </span>
                        {!isArchive && d.isRanking && <><span className="text-slate-300">·</span><span className="inline-flex items-center gap-1 text-blue-600 animate-pulse"><Activity className="h-3 w-3" /> Ranking</span></>}
                      </div>
                    </div>
                    {((archiveMode && archiveData) || (!archiveMode && d.archives.length > 0 && d.category)) && (
                      <div className="relative shrink-0 mt-1" ref={archiveRef}>
                        <button onClick={() => setArchiveOpen(v => !v)}
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm border text-xs font-medium transition-all ${
                            isArchive ? "bg-blue-50 text-blue-700 border-blue-200" : "border-slate-200 text-slate-500 hover:border-slate-400"
                          }`}>
                          <Archive className="h-3 w-3" />
                          {isArchive ? archiveLabel : (d.activeArchive ? d.activeArchive.label : "Live")}
                          <ChevronDown className={`h-3 w-3 transition-transform ${archiveOpen ? "rotate-180" : ""}`} />
                        </button>
                        {archiveOpen && (
                          <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-sm shadow-lg min-w-[220px] max-h-[320px] overflow-y-auto py-1">
                            <button onClick={() => { navigate(`${basePath}/?cat=${isArchive ? archiveCat : d.category}&period=all`); setArchiveOpen(false); }}
                              className={`w-full text-left px-3 py-1.5 text-sm transition-colors ${!isArchive && !d.activeArchive ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-50 text-slate-600"}`}>
                              Live rankings
                            </button>
                            <div className="px-3 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">Archive</div>
                            {d.archives.map(a => {
                              const slug = a.period_type === "weekly" ? `w${a.week}` : `m${a.month}`;
                              const isCurrent = isArchive && params.weekOrMonth === slug && params.year === String(a.year);
                              return (
                                <button key={`${a.category}-${a.year}-${slug}`}
                                  onClick={() => { navigate(`${basePath}/leaderboard/${a.category}/${a.year}/${slug}`); setArchiveOpen(false); }}
                                  className={`w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center justify-between ${isCurrent ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-50"}`}>
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
                  {!isArchive && d.hasSelectedTags && (
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
                    <RankedTable
                      leaderboard={displayLeaderboard} loading={displayLoading}
                      sortKey={d.sortKey} sortDir={d.sortDir} onSort={d.handleSort}
                      showRatingCol={isArchive ? displayLeaderboard.some(e => e.ai_rating) : d.showRatingCol}
                      showGapCol={isArchive ? displayLeaderboard.some(e => e.gap_score != null) : d.showGapCol}
                      hasSelectedTags={d.hasSelectedTags} globalStats={d.globalStats}
                      isArchive={!!isArchive || !!d.activeArchive} nextCursor={isArchive ? null : d.nextCursor}
                      loadMore={isArchive ? null : d.loadMore} loadingMore={d.loadingMore} keyword={d.keyword}
                      onCategoryClick={isLoggedIn ? (cat) => { d.setCategory(cat); d.setSelectedTags([]); d.setTagFilterOpen(false); d.clearArchive(); } : () => requireAuth()}
                      activeCodes={activeCodes}
                    />
                  </div>
                </>
              );
            })()}
          </div>
        </main>
      </div>
      <SuggestionModal open={suggestOpen} onClose={() => setSuggestOpen(false)} />
    </div>
  );
}
