import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Full-featured leaderboard hook — matches the production LeaderboardPage's API contract.
 * Supports: categories, tags (AND/OR), periods, archives, sorting, search, infinite scroll.
 * Reads initial state from URL search params (cat, period, sort, dir, q, tags, tag_mode).
 */
export function useLeaderboardData() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [categories, setCategories] = useState([]);
  const [featured, setFeatured] = useState([]);
  const [allTags, setAllTags] = useState([]);
  const [category, setCategory] = useState(searchParams.get("cat") || "");
  const [selectedTags, setSelectedTags] = useState(() => {
    const t = searchParams.get("tags");
    return t ? t.split(",").filter(Boolean) : [];
  });
  const [tagMode, setTagMode] = useState(searchParams.get("tag_mode") || "or");
  const [tagFilterOpen, setTagFilterOpen] = useState(!!searchParams.get("tags"));
  const [period, setPeriod] = useState(searchParams.get("period") || "week");
  const [keyword, setKeyword] = useState(searchParams.get("q") || "");
  const [debouncedKeyword, setDebouncedKeyword] = useState(searchParams.get("q") || "");
  const [sortKey, setSortKey] = useState(searchParams.get("sort") || "rank");
  const [sortDir, setSortDir] = useState(searchParams.get("dir") || "asc");
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalInPeriod, setTotalInPeriod] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);
  const [isRanking, setIsRanking] = useState(false);
  const [nextCursor, setNextCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [showRatingCol, setShowRatingCol] = useState(true);
  const [showGapCol, setShowGapCol] = useState(true);
  const [archives, setArchives] = useState([]);
  const [activeArchive, setActiveArchive] = useState(null);
  const [globalStats, setGlobalStats] = useState(false);
  const abortRef = useRef(null);

  const isTagMode = tagFilterOpen || selectedTags.length > 0;
  const hasSelectedTags = selectedTags.length > 0;

  // Sync filter state to URL params (so back button / links preserve state)
  useEffect(() => {
    const p = new URLSearchParams();
    if (category) p.set("cat", category);
    if (period && period !== "week") p.set("period", period);
    if (sortKey && sortKey !== "rank") p.set("sort", sortKey);
    if (sortDir && sortDir !== "asc") p.set("dir", sortDir);
    if (debouncedKeyword) p.set("q", debouncedKeyword);
    if (selectedTags.length > 0) p.set("tags", selectedTags.join(","));
    if (selectedTags.length > 0 && tagMode !== "or") p.set("tag_mode", tagMode);
    setSearchParams(p, { replace: true });
  }, [category, period, sortKey, sortDir, debouncedKeyword, selectedTags, tagMode, setSearchParams]);

  // Debounce search
  useEffect(() => {
    if (keyword === debouncedKeyword) return;
    const id = setTimeout(() => setDebouncedKeyword(keyword), 250);
    return () => clearTimeout(id);
  }, [keyword, debouncedKeyword]);

  // Load categories + tags
  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
      setFeatured(res.data.featured || []);
    }).catch(() => {});
    axios.get(`${API}/api/tags`).then(res => {
      setAllTags(res.data.tags || []);
    }).catch(() => {});
  }, []);

  // Fetch leaderboard
  useEffect(() => {
    if (categories.length === 0) return;
    if (activeArchive) return; // Archive data is loaded separately
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);

    const params = new URLSearchParams();

    if (hasSelectedTags) {
      params.set("tags", selectedTags.join(","));
      params.set("tag_mode", tagMode);
      if (globalStats) params.set("global_stats", "true");
    } else if (isTagMode) {
      params.set("show_all", "true");
    } else if (category) {
      params.set("category", category);
    }

    params.set("period", period);
    params.set("limit", "50");
    if (debouncedKeyword) params.set("search", debouncedKeyword);
    if (sortKey && sortKey !== "rank") {
      params.set("sort_by", sortKey);
      params.set("sort_dir", sortDir);
    }

    axios.get(`${API}/api/leaderboard?${params}`, { signal: ctrl.signal })
      .then(res => {
        if (ctrl.signal.aborted) return;
        const d = res.data;
        setLeaderboard(d.leaderboard || []);
        setTotalPapers(d.total_papers || 0);
        setTotalInPeriod(d.total_in_period || 0);
        setTotalMatches(d.total_matches || 0);
        setIsRanking(d.is_ranking || false);
        setNextCursor(d.next_cursor || null);
        setShowRatingCol(d.show_rating_column !== false);
        setShowGapCol(d.show_gap_column !== false);
        setArchives(d.archives || []);
        setLoading(false);
      })
      .catch(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [category, period, debouncedKeyword, sortKey, sortDir, categories.length, selectedTags, tagMode, isTagMode, hasSelectedTags, globalStats, activeArchive]);

  // Load more (infinite scroll)
  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore || activeArchive) return;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      if (hasSelectedTags) {
        params.set("tags", selectedTags.join(","));
        params.set("tag_mode", tagMode);
        if (globalStats) params.set("global_stats", "true");
      } else if (category) {
        params.set("category", category);
      }
      params.set("period", period);
      params.set("limit", "50");
      params.set("cursor", nextCursor);
      if (debouncedKeyword) params.set("search", debouncedKeyword);
      if (sortKey && sortKey !== "rank") { params.set("sort_by", sortKey); params.set("sort_dir", sortDir); }
      const res = await axios.get(`${API}/api/leaderboard?${params}`);
      setLeaderboard(prev => [...prev, ...(res.data.leaderboard || [])]);
      setNextCursor(res.data.next_cursor || null);
    } catch { /* ignore */ }
    setLoadingMore(false);
  }, [nextCursor, loadingMore, category, period, debouncedKeyword, sortKey, sortDir, selectedTags, tagMode, hasSelectedTags, globalStats, activeArchive]);

  // Load archive
  const loadArchive = useCallback(async (archive) => {
    if (!archive) { setActiveArchive(null); return; }
    try {
      const slug = archive.period_type === "older" ? "older"
        : archive.period_type === "weekly" ? `w${archive.week}` : `m${archive.month}`;
      const url = archive.period_type === "older"
        ? `${API}/api/archive/${archive.category}/older`
        : `${API}/api/archive/${archive.category}/${archive.year}/${slug}`;
      const res = await axios.get(url);
      if (res.data.leaderboard) {
        setActiveArchive({ ...res.data, label: archive.label || slug });
        setLeaderboard(res.data.leaderboard || []);
        setLoading(false);
      }
    } catch (e) {
      console.error("Failed to load archive:", e);
    }
  }, []);

  const clearArchive = useCallback(() => {
    setActiveArchive(null);
  }, []);

  const handleSort = useCallback((key) => {
    if (!activeArchive) {
      setNextCursor(null);
    }
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "title" || key === "published" ? "asc" : "desc");
    }
  }, [sortKey, activeArchive]);

  // For archive mode, sort locally
  const displayLeaderboard = useMemo(() => {
    if (!activeArchive) return leaderboard;
    const sorted = [...leaderboard];
    if (sortKey && sortKey !== "rank") {
      const dir = sortDir === "asc" ? 1 : -1;
      sorted.sort((a, b) => {
        const va = a[sortKey] ?? a.ts_score ?? 0;
        const vb = b[sortKey] ?? b.ts_score ?? 0;
        if (typeof va === "string") return dir * va.localeCompare(vb);
        return dir * (va - vb);
      });
    }
    return sorted.map((p, i) => ({ ...p, _displayRank: i + 1 }));
  }, [leaderboard, activeArchive, sortKey, sortDir]);

  const categoryName = useMemo(() => {
    if (hasSelectedTags) return selectedTags.join(tagMode === "and" ? " ∩ " : " ∪ ");
    if (isTagMode) return "All Papers";
    if (!category) return "All";
    return categories.find(c => c.id === category)?.name || category;
  }, [category, categories, hasSelectedTags, selectedTags, tagMode, isTagMode]);

  return {
    categories, featured, allTags,
    category, setCategory, categoryName,
    selectedTags, setSelectedTags, tagMode, setTagMode,
    tagFilterOpen, setTagFilterOpen, isTagMode, hasSelectedTags,
    period, setPeriod, keyword, setKeyword, debouncedKeyword,
    sortKey, sortDir, handleSort,
    leaderboard: displayLeaderboard, loading, totalPapers, totalInPeriod, totalMatches, isRanking,
    nextCursor, loadMore, loadingMore,
    showRatingCol, showGapCol,
    archives, activeArchive, loadArchive, clearArchive,
    globalStats, setGlobalStats,
  };
}
