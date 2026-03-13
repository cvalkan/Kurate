import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Bookmark, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { useBookmarks } from "@/contexts/BookmarkContext";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function BookmarksPage() {
  const { user, getAuthHeaders } = useAuth();
  const { toggleBookmark } = useBookmarks();
  const [bookmarks, setBookmarks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    axios.get(`${API}/api/bookmarks`, { withCredentials: true, headers: getAuthHeaders() })
      .then(res => setBookmarks(res.data.bookmarks || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user, getAuthHeaders]);

  const handleRemove = async (paperId) => {
    await toggleBookmark(paperId);
    setBookmarks(prev => prev.filter(b => b.paper_id !== paperId));
  };

  if (!user) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-20 text-center text-muted-foreground">
        <Bookmark className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Sign in to view your bookmarks.</p>
      </div>
    );
  }

  const categories = [...new Set(bookmarks.flatMap(b => b.paper_categories || []))];
  const filtered = filter ? bookmarks.filter(b => (b.paper_categories || []).includes(filter)) : bookmarks;

  if (loading) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-12">
        <div className="space-y-3">{[...Array(5)].map((_, i) => <div key={i} className="h-16 bg-secondary/30 rounded-lg animate-pulse" />)}</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 max-w-3xl py-8 md:py-12">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-heading text-xl font-semibold" data-testid="bookmarks-title">Bookmarks</h1>
          <p className="text-sm text-muted-foreground">{bookmarks.length} saved paper{bookmarks.length !== 1 ? "s" : ""}</p>
        </div>
      </div>

      {categories.length > 1 && (
        <div className="flex flex-wrap gap-1.5 mb-6" data-testid="bookmark-filters">
          <button
            onClick={() => setFilter("")}
            className={`px-2.5 py-1 rounded-full text-xs transition-colors ${!filter ? "bg-primary text-primary-foreground" : "bg-secondary/50 text-muted-foreground hover:bg-secondary"}`}
          >All</button>
          {categories.map(cat => (
            <button key={cat} onClick={() => setFilter(cat)}
              className={`px-2.5 py-1 rounded-full text-xs transition-colors ${filter === cat ? "bg-primary text-primary-foreground" : "bg-secondary/50 text-muted-foreground hover:bg-secondary"}`}
            >{cat}</button>
          ))}
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground border border-border rounded-lg">
          <Bookmark className="h-8 w-8 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No bookmarks yet</p>
          <p className="text-xs mt-1">Click the bookmark icon on any paper to save it here.</p>
          <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">Browse the leaderboard</Link>
        </div>
      ) : (
        <div className="space-y-2" data-testid="bookmark-list">
          {filtered.map(b => (
            <div key={b.paper_id} className="flex items-start gap-3 p-3 border border-border rounded-lg hover:bg-secondary/20 transition-colors group" data-testid={`bookmark-${b.paper_id}`}>
              <div className="flex-1 min-w-0">
                <Link to={`/paper/${b.paper_id}`} className="text-sm font-medium hover:text-accent transition-colors line-clamp-2">
                  {b.paper_title}
                </Link>
                <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                  <span className="truncate max-w-[200px]">{(b.paper_authors || []).slice(0, 3).join(", ")}{(b.paper_authors || []).length > 3 ? ` +${b.paper_authors.length - 3}` : ""}</span>
                  {b.paper_categories?.[0] && <span className="px-1.5 py-0.5 rounded bg-secondary/50 text-[10px]">{b.paper_categories[0]}</span>}
                  {b.paper_arxiv_id && (
                    <a href={`https://arxiv.org/abs/${b.paper_arxiv_id}`} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">{b.paper_arxiv_id}</a>
                  )}
                </div>
              </div>
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-muted-foreground/40 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                onClick={() => handleRemove(b.paper_id)} data-testid={`remove-bookmark-${b.paper_id}`}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
