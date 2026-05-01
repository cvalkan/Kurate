import { useState, useEffect, useCallback, useMemo } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Search, ExternalLink, FileText, ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function fmtDate(d) {
  if (!d) return "";
  return d.slice(0, 10);
}

export default function DefiPage() {
  const [papers, setPapers] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState("date");
  const [dir, setDir] = useState("desc");
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [stats, setStats] = useState(null);
  const [subset, setSubset] = useState("all");
  const limit = 50;

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/defi/papers`, {
        params: { sort, dir, limit, offset, search: debouncedSearch, subset },
      });
      setPapers(r.data.papers || []);
      setTotal(r.data.total || 0);
    } catch { }
    finally { setLoading(false); }
  }, [sort, dir, offset, debouncedSearch, subset]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setOffset(0); }, [sort, dir, debouncedSearch, subset]);

  useEffect(() => {
    axios.get(`${API}/api/defi/stats`).then(r => setStats(r.data)).catch(() => {});
  }, []);

  const toggleSort = (field) => {
    if (sort === field) {
      setDir(d => d === "desc" ? "asc" : "desc");
    } else {
      setSort(field);
      setDir(field === "title" ? "asc" : "desc");
    }
  };

  const SortHeader = ({ field, children, className = "" }) => (
    <th
      className={`px-3 py-2.5 text-left font-medium cursor-pointer select-none hover:text-foreground transition-colors ${className}`}
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sort === field && <ArrowUpDown className="h-3 w-3 text-accent" />}
      </span>
    </th>
  );

  const pageCount = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <>
      <Helmet>
        <title>DeFi Paper Rankings | Kurate.org</title>
        <meta name="description" content="AI-ranked decentralized finance, cryptocurrency, and blockchain research papers" />
      </Helmet>

      <div className="container mx-auto px-4 max-w-6xl py-6 md:py-10">
        <div className="mb-6">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
            DeFi & Crypto Research
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {total.toLocaleString()} papers on decentralized finance, cryptocurrency, and blockchain
            {stats && ` from ${Object.keys(stats.by_year || {}).length} years`}
          </p>
        </div>

        {/* Subset toggle */}
        <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit mb-5">
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
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-5">
            {Object.entries(stats.by_year || {}).sort((a,b) => b[0].localeCompare(a[0])).map(([year, count]) => (
              <span key={year}>{year}: {count}</span>
            ))}
            <span className="text-blue-600">{stats.with_pdf} with PDF</span>
            <span className="text-green-600">{stats.with_abstract} with abstract</span>
          </div>
        )}

        {/* Search + sort controls */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="relative w-64">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search title, author, keyword..."
              className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-accent"
              data-testid="defi-search"
            />
          </div>
          <div className="ml-auto text-xs text-muted-foreground">
            {offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString()}
          </div>
        </div>

        {/* Table */}
        <div className="border rounded-lg overflow-x-auto" data-testid="defi-table">
          <table className="w-full text-xs" style={{ minWidth: "900px", tableLayout: "fixed" }}>
            <colgroup>
              <col style={{ width: "35px" }} />
              <col style={{ width: "40%" }} />
              <col style={{ width: "80px" }} />
              <col style={{ width: "110px" }} />
              <col style={{ width: "50px" }} />
              <col style={{ width: "50px" }} />
              <col style={{ width: "45px" }} />
              <col style={{ width: "45px" }} />
              <col style={{ width: "40px" }} />
            </colgroup>
            <thead>
              <tr className="bg-secondary/50 text-xs text-muted-foreground">
                <th className="px-3 py-2.5 text-left font-medium">#</th>
                <SortHeader field="title">Paper</SortHeader>
                <SortHeader field="date">Date</SortHeader>
                <th className="px-3 py-2.5 text-left font-medium">Source</th>
                <SortHeader field="citations">Cited</SortHeader>
                <th className="px-3 py-2.5 text-left font-medium">Score</th>
                <th className="px-3 py-2.5 text-left font-medium">CI</th>
                <th className="px-3 py-2.5 text-left font-medium">Gap</th>
                <th className="px-3 py-2.5 text-center font-medium">PDF</th>
              </tr>
            </thead>
            <tbody>
              {loading && !papers.length ? (
                [...Array(10)].map((_, i) => (
                  <tr key={i} className="border-t border-border/50">
                    <td colSpan={9} className="px-3 py-3"><div className="h-4 bg-secondary/30 rounded animate-pulse" /></td>
                  </tr>
                ))
              ) : papers.length === 0 ? (
                <tr><td colSpan={9} className="px-3 py-12 text-center text-muted-foreground">No papers found</td></tr>
              ) : papers.map((p, i) => (
                <tr key={p.doi || i} className="border-t border-border/50 hover:bg-secondary/20 transition-colors">
                  <td className="px-3 py-2 text-muted-foreground font-mono">{offset + i + 1}</td>
                  <td className="px-3 py-2">
                    <div className="min-w-0">
                      <p className="text-xs sm:text-sm font-medium leading-tight truncate" title={p.title}>{p.title}</p>
                      <p className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 truncate">
                        {(p.authors || []).slice(0, 3).join(", ")}
                        {(p.authors || []).length > 3 && ` +${p.authors.length - 3}`}
                      </p>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{fmtDate(p.publication_date)}</td>
                  <td className="px-3 py-2 text-muted-foreground text-[10px] truncate max-w-[120px]" title={p.source}>{p.source || "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{p.cited_by_count || "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground/40">—</td>
                  <td className="px-3 py-2 text-muted-foreground/40">—</td>
                  <td className="px-3 py-2 text-muted-foreground/40">—</td>
                  <td className="px-3 py-2 text-center">
                    {p.pdf_url ? (
                      <a href={p.pdf_url} target="_blank" rel="noopener noreferrer"
                        className="text-accent hover:text-accent/80" title="Download PDF">
                        <FileText className="h-3.5 w-3.5 inline" />
                      </a>
                    ) : p.url ? (
                      <a href={p.url} target="_blank" rel="noopener noreferrer"
                        className="text-muted-foreground/40 hover:text-muted-foreground" title="View on source">
                        <ExternalLink className="h-3.5 w-3.5 inline" />
                      </a>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pageCount > 1 && (
          <div className="flex items-center justify-between mt-4">
            <Button size="sm" variant="outline" className="text-xs h-8 gap-1"
              disabled={offset === 0} onClick={() => setOffset(o => Math.max(0, o - limit))}>
              <ChevronLeft className="h-3.5 w-3.5" /> Previous
            </Button>
            <span className="text-xs text-muted-foreground">Page {currentPage} of {pageCount}</span>
            <Button size="sm" variant="outline" className="text-xs h-8 gap-1"
              disabled={offset + limit >= total} onClick={() => setOffset(o => o + limit)}>
              Next <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
