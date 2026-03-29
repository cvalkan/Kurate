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
  const [period, setPeriod] = useState(searchParams.get("period") || "week");
  const [loading, setLoading] = useState(true);
  const [warmingUp, setWarmingUp] = useState(false);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);
  const [isRanking, setIsRanking] = useState(false);
  const [showRatingCol, setShowRatingCol] = useState(true);
  const [showGapCol, setShowGapCol] = useState(true);
  const [archives, setArchives] = useState([]);
  const [activeArchive, setActiveArchive] = useState(null);

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
  const [nextCursor, setNextCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sortKey, setSortKey] = useState(searchParams.get("sort") || "rank");
  const [sortDir, setSortDir] = useState(searchParams.get("dir") || "asc");
  const [scoringMethod, setScoringMethod] = useState(searchParams.get("method") || "wr");

  const { user } = useAuth();
  const [showSuggestion, setShowSuggestion] = useState(false);
  const isLoggedIn = !!user;

  const requireAuth = () => window.dispatchEvent(new Event("open-auth-modal"));
  const abortRef = useRef(null);

  const categoryName = categories.find(c => c.id === category)?.name || "Papers";
  const hasSelectedTags = selectedTags.length > 0;
  const isTagMode = tagFilterOpen || hasSelectedTags;

  const handleSort = (key) => {
    // Clear data immediately to prevent loadMore from firing with stale offset
    // during the async gap before fetchLeaderboard's response arrives
    setLeaderboard([]);
    setNextCursor(null);
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "title" || key === "published" ? "asc" : "desc");
    }
  };

  // Capture archive slug from URL on mount (before URL sync overwrites it)
  const archiveSlugRef = useRef(new URLSearchParams(window.location.search).get("archive"));

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
    if (activeArchive && archiveSlugRef.current) p.set("archive", archiveSlugRef.current);
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [category, period, selectedTags, tagMode, tagFilterOpen, debouncedKeyword, globalStats, isTagMode, sortKey, sortDir, activeArchive]);

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

  // Server-side pagination with server-side sorting.
  // Single-category views are small (<1000 papers) — load all at once for instant sorting.
  // Cross-category (show_all/tags) can be 2000+ papers — paginate for performance.
  const PAGE_SIZE = isTagMode ? 200 : 2000;

  const fetchLeaderboard = useCallback(async () => {
    if (!category && !isTagMode) return;
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const params = { period, limit: PAGE_SIZE };
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
      // Server-side sorting
      if (sortKey && sortKey !== "rank") {
        params.sort_by = sortKey;
        params.sort_dir = sortDir;
      }
      const res = await axios.get(`${API}/api/leaderboard`, { params, signal: controller.signal });
      if (!controller.signal.aborted) {
        if (res.data.warming_up) {
          setWarmingUp(true);
          setLeaderboard([]);
          setNextCursor(null);
          setLoading(false);
          setTimeout(() => fetchLeaderboard(), 2000);
          return;
        }
        setWarmingUp(false);
        setLeaderboard((res.data.leaderboard || []).map((e, i) => ({ ...e, rank: i + 1 })));
        setNextCursor(res.data.next_cursor || null);
        setTotalPapers(res.data.total_papers || 0);
        setTotalMatches(res.data.total_matches || 0);
        setIsRanking(res.data.is_ranking || false);
        if (res.data.show_rating_column !== undefined) setShowRatingCol(res.data.show_rating_column);
        if (res.data.show_gap_column !== undefined) setShowGapCol(res.data.show_gap_column);
        if (res.data.archives) setArchives(res.data.archives);
        setLoading(false);
      }
    } catch (err) {
      if (err.name !== "CanceledError" && err.code !== "ERR_CANCELED") {
        console.error("Failed to fetch leaderboard:", err);
        setLoading(false);
      }
    }
  }, [category, period, selectedTags, tagMode, isTagMode, hasSelectedTags, globalStats, debouncedKeyword, sortKey, sortDir]);

  // Load next page using keyset cursor or offset (infinite scroll)
  const loadMore = useCallback(async () => {
    if (loadingMore || loading) return; // Skip if main fetch is pending
    // For non-default sorts, use offset-based pagination (no keyset cursor)
    const useOffset = sortKey && sortKey !== "rank";
    if (!useOffset && !nextCursor) return;
    if (useOffset && leaderboard.length === 0) return; // No data yet — fresh sort pending
    setLoadingMore(true);
    try {
      const params = { period, limit: PAGE_SIZE };
      if (useOffset) {
        params.offset = leaderboard.length;
        params.sort_by = sortKey;
        params.sort_dir = sortDir;
      } else {
        params.cursor = nextCursor;
      }
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
      const res = await axios.get(`${API}/api/leaderboard`, { params });
      const newEntries = res.data.leaderboard || [];
      if (newEntries.length > 0) {
        // Fix rank numbers to continue from where we left off
        const startRank = leaderboard.length + 1;
        const renumbered = newEntries.map((e, i) => ({ ...e, rank: startRank + i }));
        setLeaderboard(prev => [...prev, ...renumbered]);
      }
      setNextCursor(res.data.next_cursor || null);
      // If fewer entries returned than requested, no more pages
      if (newEntries.length < PAGE_SIZE) setNextCursor(null);
    } catch (err) {
      console.error("Failed to load more:", err);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore, category, period, selectedTags, tagMode, isTagMode, hasSelectedTags, globalStats, debouncedKeyword, leaderboard.length, sortKey, sortDir]);

  // Fetch on param change (debounce tag mode)
  const initialLoadDone = useRef(false);
  const debounceRef = useRef(null);
  useEffect(() => {
    if (!initialLoadDone.current) setLoading(true);
    setNextCursor(null);  // Reset cursor on param change
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

  // Load archive from URL param on mount (after archives list is populated)
  useEffect(() => {
    const slug = archiveSlugRef.current;
    if (!slug || !archives.length || activeArchive) return;
    const match = archives.find(a => {
      const s = a.period_type === "older" ? "older"
        : a.period_type === "weekly" ? `${a.year}-w${a.week}` : `${a.year}-m${a.month}`;
      return s === slug;
    });
    if (!match) return;
    const apiSlug = match.period_type === "older" ? "older"
      : match.period_type === "weekly" ? `w${match.week}` : `m${match.month}`;
    const url = match.period_type === "older"
      ? `${API}/api/archive/${match.category}/older`
      : `${API}/api/archive/${match.category}/${match.year}/${apiSlug}`;
    axios.get(url).then(r => { if (r.data.leaderboard) { setActiveArchive(r.data); setLoading(false); } }).catch(() => {});
  }, [archives]); // eslint-disable-line react-hooks/exhaustive-deps



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
        categories={categories} category={category}
        setCategory={(cat) => { setCategory(cat); if (activeArchive) { setActiveArchive(null); setPeriod("week"); const p = new URLSearchParams(window.location.search); p.delete("archive"); window.history.replaceState(null, "", `?${p.toString()}`); } }}
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
        leaderboard={activeArchive ? activeArchive.leaderboard : leaderboard}
        totalPapers={activeArchive ? activeArchive.paper_count : totalPapers}
        totalMatches={activeArchive ? activeArchive.match_count : totalMatches}
        isRanking={activeArchive ? false : isRanking}
        hasSelectedTags={hasSelectedTags} isTagMode={isTagMode}
        tagMode={tagMode} selectedTags={selectedTags}
      />

      {hasSelectedTags && <StatsToggle globalStats={globalStats} setGlobalStats={setGlobalStats} />}

      <PeriodFilter
        period={activeArchive ? null : period} setPeriod={setPeriod} keyword={keyword} setKeyword={setKeyword}
        isLoggedIn={isLoggedIn} requireAuth={requireAuth} archives={isTagMode ? [] : archives}
        onArchiveSelect={(data, archive) => {
          setActiveArchive(data);
          if (data && archive) {
            const slug = archive.period_type === "older" ? "older"
              : archive.period_type === "weekly" ? `${archive.year}-w${archive.week}`
              : `${archive.year}-m${archive.month}`;
            archiveSlugRef.current = slug;
          } else {
            archiveSlugRef.current = null;
          }
          if (data) setLoading(false);
        }}
        activeArchiveLabel={activeArchive?.label}
        scoringToggle={
          <div className="flex items-center gap-2 shrink-0" data-testid="scoring-method-toggle">
            <div className="flex items-center gap-0.5 p-0.5 bg-secondary/50 rounded-md">
              {[["wr", "Win Rate"], ["ts", "TrueSkill"]].map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setScoringMethod(key)}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
                    scoringMethod === key
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  data-testid={`scoring-method-${key}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="text-[10px] text-muted-foreground hidden sm:inline">
              {scoringMethod === "ts" ? "Bayesian TrueSkill rating" : "Regularized win-rate (default)"}
            </span>
          </div>
        }
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
            leaderboard={activeArchive ? activeArchive.leaderboard : leaderboard}
            loading={loading && !activeArchive} showCatCol={isTagMode}
            hasSelectedTags={hasSelectedTags} globalStats={globalStats}
            debouncedKeyword={debouncedKeyword} keyword={keyword}
            onLoadMore={activeArchive ? null : loadMore}
            hasMore={activeArchive ? false : (!!nextCursor || (leaderboard.length > 0 && leaderboard.length < totalPapers && sortKey && sortKey !== "rank"))}
            loadingMore={loadingMore}
            sortKey={sortKey} sortDir={sortDir} onSort={handleSort}
            showRatingCol={showRatingCol} showGapCol={showGapCol}
            scoringMethod={scoringMethod}
          />

      <div className="mt-6 text-center text-xs text-muted-foreground">
        {hasSelectedTags
          ? "Cross-category rankings based on available tournament matches between tagged papers."
          : isTagMode
          ? "All papers ranked by their tournament performance within their primary categories."
          : "Win-rate scores from pairwise comparisons with 95% confidence intervals. Papers compared using full-text deep analysis."}
      </div>
    </div>
    <SuggestionModal open={showSuggestion} onClose={() => setShowSuggestion(false)} defaultType="field" />
    </TooltipProvider>
  );
}
