import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Tag, X, ChevronDown, ChevronUp, HelpCircle, Lock } from "lucide-react";

export function TagFilter({
  allTags, selectedTags, setSelectedTags, tagMode, setTagMode,
  tagFilterOpen, setTagFilterOpen, isLoggedIn, requireAuth,
  globalStats, setGlobalStats,
}) {
  const [tagSearch, setTagSearch] = useState("");

  const toggleTag = (tagId) => {
    setSelectedTags(prev => prev.includes(tagId) ? prev.filter(t => t !== tagId) : [...prev, tagId]);
  };

  const clearTags = () => {
    setSelectedTags([]);
    setTagFilterOpen(false);
    setTagSearch("");
    setGlobalStats(false);
  };

  const filteredTags = allTags.filter(t => !tagSearch || t.id.toLowerCase().includes(tagSearch.toLowerCase()));

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 flex-wrap">
        {isLoggedIn ? (
          <Button variant={tagFilterOpen ? "default" : "outline"} size="sm" onClick={() => setTagFilterOpen(!tagFilterOpen)} className="gap-1.5 text-xs h-7" data-testid="tag-filter-toggle">
            <Tag className="h-3 w-3" /> Filter by tags {tagFilterOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </Button>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="sm" onClick={requireAuth} className="gap-1.5 text-xs h-7 opacity-50" data-testid="tag-filter-toggle-locked">
                <Lock className="h-3 w-3" /> Filter by tags
              </Button>
            </TooltipTrigger>
            <TooltipContent><p className="text-xs">Sign in for free to filter by tags</p></TooltipContent>
          </Tooltip>
        )}
        <Tooltip>
          <TooltipTrigger asChild><HelpCircle className="h-3.5 w-3.5 text-muted-foreground cursor-help" /></TooltipTrigger>
          <TooltipContent side="right" className="max-w-xs"><p className="text-xs">Papers have multiple arXiv category tags (primary + secondary). Use this to view papers across categories. Select multiple tags and choose AND (intersection) or OR (union).</p></TooltipContent>
        </Tooltip>

        {selectedTags.length >= 2 && (
          <div className="flex items-center gap-0.5 p-0.5 bg-secondary/50 rounded-md">
            <button onClick={() => setTagMode("or")} className={`px-2 py-0.5 text-[11px] rounded font-medium transition-colors ${tagMode === "or" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>OR</button>
            <button onClick={() => setTagMode("and")} className={`px-2 py-0.5 text-[11px] rounded font-medium transition-colors ${tagMode === "and" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>AND</button>
          </div>
        )}

        {selectedTags.map(tag => (
          <Badge key={tag} variant="secondary" className="gap-1 text-xs cursor-pointer hover:bg-destructive/10" onClick={() => toggleTag(tag)}>
            {tag} <X className="h-3 w-3" />
          </Badge>
        ))}
        {(selectedTags.length > 0 || tagFilterOpen) && (
          <button onClick={clearTags} className="text-xs text-muted-foreground hover:text-foreground underline">
            {selectedTags.length > 0 ? "Clear all" : "Close"}
          </button>
        )}
      </div>

      {tagFilterOpen && (
        <div className="mt-2 p-3 bg-secondary/30 border border-border rounded-lg" data-testid="tag-panel">
          <Input placeholder="Search tags (e.g. cs.AI, physics)..." value={tagSearch} onChange={e => setTagSearch(e.target.value)} className="h-8 text-xs mb-2 max-w-xs" />
          <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
            {filteredTags.map(tag => {
              const isSelected = selectedTags.includes(tag.id);
              const matchCount = tag.matches || 0;
              return (
                <button key={tag.id} onClick={() => toggleTag(tag.id)} className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition-colors ${isSelected ? "bg-primary text-primary-foreground border-primary" : "bg-background text-muted-foreground border-border hover:bg-secondary"}`} title={`${tag.count} papers, ${matchCount} matches`}>
                  {tag.id}
                  <span className={`font-mono text-[10px] ${isSelected ? "text-primary-foreground/70" : "text-muted-foreground/60"}`}>{tag.count}</span>
                  {matchCount > 0 && <span className={`font-mono text-[9px] ${isSelected ? "text-primary-foreground/50" : "text-muted-foreground/40"}`}>({matchCount})</span>}
                </button>
              );
            })}
            {filteredTags.length === 0 && <span className="text-xs text-muted-foreground">No matching tags</span>}
          </div>
        </div>
      )}
    </div>
  );
}
