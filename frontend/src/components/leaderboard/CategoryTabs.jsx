import { useRef, useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChevronDown, Lock, Lightbulb, Search } from "lucide-react";

export function CategoryTabs({
  categories, category, setCategory, isTagMode, isLoggedIn,
  requireAuth, setSelectedTags, setTagFilterOpen, onSuggest,
}) {
  const [moreCatsOpen, setMoreCatsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const moreCatsRef = useRef(null);
  const searchRef = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (moreCatsRef.current && !moreCatsRef.current.contains(e.target)) setMoreCatsOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (moreCatsOpen && searchRef.current) {
      searchRef.current.focus();
    }
    if (!moreCatsOpen) setSearch("");
  }, [moreCatsOpen]);

  // Group overflow categories by their domain
  const groupedOverflow = useMemo(() => {
    const overflow = categories.slice(5);
    const lc = search.toLowerCase();
    const filtered = lc
      ? overflow.filter(c => c.name.toLowerCase().includes(lc) || c.id.toLowerCase().includes(lc))
      : overflow;

    const groups = {};
    const groupOrder = [];
    for (const c of filtered) {
      const g = c.group || "Other";
      if (!groups[g]) {
        groups[g] = [];
        groupOrder.push(g);
      }
      groups[g].push(c);
    }
    return { groups, groupOrder };
  }, [categories, search]);

  if (categories.length <= 1) return null;

  const selectCategory = (id) => {
    setCategory(id);
    setSelectedTags([]);
    setTagFilterOpen(false);
  };

  const overflowCount = categories.length - 5;

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
                {categories.slice(5).find(c => c.id === category)?.name || `More (${overflowCount})`}
                <ChevronDown className={`h-3 w-3 transition-transform ${moreCatsOpen ? "rotate-180" : ""}`} />
              </Button>
            ) : (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="sm" className="text-xs h-8 gap-1 shrink-0 opacity-50" onClick={requireAuth} data-testid="more-categories-btn-locked">
                    <Lock className="h-3 w-3" /> More <ChevronDown className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent><p className="text-xs">Sign in for free to access more categories</p></TooltipContent>
              </Tooltip>
            )}
            {moreCatsOpen && isLoggedIn && (
              <div
                className="fixed z-50 bg-background border border-border rounded-lg shadow-lg w-[300px] py-1"
                style={{
                  top: moreCatsRef.current?.getBoundingClientRect().bottom + 4,
                  left: Math.min(
                    moreCatsRef.current?.getBoundingClientRect().left || 0,
                    window.innerWidth - 440
                  ),
                  maxHeight: "min(420px, 60vh)",
                  overflowY: "auto",
                }}
                data-testid="more-categories-dropdown"
              >
                {/* Search filter */}
                {overflowCount > 6 && (
                  <div className="px-2 py-1.5 border-b border-border/50 sticky top-0 bg-background z-10">
                    <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-muted/50">
                      <Search className="h-3 w-3 text-muted-foreground shrink-0" />
                      <input
                        ref={searchRef}
                        type="text"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Filter categories..."
                        className="bg-transparent text-xs outline-none w-full placeholder:text-muted-foreground/60"
                        data-testid="category-search-input"
                      />
                    </div>
                  </div>
                )}
                {/* Grouped category list */}
                {groupedOverflow.groupOrder.length === 0 && (
                  <div className="px-3 py-3 text-xs text-muted-foreground text-center">No matching categories</div>
                )}
                {groupedOverflow.groupOrder.map((group) => (
                  <div key={group}>
                    <div className="px-3 pt-3 pb-1 text-xs font-extrabold uppercase tracking-wide text-foreground/80 select-none" data-testid={`group-${group}`}>
                      {group}
                    </div>
                    {groupedOverflow.groups[group].map((c) => (
                      <button
                        key={c.id}
                        className={`w-full text-left px-3 py-1.5 text-sm hover:bg-accent/10 transition-colors whitespace-nowrap ${category === c.id ? "bg-accent/10 text-accent font-medium" : ""}`}
                        onClick={() => { selectCategory(c.id); setMoreCatsOpen(false); }}
                        data-testid={`cat-${c.id}`}
                      >
                        <span className="font-mono text-[11px] text-muted-foreground mr-2">{c.id}</span>
                        {c.name}
                      </button>
                    ))}
                  </div>
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
          <TooltipContent side="bottom"><p className="text-xs">{isLoggedIn ? "Suggest a new field or share feedback" : "Sign in for free to suggest a field"}</p></TooltipContent>
        </Tooltip>
      </div>
      {isTagMode && <p className="text-[10px] text-muted-foreground mt-1 ml-1">Category tabs disabled while tag filter is active</p>}
    </div>
  );
}
