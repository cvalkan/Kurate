import { useState, useEffect, useCallback, useRef } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Search } from "lucide-react";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";

const API = process.env.REACT_APP_BACKEND_URL;

export default function DefiPage() {
  const [papers, setPapers] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sort, setSort] = useState("published");
  const [sortDir, setSortDir] = useState("desc");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [stats, setStats] = useState(null);
  const [subset, setSubset] = useState("all");
  const offsetRef = useRef(0);
  const limit = 50;

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Map backend sort keys to API params
  const sortMap = { published: "date", title: "title", comparisons: "citations" };
  const apiSort = sortMap[sort] || "date";

  const load = useCallback(async (append = false) => {
    if (append) setLoadingMore(true); else setLoading(true);
    const off = append ? offsetRef.current : 0;
    try {
      const r = await axios.get(`${API}/api/defi/papers`, {
        params: { sort: apiSort, dir: sortDir, limit, offset: off, search: debouncedSearch, subset },
      });
      const newPapers = (r.data.papers || []).map((p, i) => ({
        // Map to LeaderboardTable's expected shape
        id: p.doi || p.openalex_id || `defi-${off + i}`,
        title: p.title,
        authors: p.authors,
        published: p.publication_date,
        score: null,
        win_rate: null,
        comparisons: null,
        wilson_margin: null,
        ci: null,
        gap_score: null,
        ts_score: null,
        arxiv_id: p.arxiv_id || null,
        link: p.url,
        ai_rating: null,
        // DeFi-specific
        cited_by_count: p.cited_by_count,
        pdf_url: p.pdf_url,
        _displayRank: off + i + 1,
      }));
      if (append) {
        setPapers(prev => [...prev, ...newPapers]);
      } else {
        setPapers(newPapers);
      }
      setTotal(r.data.total || 0);
      offsetRef.current = off + newPapers.length;
    } catch { }
    finally { setLoading(false); setLoadingMore(false); }
  }, [apiSort, sortDir, debouncedSearch, subset]);

  useEffect(() => { offsetRef.current = 0; load(false); }, [load]);

  useEffect(() => {
    axios.get(`${API}/api/defi/stats`).then(r => setStats(r.data)).catch(() => {});
  }, []);

  const handleSort = (key, dir) => {
    // Map LeaderboardTable sort keys to our API
    setSort(key);
    setSortDir(dir);
  };

  const loadMore = () => {
    if (offsetRef.current < total) load(true);
  };

  return (
    <TooltipProvider>
      <Helmet>
        <title>DeFi Paper Rankings | Kurate.org</title>
        <meta name="description" content="AI-ranked decentralized finance, cryptocurrency, and blockchain research papers" />
      </Helmet>

      <div className="container mx-auto px-4 max-w-6xl py-6 md:py-10">
        <div className="mb-4">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
            DeFi & Crypto Research
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {total.toLocaleString()} papers on decentralized finance, cryptocurrency, and blockchain
          </p>
        </div>

        {/* Subset toggle */}
        <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit mb-4">
          <button onClick={() => setSubset("all")}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
              subset === "all" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`} data-testid="subset-all">
            All DeFi ({stats?.total?.toLocaleString() || "..."})
          </button>
          <button onClick={() => setSubset("ai")}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
              subset === "ai" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`} data-testid="subset-ai">
            AI & DeFi ({stats?.ai_count?.toLocaleString() || "..."})
          </button>
        </div>

        {/* Stats */}
        {stats && (
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-4">
            {Object.entries(stats.by_year || {}).sort((a,b) => b[0].localeCompare(a[0])).map(([year, count]) => (
              <span key={year}>{year}: {count}</span>
            ))}
          </div>
        )}

        {/* Search */}
        <div className="flex items-center gap-3 mb-4">
          <div className="relative w-64">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search title, author, keyword..."
              className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-accent"
              data-testid="defi-search" />
          </div>
        </div>

        {/* Reuse LeaderboardTable */}
        <LeaderboardTable
          leaderboard={papers}
          loading={loading}
          showCatCol={false}
          hasSelectedTags={false}
          globalStats={null}
          debouncedKeyword={debouncedSearch}
          keyword={search}
          onLoadMore={loadMore}
          hasMore={offsetRef.current < total}
          loadingMore={loadingMore}
          sortKey={sort}
          sortDir={sortDir}
          onSort={handleSort}
          showRatingCol={false}
          showGapCol={false}
          scoringMethod="wr"
          isArchive={false}
        />
      </div>
    </TooltipProvider>
  );
}
