import { useRef, useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChevronDown, Lock, Lightbulb, Search } from "lucide-react";

export function CategoryTabs({
  categories, featured, category, setCategory, isTagMode, isLoggedIn,
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
    if (moreCatsOpen && searchRef.current && !("ontouchstart" in window)) {
      searchRef.current.focus();
    }
    if (!moreCatsOpen) setSearch("");
  }, [moreCatsOpen]);

  // Use featured list for tabs, rest goes to "More"
  const featuredSet = new Set(featured || []);
  const featuredCats = (featured || []).map(id => categories.find(c => c.id === id)).filter(Boolean);
  const overflowCats = categories.filter(c => !featuredSet.has(c.id));

  // Group overflow categories by their domain
  const groupedOverflow = useMemo(() => {
    const lc = search.toLowerCase();
    const filtered = lc
      ? overflowCats.filter(c => c.name.toLowerCase().includes(lc) || c.id.toLowerCase().includes(lc))
      : overflowCats;

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
  }, [overflowCats, search]);

  if (categories.length <= 1) return null;

  const selectCategory = (id) => {
    setCategory(id);
    setSelectedTags([]);
    setTagFilterOpen(false);
  };

  const overflowCount = overflowCats.length;

  return (
    <div className={`mb-3 transition-opacity ${isTagMode ? "opacity-40 pointer-events-none" : ""}`}>
      <div className="flex items-center gap-2 overflow-x-auto scrollbar-none pb-1" data-testid="category-tabs">
        {featuredCats.map((c) => (
          <button
            key={c.id}
            onClick={() => selectCategory(c.id)}
            className={`inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border transition-all shrink-0 ${
              !isTagMode && category === c.id
                ? "bg-blue-50 text-blue-700 border-blue-200"
                : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
            } ${isTagMode ? "opacity-40 pointer-events-none" : ""}`}
            data-testid={`cat-${c.id}`}
            disabled={isTagMode}
          >
            {c.name}
          </button>
        ))}
        {overflowCats.length > 0 && (
          <div className="relative shrink-0" ref={moreCatsRef}>
            {isLoggedIn ? (
              <button
                onClick={() => setMoreCatsOpen(v => !v)}
                disabled={isTagMode}
                className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border transition-all shrink-0 ${
                  !isTagMode && overflowCats.some(c => c.id === category)
                    ? "bg-blue-50 text-blue-700 border-blue-200"
                    : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
                } ${isTagMode ? "opacity-40" : ""}`}
                data-testid="more-categories-btn"
              >
                {overflowCats.find(c => c.id === category)?.name || `More`}
                <ChevronDown className={`h-3 w-3 transition-transform ${moreCatsOpen ? "rotate-180" : ""}`} />
              </button>
            ) : (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button onClick={requireAuth} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border border-slate-200 text-slate-400 shrink-0" data-testid="more-categories-btn-locked">
                    <Lock className="h-3 w-3" /> More <ChevronDown className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent><p className="text-xs">Sign in for free to access more categories</p></TooltipContent>
              </Tooltip>
            )}
            {moreCatsOpen && isLoggedIn && (
              <div
                className="fixed z-50 bg-white border border-slate-200 rounded-sm shadow-lg py-1"
                style={{
                  top: moreCatsRef.current?.getBoundingClientRect().bottom + 4,
                  left: Math.max(8, Math.min(
                    moreCatsRef.current?.getBoundingClientRect().left || 0,
                    window.innerWidth - 308
                  )),
                  width: Math.min(300, window.innerWidth - 16),
                  maxHeight: "min(420px, 60vh)",
                  overflowY: "auto",
                }}
                data-testid="more-categories-dropdown"
              >
                {/* Search filter */}
                {overflowCount > 6 && (
                  <div className="px-2 py-1.5 border-b border-slate-100 sticky top-0 bg-white z-10">
                    <div className="relative">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                      <input
                        ref={searchRef}
                        type="text"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Filter categories..."
                        className="w-full pl-8 pr-3 py-1.5 text-sm border border-slate-200 rounded-sm focus:outline-none focus:ring-1 focus:ring-blue-600 bg-white"
                        data-testid="category-search-input"
                      />
                    </div>
                  </div>
                )}
                {/* Grouped category list */}
                {groupedOverflow.groupOrder.length === 0 && (
                  <div className="px-3 py-3 text-xs text-slate-400 text-center">No matching categories</div>
                )}
                {groupedOverflow.groupOrder.map((group) => (
                  <div key={group}>
                    <div className="px-3 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 select-none" data-testid={`group-${group}`}>
                      {group}
                    </div>
                    {groupedOverflow.groups[group].map((c) => (
                      <button
                        key={c.id}
                        className={`w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 transition-colors flex items-center gap-2 ${category === c.id ? "bg-blue-50 text-blue-700 font-medium" : ""}`}
                        onClick={() => { selectCategory(c.id); setMoreCatsOpen(false); }}
                        data-testid={`cat-${c.id}`}
                      >
                        <span className="font-mono text-blue-600 text-xs">{c.id}</span>
                        <span className="text-slate-700">{c.name}</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="w-px h-5 bg-slate-200 mx-1 shrink-0" />
        <Tooltip>
          <TooltipTrigger asChild>
            <button onClick={onSuggest} className="inline-flex items-center gap-1 text-xs px-3 py-1.5 shrink-0 text-slate-500 hover:text-slate-900 hover:bg-slate-50 rounded-full border border-transparent hover:border-slate-200 transition-colors" data-testid="suggest-field-btn">
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
