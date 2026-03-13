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

  // Selection state for "Save to Reading List"
  const [selectedPapers, setSelectedPapers] = useState(new Set());
  const [showSaveToList, setShowSaveToList] = useState(false);
  const [saveTarget, setSaveTarget] = useState(""); // list_id or "__new__"
  const [saving, setSaving] = useState(false);

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
    setSelectedPapers(prev => { const next = new Set(prev); next.delete(paperId); return next; });
  };

  const toggleSelect = (paperId) => {
    setSelectedPapers(prev => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId); else next.add(paperId);
      return next;
    });
  };

  const saveToList = async () => {
    if (!selectedPapers.size) { toast.error("Select papers first"); return; }
    const ids = [...selectedPapers];
    setSaving(true);
    try {
      if (saveTarget === "__new__") {
        if (!newListName.trim()) { toast.error("Enter a list name"); setSaving(false); return; }
        const res = await axios.post(`${API}/api/lists/from-bookmarks`, {
          name: newListName.trim(), description: newListDesc.trim(), paper_ids: ids,
        }, { withCredentials: true, headers: { ...getAuthHeaders(), "Content-Type": "application/json" } });
        setMyLists(prev => [res.data.list, ...prev]);
        setNewListName(""); setNewListDesc("");
        toast.success(`Created "${res.data.list.name}" with ${ids.length} papers`);
      } else {
        const res = await axios.post(`${API}/api/lists/${saveTarget}/papers`, { paper_ids: ids },
          { withCredentials: true, headers: { ...getAuthHeaders(), "Content-Type": "application/json" } });
        const listName = myLists.find(l => l.list_id === saveTarget)?.name || "list";
        toast.success(`Added ${res.data.added} paper${res.data.added !== 1 ? "s" : ""} to "${listName}"`);
        // Update local list paper count
        setMyLists(prev => prev.map(l => l.list_id === saveTarget ? { ...l, paper_ids: [...(l.paper_ids || []), ...ids] } : l));
      }
      setSelectedPapers(new Set());
      setShowSaveToList(false);
      setSaveTarget("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to save");
    } finally { setSaving(false); }
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
          <div className="flex items-start justify-between mb-4">
            <div>
              <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight mb-1" data-testid="bookmarks-title">Bookmarks</h1>
              <p className="text-sm text-muted-foreground">{papers.length} saved paper{papers.length !== 1 ? "s" : ""}</p>
            </div>
          </div>

          {/* Save to reading list bar */}
          {selectedPapers.size > 0 && (
            <div className="mb-4 p-3 border border-accent/30 rounded-lg bg-accent/5 flex flex-wrap items-center gap-3" data-testid="save-to-list-bar">
              <span className="text-sm font-medium">{selectedPapers.size} selected</span>
              <select value={saveTarget} onChange={e => { setSaveTarget(e.target.value); setShowSaveToList(true); }}
                className="h-8 rounded-md border border-input bg-background px-2 text-xs min-w-[180px]" data-testid="list-select">
                <option value="">Choose a reading list...</option>
                {myLists.map(l => <option key={l.list_id} value={l.list_id}>{l.name} ({(l.paper_ids||[]).length})</option>)}
                <option value="__new__">+ Create new list</option>
              </select>
              {saveTarget === "__new__" && (
                <Input value={newListName} onChange={e => setNewListName(e.target.value)}
                  placeholder="New list name" className="text-xs h-8 w-52" data-testid="new-list-name" />
              )}
              {saveTarget && (
                <Button size="sm" className="gap-1.5 h-8 text-xs" onClick={saveToList} disabled={saving} data-testid="save-to-list-btn">
                  <List className="h-3.5 w-3.5" /> {saving ? "Saving..." : "Save to list"}
                </Button>
              )}
              <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => { setSelectedPapers(new Set()); setSaveTarget(""); }}>
                Clear
              </Button>
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
                selectedPapers={selectedPapers} onToggleSelect={toggleSelect}
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
              <Button size="sm" className="gap-1.5 text-xs" onClick={() => { setTab("bookmarks"); }} data-testid="new-list-btn">
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
                <Button size="sm" variant="outline" className="gap-1.5 text-xs mt-4" onClick={() => { setTab("bookmarks"); }}>
                  <Plus className="h-3.5 w-3.5" /> Select papers from bookmarks
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
