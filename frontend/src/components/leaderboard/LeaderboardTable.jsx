import { useRef, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { Trophy, ArrowUp, ArrowDown } from "lucide-react";
import { RankBadge } from "./RankBadge";

const SORT_COLUMNS = [
  { key: "rank", label: "#", align: "left" },
  { key: "title", label: "Paper", align: "left" },
  { key: "score", label: "Score", align: "right", hideOnMobile: false },
  { key: "win_rate", label: "Win %", align: "right", hideOnMobile: true },
  { key: "wilson_margin", label: "95% CI", align: "right", hideOnMobile: true },
  { key: "comparisons", label: "Mtch", align: "right", hideOnMobile: true },
  { key: "published", label: "Published", align: "right", hideOnTablet: true },
];

function SortHeader({ label, sortKey, currentSort, currentDir, onSort, className }) {
  const isActive = currentSort === sortKey;
  return (
    <button
      onClick={() => onSort(sortKey)}
      className={`inline-flex items-center gap-0.5 hover:text-foreground transition-colors ${isActive ? "text-foreground" : ""} ${className || ""}`}
      data-testid={`sort-${sortKey}`}
    >
      {label}
      {isActive && (currentDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
    </button>
  );
}

export function LeaderboardTable({
  leaderboard, loading, showCatCol, hasSelectedTags, globalStats,
  debouncedKeyword, keyword, displayCount, setDisplayCount,
  sortKey, sortDir, onSort,
}) {
  const sentinelRef = useRef(null);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setDisplayCount(prev => prev + 50); },
      { rootMargin: "200px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [leaderboard, setDisplayCount]);

  const getScore = (p) => hasSelectedTags && globalStats && p.global_score !== undefined ? p.global_score : p.score;
  const getWinRate = (p) => hasSelectedTags && globalStats && p.global_win_rate !== undefined ? p.global_win_rate : p.win_rate;
  const getComparisons = (p) => hasSelectedTags && globalStats && p.global_comparisons !== undefined ? p.global_comparisons : p.comparisons;
  const getWilsonMargin = (p) => hasSelectedTags && globalStats ? null : p.wilson_margin;

  // Sort the leaderboard
  const sorted = useMemo(() => {
    if (!sortKey || sortKey === "rank") return leaderboard;
    const getValue = (p) => {
      switch (sortKey) {
        case "title": return p.title?.toLowerCase() || "";
        case "score": return getScore(p) || 0;
        case "win_rate": return getWinRate(p) || 0;
        case "wilson_margin": return getWilsonMargin(p) || 999;
        case "comparisons": return getComparisons(p) || 0;
        case "published": return p.published || "";
        default: return 0;
      }
    };
    const dir = sortDir === "asc" ? 1 : -1;
    return [...leaderboard].sort((a, b) => {
      const va = getValue(a), vb = getValue(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [leaderboard, sortKey, sortDir, hasSelectedTags, globalStats]); // eslint-disable-line react-hooks/exhaustive-deps

  const gridCls = showCatCol
    ? "grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4rem_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_4.5rem_5rem_4.5rem_4.5rem_4rem_7rem]"
    : "grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem]";

  const visibleList = sorted.slice(0, displayCount);
  const hasMore = sorted.length > visibleList.length;

  const scoreLabel = hasSelectedTags && globalStats ? "Score (G)" : "Score";
  const winLabel = hasSelectedTags && globalStats ? "Win % (G)" : "Win %";
  const matchLabel = hasSelectedTags && globalStats ? "Mtch (G)" : "Mtch";

  if (loading) {
    return (
      <div className="space-y-3" data-testid="loading-skeleton">
        {[...Array(8)].map((_, i) => <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />)}
      </div>
    );
  }

  if (leaderboard.length === 0) {
    return (
      <div className="text-center py-20 text-muted-foreground" data-testid="empty-state">
        <Trophy className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">
          {debouncedKeyword ? `No papers matching "${keyword}".` : `No papers found for this ${hasSelectedTags ? "tag combination" : "period"}.`}
        </p>
        <p className="text-xs mt-1">{debouncedKeyword ? "Try different keywords." : hasSelectedTags ? "Try different tags, switch to OR mode, or clear the filter." : "Try a broader time range."}</p>
      </div>
    );
  }

  return (
    <>
      {debouncedKeyword && (
        <div className="text-xs text-muted-foreground mb-2">Showing {leaderboard.length} papers matching "{keyword}"</div>
      )}
      <div className="border border-border rounded-lg overflow-x-auto" data-testid="leaderboard-table">
        <div className={`grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4 py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border select-none ${gridCls}`}>
          <SortHeader label="#" sortKey="rank" currentSort={sortKey} currentDir={sortDir} onSort={onSort} />
          <SortHeader label="Paper" sortKey="title" currentSort={sortKey} currentDir={sortDir} onSort={onSort} />
          {showCatCol && <div className="text-center hidden sm:block">Cat</div>}
          <SortHeader label={scoreLabel} sortKey="score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" />
          <SortHeader label={winLabel} sortKey="win_rate" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden sm:flex" />
          <SortHeader label="95% CI" sortKey="wilson_margin" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden sm:flex" />
          <SortHeader label={matchLabel} sortKey="comparisons" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden sm:flex" />
          <SortHeader label="Published" sortKey="published" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden md:flex" />
        </div>
        {visibleList.map((paper, idx) => (
          <Link
            key={paper.id}
            to={`/paper/${paper.id}`}
            className={`grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4 py-2 sm:py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${gridCls} ${idx < 3 && !debouncedKeyword && (!sortKey || sortKey === "rank") ? "bg-accent/[0.02]" : ""}`}
            data-testid={`leaderboard-row-${idx}`}
          >
            <div><RankBadge rank={paper.rank} /></div>
            <div className="min-w-0">
              <p className="text-xs sm:text-sm font-medium truncate leading-tight" title={paper.title}>{paper.title}</p>
              <p className="text-[10px] sm:text-xs text-muted-foreground truncate mt-0.5">
                {paper.authors?.slice(0, 2).join(", ")}
                {paper.authors?.length > 2 && ` +${paper.authors.length - 2}`}
              </p>
            </div>
            {showCatCol && (
              <div className="text-center hidden sm:block">
                <span className="inline-block text-[9px] px-1.5 py-0.5 rounded font-mono bg-secondary text-muted-foreground">{paper.primary_category || "?"}</span>
              </div>
            )}
            <div className="text-right font-mono text-xs sm:text-sm font-medium">{getScore(paper)}</div>
            <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground hidden sm:block">{getWinRate(paper)}%</div>
            <div className="text-right font-mono text-xs text-muted-foreground hidden sm:block">
              {(() => { const wm = getWilsonMargin(paper); return wm != null && wm > 0 ? `\u00B1${wm}%` : "--"; })()}
            </div>
            <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground hidden sm:block">{getComparisons(paper)}</div>
            <div className="text-right text-xs text-muted-foreground hidden md:block">
              {paper.published ? new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "--"}
            </div>
          </Link>
        ))}
      </div>
      {hasMore && <div ref={sentinelRef} className="py-4 text-center text-xs text-muted-foreground">Loading more...</div>}
    </>
  );
}
