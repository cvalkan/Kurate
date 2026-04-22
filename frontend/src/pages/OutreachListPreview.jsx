import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import {
  ArrowLeft, Twitter, Heart, Repeat2, UserPlus, UserCheck,
  MessageSquare, ExternalLink, RefreshCw, Search,
} from "lucide-react";
import { Button } from "../components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

const CONFIDENCE_COLORS = {
  high: "bg-green-100 text-green-800 border-green-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-600 border-gray-200",
};
const CONFIDENCE_DOT = {
  high: "bg-green-500",
  medium: "bg-amber-500",
  low: "bg-gray-400",
};
const MEDAL = ["🥇", "🥈", "🥉"];

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

export default function OutreachListPreview() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState("monthly:2026-3");
  const [periods, setPeriods] = useState({ weekly: [], monthly: [] });
  const [variant, setVariant] = useState("L1");
  const [query, setQuery] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/admin/outreach/confidence-preview`, {
        params: { period, top_n: 3 }, headers: getAdminHeaders(),
      });
      setData(r.data);
    } catch (e) {
      toast.error(`Load failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    axios.get(`${API}/api/admin/outreach/archive-periods`, { headers: getAdminHeaders() })
      .then(r => setPeriods(r.data)).catch(() => {});
  }, []);

  useEffect(() => { load(); /* eslint-disable-line */ }, [period]);

  const categories = data?.categories || [];

  // Build flat list: each candidate becomes one row, annotated with paper + medal
  const flatRows = useMemo(() => {
    const rows = [];
    for (const cat of categories) {
      (cat.papers || []).forEach((p, i) => {
        const medal = MEDAL[i] || `#${i + 1}`;
        const cands = p.candidates || [];
        if (cands.length === 0) {
          rows.push({ paper: p, medal, category: cat.category, catName: cat.name, candidate: null });
        } else {
          for (const c of cands) {
            rows.push({ paper: p, medal, category: cat.category, catName: cat.name, candidate: c });
          }
        }
      });
    }
    if (!query.trim()) return rows;
    const q = query.toLowerCase();
    return rows.filter(r =>
      (r.paper.title || "").toLowerCase().includes(q) ||
      (r.candidate?.handle || "").toLowerCase().includes(q) ||
      (r.candidate?.name || "").toLowerCase().includes(q) ||
      (r.category || "").toLowerCase().includes(q)
    );
  }, [categories, query]);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5 sm:py-6">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-4">
          <Link to="/admin/outreach" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> Back to Outreach
          </Link>
          <Button onClick={load} disabled={loading} size="sm" variant="outline" className="gap-1.5 text-xs h-8">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>

        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Outreach — Leaderboard-style List View</h1>
        <p className="text-sm text-muted-foreground mt-1 mb-4">
          Same data, rendered in the live leaderboard's grid layout. Shows both the old and new confidence scores
          (<span className="text-muted-foreground">V1 / V2</span>) so you can see how P0+P1 changes the triage.
        </p>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-5">
          <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
            {["L1", "L2"].map(v => (
              <button key={v} onClick={() => setVariant(v)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
                  variant === v ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {v === "L1" ? "Flat (one row per candidate)" : "Paper-grouped"}
              </button>
            ))}
          </div>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}
            className="h-8 px-2 text-xs border rounded-md bg-background"
          >
            {periods.monthly?.map(p => <option key={`m-${p.value}`} value={`monthly:${p.value}`}>{p.label}</option>)}
            {periods.weekly?.map(p => <option key={`w-${p.value}`} value={`weekly:${p.value}`}>{p.label}</option>)}
          </select>
          <div className="relative flex-1 sm:flex-none sm:min-w-[240px]">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter by paper, handle…"
              className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div className="text-[11px] text-muted-foreground sm:ml-auto">
            {flatRows.length} row{flatRows.length === 1 ? "" : "s"}
          </div>
        </div>

        {loading && !data ? (
          <div className="space-y-2">
            {[...Array(8)].map((_, i) => <div key={i} className="h-12 bg-secondary/30 rounded-lg animate-pulse" />)}
          </div>
        ) : variant === "L1" ? (
          <FlatListView rows={flatRows} />
        ) : (
          <PaperGroupedView categories={categories} query={query} />
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Variant L1 — Flat: one row per candidate, leaderboard-style grid
// Columns: # · Paper · @handle · V1→V2 · ❤ · 🔁 · Actions
// ============================================================================
function FlatListView({ rows }) {
  const { isMobile, isTablet } = useBreakpoints();

  // Grid sizes mirror LeaderboardTable
  const cols = ["2rem", "1fr"];           // # + Paper/title
  cols.push(isMobile ? "7rem" : "9rem");  // @handle
  cols.push(isMobile ? "4.5rem" : "6rem"); // V1→V2
  if (!isMobile) cols.push("3.5rem");     // ❤
  if (!isMobile && !isTablet) cols.push("3.5rem"); // 🔁
  cols.push(isMobile ? "3rem" : "7.5rem"); // Actions
  const gridStyle = { gridTemplateColumns: cols.join(" ") };
  const base = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

  if (rows.length === 0) {
    return <div className="text-center py-16 text-muted-foreground text-sm border rounded-lg">Nothing to show.</div>;
  }

  return (
    <div className="border border-border rounded-lg overflow-x-auto" data-testid="list-preview-L1">
      <div className={`${base} py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border select-none`} style={gridStyle}>
        <div>#</div>
        <div>Paper</div>
        <div>Handle</div>
        <div className="text-right">V1 → V2</div>
        {!isMobile && <div className="text-right">❤</div>}
        {!isMobile && !isTablet && <div className="text-right">🔁</div>}
        <div className="text-right">Actions</div>
      </div>
      {rows.map((r, idx) => (
        <FlatRow key={`${r.paper.id}-${r.candidate?.handle || "empty"}-${idx}`} row={r} idx={idx} gridStyle={gridStyle} base={base} isMobile={isMobile} isTablet={isTablet} />
      ))}
    </div>
  );
}

function FlatRow({ row, idx, gridStyle, base, isMobile, isTablet }) {
  const { paper, medal, candidate: c } = row;
  const v1 = c?.confidence_v1;
  const v2 = c?.confidence_v2;
  const changed = v1 && v2 && v1 !== v2;

  return (
    <div className={`${base} py-2 sm:py-2.5 items-center border-b border-border/50 last:border-0 hover:bg-secondary/30 transition-colors`} style={gridStyle}
      data-testid={`list-row-${idx}`}
    >
      <div className="text-base sm:text-lg" title={`#${idx + 1}`}>{medal}</div>
      <div className="min-w-0">
        <p className="text-[12px] sm:text-[13px] font-medium truncate leading-tight" title={paper.title}>
          {paper.title}
        </p>
        <p className="text-[10px] sm:text-[11px] text-muted-foreground truncate mt-0.5">
          {(paper.authors || []).slice(0, 2).join(", ")}
          {(paper.authors || []).length > 2 && ` +${paper.authors.length - 2}`}
          {paper.arxiv_id && <span className="ml-2 text-accent">{paper.arxiv_id}</span>}
        </p>
      </div>
      <div className="min-w-0">
        {c ? (
          <a href={`https://x.com/${c.handle}`} target="_blank" rel="noopener noreferrer"
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] font-medium shrink-0 max-w-full truncate ${CONFIDENCE_COLORS[c.confidence] || CONFIDENCE_COLORS.low} hover:opacity-80`}
          >
            <Twitter className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">@{c.handle}</span>
          </a>
        ) : (
          <span className="text-[10px] text-muted-foreground italic">—</span>
        )}
      </div>
      <div className="text-[10px] flex items-center justify-end gap-1">
        {c ? (
          <>
            <ConfDot conf={v1} />
            <span className={changed ? "text-muted-foreground line-through" : "text-muted-foreground"}>{v1}</span>
            <span className="text-muted-foreground/40">→</span>
            <ConfDot conf={v2} />
            <span className={changed ? "font-semibold text-foreground" : "text-muted-foreground"}>{v2}</span>
          </>
        ) : <span className="text-muted-foreground">—</span>}
      </div>
      {!isMobile && (
        <div className="text-right text-[11px] text-muted-foreground tabular-nums">
          {c?.tweet_likes ?? "—"}
        </div>
      )}
      {!isMobile && !isTablet && (
        <div className="text-right text-[11px] text-muted-foreground tabular-nums">
          {c?.tweet_retweets ?? "—"}
        </div>
      )}
      <div className="flex items-center justify-end gap-1">
        {c?.tweet_url && (
          <a href={c.tweet_url} target="_blank" rel="noopener noreferrer" title="Open tweet"
            className="h-6 w-6 rounded border border-border text-muted-foreground hover:text-foreground flex items-center justify-center"
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
        {!isMobile && c?.tweet_url && (
          <>
            <IconBadge icon={Heart} active={c.liked} activeCls="border-pink-500 bg-pink-50 text-pink-600" title={c.liked ? "Liked" : "Not liked"} fill={c.liked} />
            <IconBadge icon={c.followed ? UserCheck : UserPlus} active={c.followed} activeCls="border-indigo-500 bg-indigo-50 text-indigo-700" title={c.followed ? "Following" : "Not followed"} />
            <IconBadge icon={Twitter} active={c.quote_tweeted} activeCls="border-blue-500 bg-blue-50 text-blue-700" title={c.quote_tweeted ? "QT'd" : "Not QT'd"} fill={c.quote_tweeted} />
            <IconBadge icon={MessageSquare} active={false} title="Draft Quote (visual only on preview)" />
          </>
        )}
      </div>
    </div>
  );
}

function ConfDot({ conf }) {
  if (!conf) return null;
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${CONFIDENCE_DOT[conf] || CONFIDENCE_DOT.low}`} />;
}

function IconBadge({ icon: Icon, active, activeCls, title, fill }) {
  return (
    <span
      className={`h-6 w-6 rounded border flex items-center justify-center ${active ? activeCls : "border-border text-muted-foreground/70"}`}
      title={title}
    >
      <Icon className={`h-3 w-3 ${fill ? "fill-current" : ""}`} />
    </span>
  );
}

// ============================================================================
// Variant L2 — Paper-grouped (closer to live leaderboard: one row per paper)
// Columns: # · Paper · Rating · Handles (stacked pills with V1→V2 chips)
// ============================================================================
function PaperGroupedView({ categories, query }) {
  const { isMobile, isTablet } = useBreakpoints();
  const cols = ["2rem", "1fr"];
  if (!isMobile) cols.push("3.5rem");     // Rating
  if (!isMobile && !isTablet) cols.push("3rem");  // Tweets count
  cols.push("1fr");                        // Handles
  const gridStyle = { gridTemplateColumns: cols.join(" ") };
  const base = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

  const q = query.trim().toLowerCase();
  const filtered = q ? categories.map(cat => ({
    ...cat,
    papers: (cat.papers || []).filter(p =>
      (p.title || "").toLowerCase().includes(q) ||
      (p.authors || []).some(a => a.toLowerCase().includes(q)) ||
      (p.candidates || []).some(c => (c.handle || "").toLowerCase().includes(q))
    ),
  })).filter(c => c.papers.length > 0) : categories;

  if (filtered.length === 0) {
    return <div className="text-center py-16 text-muted-foreground text-sm border rounded-lg">No matches.</div>;
  }

  return (
    <div className="space-y-4" data-testid="list-preview-L2">
      {filtered.map(cat => (
        <div key={cat.category} className="border rounded-lg overflow-x-auto">
          <div className="bg-muted/30 px-3 sm:px-4 py-2 border-b flex items-baseline gap-2">
            <span className="font-semibold text-sm">{cat.name || cat.category}</span>
            <span className="text-[10px] sm:text-xs text-muted-foreground">{cat.category}</span>
            {cat.label && <span className="ml-auto text-[10px] text-muted-foreground">{cat.label}</span>}
          </div>
          <div className={`${base} py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border`} style={gridStyle}>
            <div>#</div>
            <div>Paper</div>
            {!isMobile && <div className="text-right">Rating</div>}
            {!isMobile && !isTablet && <div className="text-right">Tweets</div>}
            <div>Handles</div>
          </div>
          {(cat.papers || []).map((p, i) => (
            <div key={p.id} className={`${base} py-2 sm:py-3 items-start border-b border-border/50 last:border-0 hover:bg-secondary/30 transition-colors`} style={gridStyle}>
              <div className="text-base sm:text-lg">{MEDAL[i] || `#${i + 1}`}</div>
              <div className="min-w-0">
                <p className="text-[12px] sm:text-[13px] font-medium leading-tight">{p.title}</p>
                <p className="text-[10px] sm:text-[11px] text-muted-foreground truncate mt-0.5">
                  {(p.authors || []).slice(0, 3).join(", ")}
                  {(p.authors || []).length > 3 && " et al."}
                  {p.arxiv_id && <span className="ml-2 text-accent">{p.arxiv_id}</span>}
                </p>
              </div>
              {!isMobile && (
                <div className="text-right text-[12px] tabular-nums font-mono text-muted-foreground pt-0.5">{p.ai_rating ?? "—"}</div>
              )}
              {!isMobile && !isTablet && (
                <div className="text-right text-[11px] tabular-nums text-muted-foreground pt-0.5">{p.total_tweets ?? 0}</div>
              )}
              <div className="min-w-0 space-y-1">
                {(p.candidates || []).length === 0 && (
                  <span className="text-[11px] text-muted-foreground italic">{p.discovered ? "No tweets" : "—"}</span>
                )}
                {(p.candidates || []).slice(0, 3).map(c => (
                  <div key={c.handle} className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <a href={`https://x.com/${c.handle}`} target="_blank" rel="noopener noreferrer"
                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border font-medium shrink-0 ${CONFIDENCE_COLORS[c.confidence_v2] || CONFIDENCE_COLORS.low} hover:opacity-80`}
                    >
                      <Twitter className="h-2.5 w-2.5" />@{c.handle}
                    </a>
                    <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground" title={`V1=${c.confidence_v1} → V2=${c.confidence_v2}`}>
                      <ConfDot conf={c.confidence_v1} />
                      <span className={c.confidence_v1 === c.confidence_v2 ? "" : "line-through opacity-60"}>{c.confidence_v1}</span>
                      <span className="opacity-40">→</span>
                      <ConfDot conf={c.confidence_v2} />
                      <span className={c.confidence_v1 === c.confidence_v2 ? "" : "font-semibold text-foreground"}>{c.confidence_v2}</span>
                    </span>
                    <span className="text-[10px] text-muted-foreground inline-flex items-center gap-0.5">
                      <Heart className="h-2.5 w-2.5" /> {c.tweet_likes ?? 0}
                    </span>
                    <span className="text-[10px] text-muted-foreground inline-flex items-center gap-0.5">
                      <Repeat2 className="h-2.5 w-2.5" /> {c.tweet_retweets ?? 0}
                    </span>
                    {c.tweet_url && (
                      <a href={c.tweet_url} target="_blank" rel="noopener noreferrer"
                        className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
                      >
                        <ExternalLink className="h-2.5 w-2.5" /> tweet
                      </a>
                    )}
                    {c.signals_v2?.reasons?.length > 0 && (
                      <span className="text-[9px] text-muted-foreground/70" title={c.signals_v2.reasons.join(", ")}>
                        · {c.signals_v2.reasons.slice(0, 2).join("+")}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
