import { Bookmark } from "lucide-react";

export function BookmarkButton({ paperId, bookmarkedIds, onToggle, size = "sm" }) {
  const isBookmarked = bookmarkedIds?.has(paperId);
  const cls = size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4";

  return (
    <button
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggle(paperId); }}
      className={`inline-flex items-center justify-center rounded-md transition-colors hover:bg-secondary/50 p-1 ${isBookmarked ? "text-accent" : "text-muted-foreground/40 hover:text-muted-foreground"}`}
      title={isBookmarked ? "Remove bookmark" : "Bookmark paper"}
      data-testid={`bookmark-${paperId}`}
    >
      <Bookmark className={cls} fill={isBookmarked ? "currentColor" : "none"} />
    </button>
  );
}
