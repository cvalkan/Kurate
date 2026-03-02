import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import axios from "axios";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuth } from "@/contexts/AuthContext";
import { SuggestionModal } from "@/components/SuggestionModal";
import { CategoryTabs } from "@/components/leaderboard/CategoryTabs";
import { TagFilter } from "@/components/leaderboard/TagFilter";
import { StatusBar } from "@/components/leaderboard/StatusBar";
import { StatsToggle } from "@/components/leaderboard/StatsToggle";
import { PeriodFilter } from "@/components/leaderboard/PeriodFilter";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";

const API = process.env.REACT_APP_BACKEND_URL;

export default function LeaderboardPage() {
  const [searchParams] = useSearchParams();

  // State — initialized from URL params for back-navigation restore
  const [leaderboard, setLeaderboard] = useState([]);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState(searchParams.get("cat") || "");
  const [period, setPeriod] = useState(searchParams.get("period") || "all");
  const [loading, setLoading] = useState(true);
  const [warmingUp, setWarmingUp] = useState(false);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);
  const [isRanking, setIsRanking] = useState(false);

  const [allTags, setAllTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState(() => {
    const t = searchParams.get("tags");
    return t ? t.split(",").filter(Boolean) : [];
  });
  const [tagMode, setTagMode] = useState(searchParams.get("tagMode") || "or");
  const [tagFilterOpen, setTagFilterOpen] = useState(searchParams.get("tagOpen") === "1");

  const [keyword, setKeyword] = useState(searchParams.get("q") || "");
  const [debouncedKeyword, setDebouncedKeyword] = useState(searchParams.get("q") || "");
  const [globalStats, setGlobalStats] = useState(searchParams.get("global") === "1");
  const [displayCount, setDisplayCount] = useState(50);
  const [sortKey, setSortKey] = useState(searchParams.get("sort") || "rank");
  const [sortDir, setSortDir] = useState(searchParams.get("dir") || "asc");

  const { user } = useAuth();
  const [showSuggestion, setShowSuggestion] = useState(false);
  const isLoggedIn = !!user;

  const requireAuth = () => window.dispatchEvent(new Event("open-auth-modal"));
  const abortRef = useRef(null);

  const categoryName = categories.find(c => c.id === category)?.name || "Papers";
  const hasSelectedTags = selectedTags.length > 0;
  const isTagMode = tagFilterOpen || hasSelectedTags;

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "title" || key === "published" ? "asc" : "desc");
    }
  };

  // Sync state → URL (replaceState)
  const syncRef = useRef(false);
  useEffect(() => {
    if (!syncRef.current) { syncRef.current = true; return; }
    const p = new URLSearchParams();
    if (category && !isTagMode) p.set("cat", category);
    if (period !== "week") p.set("period", period);
    if (selectedTags.length) p.set("tags", selectedTags.join(","));
    if (tagMode !== "or") p.set("tagMode", tagMode);
    if (tagFilterOpen && !selectedTags.length) p.set("tagOpen", "1");
    if (debouncedKeyword) p.set("q", debouncedKeyword);
    if (globalStats) p.set("global", "1");
    if (sortKey && sortKey !== "rank") p.set("sort", sortKey);
    if (sortKey && sortKey !== "rank" && sortDir !== "asc") p.set("dir", sortDir);
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [category, period, selectedTags, tagMode, tagFilterOpen, debouncedKeyword, globalStats, isTagMode, sortKey, sortDir]);

  // Notify navbar
  useEffect(() => {
    if (hasSelectedTags) window.dispatchEvent(new CustomEvent("category-change", { detail: { tags: selectedTags } }));
    else if (isTagMode) window.dispatchEvent(new CustomEvent("category-change", { detail: { name: "All Papers" } }));
    else if (categoryName !== "Papers") window.dispatchEvent(new CustomEvent("category-change", { detail: { name: categoryName } }));
  }, [categoryName, isTagMode, hasSelectedTags, selectedTags]);

  // Load categories and tags
  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
      if (!category) setCategory(res.data.default || "cs.RO");
    }).catch(() => { if (!category) setCategory("cs.RO"); });
    axios.get(`${API}/api/tags`).then(res => setAllTags(res.data.tags || [])).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounce keyword
  useEffect(() => {
    const t = setTimeout(() => setDebouncedKeyword(keyword), 300);
    return () => clearTimeout(t);
  }, [keyword]);

  const fetchLeaderboard = useCallback(async () => {
    if (!category && !isTagMode) return;
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const params = { period };
      if (debouncedKeyword) params.search = debouncedKeyword;
      if (hasSelectedTags) {
        params.tags = selectedTags.join(",");
        params.tag_mode = tagMode;
        params.global_stats = globalStats;
      } else if (isTagMode) {
        params.show_all = true;
      } else {
        params.category = category;
      }
      const res = await axios.get(`${API}/api/leaderboard`, { params, signal: controller.signal });
      if (!controller.signal.aborted) {
        // Check for warming_up status
        if (res.data.warming_up) {
          setWarmingUp(true);
          setLeaderboard([]);
          setLoading(false);
          // Retry after 2 seconds
          setTimeout(() => fetchLeaderboard(), 2000);
          return;
        }
        setWarmingUp(false);
        setLeaderboard(res.data.leaderboard || []);
        setTotalPapers(res.data.total_papers || 0);
        setTotalMatches(res.data.total_matches || 0);
        setIsRanking(res.data.is_ranking || false);
        setLoading(false);
      }
    } catch (err) {
      if (err.name !== "CanceledError" && err.code !== "ERR_CANCELED") {
        console.error("Failed to fetch leaderboard:", err);
        setLoading(false);
      }
    }
  }, [category, period, selectedTags, tagMode, isTagMode, hasSelectedTags, globalStats, debouncedKeyword]);

  // Fetch on param change (debounce tag mode)
  const initialLoadDone = useRef(false);
  const debounceRef = useRef(null);
  useEffect(() => {
    if (!initialLoadDone.current) setLoading(true);
    setDisplayCount(50);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (isTagMode && initialLoadDone.current) {
      debounceRef.current = setTimeout(() => fetchLeaderboard().then(() => { initialLoadDone.current = true; }), 250);
    } else {
      fetchLeaderboard().then(() => { initialLoadDone.current = true; });
    }
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); if (abortRef.current) abortRef.current.abort(); };
  }, [fetchLeaderboard]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-refresh (category view only)
  useEffect(() => {
    if (isTagMode) return;
    const interval = setInterval(fetchLeaderboard, 30000);
    return () => clearInterval(interval);
  }, [fetchLeaderboard, isTagMode]);

  const title = hasSelectedTags
    ? `${selectedTags.join(tagMode === "and" ? " \u2229 " : " \u222A ")} Papers`
    : isTagMode ? "All Papers" : `${categoryName} Paper Rankings`;

  return (
    <TooltipProvider delayDuration={200}>
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">{title}</h1>
        <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
          {hasSelectedTags
            ? `Cross-category view: showing papers tagged with ${selectedTags.join(tagMode === "and" ? " AND " : " OR ")}.`
            : isTagMode
            ? "Showing all papers across all categories. Select tags below to filter."
            : <>AI-estimated scientific impact ranking of the latest arXiv {categoryName} preprints. <Link to="/methodology" className="text-accent hover:underline">Methodology</Link></>}
        </p>
      </div>

      <CategoryTabs
        categories={categories} category={category} setCategory={setCategory}
        isTagMode={isTagMode} isLoggedIn={isLoggedIn} requireAuth={requireAuth}
        setSelectedTags={setSelectedTags} setTagFilterOpen={setTagFilterOpen}
        onSuggest={() => isLoggedIn ? setShowSuggestion(true) : requireAuth()}
      />

      <TagFilter
        allTags={allTags} selectedTags={selectedTags} setSelectedTags={setSelectedTags}
        tagMode={tagMode} setTagMode={setTagMode} tagFilterOpen={tagFilterOpen}
        setTagFilterOpen={setTagFilterOpen} isLoggedIn={isLoggedIn} requireAuth={requireAuth}
        globalStats={globalStats} setGlobalStats={setGlobalStats}
      />

      <StatusBar
        leaderboard={leaderboard} totalPapers={totalPapers} totalMatches={totalMatches}
        isRanking={isRanking} hasSelectedTags={hasSelectedTags} isTagMode={isTagMode}
        tagMode={tagMode} selectedTags={selectedTags}
      />

      {hasSelectedTags && <StatsToggle globalStats={globalStats} setGlobalStats={setGlobalStats} />}

      <PeriodFilter
        period={period} setPeriod={setPeriod} keyword={keyword} setKeyword={setKeyword}
        isLoggedIn={isLoggedIn} requireAuth={requireAuth}
      />

      {warmingUp && (
        <div className="mb-4 p-4 bg-accent/10 border border-accent/30 rounded-lg flex items-center gap-3" data-testid="warming-up-banner">
          <div className="animate-spin h-5 w-5 border-2 border-accent border-t-transparent rounded-full" />
          <div>
            <p className="text-sm font-medium text-accent">Warming up...</p>
            <p className="text-xs text-muted-foreground">Leaderboard data is being prepared. This only happens once after deployment.</p>
          </div>
        </div>
      )}

      <LeaderboardTable
        leaderboard={leaderboard} loading={loading} showCatCol={isTagMode}
        hasSelectedTags={hasSelectedTags} globalStats={globalStats}
        debouncedKeyword={debouncedKeyword} keyword={keyword}
        displayCount={displayCount} setDisplayCount={setDisplayCount}
        sortKey={sortKey} sortDir={sortDir} onSort={handleSort}
      />

      <div className="mt-6 text-center text-xs text-muted-foreground">
        {hasSelectedTags
          ? "Cross-category rankings based on available tournament matches between tagged papers."
          : isTagMode
          ? "All papers ranked by their tournament performance within their primary categories."
          : "Elo-style ratings from Bradley-Terry model with 95% confidence intervals. Papers compared using full-text deep analysis."}
      </div>
    </div>
    <SuggestionModal open={showSuggestion} onClose={() => setShowSuggestion(false)} defaultType="field" />
    </TooltipProvider>
  );
}
