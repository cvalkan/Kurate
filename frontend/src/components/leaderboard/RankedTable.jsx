import { useRef, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Bookmark } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { LatexTitle } from "@/components/LatexTitle";
import { useBasePath } from "@/contexts/BasePathContext";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { useAuth } from "@/contexts/AuthContext";

const COL_TIPS = {
  rank: "Position in current view.",
  title: "Paper title. Click to sort alphabetically.",
  score: "TrueSkill score from pairwise comparisons. Higher = stronger.",
  wilson_margin: "95% confidence interval. Lower = more certain.",
  comparisons: "Number of pairwise LLM comparisons.",
  win_rate: "Percentage of comparisons won.",
  ai_rating: "Standalone AI quality rating (1 to 10).",
  gap_score: "Difference between tournament rank percentile and AI rating percentile.",
  published: "arXiv publication date.",
};

function SortDiv({ label, sortKey, current, dir, onSort, className = "", tip }) {
  const active = current === sortKey;
  const el = (
    <div onClick={() => onSort(sortKey)}
      className={`uppercase text-[10px] font-bold tracking-wider cursor-pointer select-none hover:text-slate-900 transition-colors whitespace-nowrap ${active ? "text-slate-900" : "text-slate-500"} ${className}`}>
      <span className="relative">
        {label}
      </span>
    </div>
  );
  if (!tip) return el;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{el}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs"><p className="text-xs">{tip}</p></TooltipContent>
    </Tooltip>
  );
}

export function RankedTable({
  leaderboard, loading, sortKey, sortDir, onSort,
  showRatingCol, showGapCol, hasSelectedTags, globalStats, isArchive,
  nextCursor, loadMore, loadingMore, keyword,
  onCategoryClick, activeCodes,
}) {
  const sentinelRef = useRef(null);
  const basePath = useBasePath();
  const location = useLocation();
  const { bookmarkedIds, toggleBookmark } = useBookmarks();
  const { user } = useAuth();
  const isLoggedIn = !!user;
  const requireAuth = () => window.dispatchEvent(new Event("open-auth-modal"));

  // Responsive breakpoints (matching old design)
  const [isMobile, setIsMobile] = useState(false);
  const [isTablet, setIsTablet] = useState(false);
  useEffect(() => {
    const check = () => { setIsMobile(window.innerWidth < 640); setIsTablet(window.innerWidth < 1024); };
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !loadMore || !nextCursor || loadingMore) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadMore();
    }, { rootMargin: "200px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore, nextCursor, loadingMore]);

  const isGlobal = hasSelectedTags && globalStats;
  const getScore = (p) => isGlobal && p.global_score !== undefined ? p.global_score : (p.ts_score || p.score);
  const getWinRate = (p) => isGlobal && p.global_win_rate !== undefined ? p.global_win_rate : p.win_rate;
  const getComparisons = (p) => isGlobal && p.global_comparisons !== undefined ? p.global_comparisons : p.comparisons;
  const getCi = (p) => isGlobal ? null : p.ci;
  const getRank = (p, i) => i + 1;

  // Fixed grid columns — same approach as old LeaderboardTable
  const cols = [];
  cols.push("1.75rem", "1fr"); // # + Paper
  cols.push(isMobile ? "2.75rem" : "3.25rem"); // Score
  if (!isMobile && !isTablet) cols.push("2.45rem"); // CI
  if (!isMobile) cols.push("2.45rem"); // Match
  if (!isMobile) cols.push("2.75rem"); // Win%
  if (showRatingCol && !isMobile && !isTablet) cols.push("2.75rem"); // Rating
  if (showGapCol && !isMobile && !isTablet) cols.push("2.45rem"); // Gap
  if (!isMobile) cols.push("4.75rem"); // Published
  cols.push("1.45rem"); // Bookmark
  const gridStyle = { gridTemplateColumns: cols.join(" ") };
  const gridBase = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

  if (loading && leaderboard.length === 0) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(8)].map((_, i) => <div key={i} className="h-12 bg-slate-50 rounded-sm animate-pulse" />)}
      </div>
    );
  }

  if (leaderboard.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-slate-400">
        {keyword ? `No papers matching "${keyword}".` : "No papers found for this period. Try a broader time range."}
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
    <>
      {/* Header */}
      <div className={`${gridBase} py-2.5 bg-slate-50 text-slate-500 border-b border-slate-100 select-none items-end`} style={gridStyle}>
        <div className="text-center text-[10px] font-bold uppercase tracking-wider">#</div>
        <SortDiv label="Paper" sortKey="title" current={sortKey} dir={sortDir} onSort={onSort} tip={COL_TIPS.title} />
        <SortDiv label="Score" sortKey="score" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.score} />
        {!isMobile && !isTablet && <SortDiv label="CI" sortKey="wilson_margin" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.wilson_margin} />}
        {!isMobile && <SortDiv label="Match" sortKey="comparisons" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.comparisons} />}
        {!isMobile && <SortDiv label="Win%" sortKey="win_rate" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.win_rate} />}
        {showRatingCol && !isMobile && !isTablet && <SortDiv label="Rating" sortKey="ai_rating" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.ai_rating} />}
        {showGapCol && !isMobile && !isTablet && <SortDiv label="Gap" sortKey="gap_score" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.gap_score} />}
        {!isMobile && <SortDiv label="Published" sortKey="published" current={sortKey} dir={sortDir} onSort={onSort} className="text-right" tip={COL_TIPS.published} />}
        <div />
      </div>

      {/* Rows */}
      {leaderboard.map((p, i) => {
        const isBookmarked = bookmarkedIds?.has(p.id);
        return (
          <div key={p.id || i} className={`${gridBase} py-2 sm:py-3 items-center border-b border-slate-100 hover:bg-slate-50/70 transition-colors group`} style={gridStyle}>
            <div className="text-center">
              <span className="font-serif text-base font-medium text-blue-600">{getRank(p, i)}</span>
            </div>
            <div className="min-w-0">
              <Link to={`${basePath}/paper/${p.id}`} state={{ from: location.pathname + location.search }} className="text-sm font-medium text-slate-900 hover:text-blue-700 leading-snug line-clamp-2">
                <LatexTitle text={p.title} />
              </Link>
              <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500 flex-wrap">
                <span>{p.authors?.slice(0, 2).join(", ")}{p.authors?.length > 2 ? ` +${p.authors.length - 2}` : ""}</span>
                {(() => {
                  const m = p.arxiv_id && /v(\d+)$/.exec(p.arxiv_id);
                  const v = m ? parseInt(m[1], 10) : (p.current_version || 1);
                  return v > 1 ? <span className="text-[9px] font-mono px-1 py-px rounded bg-amber-50 text-amber-700 border border-amber-200">v{v}</span> : null;
                })()}
                {(() => {
                  const primary = p.primary_category || (p.categories || [])[0] || "";
                  const secondary = (p.categories || []).filter(c => c !== primary);
                  if (!primary) return null;
                  const canClick = onCategoryClick && activeCodes;
                  return (
                    <>
                      {canClick && activeCodes.has(primary) ? (
                        <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); onCategoryClick(primary); }}
                          className="inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 transition-colors cursor-pointer">
                          {primary}
                        </button>
                      ) : (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium bg-blue-50 text-blue-700 border-blue-200">{primary}</span>
                      )}
                      {secondary.map(tag => (
                        canClick && activeCodes.has(tag) ? (
                          <button key={tag} type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); onCategoryClick(tag); }}
                            className="inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium bg-slate-50 text-slate-500 border-slate-200 hover:bg-slate-100 transition-colors cursor-pointer">
                            {tag}
                          </button>
                        ) : (
                          <span key={tag} className="inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium bg-slate-50 text-slate-500 border-slate-200">{tag}</span>
                        )
                      ))}
                    </>
                  );
                })()}
              </div>
            </div>
            <div className="text-right text-sm font-semibold tabular-nums">{getScore(p) || "\u2014"}</div>
            {!isMobile && !isTablet && <div className="text-right text-xs text-slate-500">{(() => { const c = getCi(p); return c != null && c > 0 ? `\u00B1${Math.round(c)}` : "\u2014"; })()}</div>}
            {!isMobile && <div className="text-right text-xs text-slate-500">{getComparisons(p) ?? "\u2014"}</div>}
            {!isMobile && <div className="text-right text-xs text-slate-500">{getWinRate(p) != null ? `${getWinRate(p)}%` : "\u2014"}</div>}
            {showRatingCol && !isMobile && !isTablet && <div className="text-right text-xs text-slate-500">{(typeof p.ai_rating === "object" ? p.ai_rating?.score : p.ai_rating) || "\u2014"}</div>}
            {showGapCol && !isMobile && !isTablet && <div className={`text-right text-xs ${p.gap_score > 0 ? "text-emerald-600" : p.gap_score < 0 ? "text-red-400" : "text-slate-500"}`}>{p.gap_score != null ? (p.gap_score > 0 ? "+" : "") + p.gap_score : "\u2014"}</div>}
            {!isMobile && <div className="text-right text-xs text-slate-500 whitespace-nowrap">{p.published ? new Date(p.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "\u2014"}</div>}
            <div>
              <button
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); isLoggedIn ? toggleBookmark(p.id) : requireAuth(); }}
                className={`transition-colors ${isBookmarked ? "text-blue-600" : "text-slate-300 hover:text-blue-600"}`}
                title={isBookmarked ? "Remove bookmark" : "Bookmark"}
              >
                <Bookmark className="h-3.5 w-3.5 mt-[6px]" fill={isBookmarked ? "currentColor" : "none"} />
              </button>
            </div>
          </div>
        );
      })}
      {nextCursor && !isArchive && (
        <div ref={sentinelRef} className="py-4 text-center text-xs text-slate-400">{loadingMore ? "Loading more..." : "\u00A0"}</div>
      )}
    </>
    </TooltipProvider>
  );
}
