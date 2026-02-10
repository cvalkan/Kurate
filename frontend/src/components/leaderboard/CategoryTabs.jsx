import { useRef, useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChevronDown, Lock, Lightbulb } from "lucide-react";

export function CategoryTabs({
  categories, category, setCategory, isTagMode, isLoggedIn,
  requireAuth, setSelectedTags, setTagFilterOpen, onSuggest,
}) {
  const [moreCatsOpen, setMoreCatsOpen] = useState(false);
  const moreCatsRef = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (moreCatsRef.current && !moreCatsRef.current.contains(e.target)) setMoreCatsOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (categories.length <= 1) return null;

  const selectCategory = (id) => {
    setCategory(id);
    setSelectedTags([]);
    setTagFilterOpen(false);
  };

  return (
    <div className={`mb-3 transition-opacity ${isTagMode ? "opacity-40 pointer-events-none" : ""}`}>
      <div className="flex items-center gap-1 p-1 bg-primary/5 rounded-lg overflow-x-auto scrollbar-none" data-testid="category-tabs">
        {categories.slice(0, 5).map((c) => (
          <Button
            key={c.id}
            variant={!isTagMode && category === c.id ? "default" : "ghost"}
            size="sm"
            onClick={() => selectCategory(c.id)}
            className="text-xs h-8 shrink-0"
            data-testid={`cat-${c.id}`}
            disabled={isTagMode}
          >
            {c.name}
          </Button>
        ))}
        {categories.length > 5 && (
          <div className="relative shrink-0" ref={moreCatsRef}>
            {isLoggedIn ? (
              <Button
                variant={!isTagMode && categories.slice(5).some(c => c.id === category) ? "default" : "ghost"}
                size="sm"
                className="text-xs h-8 gap-1 shrink-0"
                onClick={() => setMoreCatsOpen(v => !v)}
                disabled={isTagMode}
                data-testid="more-categories-btn"
              >
                {categories.slice(5).find(c => c.id === category)?.name || "More"}
                <ChevronDown className={`h-3 w-3 transition-transform ${moreCatsOpen ? "rotate-180" : ""}`} />
              </Button>
            ) : (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="sm" className="text-xs h-8 gap-1 shrink-0 opacity-50" onClick={requireAuth} data-testid="more-categories-btn-locked">
                    <Lock className="h-3 w-3" /> More <ChevronDown className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent><p className="text-xs">Sign in to access more categories</p></TooltipContent>
              </Tooltip>
            )}
            {moreCatsOpen && isLoggedIn && (
              <div className="fixed z-50 bg-background border border-border rounded-lg shadow-lg min-w-48 py-1" style={{ top: moreCatsRef.current?.getBoundingClientRect().bottom + 4, left: moreCatsRef.current?.getBoundingClientRect().left }} data-testid="more-categories-dropdown">
                {categories.slice(5).map((c) => (
                  <button
                    key={c.id}
                    className={`w-full text-left px-3 py-1.5 text-sm hover:bg-accent/10 transition-colors ${category === c.id ? "bg-accent/10 text-accent font-medium" : ""}`}
                    onClick={() => { selectCategory(c.id); setMoreCatsOpen(false); }}
                    data-testid={`cat-${c.id}`}
                  >
                    <span className="font-mono text-[11px] text-muted-foreground mr-2">{c.id}</span>
                    {c.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="w-px h-5 bg-border mx-0.5" />
        <Tooltip>
          <TooltipTrigger asChild>
            <button onClick={onSuggest} className="inline-flex items-center gap-1 text-xs h-8 px-3 shrink-0 text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-md transition-colors" data-testid="suggest-field-btn">
              <Lightbulb className="h-3.5 w-3.5" /><span>Suggest</span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom"><p className="text-xs">{isLoggedIn ? "Suggest a new field or share feedback" : "Sign in to suggest a field"}</p></TooltipContent>
        </Tooltip>
      </div>
      {isTagMode && <p className="text-[10px] text-muted-foreground mt-1 ml-1">Category tabs disabled while tag filter is active</p>}
    </div>
  );
}
