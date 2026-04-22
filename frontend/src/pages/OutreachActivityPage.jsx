import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { ArrowLeft, ExternalLink, Heart, Twitter, RefreshCw, Search } from "lucide-react";
import { Button } from "../components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s.slice(0, 10);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

function useBreakpoints() {
  const [bp, setBp] = useState({ isMobile: false, isTablet: false });
  useEffect(() => {
    const check = () => setBp({
      isMobile: window.innerWidth < 640,
      isTablet: window.innerWidth < 1024,
    });
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return bp;
}

function HandleBadge({ handle, tone = "blue" }) {
  const cls =
    tone === "pink"
      ? "border-pink-400 bg-pink-50 text-pink-700"
      : "border-blue-400 bg-blue-50 text-blue-700";
  const Icon = tone === "pink" ? Heart : Twitter;
  return (
    <a
      href={`https://x.com/${handle}`}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] font-medium hover:opacity-80 transition-opacity truncate max-w-full ${cls}`}
      title={`@${handle}`}
    >
      <Icon className={`h-2.5 w-2.5 shrink-0 ${tone === "pink" ? "fill-pink-500" : ""}`} />
      <span className="truncate">@{handle}</span>
    </a>
  );
}

export default function OutreachActivityPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("quotes");
  const [query, setQuery] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/admin/outreach/activity`, { headers: getAdminHeaders() });
      setData(r.data);
    } catch (e) {
      toast.error(`Failed to load activity: ${e.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const quotes = data?.quotes || [];
  const likes = data?.likes || [];

  const filterFn = (row) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      (row.paper_title || "").toLowerCase().includes(q) ||
      (row.handle || "").toLowerCase().includes(q) ||
      (row.paper_arxiv_id || "").toLowerCase().includes(q) ||
      (row.paper_authors || []).some((a) => a.toLowerCase().includes(q))
    );
  };
  const filteredQuotes = useMemo(() => quotes.filter(filterFn), [quotes, query]);
  const filteredLikes = useMemo(() => likes.filter(filterFn), [likes, query]);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5 sm:py-6">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-4">
          <Link
            to="/admin/outreach"
            data-testid="activity-back-link"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to Outreach
          </Link>
          <Button
            onClick={load}
            disabled={loading}
            size="sm"
            variant="outline"
            className="gap-1.5 text-xs h-8"
            data-testid="activity-refresh-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>

        {/* Title */}
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight" data-testid="activity-title">
          Outreach Activity
        </h1>
        <p className="text-sm text-muted-foreground mt-1 mb-5">
          Everything @KurateOrg has quoted or liked from discovered handles.
        </p>

        {/* Tabs + search */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
          <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit">
            <button
              onClick={() => setTab("quotes")}
              data-testid="activity-tab-quotes"
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors inline-flex items-center gap-1.5 ${
                tab === "quotes" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Twitter className="h-3.5 w-3.5" />
              Quotes <span className="opacity-60">({filteredQuotes.length})</span>
            </button>
            <button
              onClick={() => setTab("likes")}
              data-testid="activity-tab-likes"
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors inline-flex items-center gap-1.5 ${
                tab === "likes" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Heart className="h-3.5 w-3.5" />
              Likes <span className="opacity-60">({filteredLikes.length})</span>
            </button>
          </div>
          <div className="relative sm:ml-auto w-full sm:w-64">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search paper, handle, author…"
              data-testid="activity-search"
              className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        </div>

        {loading && !data ? (
          <div className="space-y-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-12 bg-secondary/30 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : tab === "quotes" ? (
          <QuotesTable rows={filteredQuotes} query={query} />
        ) : (
          <LikesTable rows={filteredLikes} query={query} />
        )}
      </div>
    </div>
  );
}

const GRID_BASE = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

function QuotesTable({ rows, query }) {
  const { isMobile, isTablet } = useBreakpoints();
  // Columns: #, Paper, @handle, (Cat), (Posted), Link
  const cols = ["2rem", "1fr", isMobile ? "6rem" : "8rem"];
  if (!isMobile && !isTablet) cols.push("5rem");       // Cat · Rank
  if (!isMobile) cols.push("5.5rem");                  // Posted
  cols.push("2.5rem");                                 // Link icon
  const gridStyle = { gridTemplateColumns: cols.join(" ") };

  if (rows.length === 0) {
    return (
      <div
        className="text-center py-16 text-muted-foreground text-sm border border-border rounded-lg"
        data-testid="activity-quotes-empty"
      >
        {query ? "No matches for your search." : "No quote tweets yet. Post one from the Outreach page to see it here."}
      </div>
    );
  }

  return (
    <div className="border border-border rounded-lg overflow-x-auto" data-testid="activity-quotes-table">
      <div
        className={`${GRID_BASE} py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border select-none`}
        style={gridStyle}
      >
        <div>#</div>
        <div>Paper</div>
        <div>Quoted</div>
        {!isMobile && !isTablet && <div>Category</div>}
        {!isMobile && <div className="text-right">Posted</div>}
        <div className="text-right">Tweet</div>
      </div>
      {rows.map((q, i) => (
        <a
          key={`${q.paper_id}-${q.handle}-${q.quote_tweet_id}`}
          href={q.quote_tweet_url || q.tweet_url || "#"}
          target="_blank"
          rel="noopener noreferrer"
          className={`${GRID_BASE} py-2 sm:py-3 items-center border-b border-border/50 last:border-0 hover:bg-secondary/30 transition-colors cursor-pointer`}
          style={gridStyle}
          data-testid={`activity-quote-${q.handle}`}
        >
          <div className="text-xs text-muted-foreground font-mono">{i + 1}</div>
          <div className="min-w-0">
            <p className="text-xs sm:text-sm font-medium truncate leading-tight" title={q.paper_title}>
              {q.paper_title || "(unknown paper)"}
            </p>
            <p className="text-[10px] sm:text-xs text-muted-foreground truncate mt-0.5">
              {(q.paper_authors || []).slice(0, 2).join(", ")}
              {(q.paper_authors || []).length > 2 && ` +${q.paper_authors.length - 2}`}
              {q.paper_arxiv_id && (
                <span className="ml-2 text-accent">{q.paper_arxiv_id}</span>
              )}
            </p>
          </div>
          <div className="min-w-0">
            <HandleBadge handle={q.handle} tone="blue" />
          </div>
          {!isMobile && !isTablet && (
            <div className="text-[11px] text-muted-foreground truncate" title={`${q.category || ""} · #${q.rank || ""} · ${q.period_label || ""}`}>
              {q.category || "—"}
              {q.rank ? <span className="text-muted-foreground/70"> · #{q.rank}</span> : null}
            </div>
          )}
          {!isMobile && (
            <div className="text-right text-[11px] text-muted-foreground">{fmtDate(q.posted_at)}</div>
          )}
          <div className="flex items-center justify-end">
            <ExternalLink className="h-3.5 w-3.5 text-accent" />
          </div>
        </a>
      ))}
    </div>
  );
}

function LikesTable({ rows, query }) {
  const { isMobile } = useBreakpoints();
  const cols = ["2rem", "1fr", isMobile ? "6rem" : "8rem"];
  if (!isMobile) cols.push("5.5rem");
  cols.push("2.5rem");
  const gridStyle = { gridTemplateColumns: cols.join(" ") };

  if (rows.length === 0) {
    return (
      <div
        className="text-center py-16 text-muted-foreground text-sm border border-border rounded-lg"
        data-testid="activity-likes-empty"
      >
        {query ? "No matches for your search." : "No likes yet. Like a tweet from the Outreach page to see it here."}
      </div>
    );
  }

  return (
    <div className="border border-border rounded-lg overflow-x-auto" data-testid="activity-likes-table">
      <div
        className={`${GRID_BASE} py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border select-none`}
        style={gridStyle}
      >
        <div>#</div>
        <div>Paper</div>
        <div>Liked</div>
        {!isMobile && <div className="text-right">Liked at</div>}
        <div className="text-right">Tweet</div>
      </div>
      {rows.map((l, i) => (
        <a
          key={`${l.paper_id}-${l.tweet_id}`}
          href={l.tweet_url || "#"}
          target="_blank"
          rel="noopener noreferrer"
          className={`${GRID_BASE} py-2 sm:py-3 items-center border-b border-border/50 last:border-0 hover:bg-secondary/30 transition-colors cursor-pointer`}
          style={gridStyle}
          data-testid={`activity-like-${l.handle}`}
        >
          <div className="text-xs text-muted-foreground font-mono">{i + 1}</div>
          <div className="min-w-0">
            <p className="text-xs sm:text-sm font-medium truncate leading-tight" title={l.paper_title}>
              {l.paper_title || "(unknown paper)"}
            </p>
            <p className="text-[10px] sm:text-xs text-muted-foreground truncate mt-0.5">
              {(l.paper_authors || []).slice(0, 2).join(", ")}
              {(l.paper_authors || []).length > 2 && ` +${l.paper_authors.length - 2}`}
              {l.paper_arxiv_id && (
                <span className="ml-2 text-accent">{l.paper_arxiv_id}</span>
              )}
            </p>
          </div>
          <div className="min-w-0">
            <HandleBadge handle={l.handle} tone="pink" />
          </div>
          {!isMobile && (
            <div className="text-right text-[11px] text-muted-foreground">{fmtDate(l.liked_at)}</div>
          )}
          <div className="flex items-center justify-end">
            <ExternalLink className="h-3.5 w-3.5 text-accent" />
          </div>
        </a>
      ))}
    </div>
  );
}
