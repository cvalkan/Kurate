import { useRef, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Trophy, ArrowUp, ArrowDown, X } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { RankBadge } from "./RankBadge";
import { BookmarkButton } from "@/components/BookmarkButton";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { LatexTitle } from "@/components/LatexTitle";

const COLUMN_TIPS = {
  rank: "Position based on win-rate score (higher = better). Click to restore default ranking.",
  title: "Paper title. Click to sort alphabetically.",
  score: "Win-rate score from pairwise comparisons. 1200 = average, higher = stronger.",
  score_g: "Win-rate score from ALL matches across all categories (pairwise win-rate). Reflects overall performance.",
  win_rate: "Percentage of head-to-head comparisons won within this set.",
  win_rate_g: "Win rate across ALL matches the paper has participated in, not just this filtered set.",
  wilson_margin: "95% confidence interval in \u00B1Elo points (from TrueSkill \u03C3). Lower = more certain ranking. Based on opponent strength, not just win rate.",
  comparisons: "Number of head-to-head LLM comparisons this paper has participated in within this set.",
  comparisons_g: "Total comparisons across ALL categories, including matches outside this filtered set.",
  published: "arXiv publication date.",
};

function SortHeader({ label, sortKey, currentSort, currentDir, onSort, className, tip }) {
  const isActive = currentSort === sortKey;
  const btn = (
    <button
      onClick={() => onSort(sortKey)}
      className={`inline-flex items-center gap-0.5 hover:text-foreground transition-colors ${isActive ? "text-foreground" : ""} ${className || ""}`}
      data-testid={`sort-${sortKey}`}
    >
      {label}
      {isActive && (currentDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
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

export function LeaderboardTable({
  leaderboard, loading, showCatCol, hasSelectedTags, globalStats,
  debouncedKeyword, keyword, onLoadMore, hasMore, loadingMore,
  sortKey, sortDir, onSort, showRatingCol = true, showGapCol = true,
  bookmarksMode = false, onRemoveBookmark, selectedPapers, onToggleSelect,
  scoringMethod = "ts", isArchive = false,
}) {
  const sentinelRef = useRef(null);
  const { bookmarkedIds, toggleBookmark } = useBookmarks();

  // Sentinel triggers server page loads when user scrolls near bottom
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        if (hasMore && onLoadMore && !loadingMore) {
          onLoadMore();
        }
      },
      { rootMargin: "400px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [onLoadMore, hasMore, loadingMore]);

  const isGlobal = hasSelectedTags && globalStats;
  const getScore = (p) => {
    if (isGlobal && p.global_score !== undefined) return p.global_score;
    return p.ts_score || p.score;
  };
  const getWinRate = (p) => isGlobal && p.global_win_rate !== undefined ? p.global_win_rate : p.win_rate;
  const getComparisons = (p) => isGlobal && p.global_comparisons !== undefined ? p.global_comparisons : p.comparisons;
  const getWilsonMargin = (p) => {
    if (isGlobal) return null;
    return p.ci;
  };
  const getRank = (p) => {
    if (isArchive) return null; // Archives derive rank from array position, handled below
    return p.rank_ts || p.rank;
  };

  const scoreRankMap = useMemo(() => {
    const scoreFn = isGlobal ? (p => p.global_score || 0)
      : (p => p.ts_score || p.score || 0);
    const byScore = [...leaderboard].sort((a, b) => scoreFn(b) - scoreFn(a));
    const map = {};
    byScore.forEach((p, i) => { map[p.id] = i + 1; });
    return map;
  }, [leaderboard, isGlobal]); // eslint-disable-line react-hooks/exhaustive-deps

  // Assign display rank to each entry.
  // Archives: rank = array position (1-indexed). Array is sorted by score desc.
  // Live: use rank_ts from backend.
  // Global: re-sort by global_score.
  const sorted = useMemo(() => {
    if (isGlobal) {
      const ranked = [...leaderboard].sort((a, b) => (b.global_score || 0) - (a.global_score || 0));
      ranked.forEach((p, i) => { p._displayRank = i + 1; });
      return ranked;
    }
    if (isArchive) {
      return leaderboard.map((p, i) => ({ ...p, _displayRank: i + 1 }));
    }
    return leaderboard.map((p, i) => ({
      ...p,
      _displayRank: getRank(p) || (i + 1),
    }));
  }, [leaderboard, isGlobal, isArchive]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build grid template based on visible columns and screen size
  // Mobile: #, Paper, Score only. Tablet: +Win%, Match. Desktop: all columns.
  const [isMobile, setIsMobile] = useState(false);
  const [isTablet, setIsTablet] = useState(false);
  useEffect(() => {
    const check = () => {
      setIsMobile(window.innerWidth < 640);
      setIsTablet(window.innerWidth < 1024);
    };
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const cols = [];
  if (bookmarksMode && selectedPapers) cols.push("1.5rem"); // Checkbox
  cols.push("2.5rem", "1fr"); // # + Paper
  if (showCatCol && !isMobile) cols.push("3.5rem"); // Cat
  cols.push(isMobile ? "3.5rem" : "4rem"); // Score
  if (!isMobile && !isTablet) cols.push("3.5rem"); // CI
  if (!isMobile) cols.push("3rem"); // Match
  if (!isMobile) cols.push("3.5rem"); // Win%
  if (showRatingCol && !isMobile && !isTablet) cols.push("3rem"); // Rating
  if (showGapCol && !isMobile && !isTablet) cols.push("3rem"); // Gap
  if (!isMobile) cols.push("5.5rem"); // Published
  if (bookmarksMode && !isMobile) cols.push("5.5rem"); // Bookmarked
  if (bookmarksMode) cols.push("1.5rem"); // Remove
  else cols.push("1.5rem"); // Bookmark icon
  const gridStyle = { gridTemplateColumns: cols.join(" ") };
  const gridBase = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

  const visibleList = sorted;
  const hasMoreToShow = hasMore;

  const scoreLabel = "Score";
  const scoreTip = isGlobal ? COLUMN_TIPS.score_g : "TrueSkill score from pairwise comparisons. Bayesian rating updated incrementally per match.";
  const winLabel = "Win %";
  const matchLabel = "Match";

  if (loading) {
    return (
      <div className="space-y-3" data-testid="loading-skeleton">
        {[...Array(8)].map((_, i) => <div key={i} className="h-14 bg-secondary/30 rounded-sm animate-pulse" />)}
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
      <div className="border border-border rounded-sm overflow-x-auto" data-testid="leaderboard-table">
        <div className={`${gridBase} py-2.5 bg-slate-50 text-[10px] font-medium uppercase tracking-wider text-slate-500 border-b border-slate-200 select-none`} style={gridStyle}>
          {bookmarksMode && selectedPapers && <div />}
          <SortHeader label="#" sortKey="rank" currentSort={sortKey} currentDir={sortDir} onSort={onSort} tip={COLUMN_TIPS.rank} />
          <SortHeader label="Paper" sortKey="title" currentSort={sortKey} currentDir={sortDir} onSort={onSort} tip={COLUMN_TIPS.title} />
          {showCatCol && !isMobile && <div className="text-center">Cat</div>}
          <SortHeader label={isMobile ? "Score" : scoreLabel} sortKey="score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={scoreTip} />
          {!isMobile && !isTablet && <SortHeader label="95% CI" sortKey="wilson_margin" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={COLUMN_TIPS.wilson_margin} />}
          {!isMobile && <SortHeader label={matchLabel} sortKey="comparisons" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={isGlobal ? COLUMN_TIPS.comparisons_g : COLUMN_TIPS.comparisons} />}
          {!isMobile && <SortHeader label={winLabel} sortKey="win_rate" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={isGlobal ? COLUMN_TIPS.win_rate_g : COLUMN_TIPS.win_rate} />}
          {showRatingCol && !isMobile && !isTablet && <SortHeader label="Rating" sortKey="ai_rating" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip="Single-item AI quality rating (1-10) from Opus 4.6 Thinking." />}
          {showGapCol && !isMobile && !isTablet && <SortHeader label="Gap" sortKey="gap_score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip="Difference between tournament rank percentile and AI rating percentile. Positive = tournament ranks the paper higher than the AI rating suggests. Negative = AI rating is more optimistic than tournament performance. Measured in percentile points (e.g., -5.9 means the AI rates the paper ~6 percentile points higher than the tournament does)." />}
          {!isMobile && <SortHeader label="Published" sortKey="published" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={COLUMN_TIPS.published} />}
          {bookmarksMode && !isMobile && <SortHeader label="Saved" sortKey="bookmarked_at" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip="When you bookmarked this paper." />}
          {bookmarksMode && <div />}
          {!bookmarksMode && <div />}
        </div>
        {visibleList.map((paper, idx) => {
          const rowProps = paper._external_link && paper.link
            ? { as: "a", href: paper.link, target: "_blank", rel: "noopener noreferrer" }
            : { as: Link, to: `/paper/${paper.id}` };
          const RowTag = paper._external_link && paper.link ? "a" : Link;
          const rowLinkProps = paper._external_link && paper.link
            ? { href: paper.link, target: "_blank", rel: "noopener noreferrer" }
            : { to: `/paper/${paper.id}` };
          return (
          <RowTag
            key={paper.id || idx}
            {...rowLinkProps}
            className={`${gridBase} py-2 sm:py-3 items-center border-b border-slate-100 hover:bg-slate-50/70 transition-colors cursor-pointer`}
            style={gridStyle}
            data-testid={`leaderboard-row-${idx}`}
          >
            {bookmarksMode && selectedPapers && (
              <div className="flex items-center justify-center -m-2 p-2"
                onClickCapture={e => { e.preventDefault(); e.stopPropagation(); onToggleSelect?.(paper.id); }}
                onMouseDown={e => { e.preventDefault(); e.stopPropagation(); }}
              >
                <input type="checkbox" checked={selectedPapers.has(paper.id)} readOnly tabIndex={-1}
                  className="h-4 w-4 rounded border-border accent-accent pointer-events-none" />
              </div>
            )}
            <div>
              <RankBadge rank={scoreRankMap[paper.id] || paper._displayRank || paper.rank} />
            </div>
            <div className="min-w-0">
              {(() => {
                const m = paper.arxiv_id && /v(\d+)$/.exec(paper.arxiv_id);
                const v = m ? parseInt(m[1], 10) : (paper.current_version || 1);
                return (
                  <>
                    <p className="text-xs sm:text-sm font-medium leading-tight truncate" title={paper.title}>
                      <LatexTitle text={paper.title} />
                    </p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <p className="text-[10px] sm:text-xs text-muted-foreground truncate">
                        {paper.authors?.slice(0, 2).join(", ")}
                        {paper.authors?.length > 2 && ` +${paper.authors.length - 2}`}
                      </p>
                      {v > 1 && (
                        <span
                          className="shrink-0 text-[9px] sm:text-[10px] font-mono px-1 py-px rounded bg-amber-50 text-amber-700 border border-amber-200"
                          data-testid={`version-badge-${paper.id}`}
                          title={`Revised on arXiv — version ${v}`}
                        >
                          v{v}
                        </span>
                      )}
                      {paper.cited_by_count > 0 && (
                        <span
                          className="shrink-0 text-[9px] sm:text-[10px] px-1 py-px rounded bg-blue-50 text-blue-600 border border-blue-200"
                          title={`Cited by ${paper.cited_by_count} papers`}
                        >
                          {paper.cited_by_count} cited
                        </span>
                      )}
                    </div>
                  </>
                );
              })()}
            </div>
            {showCatCol && !isMobile && (
              <div className="text-center">
                <span className="inline-block text-[9px] px-1.5 py-0.5 rounded font-mono bg-secondary text-muted-foreground">{paper.primary_category || "?"}</span>
              </div>
            )}
            <div className="text-right text-xs sm:text-sm font-semibold tabular-nums">{getScore(paper) || "—"}</div>
            {!isMobile && !isTablet && <div className="text-right font-mono text-xs text-muted-foreground">
              {(() => { const wm = getWilsonMargin(paper); return wm != null && wm > 0 ? `\u00B1${Math.round(wm)}` : "—"; })()}
            </div>}
            {!isMobile && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground">{getComparisons(paper) != null ? getComparisons(paper) : "—"}</div>}
            {!isMobile && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground">{getWinRate(paper) != null ? `${getWinRate(paper)}%` : "—"}</div>}
            {showRatingCol && !isMobile && !isTablet && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground">{(typeof paper.ai_rating === "object" && paper.ai_rating ? paper.ai_rating.score : paper.ai_rating) || "—"}</div>}
            {showGapCol && !isMobile && !isTablet && (() => { const gap = paper.gap_score; return <div className={`text-right font-mono text-[10px] sm:text-xs ${gap > 0 ? "text-emerald-600" : gap < 0 ? "text-red-400" : "text-muted-foreground"}`}>{gap != null ? (gap > 0 ? "+" : "") + gap : "\u2014"}</div>; })()}
            {!isMobile && <div className="text-right text-xs text-muted-foreground">
              {paper.published ? new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "--"}
            </div>}
            {bookmarksMode && !isMobile && <div className="text-right text-xs text-muted-foreground">
              {paper.bookmarked_at ? new Date(paper.bookmarked_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "—"}
            </div>}
            {bookmarksMode && (
              <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); onRemoveBookmark?.(paper.id); }}
                className="flex items-center justify-center text-red-400 hover:text-red-600 transition-colors"
                title="Remove bookmark" data-testid={`remove-bm-${paper.id}`}>
                <X className="h-3.5 w-3.5" />
              </button>
            )}
            {!bookmarksMode && <BookmarkButton paperId={paper.id} bookmarkedIds={bookmarkedIds} onToggle={toggleBookmark} />}
          </RowTag>
        );
        })}
      </div>
      {/* Unified sentinel: triggers both progressive render and server page loads */}
      {hasMoreToShow && <div ref={sentinelRef} className="py-4 text-center text-xs text-muted-foreground">{loadingMore ? "Loading more..." : ""}</div>}
    </>
  );
}
