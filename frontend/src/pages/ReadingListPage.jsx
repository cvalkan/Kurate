import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { List, ExternalLink, Copy, Check, User, Share2, Bookmark, Plus, ChevronDown, ChevronLeft, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuth } from "@/contexts/AuthContext";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function ReadingListPage() {
  const { listId } = useParams();
  const { user, getAuthHeaders } = useAuth();
  const { refreshBookmarks } = useBookmarks();
  const [list, setList] = useState(null);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [displayCount, setDisplayCount] = useState(50);
  const [sortKey, setSortKey] = useState("");
  const [sortDir, setSortDir] = useState("desc");

  // Import state
  const [showImport, setShowImport] = useState(false);
  const [myLists, setMyLists] = useState([]);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    axios.get(`${API}/api/lists/public/${listId}`)
      .then(res => { setList(res.data.list); setPapers(res.data.papers || []); })
      .catch(() => setList(null))
      .finally(() => setLoading(false));
  }, [listId]);

  // Fetch user's own lists for import target
  useEffect(() => {
    if (!user) return;
    axios.get(`${API}/api/lists`, { withCredentials: true, headers: getAuthHeaders() })
      .then(res => setMyLists(res.data.lists || []))
      .catch(() => {});
  }, [user, getAuthHeaders]);

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir(key === "title" ? "asc" : "desc"); }
  };

  const shareUrl = `${window.location.origin}/api/lists/${listId}/share`;
  const listUrl = `${window.location.origin}/list/${listId}`;

  const copyLink = () => {
    navigator.clipboard.writeText(listUrl);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  const shareTwitter = () => {
    const text = `Check out "${list?.name}" — a curated reading list of ${list?.paper_count} papers on Kurate.org!\n\n${shareUrl}`;
    window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`, "_blank");
  };

  const shareLinkedIn = () => {
    const text = `Check out "${list?.name}" — a curated reading list of ${list?.paper_count} papers on Kurate.org!`;
    navigator.clipboard.writeText(text).then(() => toast.success("Text copied — paste it in your LinkedIn post!")).catch(() => {});
    window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`, "_blank");
  };

  const importAsBookmarks = async () => {
    setImporting(true);
    try {
      const res = await axios.post(`${API}/api/lists/${listId}/import-bookmarks`, {}, { withCredentials: true, headers: getAuthHeaders() });
      toast.success(`Imported ${res.data.added} paper${res.data.added !== 1 ? "s" : ""} as bookmarks`);
      setShowImport(false);
      refreshBookmarks();
    } catch (err) { toast.error(err.response?.data?.detail || "Failed"); }
    finally { setImporting(false); }
  };

  const importToList = async (targetId) => {
    setImporting(true);
    try {
      const res = await axios.post(`${API}/api/lists/${listId}/import-to-list?target_list_id=${targetId}`, {}, { withCredentials: true, headers: getAuthHeaders() });
      const name = myLists.find(l => l.list_id === targetId)?.name || "list";
      toast.success(`Added ${res.data.added} paper${res.data.added !== 1 ? "s" : ""} to "${name}"`);
      setShowImport(false);
    } catch (err) { toast.error(err.response?.data?.detail || "Failed"); }
    finally { setImporting(false); }
  };

  const forkAsNewList = async () => {
    setImporting(true);
    try {
      await axios.post(`${API}/api/lists/${listId}/fork`, {}, { withCredentials: true, headers: getAuthHeaders() });
      toast.success("Saved as a new reading list!");
      setShowImport(false);
    } catch (err) { toast.error(err.response?.data?.detail || "Failed"); }
    finally { setImporting(false); }
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-7xl py-12">
        <div className="space-y-3">{[...Array(5)].map((_, i) => <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />)}</div>
      </div>
    );
  }

  if (!list) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-20 text-center text-muted-foreground">
        <List className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Reading list not found or is private.</p>
        <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">View Leaderboard</Link>
      </div>
    );
  }

  const ranked = papers.map((p, i) => ({ ...p, rank: i + 1, _displayRank: i + 1 }));

  return (
    <TooltipProvider delayDuration={200}>
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-8 md:py-10">
      <div className="mb-6">
        <button onClick={() => window.history.back()} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-2 transition-colors">
          <ChevronLeft className="h-3 w-3" /> Back
        </button>
        <div className="flex items-start justify-between gap-4 mb-1">
          <div>
            <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight" data-testid="list-title">{list.name}</h1>
            {list.description && <p className="text-sm text-muted-foreground mt-1 hidden">{list.description}</p>}
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground mb-4">
          <span className="flex items-center gap-1"><User className="h-3 w-3" /> {list.user_name || "Anonymous"}</span>
          <span>{list.paper_count} paper{list.paper_count !== 1 ? "s" : ""}</span>
          {list.created_at && <span>Created {new Date(list.created_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}</span>}
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-2" data-testid="list-actions">
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={copyLink} data-testid="copy-list-link">
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied!" : "Copy link"}
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={shareTwitter} data-testid="share-x-btn">
            <Share2 className="h-3.5 w-3.5" /> Share on X
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={shareLinkedIn} data-testid="share-linkedin-btn">
            <Share2 className="h-3.5 w-3.5" /> Share on LinkedIn
          </Button>
          <a href={`${API}/api/lists/${listId}/image.png`} download={`kurate-list-${listId}.png`} className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded-md border border-input bg-background hover:bg-secondary/50 transition-colors font-medium" data-testid="download-list-img">
            <Download className="h-3.5 w-3.5" /> Download image
          </a>
          {user && (
            <div className="relative">
              <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => setShowImport(!showImport)} data-testid="import-btn">
                <Plus className="h-3.5 w-3.5" /> Import <ChevronDown className={`h-3 w-3 transition-transform ${showImport ? "rotate-180" : ""}`} />
              </Button>
              {showImport && (
                <div className="absolute top-full mt-1 left-0 z-50 bg-background border border-border rounded-lg shadow-lg min-w-[220px] py-1" data-testid="import-dropdown">
                  <button onClick={importAsBookmarks} disabled={importing}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-secondary/30 flex items-center gap-2">
                    <Bookmark className="h-3.5 w-3.5 text-muted-foreground" /> Import as bookmarks
                  </button>
                  <div className="border-t border-border my-1" />
                  {myLists.length > 0 && (
                    <>
                      <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-muted-foreground font-medium">Add to existing list</div>
                      {myLists.map(l => (
                        <button key={l.list_id} onClick={() => importToList(l.list_id)} disabled={importing}
                          className="w-full text-left px-3 py-1.5 text-sm hover:bg-secondary/30 flex items-center gap-2 truncate">
                          <List className="h-3 w-3 text-muted-foreground shrink-0" /> {l.name}
                        </button>
                      ))}
                      <div className="border-t border-border my-1" />
                    </>
                  )}
                  <button onClick={forkAsNewList} disabled={importing}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-secondary/30 flex items-center gap-2">
                    <Plus className="h-3.5 w-3.5 text-muted-foreground" /> Save as new list
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {ranked.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground border border-border rounded-lg">
          <List className="h-8 w-8 mx-auto mb-3 opacity-30" />
          <p className="text-sm">This reading list is empty.</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <LeaderboardTable
            leaderboard={ranked}
            loading={false}
            showCatCol={true}
            hasSelectedTags={false}
            globalStats={false}
            debouncedKeyword=""
            keyword=""
            displayCount={displayCount}
            setDisplayCount={setDisplayCount}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={handleSort}
            showRatingCol={true}
            showGapCol={true}
          />
        </div>
      )}

      <div className="text-center text-sm text-muted-foreground mt-8">
        <Link to="/" className="text-accent hover:underline">Explore the leaderboard</Link>
      </div>
    </div>
    </TooltipProvider>
  );
}
