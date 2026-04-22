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
  return s.slice(0, 16).replace("T", " ");
}

function PaperHeader({ title, authors, arxivId }) {
  return (
    <div className="min-w-0">
      <div className="font-medium text-[13.5px] leading-snug">{title || "(unknown paper)"}</div>
      <div className="text-[11px] text-muted-foreground mt-0.5 flex flex-wrap gap-x-2">
        {authors && authors.length > 0 && (
          <span className="truncate max-w-full">{authors.slice(0, 3).join(", ")}{authors.length > 3 ? " et al." : ""}</span>
        )}
        {arxivId && (
          <a
            href={`https://arxiv.org/abs/${arxivId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent hover:underline shrink-0"
          >
            {arxivId}
          </a>
        )}
      </div>
    </div>
  );
}

function HandlePill({ handle, tone = "blue" }) {
  const cls =
    tone === "pink"
      ? "border-pink-500 bg-pink-50 text-pink-700"
      : "border-blue-500 bg-blue-50 text-blue-700";
  const Icon = tone === "pink" ? Heart : Twitter;
  return (
    <a
      href={`https://x.com/${handle}`}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium hover:opacity-80 transition-opacity shrink-0 ${cls}`}
    >
      <Icon className={`h-3 w-3 ${tone === "pink" ? "fill-pink-500" : ""}`} />
      @{handle}
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

  const shownRows = tab === "quotes" ? filteredQuotes : filteredLikes;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-5 sm:py-6">
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
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-5">
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

        {/* List */}
        {loading && !data ? (
          <div className="text-center py-16 text-muted-foreground text-sm">Loading…</div>
        ) : shownRows.length === 0 ? (
          <div
            className="text-center py-16 text-muted-foreground text-sm border rounded-lg"
            data-testid={tab === "quotes" ? "activity-quotes-empty" : "activity-likes-empty"}
          >
            {query
              ? "No matches for your search."
              : tab === "quotes"
              ? "No quote tweets yet. Post one from the Outreach page to see it here."
              : "No likes yet. Like a tweet from the Outreach page to see it here."}
          </div>
        ) : (
          <div
            className="space-y-2.5"
            data-testid={tab === "quotes" ? "activity-quotes-table" : "activity-likes-table"}
          >
            {tab === "quotes"
              ? shownRows.map((q) => <QuoteCard key={`${q.paper_id}-${q.handle}-${q.quote_tweet_id}`} q={q} />)
              : shownRows.map((l) => <LikeCard key={`${l.paper_id}-${l.tweet_id}`} l={l} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function QuoteCard({ q }) {
  return (
    <div
      className="border rounded-lg p-3 sm:p-4 hover:border-accent/60 transition-colors"
      data-testid={`activity-quote-${q.handle}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start gap-3">
        <div className="flex-1 min-w-0">
          <PaperHeader title={q.paper_title} authors={q.paper_authors} arxivId={q.paper_arxiv_id} />
          {q.draft_text && (
            <div className="text-[11.5px] text-muted-foreground mt-2 italic line-clamp-3 leading-relaxed">
              "{q.draft_text}"
            </div>
          )}
        </div>
        <div className="flex flex-row sm:flex-col sm:items-end gap-2 sm:gap-1.5 sm:shrink-0 sm:min-w-[180px]">
          <HandlePill handle={q.handle} tone="blue" />
          <div className="text-[10.5px] text-muted-foreground">{fmtDate(q.posted_at)}</div>
          {(q.category || q.period_label) && (
            <div className="text-[10px] text-muted-foreground">
              {q.category}{q.rank ? ` · #${q.rank}` : ""}{q.period_label ? ` · ${q.period_label}` : ""}
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 mt-2.5 pt-2.5 border-t text-[11px]">
        {q.quote_tweet_url && (
          <a
            href={q.quote_tweet_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline inline-flex items-center gap-1 font-medium"
          >
            Our quote <ExternalLink className="h-3 w-3" />
          </a>
        )}
        {q.tweet_url && (
          <a
            href={q.tweet_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
          >
            Original <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}

function LikeCard({ l }) {
  return (
    <div
      className="border rounded-lg p-3 sm:p-4 hover:border-pink-400 transition-colors"
      data-testid={`activity-like-${l.handle}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start gap-3">
        <div className="flex-1 min-w-0">
          <PaperHeader title={l.paper_title} authors={l.paper_authors} arxivId={l.paper_arxiv_id} />
        </div>
        <div className="flex flex-row sm:flex-col sm:items-end gap-2 sm:gap-1.5 sm:shrink-0 sm:min-w-[180px]">
          <HandlePill handle={l.handle} tone="pink" />
          <div className="text-[10.5px] text-muted-foreground">{fmtDate(l.liked_at)}</div>
        </div>
      </div>
      {l.tweet_url && (
        <div className="flex items-center gap-3 mt-2.5 pt-2.5 border-t text-[11px]">
          <a
            href={l.tweet_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent hover:underline inline-flex items-center gap-1"
          >
            View tweet <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      )}
    </div>
  );
}
