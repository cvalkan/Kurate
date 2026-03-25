import { useRef, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Trophy, ArrowUp, ArrowDown, X } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { RankBadge } from "./RankBadge";
import { BookmarkButton } from "@/components/BookmarkButton";
import { useBookmarks } from "@/contexts/BookmarkContext";

const COLUMN_TIPS = {
  rank: "Position based on win-rate score (higher = better). Click to restore default ranking.",
  title: "Paper title. Click to sort alphabetically.",
  score: "Win-rate score from pairwise comparisons. 1200 = average, higher = stronger.",
  score_g: "Win-rate score from ALL matches across all categories (pairwise win-rate). Reflects overall performance.",
  win_rate: "Percentage of head-to-head comparisons won within this set.",
  win_rate_g: "Win rate across ALL matches the paper has participated in, not just this filtered set.",
  wilson_margin: "95% Wilson confidence interval half-width. The interval is asymmetric \u2014 at 99% win rate, \u00B16% means the true rate is likely between 93\u2013100% (not 93\u2013105%). At extreme win rates the uncertainty is mostly one-sided because win rate can\u2019t exceed 100% or go below 0%. Lower margin = more matches played = more certainty.",
  comparisons: "Number of head-to-head LLM comparisons this paper has participated in within this set.",
  comparisons_g: "Total comparisons across ALL categories, including matches outside this filtered set.",
  published: "arXiv publication date.",
  community_likes: "AlphaXiv community likes \u2014 a popularity metric from alphaxiv.org. Higher = more community interest (not necessarily higher quality).",
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
}) {
  const sentinelRef = useRef(null);
  const { bookmarkedIds, toggleBookmark } = useBookmarks();

  // Progressive DOM rendering + server pagination via single sentinel
  const [renderCount, setRenderCount] = useState(100);

  // Reset on new data
  useEffect(() => { setRenderCount(100); }, [leaderboard]);

  // Single unified sentinel: handles both progressive render and server page loads
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        // If there are loaded entries not yet rendered: expand render window
        if (leaderboard.length > renderCount) {
          setRenderCount(prev => prev + 100);
        }
        // If all loaded entries are rendered and more pages exist: fetch next page
        else if (hasMore && onLoadMore && !loadingMore) {
          onLoadMore();
        }
      },
      { rootMargin: "400px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [leaderboard, renderCount, onLoadMore, hasMore, loadingMore]);

  const isGlobal = hasSelectedTags && globalStats;
  const getScore = (p) => isGlobal && p.global_score !== undefined ? p.global_score : p.score;
  const getWinRate = (p) => isGlobal && p.global_win_rate !== undefined ? p.global_win_rate : p.win_rate;
  const getComparisons = (p) => isGlobal && p.global_comparisons !== undefined ? p.global_comparisons : p.comparisons;
  const getWilsonMargin = (p) => isGlobal ? null : p.wilson_margin;

  // Re-rank by global score when Global toggle is active, then apply user sort
  const sorted = useMemo(() => {
    // Step 1: Re-rank by the active score metric
    let ranked;
    if (isGlobal) {
      ranked = [...leaderboard].sort((a, b) => (b.global_score || 0) - (a.global_score || 0));
      ranked.forEach((p, i) => { p._displayRank = i + 1; });
    } else {
      ranked = leaderboard.map(p => ({ ...p, _displayRank: p.rank }));
    }

    // Step 2: Apply user sort (if not default rank)
    if (!sortKey || sortKey === "rank") return ranked;
    const getValue = (p) => {
      switch (sortKey) {
        case "title": return p.title?.toLowerCase() || "";
        case "score": return getScore(p) || 0;
        case "win_rate": return getWinRate(p) || 0;
        case "wilson_margin": return getWilsonMargin(p) || 999;
        case "comparisons": return getComparisons(p) || 0;
        case "community_likes": return p.community_likes || 0;
        case "ai_rating": { const r = p.ai_rating; return (typeof r === "object" && r ? r.score : r) || 0; }
        case "gap_score": return p.gap_score || 0;
        case "published": return p.published || "";
        case "bookmarked_at": return p.bookmarked_at || "";
        default: return 0;
      }
    };
    const dir = sortDir === "asc" ? 1 : -1;
    return [...ranked].sort((a, b) => {
      const va = getValue(a), vb = getValue(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [leaderboard, sortKey, sortDir, isGlobal]); // eslint-disable-line react-hooks/exhaustive-deps

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
  if (!isMobile) cols.push("3.5rem"); // Win%
  if (!isMobile && !isTablet) cols.push("3.5rem"); // CI
  if (!isMobile) cols.push("3rem"); // Match
  if (showRatingCol && !isMobile && !isTablet) cols.push("3rem"); // Rating
  if (showGapCol && !isMobile && !isTablet) cols.push("3rem"); // Gap
  if (!isMobile) cols.push("5.5rem"); // Published
  if (bookmarksMode && !isMobile) cols.push("5.5rem"); // Bookmarked
  if (bookmarksMode) cols.push("1.5rem"); // Remove
  else cols.push("1.5rem"); // Bookmark icon
  const gridStyle = { gridTemplateColumns: cols.join(" ") };
  const gridBase = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

  const visibleList = sorted.slice(0, renderCount);
  const hasMoreToShow = hasMore || sorted.length > renderCount;

  const scoreLabel = "Score";
  const winLabel = "Win %";
  const matchLabel = "Match";

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
        <div className={`${gridBase} py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border select-none`} style={gridStyle}>
          {bookmarksMode && selectedPapers && <div />}
          <SortHeader label="#" sortKey="rank" currentSort={sortKey} currentDir={sortDir} onSort={onSort} tip={COLUMN_TIPS.rank} />
          <SortHeader label="Paper" sortKey="title" currentSort={sortKey} currentDir={sortDir} onSort={onSort} tip={COLUMN_TIPS.title} />
          {showCatCol && !isMobile && <div className="text-center">Cat</div>}
          <SortHeader label={isMobile ? "Score" : scoreLabel} sortKey="score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={isGlobal ? COLUMN_TIPS.score_g : COLUMN_TIPS.score} />
          {!isMobile && <SortHeader label={winLabel} sortKey="win_rate" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={isGlobal ? COLUMN_TIPS.win_rate_g : COLUMN_TIPS.win_rate} />}
          {!isMobile && !isTablet && <SortHeader label="95% CI" sortKey="wilson_margin" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={COLUMN_TIPS.wilson_margin} />}
          {!isMobile && <SortHeader label={matchLabel} sortKey="comparisons" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={isGlobal ? COLUMN_TIPS.comparisons_g : COLUMN_TIPS.comparisons} />}
          {showRatingCol && !isMobile && !isTablet && <SortHeader label="Rating" sortKey="ai_rating" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip="Single-item AI quality rating (1-10) from Opus 4.6 Thinking." />}
          {showGapCol && !isMobile && !isTablet && <SortHeader label="Gap" sortKey="gap_score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip="Tournament rank minus standalone rating rank. Positive = does better in competition." />}
          {!isMobile && <SortHeader label="Published" sortKey="published" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={COLUMN_TIPS.published} />}
          {bookmarksMode && !isMobile && <SortHeader label="Saved" sortKey="bookmarked_at" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip="When you bookmarked this paper." />}
          {bookmarksMode && <div />}
          {!bookmarksMode && <div />}
        </div>
        {visibleList.map((paper, idx) => (
          <Link
            key={paper.id}
            to={`/paper/${paper.id}`}
            className={`${gridBase} py-2 sm:py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${idx < 3 && !debouncedKeyword && (!sortKey || sortKey === "rank") ? "bg-accent/[0.02]" : ""}`}
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
            <div><RankBadge rank={paper._displayRank ?? paper.rank} /></div>
            <div className="min-w-0">
              <p className="text-xs sm:text-sm font-medium truncate leading-tight" title={paper.title}>{paper.title}</p>
              <p className="text-[10px] sm:text-xs text-muted-foreground truncate mt-0.5">
                {paper.authors?.slice(0, 2).join(", ")}
                {paper.authors?.length > 2 && ` +${paper.authors.length - 2}`}
              </p>
            </div>
            {showCatCol && !isMobile && (
              <div className="text-center">
                <span className="inline-block text-[9px] px-1.5 py-0.5 rounded font-mono bg-secondary text-muted-foreground">{paper.primary_category || "?"}</span>
              </div>
            )}
            <div className="text-right font-mono text-xs sm:text-sm font-medium">{getScore(paper) || "—"}</div>
            {!isMobile && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground">{getWinRate(paper) != null ? `${getWinRate(paper)}%` : "—"}</div>}
            {!isMobile && !isTablet && <div className="text-right font-mono text-xs text-muted-foreground">
              {(() => { const wm = getWilsonMargin(paper); return wm != null && wm > 0 ? `\u00B1${wm}%` : "—"; })()}
            </div>}
            {!isMobile && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground">{getComparisons(paper) != null ? getComparisons(paper) : "—"}</div>}
            {showRatingCol && !isMobile && !isTablet && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground">{(typeof paper.ai_rating === "object" && paper.ai_rating ? paper.ai_rating.score : paper.ai_rating) || "—"}</div>}
            {showGapCol && !isMobile && !isTablet && <div className={`text-right font-mono text-[10px] sm:text-xs ${paper.gap_score > 0 ? "text-emerald-600" : paper.gap_score < 0 ? "text-red-400" : "text-muted-foreground"}`}>{paper.gap_score != null ? (paper.gap_score > 0 ? "+" : "") + paper.gap_score : "—"}</div>}
            {!isMobile && <div className="text-right text-xs text-muted-foreground">
              {paper.published ? new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "--"}
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
          </Link>
        ))}
      </div>
      {/* Unified sentinel: triggers both progressive render and server page loads */}
      {hasMoreToShow && <div ref={sentinelRef} className="py-4 text-center text-xs text-muted-foreground">{loadingMore ? "Loading more..." : ""}</div>}
    </>
  );
}
