import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Shared hook for leaderboard data — used by design explorations.
 * Handles category loading, paper fetching, sorting, infinite scroll.
 */
export function useLeaderboardData() {
  const [categories, setCategories] = useState([]);
  const [featured, setFeatured] = useState([]);
  const [category, setCategory] = useState("");  // "" = All Categories
  const [period, setPeriod] = useState("week");
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [sortKey, setSortKey] = useState("rank");
  const [sortDir, setSortDir] = useState("asc");
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);
  const [nextCursor, setNextCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [showRatingCol, setShowRatingCol] = useState(true);
  const [showGapCol, setShowGapCol] = useState(true);
  const abortRef = useRef(null);

  // Debounce search
  useEffect(() => {
    if (keyword === debouncedKeyword) return;
    const id = setTimeout(() => setDebouncedKeyword(keyword), 250);
    return () => clearTimeout(id);
  }, [keyword, debouncedKeyword]);

  // Load categories
  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      const cats = res.data.categories || [];
      setCategories(cats);
      setFeatured(res.data.featured || []);
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch leaderboard
  useEffect(() => {
    if (categories.length === 0) return;
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);

    const params = new URLSearchParams();
    if (category) params.set("category", category);
    params.set("period", period);
    params.set("limit", "50");
    if (debouncedKeyword) params.set("search", debouncedKeyword);
    if (sortKey && sortKey !== "rank") { params.set("sort_by", sortKey); params.set("sort_dir", sortDir); }

    axios.get(`${API}/api/leaderboard?${params}`, { signal: ctrl.signal })
      .then(res => {
        if (ctrl.signal.aborted) return;
        setLeaderboard(res.data.leaderboard || []);
        setTotalPapers(res.data.total_papers || 0);
        setTotalMatches(res.data.total_matches || 0);
        setNextCursor(res.data.next_cursor || null);
        setShowRatingCol(res.data.show_rating_column !== false);
        setShowGapCol(res.data.show_gap_column !== false);
        setLoading(false);
      })
      .catch(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [category, period, debouncedKeyword, sortKey, sortDir, categories.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      if (category) params.set("category", category);
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
  }, [nextCursor, loadingMore, category, period, debouncedKeyword, sortKey, sortDir]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "title" || key === "published" ? "asc" : "desc");
    }
  };

  return {
    categories, featured, category, setCategory,
    period, setPeriod, keyword, setKeyword, debouncedKeyword,
    sortKey, sortDir, handleSort,
    leaderboard, loading, totalPapers, totalMatches,
    nextCursor, loadMore, loadingMore,
    showRatingCol, showGapCol,
  };
}
