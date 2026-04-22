import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { ArrowLeft, ExternalLink, Heart, Twitter, RefreshCw } from "lucide-react";
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

function PaperCell({ title, authors, arxivId }) {
  return (
    <div className="min-w-0">
      <div className="font-medium text-[13px] leading-snug truncate">{title || "(unknown paper)"}</div>
      <div className="text-[11px] text-muted-foreground truncate">
        {(authors || []).slice(0, 3).join(", ")}
        {arxivId && (
          <a
            href={`https://arxiv.org/abs/${arxivId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-2 text-accent hover:underline"
          >
            {arxivId}
          </a>
        )}
      </div>
    </div>
  );
}

export default function OutreachActivityPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("quotes"); // "quotes" | "likes"

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

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <Link
              to="/admin/outreach"
              data-testid="activity-back-link"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Back to Outreach
            </Link>
          </div>
          <Button
            onClick={load}
            disabled={loading}
            size="sm"
            variant="outline"
            className="gap-1.5 text-xs h-8"
            data-testid="activity-refresh-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        <h1 className="text-2xl font-bold tracking-tight mb-1" data-testid="activity-title">
          Outreach Activity
        </h1>
        <p className="text-sm text-muted-foreground mb-5">
          Everything @KurateOrg has quoted or liked from discovered handles.
        </p>

        {/* Tabs */}
        <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit mb-5">
          <button
            onClick={() => setTab("quotes")}
            data-testid="activity-tab-quotes"
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
              tab === "quotes" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Twitter className="h-3.5 w-3.5 inline mr-1" />
            Quote Tweets ({quotes.length})
          </button>
          <button
            onClick={() => setTab("likes")}
            data-testid="activity-tab-likes"
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
              tab === "likes" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Heart className="h-3.5 w-3.5 inline mr-1" />
            Likes ({likes.length})
          </button>
        </div>

        {loading && !data ? (
          <div className="text-center py-16 text-muted-foreground text-sm">Loading...</div>
        ) : tab === "quotes" ? (
          <QuotesTable rows={quotes} />
        ) : (
          <LikesTable rows={likes} />
        )}
      </div>
    </div>
  );
}

function QuotesTable({ rows }) {
  if (rows.length === 0) {
    return (
      <div className="text-center py-16 text-muted-foreground text-sm border rounded-lg" data-testid="activity-quotes-empty">
        No quote tweets yet. Post one from the Outreach page to see it here.
      </div>
    );
  }
  return (
    <div className="border rounded-lg overflow-hidden" data-testid="activity-quotes-table">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 border-b">
          <tr>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground" style={{ width: "45%" }}>Paper</th>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground">Quoted @handle</th>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground w-36">Posted</th>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground w-32">Links</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((q) => (
            <tr key={`${q.paper_id}-${q.handle}-${q.quote_tweet_id}`} className="border-b last:border-0 hover:bg-muted/10" data-testid={`activity-quote-${q.handle}`}>
              <td className="px-3 py-2 align-top">
                <PaperCell title={q.paper_title} authors={q.paper_authors} arxivId={q.paper_arxiv_id} />
                {q.draft_text && (
                  <div className="text-[11px] text-muted-foreground mt-1 line-clamp-2 italic">
                    "{q.draft_text}"
                  </div>
                )}
              </td>
              <td className="px-3 py-2 align-top">
                <a
                  href={`https://x.com/${q.handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                >
                  <Twitter className="h-3 w-3" />@{q.handle}
                </a>
                {q.category && (
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    {q.category}{q.rank ? ` · #${q.rank}` : ""}{q.period_label ? ` · ${q.period_label}` : ""}
                  </div>
                )}
              </td>
              <td className="px-3 py-2 align-top text-xs text-muted-foreground">{fmtDate(q.posted_at)}</td>
              <td className="px-3 py-2 align-top">
                <div className="flex flex-col gap-1 text-[11px]">
                  {q.quote_tweet_url && (
                    <a
                      href={q.quote_tweet_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline inline-flex items-center gap-0.5"
                    >
                      Our quote <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  )}
                  {q.tweet_url && (
                    <a
                      href={q.tweet_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
                    >
                      Original <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LikesTable({ rows }) {
  if (rows.length === 0) {
    return (
      <div className="text-center py-16 text-muted-foreground text-sm border rounded-lg" data-testid="activity-likes-empty">
        No likes yet. Like a tweet from the Outreach page to see it here.
      </div>
    );
  }
  return (
    <div className="border rounded-lg overflow-hidden" data-testid="activity-likes-table">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 border-b">
          <tr>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground" style={{ width: "55%" }}>Paper</th>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground">Liked @handle</th>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground w-36">Liked at</th>
            <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground w-28">Tweet</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => (
            <tr key={`${l.paper_id}-${l.tweet_id}`} className="border-b last:border-0 hover:bg-muted/10" data-testid={`activity-like-${l.handle}`}>
              <td className="px-3 py-2 align-top">
                <PaperCell title={l.paper_title} authors={l.paper_authors} arxivId={l.paper_arxiv_id} />
              </td>
              <td className="px-3 py-2 align-top">
                <a
                  href={`https://x.com/${l.handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-pink-600 hover:underline"
                >
                  <Heart className="h-3 w-3 fill-pink-500" />@{l.handle}
                </a>
              </td>
              <td className="px-3 py-2 align-top text-xs text-muted-foreground">{fmtDate(l.liked_at)}</td>
              <td className="px-3 py-2 align-top">
                {l.tweet_url && (
                  <a
                    href={l.tweet_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[11px] text-accent hover:underline inline-flex items-center gap-0.5"
                  >
                    View <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
