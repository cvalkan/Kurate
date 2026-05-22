import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Helmet } from "react-helmet";
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
import { SignupCTA } from "@/components/SignupCTA";

const API = process.env.REACT_APP_BACKEND_URL;

export default function LeaderboardPage() {
  const [searchParams] = useSearchParams();

  // State — initialized from URL params for back-navigation restore
  const [leaderboard, setLeaderboard] = useState([]);
  const [categories, setCategories] = useState([]);
  const [featured, setFeatured] = useState([]);
  const [newCategoryNames, setNewCategoryNames] = useState([]);
  const [category, setCategory] = useState(searchParams.get("cat") || "");
  const [period, setPeriod] = useState(searchParams.get("period") || "week");
  const [loading, setLoading] = useState(true);
  const [warmingUp, setWarmingUp] = useState(false);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalInPeriod, setTotalInPeriod] = useState(0);
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
  const [globalStats, setGlobalStats] = useState(searchParams.get("global") !== "0");
  const [nextCursor, setNextCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sortPending, setSortPending] = useState(false); // Blocks loadMore during sort transition
  const [sortKey, setSortKey] = useState(searchParams.get("sort") || "rank");
  const [sortDir, setSortDir] = useState(searchParams.get("dir") || "asc");
  const scoringMethod = "ts";

  const { user } = useAuth();
  const [showSuggestion, setShowSuggestion] = useState(false);
  const isLoggedIn = !!user;

  const requireAuth = () => window.dispatchEvent(new Event("open-auth-modal"));
  const abortRef = useRef(null);

  const categoryName = categories.find(c => c.id === category)?.name || "Papers";
  const hasSelectedTags = selectedTags.length > 0;
  const isTagMode = tagFilterOpen || hasSelectedTags;

  const handleSort = (key) => {
    if (!activeArchive) {
      // Server-side sort: block loadMore during the async gap
      setSortPending(true);
      setNextCursor(null);
    }
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "title" || key === "published" ? "asc" : "desc");
    }
  };

  // Capture UTM / ad-tracking params on first mount, then preserve them across
  // URL syncs below. Without this, LeaderboardPage would overwrite ?utm_source=…
  // / ?gclid=… with only its own params, breaking Google Ads & GA4 attribution.
  const preservedAdParams = useMemo(() => {
    const src = new URLSearchParams(window.location.search);
    const keep = new URLSearchParams();
    const AD_KEY = /^(utm_[a-z_]+|gclid|gbraid|wbraid|fbclid|msclkid|ttclid|yclid|twclid|li_fat_id|mc_eid|mc_cid|dclid|scid)$/i;
    for (const k of Array.from(src.keys())) {
      if (AD_KEY.test(k)) keep.set(k, src.get(k));
    }
    return keep;
  }, []);

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
    if (!globalStats) p.set("global", "0");
    if (sortKey && sortKey !== "rank") p.set("sort", sortKey);
    if (sortKey && sortKey !== "rank" && sortDir !== "asc") p.set("dir", sortDir);
    if (activeArchive && archiveSlugRef.current) p.set("archive", archiveSlugRef.current);
    // Re-apply UTM / gclid / etc. so Ads attribution survives every URL rewrite
    for (const [k, v] of preservedAdParams.entries()) p.set(k, v);
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [category, period, selectedTags, tagMode, tagFilterOpen, debouncedKeyword, globalStats, isTagMode, sortKey, sortDir, activeArchive, preservedAdParams]);

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
      setFeatured(res.data.featured || []);
      if (!category) setCategory(res.data.default || "cs.RO");
      // Build "New" category names from IDs
      const newIds = res.data.new_categories || [];
      const allCats = res.data.categories || [];
      setNewCategoryNames(newIds.map(id => allCats.find(c => c.id === id)?.name).filter(Boolean));
    }).catch(() => { if (!category) setCategory("cs.RO"); });
    axios.get(`${API}/api/tags`).then(res => setAllTags(res.data.tags || [])).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounce keyword
  useEffect(() => {
    const t = setTimeout(() => setDebouncedKeyword(keyword), 300);
    return () => clearTimeout(t);
  }, [keyword]);

  // Server-side pagination with server-side sorting.
  const PAGE_SIZE = 200;

  // Client-side sorted (and keyword-filtered) archive leaderboard
  const sortedArchiveLeaderboard = useMemo(() => {
    if (!activeArchive?.leaderboard) return null;
    let data = [...activeArchive.leaderboard];
    // Client-side keyword filter (server-side search is skipped for archives)
    if (debouncedKeyword) {
      const q = debouncedKeyword.toLowerCase();
      data = data.filter(p =>
        (p.title || "").toLowerCase().includes(q) ||
        (p.authors || []).some(a => (a || "").toLowerCase().includes(q)) ||
        (p.arxiv_id || "").toLowerCase().includes(q)
      );
    }
    // Default: preserve array order (position = rank, array sorted by score at freeze time)
    // User can click column headers to re-sort by other fields (win_rate, comparisons, etc.)
    if (!sortKey || sortKey === "rank") {
      // "rank" sort = original array order (ascending position = descending score)
      return sortDir === "desc" ? [...data].reverse() : data;
    }
    // Non-default sort: sort by the requested field
    const key = sortKey === "score" ? "score"
      : sortKey === "wilson_margin" ? "ts_sigma"
      : sortKey === "gap_score" ? "gap_score"
      : sortKey;
    const dir = sortDir || "desc";
    data.sort((a, b) => {
      let va = a[key], vb = b[key];
      if (typeof va === "string" && typeof vb === "string") {
        return dir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      va = va ?? (dir === "asc" ? Infinity : -Infinity);
      vb = vb ?? (dir === "asc" ? Infinity : -Infinity);
      return dir === "asc" ? va - vb : vb - va;
    });
    return data;
  }, [activeArchive, sortKey, sortDir, debouncedKeyword]);


  const fetchLeaderboard = useCallback(async () => {
    if (activeArchive) return; // Archive data is sorted client-side
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
      const effectiveSortKey = sortKey === "score" ? "ts_score"
        : sortKey === "wilson_margin" ? "wilson_margin"
        : sortKey === "gap_score" ? "gap_score"
        : sortKey;
      if (effectiveSortKey && effectiveSortKey !== "rank") {
        params.sort_by = effectiveSortKey;
        params.sort_dir = sortDir;
      } else {
        params.sort_by = "ts_score";
        params.sort_dir = "desc";
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
        setTotalInPeriod(res.data.total_in_period || res.data.total_papers || 0);
        setTotalMatches(res.data.total_matches || 0);
        setIsRanking(res.data.is_ranking || false);
        if (res.data.show_rating_column !== undefined) setShowRatingCol(res.data.show_rating_column);
        if (res.data.show_gap_column !== undefined) setShowGapCol(res.data.show_gap_column);
        if (res.data.archives) setArchives(res.data.archives);
        setSortPending(false);
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
    if (loadingMore || loading || sortPending) return; // Skip if main fetch or sort pending
    // Always use offset-based pagination for TS sort
    const isNonDefaultSort = (sortKey && sortKey !== "rank");
    const useOffset = isNonDefaultSort || true;
    if (useOffset && leaderboard.length === 0) return; // No data yet — fresh sort pending
    setLoadingMore(true);
    try {
      const params = { period, limit: PAGE_SIZE };
      if (useOffset) {
        params.offset = leaderboard.length;
        const effectiveSortKey = sortKey === "score" ? "ts_score"
          : sortKey === "wilson_margin" ? "wilson_margin"
          : sortKey === "gap_score" ? "gap_score"
          : sortKey;
        if (effectiveSortKey && effectiveSortKey !== "rank") {
          params.sort_by = effectiveSortKey;
          params.sort_dir = sortDir;
        } else {
          params.sort_by = "ts_score";
          params.sort_dir = "desc";
        }
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
  }, [nextCursor, loadingMore, loading, sortPending, category, period, selectedTags, tagMode, isTagMode, hasSelectedTags, globalStats, debouncedKeyword, leaderboard.length, sortKey, sortDir]);

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

  // SEO: Build canonical URL (strip noise params, keep only meaningful ones)
  const seoCanonical = useMemo(() => {
    const base = "https://kurate.org";
    if (isTagMode || hasSelectedTags) return base; // tag views → canonical to homepage
    if (category && category !== categories[0]?.id) return `${base}/?cat=${category}`;
    return base;
  }, [category, categories, isTagMode, hasSelectedTags]);
  const seoTitle = activeArchive
    ? `${categoryName} Paper Rankings — ${activeArchive.label} | Kurate.org`
    : hasSelectedTags
    ? `${selectedTags.join(" & ")} Paper Rankings | Kurate.org`
    : `${categoryName} Paper Rankings | Kurate.org`;
  const seoSource = category?.startsWith("iacr.") ? "IACR ePrint" : category?.startsWith("chemrxiv.") ? "ChemRxiv" : "arXiv";
  const seoDesc = `AI-estimated scientific impact ranking of the latest ${seoSource} ${categoryName} preprints. Papers compared using full-text deep analysis by multiple LLMs.`;

  return (
    <TooltipProvider delayDuration={200}>
    <Helmet>
      <title>{seoTitle}</title>
      <meta name="description" content={seoDesc} />
      <link rel="canonical" href={seoCanonical} />
      <meta property="og:title" content={seoTitle} />
      <meta property="og:description" content={seoDesc} />
      <meta property="og:url" content={seoCanonical} />
    </Helmet>    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">{title}</h1>
        <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
          {hasSelectedTags
            ? `Cross-category view: showing papers tagged with ${selectedTags.join(tagMode === "and" ? " AND " : " OR ")}.`
            : isTagMode
            ? "Showing all papers across all categories. Select tags below to filter."
            : <>AI-estimated scientific impact ranking of the latest {category?.startsWith("iacr.") ? "IACR ePrint" : "arXiv"} {categoryName} preprints. <Link to="/methodology" className="text-accent hover:underline">Methodology</Link>{newCategoryNames.length > 0 && <>{" "}<span className="inline-flex items-center gap-1 ml-2 text-xs font-medium text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 dark:text-emerald-400 px-2 py-0.5 rounded-full">New: {newCategoryNames.join(", ")}</span></>}</>}
        </p>
      </div>

      {!isLoggedIn && <SignupCTA onClick={requireAuth} categories={categories} />}

      <CategoryTabs
        categories={categories} featured={featured} category={category}
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
        leaderboard={sortedArchiveLeaderboard || leaderboard}
        totalPapers={activeArchive ? activeArchive.paper_count : totalPapers}
        totalInPeriod={activeArchive ? activeArchive.paper_count : totalInPeriod}
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
          if (data) setScoringMethod("ts"); // Reset to TrueSkill when entering archive
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
        scoringToggle={null}
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

          <div className={sortPending ? "opacity-50 pointer-events-none transition-opacity duration-150" : "transition-opacity duration-150"}>
          <LeaderboardTable
            leaderboard={sortedArchiveLeaderboard || leaderboard}
            loading={loading && !activeArchive} showCatCol={isTagMode}
            hasSelectedTags={hasSelectedTags} globalStats={globalStats}
            debouncedKeyword={debouncedKeyword} keyword={keyword}
            onLoadMore={activeArchive ? null : loadMore}
            hasMore={activeArchive ? false : (!!nextCursor || (leaderboard.length > 0 && leaderboard.length < totalInPeriod && sortKey && sortKey !== "rank"))}
            loadingMore={loadingMore}
            sortKey={sortKey} sortDir={sortDir} onSort={handleSort}
            showRatingCol={showRatingCol} showGapCol={showGapCol}
            scoringMethod={scoringMethod}
            isArchive={!!activeArchive}
          />
          </div>

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
