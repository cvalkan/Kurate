import { useState, useEffect, useCallback, useRef } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Search, FileText, ExternalLink } from "lucide-react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BookmarkButton } from "@/components/BookmarkButton";
import { useBookmarks } from "@/contexts/BookmarkContext";

const API = process.env.REACT_APP_BACKEND_URL;

export default function DefiPage() {
  const [papers, setPapers] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sort, setSort] = useState("ai_rating");
  const [sortDir, setSortDir] = useState("desc");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [stats, setStats] = useState(null);
  const [group, setGroup] = useState("blockchain_ai_agents");
  const offsetRef = useRef(0);
  const sentinelRef = useRef(null);
  const limit = 50;
  const { bookmarkedIds, toggleBookmark } = useBookmarks();

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const sortMap = { published: "date", title: "title", ai_rating: "ai_rating" };
  const apiSort = sortMap[sort] || "ai_rating";

  const load = useCallback(async (append = false) => {
    if (append) setLoadingMore(true); else setLoading(true);
    const off = append ? offsetRef.current : 0;
    try {
      const r = await axios.get(`${API}/api/defi/papers`, {
        params: { sort: apiSort, dir: sortDir, limit, offset: off, search: debouncedSearch, group },
      });
      const newPapers = (r.data.papers || []).map((p, i) => ({
        id: p.paper_id || p.doi || p.openalex_id || `defi-${off + i}`,
        title: p.title,
        authors: p.authors,
        published: p.publication_date,
        ai_rating: p.ai_rating || null,
        cited_by_count: p.cited_by_count,
        pdf_url: p.pdf_url,
        url: p.url,
        doi: p.doi,
        link: p.paper_id ? `/paper/${p.paper_id}` : (p.pdf_url || p.url || (p.doi ? `https://doi.org/${p.doi}` : null)),
        _external: !p.paper_id,
        _rank: off + i + 1,
      }));
      if (append) {
        setPapers(prev => {
          const ids = new Set(prev.map(p => p.id));
          return [...prev, ...newPapers.filter(p => !ids.has(p.id))];
        });
      } else {
        setPapers(newPapers);
      }
      setTotal(r.data.total || 0);
      offsetRef.current = off + newPapers.length;
    } catch {}
    finally { setLoading(false); setLoadingMore(false); }
  }, [apiSort, sortDir, debouncedSearch, group]);

  useEffect(() => { offsetRef.current = 0; load(false); }, [load]);
  useEffect(() => {
    axios.get(`${API}/api/defi/stats`).then(r => setStats(r.data)).catch(() => {});
  }, []);

  // Infinite scroll
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && offsetRef.current < total && !loadingMore) load(true);
    }, { rootMargin: "400px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [total, loadingMore, load]);

  const handleSort = (key) => {
    if (sort === key) {
      setSortDir(d => d === "desc" ? "asc" : "desc");
    } else {
      setSort(key);
      setSortDir(key === "title" ? "asc" : "desc");
    }
  };

  const SortBtn = ({ label, sortKey, className }) => (
    <button onClick={() => handleSort(sortKey)}
      className={`inline-flex items-center gap-0.5 hover:text-foreground transition-colors text-[10px] font-medium ${sort === sortKey ? "text-foreground" : "text-muted-foreground"} ${className || ""}`}>
      {label}
      {sort === sortKey && <span className="text-[9px]">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>}
    </button>
  );

  return (
    <TooltipProvider>
      <Helmet>
        <title>Blockchain & AI Agents | Kurate.org</title>
        <meta name="description" content="AI-ranked blockchain and AI agent research papers" />
      </Helmet>

      <div className="container mx-auto px-4 max-w-5xl py-6 md:py-10">
        <div className="mb-5">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
            Blockchain & AI Agents
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {total.toLocaleString()} papers on AI agents, autonomous systems, and blockchain
          </p>
        </div>

        {/* Controls row */}
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
            <button onClick={() => setGroup("blockchain_ai_agents")}
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                group === "blockchain_ai_agents" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`} data-testid="group-agents">
              AI Agents ({stats?.agent_count?.toLocaleString() || "..."})
            </button>
            <button onClick={() => setGroup("")}
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                group === "" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`} data-testid="group-all">
              All Papers ({stats?.total?.toLocaleString() || "..."})
            </button>
          </div>
          <div className="relative">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search..."
              className="h-8 pl-8 pr-3 text-xs border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-accent w-48"
              data-testid="defi-search" />
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div className="space-y-3">{[...Array(8)].map((_, i) => <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />)}</div>
        ) : papers.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground">
            <FileText className="h-8 w-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">{debouncedSearch ? `No papers matching "${search}"` : "No papers found"}</p>
          </div>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden" data-testid="defi-table">
            {/* Header */}
            <div className="grid gap-2 px-3 py-2 bg-secondary/50 border-b border-border items-center"
              style={{ gridTemplateColumns: "2.5rem 1fr 4rem 5.5rem 1.5rem" }}>
              <SortBtn label="#" sortKey="rank" />
              <SortBtn label="Paper" sortKey="title" />
              <SortBtn label="Rating" sortKey="ai_rating" className="justify-end" />
              <SortBtn label="Published" sortKey="published" className="justify-end" />
              <div />
            </div>
            {/* Rows */}
            {papers.map((p, i) => {
              const Row = p._external ? "a" : "a";
              const href = p.link;
              return (
                <a key={p.id} href={href} target={p._external ? "_blank" : undefined} rel={p._external ? "noopener noreferrer" : undefined}
                  className="grid gap-2 px-3 py-2.5 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer"
                  style={{ gridTemplateColumns: "2.5rem 1fr 4rem 5.5rem 1.5rem" }}
                  data-testid={`defi-row-${i}`}>
                  <div className="text-xs text-muted-foreground font-mono">{p._rank}</div>
                  <div className="min-w-0">
                    <p className="text-xs sm:text-sm font-medium truncate leading-tight flex items-center gap-1.5">
                      {p.title}
                      {p._external && <ExternalLink className="h-3 w-3 text-muted-foreground shrink-0" />}
                    </p>
                    <p className="text-[10px] sm:text-xs text-muted-foreground truncate mt-0.5">
                      {(p.authors || []).slice(0, 3).join(", ")}
                      {(p.authors || []).length > 3 && ` +${p.authors.length - 3}`}
                    </p>
                  </div>
                  <div className="text-right font-mono text-xs font-medium">
                    {p.ai_rating ? (typeof p.ai_rating === "object" ? p.ai_rating.score : p.ai_rating) : <span className="text-muted-foreground">{"\u2014"}</span>}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {p.published ? new Date(p.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "\u2014"}
                  </div>
                  <div onClick={e => { e.preventDefault(); e.stopPropagation(); }}>
                    <BookmarkButton paperId={p.id} bookmarkedIds={bookmarkedIds} onToggle={toggleBookmark} />
                  </div>
                </a>
              );
            })}
          </div>
        )}
        {/* Infinite scroll sentinel */}
        {offsetRef.current < total && <div ref={sentinelRef} className="py-4 text-center text-xs text-muted-foreground">{loadingMore ? "Loading more..." : ""}</div>}
      </div>
    </TooltipProvider>
  );
}
