import { useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowUp, ArrowDown, Bookmark } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { LatexTitle } from "@/components/LatexTitle";
import { useBasePath } from "@/contexts/BasePathContext";
import { useBookmarks } from "@/contexts/BookmarkContext";

const COL_TIPS = {
  rank: "Position based on score. Click to restore default ranking.",
  title: "Paper title. Click to sort alphabetically.",
  score: "TrueSkill score from pairwise comparisons. Higher = stronger.",
  wilson_margin: "95% confidence interval in Elo points. Lower = more certain.",
  comparisons: "Number of pairwise LLM comparisons this paper has participated in.",
  win_rate: "Percentage of head-to-head comparisons won.",
  ai_rating: "Standalone AI quality rating (1 to 10) from Opus 4.6 Thinking.",
  gap_score: "Difference between tournament rank percentile and AI rating percentile.",
  published: "arXiv publication date.",
};

function SortHeader({ label, sortKey, current, dir, onSort, className = "", tip }) {
  const active = current === sortKey;
  const btn = (
    <button onClick={() => onSort(sortKey)} className={`inline-flex items-center gap-0.5 uppercase text-[10px] font-bold tracking-wider hover:text-slate-900 transition-colors ${active ? "text-slate-900" : ""} ${className}`}>
      {label}
      {active && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
    </button>
  );
  if (!tip) return btn;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{btn}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs"><p className="text-xs">{tip}</p></TooltipContent>
    </Tooltip>
  );
}

export function LeaderboardTableNew({
  leaderboard, loading, sortKey, sortDir, onSort,
  showRatingCol, showGapCol, hasSelectedTags, globalStats, isArchive,
  nextCursor, loadMore, loadingMore, keyword,
  onCategoryClick, activeCodes,
}) {
  const sentinelRef = useRef(null);
  const basePath = useBasePath();
  const { bookmarkedIds, toggleBookmark } = useBookmarks();

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
  const isDefaultSort = !sortKey || sortKey === "rank";
  const getScore = (p) => isGlobal && p.global_score !== undefined ? p.global_score : (p.ts_score || p.score);
  const getWinRate = (p) => isGlobal && p.global_win_rate !== undefined ? p.global_win_rate : p.win_rate;
  const getComparisons = (p) => isGlobal && p.global_comparisons !== undefined ? p.global_comparisons : p.comparisons;
  const getCi = (p) => isGlobal ? null : p.ci;
  // When sorted by default (rank), show the backend's TrueSkill rank.
  // When sorted by any other column, show position in current order (1, 2, 3...).
  const getRank = (p, i) => isDefaultSort ? (p._displayRank || p.rank_ts || p.rank || (i + 1)) : (i + 1);

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
      <table className="w-full table-fixed">
        <colgroup>
          <col className="w-12" />{/* # */}
          <col />{/* Paper — gets remaining space */}
          <col className="w-16" />{/* Score */}
          <col className="w-14" />{/* CI */}
          <col className="w-14" />{/* Match */}
          <col className="w-14" />{/* Win% */}
          {showRatingCol && <col className="w-16" />}{/* Rating */}
          {showGapCol && <col className="w-14" />}{/* Gap */}
          <col className="w-24" />{/* Published */}
          <col className="w-8" />{/* Bookmark */}
        </colgroup>
        <thead>
          <tr className="text-slate-500 bg-slate-50 border-b border-slate-100 whitespace-nowrap">
            <th className="pl-5 pr-2 py-2.5 text-center w-10"><SortHeader label="#" sortKey="rank" current={sortKey} dir={sortDir} onSort={onSort} tip={COL_TIPS.rank} /></th>
            <th className="px-2 py-2.5 text-left"><SortHeader label="Paper" sortKey="title" current={sortKey} dir={sortDir} onSort={onSort} tip={COL_TIPS.title} /></th>
            <th className="px-2 py-2.5 text-right"><SortHeader label="Score" sortKey="score" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.score} /></th>
            <th className="px-2 py-2.5 text-right hidden lg:table-cell"><SortHeader label="CI" sortKey="wilson_margin" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.wilson_margin} /></th>
            <th className="px-2 py-2.5 text-right hidden md:table-cell"><SortHeader label="Match" sortKey="comparisons" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.comparisons} /></th>
            <th className="px-2 py-2.5 text-right hidden md:table-cell"><SortHeader label="Win%" sortKey="win_rate" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.win_rate} /></th>
            {showRatingCol && <th className="px-2 py-2.5 text-right hidden lg:table-cell"><SortHeader label="Rating" sortKey="ai_rating" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.ai_rating} /></th>}
            {showGapCol && <th className="px-2 py-2.5 text-right hidden xl:table-cell"><SortHeader label="Gap" sortKey="gap_score" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.gap_score} /></th>}
            <th className="px-2 py-2.5 text-right hidden sm:table-cell"><SortHeader label="Published" sortKey="published" current={sortKey} dir={sortDir} onSort={onSort} className="justify-end" tip={COL_TIPS.published} /></th>
            <th className="pr-4 py-2.5 w-8"></th>
          </tr>
        </thead>
        <tbody>
          {leaderboard.map((p, i) => {
            const isBookmarked = bookmarkedIds?.has(p.id);
            return (
              <tr key={p.id || i} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70 transition-colors group">
                <td className="pl-5 pr-2 py-3 text-center align-baseline">
                  <span className="font-serif text-base font-medium text-blue-600">{getRank(p, i)}</span>
                </td>
                <td className="px-2 py-3">
                  <Link to={`${basePath}/paper/${p.id}`} className="text-sm font-medium text-slate-900 hover:text-blue-700 leading-snug line-clamp-2">
                    <LatexTitle text={p.title} />
                  </Link>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500 flex-wrap">
                    <span>{p.authors?.slice(0, 2).join(", ")}{p.authors?.length > 2 ? ` +${p.authors.length - 2}` : ""}</span>
                    {(() => {
                      const m = p.arxiv_id && /v(\d+)$/.exec(p.arxiv_id);
                      const v = m ? parseInt(m[1], 10) : (p.current_version || 1);
                      return v > 1 ? (
                        <span className="text-[9px] font-mono px-1 py-px rounded bg-amber-50 text-amber-700 border border-amber-200">v{v}</span>
                      ) : null;
                    })()}
                    {/* Primary + secondary category tags */}
                    {(() => {
                      const primary = p.primary_category || (p.categories || [])[0] || "";
                      const secondary = (p.categories || []).filter(c => c !== primary);
                      if (!primary) return null;
                      const canClick = onCategoryClick && activeCodes;
                      return (
                        <>
                          <span className="text-slate-300">·</span>
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
                </td>
                <td className="px-2 py-3 text-right align-baseline">
                  <span className="text-sm font-semibold tabular-nums">{getScore(p) || "\u2014"}</span>
                </td>
                <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden lg:table-cell">
                  {(() => { const c = getCi(p); return c != null && c > 0 ? `\u00B1${Math.round(c)}` : "\u2014"; })()}
                </td>
                <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden md:table-cell">{getComparisons(p) ?? "\u2014"}</td>
                <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden md:table-cell">{getWinRate(p) != null ? `${getWinRate(p)}%` : "\u2014"}</td>
                {showRatingCol && (
                  <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden lg:table-cell">
                    {(typeof p.ai_rating === "object" ? p.ai_rating?.score : p.ai_rating) || "\u2014"}
                  </td>
                )}
                {showGapCol && (
                  <td className={`px-2 py-3 text-right align-baseline text-xs hidden xl:table-cell ${p.gap_score > 0 ? "text-emerald-600" : p.gap_score < 0 ? "text-red-400" : "text-slate-500"}`}>
                    {p.gap_score != null ? (p.gap_score > 0 ? "+" : "") + p.gap_score : "\u2014"}
                  </td>
                )}
                <td className="px-2 py-3 text-right align-baseline text-xs text-slate-500 hidden sm:table-cell whitespace-nowrap">
                  {p.published ? new Date(p.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "\u2014"}
                </td>
                <td className="pr-4 py-3 text-center align-baseline">
                  <button
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleBookmark(p.id); }}
                    className={`transition-colors ${isBookmarked ? "text-blue-600" : "text-slate-300 opacity-0 group-hover:opacity-100 hover:text-blue-600"}`}
                    title={isBookmarked ? "Remove bookmark" : "Bookmark"}
                  >
                    <Bookmark className="h-3.5 w-3.5" fill={isBookmarked ? "currentColor" : "none"} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {nextCursor && !isArchive && (
        <div ref={sentinelRef} className="py-4 text-center text-xs text-slate-400">
          {loadingMore ? "Loading more..." : "\u00A0"}
        </div>
      )}
    </>
    </TooltipProvider>
  );
}
