import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Clock, Calendar, CalendarDays, Infinity, Search, X, Lock, Archive, ChevronDown } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const PERIODS = [
  { key: "recent", label: "Most Recent", icon: Clock },
  { key: "week", label: "Last 7 Days", icon: Calendar },
  { key: "month", label: "Last 30 Days", icon: CalendarDays },
  { key: "all", label: "All Time", icon: Infinity },
];

export function PeriodFilter({ period, setPeriod, keyword, setKeyword, isLoggedIn, requireAuth, archives = [], onArchiveSelect, activeArchiveLabel }) {
  const [archiveOpen, setArchiveOpen] = useState(false);
  const archiveRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (archiveRef.current && !archiveRef.current.contains(e.target)) setArchiveOpen(false); };
    document.addEventListener("mousedown", handler);
    window.addEventListener("scroll", () => setArchiveOpen(false), true);
    return () => {
      document.removeEventListener("mousedown", handler);
      window.removeEventListener("scroll", () => setArchiveOpen(false), true);
    };
  }, []);

  const handleArchiveClick = async (archive) => {
    setArchiveOpen(false);
    const slug = archive.period_type === "older"
      ? "older"
      : archive.period_type === "weekly" ? `w${archive.week}` : `m${archive.month}`;
    const apiUrl = archive.period_type === "older"
      ? `${API}/api/archive/${archive.category}/older`
      : `${API}/api/archive/${archive.category}/${archive.year}/${slug}`;
    try {
      const res = await axios.get(apiUrl);
      if (res.data.leaderboard) {
        onArchiveSelect(res.data, archive);
        // Update URL for shareability (without triggering React re-render)
        const shareSlug = archive.period_type === "older" ? "older"
          : archive.period_type === "weekly" ? `${archive.year}-w${archive.week}`
          : `${archive.year}-m${archive.month}`;
        const params = new URLSearchParams(window.location.search);
        params.set("archive", shareSlug);
        params.delete("period");
        window.history.replaceState(null, "", `?${params.toString()}`);
      }
    } catch (e) {
      console.error("Failed to load archive:", e);
    }
  };

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 mb-6">
      <div className="flex items-center gap-1 p-1 bg-secondary/50 rounded-lg overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-1" data-testid="period-filter">
        {PERIODS.map((p) => {
          const Icon = p.icon;
          const isLocked = !isLoggedIn && (p.key === "month" || p.key === "all");
          return isLocked ? (
            <Tooltip key={p.key}>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" onClick={requireAuth} className="gap-1.5 text-xs h-8 shrink-0 opacity-40" data-testid={`filter-${p.key}-locked`}>
                  <Lock className="h-3 w-3" /> {p.label}
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Sign in to access {p.label.toLowerCase()} view</p></TooltipContent>
            </Tooltip>
          ) : (
            <Button key={p.key} variant={period === p.key ? "default" : "ghost"} size="sm"
              onClick={() => {
                setPeriod(p.key);
                if (onArchiveSelect) onArchiveSelect(null);
                // Clear archive URL param
                const params = new URLSearchParams(window.location.search);
                if (params.has("archive")) { params.delete("archive"); window.history.replaceState(null, "", `?${params.toString()}`); }
              }}
              className="gap-1.5 text-xs h-8 shrink-0" data-testid={`filter-${p.key}`}>
              <Icon className="h-3.5 w-3.5" /> {p.label}
            </Button>
          );
        })}
        {archives.length > 0 && (
          <div className="relative shrink-0" ref={archiveRef}>
            <Button
              variant={activeArchiveLabel ? "default" : "ghost"} size="sm"
              onClick={() => setArchiveOpen(v => !v)}
              className="gap-1.5 text-xs h-8"
              data-testid="filter-archive"
            >
              <Archive className="h-3.5 w-3.5" />
              {activeArchiveLabel || "Archive"}
              <ChevronDown className={`h-3 w-3 transition-transform ${archiveOpen ? "rotate-180" : ""}`} />
            </Button>
            {archiveOpen && (
              <div className="fixed z-50 bg-background border border-border rounded-lg shadow-lg min-w-[220px] max-h-[320px] overflow-y-auto py-1"
                style={{ top: archiveRef.current?.getBoundingClientRect().bottom + 4, left: archiveRef.current?.getBoundingClientRect().left }}>
                {archives.map(a => {
                  const slug = a.period_type === "weekly" ? `w${a.week}` : `m${a.month}`;
                  return (
                    <button
                      key={`${a.category}-${a.year}-${slug}`}
                      onClick={() => handleArchiveClick(a)}
                      className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent/10 transition-colors flex items-center justify-between"
                    >
                      <span>{a.label}</span>
                      <span className="text-[10px] text-muted-foreground ml-3">{a.paper_count} papers</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input placeholder="Search papers..." value={keyword} onChange={e => setKeyword(e.target.value)} className="h-8 text-xs pl-8 w-full sm:w-48" data-testid="keyword-search" />
        {keyword && (
          <button onClick={() => setKeyword("")} className="absolute right-2 top-1/2 -translate-y-1/2">
            <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
          </button>
        )}
      </div>
    </div>
  );
}
