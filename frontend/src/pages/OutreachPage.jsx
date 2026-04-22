import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Search, ExternalLink, Twitter, RefreshCw, ChevronDown, Users, Trophy, Clock, Calendar, Heart } from "lucide-react";
import { Button } from "../components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

const PERIODS = [
  { id: "all", label: "All Time", icon: Trophy },
  { id: "recent", label: "Most Recent", icon: Clock },
  { id: "7d", label: "Last 7 Days", icon: Calendar },
  { id: "30d", label: "Last 30 Days", icon: Calendar },
];

const CONFIDENCE_COLORS = {
  high: "bg-green-100 text-green-800 border-green-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-600 border-gray-200",
};

function LikeButton({ paperId, candidate, size = "sm" }) {
  const [liked, setLiked] = useState(Boolean(candidate?.liked));
  const [busy, setBusy] = useState(false);
  const tweetUrl = candidate?.tweet_url;

  const handleLike = async (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (!tweetUrl || busy) return;
    const verb = liked ? "Re-like" : "Like";
    if (!window.confirm(`${verb} @${candidate.handle}'s tweet as @kurateorg?`)) return;
    setBusy(true);
    try {
      const res = await axios.post(
        `${API}/api/admin/outreach/like-tweet`,
        { paper_id: paperId, tweet_url: tweetUrl, handle: candidate.handle },
        { headers: getAdminHeaders() }
      );
      setLiked(true);
      if (res.data?.status === "already_liked") {
        toast.message("Already liked earlier");
      } else {
        toast.success(`Liked @${candidate.handle}'s tweet`);
      }
    } catch (err) {
      toast.error(`Like failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!tweetUrl) return null;
  const iconSize = size === "xs" ? "h-2.5 w-2.5" : "h-3 w-3";
  const textSize = size === "xs" ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <button
      onClick={handleLike}
      disabled={busy}
      data-testid={`like-btn-${candidate.handle}`}
      title={liked ? "Already liked — click to like again" : "Like this tweet as @kurateorg"}
      className={`shrink-0 ${textSize} rounded border inline-flex items-center gap-1 transition-colors disabled:opacity-60 ${
        liked
          ? "border-pink-500 bg-pink-50 text-pink-600 hover:bg-pink-100"
          : "border-pink-500 text-pink-600 hover:bg-pink-500 hover:text-white"
      }`}
    >
      <Heart className={`${iconSize} ${liked ? "fill-pink-500" : ""}`} />
      {busy ? "…" : liked ? "Liked" : "Like"}
    </button>
  );
}

function XAuthCard() {
  const [status, setStatus] = useState(null);
  const [open, setOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [verify, setVerify] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/admin/outreach/twitter-auth/status`, { headers: getAdminHeaders() });
      setStatus(r.data);
    } catch (e) {
      /* ignore — shown as not-configured below */
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleSave = async () => {
    const tok = tokenInput.trim();
    if (tok.length < 20) {
      toast.error("auth_token must be 20+ alphanumeric characters");
      return;
    }
    setBusy(true);
    try {
      const r = await axios.post(
        `${API}/api/admin/outreach/twitter-auth`,
        { auth_token: tok, verify },
        { headers: getAdminHeaders() }
      );
      if (verify && !r.data?.verified) {
        toast.warning("Saved without verification");
      } else if (verify) {
        toast.success(`Saved & verified — token ${r.data.masked}`);
      } else {
        toast.success(`Saved — token ${r.data.masked}`);
      }
      setTokenInput("");
      setOpen(false);
      await refresh();
    } catch (e) {
      toast.error(`Failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleClear = async () => {
    if (!window.confirm("Remove DB-stored token and fall back to env TWITTER_AUTH_TOKEN?")) return;
    try {
      await axios.delete(`${API}/api/admin/outreach/twitter-auth`, { headers: getAdminHeaders() });
      toast.success("Cleared — now using env token");
      await refresh();
    } catch (e) {
      toast.error(`Clear failed: ${e.response?.data?.detail || e.message}`);
    }
  };

  const stale = status?.source === "db" && !status?.last_verified_at;
  return (
    <div className="mb-5 border rounded-md px-3 py-2 bg-secondary/30 flex flex-wrap items-center gap-3 text-xs" data-testid="x-auth-card">
      <span className="font-semibold">X Auth</span>
      {status ? (
        <>
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border ${
              status.configured
                ? stale ? "border-amber-500 bg-amber-50 text-amber-700"
                        : "border-green-500 bg-green-50 text-green-700"
                : "border-red-500 bg-red-50 text-red-700"
            }`}
            data-testid="x-auth-status"
          >
            <Twitter className="h-3 w-3" />
            {status.configured ? `${status.source} · ${status.masked}` : "not configured"}
          </span>
          {status.source === "db" && status.updated_at && (
            <span className="text-muted-foreground">updated {status.updated_at.slice(0, 16).replace("T", " ")}</span>
          )}
          {status.source === "db" && status.last_verified_at && (
            <span className="text-green-700">✓ verified {status.last_verified_at.slice(0, 16).replace("T", " ")}</span>
          )}
        </>
      ) : (
        <span className="text-muted-foreground">loading…</span>
      )}
      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={() => setOpen((o) => !o)}
          data-testid="x-auth-update-toggle"
          className="text-[11px] px-2 py-0.5 rounded border border-accent text-accent hover:bg-accent hover:text-background transition-colors"
        >
          {open ? "Cancel" : "Update token"}
        </button>
        {status?.source === "db" && (
          <button onClick={handleClear}
            data-testid="x-auth-clear"
            className="text-[11px] px-2 py-0.5 rounded border border-muted-foreground text-muted-foreground hover:bg-muted transition-colors"
          >
            Revert to env
          </button>
        )}
      </div>
      {open && (
        <div className="w-full mt-2 flex flex-wrap items-center gap-2" data-testid="x-auth-form">
          <input
            type="password"
            autoComplete="off"
            placeholder="Paste auth_token cookie from x.com (40-char hex)"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            className="flex-1 min-w-[280px] text-xs font-mono px-2 py-1 rounded border bg-background"
            data-testid="x-auth-input"
          />
          <label className="inline-flex items-center gap-1 text-[11px] text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />
            Verify via Like+Unlike round-trip
          </label>
          <Button
            size="sm" className="text-xs h-7"
            onClick={handleSave}
            disabled={busy || tokenInput.trim().length < 20}
            data-testid="x-auth-save"
          >
            {busy ? "Saving…" : verify ? "Verify & Save" : "Save"}
          </Button>
          <span className="text-[10px] text-muted-foreground w-full">
            💡 Get this from x.com logged in as @KurateOrg: DevTools → Application → Cookies → <code>auth_token</code>.
            Token is stored server-side only; never logged.
          </span>
        </div>
      )}
    </div>
  );
}

function QTBadge({ candidate }) {
  if (!candidate?.quote_tweeted) return null;
  const url = candidate.quote_tweet_url || (candidate.quote_tweet_id
    ? `https://x.com/KurateOrg/status/${candidate.quote_tweet_id}` : null);
  const when = candidate.quote_tweeted_at?.slice(0, 10) || "";
  return (
    <a
      href={url || "#"}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      data-testid={`qt-badge-${candidate.handle}`}
      title={`Quote-tweeted ${when}${url ? "" : " (url unknown)"}`}
      className="shrink-0 text-[10px] px-1.5 py-0.5 rounded border border-blue-500 bg-blue-50 text-blue-700 inline-flex items-center gap-1 hover:bg-blue-100"
    >
      <Twitter className="h-2.5 w-2.5" />
      QT'd
    </a>
  );
}

export default function OutreachPage() {
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [categories, setCategories] = useState([]);
  const [selectedCat, setSelectedCat] = useState(null); // null = All Categories
  const [period, setPeriod] = useState("all");
  const [topN, setTopN] = useState(10);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [stats, setStats] = useState(null);
  const [archives, setArchives] = useState([]);
  const [selectedArchive, setSelectedArchive] = useState("");
  const [viewMode, setViewMode] = useState("medalists"); // "medalists" | "explorer"
  const [medalists, setMedalists] = useState(null);
  const [medalistsLoading, setMedalistsLoading] = useState(false);
  const [discoveringMedalists, setDiscoveringMedalists] = useState(false);
  const [medalistPeriod, setMedalistPeriod] = useState("current");

  // Auth
  const handleLogin = async () => {
    try {
      const res = await axios.post(`${API}/api/admin/login`, { password });
      if (res.data.token) {
        localStorage.setItem("admin_token", res.data.token);
        sessionStorage.setItem("admin_token", res.data.token);
        setAuthed(true);
      }
    } catch {
      toast.error("Invalid password");
    }
  };

  useEffect(() => {
    const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
    if (token) setAuthed(true);
  }, []);

  // Load categories
  useEffect(() => {
    if (!authed) return;
    axios.get(`${API}/api/categories`).then(r => {
      const cats = r.data.categories || r.data || [];
      setCategories(cats);
    }).catch(() => {});
    // Load stats
    axios.get(`${API}/api/admin/outreach/handle-stats`, { headers: getAdminHeaders() })
      .then(r => setStats(r.data))
      .catch(() => {});
  }, [authed]);

  // Load archives when category changes
  useEffect(() => {
    if (!authed || !selectedCat) return;
    axios.get(`${API}/api/leaderboard/archives?category=${selectedCat}`, { headers: getAdminHeaders() })
      .then(r => {
        const arcs = (r.data.archives || []).filter(a => a.period_type === "weekly");
        setArchives(arcs);
      })
      .catch(() => setArchives([]));
  }, [authed, selectedCat]);

  // Load medalists
  const loadMedalists = useCallback(async () => {
    if (!authed) return;
    setMedalistsLoading(true);
    try {
      const res = await axios.get(`${API}/api/admin/outreach/medalists`, {
        headers: getAdminHeaders(), params: { period: medalistPeriod, top_n: 3 },
      });
      setMedalists(res.data);
    } catch { }
    finally { setMedalistsLoading(false); }
  }, [authed, medalistPeriod]);

  useEffect(() => { if (viewMode === "medalists") loadMedalists(); }, [viewMode, loadMedalists]);

  // Discover all medalist handles
  const handleDiscoverMedalists = async () => {
    setDiscoveringMedalists(true);
    try {
      const res = await axios.post(`${API}/api/admin/outreach/discover-medalists`, null, {
        headers: getAdminHeaders(), params: { period: medalistPeriod, top_n: 3 },
      });
      if (res.data.status === "started") {
        toast.success(res.data.message);
        const poll = setInterval(async () => {
          try {
            const status = await axios.get(`${API}/api/admin/outreach/discover-status`, { headers: getAdminHeaders() });
            if (!status.data.running) {
              clearInterval(poll);
              setDiscoveringMedalists(false);
              loadMedalists();
              toast.success("Medalist discovery complete!");
            } else {
              loadMedalists(); // Refresh incrementally
            }
          } catch { clearInterval(poll); setDiscoveringMedalists(false); }
        }, 4000);
      } else {
        toast.info(res.data.message || "Already running");
        setDiscoveringMedalists(false);
      }
    } catch (e) {
      toast.error(`Failed: ${e.response?.data?.detail || e.message}`);
      setDiscoveringMedalists(false);
    }
  };

  // Load cached discoveries
  const loadDiscoveries = useCallback(async () => {
    if (!authed) return;
    setLoading(true);
    try {
      const p = selectedArchive ? `archive:${selectedArchive}` : period;
      const params = { period: p, top_n: topN };
      if (selectedCat) params.category = selectedCat;
      const res = await axios.get(`${API}/api/admin/outreach/discoveries`, {
        headers: getAdminHeaders(), params,
      });
      setPapers(res.data.papers || []);
    } catch (e) {
      toast.error("Failed to load discoveries");
    } finally {
      setLoading(false);
    }
  }, [authed, selectedCat, period, topN, selectedArchive]);

  useEffect(() => { loadDiscoveries(); }, [loadDiscoveries]);

  // Trigger discovery
  const handleDiscover = async () => {
    setDiscovering(true);
    try {
      const p = selectedArchive ? `archive:${selectedArchive}` : period;
      const body = { period: p, top_n: topN };
      if (selectedCat) body.category = selectedCat;
      const res = await axios.post(`${API}/api/admin/outreach/discover`, body, {
        headers: getAdminHeaders(),
      });
      if (res.data.status === "started") {
        toast.success(res.data.message);
        // Poll for completion and refresh results incrementally
        const poll = setInterval(async () => {
          try {
            const status = await axios.get(`${API}/api/admin/outreach/discover-status`, { headers: getAdminHeaders() });
            if (!status.data.running) {
              clearInterval(poll);
              setDiscovering(false);
              loadDiscoveries();
              axios.get(`${API}/api/admin/outreach/handle-stats`, { headers: getAdminHeaders() })
                .then(r => setStats(r.data)).catch(() => {});
              toast.success("Discovery complete!");
            } else {
              // Refresh results while still running
              loadDiscoveries();
            }
          } catch { clearInterval(poll); setDiscovering(false); }
        }, 4000);
      } else if (res.data.status === "already_running") {
        toast.info(`Already running (${res.data.progress}/${res.data.total})`);
        setDiscovering(false);
      } else {
        toast.info(res.data.message || "No papers found");
        setDiscovering(false);
      }
    } catch (e) {
      toast.error(`Discovery failed: ${e.response?.data?.detail || e.message}`);
      setDiscovering(false);
    }
  };

  if (!authed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-80 space-y-3">
          <h1 className="text-lg font-semibold text-center">X Outreach — Admin</h1>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleLogin()}
            placeholder="Admin password" className="w-full h-9 px-3 text-sm border rounded-md" data-testid="outreach-password" />
          <Button onClick={handleLogin} className="w-full" data-testid="outreach-login-btn">Sign in</Button>
        </div>
      </div>
    );
  }

  const discoveredCount = papers.filter(p => p.discovered).length;
  const totalCandidates = papers.reduce((sum, p) => sum + (p.candidates?.length || 0), 0);
  const highConfidence = papers.reduce((sum, p) => sum + (p.candidates?.filter(c => c.confidence === "high").length || 0), 0);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight" data-testid="outreach-title">X Outreach</h1>
            <p className="text-sm text-muted-foreground mt-1">Discover author handles from top-ranked papers</p>
          </div>
          {stats && (
            <div className="flex gap-4 text-xs text-muted-foreground">
              <span>{stats.total_papers_searched} papers searched</span>
              <span>{stats.papers_with_candidates} with handles</span>
              <span className="text-green-600">{stats.by_confidence?.high?.unique || 0} high-confidence</span>
            </div>
          )}
        </div>

        {/* View toggle */}
        <XAuthCard />
        <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit mb-5">
          <button onClick={() => setViewMode("medalists")}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${viewMode === "medalists" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >
            <Trophy className="h-3.5 w-3.5 inline mr-1" />Medalists
          </button>
          <button onClick={() => setViewMode("explorer")}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${viewMode === "explorer" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >
            <Search className="h-3.5 w-3.5 inline mr-1" />Category Explorer
          </button>
        </div>

        {viewMode === "medalists" ? (
          <MedalistsView
            medalists={medalists}
            loading={medalistsLoading}
            discovering={discoveringMedalists}
            onDiscover={handleDiscoverMedalists}
            onRefresh={loadMedalists}
            period={medalistPeriod}
            setPeriod={setMedalistPeriod}
          />
        ) : (
        <>
        {/* Category tabs */}
        <div className="flex flex-wrap gap-1.5 mb-4" data-testid="outreach-category-tabs">
          <button
            onClick={() => { setSelectedCat(null); setSelectedArchive(""); }}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              !selectedCat ? "bg-foreground text-background" : "bg-secondary/60 text-muted-foreground hover:text-foreground"
            }`}
          >
            All Categories
          </button>
          {categories.map(c => (
            <button key={c.id} onClick={() => { setSelectedCat(c.id); setSelectedArchive(""); }}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                selectedCat === c.id ? "bg-foreground text-background" : "bg-secondary/60 text-muted-foreground hover:text-foreground"
              }`}
            >
              {c.name || c.id}
            </button>
          ))}
        </div>

        {/* Period + controls */}
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
            {PERIODS.map(p => (
              <button key={p.id} onClick={() => { setPeriod(p.id); setSelectedArchive(""); }}
                className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
                  period === p.id && !selectedArchive ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Archive selector */}
          {selectedCat && archives.length > 0 && (
            <select value={selectedArchive} onChange={e => { setSelectedArchive(e.target.value); if (e.target.value) setPeriod(""); }}
              className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="outreach-archive-select"
            >
              <option value="">Weekly Archives...</option>
              {archives.map(a => (
                <option key={`${a.year}-${a.week}`} value={`${a.year}-${a.week}`}>
                  {a.label || `Week ${a.week}, ${a.year}`}
                </option>
              ))}
            </select>
          )}

          {/* Top N */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Top</span>
            <select value={topN} onChange={e => setTopN(Number(e.target.value))}
              className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="outreach-topn"
            >
              {[3, 5, 10, 20, 50].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <span className="text-xs text-muted-foreground">papers</span>
          </div>

          {/* Discover button + progress */}
          <Button onClick={handleDiscover} disabled={discovering} size="sm" className="gap-1.5"
            data-testid="outreach-discover-btn"
          >
            {discovering ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
            {discovering ? `Searching X...` : `Find Handles (top ${topN})`}
          </Button>

          {discovering && (
            <span className="text-xs text-muted-foreground animate-pulse">
              Scanning papers for tweets — results appear as they're found...
            </span>
          )}

          {/* Summary */}
          <div className="ml-auto text-xs text-muted-foreground">
            {papers.length} papers · {discoveredCount} searched · {totalCandidates} handles ({highConfidence} high)
          </div>
        </div>

        {/* Results table */}
        <div className="border rounded-lg overflow-hidden" data-testid="outreach-results">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/30 border-b">
                <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground w-8">#</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground" style={{width: "40%"}}>Paper</th>
                <th className="text-center px-2 py-2 text-xs font-medium text-muted-foreground w-14">Score</th>
                <th className="text-center px-2 py-2 text-xs font-medium text-muted-foreground w-14">Rating</th>
                <th className="text-center px-2 py-2 text-xs font-medium text-muted-foreground w-16">Tweets</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-muted-foreground">X Handles & Tweets</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="text-center py-8 text-muted-foreground">Loading...</td></tr>
              ) : papers.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-8 text-muted-foreground">
                  No papers. Select a category and click "Find Handles".
                </td></tr>
              ) : papers.map((p, i) => (
                <PaperRow key={p.id} paper={p} index={i} />
              ))}
            </tbody>
          </table>
        </div>
        </>
        )}
      </div>
    </div>
  );
}

const MEDAL = ["🥇", "🥈", "🥉"];

function MedalistsView({ medalists, loading, discovering, onDiscover, onRefresh, period, setPeriod }) {
  const [archivePeriods, setArchivePeriods] = useState({ weekly: [], monthly: [] });
  const [archiveType, setArchiveType] = useState("weekly"); // "weekly" | "monthly"

  // Load available archive periods
  useEffect(() => {
    axios.get(`${API}/api/admin/outreach/archive-periods`, { headers: getAdminHeaders() })
      .then(r => {
        setArchivePeriods(r.data);
        // Auto-select the latest weekly archive if no period set
        if (!period && r.data.weekly?.length > 0) {
          setPeriod(`weekly:${r.data.weekly[0].value}`);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line

  if (loading && !medalists) {
    return <div className="text-center py-12 text-muted-foreground">Loading medalists...</div>;
  }

  const cats = medalists?.categories || [];
  const totalPapers = medalists?.total_papers || 0;
  const totalDiscovered = medalists?.total_discovered || 0;
  const archives = archiveType === "weekly" ? archivePeriods.weekly : archivePeriods.monthly;

  return (
    <div>
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        {/* Weekly / Monthly toggle */}
        <div className="flex items-center gap-0.5 p-0.5 bg-secondary/50 rounded-md">
          <button onClick={() => { setArchiveType("weekly"); if (archivePeriods.weekly?.[0]) setPeriod(`weekly:${archivePeriods.weekly[0].value}`); }}
            className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
              archiveType === "weekly" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Calendar className="h-3 w-3 inline mr-1" />Weekly
          </button>
          <button onClick={() => { setArchiveType("monthly"); if (archivePeriods.monthly?.[0]) setPeriod(`monthly:${archivePeriods.monthly[0].value}`); }}
            className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
              archiveType === "monthly" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Calendar className="h-3 w-3 inline mr-1" />Monthly
          </button>
        </div>

        {/* Period dropdown */}
        {archives.length > 0 && (
          <select
            value={period.split(":")[1] || ""}
            onChange={e => e.target.value && setPeriod(`${archiveType}:${e.target.value}`)}
            className="h-8 px-2 text-xs border rounded-md bg-background min-w-[200px]"
          >
            {archives.map(a => (
              <option key={a.value} value={a.value}>
                {a.label} — {a.categories} categories, {a.total_papers} papers
              </option>
            ))}
          </select>
        )}

        <Button onClick={onDiscover} disabled={discovering} size="sm" className="gap-1.5">
          {discovering ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          {discovering ? "Searching..." : "Find All Tweets"}
        </Button>
        {discovering && (
          <span className="text-xs text-muted-foreground animate-pulse">
            Scanning medalists for tweets...
          </span>
        )}
        <div className="ml-auto text-xs text-muted-foreground">
          {totalPapers} medalists across {cats.length} categories · {totalDiscovered} searched
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-muted-foreground">Loading...</div>
      ) : (

      <div className="space-y-4">
        {cats.map(cat => (
          <div key={cat.category} className="border rounded-lg overflow-hidden">
            <div className="bg-muted/30 px-4 py-2 border-b">
              <span className="font-semibold text-sm">{cat.name || cat.category}</span>
              <span className="text-xs text-muted-foreground ml-2">{cat.category}</span>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {cat.papers.map((p, i) => (
                  <MedalistRow key={p.id} paper={p} medal={MEDAL[i] || `#${i+1}`} category={cat.category} periodLabel={cat.label || ""} />
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {cats.length === 0 && !loading && (
          <div className="text-center py-12 text-muted-foreground">No medalists found for this period.</div>
        )}
      </div>
      )}
    </div>
  );
}

function MedalistRow({ paper, medal, category, periodLabel }) {
  const candidates = paper.candidates || [];
  const best = candidates[0];
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState(null);
  const [editText, setEditText] = useState("");
  const [posting, setPosting] = useState(false);
  // Persist last-posted URL so even after closing/reopening the draft we keep the badge visible
  const [lastPost, setLastPost] = useState(null);

  const handlePost = async () => {
    const existing = draft?.handle
      ? candidates.find((c) => c.handle === draft.handle && c.quote_tweeted)
      : null;
    const verb = existing || lastPost ? "Post ANOTHER quote tweet" : "Post quote tweet";
    if (!window.confirm(`${verb} from @kurateorg with your current edits?`)) return;
    setPosting(true);
    try {
      const res = await axios.post(`${API}/api/admin/outreach/post-tweet`, {
        paper_id: paper.id,
        handle: draft.handle,
        text: editText,
      }, { headers: getAdminHeaders() });
      toast.success("Tweet posted from @kurateorg!");
      setLastPost({
        url: res.data?.url || null,
        posted_at: res.data?.posted_at || new Date().toISOString(),
        quote_tweet_id: res.data?.quote_tweet_id || null,
      });
      // Reflect posted state on the candidate so sibling UI (QTBadge) updates immediately
      const c = candidates.find((x) => x.handle === draft.handle);
      if (c) {
        c.quote_tweeted = true;
        c.quote_tweet_id = res.data?.quote_tweet_id || c.quote_tweet_id;
        c.quote_tweet_url = res.data?.url || c.quote_tweet_url;
        c.quote_tweeted_at = res.data?.posted_at || new Date().toISOString();
      }
    } catch (e) {
      toast.error(`Post failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setPosting(false);
    }
  };


  const handleDraft = async (candidate) => {
    setDrafting(true);
    try {
      const res = await axios.post(`${API}/api/admin/outreach/draft-tweet`, {
        paper_id: paper.id,
        tweet_url: candidate.tweet_url,
        handle: candidate.handle,
        category: category,
        rank: parseInt(medal === "🥇" ? 1 : medal === "🥈" ? 2 : medal === "🥉" ? 3 : 0),
        period_label: periodLabel || "",
      }, { headers: getAdminHeaders() });
      setDraft(res.data);
      setEditText(res.data.draft_text);
      // Carry forward any already-known QT state for this candidate
      if (candidate.quote_tweeted) {
        setLastPost({
          url: candidate.quote_tweet_url,
          posted_at: candidate.quote_tweeted_at,
          quote_tweet_id: candidate.quote_tweet_id,
        });
      } else {
        setLastPost(null);
      }
    } catch (e) {
      toast.error("Failed to generate draft");
    } finally {
      setDrafting(false);
    }
  };

  return (
    <>
      <tr className="border-b last:border-0 hover:bg-muted/10">
        <td className="px-3 py-2 w-8 text-center text-lg align-top pt-2.5">{medal}</td>
        <td className="px-3 py-2 align-top" style={{width: "40%"}}>
          <div className="font-medium text-[13px] leading-snug">{paper.title}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">
            {(paper.authors || []).slice(0, 3).join(", ")}
            {paper.arxiv_id && (
              <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer"
                className="ml-2 text-accent hover:underline"
              >{paper.arxiv_id}</a>
            )}
          </div>
        </td>
        <td className="px-2 py-2 text-xs font-mono text-center align-top pt-3 w-14">{paper.ai_rating || "—"}</td>
        <td className="px-3 py-2 align-top">
          {candidates.length > 0 ? (
            <div className="space-y-1">
              {candidates.slice(0, 2).map(c => (
                <div key={c.handle} className="flex items-center gap-2 text-[11px]">
                  <a href={`https://x.com/${c.handle}`} target="_blank" rel="noopener noreferrer"
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border font-medium shrink-0 ${CONFIDENCE_COLORS[c.confidence]} hover:opacity-80`}
                  >
                    <Twitter className="h-2.5 w-2.5" />@{c.handle}
                  </a>
                  {c.tweet_url && (
                    <a href={c.tweet_url} target="_blank" rel="noopener noreferrer"
                      className={`truncate flex items-center gap-1 ${
                        (c.tweet_likes > 0 || c.tweet_retweets > 0) ? "text-blue-600" : "text-muted-foreground"
                      } hover:text-foreground`}
                      title={c.tweet_text}
                    >
                      <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                      <span className="truncate">{c.tweet_text?.slice(0, 50)}{c.tweet_text?.length > 50 ? "..." : ""}</span>
                    </a>
                  )}
                  {c.tweet_url && (
                    <>
                      <LikeButton paperId={paper.id} candidate={c} size="xs" />
                      <QTBadge candidate={c} />
                      <button onClick={() => handleDraft(c)} disabled={drafting}
                        className="shrink-0 text-[10px] px-1.5 py-0.5 rounded border border-accent text-accent hover:bg-accent hover:text-background transition-colors disabled:opacity-50"
                      >
                        {drafting ? "..." : c.quote_tweeted ? "Draft again" : "Draft Quote"}
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>
          ) : paper.discovered ? (
            <span className="text-[10px] text-muted-foreground italic">No tweets found</span>
          ) : (
            <span className="text-[10px] text-gray-400">—</span>
          )}
        </td>
      </tr>
      {draft && (
        <tr className="bg-accent/5">
          <td colSpan={4} className="px-6 py-3">
            <div className="max-w-2xl">
              <div className="flex items-center gap-2 mb-2">
                <Twitter className="h-4 w-4 text-accent" />
                <span className="text-xs font-semibold">Quote Tweet Draft</span>
                <span className="text-[10px] text-muted-foreground">quoting @{draft.handle}</span>
                <a href={draft.tweet_url} target="_blank" rel="noopener noreferrer"
                  className="text-[10px] text-accent hover:underline flex items-center gap-0.5 ml-auto"
                >
                  Original tweet <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </div>
              <textarea
                value={editText}
                onChange={e => setEditText(e.target.value)}
                rows={4}
                className="w-full text-sm border rounded-md p-2.5 bg-background resize-none focus:outline-none focus:ring-1 focus:ring-accent"
                data-testid="draft-textarea"
              />
              <div className="flex items-center justify-between mt-2">
                <span className={`text-[10px] ${editText.length > 280 ? "text-red-500 font-semibold" : "text-muted-foreground"}`}>
                  {editText.length} / 280 chars
                </span>
                <div className="flex items-center gap-2">
                  {lastPost && (
                    <a
                      href={lastPost.url || "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[10px] text-blue-700 hover:underline flex items-center gap-1"
                      data-testid="last-post-link"
                      title={`Posted ${lastPost.posted_at}`}
                    >
                      <Twitter className="h-3 w-3" />
                      Posted — open quote tweet
                    </a>
                  )}
                  <button onClick={() => setDraft(null)}
                    className="text-xs text-muted-foreground hover:text-foreground"
                  >Close</button>
                  <Button
                    onClick={handlePost}
                    disabled={posting || editText.length > 280}
                    size="sm"
                    className="text-xs h-7 gap-1"
                    data-testid="post-tweet-btn"
                  >
                    <Twitter className="h-3 w-3" />
                    {posting ? "Posting..." : lastPost ? "Post again" : "Reply from @kurateorg"}
                  </Button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function PaperRow({ paper, index }) {
  const [expanded, setExpanded] = useState(false);
  const candidates = paper.candidates || [];
  // Show up to 3 handles inline, sorted by confidence
  const shown = candidates.slice(0, 3);
  const hasMore = candidates.length > 3;

  return (
    <>
      <tr className="border-b hover:bg-muted/10 cursor-pointer" onClick={() => candidates.length > 0 && setExpanded(!expanded)}
        data-testid={`outreach-paper-${paper.id?.slice(0, 8)}`}
      >
        <td className="px-3 py-2 text-xs text-muted-foreground align-top pt-3">{index + 1}</td>
        <td className="px-3 py-2 align-top" style={{width: "40%"}}>
          <div className="font-medium text-[13px] leading-snug">{paper.title}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">
            {(paper.authors || []).slice(0, 3).join(", ")}
            {paper.arxiv_id && (
              <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer"
                className="ml-2 text-accent hover:underline" onClick={e => e.stopPropagation()}
              >
                {paper.arxiv_id}
              </a>
            )}
          </div>
        </td>
        <td className="px-2 py-2 text-xs font-mono text-center align-top pt-3">{paper.ts_score || "—"}</td>
        <td className="px-2 py-2 text-xs font-mono text-center align-top pt-3">{paper.ai_rating || "—"}</td>
        <td className="px-2 py-2 text-center align-top pt-3">
          {paper.discovered ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">
              {paper.total_tweets}
            </span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-400 border border-gray-200">—</span>
          )}
        </td>
        <td className="px-3 py-2 align-top">
          {shown.length > 0 ? (
            <div className="space-y-1">
              {shown.map(c => (
                <div key={c.handle} className="flex items-center gap-2 text-[11px]">
                  <a href={`https://x.com/${c.handle}`} target="_blank" rel="noopener noreferrer"
                    onClick={e => e.stopPropagation()}
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border font-medium shrink-0 ${CONFIDENCE_COLORS[c.confidence]} hover:opacity-80`}
                  >
                    <Twitter className="h-2.5 w-2.5" />@{c.handle}
                  </a>
                  {c.tweet_url && (
                    <a href={c.tweet_url} target="_blank" rel="noopener noreferrer"
                      onClick={e => e.stopPropagation()}
                      className={`hover:text-foreground truncate flex items-center gap-1 ${
                        (c.tweet_likes > 0 || c.tweet_retweets > 0) ? "text-blue-600" : "text-muted-foreground"
                      }`}
                      title={c.tweet_text}
                    >
                      <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                      <span className="truncate">{c.tweet_text?.slice(0, 60)}{c.tweet_text?.length > 60 ? "..." : ""}</span>
                    </a>
                  )}
                  {c.liked && (
                    <span className="shrink-0 text-[10px] px-1 py-0.5 rounded border border-pink-500 bg-pink-50 text-pink-600 inline-flex items-center gap-0.5"
                      data-testid={`liked-indicator-${c.handle}`}
                      title={`Liked ${c.liked_at?.slice(0, 10) || ""}`}
                    >
                      <Heart className="h-2 w-2 fill-pink-500" />Liked
                    </span>
                  )}
                  <QTBadge candidate={c} />
                </div>
              ))}
              {hasMore && (
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
                  +{candidates.length - 3} more
                </div>
              )}
            </div>
          ) : paper.discovered ? (
            <span className="text-[10px] text-muted-foreground italic">No handles found</span>
          ) : null}
        </td>
      </tr>
      {expanded && candidates.length > 0 && (
        <tr className="bg-muted/5">
          <td colSpan={6} className="px-6 py-3">
            <div className="space-y-2">
              {candidates.map(c => (
                <CandidateDetail key={c.handle} candidate={c} paperId={paper.id} />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function HandleBadge({ candidate }) {
  return (
    <a href={`https://x.com/${candidate.handle}`} target="_blank" rel="noopener noreferrer"
      onClick={e => e.stopPropagation()}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium border ${CONFIDENCE_COLORS[candidate.confidence]} hover:opacity-80 transition-opacity`}
      title={`${candidate.name} (${candidate.confidence} confidence)`}
    >
      <Twitter className="h-2.5 w-2.5" />
      @{candidate.handle}
    </a>
  );
}

function CandidateDetail({ candidate: c, paperId }) {
  return (
    <div className={`flex items-start gap-3 p-2.5 rounded-md border ${CONFIDENCE_COLORS[c.confidence]}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <a href={`https://x.com/${c.handle}`} target="_blank" rel="noopener noreferrer"
            className="font-semibold text-sm hover:underline flex items-center gap-1"
          >
            <Twitter className="h-3 w-3" />
            @{c.handle}
          </a>
          <span className="text-xs text-muted-foreground">{c.name}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-background border">
            {c.followers?.toLocaleString()} followers
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${CONFIDENCE_COLORS[c.confidence]}`}>
            {c.confidence}
          </span>
          {c.matched_author && (
            <span className="text-[10px] text-muted-foreground">
              matches "{c.matched_author}" ({Math.round(c.name_similarity * 100)}%)
            </span>
          )}
          <div className="ml-auto flex items-center gap-1">
            <QTBadge candidate={c} />
            {c.tweet_url && <LikeButton paperId={paperId} candidate={c} size="sm" />}
          </div>
        </div>
        {c.bio && <div className="text-[11px] text-muted-foreground mt-1 truncate">{c.bio}</div>}
        {c.tweet_text && (
          <div className="mt-1.5 text-xs bg-background/50 rounded p-2 border border-border/50">
            <div className="line-clamp-2">{c.tweet_text}</div>
            <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground">
              <span>{c.tweet_likes} likes</span>
              <span>{c.tweet_retweets} RTs</span>
              <a href={c.tweet_url} target="_blank" rel="noopener noreferrer"
                className="text-accent hover:underline flex items-center gap-0.5"
              >
                View tweet <ExternalLink className="h-2.5 w-2.5" />
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
