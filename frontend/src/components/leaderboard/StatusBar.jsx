import { Users, Swords, Activity, Tag, Globe } from "lucide-react";

export function StatusBar({ leaderboard, totalPapers, totalInPeriod, totalMatches, isRanking, hasSelectedTags, isTagMode, tagMode, selectedTags }) {
  const shownCount = leaderboard.length;
  const listTotal = totalInPeriod || totalPapers;
  return (
    <div className="flex items-center gap-3 mb-6 text-xs flex-wrap" data-testid="status-bar">
      <div className="flex items-center gap-1.5 text-muted-foreground shrink-0">
        <Users className="h-3.5 w-3.5" />
        <span className="font-mono">{shownCount}</span>
        <span>papers{shownCount < listTotal ? ` (${listTotal} total)` : ""}</span>
      </div>
      <div className="w-px h-3 bg-border shrink-0" />
      <div className="flex items-center gap-1.5 text-muted-foreground shrink-0">
        <Swords className="h-3.5 w-3.5" />
        <span className="font-mono">{totalMatches}</span>
        <span>matches</span>
      </div>
      {isRanking && (
        <>
          <div className="w-px h-3 bg-border shrink-0" />
          <span className="inline-flex items-center gap-1 text-xs text-accent animate-pulse shrink-0">
            <Activity className="h-3 w-3" /> Ranking in progress
          </span>
        </>
      )}
      {hasSelectedTags && (
        <>
          <div className="w-px h-3 bg-border shrink-0" />
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
            <Tag className="h-3 w-3" /> Cross-category {tagMode === "and" && selectedTags.length >= 2 ? "(AND)" : "(OR)"}
          </span>
        </>
      )}
      {isTagMode && !hasSelectedTags && (
        <>
          <div className="w-px h-3 bg-border shrink-0" />
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
            <Globe className="h-3 w-3" /> All categories
          </span>
        </>
      )}
    </div>
  );
}
