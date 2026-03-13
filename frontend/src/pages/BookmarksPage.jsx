import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Bookmark } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function BookmarksPage() {
  const { user, getAuthHeaders } = useAuth();
  const { toggleBookmark } = useBookmarks();
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [displayCount, setDisplayCount] = useState(50);
  const [sortKey, setSortKey] = useState("");
  const [sortDir, setSortDir] = useState("desc");

  const [showRatingCol, setShowRatingCol] = useState(true);
  const [showGapCol, setShowGapCol] = useState(true);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    // Fetch bookmarks + admin column visibility settings in parallel
    Promise.all([
      axios.get(`${API}/api/bookmarks`, { withCredentials: true, headers: getAuthHeaders() }),
      axios.get(`${API}/api/leaderboard?category=cs.RO&period=week`),
    ]).then(([bkRes, lbRes]) => {
      setPapers(bkRes.data.papers || []);
      if (lbRes.data.show_rating_column !== undefined) setShowRatingCol(lbRes.data.show_rating_column);
      if (lbRes.data.show_gap_column !== undefined) setShowGapCol(lbRes.data.show_gap_column);
    }).catch(() => {})
      .finally(() => setLoading(false));
  }, [user, getAuthHeaders]);

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir(key === "title" || key === "bookmarked_at" ? "asc" : "desc"); }
  };

  const handleRemove = async (paperId) => {
    await toggleBookmark(paperId);
    setPapers(prev => prev.filter(p => p.id !== paperId));
  };

  if (!user) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-20 text-center text-muted-foreground">
        <Bookmark className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Sign in to view your bookmarks.</p>
      </div>
    );
  }

  const categories = [...new Set(papers.flatMap(p => p.categories || []))];
  const filtered = filter ? papers.filter(p => (p.categories || []).includes(filter)) : papers;

  // Add rank for display (rank by bookmark order or score)
  const ranked = filtered.map((p, i) => ({ ...p, rank: i + 1, _displayRank: i + 1 }));

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-7xl py-12">
        <div className="space-y-3">{[...Array(5)].map((_, i) => <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />)}</div>
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-8 md:py-10">
      <div className="mb-6">
        <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight mb-1" data-testid="bookmarks-title">Bookmarks</h1>
        <p className="text-sm text-muted-foreground">{papers.length} saved paper{papers.length !== 1 ? "s" : ""}</p>
      </div>

      {categories.length > 1 && (
        <div className="flex flex-wrap gap-1.5 mb-6" data-testid="bookmark-filters">
          <button onClick={() => setFilter("")}
            className={`px-2.5 py-1 rounded-full text-xs transition-colors ${!filter ? "bg-primary text-primary-foreground" : "bg-secondary/50 text-muted-foreground hover:bg-secondary"}`}
          >All</button>
          {categories.map(cat => (
            <button key={cat} onClick={() => setFilter(cat)}
              className={`px-2.5 py-1 rounded-full text-xs transition-colors ${filter === cat ? "bg-primary text-primary-foreground" : "bg-secondary/50 text-muted-foreground hover:bg-secondary"}`}
            >{cat}</button>
          ))}
        </div>
      )}

      {ranked.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground border border-border rounded-lg">
          <Bookmark className="h-8 w-8 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No bookmarks yet</p>
          <p className="text-xs mt-1">Click the bookmark icon on any paper to save it here.</p>
          <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">Browse the leaderboard</Link>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <LeaderboardTable
            leaderboard={ranked}
            loading={false}
            showCatCol={!filter}
            hasSelectedTags={false}
            globalStats={false}
            debouncedKeyword=""
            keyword=""
            displayCount={displayCount}
            setDisplayCount={setDisplayCount}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={handleSort}
            showRatingCol={showRatingCol}
            showGapCol={showGapCol}
            bookmarksMode={true}
            onRemoveBookmark={handleRemove}
          />
        </div>
      )}
    </div>
    </TooltipProvider>
  );
}
