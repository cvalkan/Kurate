import { useRef, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { Trophy, ArrowUp, ArrowDown } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { RankBadge } from "./RankBadge";

const COLUMN_TIPS = {
  rank: "Position based on Elo score (higher = better). Click to restore default ranking.",
  title: "Paper title. Click to sort alphabetically.",
  score: "Elo-style rating from Bradley-Terry model. 1200 = average, higher = stronger.",
  score_g: "Elo score from ALL matches across all categories (Bradley-Terry). Reflects overall performance.",
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
  debouncedKeyword, keyword, displayCount, setDisplayCount,
  sortKey, sortDir, onSort, showRatingCol = true, showGapCol = true,
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
        case "ai_rating": return p.ai_rating || 0;
        case "sp_score": return p.sp_score || 0;
        case "published": return p.published || "";
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

  // Dynamic grid: base columns + optional Rating + Gap
  const extraCols = (showRatingCol ? 1 : 0) + (showGapCol ? 1 : 0);
  const gridCls = showCatCol
    ? `grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4rem_4.5rem_4rem_4rem_4rem${showRatingCol ? "_3rem" : ""}${showGapCol ? "_3rem" : ""}] md:grid-cols-[3rem_1fr_4.5rem_5rem_4.5rem_4.5rem_4rem${showRatingCol ? "_3rem" : ""}${showGapCol ? "_3rem" : ""}_7rem]`
    : `grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem${showRatingCol ? "_3rem" : ""}${showGapCol ? "_3rem" : ""}] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem${showRatingCol ? "_3rem" : ""}${showGapCol ? "_3rem" : ""}_7rem]`;

  const visibleList = sorted.slice(0, displayCount);
  const hasMore = sorted.length > visibleList.length;

  const scoreLabel = isGlobal ? "Score (G)" : "Score";
  const winLabel = isGlobal ? "Win % (G)" : "Win %";
  const matchLabel = isGlobal ? "Mtch (G)" : "Match";

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
          <SortHeader label="#" sortKey="rank" currentSort={sortKey} currentDir={sortDir} onSort={onSort} tip={COLUMN_TIPS.rank} />
          <SortHeader label="Paper" sortKey="title" currentSort={sortKey} currentDir={sortDir} onSort={onSort} tip={COLUMN_TIPS.title} />
          {showCatCol && <div className="text-center hidden sm:block">Cat</div>}
          <SortHeader label={scoreLabel} sortKey="score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end" tip={isGlobal ? COLUMN_TIPS.score_g : COLUMN_TIPS.score} />
          <SortHeader label={winLabel} sortKey="win_rate" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden sm:flex" tip={isGlobal ? COLUMN_TIPS.win_rate_g : COLUMN_TIPS.win_rate} />
          <SortHeader label="95% CI" sortKey="wilson_margin" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden sm:flex" tip={COLUMN_TIPS.wilson_margin} />
          <SortHeader label={matchLabel} sortKey="comparisons" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden sm:flex" tip={isGlobal ? COLUMN_TIPS.comparisons_g : COLUMN_TIPS.comparisons} />
          <SortHeader label="Rating" sortKey="ai_rating" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className={`justify-end hidden ${showRatingCol ? "sm:flex" : "!hidden"}`} tip="Single-item AI quality rating (1-10) from Opus 4.6 Thinking. Based on significance, rigor, novelty, and clarity." />
          <SortHeader label="Gap" sortKey="sp_score" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className={`justify-end hidden ${showGapCol ? "sm:flex" : "!hidden"}`} tip="Tournament rank minus standalone score rank. Positive = paper does better in competition than its standalone score suggests. Negative = paper looks better on paper than in head-to-head." />
          <SortHeader label="Published" sortKey="published" currentSort={sortKey} currentDir={sortDir} onSort={onSort} className="justify-end hidden md:flex" tip={COLUMN_TIPS.published} />
        </div>
        {visibleList.map((paper, idx) => (
          <Link
            key={paper.id}
            to={`/paper/${paper.id}`}
            className={`grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4 py-2 sm:py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${gridCls} ${idx < 3 && !debouncedKeyword && (!sortKey || sortKey === "rank") ? "bg-accent/[0.02]" : ""}`}
            data-testid={`leaderboard-row-${idx}`}
          >
            <div><RankBadge rank={paper._displayRank ?? paper.rank} /></div>
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
            {showRatingCol && <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground hidden sm:block">{paper.ai_rating || "—"}</div>}
            {showGapCol && <div className={`text-right font-mono text-[10px] sm:text-xs hidden sm:block ${paper.sp_score > 0 ? "text-emerald-600" : paper.sp_score < 0 ? "text-red-400" : "text-muted-foreground"}`}>{paper.sp_score != null ? (paper.sp_score > 0 ? "+" : "") + paper.sp_score : "—"}</div>}
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
