import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Bookmark, List, Plus, Trash2, ExternalLink, Check, Globe, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/AuthContext";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function BookmarksPage() {
  const { user, getAuthHeaders } = useAuth();
  const { toggleBookmark } = useBookmarks();
  const [tab, setTab] = useState("bookmarks");
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [displayCount, setDisplayCount] = useState(50);
  const [sortKey, setSortKey] = useState("");
  const [sortDir, setSortDir] = useState("desc");
  const [showRatingCol, setShowRatingCol] = useState(true);
  const [showGapCol, setShowGapCol] = useState(true);

  // Reading lists state
  const [myLists, setMyLists] = useState([]);
  const [showCreateList, setShowCreateList] = useState(false);
  const [newListName, setNewListName] = useState("");
  const [newListDesc, setNewListDesc] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    const headers = getAuthHeaders();
    Promise.all([
      axios.get(`${API}/api/bookmarks`, { withCredentials: true, headers }),
      axios.get(`${API}/api/leaderboard?category=cs.RO&period=week`),
      axios.get(`${API}/api/lists`, { withCredentials: true, headers }),
    ]).then(([bkRes, lbRes, listsRes]) => {
      setPapers(bkRes.data.papers || []);
      if (lbRes.data.show_rating_column !== undefined) setShowRatingCol(lbRes.data.show_rating_column);
      if (lbRes.data.show_gap_column !== undefined) setShowGapCol(lbRes.data.show_gap_column);
      setMyLists(listsRes.data.lists || []);
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

  const createListFromBookmarks = async () => {
    if (!newListName.trim()) { toast.error("Enter a list name"); return; }
    setCreating(true);
    try {
      const ids = (filter ? papers.filter(p => (p.categories || []).includes(filter)) : papers).map(p => p.id);
      const res = await axios.post(`${API}/api/lists/from-bookmarks`, {
        name: newListName.trim(), description: newListDesc.trim(), paper_ids: ids,
      }, { withCredentials: true, headers: { ...getAuthHeaders(), "Content-Type": "application/json" } });
      setMyLists(prev => [res.data.list, ...prev]);
      setShowCreateList(false);
      setNewListName("");
      setNewListDesc("");
      toast.success("Reading list created!");
      setTab("lists");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to create list");
    } finally { setCreating(false); }
  };

  const deleteList = async (listId) => {
    try {
      await axios.delete(`${API}/api/lists/${listId}`, { withCredentials: true, headers: getAuthHeaders() });
      setMyLists(prev => prev.filter(l => l.list_id !== listId));
      toast.success("List deleted");
    } catch { toast.error("Failed to delete"); }
  };

  if (!user) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-20 text-center text-muted-foreground">
        <Bookmark className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Sign in to view your bookmarks and reading lists.</p>
      </div>
    );
  }

  const categories = [...new Set(papers.flatMap(p => p.categories || []))];
  const filtered = filter ? papers.filter(p => (p.categories || []).includes(filter)) : papers;
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
      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 p-1 bg-secondary/50 rounded-lg w-fit" data-testid="bookmarks-tabs">
        <button onClick={() => setTab("bookmarks")}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${tab === "bookmarks" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          data-testid="tab-bookmarks">
          <Bookmark className="h-3.5 w-3.5" /> Bookmarks <span className="text-xs text-muted-foreground ml-0.5">({papers.length})</span>
        </button>
        <button onClick={() => setTab("lists")}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${tab === "lists" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          data-testid="tab-lists">
          <List className="h-3.5 w-3.5" /> Reading Lists <span className="text-xs text-muted-foreground ml-0.5">({myLists.length})</span>
        </button>
      </div>

      {/* Bookmarks tab */}
      {tab === "bookmarks" && (
        <>
          <div className="flex items-start justify-between mb-6">
            <div>
              <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight mb-1" data-testid="bookmarks-title">Bookmarks</h1>
              <p className="text-sm text-muted-foreground">{papers.length} saved paper{papers.length !== 1 ? "s" : ""}</p>
            </div>
            {papers.length > 0 && (
              <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => setShowCreateList(!showCreateList)} data-testid="create-list-btn">
                <Plus className="h-3.5 w-3.5" /> Create reading list
              </Button>
            )}
          </div>

          {showCreateList && (
            <div className="mb-6 p-4 border border-border rounded-lg bg-secondary/10 space-y-3" data-testid="create-list-form">
              <h3 className="text-sm font-medium">Create a shareable reading list{filter ? ` from ${filter} bookmarks` : " from all bookmarks"}</h3>
              <Input value={newListName} onChange={e => setNewListName(e.target.value)} placeholder="List name, e.g. Best Robotics Papers Q1 2026" className="text-sm" data-testid="list-name-input" />
              <Input value={newListDesc} onChange={e => setNewListDesc(e.target.value)} placeholder="Description (optional)" className="text-sm" data-testid="list-desc-input" />
              <div className="flex items-center gap-2">
                <Button size="sm" className="gap-1.5" onClick={createListFromBookmarks} disabled={creating} data-testid="create-list-submit">
                  <Plus className="h-3.5 w-3.5" /> {creating ? "Creating..." : `Create with ${filtered.length} papers`}
                </Button>
                <Button size="sm" variant="ghost" className="text-xs" onClick={() => setShowCreateList(false)}>Cancel</Button>
              </div>
            </div>
          )}

          {categories.length > 1 && (
            <div className="flex flex-wrap gap-1.5 mb-6" data-testid="bookmark-filters">
              <button onClick={() => setFilter("")} className={`px-2.5 py-1 rounded-full text-xs transition-colors ${!filter ? "bg-primary text-primary-foreground" : "bg-secondary/50 text-muted-foreground hover:bg-secondary"}`}>All</button>
              {categories.map(cat => (
                <button key={cat} onClick={() => setFilter(cat)} className={`px-2.5 py-1 rounded-full text-xs transition-colors ${filter === cat ? "bg-primary text-primary-foreground" : "bg-secondary/50 text-muted-foreground hover:bg-secondary"}`}>{cat}</button>
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
                leaderboard={ranked} loading={false} showCatCol={!filter}
                hasSelectedTags={false} globalStats={false}
                debouncedKeyword="" keyword=""
                displayCount={displayCount} setDisplayCount={setDisplayCount}
                sortKey={sortKey} sortDir={sortDir} onSort={handleSort}
                showRatingCol={showRatingCol} showGapCol={showGapCol}
                bookmarksMode={true} onRemoveBookmark={handleRemove}
              />
            </div>
          )}
        </>
      )}

      {/* Reading Lists tab */}
      {tab === "lists" && (
        <>
          <div className="flex items-start justify-between mb-6">
            <div>
              <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight mb-1">Reading Lists</h1>
              <p className="text-sm text-muted-foreground">Curate and share collections of papers</p>
            </div>
            {papers.length > 0 && (
              <Button size="sm" className="gap-1.5 text-xs" onClick={() => { setTab("bookmarks"); setShowCreateList(true); }} data-testid="new-list-btn">
                <Plus className="h-3.5 w-3.5" /> New list from bookmarks
              </Button>
            )}
          </div>

          {myLists.length === 0 ? (
            <div className="p-12 text-center text-muted-foreground border border-border rounded-lg">
              <List className="h-8 w-8 mx-auto mb-3 opacity-30" />
              <p className="text-sm font-medium">No reading lists yet</p>
              <p className="text-xs mt-1">Create one from your bookmarks to share curated paper collections.</p>
              {papers.length > 0 && (
                <Button size="sm" variant="outline" className="gap-1.5 text-xs mt-4" onClick={() => { setTab("bookmarks"); setShowCreateList(true); }}>
                  <Plus className="h-3.5 w-3.5" /> Create your first list
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2" data-testid="lists-grid">
              {myLists.map(l => (
                <div key={l.list_id} className="flex items-center gap-3 px-4 py-3 border border-border rounded-lg hover:bg-secondary/20 transition-colors group" data-testid={`list-${l.list_id}`}>
                  <List className="h-4 w-4 text-accent shrink-0" />
                  <div className="flex-1 min-w-0">
                    <Link to={`/list/${l.list_id}`} className="text-sm font-medium hover:text-accent transition-colors truncate block">{l.name}</Link>
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-0.5">
                      <span>{(l.paper_ids || []).length} papers</span>
                      <span>{l.public ? "Public" : "Private"}</span>
                      {l.created_at && <span>Created {new Date(l.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>}
                    </div>
                  </div>
                  <CopyButton url={`${window.location.origin}/list/${l.list_id}`} />
                  <button onClick={() => deleteList(l.list_id)}
                    className="text-red-400 hover:text-red-600 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
                    title="Delete list" data-testid={`delete-list-${l.list_id}`}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
    </TooltipProvider>
  );
}

function CopyButton({ url }) {
  const [copied, setCopied] = useState(false);
  return (
    <button onClick={(e) => { e.preventDefault(); navigator.clipboard.writeText(url); setCopied(true); toast.success("Link copied!"); setTimeout(() => setCopied(false), 2000); }}
      className="text-muted-foreground/50 hover:text-accent transition-colors shrink-0" title="Copy share link">
      {copied ? <Check className="h-3.5 w-3.5" /> : <ExternalLink className="h-3.5 w-3.5" />}
    </button>
  );
}
