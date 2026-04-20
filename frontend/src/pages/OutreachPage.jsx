import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Search, ExternalLink, Twitter, RefreshCw, ChevronDown, Users, Trophy, Clock, Calendar } from "lucide-react";
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
        headers: getAdminHeaders(), params: { period: "current", top_n: 3 },
      });
      setMedalists(res.data);
    } catch { }
    finally { setMedalistsLoading(false); }
  }, [authed]);

  useEffect(() => { if (viewMode === "medalists") loadMedalists(); }, [viewMode, loadMedalists]);

  // Discover all medalist handles
  const handleDiscoverMedalists = async () => {
    setDiscoveringMedalists(true);
    try {
      const res = await axios.post(`${API}/api/admin/outreach/discover-medalists`, null, {
        headers: getAdminHeaders(), params: { period: "current", top_n: 3 },
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

function MedalistsView({ medalists, loading, discovering, onDiscover, onRefresh }) {
  if (loading || !medalists) {
    return <div className="text-center py-12 text-muted-foreground">Loading medalists...</div>;
  }

  const cats = medalists.categories || [];
  const totalPapers = medalists.total_papers || 0;
  const totalDiscovered = medalists.total_discovered || 0;

  return (
    <div>
      <div className="flex items-center gap-3 mb-5">
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
                  <MedalistRow key={p.id} paper={p} medal={MEDAL[i] || `#${i+1}`} />
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {cats.length === 0 && (
          <div className="text-center py-12 text-muted-foreground">No medalists found. Rankings may still be loading.</div>
        )}
      </div>
    </div>
  );
}

function MedalistRow({ paper, medal }) {
  const candidates = paper.candidates || [];
  const best = candidates[0];

  return (
    <tr className="border-b last:border-0 hover:bg-muted/10">
      <td className="px-3 py-2 w-8 text-center text-lg align-top pt-2.5">{medal}</td>
      <td className="px-3 py-2 align-top" style={{width: "45%"}}>
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
                <CandidateDetail key={c.handle} candidate={c} />
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

function CandidateDetail({ candidate: c }) {
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
