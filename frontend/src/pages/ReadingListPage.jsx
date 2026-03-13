import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { List, ExternalLink, Copy, Check, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function ReadingListPage() {
  const { listId } = useParams();
  const { user, getAuthHeaders } = useAuth();
  const [list, setList] = useState(null);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [displayCount, setDisplayCount] = useState(50);
  const [sortKey, setSortKey] = useState("");
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    axios.get(`${API}/api/lists/public/${listId}`)
      .then(res => { setList(res.data.list); setPapers(res.data.papers || []); })
      .catch(() => setList(null))
      .finally(() => setLoading(false));
  }, [listId]);

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir(key === "title" ? "asc" : "desc"); }
  };

  const copyLink = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  const forkList = async () => {
    if (!user) { toast.error("Sign in to copy this list"); return; }
    try {
      const res = await axios.post(`${API}/api/lists/${listId}/fork`, {}, { withCredentials: true, headers: getAuthHeaders() });
      toast.success("List copied to your account!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to copy list");
    }
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
        <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">Browse the leaderboard</Link>
      </div>
    );
  }

  const ranked = papers.map((p, i) => ({ ...p, rank: i + 1, _displayRank: i + 1 }));

  return (
    <TooltipProvider delayDuration={200}>
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-8 md:py-10">
      <div className="mb-6">
        <div className="flex items-start justify-between gap-4 mb-1">
          <div>
            <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight" data-testid="list-title">{list.name}</h1>
            {list.description && <p className="text-sm text-muted-foreground mt-1">{list.description}</p>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={copyLink} data-testid="copy-list-link">
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied!" : "Share"}
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={forkList} data-testid="fork-list-btn">
              <Copy className="h-3.5 w-3.5" /> Copy to my lists
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><User className="h-3 w-3" /> {list.user_name || "Anonymous"}</span>
          <span>{list.paper_count} paper{list.paper_count !== 1 ? "s" : ""}</span>
          {list.created_at && <span>Created {new Date(list.created_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}</span>}
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
